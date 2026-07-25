import os
from collections.abc import Generator
from pathlib import Path

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
"""

from app.core.config import get_settings
from app.core.db import Base, get_db_session
from app.infrastructure.db import models  # noqa: F401
from app.knowledge import KnowledgeRepository
from app.application.services.editorial_engine_v1 import build_editorial_generation_service
from app.application.services.github_intelligence_service import GitHubIntelligenceService
from app.application.services.simple_campaign_service import ManualLinkedInPublisher, SimpleCampaignService
from app.entrypoints.api.dependencies import get_github_intelligence_service, get_simple_campaign_service
from app.infrastructure.connectors.fakes import CompositeSimulatedPublisher, OlingMockPublisher, SimulatedMapsiSiteConnector
from app.infrastructure.connectors.github import GitHubConnector
from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
from app.infrastructure.repositories.product_intelligence import (
    SqlAlchemyProductChangeRepository,
    SqlAlchemyRepositoryCursorRepository,
    SqlAlchemyRepositorySourceRepository,
    SqlAlchemySourceEvidenceRepository,
    SqlAlchemyWebhookDeliveryRepository,
)
from app.infrastructure.tasks import InMemoryTaskQueue
from app.main import create_app

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
    get_settings.cache_clear()

    def override_db_session() -> Generator[Session, None, None]:
        yield session

    def override_simple_campaign_service() -> SimpleCampaignService:
        repository = SqlAlchemyCampaignRepository(session)
        return SimpleCampaignService(
            repository=repository,
            publisher=CompositeSimulatedPublisher(
                {
                    "linkedin_manual": ManualLinkedInPublisher(),
                    "oling": OlingMockPublisher(),
                    "mapsi_site": SimulatedMapsiSiteConnector(),
                }
            ),
            audit_log=SqlAlchemyAuditLogRepository(session),
            task_queue=queue,
            project_root=Path(__file__).resolve().parents[1],
            editorial_service=build_editorial_generation_service(session, force_mode="simulated"),
            knowledge_repository=KnowledgeRepository(session, root=Path(__file__).resolve().parents[1] / "knowledge"),
        )

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

    app = create_app()
    app.dependency_overrides[get_db_session] = override_db_session
    app.dependency_overrides[get_simple_campaign_service] = override_simple_campaign_service
    app.dependency_overrides[get_github_intelligence_service] = override_github_service
    with TestClient(app) as api_client:
        yield api_client
