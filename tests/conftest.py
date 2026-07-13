import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["MAPSI_API_KEY"] = "test-key"
os.environ["REDIS_URL"] = "redis://localhost:6379/15"
os.environ["REDIS_QUEUE_NAME"] = "mapsi:test:tasks"
os.environ["GITHUB_WEBHOOK_SECRET"] = "test-github-secret"
os.environ["GITHUB_ALLOWED_REPOSITORIES"] = "mapsi/mapsi-v6"
os.environ["MAPSI_GROWTH_BASE_URL"] = "https://mapsi-v6.example.test"
os.environ["MAPSI_GROWTH_BEARER_TOKEN"] = "test-growth-bearer"
os.environ["OLING_MODE"] = "mock"
os.environ["OLING_API_TOKEN"] = "oling-test-token"
os.environ["OLING_BASE_URL"] = "http://testserver"
os.environ["OLING_SITE_BASE_URL"] = "https://www.oling.fr"
os.environ["PUBLISH_OLING_ENABLED"] = "true"
os.environ["MAPSI_SITE_MODE"] = "mock"
os.environ["MAPSI_SITE_API_TOKEN"] = "mapsi-site-test-token"
os.environ["MAPSI_SITE_BASE_URL"] = "http://testserver"
os.environ["MAPSI_SITE_PUBLIC_BASE_URL"] = "https://www.mapsi.fr"
os.environ["PUBLISH_MAPSI_SITE_ENABLED"] = "true"
os.environ["PUBLISH_LINKEDIN_ENABLED"] = "true"
os.environ["WORKFLOW_KILL_SWITCH"] = "false"
os.environ["STUDIO_ADMIN_API_ENABLED"] = "true"
os.environ["STUDIO_ADMIN_JWT_ISSUER"] = "mapsi-studio"
os.environ["STUDIO_ADMIN_JWT_AUDIENCE"] = "mapsi-growth-admin"
os.environ["STUDIO_ADMIN_JWT_ALLOWED_ALGORITHMS"] = "RS256"
os.environ["STUDIO_ADMIN_JWT_MAX_LIFETIME_SECONDS"] = "300"
os.environ["STUDIO_ADMIN_ENFORCE_REPLAY_PROTECTION"] = "true"
os.environ["STUDIO_ADMIN_JWT_PUBLIC_KEYS"] = """keys:
  - kid: studio-k1
    alg: RS256
    public_key_pem: |
      -----BEGIN PUBLIC KEY-----
      MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA5DyWBiLecO5V3GtYiejp
      vAKj8ZjyPqxrLQuXX63xB3XpL2aFhIKM5PlNEmy0GmrvFdtFPRTuIYjvjkXe7E0Y
      4Yyx7iVTOx9fW8s8wJBdVnzalL5y2PamgygW1NotUqbMPHRWDNjlG2f6JPdzEKnj
      j07KCzlzcNGnsaeBSN0WT5gaeaThT192lfTHV4Q5LbgHR5eM+l0B885kOQWt4rHG
      SLB2vQbDF7GifiW0zSIYZE8l4169f+ZpyIgEever3CV5F8VwcTmvg4pSLsqN1HPh
      DwY84h7HP857verdJQSuQQEDJavsxXGpPZCbreAZfr+CjjScPCTbMySfJTVBxW7Y
      HQIDAQAB
      -----END PUBLIC KEY-----
  - kid: studio-k2
    alg: RS256
    public_key_pem: |
      -----BEGIN PUBLIC KEY-----
      MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAo0RGLLJ266ahymTe16N9
      mVwdwhGxKiR0c1hRbGUP9+v1VGfhXTTglF1EKqBSSt4UAYR97Zz9AH8iCFNg3uMJ
      WQZczjDBsbs92cRBcYdohqRDi8MBtNfQNG9ejqSviSO3zT0lcFlO50tk4zVm84EL
      TZC83sXhqlXMVZxZZdEd7MIhi7pjzOZkUPT395EEXBtyF0XLa4/jW5oEHPz+yzeB
      GewL95ahrK5m104pfC9p3qroEJOtt0TsXkIKujRz3SZwXPXli61NUzEDt7mmku3g
      yJmNruqmSfh4vsBoSrkVg3cSqVIg0Q5q+s/yvd/qZYWw6Mua/2SZWArdeIKrf0+t
      dwIDAQAB
      -----END PUBLIC KEY-----
"""

from app.core.db import Base
from app.core.db import get_db_session
from app.infrastructure.db import models  # noqa: F401
from app.entrypoints.api.dependencies import get_campaign_service
from app.entrypoints.api.dependencies import get_campaign_publisher_service
from app.entrypoints.api.dependencies import get_github_intelligence_service
from app.entrypoints.api.dependencies import get_linkedin_metrics_collector
from app.entrypoints.api.dependencies import get_linkedin_oauth_service
from app.entrypoints.api.dependencies import get_linkedin_organization_resolver
from app.entrypoints.api.dependencies import get_linkedin_post_publisher
from app.entrypoints.api.dependencies import get_mapsi_news_publisher
from app.entrypoints.api.dependencies import get_oling_news_publisher
from app.entrypoints.api.dependencies import get_mapsi_product_changes_service
from app.entrypoints.api.dependencies import get_adoption_measurement_service
from app.entrypoints.api.dependencies import get_review_portal_service
from app.entrypoints.api.dependencies import get_studio_admin_service
from app.application.services.adoption_measurement_service import AdoptionMeasurementService
from app.application.services.audience_segmentation_service import AudienceSegmentationService
from app.application.services.campaign_publisher import CampaignPublisher
from app.application.services.linkedin_metrics_collector import LinkedInMetricsCollector
from app.application.services.linkedin_oauth_service import LinkedInOAuthService
from app.application.services.linkedin_organization_resolver import LinkedInOrganizationResolver
from app.application.services.linkedin_post_publisher import LinkedInPostPublisher
from app.application.services.mapsi_market_campaign_builder import MapsiMarketCampaignBuilder
from app.application.services.mapsi_news_publisher import MapsiNewsPublisher
from app.application.services.mapsi_product_changes_service import MapsiProductChangesService
from app.application.services.mapsi_user_weekly_email_builder import MapsiUserWeeklyEmailBuilder
from app.application.services.oling_practice_campaign_builder import OlingPracticeCampaignBuilder
from app.application.services.oling_news_publisher import OlingNewsPublisher
from app.entrypoints.api.routes.campaigns import get_idempotency_store
from app.application.services.github_intelligence_service import GitHubIntelligenceService
from app.application.services.review_portal_service import ReviewPortalService
from app.application.services.studio_admin_service import StudioAdminService
from app.infrastructure.connectors.linkedin import LinkedInConnector, build_linkedin_config
from app.infrastructure.connectors.mapsi_site import MapsiSiteConnector, build_mapsi_site_config
from app.infrastructure.connectors.mautic import MauticConnector, MauticConnectorConfig
from app.infrastructure.connectors.fakes import (
    CompositeSimulatedGenerator,
    CompositeSimulatedPublisher,
    SimulatedDolibarrConnector,
    SimulatedGitHubConnector,
    SimulatedLinkedInConnector,
    SimulatedMAPSIConnector,
    SimulatedMauticConnector,
    SimulatedMicrosoftGraphConnector,
    SimulatedMapsiSiteConnector,
    SimulatedOlingSiteConnector,
)
from app.infrastructure.connectors.github import GitHubConnector
from app.infrastructure.repositories.audience_segments import AudienceSegmentationRepository
from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
from app.infrastructure.repositories.channel_operational_state import ChannelOperationalStateRepository
from app.infrastructure.repositories.editorial_source_packs import EditorialSourcePackRepository
from app.infrastructure.repositories.editorial_pipeline import EditorialPipelineRepository
from app.infrastructure.repositories.feature_communication_catalog import FeatureCommunicationCatalogRepository
from app.infrastructure.repositories.idempotency import SqlAlchemyIdempotencyRepository
from app.infrastructure.repositories.mautic_publications import MauticPublicationRepository
from app.infrastructure.repositories.mautic_sync import MauticSyncRepository
from app.infrastructure.repositories.mapsi_site_publications import MapsiNewsPublicationRepository
from app.infrastructure.repositories.mapsi_usage import MapsiUsageRepository
from app.infrastructure.repositories.linkedin import LinkedInOAuthTokenRepository, LinkedInPublicationRepository
from app.infrastructure.repositories.oling import OlingNewsPublicationRepository
from app.infrastructure.repositories.product_intelligence import (
    SqlAlchemyProductChangeRepository,
    SqlAlchemyRepositoryCursorRepository,
    SqlAlchemyRepositorySourceRepository,
    SqlAlchemySourceEvidenceRepository,
    SqlAlchemyWebhookDeliveryRepository,
)
from app.infrastructure.repositories.review_portal import ReviewPortalRepository
from app.infrastructure.repositories.weekly_communication_packs import WeeklyCommunicationPackRepository
from app.infrastructure.tasks import InMemoryTaskQueue
from app.mock_mautic_server import app as mautic_mock_app
from app.mock_mautic_server import STATE as MAUTIC_STATE
from app.mock_linkedin_server import app as linkedin_mock_app
from app.mock_linkedin_server import STATE as LINKEDIN_STATE
from app.mock_oling_server import STATE as OLING_STATE
from app.mock_mapsi_news_server import STATE as MAPSI_SITE_STATE
from app.main import create_app
from app.application.services.campaign_service import CampaignService
from app.core.config import get_settings

TEST_DATABASE_URL = "sqlite+pysqlite:///:memory:"
engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    future=True,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@pytest.fixture(autouse=True)
def reset_database() -> Generator[None, None, None]:
    for key in MAUTIC_STATE:
        MAUTIC_STATE[key].clear()
    LINKEDIN_STATE["tokens"].clear()
    LINKEDIN_STATE["posts"].clear()
    LINKEDIN_STATE["metrics"].clear()
    LINKEDIN_STATE["uploads"].clear()
    OLING_STATE["articles"].clear()
    OLING_STATE["preview_tokens"].clear()
    MAPSI_SITE_STATE["articles"].clear()
    MAPSI_SITE_STATE["preview_tokens"].clear()
    MAPSI_SITE_STATE["next_article_id"] = 1
    MAPSI_SITE_STATE["supports_unpublish"] = True
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def session() -> Generator[Session, None, None]:
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client(session: Session) -> Generator[TestClient, None, None]:
    queue = InMemoryTaskQueue()

    def override_db_session() -> Generator[Session, None, None]:
        yield session

    def override_service() -> CampaignService:
        repository = SqlAlchemyCampaignRepository(session)
        audit_log = SqlAlchemyAuditLogRepository(session)
        review_portal = ReviewPortalService(repository, ReviewPortalRepository(session), audit_log)
        generator = CompositeSimulatedGenerator(
            [
                SimulatedGitHubConnector(),
                SimulatedMAPSIConnector(),
                SimulatedMicrosoftGraphConnector(),
                SimulatedMauticConnector(),
                SimulatedDolibarrConnector(),
            ]
        )
        publisher = CompositeSimulatedPublisher(
            {
                "linkedin": SimulatedLinkedInConnector(),
                "oling": SimulatedOlingSiteConnector(),
                "mapsi_site": SimulatedMapsiSiteConnector(),
            }
        )
        return CampaignService(repository, generator, publisher, audit_log, queue, review_portal=review_portal)

    def override_idempotency_store():
        return SqlAlchemyIdempotencyRepository(session)

    def override_github_service() -> GitHubIntelligenceService:
        return GitHubIntelligenceService(
            connector=GitHubConnector(get_settings()),
            repository_sources=SqlAlchemyRepositorySourceRepository(session),
            repository_cursors=SqlAlchemyRepositoryCursorRepository(session),
            product_changes=SqlAlchemyProductChangeRepository(session),
            source_evidences=SqlAlchemySourceEvidenceRepository(session),
            webhook_deliveries=SqlAlchemyWebhookDeliveryRepository(session),
            task_queue=queue,
        )

    class FakeMapsiProductChangesConnector:
        def get_product_changes(self):
            from app.generated.mapsi_contract_models import ProductChange, ProductChangeCollection

            return ProductChangeCollection(
                contract_version="1.0.0",
                generated_at="2026-07-11T15:00:00+00:00",
                items=[
                    ProductChange(
                        id="MAPSI-2026-010",
                        title="Export des indicateurs du tableau utilisateur",
                        summary="Les responsables peuvent exporter les indicateurs visibles depuis le tableau utilisateur sans retraitement manuel.",
                        url="https://github.com/oling-mapsi/mapsi-v6/pull/2101",
                        published_at="2026-07-01T00:00:00Z",
                        tags=["product", "release", "dashboard"],
                        communicable=True,
                    )
                ],
            )

    def override_mapsi_product_changes_service() -> MapsiProductChangesService:
        return MapsiProductChangesService(
            connector=FakeMapsiProductChangesConnector(),
            repository_sources=SqlAlchemyRepositorySourceRepository(session),
            product_changes=SqlAlchemyProductChangeRepository(session),
            source_evidences=SqlAlchemySourceEvidenceRepository(session),
            repository_full_name="oling-mapsi/mapsi-v6",
            default_branch="master",
        )

    def override_review_portal_service() -> ReviewPortalService:
        repository = SqlAlchemyCampaignRepository(session)
        audit_log = SqlAlchemyAuditLogRepository(session)
        return ReviewPortalService(repository, ReviewPortalRepository(session), audit_log)

    def override_studio_admin_service() -> StudioAdminService:
        repository = SqlAlchemyCampaignRepository(session)
        audit_log = SqlAlchemyAuditLogRepository(session)
        review_repository = ReviewPortalRepository(session)
        review_service = ReviewPortalService(repository, review_repository, audit_log)
        publisher = CompositeSimulatedPublisher(
            {
                "linkedin": SimulatedLinkedInConnector(),
                "oling": SimulatedOlingSiteConnector(),
                "mapsi_site": SimulatedMapsiSiteConnector(),
            }
        )
        campaign_service = CampaignService(
            repository,
            CompositeSimulatedGenerator(
                [
                    SimulatedGitHubConnector(),
                    SimulatedMAPSIConnector(),
                    SimulatedMicrosoftGraphConnector(),
                    SimulatedMauticConnector(),
                    SimulatedDolibarrConnector(),
                ]
            ),
            publisher,
            audit_log,
            queue,
            review_portal=review_service,
        )
        return StudioAdminService(
            campaign_service=campaign_service,
            review_portal_service=review_service,
            review_repository=review_repository,
            audit_repository=audit_log,
            mautic_publications=MauticPublicationRepository(session),
            linkedin_publications=LinkedInPublicationRepository(session),
            oling_publications=OlingNewsPublicationRepository(session),
            mapsi_site_publications=MapsiNewsPublicationRepository(session),
            channel_state_repository=ChannelOperationalStateRepository(session),
            weekly_pack_repository=WeeklyCommunicationPackRepository(session),
            editorial_source_pack_repository=EditorialSourcePackRepository(session),
            campaign_publisher=override_campaign_publisher_service(),
            linkedin_publisher=override_linkedin_post_publisher(),
            oling_publisher=override_oling_news_publisher(),
            mapsi_publisher=override_mapsi_news_publisher(),
            mapsi_market_builder=MapsiMarketCampaignBuilder(
                editorial_repository=EditorialPipelineRepository(session),
                editorial_source_packs=EditorialSourcePackRepository(session),
            ),
            oling_practice_builder=OlingPracticeCampaignBuilder(
                editorial_repository=EditorialPipelineRepository(session),
                editorial_source_packs=EditorialSourcePackRepository(session),
            ),
            mapsi_users_builder=MapsiUserWeeklyEmailBuilder(
                editorial_repository=EditorialPipelineRepository(session),
                catalog_repository=FeatureCommunicationCatalogRepository(session),
                segmentation_service=AudienceSegmentationService(AudienceSegmentationRepository(session)),
                mapsi_usage_repository=MapsiUsageRepository(session),
            ),
        )

    def override_campaign_publisher_service() -> CampaignPublisher:
        repository = SqlAlchemyCampaignRepository(session)
        audit_log = SqlAlchemyAuditLogRepository(session)
        review_portal = ReviewPortalService(repository, ReviewPortalRepository(session), audit_log)
        return CampaignPublisher(
            campaign_repository=repository,
            review_portal=review_portal,
            segmentation_service=AudienceSegmentationService(AudienceSegmentationRepository(session)),
            mautic_repository=MauticPublicationRepository(session),
            mautic_sync_repository=MauticSyncRepository(session),
            mautic_connector=MauticConnector(
                MauticConnectorConfig(
                    base_url="http://testserver",
                    username="",
                    password="",
                    access_token="sandbox-token",
                    verify_tls=False,
                ),
                client=TestClient(mautic_mock_app),
            ),
            audit_log=audit_log,
        )

    def override_adoption_measurement_service() -> AdoptionMeasurementService:
        repository = SqlAlchemyCampaignRepository(session)
        audit_log = SqlAlchemyAuditLogRepository(session)
        return AdoptionMeasurementService(
            campaign_repository=repository,
            mautic_publications=MauticPublicationRepository(session),
            mautic_sync_repository=MauticSyncRepository(session),
            mapsi_usage_repository=MapsiUsageRepository(session),
            review_repository=ReviewPortalRepository(session),
            mautic_connector=MauticConnector(
                MauticConnectorConfig(
                    base_url="http://testserver",
                    username="",
                    password="",
                    access_token="sandbox-token",
                    verify_tls=False,
                ),
                client=TestClient(mautic_mock_app),
            ),
            audit_log=audit_log,
        )

    def build_linkedin_connector() -> LinkedInConnector:
        config = build_linkedin_config(get_settings())
        config.base_url = "http://testserver"
        config.mode = "mock"
        return LinkedInConnector(config, client=TestClient(linkedin_mock_app))

    def override_linkedin_oauth_service() -> LinkedInOAuthService:
        return LinkedInOAuthService(
            connector=build_linkedin_connector(),
            repository=LinkedInOAuthTokenRepository(session),
        )

    def override_linkedin_organization_resolver() -> LinkedInOrganizationResolver:
        connector = build_linkedin_connector()
        oauth_service = LinkedInOAuthService(connector=connector, repository=LinkedInOAuthTokenRepository(session))
        return LinkedInOrganizationResolver(connector=connector, oauth_service=oauth_service)

    def override_linkedin_post_publisher() -> LinkedInPostPublisher:
        repository = SqlAlchemyCampaignRepository(session)
        audit_log = SqlAlchemyAuditLogRepository(session)
        connector = build_linkedin_connector()
        oauth_service = LinkedInOAuthService(connector=connector, repository=LinkedInOAuthTokenRepository(session))
        resolver = LinkedInOrganizationResolver(connector=connector, oauth_service=oauth_service)
        return LinkedInPostPublisher(
            campaign_repository=repository,
            publication_repository=LinkedInPublicationRepository(session),
            oauth_service=oauth_service,
            organization_resolver=resolver,
            connector=connector,
            audit_log=audit_log,
        )

    def override_linkedin_metrics_collector() -> LinkedInMetricsCollector:
        repository = SqlAlchemyCampaignRepository(session)
        audit_log = SqlAlchemyAuditLogRepository(session)
        connector = build_linkedin_connector()
        oauth_service = LinkedInOAuthService(connector=connector, repository=LinkedInOAuthTokenRepository(session))
        return LinkedInMetricsCollector(
            campaign_repository=repository,
            publication_repository=LinkedInPublicationRepository(session),
            oauth_service=oauth_service,
            connector=connector,
            audit_log=audit_log,
        )

    def override_oling_news_publisher() -> OlingNewsPublisher:
        repository = SqlAlchemyCampaignRepository(session)
        audit_log = SqlAlchemyAuditLogRepository(session)
        review_portal = ReviewPortalService(repository, ReviewPortalRepository(session), audit_log)
        from app.infrastructure.connectors.oling import build_oling_config, OlingConnector
        return OlingNewsPublisher(
            campaign_repository=repository,
            publication_repository=OlingNewsPublicationRepository(session),
            connector=OlingConnector(build_oling_config(), client=TestClient(__import__("app.mock_oling_server", fromlist=["app"]).app)),
            audit_log=audit_log,
            review_portal=review_portal,
        )

    def override_mapsi_news_publisher() -> MapsiNewsPublisher:
        repository = SqlAlchemyCampaignRepository(session)
        audit_log = SqlAlchemyAuditLogRepository(session)
        review_portal = ReviewPortalService(repository, ReviewPortalRepository(session), audit_log)
        return MapsiNewsPublisher(
            campaign_repository=repository,
            publication_repository=MapsiNewsPublicationRepository(session),
            connector=MapsiSiteConnector(build_mapsi_site_config(), client=TestClient(__import__("app.mock_mapsi_news_server", fromlist=["app"]).app)),
            audit_log=audit_log,
            review_portal=review_portal,
        )

    app = create_app()
    app.dependency_overrides[get_campaign_service] = override_service
    app.dependency_overrides[get_db_session] = override_db_session
    app.dependency_overrides[get_idempotency_store] = override_idempotency_store
    app.dependency_overrides[get_github_intelligence_service] = override_github_service
    app.dependency_overrides[get_mapsi_product_changes_service] = override_mapsi_product_changes_service
    app.dependency_overrides[get_review_portal_service] = override_review_portal_service
    app.dependency_overrides[get_studio_admin_service] = override_studio_admin_service
    app.dependency_overrides[get_campaign_publisher_service] = override_campaign_publisher_service
    app.dependency_overrides[get_adoption_measurement_service] = override_adoption_measurement_service
    app.dependency_overrides[get_linkedin_oauth_service] = override_linkedin_oauth_service
    app.dependency_overrides[get_linkedin_organization_resolver] = override_linkedin_organization_resolver
    app.dependency_overrides[get_linkedin_post_publisher] = override_linkedin_post_publisher
    app.dependency_overrides[get_linkedin_metrics_collector] = override_linkedin_metrics_collector
    app.dependency_overrides[get_oling_news_publisher] = override_oling_news_publisher
    app.dependency_overrides[get_mapsi_news_publisher] = override_mapsi_news_publisher
    with TestClient(app) as api_client:
        yield api_client
