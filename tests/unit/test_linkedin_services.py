from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.application.services.linkedin_metrics_collector import LinkedInMetricsCollector
from app.application.services.linkedin_oauth_service import LinkedInOAuthService
from app.application.services.linkedin_organization_resolver import LinkedInOrganizationResolver
from app.application.services.linkedin_post_publisher import LinkedInPostPublisher
from app.domain.entities import AudienceSegment, CampaignRun, ContentAsset, LinkedInOAuthToken, SourceEvidence
from app.domain.enums import AssetStatus, CampaignStatus
from app.domain.errors import CampaignPublicationForbiddenError
from app.infrastructure.connectors.linkedin import LinkedInConnector, build_linkedin_config
from app.infrastructure.observability import logger
from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
from app.infrastructure.repositories.linkedin import LinkedInOAuthTokenRepository, LinkedInPublicationRepository
from app.mock_linkedin_server import app as linkedin_mock_app


def build_services(session):
    config = build_linkedin_config()
    config.base_url = "http://testserver"
    config.mode = "mock"
    connector = LinkedInConnector(config, client=TestClient(linkedin_mock_app))
    oauth_repository = LinkedInOAuthTokenRepository(session)
    oauth_service = LinkedInOAuthService(connector=connector, repository=oauth_repository)
    resolver = LinkedInOrganizationResolver(connector=connector, oauth_service=oauth_service)
    publisher = LinkedInPostPublisher(
        campaign_repository=SqlAlchemyCampaignRepository(session),
        publication_repository=LinkedInPublicationRepository(session),
        oauth_service=oauth_service,
        organization_resolver=resolver,
        connector=connector,
        audit_log=SqlAlchemyAuditLogRepository(session),
    )
    metrics = LinkedInMetricsCollector(
        campaign_repository=SqlAlchemyCampaignRepository(session),
        publication_repository=LinkedInPublicationRepository(session),
        oauth_service=oauth_service,
        connector=connector,
        audit_log=SqlAlchemyAuditLogRepository(session),
    )
    return oauth_repository, oauth_service, publisher, metrics


def seed_campaign(session, *, asset_type: str = "linkedin_company_post", asset_status: AssetStatus = AssetStatus.APPROVED):
    campaign = CampaignRun(name="LinkedIn campaign", objective="awareness", status=CampaignStatus.APPROVED)
    campaign.audience_segments.append(AudienceSegment(campaign_run_id=campaign.id, name="Prospects", description="Prospects"))
    campaign.source_evidences.append(SourceEvidence(campaign_run_id=campaign.id, source_system="github", reference="github:1"))
    campaign.content_assets.append(
        ContentAsset(
            campaign_run_id=campaign.id,
            asset_type=asset_type,
            channel="linkedin",
            title="Post",
            body="Post body",
            evidence_ids=[campaign.source_evidences[0].id],
            audience_segment_id=campaign.audience_segments[0].id,
            status=asset_status,
            content_hash="hash-1",
        )
    )
    return SqlAlchemyCampaignRepository(session).add(campaign)


def test_linkedin_publish_requires_approved_asset(session) -> None:
    _, oauth_service, publisher, _ = build_services(session)
    oauth_service.exchange_code("seed")
    campaign = seed_campaign(session, asset_status=AssetStatus.READY_FOR_REVIEW)
    asset_id = campaign.content_assets[0].id

    with pytest.raises(CampaignPublicationForbiddenError):
        publisher.publish_asset(campaign.id, asset_id, idempotency_key="li-1")


def test_linkedin_publish_is_idempotent_for_same_asset_hash(session) -> None:
    _, oauth_service, publisher, metrics = build_services(session)
    oauth_service.exchange_code("seed")
    campaign = seed_campaign(session)
    asset_id = campaign.content_assets[0].id

    first = publisher.publish_asset(campaign.id, asset_id, idempotency_key="li-1")
    second = publisher.publish_asset(campaign.id, asset_id, idempotency_key="li-1")
    report = metrics.collect(campaign.id)

    assert first["linkedin_post_urn"] == second["linkedin_post_urn"]
    assert report["collected"] == 1


def test_linkedin_personal_draft_stays_manual_copy(session) -> None:
    _, oauth_service, publisher, _ = build_services(session)
    oauth_service.exchange_code("seed")
    campaign = seed_campaign(session, asset_type="linkedin_personal_draft")

    result = publisher.publish_asset(campaign.id, campaign.content_assets[0].id, idempotency_key="li-manual")

    assert result["status"] == "manual_copy"
    assert result["mode"] == "manual"
    assert result["metrics"]["manual_copy_required"] is True


def test_linkedin_oauth_refreshes_expiring_token(session) -> None:
    oauth_repository, oauth_service, _, _ = build_services(session)
    token = LinkedInOAuthToken(
        access_token="stale-token",
        refresh_token="refresh-1",
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
        refresh_expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    oauth_repository.save(token)

    refreshed = oauth_service.get_valid_token()

    assert refreshed.access_token.startswith("mock-token-")
    expires_at = refreshed.expires_at.replace(tzinfo=UTC) if refreshed.expires_at and refreshed.expires_at.tzinfo is None else refreshed.expires_at
    assert expires_at is not None and expires_at > datetime.now(UTC)


def test_linkedin_logs_do_not_expose_token(session, caplog) -> None:
    _, oauth_service, publisher, _ = build_services(session)
    oauth_service.exchange_code("secret-code")
    campaign = seed_campaign(session)

    with caplog.at_level("INFO", logger="app.github"):
        publisher.publish_asset(campaign.id, campaign.content_assets[0].id, idempotency_key="li-log")

    assert "mock-token-" not in caplog.text
