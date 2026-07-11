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

from app.core.db import Base
from app.infrastructure.db import models  # noqa: F401
from app.entrypoints.api.dependencies import get_campaign_service
from app.entrypoints.api.dependencies import get_campaign_publisher_service
from app.entrypoints.api.dependencies import get_github_intelligence_service
from app.entrypoints.api.dependencies import get_linkedin_metrics_collector
from app.entrypoints.api.dependencies import get_linkedin_oauth_service
from app.entrypoints.api.dependencies import get_linkedin_organization_resolver
from app.entrypoints.api.dependencies import get_linkedin_post_publisher
from app.entrypoints.api.dependencies import get_mapsi_product_changes_service
from app.entrypoints.api.dependencies import get_adoption_measurement_service
from app.entrypoints.api.dependencies import get_review_portal_service
from app.application.services.adoption_measurement_service import AdoptionMeasurementService
from app.application.services.audience_segmentation_service import AudienceSegmentationService
from app.application.services.campaign_publisher import CampaignPublisher
from app.application.services.linkedin_metrics_collector import LinkedInMetricsCollector
from app.application.services.linkedin_oauth_service import LinkedInOAuthService
from app.application.services.linkedin_organization_resolver import LinkedInOrganizationResolver
from app.application.services.linkedin_post_publisher import LinkedInPostPublisher
from app.application.services.mapsi_product_changes_service import MapsiProductChangesService
from app.entrypoints.api.routes.campaigns import get_idempotency_store
from app.application.services.github_intelligence_service import GitHubIntelligenceService
from app.application.services.review_portal_service import ReviewPortalService
from app.infrastructure.connectors.linkedin import LinkedInConnector, build_linkedin_config
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
    SimulatedOlingSiteConnector,
)
from app.infrastructure.connectors.github import GitHubConnector
from app.infrastructure.repositories.audience_segments import AudienceSegmentationRepository
from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
from app.infrastructure.repositories.idempotency import SqlAlchemyIdempotencyRepository
from app.infrastructure.repositories.mautic_publications import MauticPublicationRepository
from app.infrastructure.repositories.mautic_sync import MauticSyncRepository
from app.infrastructure.repositories.mapsi_usage import MapsiUsageRepository
from app.infrastructure.repositories.linkedin import LinkedInOAuthTokenRepository, LinkedInPublicationRepository
from app.infrastructure.repositories.product_intelligence import (
    SqlAlchemyProductChangeRepository,
    SqlAlchemyRepositoryCursorRepository,
    SqlAlchemyRepositorySourceRepository,
    SqlAlchemySourceEvidenceRepository,
    SqlAlchemyWebhookDeliveryRepository,
)
from app.infrastructure.repositories.review_portal import ReviewPortalRepository
from app.infrastructure.tasks import InMemoryTaskQueue
from app.mock_mautic_server import app as mautic_mock_app
from app.mock_mautic_server import STATE as MAUTIC_STATE
from app.mock_linkedin_server import app as linkedin_mock_app
from app.mock_linkedin_server import STATE as LINKEDIN_STATE
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

    app = create_app()
    app.dependency_overrides[get_campaign_service] = override_service
    app.dependency_overrides[get_idempotency_store] = override_idempotency_store
    app.dependency_overrides[get_github_intelligence_service] = override_github_service
    app.dependency_overrides[get_mapsi_product_changes_service] = override_mapsi_product_changes_service
    app.dependency_overrides[get_review_portal_service] = override_review_portal_service
    app.dependency_overrides[get_campaign_publisher_service] = override_campaign_publisher_service
    app.dependency_overrides[get_adoption_measurement_service] = override_adoption_measurement_service
    app.dependency_overrides[get_linkedin_oauth_service] = override_linkedin_oauth_service
    app.dependency_overrides[get_linkedin_organization_resolver] = override_linkedin_organization_resolver
    app.dependency_overrides[get_linkedin_post_publisher] = override_linkedin_post_publisher
    app.dependency_overrides[get_linkedin_metrics_collector] = override_linkedin_metrics_collector
    with TestClient(app) as api_client:
        yield api_client
