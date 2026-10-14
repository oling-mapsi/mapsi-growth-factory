from pathlib import Path

from app.application.ports.connectors import PublisherPort
from app.application.services.editorial_engine_v1 import build_editorial_generation_service
from app.application.services.simple_generation_worker import SimpleGenerationWorker
from app.application.services.simple_campaign_service import CreateSimpleCampaignCommand, PublishSimpleCampaignCommand, SimpleCampaignService
from app.domain.entities import CampaignRun, ContentAsset, Publication, SourceEvidence
from app.domain.errors import ApprovalPrerequisiteError
from app.domain.enums import AssetStatus, CampaignStatus
from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
from app.infrastructure.db.models import SimpleGenerationJobModel
from app.infrastructure.repositories.simple_generation_jobs import SimpleGenerationJobRepository
from app.infrastructure.tasks import InMemoryTaskQueue
from app.knowledge import KnowledgeRepository


class TrackingPublisher(PublisherPort):
    def __init__(self) -> None:
        self.unpublished_asset_ids: list[str] = []

    def validate_configuration(self, channel: str) -> dict:
        return {"channel": channel}

    def create_preview(self, campaign: CampaignRun, asset: ContentAsset) -> dict:
        return {}

    def publish(self, campaign: CampaignRun, asset: ContentAsset) -> Publication:
        raise NotImplementedError

    def update(self, campaign: CampaignRun, asset: ContentAsset) -> Publication:
        raise NotImplementedError

    def unpublish(self, campaign: CampaignRun, asset: ContentAsset) -> bool:
        self.unpublished_asset_ids.append(asset.id)
        return True

    def get_publication_status(self, campaign: CampaignRun, asset: ContentAsset) -> dict:
        return {}

    def collect_metrics(self, campaign: CampaignRun, asset: ContentAsset) -> dict:
        return {}


def test_delete_simple_campaign_does_not_unpublish_published_assets(session) -> None:
    repository = SqlAlchemyCampaignRepository(session)
    publisher = TrackingPublisher()
    campaign = CampaignRun(
        name="Campagne archivee",
        objective="Supprimer l'ancienne campagne",
        workflow_kind="SIMPLE",
        campaign_type="MAPSI_MARKETING",
        selected_channels=["mapsi_site", "oling_site", "linkedin_manual"],
        status=CampaignStatus.PUBLISHED,
        content_assets=[
            ContentAsset(
                id="asset-mapsi",
                campaign_run_id="campaign-1",
                asset_type="mapsi_news_article",
                channel="mapsi_site",
                title="Article MAPSI",
                content_html="<p>Publie</p>",
                content_text="Publie",
                status=AssetStatus.PUBLISHED,
            ),
            ContentAsset(
                id="asset-oling",
                campaign_run_id="campaign-1",
                asset_type="oling_news_article",
                channel="oling",
                title="Article Oling",
                content_html="<p>Publie</p>",
                content_text="Publie",
                status=AssetStatus.PUBLISHED,
            ),
            ContentAsset(
                id="asset-linkedin",
                campaign_run_id="campaign-1",
                asset_type="linkedin_company_post",
                channel="linkedin_manual",
                title="Post LinkedIn",
                content_text="Pret",
                status=AssetStatus.PUBLISHED,
            ),
        ],
    )
    saved = repository.add(campaign)
    for asset in saved.content_assets:
        asset.campaign_run_id = saved.id

    service = SimpleCampaignService(
        repository=repository,
        publisher=publisher,
        audit_log=SqlAlchemyAuditLogRepository(session),
        task_queue=InMemoryTaskQueue(),
        project_root=Path(__file__).resolve().parents[2],
    )

    try:
        service.delete_campaign(saved.id)
    except Exception as exc:
        assert "never published" in str(exc)
    else:
        raise AssertionError("delete should reject published campaigns")

    assert publisher.unpublished_asset_ids == []
    assert repository.get(saved.id) is not None


def test_unpublish_simple_campaign_is_explicit(session) -> None:
    repository = SqlAlchemyCampaignRepository(session)
    publisher = TrackingPublisher()
    campaign = CampaignRun(
        name="Campagne publiee",
        objective="Depublier explicitement",
        workflow_kind="SIMPLE",
        campaign_type="MAPSI_MARKETING",
        selected_channels=["mapsi_site", "oling_site"],
        status=CampaignStatus.PUBLISHED,
        content_assets=[
            ContentAsset(id="asset-mapsi", campaign_run_id="campaign-2", channel="mapsi_site", title="Article", content_text="Publie", status=AssetStatus.PUBLISHED),
            ContentAsset(id="asset-oling", campaign_run_id="campaign-2", channel="oling", title="Article", content_text="Publie", status=AssetStatus.PUBLISHED),
        ],
    )
    for asset in campaign.content_assets:
        asset.ensure_content_hash()
        asset.approved_content_hash = asset.content_hash
        asset.approved_by = "tester"
        asset.status = AssetStatus.PUBLISHED
    saved = repository.add(campaign)
    service = SimpleCampaignService(
        repository=repository,
        publisher=publisher,
        audit_log=SqlAlchemyAuditLogRepository(session),
        task_queue=InMemoryTaskQueue(),
        project_root=Path(__file__).resolve().parents[2],
    )

    service.unpublish_campaign(saved.id, PublishSimpleCampaignCommand(channels=["mapsi_site"]), actor="tester")

    assert publisher.unpublished_asset_ids == ["asset-mapsi"]


def test_approval_blocks_failed_editorial_quality(session) -> None:
    campaign = CampaignRun(
        id="campaign-quality",
        name="Qualite",
        objective="Verifier",
        workflow_kind="SIMPLE",
        campaign_type="OLING",
        selected_channels=["oling_site"],
        status=CampaignStatus.READY_FOR_REVIEW,
        source_evidences=[SourceEvidence(campaign_run_id="campaign-quality", source_system="knowledge", evidence_type="source", reference="ref")],
        content_assets=[
            ContentAsset(
                id="asset-quality",
                campaign_run_id="campaign-quality",
                asset_type="oling_news_article",
                channel="oling",
                title="Article",
                content_text="Texte",
                status=AssetStatus.REVIEWED,
                results={
                    "editorial_quality": {
                        "passed": False,
                        "issues": [{"code": "claim_unknown_source", "severity": "error"}],
                    }
                },
            )
        ],
    )

    try:
        campaign.approve_asset("asset-quality", "ok", "tester")
    except ApprovalPrerequisiteError as exc:
        assert "blocking editorial quality" in str(exc)
    else:
        raise AssertionError("approval should fail")


def test_simple_generation_is_enqueued_and_processed_once(session) -> None:
    repository = SqlAlchemyCampaignRepository(session)
    jobs = SimpleGenerationJobRepository(session)
    service = SimpleCampaignService(
        repository=repository,
        publisher=TrackingPublisher(),
        audit_log=SqlAlchemyAuditLogRepository(session),
        task_queue=InMemoryTaskQueue(),
        project_root=Path(__file__).resolve().parents[2],
        editorial_service=build_editorial_generation_service(session, force_mode="simulated"),
        knowledge_repository=KnowledgeRepository(session, root=Path(__file__).resolve().parents[2] / "knowledge"),
        generation_jobs=jobs,
    )
    campaign = service.create_campaign(
        CreateSimpleCampaignCommand(
            name="Async",
            campaign_type="OLING",
            theme="ERP",
            selected_channels=["oling_site"],
        )
    )

    queued = service.generate_campaign(campaign.id)
    duplicate = service.generate_campaign(campaign.id)
    assert queued.status is CampaignStatus.GENERATING
    assert duplicate.status is CampaignStatus.GENERATING
    assert session.query(SimpleGenerationJobModel).count() == 1

    worker = SimpleGenerationWorker(jobs, service)
    assert worker.process_one() is True

    generated = repository.get(campaign.id)
    assert generated.status is CampaignStatus.READY_FOR_REVIEW
    assert len(generated.content_assets) == 1
    assert jobs.latest_for_campaign(campaign.id).status == "SUCCEEDED"


def test_failed_simple_generation_can_be_resumed_without_duplicate_job(session) -> None:
    repository = SqlAlchemyCampaignRepository(session)
    jobs = SimpleGenerationJobRepository(session)
    service = SimpleCampaignService(
        repository=repository,
        publisher=TrackingPublisher(),
        audit_log=SqlAlchemyAuditLogRepository(session),
        task_queue=InMemoryTaskQueue(),
        project_root=Path(__file__).resolve().parents[2],
        editorial_service=build_editorial_generation_service(session, force_mode="simulated"),
        knowledge_repository=KnowledgeRepository(session, root=Path(__file__).resolve().parents[2] / "knowledge"),
        generation_jobs=jobs,
    )
    campaign = service.create_campaign(
        CreateSimpleCampaignCommand(
            name="Resume",
            campaign_type="OLING",
            theme="ERP",
            selected_channels=["oling_site"],
        )
    )
    service.generate_campaign(campaign.id)
    job = jobs.latest_for_campaign(campaign.id)
    jobs.mark_failed(job.id, RuntimeError("simulated openai failure"))

    service.generate_campaign(campaign.id)

    assert session.query(SimpleGenerationJobModel).count() == 1
    resumed = jobs.latest_for_campaign(campaign.id)
    assert resumed.id == job.id
    assert resumed.status == "PENDING"
