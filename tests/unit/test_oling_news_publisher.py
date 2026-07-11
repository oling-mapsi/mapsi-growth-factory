from datetime import UTC, datetime
import json

import pytest
from fastapi.testclient import TestClient

from app.application.services.oling_news_publisher import OlingNewsPublisher
from app.application.services.review_portal_service import ReviewPortalService
from app.core.config import get_settings
from app.domain.entities import AudienceSegment, CampaignReview, CampaignRun, ContentAsset, SourceEvidence
from app.domain.enums import AssetStatus, CampaignStatus
from app.domain.errors import CampaignPublicationForbiddenError, ExternalConnectorError
from app.infrastructure.connectors.oling import OlingConnector, build_oling_config
from app.infrastructure.connectors import oling as oling_connector_module
from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
from app.infrastructure.repositories.oling import OlingNewsPublicationRepository
from app.infrastructure.repositories.review_portal import ReviewPortalRepository
from app.mock_oling_server import STATE, app as oling_mock_app


def build_publisher(session, *, mode: str = "live", retries: int = 1, breaker_threshold: int = 2) -> OlingNewsPublisher:
    oling_connector_module._CIRCUIT_BREAKERS.clear()
    settings = get_settings()
    settings.oling_mode = mode
    settings.oling_base_url = "http://testserver"
    settings.oling_site_base_url = "https://www.oling.fr"
    settings.oling_api_token = "oling-test-token"
    settings.oling_verify_tls = False
    settings.oling_max_retries = retries
    settings.oling_retry_backoff_seconds = 0.0
    settings.oling_circuit_breaker_threshold = breaker_threshold
    settings.oling_circuit_breaker_reset_seconds = 60
    settings.publish_oling_enabled = True
    settings.workflow_kill_switch = False
    connector = OlingConnector(build_oling_config(settings), client=TestClient(oling_mock_app))
    repository = SqlAlchemyCampaignRepository(session)
    audit_log = SqlAlchemyAuditLogRepository(session)
    review_portal = ReviewPortalService(repository, ReviewPortalRepository(session), audit_log)
    return OlingNewsPublisher(
        campaign_repository=repository,
        publication_repository=OlingNewsPublicationRepository(session),
        connector=connector,
        audit_log=audit_log,
        review_portal=review_portal,
    )


def seed_campaign(session, *, title: str = "Article Oling", status: AssetStatus = AssetStatus.APPROVED, approved_hash_matches: bool = True):
    campaign = CampaignRun(name="Oling campaign", objective="awareness", status=CampaignStatus.APPROVED)
    campaign.audience_segments.append(AudienceSegment(campaign_run_id=campaign.id, name="Prospects", description="Prospects"))
    campaign.source_evidences.append(SourceEvidence(campaign_run_id=campaign.id, source_system="mapsi", reference="mapsi:1"))
    asset = ContentAsset(
        campaign_run_id=campaign.id,
        asset_type="oling_news_article",
        channel="oling",
        title=title,
        content_html="<p>Contenu riche</p>",
        content_text="Contenu riche",
        excerpt="Resume court",
        audience_segment_id=campaign.audience_segments[0].id,
        status=status,
    )
    asset.ensure_content_hash()
    if status is AssetStatus.APPROVED:
        asset.approved_content_hash = asset.content_hash if approved_hash_matches else "stale-hash"
        asset.approved_by = "approver"
        asset.approved_at = datetime.now(UTC)
    campaign.content_assets.append(asset)
    campaign = SqlAlchemyCampaignRepository(session).add(campaign)
    review = CampaignReview(
        campaign_run_id=campaign.id,
        quality_control={"passed": True},
        approved_content_hash="review-hash",
        approved_audience_hash="audience-hash",
        approved_by="approver",
        approved_at=datetime.now(UTC),
    )
    ReviewPortalRepository(session).save_review(review)
    return campaign


def test_oling_publish_and_preview_are_persisted(session, monkeypatch) -> None:
    get_settings.cache_clear()
    publisher = build_publisher(session)
    campaign = seed_campaign(session)
    asset = campaign.content_assets[0]

    preview = publisher.create_preview(campaign, asset)
    publication = publisher.publish(campaign, asset)
    stored = OlingNewsPublicationRepository(session).get_latest_for_asset(asset.id)

    assert preview["preview_url"].startswith("http://testserver/preview/ressources/")
    assert publication.external_reference == asset.id
    assert stored is not None
    assert stored.preview_url.startswith("http://testserver/preview/ressources/")
    assert stored.public_url == "https://www.oling.fr/ressources/article-oling"
    assert stored.published_revision_number == 1
    assert stored.published_content_version == 1


def test_oling_publish_is_idempotent_for_same_asset_hash(session) -> None:
    get_settings.cache_clear()
    publisher = build_publisher(session)
    campaign = seed_campaign(session)
    asset = campaign.content_assets[0]

    first = publisher.publish(campaign, asset)
    second = publisher.publish(campaign, asset)

    assert first.external_reference == second.external_reference
    assert len(STATE["articles"]) == 1


def test_oling_publish_blocks_when_flag_disabled(session) -> None:
    get_settings.cache_clear()
    publisher = build_publisher(session)
    publisher.settings.publish_oling_enabled = False
    campaign = seed_campaign(session)

    with pytest.raises(CampaignPublicationForbiddenError):
        publisher.publish(campaign, campaign.content_assets[0])


def test_oling_publish_blocks_when_asset_hash_changed(session) -> None:
    get_settings.cache_clear()
    publisher = build_publisher(session)
    campaign = seed_campaign(session, approved_hash_matches=False)

    with pytest.raises(CampaignPublicationForbiddenError):
        publisher.publish(campaign, campaign.content_assets[0])


def test_oling_publish_blocks_when_quality_failed(session) -> None:
    get_settings.cache_clear()
    publisher = build_publisher(session)
    campaign = seed_campaign(session)
    review_repository = ReviewPortalRepository(session)
    review = review_repository.get_review_by_campaign(campaign.id)
    assert review is not None
    review.quality_control = {"passed": False}
    review_repository.save_review(review)

    with pytest.raises(CampaignPublicationForbiddenError):
        publisher.publish(campaign, campaign.content_assets[0])


def test_oling_preview_only_mode_blocks_public_publish(session) -> None:
    get_settings.cache_clear()
    publisher = build_publisher(session, mode="preview-only")
    campaign = seed_campaign(session)

    preview = publisher.create_preview(campaign, campaign.content_assets[0])
    with pytest.raises(CampaignPublicationForbiddenError):
        publisher.publish(campaign, campaign.content_assets[0])

    assert preview["preview_url"].startswith("http://testserver/preview/ressources/")


def test_oling_invalid_auth_does_not_log_token(session, caplog) -> None:
    get_settings.cache_clear()
    publisher = build_publisher(session)
    publisher.settings.oling_api_token = "wrong-token"
    publisher.connector.config.api_token = "wrong-token"
    campaign = seed_campaign(session)

    with caplog.at_level("INFO", logger="app.github"):
        with pytest.raises(ExternalConnectorError):
            publisher.create_preview(campaign, campaign.content_assets[0])

    assert "wrong-token" not in caplog.text


def test_oling_server_errors_trigger_circuit_breaker(session) -> None:
    get_settings.cache_clear()
    publisher = build_publisher(session, retries=0, breaker_threshold=1)
    campaign = seed_campaign(session, title="SERVER_ERROR")

    with pytest.raises(ExternalConnectorError):
        publisher.create_preview(campaign, campaign.content_assets[0])
    with pytest.raises(ExternalConnectorError):
        publisher.create_preview(campaign, campaign.content_assets[0])


def test_publish_asset_dry_run_returns_preview(session) -> None:
    get_settings.cache_clear()
    publisher = build_publisher(session)
    campaign = seed_campaign(session)
    asset = campaign.content_assets[0]

    result = publisher.publish_asset(campaign.id, asset.id, dry_run=True)

    assert result["dry_run"] is True
    assert result["preview"]["preview_url"].startswith("http://testserver/preview/ressources/")
