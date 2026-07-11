from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.application.services.adoption_measurement_service import AdoptionMeasurementService
from app.application.services.review_portal_service import ReviewPortalService
from app.core.security import encrypt_contact_value
from app.domain.entities import AudienceSegment, CampaignReview, CampaignRun, ContentAsset, SourceEvidence
from app.domain.enums import AssetStatus, CampaignStatus
from app.infrastructure.connectors.mautic import MauticConnector, MauticConnectorConfig
from app.infrastructure.db.models import ContactMembershipModel
from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
from app.infrastructure.repositories.mautic_publications import MauticPublicationRepository
from app.infrastructure.repositories.mautic_sync import MauticSyncRepository
from app.infrastructure.repositories.mapsi_usage import MapsiUsageRepository
from app.infrastructure.repositories.review_portal import ReviewPortalRepository
from app.mock_mautic_server import STATE, app as mautic_mock_app
from fastapi.testclient import TestClient


def reset_mock_state() -> None:
    for key in STATE:
        STATE[key].clear()


def build_connector() -> MauticConnector:
    return MauticConnector(
        MauticConnectorConfig(base_url="http://testserver", username="", password="", access_token="sandbox-token", verify_tls=False),
        client=TestClient(mautic_mock_app),
    )


def seed_synced_contact(session) -> tuple[str, str]:
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
        last_activity_at=now + timedelta(days=2),
    )
    row = session.get(ContactMembershipModel, membership.id)
    row.created_at = now - timedelta(days=60)
    row.updated_at = now - timedelta(days=60)
    session.commit()
    before_snapshot = repository.create_snapshot_if_absent(instance.id, "usage", "before", "1.3.0", now - timedelta(days=1))
    after7_snapshot = repository.create_snapshot_if_absent(instance.id, "usage", "after7", "1.3.0", now + timedelta(days=5))
    after30_snapshot = repository.create_snapshot_if_absent(instance.id, "usage", "after30", "1.3.0", now + timedelta(days=20))
    repository.upsert_feature_adoption(before_snapshot.id, membership.id, "planning", 1)
    repository.upsert_feature_adoption(after7_snapshot.id, membership.id, "planning", 4)
    repository.upsert_feature_adoption(after30_snapshot.id, membership.id, "planning", 6)

    sync = MauticSyncRepository(session)
    sync.upsert_link(
        contact_identity_id=identity.id,
        mautic_contact_id="1",
        email_hash=identity.email_hash,
        dnc_applied=False,
        remote_unsubscribed=False,
        last_sync_status="synced",
        last_source_updated_at=now,
    )
    return membership.id, identity.email_hash


def seed_campaign_and_publication(session) -> tuple[str, str]:
    now = datetime.now(UTC)
    campaign = CampaignRun(
        name="Weekly campaign",
        objective="feature_adoption",
        status=CampaignStatus.APPROVED,
        content_assets=[
            ContentAsset(campaign_run_id="", asset_type="email", channel="mautic", title="Subject", body="<p>Hello</p>", status=AssetStatus.APPROVED)
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
    repo = SqlAlchemyCampaignRepository(session)
    audit = SqlAlchemyAuditLogRepository(session)
    review_service = ReviewPortalService(repo, ReviewPortalRepository(session), audit)
    repo.add(campaign)
    review = CampaignReview(
        campaign_run_id=campaign.id,
        theme=campaign.name,
        objective=campaign.objective,
        segment_id="all_eligible_active_users",
        segment_label="All eligible active users",
        segment_version=1,
        audience_volume=1,
        exclusions={},
        evidence_ids=[campaign.source_evidences[0].id],
        email_subject="Subject",
        email_preheader="Preheader",
        email_html="<p>Hello</p>",
        email_text="Hello",
        quality_control={"passed": True},
        approved_content_hash="x",
        approved_audience_hash="y",
        approved_by="admin",
        approved_at=now,
    )
    review = review_service.review_repository.save_review(review)
    review.approved_content_hash = review_service.content_hash(review)
    review.approved_audience_hash = review_service.audience_hash(review)
    review_service.review_repository.save_review(review)
    publication = MauticPublicationRepository(session).save(
        __import__("app.domain.entities", fromlist=["MauticCampaignPublication"]).MauticCampaignPublication(
            campaign_run_id=campaign.id,
            content_version=1,
            segment_version=1,
            status="scheduled",
            mautic_email_id="10",
            mautic_segment_id="20",
            mautic_campaign_id="30",
            scheduled_at=now,
            idempotency_key="idem",
            target_instance_ids=["gpmlm"],
            target_client_ids=["tenant-a"],
            targeted_contacts=1,
        )
    )
    return campaign.id, publication.mautic_campaign_id


def build_service(session) -> AdoptionMeasurementService:
    repository = SqlAlchemyCampaignRepository(session)
    audit = SqlAlchemyAuditLogRepository(session)
    return AdoptionMeasurementService(
        campaign_repository=repository,
        mautic_publications=MauticPublicationRepository(session),
        mautic_sync_repository=MauticSyncRepository(session),
        mapsi_usage_repository=MapsiUsageRepository(session),
        review_repository=ReviewPortalRepository(session),
        mautic_connector=build_connector(),
        audit_log=audit,
    )


def test_adoption_report_aggregates_rates_and_hides_contact_keys(session) -> None:
    reset_mock_state()
    _, contact_key = seed_synced_contact(session)
    campaign_id, mautic_campaign_id = seed_campaign_and_publication(session)
    STATE["events"][int(mautic_campaign_id)] = [
        {"id": "e1", "type": "sent", "contactId": 1, "occurredAt": datetime.now(UTC).isoformat()},
        {"id": "e2", "type": "delivered", "contactId": 1, "occurredAt": datetime.now(UTC).isoformat()},
        {"id": "e3", "type": "opened", "contactId": 1, "occurredAt": datetime.now(UTC).isoformat()},
        {"id": "e4", "type": "clicked", "contactId": 1, "occurredAt": datetime.now(UTC).isoformat()},
    ]
    service = build_service(session)

    imported = service.import_events(campaign_id)
    report = service.build_report(campaign_id)

    assert imported["imported"] == 4
    assert report["rates"]["open_rate"] == 1.0
    assert report["rates"]["click_rate"] == 1.0
    assert report["usage"]["feature_usage_after_7_days"] >= report["usage"]["feature_usage_before"]
    assert report["confidentiality"]["contains_contact_keys"] is False
    assert contact_key not in str(report)
    assert "eligible@example.test" not in str(report)


def test_adoption_report_raises_alerts_on_bounces_and_unsubscribes(session) -> None:
    reset_mock_state()
    seed_synced_contact(session)
    campaign_id, mautic_campaign_id = seed_campaign_and_publication(session)
    STATE["events"][int(mautic_campaign_id)] = [
        {"id": "e1", "type": "sent", "contactId": 1, "occurredAt": datetime.now(UTC).isoformat()},
        {"id": "e2", "type": "bounced", "contactId": 1, "occurredAt": datetime.now(UTC).isoformat()},
        {"id": "e3", "type": "unsubscribed", "contactId": 1, "occurredAt": datetime.now(UTC).isoformat()},
    ]
    report = build_service(session)
    report.import_events(campaign_id)
    data = report.build_report(campaign_id)

    assert "high_bounce_rate" in data["alerts"]
    assert "high_unsubscribe_rate" in data["alerts"]
