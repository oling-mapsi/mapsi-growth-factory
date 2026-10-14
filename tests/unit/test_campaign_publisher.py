from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.application.services.audience_segmentation_service import AudienceSegmentationService
from app.application.services.campaign_publisher import CampaignPublisher
from app.application.services.mautic_contact_sync_service import MauticContactSyncService
from app.application.services.review_portal_service import ReviewPortalService
from app.core.config import get_settings
from app.core.security import encrypt_contact_value
from app.domain.entities import AudienceSegment, CampaignReview, CampaignRun, ContentAsset, SourceEvidence
from app.domain.enums import AssetStatus, CampaignStatus
from app.domain.errors import CampaignPublicationForbiddenError, DuplicateCampaignPublicationError, EmergencyStopActiveError
from app.infrastructure.connectors.mautic import MauticConnector, MauticConnectorConfig
from app.infrastructure.db.models import ContactMembershipModel
from app.infrastructure.repositories.audience_segments import AudienceSegmentationRepository
from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
from app.infrastructure.repositories.mautic_publications import MauticPublicationRepository
from app.infrastructure.repositories.mautic_sync import MauticSyncRepository
from app.infrastructure.repositories.mapsi_usage import MapsiUsageRepository
from app.infrastructure.repositories.review_portal import ReviewPortalRepository
from app.mock_mautic_server import STATE, app as mautic_mock_app


def reset_mock_state() -> None:
    for key in STATE:
        STATE[key].clear()


def build_connector(*, reset: bool = False) -> MauticConnector:
    if reset:
        reset_mock_state()
    return MauticConnector(
        MauticConnectorConfig(
            base_url="http://testserver",
            username="",
            password="",
            access_token="sandbox-token",
            verify_tls=False,
        ),
        client=TestClient(mautic_mock_app),
    )


def seed_contact(session) -> None:
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

    sync = MauticContactSyncService(
        build_connector(reset=True),
        MauticSyncRepository(session),
        AudienceSegmentationService(AudienceSegmentationRepository(session)),
    )
    sync.provision(dry_run=False)
    sync.sync_contacts(dry_run=False)


def seed_campaign_review(session) -> str:
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
        audience_segments=[
            AudienceSegment(name="All eligible", description="All eligible active users")
        ],
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
    saved_review = review_service.review_repository.save_review(review)
    token = review_service.create_review_token(saved_review.id)
    review_service.approve(token, actor="admin")
    return campaign.id


def build_service(session) -> CampaignPublisher:
    repository = SqlAlchemyCampaignRepository(session)
    audit_log = SqlAlchemyAuditLogRepository(session)
    return CampaignPublisher(
        campaign_repository=repository,
        review_portal=ReviewPortalService(repository, ReviewPortalRepository(session), audit_log),
        segmentation_service=AudienceSegmentationService(AudienceSegmentationRepository(session)),
        mautic_repository=MauticPublicationRepository(session),
        mautic_sync_repository=MauticSyncRepository(session),
        mautic_connector=build_connector(),
        audit_log=audit_log,
    )


def test_create_preview_persists_mautic_ids(session) -> None:
    seed_contact(session)
    campaign_id = seed_campaign_review(session)

    publication = build_service(session).create_preview(campaign_id, idempotency_key="preview-1")

    assert publication["status"] == "preview_ready"
    assert publication["mautic_email_id"]
    assert publication["mautic_segment_id"]
    assert publication["mautic_campaign_id"]
    assert publication["targeted_contacts"] == 1


def test_schedule_is_blocked_twice_for_same_version(session) -> None:
    seed_contact(session)
    campaign_id = seed_campaign_review(session)
    service = build_service(session)

    first = service.schedule_campaign(campaign_id, scheduled_at=datetime.now(UTC) + timedelta(hours=1), idempotency_key="schedule-1")

    assert first["status"] == "scheduled"
    with pytest.raises(DuplicateCampaignPublicationError):
        service.schedule_campaign(campaign_id, scheduled_at=datetime.now(UTC) + timedelta(hours=2), idempotency_key="schedule-2")


def test_schedule_blocks_when_contact_is_dnc(session) -> None:
    seed_contact(session)
    campaign_id = seed_campaign_review(session)
    contact_id = next(iter(STATE["contacts"].keys()))
    STATE["contacts"][contact_id]["doNotContact"] = [{"reason": "manual", "channel": "email"}]

    with pytest.raises(CampaignPublicationForbiddenError):
        build_service(session).schedule_campaign(campaign_id, scheduled_at=datetime.now(UTC) + timedelta(hours=1), idempotency_key="schedule-3")


def test_schedule_blocks_with_instance_kill_switch(session, monkeypatch) -> None:
    seed_contact(session)
    campaign_id = seed_campaign_review(session)
    monkeypatch.setenv("PUBLICATION_INSTANCE_KILL_SWITCHES", "gpmlm")
    get_settings.cache_clear()

    with pytest.raises(EmergencyStopActiveError):
        build_service(session).schedule_campaign(campaign_id, scheduled_at=datetime.now(UTC) + timedelta(hours=1), idempotency_key="schedule-4")

    monkeypatch.delenv("PUBLICATION_INSTANCE_KILL_SWITCHES", raising=False)
    get_settings.cache_clear()


def test_schedule_blocks_real_mapsi_users_audience_in_pilot_mode(session, monkeypatch) -> None:
    seed_contact(session)
    campaign_id = seed_campaign_review(session)
    monkeypatch.setenv("GROWTH_OPERATION_MODE", "pilot")
    get_settings.cache_clear()

    with pytest.raises(CampaignPublicationForbiddenError, match="Pilot mode"):
        build_service(session).schedule_campaign(
            campaign_id,
            scheduled_at=datetime.now(UTC) + timedelta(hours=1),
            idempotency_key="schedule-pilot-1",
        )

    monkeypatch.delenv("GROWTH_OPERATION_MODE", raising=False)
    get_settings.cache_clear()
