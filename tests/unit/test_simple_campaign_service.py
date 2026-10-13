from pathlib import Path

from app.application.ports.connectors import PublisherPort
from app.application.services.simple_campaign_service import PublishSimpleCampaignCommand, SimpleCampaignService
from app.domain.entities import CampaignRun, ContentAsset, Publication
from app.domain.enums import AssetStatus, CampaignStatus
from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
from app.infrastructure.tasks import InMemoryTaskQueue


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
