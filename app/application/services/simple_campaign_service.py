from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
import re
import time
from mimetypes import guess_type
from uuid import NAMESPACE_URL, uuid4, uuid5

from app.application.models.editorial_v1 import (
    EditorialBuilderSelection,
    EditorialChannelVariantContext,
    EditorialEmailMessage,
    EditorialGenerationContext,
    EditorialGenerationResult,
    EditorialLinkedInPost,
    MapsiFeatureContext,
    OlingPracticeContext,
    ProductChangeContext,
)
from app.application.ports.audit import AuditLogPort
from app.application.ports.connectors import PublisherPort
from app.application.ports.repositories import CampaignRepositoryPort
from app.application.ports.tasks import TaskQueuePort
from app.application.services.editorial_engine_v1 import EditorialGenerationService
from app.application.services.growth_image_generation import GrowthImageGenerationService
from app.application.services.growth_seo_geo import GrowthSeoGeoService
from app.application.services.html_sanitizer import HtmlSanitizer
from app.core.config import get_settings
from app.domain.entities import CampaignRun, ContentAsset, EditorialBrief, ProductChange, Publication, SourceEvidence
from app.domain.enums import AssetStatus, CampaignStatus
from app.domain.errors import CampaignNotFoundError, CampaignPublicationForbiddenError, InvalidStateTransitionError
from app.infrastructure.repositories.editorial_source_packs import EditorialSourcePackRepository
from app.infrastructure.repositories.simple_generation_jobs import SimpleGenerationJobRepository
from app.infrastructure.observability import structured_log
from app.knowledge import KnowledgeRepository
from app.knowledge.models import MapsiFeature, OlingPractice


SIMPLE_WORKFLOW_KIND = "SIMPLE"
SIMPLE_CAMPAIGN_TYPES = {"MAPSI_USERS", "MAPSI_MARKETING", "OLING"}
ALL_SIMPLE_CHANNELS = {"mapsi_site", "oling_site", "linkedin_manual", "email_manual"}
SIMPLE_CHANNEL_RULES: dict[str, set[str]] = {
    "MAPSI_USERS": ALL_SIMPLE_CHANNELS,
    "MAPSI_MARKETING": ALL_SIMPLE_CHANNELS,
    "OLING": ALL_SIMPLE_CHANNELS,
}
CHANNEL_TO_INTERNAL = {
    "mapsi_site": "mapsi_site",
    "oling_site": "oling",
    "linkedin_manual": "linkedin_manual",
    "email_manual": "email_manual",
}
CHANNEL_FROM_INTERNAL = {value: key for key, value in CHANNEL_TO_INTERNAL.items()}


@dataclass
class CreateSimpleCampaignCommand:
    name: str
    campaign_type: str
    selected_channels: list[str]
    theme: str = ""
    brief: str = ""


@dataclass
class UpdateSimpleAssetCommand:
    title: str | None = None
    content_html: str | None = None
    content_text: str | None = None
    expected_version: int | None = None


@dataclass
class GenerateSimpleImageCommand:
    visual_brief: str = ""
    expected_version: int | None = None


@dataclass
class ReviewSimpleAssetCommand:
    comment: str = ""
    actor: str = "studio-simple"
    expected_version: int | None = None


@dataclass
class ApproveSimpleAssetCommand:
    comment: str = ""
    actor: str = "studio-simple"
    expected_version: int | None = None


@dataclass
class PublishSimpleCampaignCommand:
    channels: list[str]


class ManualLinkedInPublisher(PublisherPort):
    def validate_configuration(self, channel: str) -> dict:
        return {"channel": channel, "enabled": True, "manual": True}

    def create_preview(self, campaign: CampaignRun, asset: ContentAsset) -> dict:
        return {"campaign_id": campaign.id, "asset_id": asset.id, "channel": asset.channel, "preview": asset.content_text}

    def publish(self, campaign: CampaignRun, asset: ContentAsset) -> Publication:
        return Publication(
            campaign_run_id=campaign.id,
            content_asset_id=asset.id,
            channel=asset.channel,
            external_reference=f"linkedin-manual:{asset.id}",
            external_url="",
        )

    def update(self, campaign: CampaignRun, asset: ContentAsset) -> Publication:
        return self.publish(campaign, asset)

    def unpublish(self, campaign: CampaignRun, asset: ContentAsset) -> bool:
        return True

    def get_publication_status(self, campaign: CampaignRun, asset: ContentAsset) -> dict:
        return {"campaign_id": campaign.id, "asset_id": asset.id, "status": "manual"}

    def collect_metrics(self, campaign: CampaignRun, asset: ContentAsset) -> dict:
        return {"campaign_id": campaign.id, "asset_id": asset.id, "status": "manual"}


class ManualEmailPublisher(PublisherPort):
    def validate_configuration(self, channel: str) -> dict:
        return {"channel": channel, "enabled": True, "manual": True}

    def create_preview(self, campaign: CampaignRun, asset: ContentAsset) -> dict:
        return {"campaign_id": campaign.id, "asset_id": asset.id, "channel": asset.channel, "preview": asset.content_text}

    def publish(self, campaign: CampaignRun, asset: ContentAsset) -> Publication:
        return Publication(
            campaign_run_id=campaign.id,
            content_asset_id=asset.id,
            channel=asset.channel,
            external_reference=f"email-manual:{asset.id}",
            external_url="",
        )

    def update(self, campaign: CampaignRun, asset: ContentAsset) -> Publication:
        return self.publish(campaign, asset)

    def unpublish(self, campaign: CampaignRun, asset: ContentAsset) -> bool:
        return True

    def get_publication_status(self, campaign: CampaignRun, asset: ContentAsset) -> dict:
        return {"campaign_id": campaign.id, "asset_id": asset.id, "status": "manual"}

    def collect_metrics(self, campaign: CampaignRun, asset: ContentAsset) -> dict:
        return {"campaign_id": campaign.id, "asset_id": asset.id, "status": "manual"}


class SimpleCampaignService:
    def __init__(
        self,
        repository: CampaignRepositoryPort,
        publisher: PublisherPort,
        audit_log: AuditLogPort,
        task_queue: TaskQueuePort,
        *,
        project_root: Path,
        editorial_service: EditorialGenerationService | None = None,
        knowledge_repository: KnowledgeRepository | None = None,
        source_pack_repository: EditorialSourcePackRepository | None = None,
        image_service: GrowthImageGenerationService | None = None,
        seo_geo_service: GrowthSeoGeoService | None = None,
        generation_jobs: SimpleGenerationJobRepository | None = None,
        require_real_editorial_backend: bool = False,
    ) -> None:
        self.repository = repository
        self.publisher = publisher
        self.audit_log = audit_log
        self.task_queue = task_queue
        self.project_root = project_root
        self.editorial_service = editorial_service
        self.knowledge_repository = knowledge_repository
        self.source_pack_repository = source_pack_repository
        self.image_service = image_service
        self.seo_geo_service = seo_geo_service or GrowthSeoGeoService()
        self.generation_jobs = generation_jobs
        self.require_real_editorial_backend = require_real_editorial_backend

    def create_campaign(self, command: CreateSimpleCampaignCommand) -> CampaignRun:
        campaign_type = command.campaign_type.strip().upper()
        self._validate_campaign_type(campaign_type)
        selected_channels = self._normalize_selected_channels(campaign_type, command.selected_channels)
        theme = self._resolve_theme(campaign_type, command.theme)
        campaign = CampaignRun(
            name=command.name.strip(),
            objective=command.brief.strip() or theme,
            theme=theme,
            campaign_type=campaign_type,
            workflow_kind=SIMPLE_WORKFLOW_KIND,
            selected_channels=selected_channels,
        )
        saved = self.repository.add(campaign)
        self.audit_log.append(
            saved.id,
            "simple_campaign.created",
            {"campaign_type": saved.campaign_type, "theme": saved.theme, "selected_channels": saved.selected_channels},
            actor_source="studio-simple",
            previous_state={},
            new_state={"status": saved.status.value},
            result="SUCCESS",
        )
        return saved

    def generate_asset_image(self, campaign_id: str, asset_id: str, command: GenerateSimpleImageCommand) -> CampaignRun:
        if self.image_service is None:
            raise InvalidStateTransitionError("Image generation is not configured.")
        campaign = self.get_campaign(campaign_id)
        asset = self._find_asset(campaign, asset_id)
        if command.expected_version is not None:
            asset.assert_expected_version(command.expected_version)
        external_channel = self.external_channel(asset.channel)
        result = self.image_service.generate(
            channel=external_channel,
            title=asset.title,
            content_text=asset.content_text,
            visual_brief=command.visual_brief or str((asset.results or {}).get("illustration_suggestion", "")),
        )
        asset.results = dict(asset.results or {})
        asset.results["image"] = {
            "model": result.model,
            "prompt": result.prompt,
            "alt_text": result.alt_text,
            "storage_path": result.storage_path,
            "image_url": f"/studio-simple/assets/{asset.id}/image",
            "output_format": result.output_format,
            "duration_ms": result.duration_ms,
            "tokens": result.tokens,
        }
        saved = self.repository.save(campaign)
        self.audit_log.append(
            saved.id,
            "simple_campaign.asset_image_generated",
            {"asset_id": asset_id, "channel": asset.channel, "model": result.model, "storage_path": result.storage_path},
            actor_source="studio-simple",
            previous_state={},
            new_state={"status": saved.status.value},
            result="SUCCESS",
        )
        return saved

    def get_asset_image_reference(self, asset_id: str) -> tuple[Path | None, str, str]:
        for campaign in self.repository.list():
            for asset in campaign.content_assets:
                if asset.id != asset_id:
                    continue
                image = dict((asset.results or {}).get("image") or {})
                storage_path = str(image.get("storage_path") or "")
                if storage_path:
                    resolved = (self.project_root / storage_path).resolve()
                    root = self.project_root.resolve()
                    if root == resolved or root in resolved.parents:
                        media_type = str(guess_type(str(resolved))[0] or "image/png")
                        return resolved, media_type, str(image.get("alt_text") or "")
                return None, "", str(image.get("data_url") or "")
        raise CampaignNotFoundError(f"Asset {asset_id} not found.")

    def prepare_asset_seo_geo(self, campaign_id: str, asset_id: str, expected_version: int | None = None) -> CampaignRun:
        campaign = self.get_campaign(campaign_id)
        asset = self._find_asset(campaign, asset_id)
        if expected_version is not None:
            asset.assert_expected_version(expected_version)
        image = dict((asset.results or {}).get("image") or {})
        result = self.seo_geo_service.prepare(
            channel=self.external_channel(asset.channel),
            title=asset.title,
            html=asset.content_html or asset.body,
            text=asset.content_text,
            image_alt=str(image.get("alt_text") or ""),
        )
        asset.results = dict(asset.results or {})
        asset.results["seo_geo"] = {
            "status": result.status,
            "checks": result.checks,
            "metadata": result.metadata,
            "internal_links": result.internal_links,
        }
        asset.update_draft(content_html=HtmlSanitizer.sanitize(result.html), content_text=asset.content_text)
        saved = self.repository.save(campaign)
        self.audit_log.append(
            saved.id,
            "simple_campaign.asset_seo_geo_prepared",
            {"asset_id": asset_id, "channel": asset.channel, "status": result.status, "link_count": len(result.internal_links)},
            actor_source="studio-simple",
            previous_state={},
            new_state={"status": saved.status.value},
            result="SUCCESS",
        )
        return saved

    def list_campaigns(self) -> list[CampaignRun]:
        return [
            campaign
            for campaign in self.repository.list()
            if campaign.workflow_kind == SIMPLE_WORKFLOW_KIND and campaign.status is not CampaignStatus.DELETED
        ]

    def get_campaign(self, campaign_id: str) -> CampaignRun:
        campaign = self.repository.get(campaign_id)
        if campaign is None:
            raise CampaignNotFoundError(f"Campaign {campaign_id} not found.")
        self._assert_simple_campaign(campaign)
        if campaign.status is CampaignStatus.DELETED:
            raise CampaignNotFoundError(f"Campaign {campaign_id} not found.")
        return campaign

    def generate_campaign(self, campaign_id: str) -> CampaignRun:
        if self.generation_jobs is not None:
            return self.enqueue_generation(campaign_id)
        return self.run_generation(campaign_id)

    def enqueue_generation(self, campaign_id: str) -> CampaignRun:
        campaign = self.get_campaign(campaign_id)
        self._assert_simple_campaign(campaign)
        previous_status = campaign.status.value
        job = self.generation_jobs.ensure_pending(campaign.id)
        if campaign.status is CampaignStatus.GENERATING and job.status == "RUNNING":
            return campaign
        campaign.status = CampaignStatus.GENERATING
        saved = self.repository.save(campaign)
        self.audit_log.append(
            saved.id,
            "simple_campaign.generation_enqueued",
            {"channels": saved.selected_channels},
            actor_source="studio-simple",
            previous_state={"status": previous_status},
            new_state={"status": saved.status.value},
            result="SUCCESS",
        )
        return saved

    def run_generation(self, campaign_id: str, *, stage_callback=None) -> CampaignRun:
        campaign = self.get_campaign(campaign_id)
        self._assert_simple_campaign(campaign)
        started = time.perf_counter()
        previous_status = campaign.status.value
        campaign.status = CampaignStatus.GENERATING
        self.repository.save(campaign)
        structured_log(
            "simple_campaign.generation.started",
            campaign_id=campaign.id,
            campaign_type=campaign.campaign_type,
            channels=campaign.selected_channels,
        )
        try:
            brief, assets, evidence = self._build_generation_payload(campaign, stage_callback=stage_callback)
        except Exception as exc:
            campaign.status = CampaignStatus.FAILED
            saved = self.repository.save(campaign)
            duration_ms = max(1, int((time.perf_counter() - started) * 1000))
            self.audit_log.append(
                saved.id,
                "simple_campaign.generation_failed",
                {"error_type": type(exc).__name__, "duration_ms": duration_ms},
                actor_source="studio-simple",
                previous_state={"status": previous_status},
                new_state={"status": saved.status.value},
                result="FAILURE",
            )
            structured_log(
                "simple_campaign.generation.failed",
                campaign_id=saved.id,
                error_type=type(exc).__name__,
                duration_ms=duration_ms,
            )
            raise
        campaign.source_evidences = evidence
        campaign.mark_generated(brief, assets)
        campaign._sync_status_from_assets()
        saved = self.repository.save(campaign)
        duration_ms = max(1, int((time.perf_counter() - started) * 1000))
        self.audit_log.append(
            saved.id,
            "simple_campaign.generated",
            {"asset_count": len(saved.content_assets), "channels": saved.selected_channels, "duration_ms": duration_ms},
            actor_source="studio-simple",
            previous_state={"status": previous_status},
            new_state={"status": saved.status.value},
            result="SUCCESS",
        )
        structured_log("simple_campaign.generation.completed", campaign_id=saved.id, asset_count=len(saved.content_assets), duration_ms=duration_ms)
        return saved

    def _build_generation_payload(self, campaign: CampaignRun, *, stage_callback=None) -> tuple[EditorialBrief, list[ContentAsset], list[SourceEvidence]]:
        if self.require_real_editorial_backend:
            self._assert_real_editorial_backend()
        is_regeneration = bool(campaign.content_assets)
        if self.editorial_service is None or self.knowledge_repository is None:
            raise InvalidStateTransitionError("Simple studio requires an editorial service and a knowledge repository.")

        results: dict[str, EditorialGenerationResult] = {}
        if "mapsi_site" in campaign.selected_channels:
            if stage_callback:
                stage_callback("DRAFTING")
            mapsi_context = self._build_mapsi_context(campaign, destination_site="mapsi.fr", article_type="MAPSI_PRODUCT")
            if is_regeneration:
                mapsi_context.published_topic_history = []
            results["mapsi_site"] = self.editorial_service.generate_from_context(
                context=mapsi_context,
                selection=self._mapsi_selection(campaign),
                allow_failed_quality=True,
                progress_callback=stage_callback,
            )
        if "oling_site" in campaign.selected_channels:
            if stage_callback:
                stage_callback("DRAFTING")
            if campaign.campaign_type == "OLING":
                oling_context = self._build_oling_context(campaign)
                if is_regeneration:
                    oling_context.published_topic_history = []
                results["oling_site"] = self.editorial_service.generate_from_context(
                    context=oling_context,
                    selection=self._oling_selection(campaign),
                    allow_failed_quality=True,
                    progress_callback=stage_callback,
                )
            else:
                consulting_context = self._build_mapsi_context(campaign, destination_site="oling.fr", article_type="MAPSI_CONSULTING")
                if is_regeneration:
                    consulting_context.published_topic_history = []
                results["oling_site"] = self.editorial_service.generate_from_context(
                    context=consulting_context,
                    selection=self._mapsi_selection(campaign),
                    allow_failed_quality=True,
                    progress_callback=stage_callback,
                )

        primary_result = results.get("mapsi_site") or results.get("oling_site")
        if primary_result is None:
            if stage_callback:
                stage_callback("DRAFTING")
            if campaign.campaign_type == "OLING":
                internal_context = self._build_oling_context(campaign)
                internal_selection = self._oling_selection(campaign)
            else:
                internal_context = self._build_mapsi_context(campaign, destination_site="mapsi.fr", article_type="MAPSI_PRODUCT")
                internal_selection = self._mapsi_selection(campaign)
            if is_regeneration:
                internal_context.published_topic_history = []
            primary_result = self.editorial_service.generate_from_context(
                context=internal_context,
                selection=internal_selection,
                allow_failed_quality=True,
                progress_callback=stage_callback,
            )

        if stage_callback:
            stage_callback("QUALITY_CHECK")
        evidence = self._collect_editorial_evidence(campaign.id, [result.context for result in [*results.values(), primary_result]])
        assets: list[ContentAsset] = []
        if "mapsi_site" in results:
            assets.append(self._asset_from_editorial_result(campaign, "mapsi_site", results["mapsi_site"], evidence))
        if "oling_site" in results:
            assets.append(self._asset_from_editorial_result(campaign, "oling_site", results["oling_site"], evidence))
        if "linkedin_manual" in campaign.selected_channels:
            assets.append(self._linkedin_asset_from_editorial(campaign, primary_result, evidence))
        if "email_manual" in campaign.selected_channels:
            assets.append(self._email_asset_from_editorial(campaign, primary_result, evidence))
        brief = EditorialBrief(
            campaign_run_id=campaign.id,
            title=primary_result.record.article.title,
            summary=primary_result.record.article.excerpt,
        )
        return brief, assets, evidence

    def update_asset(self, campaign_id: str, asset_id: str, command: UpdateSimpleAssetCommand) -> CampaignRun:
        campaign = self.get_campaign(campaign_id)
        self._assert_simple_campaign(campaign)
        asset = self._find_asset(campaign, asset_id)
        if command.expected_version is not None:
            asset.assert_expected_version(command.expected_version)
        asset.update_draft(
            title=command.title,
            content_html=HtmlSanitizer.sanitize(command.content_html),
            content_text=command.content_text,
        )
        campaign._sync_status_from_assets()
        saved = self.repository.save(campaign)
        self.audit_log.append(
            saved.id,
            "simple_campaign.asset_updated",
            {"asset_id": asset_id, "channel": asset.channel, "version": asset.content_version},
            actor_source="studio-simple",
            previous_state={},
            new_state={"status": saved.status.value},
            result="SUCCESS",
        )
        return saved

    def review_asset(self, campaign_id: str, asset_id: str, command: ReviewSimpleAssetCommand) -> CampaignRun:
        campaign = self.get_campaign(campaign_id)
        self._assert_simple_campaign(campaign)
        asset = self._find_asset(campaign, asset_id)
        if command.expected_version is not None:
            asset.assert_expected_version(command.expected_version)
        if asset.status not in {AssetStatus.READY_FOR_REVIEW, AssetStatus.CHANGES_REQUESTED, AssetStatus.DRAFT, AssetStatus.REVIEWED}:
            raise InvalidStateTransitionError(f"Asset {asset.id} cannot be reviewed from {asset.status.value}.")
        asset.ensure_content_hash()
        asset.status = AssetStatus.REVIEWED
        campaign._sync_status_from_assets()
        saved = self.repository.save(campaign)
        self.audit_log.append(
            saved.id,
            "simple_campaign.asset_reviewed",
            {"asset_id": asset_id, "channel": asset.channel, "version": asset.content_version, "comment": command.comment},
            actor_source=command.actor,
            previous_state={},
            new_state={"status": saved.status.value},
            result="SUCCESS",
        )
        return saved

    def approve_asset(self, campaign_id: str, asset_id: str, command: ApproveSimpleAssetCommand) -> CampaignRun:
        campaign = self.get_campaign(campaign_id)
        self._assert_simple_campaign(campaign)
        asset = self._find_asset(campaign, asset_id)
        if command.expected_version is not None:
            asset.assert_expected_version(command.expected_version)
        if asset.status not in {AssetStatus.REVIEWED, AssetStatus.READY_FOR_REVIEW, AssetStatus.APPROVED}:
            raise InvalidStateTransitionError(f"Asset {asset.id} must be reviewed before approval.")
        quality = dict((asset.results or {}).get("editorial_quality") or {})
        blocking_issues = [
            item
            for item in quality.get("issues", [])
            if isinstance(item, dict) and item.get("severity") == "error"
        ]
        if quality and not quality.get("passed", False):
            raise InvalidStateTransitionError("Asset has blocking editorial quality issues.")
        if blocking_issues:
            raise InvalidStateTransitionError("Asset has blocking editorial quality issues.")
        campaign.approve_asset(asset_id, command.comment, command.actor)
        saved = self.repository.save(campaign)
        self.audit_log.append(
            saved.id,
            "simple_campaign.asset_approved",
            {"asset_id": asset_id, "channel": asset.channel, "version": asset.content_version, "approved_by": command.actor},
            actor_source=command.actor,
            previous_state={},
            new_state={"status": saved.status.value},
            result="SUCCESS",
        )
        return saved

    def publish_campaign(self, campaign_id: str, command: PublishSimpleCampaignCommand) -> CampaignRun:
        campaign = self.get_campaign(campaign_id)
        self._assert_simple_campaign(campaign)
        channels = self._normalize_selected_channels(campaign.campaign_type, command.channels)
        for channel in channels:
            internal_channel = CHANNEL_TO_INTERNAL[channel]
            assets = [
                asset
                for asset in campaign.content_assets
                if asset.channel == internal_channel and asset.status in {AssetStatus.APPROVED, AssetStatus.PUBLISHED}
            ]
            if not assets:
                raise CampaignPublicationForbiddenError(
                    f"Campaign {campaign.id} has no approved asset for channel {channel}."
                )
            for asset in assets:
                asset.ensure_content_hash()
                if not asset.approved_content_hash or asset.approved_content_hash != asset.content_hash:
                    raise CampaignPublicationForbiddenError(
                        f"Asset {asset.id} version {asset.content_version} is not approved for publication."
                    )
                if asset.status is AssetStatus.PUBLISHED:
                    continue
                publication = self.publisher.publish(campaign, asset)
                campaign.publish(publication)
        saved = self.repository.save(campaign)
        self.audit_log.append(
            saved.id,
            "simple_campaign.published",
            {"channels": channels, "publication_count": len(saved.publications)},
            actor_source="studio-simple",
            previous_state={},
            new_state={"status": saved.status.value},
            result="SUCCESS",
        )
        return saved

    def delete_campaign(self, campaign_id: str) -> None:
        campaign = self.get_campaign(campaign_id)
        self._assert_simple_campaign(campaign)
        if campaign.publications or any(asset.status is AssetStatus.PUBLISHED for asset in campaign.content_assets):
            raise CampaignPublicationForbiddenError("Only campaigns that were never published can be deleted.")
        previous_status = campaign.status.value
        campaign.status = CampaignStatus.DELETED
        saved = self.repository.save(campaign)
        self.audit_log.append(
            saved.id,
            "simple_campaign.deleted",
            {},
            actor_source="studio-simple",
            previous_state={"status": previous_status},
            new_state={"status": saved.status.value},
            result="SUCCESS",
        )

    def archive_campaign(self, campaign_id: str, *, actor: str = "studio-simple") -> CampaignRun:
        campaign = self.get_campaign(campaign_id)
        self._assert_simple_campaign(campaign)
        previous_status = campaign.status.value
        campaign.status = CampaignStatus.ARCHIVED
        saved = self.repository.save(campaign)
        self.audit_log.append(
            saved.id,
            "simple_campaign.archived",
            {},
            actor_source=actor,
            previous_state={"status": previous_status},
            new_state={"status": saved.status.value},
            result="SUCCESS",
        )
        return saved

    def unpublish_campaign(self, campaign_id: str, command: PublishSimpleCampaignCommand, *, actor: str = "studio-simple") -> CampaignRun:
        campaign = self.get_campaign(campaign_id)
        self._assert_simple_campaign(campaign)
        channels = self._normalize_selected_channels(campaign.campaign_type, command.channels)
        unpublished_channels: list[str] = []
        for channel in channels:
            internal_channel = CHANNEL_TO_INTERNAL[channel]
            for asset in campaign.content_assets:
                if asset.channel != internal_channel or asset.status is not AssetStatus.PUBLISHED:
                    continue
                self.publisher.unpublish(campaign, asset)
                asset.status = AssetStatus.APPROVED
                asset.published_at = None
                unpublished_channels.append(channel)
        if not unpublished_channels:
            raise CampaignPublicationForbiddenError("No published asset found for requested channels.")
        campaign._sync_status_from_assets()
        saved = self.repository.save(campaign)
        for asset in campaign.content_assets:
            asset.ensure_content_hash()
        self.audit_log.append(
            saved.id,
            "simple_campaign.unpublished",
            {"channels": sorted(set(unpublished_channels))},
            actor_source=actor,
            previous_state={},
            new_state={"status": saved.status.value},
            result="SUCCESS",
        )
        return saved

    def list_oling_themes(self) -> list[str]:
        practices_dir = self.project_root / "knowledge" / "oling" / "practices"
        return sorted(path.stem for path in practices_dir.glob("*.md"))

    def external_channel(self, channel: str) -> str:
        return CHANNEL_FROM_INTERNAL.get(channel, channel)

    def simple_status(self, campaign: CampaignRun) -> str:
        if campaign.status is CampaignStatus.ARCHIVED:
            return "ARCHIVED"
        if campaign.status.value == "DRAFT":
            return "DRAFT"
        if campaign.status.value in {"PUBLISHED", "PARTIALLY_PUBLISHED"}:
            return campaign.status.value
        if campaign.status.value in {"APPROVED", "PARTIALLY_APPROVED", "READY_FOR_REVIEW", "CHANGES_REQUESTED", "GENERATED"}:
            return campaign.status.value
        if campaign.status.value == "FAILED":
            return "ERROR"
        return campaign.status.value

    def simple_asset_status(self, asset: ContentAsset) -> str:
        if asset.status is AssetStatus.PUBLISHED:
            return "PUBLISHED"
        if asset.status is AssetStatus.APPROVED:
            return "APPROVED"
        if asset.status is AssetStatus.REVIEWED:
            return "REVIEWED"
        if asset.status is AssetStatus.FAILED:
            return "ERROR"
        if asset.status is AssetStatus.DRAFT:
            return "DRAFT"
        if asset.status is AssetStatus.READY_FOR_REVIEW:
            return "GENERATED"
        return "READY"

    def _assert_simple_campaign(self, campaign: CampaignRun) -> None:
        if campaign.workflow_kind != SIMPLE_WORKFLOW_KIND:
            raise CampaignNotFoundError(f"Campaign {campaign.id} not found.")

    def _validate_campaign_type(self, campaign_type: str) -> None:
        if campaign_type not in SIMPLE_CAMPAIGN_TYPES:
            raise InvalidStateTransitionError(f"Unsupported campaign_type {campaign_type}.")

    def _normalize_selected_channels(self, campaign_type: str, selected_channels: list[str]) -> list[str]:
        normalized = []
        allowed = SIMPLE_CHANNEL_RULES[campaign_type]
        for channel in selected_channels:
            item = channel.strip()
            if not item:
                continue
            if item not in allowed:
                raise InvalidStateTransitionError(f"Channel {item} is not allowed for {campaign_type}.")
            if item not in normalized:
                normalized.append(item)
        if not normalized:
            raise InvalidStateTransitionError("At least one publication channel is required.")
        return normalized

    def _resolve_theme(self, campaign_type: str, theme: str) -> str:
        resolved = theme.strip()
        if resolved:
            return resolved
        generated_themes = {
            "MAPSI_USERS": [
                "Mieux exploiter les fonctionnalites utiles au quotidien",
                "Gagner du temps dans les usages courants de MAPSI",
                "Adopter les bons reflexes pour un usage plus fluide de MAPSI",
            ],
            "MAPSI_MARKETING": [
                "Valoriser les usages concrets et les gains obtenus avec MAPSI",
                "Mettre en avant les evolutions produit qui comptent vraiment",
                "Raconter MAPSI de maniere plus claire, plus credible et plus terrain",
            ],
            "OLING": [
                "Structurer une demarche RGPD pragmatique et utile",
                "Mieux cadrer une mission AMOA sans alourdir le pilotage",
                "Faire avancer un sujet de transformation avec une approche concrete",
            ],
        }
        return generated_themes[campaign_type][0]

    def _mapsi_selection(self, campaign: CampaignRun) -> EditorialBuilderSelection:
        feature = self._select_mapsi_feature(campaign.theme)
        return EditorialBuilderSelection(
            topic_key=feature.feature_id,
            topic=campaign.theme,
            selection_type="feature_catalog",
            source_ids=[f"knowledge:mapsi:feature:{feature.feature_id}"],
            rationale=[feature.short_description, campaign.theme],
        )

    def _oling_selection(self, campaign: CampaignRun) -> EditorialBuilderSelection:
        practice = self._select_oling_practice(campaign.theme)
        return EditorialBuilderSelection(
            topic_key=practice.practice_id,
            topic=campaign.theme,
            selection_type="oling_practice",
            source_ids=[f"knowledge:oling:practice:{practice.practice_id}"],
            rationale=[practice.description, campaign.theme],
        )

    def _build_mapsi_context(self, campaign: CampaignRun, *, destination_site: str, article_type: str) -> EditorialGenerationContext:
        if self.knowledge_repository is None or self.editorial_service is None:
            raise InvalidStateTransitionError("Editorial service is not configured.")
        feature = self._select_mapsi_feature(campaign.theme)
        rules = self.knowledge_repository.getEditorialRules()
        changes = self.knowledge_repository.listMapsIProductChangesSince(date.today() - timedelta(days=365))
        related_changes = self._related_product_changes(feature, changes)
        source_change = related_changes[0] if related_changes else self._synthetic_product_change(feature, campaign.theme)
        if campaign.campaign_type == "MAPSI_USERS":
            angle = f"Angle d'adoption utilisateur autour de {campaign.theme}. Montrer les usages, les gains immediats et les reflexes utiles."
        elif destination_site == "oling.fr":
            angle = f"Angle conseil et transformation autour de {campaign.theme}. Faire le lien entre la fonctionnalite, les usages et l'accompagnement."
        else:
            angle = f"Angle produit et communication corporate autour de {campaign.theme}. Chercher un rendu expert, vivant, credible et detaille."

        return EditorialGenerationContext(
            topic=campaign.theme,
            article_type=article_type,  # type: ignore[arg-type]
            destination_site=destination_site,  # type: ignore[arg-type]
            publication_channel="mapsi_site" if destination_site == "mapsi.fr" else "oling_site",  # type: ignore[arg-type]
            target_personas=feature.target_roles or ["direction_metier", "responsable_transformation"],
            knowledge_version=rules.knowledge_version_hash,
            positioning=rules.mapsi_product_positioning,
            terminology=rules.mapsi_terminology,
            editorial_rules=rules.mapsi_forbidden_claims,
            forbidden_claims=feature.forbidden_claims,
            mapsi_feature=MapsiFeatureContext(
                feature_id=feature.feature_id,
                module=feature.module,
                title=feature.title,
                short_description=feature.short_description,
                business_problem=feature.business_problem,
                functional_description=feature.functional_description,
                user_benefits=feature.user_benefits,
                typical_use_cases=feature.typical_use_cases,
                target_roles=feature.target_roles,
                forbidden_claims=feature.forbidden_claims,
            ),
            recent_product_changes=[
                ProductChangeContext(
                    product_change_id=change.id,
                    capability_key=change.capability_key or change.sha,
                    summary=change.summary,
                    reference=change.change_note_path or change.sha,
                    collected_at=change.collected_at,
                    source_ids=[f"product_change:{change.id}"],
                )
                for change in related_changes[:5]
            ],
            published_topic_history=self.editorial_service._build_history(),
            sources=self.editorial_service._mapsi_sources(feature.feature_id, source_change),
            context_digest=self._build_mapsi_context_digest(campaign, feature, related_changes, destination_site=destination_site),
            rewrite_instruction=(
                "Produire un article editorial complet, professionnel, detaille, avec rythme, transitions naturelles, "
                "angles concrets, ton expert et aucune formule stereotypee d'IA."
            ),
            desired_title=campaign.theme,
            length_directive="longer",
            angle_directive=angle,
        )

    def _build_oling_context(self, campaign: CampaignRun) -> EditorialGenerationContext:
        if self.knowledge_repository is None or self.editorial_service is None:
            raise InvalidStateTransitionError("Editorial service is not configured.")
        practice = self._select_oling_practice(campaign.theme)
        rules = self.knowledge_repository.getEditorialRules()
        return EditorialGenerationContext(
            topic=campaign.theme,
            article_type="OLING_PRACTICE",
            destination_site="oling.fr",
            publication_channel="oling_site",
            target_personas=["dsi", "responsable_projet", "direction_metier"],
            knowledge_version=rules.knowledge_version_hash,
            positioning=rules.oling_company_profile,
            target_clients=rules.oling_target_clients,
            differentiators=rules.oling_differentiators,
            editorial_rules=rules.oling_editorial_style,
            forbidden_claims=practice.forbidden_claims,
            oling_practice=OlingPracticeContext(
                practice_id=practice.practice_id,
                title=practice.title,
                description=practice.description,
                common_client_problems=practice.common_client_problems,
                intervention_context=practice.intervention_context,
                oling_approach=practice.oling_approach,
                mission_steps=practice.mission_steps,
                usual_deliverables=practice.usual_deliverables,
                vigilance_points=practice.vigilance_points,
                success_factors=practice.success_factors,
                concerned_sectors=practice.concerned_sectors,
                allowed_ctas=practice.allowed_ctas,
                forbidden_claims=practice.forbidden_claims,
            ),
            published_topic_history=self.editorial_service._build_history(),
            sources=self.editorial_service._oling_sources(practice.practice_id),
            context_digest=self._build_oling_context_digest(campaign, practice),
            rewrite_instruction=(
                "Produire un article de conseil OLING a forte valeur editoriale, structure, demonstration, nuances et "
                "credibilite terrain. Eviter les formulations creuses ou generiques."
            ),
            desired_title=campaign.theme,
            length_directive="longer",
            angle_directive=f"Traiter le theme libre utilisateur suivant avec la practice {practice.title}: {campaign.theme}",
        )

    def _select_mapsi_feature(self, theme: str) -> MapsiFeature:
        if self.knowledge_repository is None:
            raise InvalidStateTransitionError("Knowledge repository is not configured.")
        features = self.knowledge_repository.listMapsIFeatures()
        theme_tokens = set(self._tokens(theme))
        ranked: list[tuple[int, MapsiFeature]] = []
        for feature in features:
            haystack = " ".join(
                [
                    feature.feature_id,
                    feature.module,
                    feature.title,
                    feature.short_description,
                    feature.business_problem,
                    feature.functional_description,
                    *feature.user_benefits,
                    *feature.typical_use_cases,
                ]
            )
            score = len(theme_tokens.intersection(self._tokens(haystack))) * 10
            score += max(0, 120 - feature.communication_priority)
            ranked.append((score, feature))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return ranked[0][1]

    def _select_oling_practice(self, theme: str) -> OlingPractice:
        if self.knowledge_repository is None:
            raise InvalidStateTransitionError("Knowledge repository is not configured.")
        practices = self.knowledge_repository.listOlingPractices()
        theme_tokens = set(self._tokens(theme))
        ranked: list[tuple[int, OlingPractice]] = []
        for practice in practices:
            haystack = " ".join(
                [
                    practice.practice_id,
                    practice.title,
                    practice.description,
                    practice.intervention_context,
                    practice.oling_approach,
                    *practice.common_client_problems,
                    *practice.mission_steps,
                    *practice.usual_deliverables,
                    *practice.vigilance_points,
                    *practice.success_factors,
                ]
            )
            score = len(theme_tokens.intersection(self._tokens(haystack))) * 10
            ranked.append((score, practice))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return ranked[0][1]

    def _related_product_changes(self, feature: MapsiFeature, changes: list[ProductChange]) -> list[ProductChange]:
        feature_tokens = set(self._tokens(" ".join([feature.feature_id, feature.module, feature.title, feature.short_description, feature.functional_description])))
        ranked: list[tuple[int, ProductChange]] = []
        for change in changes:
            if not change.eligible_for_communication or change.confidential:
                continue
            haystack = " ".join([change.summary, change.capability_key, change.change_note_path, change.sha])
            score = len(feature_tokens.intersection(self._tokens(haystack))) * 10
            if feature.module and feature.module.casefold() in haystack.casefold():
                score += 20
            if score > 0:
                ranked.append((score, change))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in ranked[:5]]

    def _build_mapsi_context_digest(
        self,
        campaign: CampaignRun,
        feature: MapsiFeature,
        related_changes: list[ProductChange],
        *,
        destination_site: str,
    ) -> str:
        sections = [
            f"Theme campagne: {campaign.theme}",
            f"Brief utilisateur: {campaign.objective}" if campaign.objective and campaign.objective != campaign.theme else "",
            f"Type campagne: {campaign.campaign_type}",
            f"Destination editoriale: {destination_site}",
            f"Feature MAPSI: {feature.title} ({feature.module})",
            f"Probleme metier: {feature.business_problem}",
            f"Description fonctionnelle: {feature.functional_description}",
        ]
        if feature.user_benefits:
            sections.append("Benefices utilisateurs confirms: " + "; ".join(feature.user_benefits[:4]))
        if feature.typical_use_cases:
            sections.append("Cas d'usage communicables: " + "; ".join(feature.typical_use_cases[:4]))
        if related_changes:
            sections.append(
                "Changements produit recents relies: " + " | ".join(self._product_change_digest(change) for change in related_changes[:4])
            )
        source_pack_facts = self._source_pack_facts("MAPSI_MARKET", campaign.theme)
        if source_pack_facts:
            sections.append("Faits projets / terrain reutilisables: " + " | ".join(source_pack_facts[:6]))
        reference_snippets = self._reference_file_snippets(feature.source_references)
        if reference_snippets:
            sections.append("Extraits de references locales: " + " | ".join(reference_snippets[:3]))
        return "\n".join(section for section in sections if section.strip())

    def _build_oling_context_digest(self, campaign: CampaignRun, practice: OlingPractice) -> str:
        sections = [
            f"Theme campagne: {campaign.theme}",
            f"Brief utilisateur: {campaign.objective}" if campaign.objective and campaign.objective != campaign.theme else "",
            f"Type campagne: {campaign.campaign_type}",
            f"Practice OLING: {practice.title}",
            f"Description practice: {practice.description}",
            f"Contexte d'intervention: {practice.intervention_context}",
            f"Approche OLING: {practice.oling_approach}",
        ]
        if practice.common_client_problems:
            sections.append("Problemes clients recurrents: " + "; ".join(practice.common_client_problems[:4]))
        if practice.mission_steps:
            sections.append("Etapes de mission: " + "; ".join(practice.mission_steps[:4]))
        if practice.usual_deliverables:
            sections.append("Livrables usuels: " + "; ".join(practice.usual_deliverables[:4]))
        if practice.vigilance_points:
            sections.append("Points de vigilance: " + "; ".join(practice.vigilance_points[:4]))
        source_pack_facts = self._source_pack_facts("OLING_PRACTICE", campaign.theme)
        if source_pack_facts:
            sections.append("Faits projets / retours terrain reutilisables: " + " | ".join(source_pack_facts[:6]))
        markdown_body = self._knowledge_markdown_body(f"knowledge/oling/practices/{practice.practice_id}.md")
        if markdown_body:
            sections.append("Corps knowledge practice: " + markdown_body)
        reference_snippets = self._reference_file_snippets(practice.sources)
        if reference_snippets:
            sections.append("Extraits de references locales: " + " | ".join(reference_snippets[:3]))
        return "\n".join(section for section in sections if section.strip())

    def _source_pack_facts(self, campaign_type: str, theme: str) -> list[str]:
        if self.source_pack_repository is None:
            return []
        theme_tokens = set(self._tokens(theme))
        ranked: list[tuple[int, str]] = []
        for pack in self.source_pack_repository.list_validated(campaign_type=campaign_type):
            for item in pack.items:
                facts = list(item.anonymized_facts or item.usable_facts)
                if item.factual_summary:
                    facts.insert(0, item.factual_summary)
                haystack = " ".join(
                    [
                        pack.title,
                        pack.summary,
                        item.source_title,
                        item.factual_summary,
                        " ".join(facts),
                        " ".join(str(value) for value in item.manual_input.values() if isinstance(value, str)),
                    ]
                )
                score = len(theme_tokens.intersection(self._tokens(haystack))) * 10
                score += 5 if item.evidence_quality == "high" else 0
                for fact in facts[:4]:
                    cleaned = self._collapse_whitespace(fact)
                    if cleaned:
                        ranked.append((score + min(len(cleaned), 120), cleaned))
        ranked.sort(key=lambda item: item[0], reverse=True)
        seen: set[str] = set()
        selected: list[str] = []
        for _, fact in ranked:
            key = fact.casefold()
            if key in seen:
                continue
            seen.add(key)
            selected.append(fact)
            if len(selected) >= 8:
                break
        return selected

    def _reference_file_snippets(self, references: list[str]) -> list[str]:
        snippets: list[str] = []
        for reference in references[:4]:
            path = self.project_root / reference
            if not path.exists() or not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            cleaned = self._collapse_whitespace(text)
            if cleaned:
                snippets.append(f"{reference}: {cleaned[:280]}")
        return snippets

    def _knowledge_markdown_body(self, relative_path: str) -> str:
        path = self.project_root / relative_path
        if not path.exists() or not path.is_file():
            return ""
        text = path.read_text(encoding="utf-8")
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) == 3:
                text = parts[2]
        return self._collapse_whitespace(text)[:500]

    def _product_change_digest(self, change: ProductChange) -> str:
        details: list[str] = [change.summary]
        if change.capability_key:
            details.append(f"capability={change.capability_key}")
        if change.change_note_path:
            details.append(f"ref={change.change_note_path}")
        payload_text = self._collapse_whitespace(self._flatten_payload_text(change.raw_payload))
        if payload_text:
            details.append(payload_text[:220])
        return " ; ".join(item for item in details if item)

    def _flatten_payload_text(self, payload: object) -> str:
        if isinstance(payload, str):
            return payload
        if isinstance(payload, dict):
            values: list[str] = []
            for value in payload.values():
                flattened = self._flatten_payload_text(value)
                if flattened:
                    values.append(flattened)
            return " ".join(values)
        if isinstance(payload, list):
            return " ".join(self._flatten_payload_text(item) for item in payload if self._flatten_payload_text(item))
        return ""

    def _collapse_whitespace(self, value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()

    def _synthetic_product_change(self, feature: MapsiFeature, theme: str) -> ProductChange:
        return ProductChange(
            id=f"simple-{uuid4().hex[:12]}",
            capability_key=feature.module,
            summary=theme,
            change_note_path=f"theme:{feature.feature_id}",
            eligible_for_communication=True,
            deployment_proven=True,
            collected_at=datetime.now(UTC),
        )

    def _collect_editorial_evidence(self, campaign_id: str, contexts: list[EditorialGenerationContext]) -> list[SourceEvidence]:
        by_source_id: dict[str, SourceEvidence] = {}
        for context in contexts:
            for source in context.sources:
                if source.source_id in by_source_id:
                    continue
                by_source_id[source.source_id] = SourceEvidence(
                    id=str(uuid5(NAMESPACE_URL, f"{campaign_id}:{source.source_id}")),
                    campaign_run_id=campaign_id,
                    source_system=source.source_type,
                    evidence_type="knowledge_source" if source.source_type == "knowledge_file" else "product_change_source",
                    reference=source.reference,
                    payload=source.model_dump(mode="json"),
                )
        return list(by_source_id.values())

    def _asset_from_editorial_result(
        self,
        campaign: CampaignRun,
        channel: str,
        result: EditorialGenerationResult,
        evidence: list[SourceEvidence],
    ) -> ContentAsset:
        article = result.record.article
        evidence_ids = [
            item.id
            for item in evidence
            if str(item.payload.get("source_id", "")) in set(article.source_ids)
        ]
        internal_channel = CHANNEL_TO_INTERNAL[channel]
        asset = ContentAsset(
            campaign_run_id=campaign.id,
            asset_type="mapsi_news_article" if channel == "mapsi_site" else "oling_news_article",
            channel=internal_channel,
            locale="fr-FR",
            title=article.title,
            subject="",
            content_html=HtmlSanitizer.sanitize(article.body_html),
            content_text=article.body_text,
            excerpt=article.excerpt,
            call_to_action=article.call_to_action_label,
            target_url=article.call_to_action_url,
            source_evidence_ids=evidence_ids,
            evidence_ids=evidence_ids,
            audience_segment_id=campaign.campaign_type.casefold(),
            results={
                "editorial_article": article.model_dump(mode="json"),
                "editorial_quality": result.record.quality.model_dump(mode="json"),
                "editorial_execution": {
                    "model": result.record.model_name,
                    "prompt_version": result.record.prompt_version,
                    "knowledge_version": result.record.knowledge_version,
                    "input_hash": result.record.input_hash,
                    "output_hash": result.record.output_hash,
                    "tokens": {
                        "input": result.record.input_tokens,
                        "output": result.record.output_tokens,
                        "total": result.record.total_tokens,
                    },
                    "cost_usd": result.record.estimated_cost_usd,
                    "duration_ms": result.record.duration_ms,
                    "provider_type": result.record.provider_type,
                },
                "builder_context": result.context.model_dump(mode="json"),
                "builder_selection": result.selection.model_dump(mode="json") if result.selection else {},
                "illustration_suggestion": self._editorial_image_suggestion(campaign, article),
            },
        )
        asset.ensure_content_hash()
        return asset

    def _linkedin_asset_from_editorial(
        self,
        campaign: CampaignRun,
        result: EditorialGenerationResult,
        evidence: list[SourceEvidence],
    ) -> ContentAsset:
        article = result.record.article
        evidence_ids = [
            item.id
            for item in evidence
            if str(item.payload.get("source_id", "")) in set(article.source_ids)
        ]
        if self.editorial_service is None or not self.editorial_service.has_real_backend():
            if self.require_real_editorial_backend:
                raise InvalidStateTransitionError("LinkedIn variant generation is unavailable for simple studio.")
            variant = None
            linkedin = None
            body = self._build_linkedin_from_article(campaign, article)
            visual_brief = self._editorial_image_suggestion(campaign, article)
        else:
            context = self._channel_variant_context(campaign, article, "linkedin_manual")
            variant = self.editorial_service.generate_linkedin_variant(context=context)
            linkedin = variant.output
            if not isinstance(linkedin, EditorialLinkedInPost):
                raise InvalidStateTransitionError("LinkedIn variant generation is unavailable for simple studio.")
            body = linkedin.body_text
            visual_brief = linkedin.visual_brief
        asset = ContentAsset(
            campaign_run_id=campaign.id,
            asset_type="linkedin_manual_post",
            channel=CHANNEL_TO_INTERNAL["linkedin_manual"],
            locale="fr-FR",
            title="Publication manuelle LinkedIn",
            content_text=body,
            excerpt=visual_brief,
            audience_segment_id=campaign.campaign_type.casefold(),
            source_evidence_ids=evidence_ids,
            evidence_ids=evidence_ids,
            results={
                "source_article": article.model_dump(mode="json"),
                "illustration_suggestion": visual_brief,
            },
        )
        if linkedin is not None and variant is not None:
            asset.results["channel_variant"] = linkedin.model_dump(mode="json")
            asset.results["editorial_execution"] = {
                "model": variant.metadata.model_name,
                "prompt_version": variant.metadata.prompt_version,
                "tokens": {
                    "input": variant.metadata.token_usage.input_tokens,
                    "output": variant.metadata.token_usage.output_tokens,
                    "total": variant.metadata.token_usage.total_tokens,
                },
                "cost_usd": variant.estimated_cost_usd,
                "duration_ms": variant.duration_ms,
                "provider_type": variant.metadata.provider_type,
            }
        asset.ensure_content_hash()
        return asset

    def _email_asset_from_editorial(
        self,
        campaign: CampaignRun,
        result: EditorialGenerationResult,
        evidence: list[SourceEvidence],
    ) -> ContentAsset:
        article = result.record.article
        evidence_ids = [
            item.id
            for item in evidence
            if str(item.payload.get("source_id", "")) in set(article.source_ids)
        ]
        if self.editorial_service is None or not self.editorial_service.has_real_backend():
            if self.require_real_editorial_backend:
                raise InvalidStateTransitionError("Email variant generation is unavailable for simple studio.")
            variant = None
            email = None
            title = self._email_subject_from_article(campaign, article)
            body_html = self._build_email_html(campaign, article)
            body_text = self._build_email_from_article(campaign, article)
            preview_text = article.excerpt
            visual_brief = self._editorial_image_suggestion(campaign, article)
            call_to_action = article.call_to_action_label
            target_url = article.call_to_action_url
        else:
            context = self._channel_variant_context(campaign, article, "email_manual")
            variant = self.editorial_service.generate_email_variant(context=context)
            email = variant.output
            if not isinstance(email, EditorialEmailMessage):
                raise InvalidStateTransitionError("Email variant generation is unavailable for simple studio.")
            title = email.subject
            body_html = email.body_html
            body_text = email.body_text
            preview_text = email.preview_text
            visual_brief = email.visual_brief
            call_to_action = email.call_to_action_label
            target_url = email.call_to_action_url
        asset = ContentAsset(
            campaign_run_id=campaign.id,
            asset_type="email_manual_message",
            channel=CHANNEL_TO_INTERNAL["email_manual"],
            locale="fr-FR",
            title=title,
            content_html=HtmlSanitizer.sanitize(body_html),
            content_text=body_text,
            excerpt=preview_text,
            call_to_action=call_to_action,
            target_url=target_url,
            audience_segment_id=campaign.campaign_type.casefold(),
            source_evidence_ids=evidence_ids,
            evidence_ids=evidence_ids,
            results={
                "source_article": article.model_dump(mode="json"),
                "illustration_suggestion": visual_brief,
                "manual_send": True,
            },
        )
        if email is not None and variant is not None:
            asset.results["channel_variant"] = email.model_dump(mode="json")
            asset.results["editorial_execution"] = {
                "model": variant.metadata.model_name,
                "prompt_version": variant.metadata.prompt_version,
                "tokens": {
                    "input": variant.metadata.token_usage.input_tokens,
                    "output": variant.metadata.token_usage.output_tokens,
                    "total": variant.metadata.token_usage.total_tokens,
                },
                "cost_usd": variant.estimated_cost_usd,
                "duration_ms": variant.duration_ms,
                "provider_type": variant.metadata.provider_type,
            }
        asset.ensure_content_hash()
        return asset

    def _channel_variant_context(self, campaign: CampaignRun, article, channel: str) -> EditorialChannelVariantContext:
        destination_site = "oling.fr" if campaign.campaign_type == "OLING" or "oling_site" in campaign.selected_channels else "mapsi.fr"
        return EditorialChannelVariantContext(
            topic=campaign.theme,
            campaign_type=campaign.campaign_type,  # type: ignore[arg-type]
            channel=channel,  # type: ignore[arg-type]
            destination_site=destination_site,  # type: ignore[arg-type]
            target_personas=list(article.target_personas),
            positioning=self._channel_positioning(campaign),
            editorial_rules=self._channel_editorial_rules(campaign),
            forbidden_claims=self._channel_forbidden_claims(campaign),
            desired_tone=self._tone_signature(campaign, channel),
            desired_outcome=self._channel_outcome(campaign, channel),
            source_article=article,
        )

    def _assert_real_editorial_backend(self) -> None:
        if self.editorial_service is None or not self.editorial_service.has_real_backend():
            raise InvalidStateTransitionError(
                "Simple studio requires a real OpenAI editorial backend."
            )
        if not get_settings().openai_api_key.strip():
            raise InvalidStateTransitionError("Simple studio requires OPENAI_API_KEY to generate texts with agents.")

    def _channel_positioning(self, campaign: CampaignRun) -> str:
        if campaign.campaign_type == "MAPSI_USERS":
            return "MAPSI doit apparaitre comme un produit utile, clair, fiable et concret pour les utilisateurs."
        if campaign.campaign_type == "MAPSI_MARKETING":
            return "MAPSI doit apparaitre comme une solution credible, utile en execution et soutenue par une vraie expertise terrain."
        return "OLING doit apparaitre comme un cabinet de conseil structurant, credible, pragmatique et orienté decision."

    def _channel_editorial_rules(self, campaign: CampaignRun) -> str:
        if campaign.campaign_type == "MAPSI_USERS":
            return "Eviter le jargon, garder un ton clair, rythmé, pedagogue, et montrer rapidement le benefice concret."
        if campaign.campaign_type == "MAPSI_MARKETING":
            return "Alterner preuve, usage, mise en perspective et credibilite terrain. Proscrire les slogans et banalites."
        return "Montrer une pensee de conseil mature, structuree, sobre et credible. Pas de contenu generique ni auto-promotion creuse."

    def _channel_forbidden_claims(self, campaign: CampaignRun) -> list[str]:
        if campaign.campaign_type == "OLING" and self.knowledge_repository is not None:
            return self._select_oling_practice(campaign.theme).forbidden_claims
        if campaign.campaign_type in {"MAPSI_USERS", "MAPSI_MARKETING"} and self.knowledge_repository is not None:
            return self._select_mapsi_feature(campaign.theme).forbidden_claims
        return []

    def _channel_outcome(self, campaign: CampaignRun, channel: str) -> str:
        if channel == "linkedin_manual":
            return "Produire un post natif LinkedIn premium, lisible, humain, direct, partageable sans retouche lourde."
        if campaign.campaign_type == "MAPSI_USERS":
            return "Produire un email d'adoption utile, professionnel et actionnable."
        if campaign.campaign_type == "MAPSI_MARKETING":
            return "Produire un email de communication professionnelle, structuré et convaincant."
        return "Produire un email conseil premium, executive-friendly et directement exploitable."

    def _build_linkedin_from_article(self, campaign: CampaignRun, article) -> str:
        highlights = [claim.text for claim in article.claims[:2] if claim.text.strip()]
        while len(highlights) < 2:
            highlights.append(article.excerpt)
        return (
            f"{article.title}\n\n"
            f"{article.excerpt}\n\n"
            f"- {highlights[0]}\n"
            f"- {highlights[1]}\n\n"
            f"Angle : {campaign.theme}\n\n"
            f"Visuel suggere : {self._editorial_image_suggestion(campaign, article)}\n\n"
            f"{article.call_to_action_label} : {article.call_to_action_url}"
        )

    def _email_subject_from_article(self, campaign: CampaignRun, article) -> str:
        if campaign.campaign_type == "MAPSI_USERS":
            return f"MAPSI : {campaign.theme}"
        if campaign.campaign_type == "MAPSI_MARKETING":
            return f"Communication MAPSI : {campaign.theme}"
        return f"OLING : {campaign.theme}"

    def _build_email_from_article(self, campaign: CampaignRun, article) -> str:
        claims = [claim.text.strip() for claim in article.claims[:3] if claim.text.strip()]
        while len(claims) < 3:
            claims.append(article.excerpt)
        return (
            f"Objet : {self._email_subject_from_article(campaign, article)}\n\n"
            "Bonjour,\n\n"
            f"{article.excerpt}\n\n"
            f"{claims[0]}\n\n"
            f"{claims[1]}\n\n"
            f"{claims[2]}\n\n"
            f"Si le sujet vous interesse, {article.call_to_action_label.lower()} : {article.call_to_action_url}\n\n"
            "Bien cordialement,"
        )

    def _build_email_html(self, campaign: CampaignRun, article) -> str:
        claims = [claim.text.strip() for claim in article.claims[:3] if claim.text.strip()]
        while len(claims) < 3:
            claims.append(article.excerpt)
        return (
            f"<p><strong>Objet :</strong> {self._email_subject_from_article(campaign, article)}</p>"
            "<p>Bonjour,</p>"
            f"<p>{article.excerpt}</p>"
            f"<p>{claims[0]}</p>"
            f"<p>{claims[1]}</p>"
            f"<p>{claims[2]}</p>"
            f"<p>{article.call_to_action_label} : <a href=\"{article.call_to_action_url}\">{article.call_to_action_url}</a></p>"
            "<p>Bien cordialement,</p>"
        )

    def _editorial_image_suggestion(self, campaign: CampaignRun, article) -> str:
        if campaign.campaign_type == "MAPSI_USERS":
            return "capture produit soignee avec un cadrage utile, legendees sobres, focalisation sur l'usage concret"
        if campaign.campaign_type == "MAPSI_MARKETING":
            return "illustration editoriale melangeant interface, contexte metier, elements de pilotage et details de mise en oeuvre"
        return "visuel premium de conseil montrant atelier, cadrage, decision et execution, sans imagerie generique d'IA"

    def _tokens(self, value: str) -> set[str]:
        return {item for item in "".join(char if char.isalnum() else " " for char in value.casefold()).split() if item}

    def _find_asset(self, campaign: CampaignRun, asset_id: str) -> ContentAsset:
        for asset in campaign.content_assets:
            if asset.id == asset_id:
                return asset
        raise CampaignNotFoundError(f"Asset {asset_id} not found for campaign {campaign.id}.")

    def _build_evidence(self, campaign: CampaignRun) -> list[SourceEvidence]:
        evidences: list[SourceEvidence] = []
        if campaign.campaign_type in {"MAPSI_USERS", "MAPSI_MARKETING"}:
            for relative_path in (
                "knowledge/mapsi/product-positioning.md",
                "knowledge/mapsi/feature-catalog.yaml",
                "knowledge/mapsi/target-personas.md",
            ):
                evidences.append(self._file_evidence(campaign.id, relative_path))
        if campaign.campaign_type == "MAPSI_MARKETING":
            evidences.append(self._file_evidence(campaign.id, "knowledge/oling/differentiators.md"))
        if campaign.campaign_type == "OLING":
            evidences.extend(
                [
                    self._file_evidence(campaign.id, "knowledge/oling/company-profile.md"),
                    self._file_evidence(campaign.id, "knowledge/oling/differentiators.md"),
                ]
            )
            if campaign.theme in self.list_oling_themes():
                evidences.append(self._file_evidence(campaign.id, f"knowledge/oling/practices/{campaign.theme}.md"))
        return evidences

    def _file_evidence(self, campaign_id: str, relative_path: str) -> SourceEvidence:
        return SourceEvidence(
            campaign_run_id=campaign_id,
            source_system="knowledge_base",
            evidence_type="file",
            reference=relative_path,
        )

    def _build_assets(self, campaign: CampaignRun, evidence: list[SourceEvidence]) -> list[ContentAsset]:
        evidence_ids = [item.id for item in evidence]
        assets: list[ContentAsset] = []
        for channel in campaign.selected_channels:
            internal_channel = CHANNEL_TO_INTERNAL[channel]
            if channel == "linkedin_manual":
                assets.append(
                    ContentAsset(
                        campaign_run_id=campaign.id,
                        asset_type="linkedin_manual_post",
                        channel=internal_channel,
                        locale="fr-FR",
                        title=f"{campaign.name} - LinkedIn",
                        content_text=self._build_linkedin_text(campaign),
                        excerpt=self._image_suggestion(campaign, channel),
                        audience_segment_id="",
                        source_evidence_ids=evidence_ids,
                        evidence_ids=evidence_ids,
                        results={"illustration_suggestion": self._image_suggestion(campaign, channel)},
                    )
                )
                continue
            if channel == "email_manual":
                assets.append(
                    ContentAsset(
                        campaign_run_id=campaign.id,
                        asset_type="email_manual_message",
                        channel=internal_channel,
                        locale="fr-FR",
                        title=self._build_email_subject(campaign),
                        content_html=self._build_email_html_from_campaign(campaign),
                        content_text=self._build_email_text(campaign),
                        excerpt=self._summary_excerpt(campaign, channel),
                        call_to_action=self._call_to_action(campaign, channel),
                        audience_segment_id="",
                        source_evidence_ids=evidence_ids,
                        evidence_ids=evidence_ids,
                        results={"manual_send": True, "illustration_suggestion": self._image_suggestion(campaign, channel)},
                    )
                )
                continue
            assets.append(
                ContentAsset(
                    campaign_run_id=campaign.id,
                    asset_type="mapsi_news_article" if channel == "mapsi_site" else "oling_news_article",
                    channel=internal_channel,
                    locale="fr-FR",
                    title=self._build_article_title(campaign, channel),
                    content_html=self._build_article_html(campaign, channel),
                    content_text=self._build_article_text(campaign, channel),
                    excerpt=self._summary_excerpt(campaign, channel),
                    call_to_action=self._call_to_action(campaign, channel),
                    audience_segment_id="",
                    source_evidence_ids=evidence_ids,
                    evidence_ids=evidence_ids,
                    results={"illustration_suggestion": self._image_suggestion(campaign, channel)},
                )
            )
        return assets

    def _build_article_title(self, campaign: CampaignRun, channel: str) -> str:
        if campaign.campaign_type == "MAPSI_USERS":
            return f"MAPSI utilisateurs : {campaign.theme}"
        if campaign.campaign_type == "MAPSI_MARKETING" and channel == "oling_site":
            return f"Oling x MAPSI : {campaign.theme}"
        if campaign.campaign_type == "MAPSI_MARKETING":
            return f"MAPSI : {campaign.theme}"
        return f"Oling : {campaign.theme}"

    def _build_article_html(self, campaign: CampaignRun, channel: str) -> str:
        intro = self._article_intro(campaign, channel)
        promise = self._article_promise(campaign)
        bullet_points = self._bullet_points(campaign, channel)
        illustration = self._image_suggestion(campaign, channel)
        closing = self._article_closing(campaign, channel)
        bullet_html = "".join(f"<li>{item}</li>" for item in bullet_points)
        return (
            f"<h1>{self._build_article_title(campaign, channel)}</h1>"
            f"<p><strong>{self._tone_signature(campaign, channel)}</strong></p>"
            f"<p>{intro}</p>"
            f"<p>{promise}</p>"
            f"<h2>Points cles</h2><ul>{bullet_html}</ul>"
            f"<p><strong>Suggestion d'illustration :</strong> {illustration}</p>"
            f"<p>{closing}</p>"
            f"<p><strong>Prochaine etape :</strong> {self._call_to_action(campaign, channel)}</p>"
        )

    def _build_article_text(self, campaign: CampaignRun, channel: str) -> str:
        bullets = "\n".join(f"- {item}" for item in self._bullet_points(campaign, channel))
        return "\n\n".join(
            [
                self._build_article_title(campaign, channel),
                self._tone_signature(campaign, channel),
                self._article_intro(campaign, channel),
                self._article_promise(campaign),
                "Points cles\n" + bullets,
                "Suggestion d'illustration : " + self._image_suggestion(campaign, channel),
                self._article_closing(campaign, channel),
                "Prochaine etape : " + self._call_to_action(campaign, channel),
            ]
        )

    def _build_linkedin_text(self, campaign: CampaignRun) -> str:
        bullets = self._bullet_points(campaign, "linkedin_manual")[:2]
        return (
            f"{self._build_article_title(campaign, campaign.selected_channels[0])}\n\n"
            f"{self._tone_signature(campaign, 'linkedin_manual')}\n\n"
            f"{self._article_intro(campaign, 'linkedin_manual')}\n\n"
            f"- {bullets[0]}\n- {bullets[1]}\n\n"
            f"Illustration suggeree : {self._image_suggestion(campaign, 'linkedin_manual')}\n\n"
            f"{self._linkedin_close(campaign)}"
        )

    def _build_email_subject(self, campaign: CampaignRun) -> str:
        if campaign.campaign_type == "MAPSI_USERS":
            return f"MAPSI : {campaign.theme}"
        if campaign.campaign_type == "MAPSI_MARKETING":
            return f"Communication MAPSI : {campaign.theme}"
        return f"OLING : {campaign.theme}"

    def _build_email_text(self, campaign: CampaignRun) -> str:
        bullets = self._bullet_points(campaign, "email_manual")[:3]
        return (
            f"Objet : {self._build_email_subject(campaign)}\n\n"
            "Bonjour,\n\n"
            f"{self._article_intro(campaign, 'email_manual')}\n\n"
            f"{self._article_promise(campaign)}\n\n"
            f"- {bullets[0]}\n"
            f"- {bullets[1]}\n"
            f"- {bullets[2]}\n\n"
            f"Prochaine etape : {self._call_to_action(campaign, 'email_manual')}\n\n"
            "Bien cordialement,"
        )

    def _build_email_html_from_campaign(self, campaign: CampaignRun) -> str:
        bullets = "".join(f"<li>{item}</li>" for item in self._bullet_points(campaign, "email_manual")[:3])
        return (
            f"<p><strong>Objet :</strong> {self._build_email_subject(campaign)}</p>"
            "<p>Bonjour,</p>"
            f"<p>{self._article_intro(campaign, 'email_manual')}</p>"
            f"<p>{self._article_promise(campaign)}</p>"
            f"<ul>{bullets}</ul>"
            f"<p><strong>Prochaine etape :</strong> {self._call_to_action(campaign, 'email_manual')}</p>"
            "<p>Bien cordialement,</p>"
        )

    def _article_intro(self, campaign: CampaignRun, channel: str) -> str:
        if campaign.campaign_type == "MAPSI_USERS":
            return f"Cette communication met l'accent sur {campaign.theme} pour aider les utilisateurs MAPSI a aller droit au but."
        if campaign.campaign_type == "MAPSI_MARKETING":
            if channel == "oling_site":
                return f"Cette communication relie {campaign.theme} aux usages terrain, aux projets menes et a la proposition de valeur Oling."
            return f"Cette communication valorise {campaign.theme} pour le marketing et la communication autour de MAPSI."
        return f"Cette communication Oling traite le theme {campaign.theme} avec une approche operationnelle et concrete."

    def _article_usage(self, campaign: CampaignRun, channel: str) -> str:
        if channel == "mapsi_site":
            return "Le contenu s'appuie sur la base de connaissance MAPSI, les evolutions produit et les cas d'usage communicables."
        if channel == "oling_site":
            return "Le contenu s'appuie sur les expertises Oling, les references projet et les sujets a forte valeur MOA, RGPD ou transformation."
        return "Le contenu est declinable en publication manuelle courte pour LinkedIn."

    def _article_promise(self, campaign: CampaignRun) -> str:
        if campaign.campaign_type == "MAPSI_USERS":
            return "Le contenu doit rassurer, expliquer clairement le benefice utilisateur et montrer un gain concret sans surcharge technique."
        if campaign.campaign_type == "MAPSI_MARKETING":
            return "Le contenu doit articuler valeur produit, credibilite terrain et capacite a transformer un besoin en usage concret."
        return "Le contenu doit montrer une expertise utile, orientee decision et execution, avec une posture conseil credibile."

    def _bullet_points(self, campaign: CampaignRun, channel: str) -> list[str]:
        if campaign.campaign_type == "MAPSI_USERS":
            return [
                f"Le sujet {campaign.theme.lower()} est traite avec un angle tres operationnel pour les utilisateurs.",
                "Le message met en avant un gain de temps, de lisibilite ou de fiabilite dans l'usage quotidien.",
                "La communication reste simple, utile et directement exploitable dans le contexte MAPSI.",
            ]
        if campaign.campaign_type == "MAPSI_MARKETING":
            return [
                f"La communication relie {campaign.theme.lower()} a des cas d'usage communicables et concrets.",
                "Le discours montre a la fois la valeur produit, les projets menes et la capacite d'accompagnement.",
                f"Le canal {channel} sert a adapter le ton entre valorisation produit et preuve par l'execution.",
            ]
        return [
            f"Le theme {campaign.theme.lower()} est traite sous un angle metier clair et decisionnel.",
            "Le contenu alterne pedagogie, points d'attention et benefices attendus pour le client.",
            "La communication doit faire percevoir une expertise structurante, sans jargon inutile.",
        ]

    def _image_suggestion(self, campaign: CampaignRun, channel: str) -> str:
        if campaign.campaign_type == "MAPSI_USERS":
            return "capture d'ecran epuree de MAPSI illustrant le parcours utilisateur ou le tableau de bord concerne"
        if campaign.campaign_type == "MAPSI_MARKETING" and channel == "oling_site":
            return "illustration editoriale melangeant interface produit, scene de reunion projet et elements de cadrage"
        if campaign.campaign_type == "MAPSI_MARKETING":
            return "visuel hero de type produit-service montrant MAPSI en situation d'usage concret"
        return "illustration professionnelle sobre evoquant atelier, gouvernance, cadrage ou transformation du metier"

    def _call_to_action(self, campaign: CampaignRun, channel: str) -> str:
        if channel == "mapsi_site":
            if campaign.campaign_type == "MAPSI_USERS":
                return "Inviter le lecteur a tester la fonctionnalite, relire son parcours et passer rapidement a l'action."
            return "Inviter le lecteur a decouvrir la fonctionnalite, demander une demonstration ou prendre contact."
        if channel == "oling_site":
            if campaign.campaign_type == "MAPSI_MARKETING":
                return "Inviter le lecteur a explorer la complementarite produit-service et a demander un echange de cadrage."
            return "Inviter le lecteur a prendre rendez-vous, cadrer son besoin ou demander un premier echange."
        if channel == "email_manual":
            return "Envoyer manuellement l'email a la cible retenue avec un objet clair et un angle editorial direct."
        if campaign.campaign_type == "MAPSI_USERS":
            return "Publier manuellement sur LinkedIn avec un ton utile, simple et centre adoption."
        if campaign.campaign_type == "MAPSI_MARKETING":
            return "Publier manuellement sur LinkedIn avec un ton de preuve, de valeur et de credibilite terrain."
        return "Publier manuellement sur LinkedIn avec un ton conseil, sobre et professionnel."

    def _summary_excerpt(self, campaign: CampaignRun, channel: str) -> str:
        return f"{campaign.theme} - communication {channel} structuree avec angle, points cles et illustration suggeree."

    def _tone_signature(self, campaign: CampaignRun, channel: str) -> str:
        if campaign.campaign_type == "MAPSI_USERS":
            if channel == "linkedin_manual":
                return "Ton recommande : pedagogique, direct, rassurant, centre usage."
            return "Ton recommande : clair, pratique, orienté adoption et mise en mouvement."
        if campaign.campaign_type == "MAPSI_MARKETING":
            if channel == "oling_site":
                return "Ton recommande : conseil, structurant, axe sur la complementarite entre produit, projet et accompagnement."
            if channel == "linkedin_manual":
                return "Ton recommande : impact, preuve, credibilite, sans surpromesse."
            if channel == "email_manual":
                return "Ton recommande : professionnel, direct, personnalise, avec une progression claire du sujet vers l'action."
            return "Ton recommande : valeur, clarte, demonstration par les usages et la execution."
        if channel == "email_manual":
            return "Ton recommande : expert, clair, relationnel, structure pour faciliter une prise de contact simple."
        if channel == "linkedin_manual":
            return "Ton recommande : expert, accessible, sobre, axe decision et confiance."
        return "Ton recommande : conseil metier, structuration, hauteur de vue et concretisation."

    def _linkedin_close(self, campaign: CampaignRun) -> str:
        if campaign.campaign_type == "MAPSI_USERS":
            return "Si le sujet vous parle, je peux partager le contenu complet et montrer comment l'activer dans MAPSI."
        if campaign.campaign_type == "MAPSI_MARKETING":
            return "Si le sujet vous parle, je peux partager le contenu complet et illustrer la valeur terrain derriere cette communication."
        return "Si le sujet vous parle, je peux partager le contenu complet et ouvrir un premier echange sur le bon angle d'accompagnement."

    def _article_closing(self, campaign: CampaignRun, channel: str) -> str:
        if channel == "mapsi_site":
            return "L'objectif est de produire un article direct, publiable rapidement sur MAPSI.fr."
        if channel == "oling_site":
            return "L'objectif est de produire un article direct, publiable rapidement sur Oling."
        return "L'objectif est de fournir un message court a publier manuellement."
