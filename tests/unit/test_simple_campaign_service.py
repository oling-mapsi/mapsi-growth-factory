from pathlib import Path
from datetime import UTC, datetime, timedelta

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


def test_new_article_generation_finishes_images_and_seo_without_touching_existing_articles(session):
    from app.application.services.growth_image_generation import GrowthImageResult
    from app.application.services.growth_seo_geo import GrowthSeoGeoResult
    calls = []
    class Images:
        def generate(self, **kwargs):
            calls.append(('image', kwargs['locale']))
            return GrowthImageResult(model='fixture', prompt='fixture', alt_text='Illustration '+kwargs['locale'],
                storage_path='storage/fixture-'+kwargs['locale']+'.png', data_url='', output_format='png', duration_ms=1, tokens={})
    class Seo:
        def prepare(self, **kwargs):
            calls.append(('seo', kwargs['locale']))
            return GrowthSeoGeoResult(status='READY', checks=[], metadata={'locale':kwargs['locale']}, internal_links=[], html=kwargs['html'])
    repository = SqlAlchemyCampaignRepository(session)
    jobs = SimpleGenerationJobRepository(session)
    service = SimpleCampaignService(repository, TrackingPublisher(), SqlAlchemyAuditLogRepository(session), InMemoryTaskQueue(),
        project_root=Path(__file__).resolve().parents[2], editorial_service=build_editorial_generation_service(session, force_mode='simulated'),
        knowledge_repository=KnowledgeRepository(session), image_service=Images(), seo_geo_service=Seo(), generation_jobs=jobs)
    campaign = service.create_campaign(CreateSimpleCampaignCommand(name='Complete fixture', campaign_type='OLING', theme='ERP', selected_channels=['oling_site','mapsi_site']))
    service.generate_campaign(campaign.id)
    worker = SimpleGenerationWorker(jobs, service)
    assert worker.process_one()
    assert jobs.latest_for_campaign(campaign.id).status == 'SUCCEEDED'
    assets = repository.get(campaign.id).content_assets
    assert len(assets) == 4
    assert len(calls) == 8
    assert all(asset.results['image'] and asset.results['seo_geo']['status'] == 'READY' for asset in assets)
    assert all('<figure>' in asset.content_html and not asset.approved_content_hash for asset in assets)
    hashes = {asset.id: asset.content_hash for asset in assets}
    service.generate_campaign(campaign.id)
    worker.process_one()
    assert len(calls) == 8
    assert {asset.id:asset.content_hash for asset in repository.get(campaign.id).content_assets} == hashes


def test_human_edit_can_be_validated_but_real_source_failures_remain_blocking(session):
    import pytest
    from app.application.services.simple_campaign_service import UpdateSimpleAssetCommand, ApproveSimpleAssetCommand
    from app.domain.errors import InvalidStateTransitionError
    repository = SqlAlchemyCampaignRepository(session)
    service = SimpleCampaignService(repository, TrackingPublisher(), SqlAlchemyAuditLogRepository(session), InMemoryTaskQueue(),
        project_root=Path(__file__).resolve().parents[2], editorial_service=build_editorial_generation_service(session, force_mode='simulated'),
        knowledge_repository=KnowledgeRepository(session))
    campaign = service.create_campaign(CreateSimpleCampaignCommand(name='Human editing fixture', campaign_type='OLING', theme='ERP', selected_channels=['oling_site']))
    generated = service.generate_campaign(campaign.id)
    asset = generated.content_assets[0]
    edited = service.update_asset(campaign.id, asset.id, UpdateSimpleAssetCommand(expected_version=asset.content_version,
        content_html=asset.content_html+'<p>Le cadrage se discute avec les equipes.</p>'))
    current = next(item for item in edited.content_assets if item.id == asset.id)
    assert not current.results['editorial_quality']['passed']
    with pytest.raises(InvalidStateTransitionError):
        service.approve_asset(campaign.id, asset.id, ApproveSimpleAssetCommand(expected_version=current.content_version, actor='fixture-admin'))
    approved = service.approve_asset(campaign.id, asset.id, ApproveSimpleAssetCommand(expected_version=current.content_version,
        actor='fixture-admin', confirm_editorial_review=True))
    current = next(item for item in approved.content_assets if item.id == asset.id)
    assert current.status is AssetStatus.APPROVED
    assert current.results['human_editorial_review']['version'] == current.content_version
    assert current.approved_content_hash == current.content_hash
    other = next(item for item in approved.content_assets if item.id != asset.id)
    other.results['editorial_quality'] = {'passed':False,'issues':[{'code':'claim_without_source','severity':'error','message':'Missing source'}]}
    repository.save(approved)
    with pytest.raises(InvalidStateTransitionError):
        service.approve_asset(campaign.id, other.id, ApproveSimpleAssetCommand(expected_version=other.content_version,
            actor='fixture-admin', confirm_editorial_review=True))


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
    assert len(generated.content_assets) == 3
    assert {asset.locale for asset in generated.content_assets if asset.channel == "oling"} == {"fr-FR", "en-US", "es-ES"}
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


def test_stale_running_simple_generation_can_be_resumed(session) -> None:
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
            name="Stale",
            campaign_type="OLING",
            theme="ERP",
            selected_channels=["oling_site"],
        )
    )
    service.generate_campaign(campaign.id)
    job = jobs.claim_next()
    job.updated_at = datetime.now(UTC) - timedelta(minutes=11)
    session.commit()

    service.generate_campaign(campaign.id)

    resumed = jobs.latest_for_campaign(campaign.id)
    assert resumed.id == job.id
    assert resumed.status == "PENDING"
