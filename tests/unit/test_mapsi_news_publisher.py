from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.application.services.mapsi_news_publisher import MapsiNewsPublisher
from app.application.services.review_portal_service import ReviewPortalService
from app.core.config import get_settings
from app.domain.entities import AudienceSegment, CampaignReview, CampaignRun, ContentAsset, SourceEvidence
from app.domain.enums import AssetStatus, CampaignStatus
from app.domain.errors import (
    AuthenticationInvalidError,
    CampaignPublicationForbiddenError,
    EmergencyStopActiveError,
    ExternalConnectorError,
    RemoteConflictError,
    RemoteContractError,
    RemoteUnsupportedError,
)
from app.infrastructure.connectors.mapsi_site import MapsiSiteConnector, build_mapsi_site_config
from app.infrastructure.connectors import mapsi_site as mapsi_site_connector_module
from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
from app.infrastructure.repositories.mapsi_site_publications import MapsiNewsPublicationRepository
from app.infrastructure.repositories.review_portal import ReviewPortalRepository
from app.mock_mapsi_site_server import STATE, app as mapsi_site_mock_app


def build_publisher(session, *, mode: str = "live", retries: int = 1, breaker_threshold: int = 2) -> MapsiNewsPublisher:
    mapsi_site_connector_module._CIRCUIT_BREAKERS.clear()
    settings = get_settings()
    settings.mapsi_site_mode = mode
    settings.mapsi_site_base_url = "http://testserver"
    settings.mapsi_site_public_base_url = "https://www.mapsi.fr"
    settings.mapsi_site_api_token = "mapsi-site-test-token"
    settings.mapsi_site_verify_tls = False
    settings.mapsi_site_max_retries = retries
    settings.mapsi_site_retry_backoff_seconds = 0.0
    settings.mapsi_site_circuit_breaker_threshold = breaker_threshold
    settings.mapsi_site_circuit_breaker_reset_seconds = 60
    settings.publish_mapsi_site_enabled = True
    settings.workflow_kill_switch = False
    connector = MapsiSiteConnector(build_mapsi_site_config(settings), client=TestClient(mapsi_site_mock_app))
    repository = SqlAlchemyCampaignRepository(session)
    audit_log = SqlAlchemyAuditLogRepository(session)
    review_portal = ReviewPortalService(repository, ReviewPortalRepository(session), audit_log)
    return MapsiNewsPublisher(
        campaign_repository=repository,
        publication_repository=MapsiNewsPublicationRepository(session),
        connector=connector,
        audit_log=audit_log,
        review_portal=review_portal,
    )


def seed_campaign(session, *, title: str = "Article MAPSI", status: AssetStatus = AssetStatus.APPROVED, approved_hash_matches: bool = True):
    campaign = CampaignRun(name="Mapsi campaign", objective="awareness", status=CampaignStatus.APPROVED)
    campaign.audience_segments.append(AudienceSegment(campaign_run_id=campaign.id, name="Users", description="Users"))
    campaign.source_evidences.append(SourceEvidence(campaign_run_id=campaign.id, source_system="mapsi", reference="mapsi:1"))
    asset = ContentAsset(
        campaign_run_id=campaign.id,
        asset_type="mapsi_news_article",
        channel="mapsi_site",
        title=title,
        content_html="<p>Contenu MAPSI</p>",
        content_text="Contenu MAPSI",
        excerpt="Resume MAPSI",
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
    ReviewPortalRepository(session).save_review(
        CampaignReview(
            campaign_run_id=campaign.id,
            quality_control={"passed": True},
            approved_content_hash="review-hash",
            approved_audience_hash="audience-hash",
            approved_by="approver",
            approved_at=datetime.now(UTC),
        )
    )
    return campaign


def test_mapsi_site_publish_and_preview_are_persisted(session) -> None:
    get_settings.cache_clear()
    publisher = build_publisher(session)
    campaign = seed_campaign(session)
    asset = campaign.content_assets[0]

    preview = publisher.create_preview(campaign, asset)
    publication = publisher.publish(campaign, asset)
    stored = MapsiNewsPublicationRepository(session).get_latest_for_asset(asset.id)

    assert preview["preview_url"].startswith("http://testserver/preview/actualites/")
    assert publication.external_reference == "1"
    assert stored is not None
    assert stored.public_url == "https://www.mapsi.fr/actualites/article-mapsi"
    assert stored.publication_status == "PUBLISHED"
    assert stored.publisher_type == "mapsi_site_api"
    assert stored.metrics["growth_external_id"] == asset.id
    assert stored.metrics["remote_article_id"] == 1
    assert stored.metrics["idempotent_replay"] is False
    assert asset.status is AssetStatus.PUBLISHED
    assert asset.external_publication_id == "1"


def test_mapsi_site_publish_is_idempotent_for_same_asset_hash(session) -> None:
    get_settings.cache_clear()
    publisher = build_publisher(session)
    campaign = seed_campaign(session)
    asset = campaign.content_assets[0]

    first = publisher.publish_asset(campaign.id, asset.id, idempotency_key="mapsi-1")
    second = publisher.publish_asset(campaign.id, asset.id, idempotency_key="mapsi-2")

    assert first["details"]["publication_status"] == "PUBLISHED"
    assert second["details"]["idempotency_key"] == "mapsi-1"
    assert second["details"]["idempotent_replay"] is True
    assert second["details"]["external_publication_id"] == first["details"]["external_publication_id"]
    assert second["details"]["external_publication_url"] == first["details"]["external_publication_url"]
    assert len(STATE["articles"]) == 1


def test_mapsi_site_publish_blocks_when_flag_or_kill_switch_enabled(session) -> None:
    get_settings.cache_clear()
    publisher = build_publisher(session)
    campaign = seed_campaign(session)

    publisher.settings.publish_mapsi_site_enabled = False
    with pytest.raises(CampaignPublicationForbiddenError):
        publisher.publish(campaign, campaign.content_assets[0])

    publisher.settings.publish_mapsi_site_enabled = True
    publisher.settings.workflow_kill_switch = True
    with pytest.raises(EmergencyStopActiveError):
        publisher.publish(campaign, campaign.content_assets[0])


def test_mapsi_site_preview_only_mode_blocks_public_publish_but_allows_preview(session) -> None:
    get_settings.cache_clear()
    publisher = build_publisher(session, mode="preview-only")
    campaign = seed_campaign(session)

    preview = publisher.create_preview(campaign, campaign.content_assets[0])

    with pytest.raises(CampaignPublicationForbiddenError):
        publisher.publish(campaign, campaign.content_assets[0])

    assert preview["preview_url"].startswith("http://testserver/preview/actualites/")


def test_mapsi_site_publish_blocks_on_wrong_asset_type(session) -> None:
    get_settings.cache_clear()
    publisher = build_publisher(session)
    campaign = seed_campaign(session)
    asset = campaign.content_assets[0]
    asset.asset_type = "website_article"
    SqlAlchemyCampaignRepository(session).save(campaign)

    with pytest.raises(CampaignPublicationForbiddenError):
        publisher.publish(campaign, asset)


def test_mapsi_site_invalid_auth_is_explicit(session) -> None:
    get_settings.cache_clear()
    publisher = build_publisher(session)
    publisher.settings.mapsi_site_api_token = "wrong-token"
    publisher.connector.config.api_token = "wrong-token"
    campaign = seed_campaign(session)

    with pytest.raises(AuthenticationInvalidError):
        publisher.create_preview(campaign, campaign.content_assets[0])


def test_mapsi_site_contract_mismatch_is_explicit(session) -> None:
    get_settings.cache_clear()
    publisher = build_publisher(session)
    campaign = seed_campaign(session, title="CONTRACT_ERROR")

    with pytest.raises(RemoteContractError):
        publisher.create_preview(campaign, campaign.content_assets[0])


def test_mapsi_site_preview_conflict_is_explicit(session) -> None:
    get_settings.cache_clear()
    publisher = build_publisher(session)
    asset_id = "mapsi-preview-conflict"
    STATE["articles"][asset_id] = {
        "growth_external_id": asset_id,
        "article_id": 99,
        "draft_slug": "conflict",
        "published_slug": None,
        "draft_version": 0,
        "published_version": None,
        "status": "draft",
        "published_at": None,
        "updated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "public_url": None,
        "has_pending_draft": False,
        "content_hash": "",
        "last_publication_idempotency_key": "",
    }

    with pytest.raises(RemoteConflictError):
        publisher.connector.get_preview_url(asset_id, correlation_id="mapsi-preview-conflict")


def test_mapsi_site_server_errors_trigger_circuit_breaker(session) -> None:
    get_settings.cache_clear()
    publisher = build_publisher(session, retries=0, breaker_threshold=1)
    campaign = seed_campaign(session, title="SERVER_ERROR")

    with pytest.raises(ExternalConnectorError):
        publisher.create_preview(campaign, campaign.content_assets[0])
    with pytest.raises(ExternalConnectorError):
        publisher.create_preview(campaign, campaign.content_assets[0])


def test_mapsi_site_publish_timeout_after_remote_success_is_reconciled(session) -> None:
    get_settings.cache_clear()
    publisher = build_publisher(session)
    campaign = seed_campaign(session)
    asset = campaign.content_assets[0]

    def timeout_after_remote_publish(external_id: str, *, correlation_id: str, idempotency_key: str = ""):
        article = STATE["articles"][external_id]
        article["published_version"] = article["draft_version"]
        article["published_slug"] = article["draft_slug"]
        article["status"] = "published"
        article["published_at"] = datetime.now(UTC).replace(microsecond=0).isoformat()
        article["updated_at"] = article["published_at"]
        article["public_url"] = f"https://www.mapsi.fr/actualites/{article['published_slug']}"
        article["has_pending_draft"] = False
        raise ExternalConnectorError("timeout")

    publisher.connector.publish = timeout_after_remote_publish

    result = publisher.publish_asset(campaign.id, asset.id, idempotency_key="timeout-1")
    stored = MapsiNewsPublicationRepository(session).get_latest_for_asset(asset.id)

    assert result["details"]["publication_status"] == "PUBLISHED"
    assert stored is not None
    assert stored.publication_status == "PUBLISHED"
    assert stored.idempotency_key == "timeout-1"


def test_mapsi_site_unpublish_can_be_reported_unsupported(session) -> None:
    get_settings.cache_clear()
    publisher = build_publisher(session)
    campaign = seed_campaign(session)
    asset = campaign.content_assets[0]
    publisher.publish(campaign, asset, idempotency_key="pub-1")
    STATE["supports_unpublish"] = False

    with pytest.raises(CampaignPublicationForbiddenError):
        publisher.unpublish(campaign, asset)

    stored = MapsiNewsPublicationRepository(session).get_latest_for_asset(asset.id)
    assert stored is not None
    assert stored.publication_status == "UNPUBLISH_UNSUPPORTED"


def test_mapsi_site_unpublish_succeeds_when_supported(session) -> None:
    get_settings.cache_clear()
    publisher = build_publisher(session)
    campaign = seed_campaign(session)
    asset = campaign.content_assets[0]
    publisher.publish(campaign, asset, idempotency_key="pub-1")

    assert publisher.unpublish(campaign, asset) is True

    stored = MapsiNewsPublicationRepository(session).get_latest_for_asset(asset.id)
    assert stored is not None
    assert stored.publication_status == "UNPUBLISHED"
