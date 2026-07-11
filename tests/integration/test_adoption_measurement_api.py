from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.security import encrypt_contact_value
from app.domain.entities import AudienceSegment, CampaignReview, CampaignRun, ContentAsset, SourceEvidence
from app.domain.enums import AssetStatus, CampaignStatus
from app.infrastructure.db.models import ContactMembershipModel
from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
from app.infrastructure.repositories.mautic_publications import MauticPublicationRepository
from app.infrastructure.repositories.mautic_sync import MauticSyncRepository
from app.infrastructure.repositories.mapsi_usage import MapsiUsageRepository
from app.infrastructure.repositories.review_portal import ReviewPortalRepository
from app.mock_mautic_server import STATE


def auth_headers() -> dict[str, str]:
    return {"X-API-Key": "test-key"}


def seed_data(session) -> tuple[str, str]:
    now = datetime.now(UTC)
    usage = MapsiUsageRepository(session)
    instance = usage.upsert_instance("gpmlm", "https://gpmlm.example", "vault://mapsi/gpmlm/growth-token", True, "1.3.0")
    account = usage.upsert_customer_account(instance.id, "tenant-a")
    identity = usage.upsert_contact_identity("hash:eligible@example.test", encrypt_contact_value("eligible@example.test"), True)
    membership = usage.upsert_contact_membership(
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
    row.created_at = now - timedelta(days=40)
    row.updated_at = now - timedelta(days=40)
    session.commit()
    before_snapshot = usage.create_snapshot_if_absent(instance.id, "usage", "before-api", "1.3.0", now - timedelta(days=1))
    after_snapshot = usage.create_snapshot_if_absent(instance.id, "usage", "after-api", "1.3.0", now + timedelta(days=4))
    usage.upsert_feature_adoption(before_snapshot.id, membership.id, "planning", 1)
    usage.upsert_feature_adoption(after_snapshot.id, membership.id, "planning", 3)
    MauticSyncRepository(session).upsert_link(
        contact_identity_id=identity.id,
        mautic_contact_id="1",
        email_hash=identity.email_hash,
        dnc_applied=False,
        remote_unsubscribed=False,
        last_sync_status="synced",
        last_source_updated_at=now,
    )

    campaign = CampaignRun(
        name="Weekly campaign",
        objective="feature_adoption",
        status=CampaignStatus.APPROVED,
        content_assets=[ContentAsset(campaign_run_id="", asset_type="email", channel="mautic", title="Subject", body="<p>Hello</p>", status=AssetStatus.APPROVED)],
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
    repo.add(campaign)
    review_repo = ReviewPortalRepository(session)
    review = review_repo.save_review(
        CampaignReview(
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
        )
    )
    from app.application.services.review_portal_service import ReviewPortalService
    review_service = ReviewPortalService(repo, review_repo, audit)
    review.approved_content_hash = review_service.content_hash(review)
    review.approved_audience_hash = review_service.audience_hash(review)
    review.approved_by = "admin"
    review.approved_at = now
    review_repo.save_review(review)
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
    STATE["events"][int(publication.mautic_campaign_id)] = [
        {"id": "api-1", "type": "sent", "contactId": 1, "occurredAt": now.isoformat()},
        {"id": "api-2", "type": "opened", "contactId": 1, "occurredAt": now.isoformat()},
    ]
    return campaign.id, identity.email_hash


def test_collect_adoption_metrics_and_report_hide_contact_keys(client, session) -> None:
    campaign_id, contact_key = seed_data(session)

    collect = client.post(
        f"/ops/campaigns/{campaign_id}/collect-adoption-metrics",
        headers={**auth_headers(), "Idempotency-Key": "adopt-1"},
        json={"correlation_id": "corr-adopt-1", "dry_run": False},
    )
    report = client.get(
        f"/ops/campaigns/{campaign_id}/adoption-report",
        headers=auth_headers(),
        params={"correlation_id": "corr-adopt-1"},
    )

    assert collect.status_code == 200
    assert collect.json()["details"]["imported"] == 2
    assert report.status_code == 200
    assert report.json()["details"]["events"]["opened"] == 1
    assert contact_key not in str(report.json())
    assert "eligible@example.test" not in str(report.json())
