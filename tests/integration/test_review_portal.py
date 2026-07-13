import base64
from datetime import UTC, datetime, timedelta

from app.application.services.review_portal_service import ReviewPortalService
from app.core.security import hash_review_token
from app.domain.entities import AudienceSegment, CampaignReview, CampaignRun, ContentAsset, Publication, SourceEvidence
from app.domain.enums import AssetStatus, CampaignStatus
from app.infrastructure.db.models import ReviewTokenModel
from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
from app.infrastructure.repositories.review_portal import ReviewPortalRepository


def auth_headers(username: str = "admin", password: str = "change-me-review-password") -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}", "X-API-Key": "test-key"}


def seed_review(session, *, campaign_status=CampaignStatus.APPROVED, published: bool = False) -> tuple[CampaignRun, CampaignReview, str]:
    campaigns = SqlAlchemyCampaignRepository(session)
    audit = SqlAlchemyAuditLogRepository(session)
    portal = ReviewPortalService(campaigns, ReviewPortalRepository(session), audit)
    campaign = CampaignRun(name="Weekly", objective="feature_adoption", status=campaign_status)
    campaign.audience_segments.append(AudienceSegment(campaign_run_id=campaign.id, name="risk_managers", description="Risk managers"))
    campaign.content_assets.append(
        ContentAsset(
            campaign_run_id=campaign.id,
            asset_type="email_sequence",
            channel="mautic",
            title="Weekly mail",
            body="<p>Hello</p>",
            status=AssetStatus.APPROVED,
        )
    )
    campaign.source_evidences.append(SourceEvidence(campaign_run_id=campaign.id, source_system="github", reference="evidence-1"))
    if published:
        campaign.publications.append(Publication(campaign_run_id=campaign.id, channel="oling", external_reference="oling:1"))
    campaigns.add(campaign)
    review = CampaignReview(
        campaign_run_id=campaign.id,
        theme="Theme",
        objective="feature_adoption",
        segment_id="risk_managers",
        segment_label="Risk managers",
        audience_volume=42,
        exclusions={"opted_out": 2},
        evidence_ids=["evidence-1"],
        email_subject="Subject",
        email_preheader="Preheader",
        email_html="<p>Hello</p>",
        email_text="Hello",
        quality_control={"passed": True, "issues": []},
        proposed_at=datetime.now(UTC),
    )
    saved = portal.review_repository.save_review(review)
    token = portal.create_review_token(saved.id)
    return campaign, saved, token


def test_review_portal_requires_authorized_user(client, session) -> None:
    _, _, token = seed_review(session)

    response = client.get(f"/review/{token}")

    assert response.status_code == 401


def test_modification_after_validation_blocks_publication(client, session) -> None:
    campaign, _, token = seed_review(session)
    response = client.post(f"/review/{token}/approve", headers=auth_headers("admin", "change-me-review-password"))
    assert response.status_code == 200

    response = client.post(
        f"/review/{token}/edit",
        data={
            "email_subject": "Changed",
            "email_preheader": "Preheader",
            "email_html": "<p>Changed</p>",
            "email_text": "Changed",
        },
        headers=auth_headers("admin", "change-me-review-password"),
    )
    assert response.status_code == 200

    publish = client.post(
        f"/campaigns/{campaign.id}/publish",
        json={"channel": "oling"},
        headers=auth_headers(),
    )

    assert publish.status_code == 409


def test_approval_expired_token(client, session) -> None:
    _, _, token = seed_review(session)
    repository = ReviewPortalRepository(session)
    token_row = repository.get_token(hash_review_token(token))
    model = session.get(ReviewTokenModel, token_row.id)
    model.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    session.commit()

    response = client.post(f"/review/{token}/approve", headers=auth_headers("admin", "change-me-review-password"))

    assert response.status_code == 409


def test_double_approval_is_blocked(client, session) -> None:
    _, _, token = seed_review(session)
    first = client.post(f"/review/{token}/approve", headers=auth_headers("admin", "change-me-review-password"))
    second = client.post(f"/review/{token}/approve", headers=auth_headers("admin", "change-me-review-password"))

    assert first.status_code == 200
    assert second.status_code == 409


def test_campaign_already_sent_blocks_review_actions(client, session) -> None:
    _, _, token = seed_review(session, published=True)

    response = client.post(
        f"/review/{token}/edit",
        data={
            "email_subject": "Changed",
            "email_preheader": "Preheader",
            "email_html": "<p>Changed</p>",
            "email_text": "Changed",
        },
        headers=auth_headers("admin", "change-me-review-password"),
    )

    assert response.status_code == 409


def test_review_portal_readonly_keeps_consultation_and_redirects_writes_to_studio(client, session, monkeypatch) -> None:
    _, _, token = seed_review(session)
    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "review_portal_mode", "readonly")
    monkeypatch.setattr(settings, "review_portal_studio_url", "https://studio.mapsi.test/growth")

    view = client.get(f"/review/{token}", headers=auth_headers())
    edit = client.post(
        f"/review/{token}/approve",
        headers=auth_headers(),
        follow_redirects=False,
    )

    assert view.status_code == 200
    assert "Lecture seule" in view.text
    assert "disabled" in view.text
    assert edit.status_code == 303
    assert edit.headers["location"] == "https://studio.mapsi.test/growth"


def test_review_portal_emergency_only_requires_allowlist_and_emergency_key(client, session, monkeypatch) -> None:
    campaign, _, token = seed_review(session)
    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "review_portal_mode", "emergency-only")
    monkeypatch.setattr(settings, "review_portal_emergency_allowlist", "admin")
    monkeypatch.setattr(settings, "review_portal_emergency_key", "emergency-secret")

    denied = client.get(f"/review/{token}", headers=auth_headers("admin"))
    allowed = client.get(
        f"/review/{token}",
        headers={**auth_headers("admin"), "X-Review-Emergency-Key": "emergency-secret"},
    )

    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert "Emergency access only" in allowed.text
    latest = SqlAlchemyAuditLogRepository(session).latest_event_for_campaign(campaign.id)
    assert latest is not None
    assert latest.event_type == "review.portal_emergency_access_granted"


def test_review_portal_disabled_shows_moved_page_and_blocks_decisions(client, session, monkeypatch) -> None:
    _, _, token = seed_review(session)
    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "review_portal_mode", "disabled")
    monkeypatch.setattr(settings, "review_portal_studio_url", "https://studio.mapsi.test/growth")

    view = client.get(f"/review/{token}", headers=auth_headers())
    write = client.post(
        f"/review/{token}/approve",
        headers=auth_headers(),
        follow_redirects=False,
    )

    assert view.status_code == 200
    assert "Administration Moved" in view.text or "Review Portal Disabled" in view.text
    assert "MAPSI Studio" in view.text
    assert write.status_code == 200 or write.status_code == 303
