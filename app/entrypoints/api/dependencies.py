from pathlib import Path

from fastapi import Depends
from sqlalchemy.orm import Session

from app.application.services.editorial_engine_v1 import build_editorial_generation_service
from app.application.services.github_intelligence_service import GitHubIntelligenceService
from app.application.services.mapsi_news_publisher import MapsiNewsPublisher
from app.application.services.oling_news_publisher import OlingNewsPublisher
from app.application.services.simple_campaign_service import ManualLinkedInPublisher, SimpleCampaignService
from app.core.config import get_settings
from app.core.db import get_db_session
from app.infrastructure.connectors.fakes import CompositeSimulatedPublisher, OlingMockPublisher, SimulatedMapsiSiteConnector
from app.infrastructure.connectors.github import GitHubConnector
from app.infrastructure.connectors.mapsi_site import MapsiSiteConnector, build_mapsi_site_config
from app.infrastructure.connectors.oling import OlingConnector, build_oling_config
from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
from app.infrastructure.repositories.mapsi_site_publications import MapsiNewsPublicationRepository
from app.infrastructure.repositories.oling import OlingNewsPublicationRepository
from app.infrastructure.repositories.product_intelligence import (
    SqlAlchemyProductChangeRepository,
    SqlAlchemyRepositoryCursorRepository,
    SqlAlchemyRepositorySourceRepository,
    SqlAlchemySourceEvidenceRepository,
    SqlAlchemyWebhookDeliveryRepository,
)
from app.infrastructure.tasks import RedisTaskQueue
from app.knowledge import KnowledgeRepository


def get_github_intelligence_service(session: Session = Depends(get_db_session)) -> GitHubIntelligenceService:
    settings = get_settings()
    task_queue = RedisTaskQueue(settings.redis_url, settings.redis_queue_name)
    return GitHubIntelligenceService(
        connector=GitHubConnector(settings),
        repository_sources=SqlAlchemyRepositorySourceRepository(session),
        repository_cursors=SqlAlchemyRepositoryCursorRepository(session),
        product_changes=SqlAlchemyProductChangeRepository(session),
        source_evidences=SqlAlchemySourceEvidenceRepository(session),
        webhook_deliveries=SqlAlchemyWebhookDeliveryRepository(session),
        task_queue=task_queue,
    )


def get_simple_campaign_service(session: Session = Depends(get_db_session)) -> SimpleCampaignService:
    settings = get_settings()
    repository = SqlAlchemyCampaignRepository(session)
    audit_log = SqlAlchemyAuditLogRepository(session)
    oling_publisher = (
        OlingMockPublisher()
        if settings.oling_mode == "mock" or settings.app_env == "test"
        else OlingNewsPublisher(
            campaign_repository=repository,
            publication_repository=OlingNewsPublicationRepository(session),
            connector=OlingConnector(build_oling_config(settings)),
            audit_log=audit_log,
            review_portal=None,
        )
    )
    mapsi_publisher = (
        SimulatedMapsiSiteConnector()
        if settings.mapsi_site_mode == "mock" or settings.app_env == "test"
        else MapsiNewsPublisher(
            campaign_repository=repository,
            publication_repository=MapsiNewsPublicationRepository(session),
            connector=MapsiSiteConnector(build_mapsi_site_config()),
            audit_log=audit_log,
            review_portal=None,
        )
    )
    publisher = CompositeSimulatedPublisher(
        {
            "linkedin_manual": ManualLinkedInPublisher(),
            "oling": oling_publisher,
            "mapsi_site": mapsi_publisher,
        }
    )
    return SimpleCampaignService(
        repository=repository,
        publisher=publisher,
        audit_log=audit_log,
        task_queue=RedisTaskQueue(settings.redis_url, settings.redis_queue_name),
        project_root=Path(__file__).resolve().parents[3],
        editorial_service=build_editorial_generation_service(session),
        knowledge_repository=KnowledgeRepository(session),
    )
