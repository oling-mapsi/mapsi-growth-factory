from app.core.config import get_settings

from tests.integration.test_operations_api import auth_headers


def create_campaign_with_linkedin_asset(client) -> tuple[str, str]:
    created = client.post(
        "/campaigns",
        headers=auth_headers(),
        json={
            "name": "LinkedIn Weekly",
            "objective": "notoriety",
            "audience": {"name": "Prospects", "description": "Prospects"},
        },
    )
    campaign_id = created.json()["id"]
    client.post(f"/campaigns/{campaign_id}/generate", headers=auth_headers())
    client.post(
        f"/campaigns/{campaign_id}/approve",
        headers=auth_headers(),
        json={"decided_by": "approver", "comment": "ok"},
    )
    campaign = client.get(f"/campaigns/{campaign_id}", headers=auth_headers()).json()
    asset_id = next(item["id"] for item in campaign["content_assets"] if item["channel"] == "linkedin")
    return campaign_id, asset_id


def test_linkedin_oauth_exchange_publish_and_collect_metrics(client) -> None:
    settings = get_settings()
    settings.linkedin_access_token = ""
    exchange = client.post(
        "/ops/linkedin/oauth/exchange",
        headers={**auth_headers(), "Idempotency-Key": "linkedin-oauth-1"},
        json={"correlation_id": "corr-li-1", "dry_run": False, "code": "mock-code"},
    )
    assert exchange.status_code == 200
    assert exchange.json()["details"]["organization"]["urn"] == "urn:li:organization:3347696"

    campaign_id, asset_id = create_campaign_with_linkedin_asset(client)

    publish = client.post(
        f"/ops/campaigns/{campaign_id}/linkedin-publish",
        headers={**auth_headers(), "Idempotency-Key": "linkedin-publish-1"},
        json={"correlation_id": "corr-li-2", "dry_run": False, "asset_id": asset_id},
    )
    assert publish.status_code == 200
    assert publish.json()["details"]["status"] == "published"

    collect = client.post(
        f"/ops/campaigns/{campaign_id}/linkedin-metrics",
        headers={**auth_headers(), "Idempotency-Key": "linkedin-metrics-1"},
        json={"correlation_id": "corr-li-3", "dry_run": False},
    )
    assert collect.status_code == 200
    assert collect.json()["details"]["collected"] == 1


def test_linkedin_publish_is_idempotent_via_api(client) -> None:
    client.post(
        "/ops/linkedin/oauth/exchange",
        headers={**auth_headers(), "Idempotency-Key": "linkedin-oauth-2"},
        json={"correlation_id": "corr-li-4", "dry_run": False, "code": "mock-code-2"},
    )
    campaign_id, asset_id = create_campaign_with_linkedin_asset(client)
    payload = {"correlation_id": "corr-li-5", "dry_run": False, "asset_id": asset_id}

    first = client.post(
        f"/ops/campaigns/{campaign_id}/linkedin-publish",
        headers={**auth_headers(), "Idempotency-Key": "linkedin-publish-2"},
        json=payload,
    )
    second = client.post(
        f"/ops/campaigns/{campaign_id}/linkedin-publish",
        headers={**auth_headers(), "Idempotency-Key": "linkedin-publish-2"},
        json=payload,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
