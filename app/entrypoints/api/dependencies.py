from fastapi import Depends
from sqlalchemy.orm import Session

from app.application.services.audience_segmentation_service import AudienceSegmentationService
from app.application.services.adoption_measurement_service import AdoptionMeasurementService
from app.application.services.campaign_service import CampaignService
from app.application.services.campaign_publisher import CampaignPublisher
from app.application.services.editorial_agents import (
    CustomerEmailWriterAgent,
    EditorialStrategyAgent,
    LinkedInWriterAgent,
    MarketEditorialStrategyAgent,
    NewsletterWriterAgent,
    ProductIntelligenceAgent,
    QualityControlAgent,
    SeoQualityAgent,
    UsageIntelligenceAgent,
    WebsiteArticleWriterAgent,
)
from app.application.services.github_intelligence_service import GitHubIntelligenceService
from app.application.services.mapsi_product_changes_service import MapsiProductChangesService
from app.application.services.mapsi_usage_collection_service import MapsiUsageCollectionService
from app.application.services.mautic_contact_sync_service import MauticContactSyncService
from app.application.services.multichannel_content_service import MultichannelContentService
from app.application.services.linkedin_metrics_collector import LinkedInMetricsCollector
from app.application.services.linkedin_oauth_service import LinkedInOAuthService
from app.application.services.linkedin_organization_resolver import LinkedInOrganizationResolver
from app.application.services.linkedin_post_publisher import LinkedInPostPublisher
from app.application.services.linkedin_media_uploader import LinkedInMediaUploader
from app.application.services.oling_news_publisher import OlingNewsPublisher
from app.application.services.review_portal_service import ReviewPortalService
from app.application.services.task_worker_service import TaskWorkerService
from app.application.services.weekly_campaign_generation_service import WeeklyCampaignGenerationService
from app.core.config import get_mapsi_instances
from app.core.db import get_db_session
from app.infrastructure.agents.openai_backend import OpenAIAgentsBackend
from app.infrastructure.agents.simulated_backend import SimulatedEditorialBackend
from app.infrastructure.connectors.fakes import (
    CompositeSimulatedGenerator,
    CompositeSimulatedPublisher,
    SimulatedDolibarrConnector,
    SimulatedGitHubConnector,
    SimulatedLinkedInConnector,
    SimulatedMAPSIConnector,
    SimulatedMapsiSiteConnector,
    SimulatedMapsiStudioConnector,
    SimulatedMapsiUsersConnector,
    SimulatedMauticConnector,
    SimulatedMicrosoftGraphConnector,
    OlingMockPublisher,
    SimulatedOlingSiteConnector,
    SimulatedProspectNewsletterConnector,
)
from app.infrastructure.connectors.github import GitHubConnector
from app.infrastructure.connectors.linkedin import LinkedInConnector, build_linkedin_config
from app.infrastructure.connectors.mautic import MauticConnector, build_mautic_config
from app.infrastructure.connectors.oling import OlingConnector, build_oling_config
from app.infrastructure.connectors.mapsi_usage import MapsiInstanceConfig, MapsiUsageConnector
from app.generated.mapsi_contract_client import MapsiContractClient
from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository
from app.infrastructure.repositories.audience_segments import AudienceSegmentationRepository
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
from app.infrastructure.repositories.editorial_pipeline import EditorialPipelineRepository
from app.infrastructure.repositories.mapsi_usage import MapsiUsageRepository
from app.infrastructure.repositories.mautic_sync import MauticSyncRepository
from app.infrastructure.repositories.mautic_publications import MauticPublicationRepository
from app.infrastructure.repositories.linkedin import LinkedInOAuthTokenRepository, LinkedInPublicationRepository
from app.infrastructure.repositories.oling import OlingNewsPublicationRepository
from app.infrastructure.repositories.review_portal import ReviewPortalRepository
from app.infrastructure.repositories.product_intelligence import (
    SqlAlchemyProductChangeRepository,
    SqlAlchemyRepositoryCursorRepository,
    SqlAlchemyRepositorySourceRepository,
    SqlAlchemySourceEvidenceRepository,
    SqlAlchemyWebhookDeliveryRepository,
)
from app.infrastructure.tasks import RedisTaskQueue
from app.core.config import get_settings


def _build_editorial_backend():
    if get_settings().editorial_agent_backend == "openai":
        return OpenAIAgentsBackend()
    return SimulatedEditorialBackend()


def get_campaign_service(session: Session = Depends(get_db_session)) -> CampaignService:
    settings = get_settings()
    repository = SqlAlchemyCampaignRepository(session)
    audit_log = SqlAlchemyAuditLogRepository(session)
    generator = CompositeSimulatedGenerator(
        [
            SimulatedGitHubConnector(),
            SimulatedMAPSIConnector(),
            SimulatedMicrosoftGraphConnector(),
            SimulatedMauticConnector(),
            SimulatedDolibarrConnector(),
        ]
    )
    review_portal = ReviewPortalService(repository, ReviewPortalRepository(session), audit_log)
    oling_publisher = (
        OlingMockPublisher()
        if settings.oling_mode == "mock" or settings.app_env in {"development", "test"}
        else OlingNewsPublisher(
            campaign_repository=repository,
            publication_repository=OlingNewsPublicationRepository(session),
            connector=OlingConnector(build_oling_config(settings)),
            audit_log=audit_log,
            review_portal=review_portal,
        )
    )
    publisher = CompositeSimulatedPublisher(
        {
            "linkedin": SimulatedLinkedInConnector(),
            "oling": oling_publisher,
            "mapsi_site": SimulatedMapsiSiteConnector(),
            "mapsi_studio": SimulatedMapsiStudioConnector(),
            "mapsi_users": SimulatedMapsiUsersConnector(),
            "prospect_newsletter": SimulatedProspectNewsletterConnector(),
        }
    )
    task_queue = RedisTaskQueue(settings.redis_url, settings.redis_queue_name)
    return CampaignService(repository, generator, publisher, audit_log, task_queue, review_portal=review_portal)


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


def get_mapsi_product_changes_service(session: Session = Depends(get_db_session)) -> MapsiProductChangesService:
    settings = get_settings()
    if not settings.mapsi_growth_base_url:
        raise RuntimeError("MAPSI_GROWTH_BASE_URL is not configured.")
    if not settings.mapsi_growth_bearer_token:
        raise RuntimeError("MAPSI_GROWTH_BEARER_TOKEN is not configured.")
    connector = MapsiContractClient(
        settings.mapsi_growth_base_url,
        headers={"Authorization": f"Bearer {settings.mapsi_growth_bearer_token}"},
    )
    return MapsiProductChangesService(
        connector=connector,
        repository_sources=SqlAlchemyRepositorySourceRepository(session),
        product_changes=SqlAlchemyProductChangeRepository(session),
        source_evidences=SqlAlchemySourceEvidenceRepository(session),
        repository_full_name=settings.mapsi_growth_repository_full_name,
        default_branch=settings.mapsi_growth_default_branch,
    )


def get_review_portal_service(session: Session = Depends(get_db_session)) -> ReviewPortalService:
    repository = SqlAlchemyCampaignRepository(session)
    audit_log = SqlAlchemyAuditLogRepository(session)
    return ReviewPortalService(repository, ReviewPortalRepository(session), audit_log)


def get_weekly_campaign_generation_service(session: Session = Depends(get_db_session)) -> WeeklyCampaignGenerationService:
    backend = _build_editorial_backend()
    return WeeklyCampaignGenerationService(
        product_agent=ProductIntelligenceAgent(backend),
        usage_agent=UsageIntelligenceAgent(backend),
        strategy_agent=EditorialStrategyAgent(backend),
        writer_agent=CustomerEmailWriterAgent(backend),
        quality_agent=QualityControlAgent(backend),
        segmentation_service=AudienceSegmentationService(AudienceSegmentationRepository(session)),
        repository=EditorialPipelineRepository(session),
    )


def get_mautic_contact_sync_service(session: Session = Depends(get_db_session)) -> MauticContactSyncService:
    return MauticContactSyncService(
        connector=MauticConnector(build_mautic_config()),
        repository=MauticSyncRepository(session),
        segmentation_service=AudienceSegmentationService(AudienceSegmentationRepository(session)),
    )


def get_mapsi_usage_collection_services(session: Session = Depends(get_db_session)) -> dict[str, MapsiUsageCollectionService]:
    services: dict[str, MapsiUsageCollectionService] = {}
    for item in get_mapsi_instances():
        instance = MapsiInstanceConfig(
            id=item["id"],
            base_url=item["base_url"],
            secret_ref=item["secret_ref"],
            enabled=bool(item["enabled"]),
        )
        services[instance.id] = MapsiUsageCollectionService(
            connector=MapsiUsageConnector(instance),
            repository=MapsiUsageRepository(session),
            instance_config=instance,
        )
    return services


def get_task_worker_service(session: Session = Depends(get_db_session)) -> TaskWorkerService:
    return TaskWorkerService(
        repository=SqlAlchemyCampaignRepository(session),
        audit_log=SqlAlchemyAuditLogRepository(session),
        github_intelligence=get_github_intelligence_service(session),
    )


def get_campaign_publisher_service(session: Session = Depends(get_db_session)) -> CampaignPublisher:
    campaign_repository = SqlAlchemyCampaignRepository(session)
    audit_log = SqlAlchemyAuditLogRepository(session)
    return CampaignPublisher(
        campaign_repository=campaign_repository,
        review_portal=ReviewPortalService(campaign_repository, ReviewPortalRepository(session), audit_log),
        segmentation_service=AudienceSegmentationService(AudienceSegmentationRepository(session)),
        mautic_repository=MauticPublicationRepository(session),
        mautic_sync_repository=MauticSyncRepository(session),
        mautic_connector=MauticConnector(build_mautic_config()),
        audit_log=audit_log,
    )


def get_adoption_measurement_service(session: Session = Depends(get_db_session)) -> AdoptionMeasurementService:
    campaign_repository = SqlAlchemyCampaignRepository(session)
    audit_log = SqlAlchemyAuditLogRepository(session)
    review_repository = ReviewPortalRepository(session)
    return AdoptionMeasurementService(
        campaign_repository=campaign_repository,
        mautic_publications=MauticPublicationRepository(session),
        mautic_sync_repository=MauticSyncRepository(session),
        mapsi_usage_repository=MapsiUsageRepository(session),
        review_repository=review_repository,
        mautic_connector=MauticConnector(build_mautic_config()),
        audit_log=audit_log,
    )


def get_linkedin_oauth_service(session: Session = Depends(get_db_session)) -> LinkedInOAuthService:
    return LinkedInOAuthService(
        connector=LinkedInConnector(build_linkedin_config()),
        repository=LinkedInOAuthTokenRepository(session),
    )


def get_linkedin_organization_resolver(session: Session = Depends(get_db_session)) -> LinkedInOrganizationResolver:
    connector = LinkedInConnector(build_linkedin_config())
    oauth_service = LinkedInOAuthService(connector=connector, repository=LinkedInOAuthTokenRepository(session))
    return LinkedInOrganizationResolver(connector=connector, oauth_service=oauth_service)


def get_linkedin_media_uploader(session: Session = Depends(get_db_session)) -> LinkedInMediaUploader:
    connector = LinkedInConnector(build_linkedin_config())
    oauth_service = LinkedInOAuthService(connector=connector, repository=LinkedInOAuthTokenRepository(session))
    resolver = LinkedInOrganizationResolver(connector=connector, oauth_service=oauth_service)
    return LinkedInMediaUploader(connector=connector, oauth_service=oauth_service, organization_resolver=resolver)


def get_linkedin_post_publisher(session: Session = Depends(get_db_session)) -> LinkedInPostPublisher:
    repository = SqlAlchemyCampaignRepository(session)
    audit_log = SqlAlchemyAuditLogRepository(session)
    connector = LinkedInConnector(build_linkedin_config())
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


def get_oling_news_publisher(session: Session = Depends(get_db_session)) -> OlingNewsPublisher:
    repository = SqlAlchemyCampaignRepository(session)
    audit_log = SqlAlchemyAuditLogRepository(session)
    review_portal = ReviewPortalService(repository, ReviewPortalRepository(session), audit_log)
    return OlingNewsPublisher(
        campaign_repository=repository,
        publication_repository=OlingNewsPublicationRepository(session),
        connector=OlingConnector(build_oling_config()),
        audit_log=audit_log,
        review_portal=review_portal,
    )


def get_linkedin_metrics_collector(session: Session = Depends(get_db_session)) -> LinkedInMetricsCollector:
    repository = SqlAlchemyCampaignRepository(session)
    audit_log = SqlAlchemyAuditLogRepository(session)
    connector = LinkedInConnector(build_linkedin_config())
    oauth_service = LinkedInOAuthService(connector=connector, repository=LinkedInOAuthTokenRepository(session))
    return LinkedInMetricsCollector(
        campaign_repository=repository,
        publication_repository=LinkedInPublicationRepository(session),
        oauth_service=oauth_service,
        connector=connector,
        audit_log=audit_log,
    )


def get_multichannel_content_service(session: Session = Depends(get_db_session)) -> MultichannelContentService:
    backend = _build_editorial_backend()
    repository = SqlAlchemyCampaignRepository(session)
    audit_log = SqlAlchemyAuditLogRepository(session)
    return MultichannelContentService(
        repository=repository,
        review_portal=ReviewPortalService(repository, ReviewPortalRepository(session), audit_log),
        market_strategy_agent=MarketEditorialStrategyAgent(backend),
        newsletter_writer=NewsletterWriterAgent(backend),
        linkedin_writer=LinkedInWriterAgent(backend),
        website_writer=WebsiteArticleWriterAgent(backend),
        seo_quality_agent=SeoQualityAgent(backend),
    )
