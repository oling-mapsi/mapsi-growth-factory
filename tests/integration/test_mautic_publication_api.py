from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.application.services.audience_segmentation_service import AudienceSegmentationService
from app.application.services.mautic_contact_sync_service import MauticContactSyncService
from app.application.services.review_portal_service import ReviewPortalService
from app.core.security import encrypt_contact_value
from app.domain.entities import AudienceSegment, CampaignReview, CampaignRun, ContentAsset, SourceEvidence
from app.domain.enums import AssetStatus, CampaignStatus
from app.infrastructure.connectors.mautic import MauticConnector, MauticConnectorConfig
from app.infrastructure.db.models import ContactMembershipModel
from app.infrastructure.repositories.audience_segments import AudienceSegmentationRepository
from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
from app.infrastructure.repositories.mautic_sync import MauticSyncRepository
from app.infrastructure.repositories.mapsi_usage import MapsiUsageRepository
from app.infrastructure.repositories.review_portal import ReviewPortalRepository
from app.mock_mautic_server import STATE, app as mautic_mock_app
from fastapi.testclient import TestClient


def auth_headers() -> dict[str, str]:
    return {"X-API-Key": "test-key"}


def reset_mock_state() -> None:
    for key in STATE:
        STATE[key].clear()


def seed_synced_contact(session) -> None:
    now = datetime.now(UTC)
    repository = MapsiUsageRepository(session)
    instance = repository.upsert_instance("gpmlm", "https://gpmlm.example", "vault://mapsi/gpmlm/growth-token", True, "1.3.0")
    account = repository.upsert_customer_account(instance.id, "tenant-a")
    identity = repository.upsert_contact_identity("hash:eligible@example.test", encrypt_contact_value("eligible@example.test"), True)
    membership = repository.upsert_contact_membership(
        contact_identity_id=identity.id,
        customer_account_id=account.id,
        external_user_id="u1",
        role_key="administrator",
        active=True,
        communication_eligible=True,
        opted_out=False,
        last_activity_at=now - timedelta(days=1),
    )
    row = session.get(ContactMembershipModel, membership.id)
    row.created_at = now - timedelta(days=5)
    row.updated_at = now - timedelta(days=5)
    session.commit()
    snapshot = repository.create_snapshot_if_absent(instance.id, "usage", "u1:usage", "1.3.0", now)
    repository.upsert_feature_adoption(snapshot.id, membership.id, "planning", 4)
    connector = MauticConnector(
        MauticConnectorConfig(base_url="http://testserver", username="", password="", access_token="sandbox-token", verify_tls=False),
        client=TestClient(mautic_mock_app),
    )
    service = MauticContactSyncService(connector, MauticSyncRepository(session), AudienceSegmentationService(AudienceSegmentationRepository(session)))
    reset_mock_state()
    service.provision(dry_run=False)
    service.sync_contacts(dry_run=False)


def seed_review(session) -> str:
    campaign = CampaignRun(
        name="Weekly campaign",
        objective="feature_adoption",
        status=CampaignStatus.APPROVED,
        content_assets=[
            ContentAsset(
                campaign_run_id="",
                asset_type="email",
                channel="mautic",
                title="Subject",
                body="<p>Hello world</p>",
                status=AssetStatus.APPROVED,
            )
        ],
        audience_segments=[AudienceSegment(name="All eligible", description="All eligible active users")],
        source_evidences=[SourceEvidence(source_system="github", reference="sha:123", evidence_type="deployment_proof")],
    )
    for asset in campaign.content_assets:
        asset.campaign_run_id = campaign.id
    for segment in campaign.audience_segments:
        segment.campaign_run_id = campaign.id
    for evidence in campaign.source_evidences:
        evidence.campaign_run_id = campaign.id
    repository = SqlAlchemyCampaignRepository(session)
    audit_log = SqlAlchemyAuditLogRepository(session)
    review_service = ReviewPortalService(repository, ReviewPortalRepository(session), audit_log)
    repository.add(campaign)
    review = CampaignReview(
        campaign_run_id=campaign.id,
        theme="Weekly campaign",
        objective=campaign.objective,
        segment_id="all_eligible_active_users",
        segment_label="All eligible active users",
        segment_version=1,
        audience_volume=1,
        exclusions={},
        evidence_ids=[campaign.source_evidences[0].id],
        email_subject="Subject",
        email_preheader="Preheader",
        email_html="<p>Hello world</p>",
        email_text="Hello world",
        quality_control={"passed": True},
    )
    saved = review_service.review_repository.save_review(review)
    token = review_service.create_review_token(saved.id)
    review_service.approve(token, actor="admin")
    return campaign.id


def test_mautic_preview_requires_api_key(client, session) -> None:
    seed_synced_contact(session)
    campaign_id = seed_review(session)

    response = client.post(
        f"/ops/campaigns/{campaign_id}/mautic-preview",
        json={"correlation_id": "corr-mautic-1", "dry_run": False},
    )

    assert response.status_code == 401


def test_mautic_schedule_replays_same_idempotent_response(client, session) -> None:
    seed_synced_contact(session)
    campaign_id = seed_review(session)
    payload = {
        "correlation_id": "corr-mautic-2",
        "dry_run": False,
        "scheduled_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    headers = {**auth_headers(), "Idempotency-Key": "mautic-schedule-1"}

    first = client.post(f"/ops/campaigns/{campaign_id}/mautic-schedule", headers=headers, json=payload)
    second = client.post(f"/ops/campaigns/{campaign_id}/mautic-schedule", headers=headers, json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
