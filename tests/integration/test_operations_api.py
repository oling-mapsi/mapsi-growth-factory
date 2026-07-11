from datetime import UTC, datetime, timedelta

from app.core.config import get_settings
from app.domain.errors import EditorialGenerationBlockedError
from app.entrypoints.api.dependencies import get_weekly_campaign_generation_service


def auth_headers() -> dict[str, str]:
    return {"X-API-Key": "test-key"}


def review_auth_headers() -> dict[str, str]:
    import base64

    token = base64.b64encode(b"admin:change-me-review-password").decode("ascii")
    return {"Authorization": f"Basic {token}"}


def create_generated_campaign(client) -> str:
    created = client.post(
        "/campaigns",
        headers=auth_headers(),
        json={
            "name": "Weekly rollout",
            "objective": "feature_adoption",
            "audience": {"name": "Admins", "description": "All admins"},
        },
    )
    campaign_id = created.json()["id"]
    client.post(f"/campaigns/{campaign_id}/generate", headers=auth_headers())
    client.post(
        f"/campaigns/{campaign_id}/approve",
        headers=auth_headers(),
        json={"decided_by": "approver", "comment": "ok"},
    )
    return campaign_id


def test_request_approval_and_publish_ready_campaign(client) -> None:
    campaign_id = create_generated_campaign(client)
    request_approval = client.post(
        f"/ops/campaigns/{campaign_id}/request-approval",
        headers={**auth_headers(), "Idempotency-Key": "ops-approval-1"},
        json={"correlation_id": "corr-1", "dry_run": False},
    )
    assert request_approval.status_code == 200
    review_url = request_approval.json()["details"]["review_url"]

    approve_review = client.post(f"{review_url}/approve", headers=review_auth_headers())
    assert approve_review.status_code == 200

    readiness = client.get(
        f"/ops/campaigns/{campaign_id}/publication-readiness",
        headers=auth_headers(),
        params={"correlation_id": "corr-1", "scheduled_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()},
    )
    assert readiness.status_code == 200
    assert readiness.json()["details"]["publishable"] is True

    publish = client.post(
        f"/ops/campaigns/{campaign_id}/publish-approved",
        headers={**auth_headers(), "Idempotency-Key": "ops-publish-1"},
        json={
            "correlation_id": "corr-1",
            "dry_run": False,
            "scheduled_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "channels": ["linkedin", "oling"],
        },
    )
    assert publish.status_code == 200
    assert publish.json()["details"]["published_channels"] == ["linkedin", "oling"]


def test_publication_readiness_blocks_when_kill_switch_enabled(client, monkeypatch) -> None:
    campaign_id = create_generated_campaign(client)
    approval = client.post(
        f"/ops/campaigns/{campaign_id}/request-approval",
        headers={**auth_headers(), "Idempotency-Key": "ops-approval-2"},
        json={"correlation_id": "corr-2", "dry_run": False},
    )
    review_url = approval.json()["details"]["review_url"]
    client.post(f"{review_url}/approve", headers=review_auth_headers())

    monkeypatch.setenv("WORKFLOW_KILL_SWITCH", "true")
    get_settings.cache_clear()
    readiness = client.get(
        f"/ops/campaigns/{campaign_id}/publication-readiness",
        headers=auth_headers(),
        params={"correlation_id": "corr-2", "scheduled_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()},
    )
    assert readiness.status_code == 200
    assert readiness.json()["details"]["kill_switch_disabled"] is False
    assert readiness.json()["details"]["publishable"] is False
    monkeypatch.delenv("WORKFLOW_KILL_SWITCH", raising=False)
    get_settings.cache_clear()


def test_generate_weekly_campaign_returns_conflict_when_no_product_changes(client) -> None:
    class BlockedWeeklyCampaignGenerationService:
        def generate(self, dry_run: bool = True) -> dict:
            raise EditorialGenerationBlockedError("No communicable product changes available.")

    client.app.dependency_overrides[get_weekly_campaign_generation_service] = lambda: BlockedWeeklyCampaignGenerationService()
    try:
        response = client.post(
            "/ops/generate-weekly-campaign",
            headers={**auth_headers(), "Idempotency-Key": "ops-weekly-1"},
            json={"correlation_id": "corr-weekly-1", "dry_run": True},
        )
    finally:
        client.app.dependency_overrides.pop(get_weekly_campaign_generation_service, None)

    assert response.status_code == 409
    assert response.json()["detail"] == "No communicable product changes available."
