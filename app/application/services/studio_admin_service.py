from __future__ import annotations

import csv
import json
from datetime import UTC, datetime, timedelta
from io import StringIO
from uuid import uuid4

from app.application.dto_studio_admin import (
    StudioAdminApproval,
    StudioAdminAssetSummary,
    StudioAdminAssetVersion,
    StudioAdminAuditEvent,
    StudioAdminBulkDecisionResult,
    StudioAdminCampaignSummary,
    StudioAdminChannel,
    StudioAdminDashboard,
    StudioAdminEvidence,
    StudioAdminHealth,
    StudioAdminPublicationOperation,
    StudioAdminPreview,
    StudioAdminPublication,
    StudioAdminGlobalKillSwitch,
    StudioAdminWeeklyPack,
    StudioAdminWeeklyPackCampaign,
    StudioAdminEditorialPreviewFact,
    StudioAdminEditorialSourceAttachmentReference,
    StudioAdminEditorialSourceItem,
    StudioAdminEditorialSourcePack,
    StudioAdminEditorialSourcePreview,
)
from app.application.services.campaign_publisher import CampaignPublisher
from app.application.services.campaign_service import CampaignService
from app.application.services.editorial_production_v1 import EditorialAssetMutationService, MapsiMarketProductionBuilder, OlingPracticeProductionBuilder
from app.application.services.linkedin_post_publisher import LinkedInPostPublisher
from app.application.services.mapsi_news_publisher import MapsiNewsPublisher
from app.application.services.mapsi_user_weekly_email_builder import MapsiUserWeeklyEmailBuilder
from app.application.services.operation_mode_service import OperationModeService
from app.application.services.oling_news_publisher import OlingNewsPublisher
from app.application.services.review_portal_service import ReviewPortalService
from app.core.config import get_settings
from app.contracts import read_contract_metadata
from app.core.security import sha256_hexdigest
from app.domain.entities import CampaignRun, ContentAsset
from app.domain.entities import AudienceSegment, EditorialBrief, EditorialSourceItem, EditorialSourcePack, SourceEvidence, WeeklyCommunicationPack, build_content_hash, utcnow
from app.domain.enums import AssetStatus, CampaignStatus
from app.domain.errors import CampaignNotFoundError, CampaignPublicationForbiddenError, EditorialSourceItemNotFoundError, EditorialSourcePackNotFoundError, WeeklyCommunicationPackConflictError, WeeklyCommunicationPackNotFoundError
from app.infrastructure.db.models import LinkedInPublicationModel, MapsiNewsPublicationModel, MauticCampaignPublicationModel, OlingNewsPublicationModel
from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository
from app.infrastructure.repositories.channel_operational_state import ChannelOperationalStateRepository
from app.infrastructure.repositories.linkedin import LinkedInPublicationRepository
from app.infrastructure.repositories.mautic_publications import MauticPublicationRepository
from app.infrastructure.repositories.mapsi_site_publications import MapsiNewsPublicationRepository
from app.infrastructure.repositories.oling import OlingNewsPublicationRepository
from app.infrastructure.repositories.review_portal import ReviewPortalRepository
from app.infrastructure.repositories.asset_revisions import AssetRevisionRepository
from app.infrastructure.repositories.editorial_source_packs import EditorialSourcePackRepository
from app.infrastructure.repositories.weekly_communication_packs import WeeklyCommunicationPackRepository


class StudioAdminService:
    def __init__(
        self,
        *,
        campaign_service: CampaignService,
        review_portal_service: ReviewPortalService,
        review_repository: ReviewPortalRepository,
        audit_repository: SqlAlchemyAuditLogRepository,
        mautic_publications: MauticPublicationRepository,
        linkedin_publications: LinkedInPublicationRepository,
        oling_publications: OlingNewsPublicationRepository,
        mapsi_site_publications: MapsiNewsPublicationRepository,
        channel_state_repository: ChannelOperationalStateRepository,
        weekly_pack_repository: WeeklyCommunicationPackRepository,
        editorial_source_pack_repository: EditorialSourcePackRepository,
        campaign_publisher: CampaignPublisher,
        linkedin_publisher: LinkedInPostPublisher,
        oling_publisher: OlingNewsPublisher,
        mapsi_publisher: MapsiNewsPublisher,
        mapsi_market_builder: MapsiMarketProductionBuilder,
        oling_practice_builder: OlingPracticeProductionBuilder,
        mapsi_users_builder: MapsiUserWeeklyEmailBuilder,
        editorial_asset_mutation_service: EditorialAssetMutationService | None = None,
        asset_revision_repository: AssetRevisionRepository | None = None,
    ) -> None:
        self.settings = get_settings()
        self.campaign_service = campaign_service
        self.review_portal_service = review_portal_service
        self.review_repository = review_repository
        self.audit_repository = audit_repository
        self.mautic_publications = mautic_publications
        self.linkedin_publications = linkedin_publications
        self.oling_publications = oling_publications
        self.mapsi_site_publications = mapsi_site_publications
        self.channel_state_repository = channel_state_repository
        self.weekly_pack_repository = weekly_pack_repository
        self.editorial_source_pack_repository = editorial_source_pack_repository
        self.campaign_publisher = campaign_publisher
        self.linkedin_publisher = linkedin_publisher
        self.oling_publisher = oling_publisher
        self.mapsi_publisher = mapsi_publisher
        self.mapsi_market_builder = mapsi_market_builder
        self.oling_practice_builder = oling_practice_builder
        self.mapsi_users_builder = mapsi_users_builder
        self.editorial_asset_mutation_service = editorial_asset_mutation_service
        self.asset_revision_repository = asset_revision_repository
        self.operation_mode = OperationModeService()

    def dashboard(self, filters: dict[str, object]) -> StudioAdminDashboard:
        campaigns = self._filter_campaigns(self.campaign_service.list_campaigns(), filters)
        assets = [asset for campaign in campaigns for asset in campaign.content_assets if self._asset_matches(asset, campaign, filters)]
        last_event = self._serialize_last_event(self.audit_repository.list_events(limit=1)[0]) if self.audit_repository.list_events(limit=1) else None
        return StudioAdminDashboard(
            campaigns_total=len(campaigns),
            campaigns_pending_validation=len([item for item in campaigns if self._campaign_pending_validation(item)]),
            campaigns_approved=len([item for item in campaigns if item.status in {CampaignStatus.APPROVED, CampaignStatus.PARTIALLY_PUBLISHED, CampaignStatus.PUBLISHED}]),
            campaigns_published=len([item for item in campaigns if item.status in {CampaignStatus.PARTIALLY_PUBLISHED, CampaignStatus.PUBLISHED}]),
            campaigns_in_error=len([item for item in campaigns if any(asset.status is AssetStatus.FAILED for asset in item.content_assets)]),
            assets_total=len(assets),
            assets_pending_validation=len([item for item in assets if item.status in {AssetStatus.READY_FOR_REVIEW, AssetStatus.QUALITY_CHECK}]),
            assets_approved=len([item for item in assets if item.status is AssetStatus.APPROVED]),
            assets_published=len([item for item in assets if item.status is AssetStatus.PUBLISHED]),
            assets_in_error=len([item for item in assets if item.status is AssetStatus.FAILED]),
            last_event=last_event,
            operational_mode=self.operation_mode.current_mode(),
            banner_message=self.operation_mode.banner_message(),
        )

    def list_campaigns(
        self,
        filters: dict[str, object],
        *,
        sort_by: str,
        sort_order: str,
        page: int,
        page_size: int,
    ) -> tuple[list[StudioAdminCampaignSummary], int]:
        campaigns = [self._campaign_summary(item) for item in self._filter_campaigns(self.campaign_service.list_campaigns(), filters)]
        campaigns = self._sort_items(campaigns, sort_by, sort_order)
        total = len(campaigns)
        return campaigns[(page - 1) * page_size : page * page_size], total

    def get_campaign(self, campaign_id: str) -> StudioAdminCampaignSummary:
        campaign = self.campaign_service.get_campaign(campaign_id)
        return self._campaign_summary(campaign)

    def create_weekly_pack(
        self,
        *,
        week_reference: str,
        year: int,
        week_number: int,
        pilot_mode: bool,
        actor: str,
        correlation_id: str,
    ) -> StudioAdminWeeklyPack:
        if self.weekly_pack_repository.get_by_week(year=year, week_number=week_number) is not None:
            raise WeeklyCommunicationPackConflictError(f"Weekly communication pack already exists for {year}-W{week_number:02d}.")
        campaigns: list[CampaignRun] = []
        for campaign_type, objective in (
            ("MAPSI_MARKET", "market_visibility"),
            ("OLING_PRACTICE", "practice_visibility"),
            ("MAPSI_USERS", "user_activation"),
        ):
            campaign = CampaignRun(
                name=f"{campaign_type.replace('_', ' ').title()} {week_reference}",
                objective=objective,
                campaign_type=campaign_type,
                week_reference=week_reference,
                week_year=year,
                week_number=week_number,
                pilot_mode=pilot_mode,
                status=CampaignStatus.NOT_STARTED,
            )
            campaign.audience_segments.append(
                AudienceSegment(
                    campaign_run_id=campaign.id,
                    name=f"{campaign_type} audience",
                    description=self._campaign_audience_description(campaign_type, pilot_mode=pilot_mode),
                )
            )
            campaigns.append(self.campaign_service.repository.add(campaign))
        pack = self.weekly_pack_repository.add(
            WeeklyCommunicationPack(
                week_reference=week_reference,
                year=year,
                week_number=week_number,
                status="NOT_STARTED",
                campaign_ids=[campaign.id for campaign in campaigns],
                global_summary={},
                operational_errors=[],
                pilot_mode=pilot_mode,
            )
        )
        for campaign in campaigns:
            campaign.weekly_pack_id = pack.id
            self.campaign_service.repository.save(campaign)
        self.audit_repository.append(
            None,
            "weekly_pack.created",
            {
                "weekly_pack_id": pack.id,
                "campaign_ids": pack.campaign_ids,
                "pilot_mode": pilot_mode,
            },
            actor_id=actor,
            actor_source="mapsi-studio",
            correlation_id=correlation_id,
            result="SUCCESS",
        )
        return self._weekly_pack_summary(pack)

    def list_weekly_packs(
        self,
        *,
        sort_by: str,
        sort_order: str,
        page: int,
        page_size: int,
    ) -> tuple[list[StudioAdminWeeklyPack], int]:
        packs = [self._weekly_pack_summary(pack) for pack in self.weekly_pack_repository.list()]
        packs = self._sort_items(packs, sort_by, sort_order)
        total = len(packs)
        return packs[(page - 1) * page_size : page * page_size], total

    def get_weekly_pack(self, pack_id: str) -> StudioAdminWeeklyPack:
        return self._weekly_pack_summary(self._load_weekly_pack(pack_id))

    def generate_weekly_pack(self, pack_id: str, *, actor: str, correlation_id: str) -> StudioAdminWeeklyPack:
        pack = self._load_weekly_pack(pack_id)
        generated_at = utcnow()
        errors: list[dict[str, object]] = []
        for campaign_id in pack.campaign_ids:
            campaign = self.campaign_service.get_campaign(campaign_id)
            try:
                self._generate_weekly_pack_campaign(pack, campaign)
            except Exception as exc:
                campaign.status = CampaignStatus.FAILED
                campaign.updated_at = utcnow()
                self.campaign_service.repository.save(campaign)
                errors.append({"campaign_id": campaign.id, "campaign_type": campaign.campaign_type, "error": str(exc)})
        pack.generated_at = generated_at
        pack.operational_errors = errors
        pack.status = self._compute_pack_status(pack)
        pack.global_summary = self._build_weekly_pack_global_summary(pack)
        if self._all_campaigns_reviewed(pack):
            pack.reviewed_at = pack.reviewed_at or utcnow()
        saved = self.weekly_pack_repository.save(pack)
        self.audit_repository.append(
            None,
            "weekly_pack.generated",
            {
                "weekly_pack_id": pack.id,
                "operational_errors": errors,
            },
            actor_id=actor,
            actor_source="mapsi-studio",
            correlation_id=correlation_id,
            result="SUCCESS" if not errors else "PARTIAL_SUCCESS",
        )
        return self._weekly_pack_summary(saved)

    def generate_weekly_pack_campaign(
        self,
        pack_id: str,
        *,
        campaign_type: str,
        actor: str,
        correlation_id: str,
    ) -> StudioAdminWeeklyPack:
        pack = self._load_weekly_pack(pack_id)
        campaign = self._load_weekly_pack_campaign(pack, campaign_type=campaign_type)
        errors: list[dict[str, object]] = []
        try:
            self._generate_weekly_pack_campaign(pack, campaign)
        except Exception as exc:
            campaign.status = CampaignStatus.FAILED
            campaign.updated_at = utcnow()
            self.campaign_service.repository.save(campaign)
            errors.append({"campaign_id": campaign.id, "campaign_type": campaign.campaign_type, "error": str(exc)})
        pack.generated_at = pack.generated_at or utcnow()
        pack.operational_errors = [item for item in pack.operational_errors if item.get("campaign_id") != campaign.id] + errors
        pack.status = self._compute_pack_status(pack)
        pack.global_summary = self._build_weekly_pack_global_summary(pack)
        if self._all_campaigns_reviewed(pack):
            pack.reviewed_at = pack.reviewed_at or utcnow()
        saved = self.weekly_pack_repository.save(pack)
        self.audit_repository.append(
            None,
            "weekly_pack.campaign_generated",
            {
                "weekly_pack_id": pack.id,
                "campaign_id": campaign.id,
                "campaign_type": campaign.campaign_type,
                "operational_errors": errors,
            },
            actor_id=actor,
            actor_source="mapsi-studio",
            correlation_id=correlation_id,
            result="SUCCESS" if not errors else "PARTIAL_SUCCESS",
        )
        return self._weekly_pack_summary(saved)

    def close_weekly_pack(self, pack_id: str, *, actor: str, correlation_id: str) -> StudioAdminWeeklyPack:
        pack = self._load_weekly_pack(pack_id)
        pack.completed_at = utcnow()
        pack.status = self._compute_pack_status(pack, closed=True)
        pack.global_summary = self._build_weekly_pack_global_summary(pack)
        saved = self.weekly_pack_repository.save(pack)
        self.audit_repository.append(
            None,
            "weekly_pack.closed",
            {
                "weekly_pack_id": pack.id,
                "status": saved.status,
            },
            actor_id=actor,
            actor_source="mapsi-studio",
            correlation_id=correlation_id,
            result="SUCCESS",
        )
        return self._weekly_pack_summary(saved)

    def return_to_safe_mode(self, *, actor: str, correlation_id: str) -> dict[str, object]:
        before_global = self.channel_state_repository.is_global_kill_switch_active(static_default=self.settings.workflow_kill_switch)
        before_channels = {
            channel: self._channel_summary(channel)
            for channel in self.operation_mode.safe_mode_channels()
            if channel in self._channel_catalog()
        }
        updated_channels: list[dict[str, object]] = []
        for channel in before_channels:
            record = self.channel_state_repository.save_channel(
                channel=channel,
                feature_enabled=False,
                feature_expires_at=None,
                emergency_kill_switch=self.channel_state_repository.is_channel_kill_switch_active(channel),
                updated_by=actor,
            )
            self.channel_state_repository.append_audit(
                scope=channel,
                action="safe_mode.channel_disabled",
                actor_id=actor,
                correlation_id=correlation_id,
                idempotency_key="",
                payload={"feature_enabled": False, "emergency_kill_switch": record.emergency_kill_switch},
            )
            updated_channels.append(
                {
                    "channel": channel,
                    "feature_enabled": record.feature_enabled,
                    "emergency_kill_switch": record.emergency_kill_switch,
                    "updated_at": record.updated_at,
                }
            )
        global_record = self.channel_state_repository.save_global(
            global_kill_switch=self.operation_mode.safe_mode_global_kill_switch_target(),
            updated_by=actor,
        )
        self.channel_state_repository.append_audit(
            scope="global",
            action="safe_mode.global_kill_switch_updated",
            actor_id=actor,
            correlation_id=correlation_id,
            idempotency_key="",
            payload={"global_kill_switch": global_record.global_kill_switch},
        )
        report = {
            "operation_mode": self.operation_mode.current_mode(),
            "banner_message": self.operation_mode.banner_message(),
            "global_kill_switch": {
                "before": before_global,
                "after": global_record.global_kill_switch,
                "updated_at": global_record.updated_at,
            },
            "channels": updated_channels,
            "drafts_preserved": True,
        }
        self.audit_repository.append(
            None,
            "operation_mode.returned_to_safe_mode",
            {
                "before": {
                    "global_kill_switch": before_global,
                    "channels": {
                        key: {
                            "feature_enabled": value.feature_enabled,
                            "emergency_kill_switch": value.emergency_kill_switch,
                        }
                        for key, value in before_channels.items()
                    },
                },
                "after": report,
            },
            actor_id=actor,
            actor_source="mapsi-studio",
            correlation_id=correlation_id,
            result="SUCCESS",
        )
        return report

    def create_editorial_source_pack(
        self,
        *,
        weekly_pack_id: str,
        campaign_type: str,
        title: str,
        summary: str,
        confidentiality_level: str,
        actor: str,
        correlation_id: str,
    ) -> StudioAdminEditorialSourcePack:
        if weekly_pack_id:
            self._load_weekly_pack(weekly_pack_id)
        pack = self.editorial_source_pack_repository.add(
            EditorialSourcePack(
                weekly_pack_id=weekly_pack_id,
                campaign_type=campaign_type,
                title=title,
                summary=summary,
                confidentiality_level=confidentiality_level,
                created_by=actor,
            )
        )
        self.audit_repository.append(
            weekly_pack_id or None,
            "editorial_source_pack.created",
            {"source_pack_id": pack.id, "campaign_type": campaign_type},
            actor_id=actor,
            actor_source="mapsi-studio",
            correlation_id=correlation_id,
            result="SUCCESS",
        )
        return self._editorial_source_pack_summary(pack)

    def get_editorial_source_pack(self, source_pack_id: str) -> StudioAdminEditorialSourcePack:
        return self._editorial_source_pack_summary(self._load_editorial_source_pack(source_pack_id))

    def update_editorial_source_pack(
        self,
        source_pack_id: str,
        *,
        title: str,
        summary: str,
        confidentiality_level: str,
        actor: str,
        correlation_id: str,
    ) -> StudioAdminEditorialSourcePack:
        pack = self._load_editorial_source_pack(source_pack_id)
        previous_state = {"title": pack.title, "summary": pack.summary, "confidentiality_level": pack.confidentiality_level}
        pack.title = title
        pack.summary = summary
        pack.confidentiality_level = confidentiality_level
        saved = self.editorial_source_pack_repository.save(pack)
        self.audit_repository.append(
            pack.weekly_pack_id or None,
            "editorial_source_pack.updated",
            {"source_pack_id": pack.id},
            actor_id=actor,
            actor_source="mapsi-studio",
            correlation_id=correlation_id,
            previous_state=previous_state,
            new_state={"title": title, "summary": summary, "confidentiality_level": confidentiality_level},
            result="SUCCESS",
        )
        return self._editorial_source_pack_summary(saved)

    def validate_editorial_source_pack(self, source_pack_id: str, *, actor: str, correlation_id: str) -> StudioAdminEditorialSourcePack:
        pack = self._load_editorial_source_pack(source_pack_id)
        pack.status = "VALIDATED"
        pack.validated_by = actor
        pack.validated_at = utcnow()
        saved = self.editorial_source_pack_repository.save(pack)
        self.audit_repository.append(
            pack.weekly_pack_id or None,
            "editorial_source_pack.validated",
            {"source_pack_id": pack.id},
            actor_id=actor,
            actor_source="mapsi-studio",
            correlation_id=correlation_id,
            new_state={"status": "VALIDATED"},
            result="SUCCESS",
        )
        return self._editorial_source_pack_summary(saved)

    def add_editorial_source_item(
        self,
        source_pack_id: str,
        *,
        payload: dict[str, object],
        actor: str,
        correlation_id: str,
    ) -> StudioAdminEditorialSourcePack:
        pack = self._load_editorial_source_pack(source_pack_id)
        item = self._build_editorial_source_item(source_pack_id, payload)
        pack.items.append(item)
        saved = self.editorial_source_pack_repository.save(pack)
        self.audit_repository.append(
            pack.weekly_pack_id or None,
            "editorial_source_item.created",
            {"source_pack_id": pack.id, "source_item_id": item.id, "source_type": item.source_type},
            actor_id=actor,
            actor_source="mapsi-studio",
            correlation_id=correlation_id,
            result="SUCCESS",
        )
        return self._editorial_source_pack_summary(saved)

    def update_editorial_source_item(
        self,
        source_pack_id: str,
        item_id: str,
        *,
        payload: dict[str, object],
        actor: str,
        correlation_id: str,
    ) -> StudioAdminEditorialSourcePack:
        pack = self._load_editorial_source_pack(source_pack_id)
        item = self._find_editorial_source_item(pack, item_id)
        previous_state = {
            "factual_summary": item.factual_summary,
            "usable_facts": list(item.usable_facts),
            "anonymized_facts": list(item.anonymized_facts),
            "prohibited_facts": list(item.prohibited_facts),
        }
        updated = self._build_editorial_source_item(source_pack_id, payload, existing=item)
        index = next(index for index, current in enumerate(pack.items) if current.id == item_id)
        pack.items[index] = updated
        saved = self.editorial_source_pack_repository.save(pack)
        self.audit_repository.append(
            pack.weekly_pack_id or None,
            "editorial_source_item.updated",
            {"source_pack_id": pack.id, "source_item_id": item_id},
            actor_id=actor,
            actor_source="mapsi-studio",
            correlation_id=correlation_id,
            previous_state=previous_state,
            new_state={
                "factual_summary": updated.factual_summary,
                "usable_facts": list(updated.usable_facts),
                "anonymized_facts": list(updated.anonymized_facts),
                "prohibited_facts": list(updated.prohibited_facts),
            },
            result="SUCCESS",
        )
        return self._editorial_source_pack_summary(saved)

    def delete_editorial_source_item(
        self,
        source_pack_id: str,
        item_id: str,
        *,
        actor: str,
        correlation_id: str,
    ) -> StudioAdminEditorialSourcePack:
        pack = self._load_editorial_source_pack(source_pack_id)
        self._find_editorial_source_item(pack, item_id)
        saved = self.editorial_source_pack_repository.delete_item(source_pack_id, item_id)
        if saved is None:
            raise EditorialSourcePackNotFoundError(f"Editorial source pack {source_pack_id} not found.")
        self.audit_repository.append(
            pack.weekly_pack_id or None,
            "editorial_source_item.deleted",
            {"source_pack_id": pack.id, "source_item_id": item_id},
            actor_id=actor,
            actor_source="mapsi-studio",
            correlation_id=correlation_id,
            result="SUCCESS",
        )
        return self._editorial_source_pack_summary(saved)

    def preview_editorial_source_pack(self, source_pack_id: str) -> StudioAdminEditorialSourcePreview:
        pack = self._load_editorial_source_pack(source_pack_id)
        allowed: list[StudioAdminEditorialPreviewFact] = []
        blocked: list[StudioAdminEditorialPreviewFact] = []
        confidential_items = 0
        anonymized_items = 0
        for item in pack.items:
            if item.confidentiality_level in {"CLIENT_CONFIDENTIAL", "STRICTLY_CONFIDENTIAL"}:
                confidential_items += 1
            allowed_facts, blocked_facts, anonymized = self._editorial_preview_for_item(item)
            if anonymized:
                anonymized_items += 1
            allowed.extend(allowed_facts)
            blocked.extend(blocked_facts)
        return StudioAdminEditorialSourcePreview(
            source_pack_id=pack.id,
            allowed_facts=allowed,
            blocked_facts=blocked,
            redaction_summary={
                "items_total": len(pack.items),
                "items_confidential": confidential_items,
                "items_anonymized": anonymized_items,
                "attachments_sent_to_model": 0,
            },
        )

    def list_campaign_assets(
        self,
        campaign_id: str,
        filters: dict[str, object],
        *,
        sort_by: str,
        sort_order: str,
        page: int,
        page_size: int,
    ) -> tuple[list[StudioAdminAssetSummary], int]:
        campaign = self.campaign_service.get_campaign(campaign_id)
        assets = [
            self._asset_summary(campaign, asset)
            for asset in campaign.content_assets
            if self._asset_matches(asset, campaign, filters)
        ]
        assets = self._sort_items(assets, sort_by, sort_order)
        total = len(assets)
        return assets[(page - 1) * page_size : page * page_size], total

    def list_assets(
        self,
        filters: dict[str, object],
        *,
        sort_by: str,
        sort_order: str,
        page: int,
        page_size: int,
    ) -> tuple[list[StudioAdminAssetSummary], int]:
        assets: list[StudioAdminAssetSummary] = []
        for campaign in self._filter_campaigns(self.campaign_service.list_campaigns(), filters):
            for asset in campaign.content_assets:
                if self._asset_matches(asset, campaign, filters):
                    assets.append(self._asset_summary(campaign, asset))
        assets = self._sort_items(assets, sort_by, sort_order)
        total = len(assets)
        return assets[(page - 1) * page_size : page * page_size], total

    def get_asset(self, asset_id: str) -> StudioAdminAssetSummary:
        campaign, asset = self._find_asset(asset_id)
        return self._asset_summary(campaign, asset)

    def get_asset_versions(self, asset_id: str) -> list[StudioAdminAssetVersion]:
        campaign, asset = self._find_asset(asset_id)
        review = self.review_repository.get_review_by_campaign(campaign.id)
        publication = self._publication_for_asset(campaign, asset)
        versions = [
            StudioAdminAssetVersion(
                version=asset.content_version,
                label="current",
                status=asset.status.value,
                content_hash=asset.content_hash,
                approved_content_hash=asset.approved_content_hash,
                published_at=asset.published_at,
                created_at=asset.created_at,
                title=asset.title,
                subject=asset.subject,
                content_html=asset.content_html or asset.body,
                content_text=asset.content_text,
                excerpt=asset.excerpt,
                call_to_action=asset.call_to_action,
                target_url=asset.target_url,
                metadata={"revision": asset.revision},
            )
        ]
        if self.asset_revision_repository is not None:
            for snapshot in self.asset_revision_repository.list_for_asset(asset_id):
                versions.append(
                    StudioAdminAssetVersion(
                        version=snapshot.version,
                        label="snapshot",
                        status=snapshot.status,
                        content_hash=snapshot.content_hash,
                        approved_content_hash=snapshot.approved_content_hash,
                        published_at=None,
                        created_at=snapshot.created_at,
                        title=snapshot.title,
                        subject=snapshot.subject,
                        content_html=snapshot.content_html,
                        content_text=snapshot.content_text,
                        excerpt=snapshot.excerpt,
                        call_to_action=snapshot.call_to_action,
                        target_url=snapshot.target_url,
                        metadata=dict(snapshot.results or {}),
                    )
                )
        if review is not None:
            versions.append(
                StudioAdminAssetVersion(
                    version=review.content_version,
                    label="review",
                    status="approved" if review.approved_at else "pending",
                    content_hash=review.approved_content_hash or "",
                    approved_content_hash=review.approved_content_hash or "",
                    published_at=review.approved_at,
                    created_at=review.proposed_at,
                    title=review.email_subject,
                    subject=review.email_subject,
                    content_html=review.email_html,
                    content_text=review.email_text,
                    excerpt=review.email_preheader,
                    metadata={"segment_version": review.segment_version},
                )
            )
        if publication is not None:
            versions.append(
                StudioAdminAssetVersion(
                    version=self._publication_version(asset, publication),
                    label="publication",
                    status=str(getattr(publication, "publication_status", getattr(publication, "status", ""))).upper(),
                    content_hash=getattr(publication, "content_hash", asset.content_hash),
                    approved_content_hash=asset.approved_content_hash,
                    published_at=getattr(publication, "published_at", None),
                    created_at=getattr(publication, "created_at", None),
                    title=asset.title,
                    subject=asset.subject,
                    content_html=asset.content_html or asset.body,
                    content_text=asset.content_text,
                    excerpt=asset.excerpt,
                    call_to_action=asset.call_to_action,
                    target_url=asset.target_url,
                    metadata=self._publication_metadata(publication),
                )
            )
        return versions

    def update_asset_draft(
        self,
        asset_id: str,
        *,
        actor: str,
        expected_version: int,
        correlation_id: str,
        idempotency_key: str | None,
        comment: str = "",
        title: str | None = None,
        subject: str | None = None,
        content_html: str | None = None,
        content_text: str | None = None,
        excerpt: str | None = None,
        call_to_action: str | None = None,
        target_url: str | None = None,
    ) -> StudioAdminAssetSummary:
        asset = self.review_portal_service.update_asset_draft(
            asset_id,
            actor=actor,
            expected_version=expected_version,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            comment=comment,
            title=title,
            subject=subject,
            content_html=content_html,
            content_text=content_text,
            excerpt=excerpt,
            call_to_action=call_to_action,
            target_url=target_url,
        )
        campaign = self.campaign_service.get_campaign(asset.campaign_run_id)
        return self._asset_summary(campaign, asset)

    def generate_mapsi_market(
        self,
        *,
        actor: str,
        correlation_id: str,
        weekly_pack_id: str = "",
        pilot_mode: bool = False,
    ) -> StudioAdminCampaignSummary:
        campaign = CampaignRun(
            name=f"MAPSI market {datetime.now(UTC).date().isoformat()}",
            objective="market_visibility",
            campaign_type="MAPSI_MARKET",
            status=CampaignStatus.DRAFT,
            weekly_pack_id=weekly_pack_id,
            pilot_mode=pilot_mode,
        )
        campaign.audience_segments.append(AudienceSegment(campaign_run_id=campaign.id, name="market", description="MAPSI market"))
        generated = self.mapsi_market_builder.build(weekly_pack_id=weekly_pack_id, pilot_mode=pilot_mode, record_theme_history=True)
        brief = EditorialBrief(campaign_run_id=campaign.id, title=generated.brief.selected_topic, summary=generated.brief.objective)
        campaign.editorial_briefs = [brief]
        campaign.content_assets = generated.assets
        campaign.status = CampaignStatus.READY_FOR_REVIEW if any(asset.status is AssetStatus.READY_FOR_REVIEW for asset in generated.assets) else CampaignStatus.FAILED
        campaign = self.campaign_service.repository.add(campaign)
        self.audit_repository.append(campaign.id, "editorial.mapsi_market_generated", {"actor": actor, "correlation_id": correlation_id}, actor_id=actor, actor_source="studio_admin")
        return self._campaign_summary(campaign)

    def generate_oling_practice(
        self,
        *,
        actor: str,
        correlation_id: str,
        weekly_pack_id: str = "",
        pilot_mode: bool = False,
    ) -> StudioAdminCampaignSummary:
        campaign = CampaignRun(
            name=f"OLING practice {datetime.now(UTC).date().isoformat()}",
            objective="practice_visibility",
            campaign_type="OLING_PRACTICE",
            status=CampaignStatus.DRAFT,
            weekly_pack_id=weekly_pack_id,
            pilot_mode=pilot_mode,
        )
        campaign.audience_segments.append(AudienceSegment(campaign_run_id=campaign.id, name="practice", description="OLING practice"))
        generated = self.oling_practice_builder.build(weekly_pack_id=weekly_pack_id, pilot_mode=pilot_mode, record_theme_history=True)
        brief = EditorialBrief(campaign_run_id=campaign.id, title=generated.brief.practice, summary=generated.brief.business_problem)
        campaign.editorial_briefs = [brief]
        campaign.content_assets = generated.assets
        campaign.status = CampaignStatus.READY_FOR_REVIEW if any(asset.status is AssetStatus.READY_FOR_REVIEW for asset in generated.assets) else CampaignStatus.FAILED
        campaign = self.campaign_service.repository.add(campaign)
        self.audit_repository.append(campaign.id, "editorial.oling_practice_generated", {"actor": actor, "correlation_id": correlation_id}, actor_id=actor, actor_source="studio_admin")
        return self._campaign_summary(campaign)

    def request_asset_regeneration(
        self,
        asset_id: str,
        *,
        actor: str,
        expected_version: int,
        correlation_id: str,
        idempotency_key: str | None,
        comment: str = "",
    ) -> StudioAdminAssetSummary:
        asset = self.review_portal_service.request_asset_regeneration(
            asset_id,
            actor=actor,
            expected_version=expected_version,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            comment=comment,
        )
        campaign = self.campaign_service.get_campaign(asset.campaign_run_id)
        return self._asset_summary(campaign, asset)

    def regenerate_asset(
        self,
        asset_id: str,
        *,
        actor: str,
        expected_version: int,
        correlation_id: str,
        idempotency_key: str | None,
        comment: str = "",
    ) -> StudioAdminAssetSummary:
        if self.editorial_asset_mutation_service is None:
            raise CampaignPublicationForbiddenError("Editorial regeneration service is not configured.")
        asset = self.editorial_asset_mutation_service.regenerate(asset_id, actor=actor, expected_version=expected_version, instruction=comment)
        campaign = self.campaign_service.get_campaign(asset.campaign_run_id)
        return self._asset_summary(campaign, asset)

    def rewrite_asset(
        self,
        asset_id: str,
        *,
        actor: str,
        expected_version: int,
        correlation_id: str,
        idempotency_key: str | None,
        instruction: str = "",
        desired_title: str = "",
        length_directive: str = "",
        angle_directive: str = "",
    ) -> StudioAdminAssetSummary:
        if self.editorial_asset_mutation_service is None:
            raise CampaignPublicationForbiddenError("Editorial rewrite service is not configured.")
        asset = self.editorial_asset_mutation_service.regenerate(
            asset_id,
            actor=actor,
            expected_version=expected_version,
            instruction=instruction,
            desired_title=desired_title,
            length_directive=length_directive,
            angle_directive=angle_directive,
        )
        campaign = self.campaign_service.get_campaign(asset.campaign_run_id)
        return self._asset_summary(campaign, asset)

    def request_asset_changes(
        self,
        asset_id: str,
        *,
        actor: str,
        expected_version: int,
        correlation_id: str,
        idempotency_key: str | None,
        comment: str,
    ) -> StudioAdminAssetSummary:
        asset = self.review_portal_service.request_asset_changes(
            asset_id,
            actor=actor,
            expected_version=expected_version,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            comment=comment,
        )
        campaign = self.campaign_service.get_campaign(asset.campaign_run_id)
        return self._asset_summary(campaign, asset)

    def approve_asset(
        self,
        asset_id: str,
        *,
        actor: str,
        expected_version: int,
        correlation_id: str,
        idempotency_key: str | None,
        comment: str = "",
    ) -> StudioAdminAssetSummary:
        asset = self.review_portal_service.approve_asset(
            asset_id,
            actor=actor,
            expected_version=expected_version,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            comment=comment,
        )
        campaign = self.campaign_service.get_campaign(asset.campaign_run_id)
        return self._asset_summary(campaign, asset)

    def reject_asset(
        self,
        asset_id: str,
        *,
        actor: str,
        expected_version: int,
        correlation_id: str,
        idempotency_key: str | None,
        comment: str,
    ) -> StudioAdminAssetSummary:
        asset = self.review_portal_service.reject_asset(
            asset_id,
            actor=actor,
            expected_version=expected_version,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            comment=comment,
        )
        campaign = self.campaign_service.get_campaign(asset.campaign_run_id)
        return self._asset_summary(campaign, asset)

    def approve_ready_assets(
        self,
        campaign_id: str,
        *,
        actor: str,
        correlation_id: str,
        idempotency_key: str | None,
        comment: str = "",
    ) -> StudioAdminBulkDecisionResult:
        assets = self.review_portal_service.approve_ready_assets(
            campaign_id,
            actor=actor,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            comment=comment,
        )
        campaign = self.campaign_service.get_campaign(campaign_id)
        return StudioAdminBulkDecisionResult(
            campaign_id=campaign_id,
            decision="APPROVED",
            comment=comment,
            processed_at=datetime.now(UTC),
            assets=[self._asset_summary(campaign, asset) for asset in assets],
        )

    def reject_ready_assets(
        self,
        campaign_id: str,
        *,
        actor: str,
        correlation_id: str,
        idempotency_key: str | None,
        comment: str,
    ) -> StudioAdminBulkDecisionResult:
        assets = self.review_portal_service.reject_ready_assets(
            campaign_id,
            actor=actor,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            comment=comment,
        )
        campaign = self.campaign_service.get_campaign(campaign_id)
        return StudioAdminBulkDecisionResult(
            campaign_id=campaign_id,
            decision="REJECTED",
            comment=comment,
            processed_at=datetime.now(UTC),
            assets=[self._asset_summary(campaign, asset) for asset in assets],
        )

    def get_asset_publication_readiness(
        self,
        asset_id: str,
        *,
        correlation_id: str,
        scheduled_at: datetime | None = None,
    ) -> StudioAdminPublicationOperation:
        campaign, asset = self._find_asset(asset_id)
        readiness = self.review_portal_service.publication_readiness(campaign.id, scheduled_at=scheduled_at or asset.scheduled_at)
        status = "ready" if readiness.get("publishable") else "blocked"
        return self._publication_operation(
            asset,
            requested_action="recalculate_readiness",
            status=status,
            correlation_id=correlation_id,
            metadata=readiness,
        )

    def create_asset_preview(
        self,
        asset_id: str,
        *,
        actor: str,
        correlation_id: str,
    ) -> StudioAdminPublicationOperation:
        campaign, asset = self._find_asset(asset_id)
        if asset.channel == "oling":
            details = self.oling_publisher.create_preview(campaign, asset)
        elif asset.channel == "mapsi_site":
            details = self.mapsi_publisher.create_preview(campaign, asset)
            self.audit_repository.append(
                campaign.id,
                "publication.preview_created",
                {"preview_url": str(details.get("preview_url") or "")},
                asset_id=asset.id,
                actor_id=actor,
                actor_source="mapsi-studio",
                correlation_id=correlation_id,
                previous_state={"status": asset.status.value},
                new_state={"status": asset.status.value},
                channel=asset.channel,
                result="SUCCESS",
            )
            return self._publication_operation(
                asset,
                requested_action="create_preview",
                status="preview_ready",
                correlation_id=correlation_id,
                publisher=str(details.get("publisher_type") or asset.results.get("publisher_type") or ""),
                external_id=str(details.get("external_publication_id") or details.get("external_id") or asset.external_publication_id),
                preview_url=str(details.get("preview_url") or ""),
                public_url="",
                published_at=asset.published_at,
                metadata=details,
                use_asset_public_url_fallback=False,
            )
        if asset.channel == "oling":
            self.audit_repository.append(
                campaign.id,
                "publication.preview_created",
                {"preview_url": str(details.get("preview_url") or "")},
                asset_id=asset.id,
                actor_id=actor,
                actor_source="mapsi-studio",
                correlation_id=correlation_id,
                previous_state={"status": asset.status.value},
                new_state={"status": asset.status.value},
                channel=asset.channel,
                result="SUCCESS",
            )
            return self._publication_operation(
                asset,
                requested_action="create_preview",
                status="preview_ready",
                correlation_id=correlation_id,
                publisher=str(details.get("publisher_type") or asset.results.get("publisher_type") or ""),
                external_id=str(details.get("external_publication_id") or details.get("external_id") or asset.external_publication_id),
                preview_url=str(details.get("preview_url") or ""),
                public_url="",
                published_at=asset.published_at,
                metadata=details,
                use_asset_public_url_fallback=False,
            )
        if asset.channel == "mautic":
            details = self.campaign_publisher.create_preview(campaign.id)
            return self._publication_operation(
                asset,
                requested_action="create_preview",
                status="preview_ready",
                correlation_id=correlation_id,
                publisher="mautic_api",
                external_id=str(details.get("mautic_campaign_id", "")),
                metadata=details,
            )
        raise CampaignPublicationForbiddenError(f"Preview is not supported for channel {asset.channel}.")

    def schedule_asset_publication(
        self,
        asset_id: str,
        *,
        actor: str,
        correlation_id: str,
        scheduled_at: datetime,
        idempotency_key: str | None = None,
    ) -> StudioAdminPublicationOperation:
        campaign, asset = self._find_asset(asset_id)
        readiness = self.review_portal_service.publication_readiness(campaign.id, scheduled_at=scheduled_at)
        if not readiness.get("publishable"):
            raise CampaignPublicationForbiddenError("Asset campaign is not publishable.")
        if asset.channel == "mautic":
            details = self.campaign_publisher.schedule_campaign(campaign.id, scheduled_at=scheduled_at, idempotency_key=idempotency_key or "")
            self.audit_repository.append(
                campaign.id,
                "publication.scheduled",
                {"scheduled_at": scheduled_at.isoformat(), "publisher": "mautic_api"},
                asset_id=asset.id,
                actor_id=actor,
                actor_source="mapsi-studio",
                correlation_id=correlation_id,
                idempotency_key=idempotency_key or "",
                previous_state={"status": asset.status.value, "scheduled_at": asset.scheduled_at.isoformat() if asset.scheduled_at else ""},
                new_state={"status": asset.status.value, "scheduled_at": scheduled_at.isoformat()},
                channel=asset.channel,
                result="SUCCESS",
            )
            return self._publication_operation(
                asset,
                requested_action="schedule",
                status="scheduled",
                correlation_id=correlation_id,
                publisher="mautic_api",
                external_id=str(details.get("mautic_campaign_id", "")),
                scheduled_at=scheduled_at,
                metadata=details,
            )
        if asset.channel in {"oling", "mapsi_site"}:
            asset.scheduled_at = scheduled_at.astimezone(UTC)
            self.review_portal_service.campaign_repository.save(campaign)
            details = self.oling_publisher.create_preview(campaign, asset) if asset.channel == "oling" else self.mapsi_publisher.create_preview(campaign, asset)
            self.audit_repository.append(
                campaign.id,
                "publication.scheduled",
                {"scheduled_at": asset.scheduled_at.isoformat(), "preview_url": str(details.get("preview_url") or "")},
                asset_id=asset.id,
                actor_id=actor,
                actor_source="mapsi-studio",
                correlation_id=correlation_id,
                idempotency_key=idempotency_key or "",
                previous_state={"status": asset.status.value},
                new_state={"status": asset.status.value, "scheduled_at": asset.scheduled_at.isoformat()},
                channel=asset.channel,
                result="SUCCESS",
            )
            return self._publication_operation(
                asset,
                requested_action="schedule",
                status="scheduled",
                correlation_id=correlation_id,
                publisher=str(details.get("publisher_type") or asset.results.get("publisher_type") or ""),
                external_id=str(details.get("external_publication_id") or details.get("external_id") or asset.external_publication_id),
                preview_url=str(details.get("preview_url") or ""),
                scheduled_at=asset.scheduled_at,
                metadata={**details, "readiness": readiness},
            )
        raise CampaignPublicationForbiddenError(f"Scheduling is not supported for channel {asset.channel}.")

    def publish_asset_operation(
        self,
        asset_id: str,
        *,
        actor: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> StudioAdminPublicationOperation:
        campaign, asset = self._find_asset(asset_id)
        if asset.channel == "oling":
            existing = self.oling_publications.get_by_asset_hash(asset.id, asset.content_hash)
            if existing is not None and existing.publication_status == "PUBLISHED":
                return self._publication_operation(
                    asset,
                    requested_action="publish",
                    status="published",
                    correlation_id=correlation_id,
                    publisher=existing.publisher_type,
                    external_id=existing.external_id,
                    preview_url=existing.preview_url,
                    public_url=existing.public_url,
                    scheduled_at=asset.scheduled_at,
                    published_at=existing.published_at,
                    metadata=self.oling_publisher._serialize(existing),  # type: ignore[attr-defined]
                    use_asset_public_url_fallback=False,
                )
        if asset.channel == "mapsi_site":
            existing = self.mapsi_site_publications.get_by_asset_hash(asset.id, asset.content_hash)
            if existing is not None and existing.publication_status == "PUBLISHED":
                return self._publication_operation(
                    asset,
                    requested_action="publish",
                    status="published",
                    correlation_id=correlation_id,
                    publisher=existing.publisher_type,
                    external_id=existing.external_id,
                    preview_url=existing.preview_url,
                    public_url=existing.public_url,
                    scheduled_at=asset.scheduled_at,
                    published_at=existing.published_at,
                    metadata=self.mapsi_publisher._serialize(existing),  # type: ignore[attr-defined]
                    use_asset_public_url_fallback=False,
                )
        readiness = self.review_portal_service.publication_readiness(campaign.id, scheduled_at=asset.scheduled_at)
        if not readiness.get("publishable"):
            raise CampaignPublicationForbiddenError("Asset campaign is not publishable.")
        if asset.channel == "oling":
            details = self.oling_publisher.publish_asset(campaign.id, asset.id, idempotency_key=idempotency_key)
            payload = dict(details.get("details") or {})
            self.audit_repository.append(
                campaign.id,
                "publication.published",
                {"external_id": str(payload.get("external_publication_id") or payload.get("external_id") or ""), "public_url": str(payload.get("external_publication_url") or payload.get("public_url") or "")},
                asset_id=asset.id,
                actor_id=actor,
                actor_source="mapsi-studio",
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                previous_state={"status": "APPROVED"},
                new_state={"status": asset.status.value},
                channel=asset.channel,
                result="SUCCESS",
            )
            return self._publication_operation(
                asset,
                requested_action="publish",
                status=str(payload.get("publication_status", "published")).lower(),
                correlation_id=correlation_id,
                publisher=str(payload.get("publisher_type") or ""),
                external_id=str(payload.get("external_publication_id") or payload.get("external_id") or ""),
                preview_url=str(payload.get("preview_url") or ""),
                public_url=str(payload.get("external_publication_url") or payload.get("public_url") or ""),
                scheduled_at=asset.scheduled_at,
                published_at=asset.published_at,
                metadata=payload,
                use_asset_public_url_fallback=False,
            )
        if asset.channel == "mapsi_site":
            details = self.mapsi_publisher.publish_asset(campaign.id, asset.id, idempotency_key=idempotency_key)
            payload = dict(details.get("details") or {})
            self.audit_repository.append(
                campaign.id,
                "publication.published",
                {"external_id": str(payload.get("external_publication_id") or payload.get("external_id") or ""), "public_url": str(payload.get("external_publication_url") or payload.get("public_url") or "")},
                asset_id=asset.id,
                actor_id=actor,
                actor_source="mapsi-studio",
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                previous_state={"status": "APPROVED"},
                new_state={"status": asset.status.value},
                channel=asset.channel,
                result="SUCCESS",
            )
            return self._publication_operation(
                asset,
                requested_action="publish",
                status=str(payload.get("publication_status", "published")).lower(),
                correlation_id=correlation_id,
                publisher=str(payload.get("publisher_type") or ""),
                external_id=str(payload.get("external_publication_id") or payload.get("external_id") or ""),
                preview_url=str(payload.get("preview_url") or ""),
                public_url=str(payload.get("external_publication_url") or payload.get("public_url") or ""),
                scheduled_at=asset.scheduled_at,
                published_at=asset.published_at,
                metadata=payload,
                use_asset_public_url_fallback=False,
            )
        if asset.channel == "linkedin":
            details = self.linkedin_publisher.publish_asset(campaign.id, asset.id, idempotency_key=idempotency_key)
            self.audit_repository.append(
                campaign.id,
                "publication.published",
                {"external_id": str(details.get("linkedin_post_urn", "")), "public_url": str(details.get("linkedin_post_urn", ""))},
                asset_id=asset.id,
                actor_id=actor,
                actor_source="mapsi-studio",
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                previous_state={"status": "APPROVED"},
                new_state={"status": asset.status.value},
                channel=asset.channel,
                result="SUCCESS",
            )
            return self._publication_operation(
                asset,
                requested_action="publish",
                status=str(details.get("status", "published")).lower(),
                correlation_id=correlation_id,
                publisher="linkedin_api" if details.get("mode") != "manual" else "linkedin_manual",
                external_id=str(details.get("linkedin_post_urn", "")),
                public_url=str(details.get("linkedin_post_urn", "")),
                published_at=asset.published_at,
                metadata=details,
            )
        raise CampaignPublicationForbiddenError(f"Direct publication is not supported for channel {asset.channel}.")

    def retry_asset_publication(
        self,
        asset_id: str,
        *,
        actor: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> StudioAdminPublicationOperation:
        campaign, asset = self._find_asset(asset_id)
        if asset.channel not in {"oling", "mapsi_site"}:
            raise CampaignPublicationForbiddenError(f"Retry is not supported for channel {asset.channel}.")
        if asset.status is AssetStatus.FAILED and asset.approved_content_hash == asset.content_hash and asset.approved_at is not None:
            asset.status = AssetStatus.APPROVED
            self.review_portal_service.campaign_repository.save(campaign)
        self.audit_repository.append(
            campaign.id,
            "publication.retry_requested",
            {},
            asset_id=asset.id,
            actor_id=actor,
            actor_source="mapsi-studio",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            previous_state={"status": "FAILED"},
            new_state={"status": asset.status.value},
            channel=asset.channel,
            result="SUCCESS",
        )
        return self.publish_asset_operation(asset_id, actor=actor, correlation_id=correlation_id, idempotency_key=idempotency_key)

    def cancel_asset_publication(
        self,
        asset_id: str,
        *,
        actor: str,
        correlation_id: str,
    ) -> StudioAdminPublicationOperation:
        campaign, asset = self._find_asset(asset_id)
        if asset.channel in {"oling", "mapsi_site"} and asset.published_at is None:
            previous_schedule = asset.scheduled_at.isoformat() if asset.scheduled_at else ""
            asset.scheduled_at = None
            self.review_portal_service.campaign_repository.save(campaign)
            self.audit_repository.append(
                campaign.id,
                "publication.cancelled",
                {},
                asset_id=asset.id,
                actor_id=actor,
                actor_source="mapsi-studio",
                correlation_id=correlation_id,
                previous_state={"scheduled_at": previous_schedule},
                new_state={"scheduled_at": ""},
                channel=asset.channel,
                result="SUCCESS",
            )
            return self._publication_operation(
                asset,
                requested_action="cancel_publication",
                status="cancelled",
                correlation_id=correlation_id,
                publisher=str(asset.results.get("publisher_type", "")),
                external_id=asset.external_publication_id,
                preview_url=str(asset.results.get("preview_url", "")),
                metadata={"publication_status": asset.results.get("publication_status", "DRAFT")},
            )
        raise CampaignPublicationForbiddenError(f"Cancellation is not supported for channel {asset.channel}.")

    def unpublish_asset_operation(
        self,
        asset_id: str,
        *,
        actor: str,
        correlation_id: str,
    ) -> StudioAdminPublicationOperation:
        campaign, asset = self._find_asset(asset_id)
        if asset.channel not in {"oling", "mapsi_site"}:
            raise CampaignPublicationForbiddenError(f"Unpublish is not supported for channel {asset.channel}.")
        previous_status = asset.status.value
        if asset.channel == "oling":
            self.oling_publisher.unpublish(campaign, asset)
        else:
            self.mapsi_publisher.unpublish(campaign, asset)
        refreshed_campaign, refreshed_asset = self._find_asset(asset_id)
        details = self.oling_publisher.get_publication_status(refreshed_campaign, refreshed_asset) if refreshed_asset.channel == "oling" else self.mapsi_publisher.get_publication_status(refreshed_campaign, refreshed_asset)
        self.audit_repository.append(
            refreshed_campaign.id,
            "publication.unpublished",
            {"external_id": str(details.get("external_publication_id") or details.get("external_id") or "")},
            asset_id=refreshed_asset.id,
            actor_id=actor,
            actor_source="mapsi-studio",
            correlation_id=correlation_id,
            previous_state={"status": previous_status},
            new_state={"status": refreshed_asset.status.value},
            channel=refreshed_asset.channel,
            result="SUCCESS",
        )
        return self._publication_operation(
            refreshed_asset,
            requested_action="unpublish",
            status=str(details.get("publication_status", "unpublished")).lower(),
            correlation_id=correlation_id,
            publisher=str(details.get("publisher_type") or ""),
            external_id=str(details.get("external_publication_id") or details.get("external_id") or ""),
            preview_url=str(details.get("preview_url") or ""),
            public_url=str(details.get("external_publication_url") or details.get("public_url") or ""),
            scheduled_at=refreshed_asset.scheduled_at,
            published_at=refreshed_asset.published_at,
            metadata=details,
        )

    def get_asset_publication_operation_status(
        self,
        asset_id: str,
        *,
        correlation_id: str,
    ) -> StudioAdminPublicationOperation:
        campaign, asset = self._find_asset(asset_id)
        if asset.channel == "oling":
            details = self.oling_publisher.get_publication_status(campaign, asset)
            return self._publication_operation(
                asset,
                requested_action="publication_status",
                status=str(details.get("publication_status", "unknown")).lower(),
                correlation_id=correlation_id,
                publisher=str(details.get("publisher_type") or ""),
                external_id=str(details.get("external_publication_id") or details.get("external_id") or ""),
                preview_url=str(details.get("preview_url") or ""),
                public_url=str(details.get("external_publication_url") or details.get("public_url") or ""),
                scheduled_at=asset.scheduled_at,
                published_at=asset.published_at,
                metadata=details,
            )
        if asset.channel == "mapsi_site":
            details = self.mapsi_publisher.get_publication_status(campaign, asset)
            return self._publication_operation(
                asset,
                requested_action="publication_status",
                status=str(details.get("publication_status", "unknown")).lower(),
                correlation_id=correlation_id,
                publisher=str(details.get("publisher_type") or ""),
                external_id=str(details.get("external_publication_id") or details.get("external_id") or ""),
                preview_url=str(details.get("preview_url") or ""),
                public_url=str(details.get("external_publication_url") or details.get("public_url") or ""),
                scheduled_at=asset.scheduled_at,
                published_at=asset.published_at,
                metadata=details,
            )
        if asset.channel == "linkedin":
            publication = self.linkedin_publications.get_by_asset_hash(asset.id, asset.content_hash)
            details = {"status": publication.status if publication else "not_published", "linkedin_post_urn": publication.linkedin_post_urn if publication else "", "mode": publication.mode if publication else ""}
            return self._publication_operation(
                asset,
                requested_action="publication_status",
                status=str(details.get("status", "unknown")).lower(),
                correlation_id=correlation_id,
                publisher="linkedin_api" if details.get("mode") != "manual" else "linkedin_manual",
                external_id=str(details.get("linkedin_post_urn") or ""),
                public_url=str(details.get("linkedin_post_urn") or ""),
                scheduled_at=asset.scheduled_at,
                published_at=asset.published_at,
                metadata=details,
            )
        if asset.channel == "mautic":
            review = self.review_repository.get_review_by_campaign(campaign.id)
            publication = self.mautic_publications.get(campaign.id, review.content_version, review.segment_version) if review is not None else None
            details = {
                "status": publication.status if publication is not None else "not_scheduled",
                "mautic_campaign_id": publication.mautic_campaign_id if publication is not None else "",
                "scheduled_at": publication.scheduled_at.isoformat() if publication is not None and publication.scheduled_at else None,
            }
            return self._publication_operation(
                asset,
                requested_action="publication_status",
                status=str(details.get("status", "unknown")).lower(),
                correlation_id=correlation_id,
                publisher="mautic_api",
                external_id=str(details.get("mautic_campaign_id") or ""),
                scheduled_at=publication.scheduled_at if publication is not None else asset.scheduled_at,
                metadata=details,
            )
        return self._publication_operation(asset, requested_action="publication_status", status="unknown", correlation_id=correlation_id)

    def get_asset_evidence(self, asset_id: str) -> list[StudioAdminEvidence]:
        campaign, asset = self._find_asset(asset_id)
        allowed_ids = set(asset.source_evidence_ids or asset.evidence_ids)
        evidences = [item for item in campaign.source_evidences if not allowed_ids or item.id in allowed_ids]
        return [self._evidence_summary(item) for item in evidences]

    def get_asset_preview(self, asset_id: str) -> StudioAdminPreview:
        campaign, asset = self._find_asset(asset_id)
        publication = self._publication_for_asset(campaign, asset)
        preview_url = str(asset.results.get("preview_url", ""))
        if publication is not None and getattr(publication, "preview_url", ""):
            preview_url = getattr(publication, "preview_url", "")
        return StudioAdminPreview(
            asset_id=asset.id,
            available=bool(preview_url),
            preview_url=preview_url,
            preview_type="remote_url" if preview_url else "none",
            generated_at=getattr(publication, "updated_at", None),
            metadata={"channel": asset.channel},
        )

    def get_asset_publication(self, asset_id: str) -> StudioAdminPublication:
        campaign, asset = self._find_asset(asset_id)
        publication = self._publication_for_asset(campaign, asset)
        if publication is None:
            return StudioAdminPublication(
                asset_id=asset.id,
                available=bool(asset.external_publication_id or asset.external_publication_url),
                publisher_type="",
                publication_mode_requested="",
                publication_mode_executed="",
                publication_status="NOT_PUBLISHED",
                external_publication_id=asset.external_publication_id,
                external_publication_url=asset.external_publication_url,
                idempotency_key="",
                published_at=asset.published_at,
                metadata={"channel": asset.channel},
            )
        return StudioAdminPublication(
            asset_id=asset.id,
            available=True,
            publisher_type=self._publication_field(publication, "publisher_type"),
            publication_mode_requested=self._publication_field(publication, "publication_mode_requested"),
            publication_mode_executed=self._publication_field(publication, "publication_mode_executed"),
            publication_status=self._publication_field(publication, "publication_status", getattr(publication, "status", "UNKNOWN")).upper(),
            external_publication_id=self._publication_field(publication, "external_id", asset.external_publication_id)
            or self._publication_field(publication, "linkedin_post_urn", "")
            or self._publication_field(publication, "mautic_campaign_id", ""),
            external_publication_url=self._publication_field(publication, "public_url", asset.external_publication_url)
            or self._publication_field(publication, "linkedin_post_urn", ""),
            idempotency_key=self._publication_field(publication, "idempotency_key"),
            published_at=getattr(publication, "published_at", asset.published_at),
            metadata=self._publication_metadata(publication),
        )

    def list_channels(self) -> list[StudioAdminChannel]:
        return [self._channel_summary(key) for key in self._channel_catalog()]

    def get_channel(self, channel: str) -> StudioAdminChannel:
        return self._channel_summary(channel)

    def health_check_channel(
        self,
        channel: str,
        *,
        actor: str,
        correlation_id: str,
        idempotency_key: str | None,
    ) -> StudioAdminChannel:
        self._channel_catalog_entry(channel)
        diagnostics = self._channel_diagnostics(channel)
        record = self.channel_state_repository.update_health_check(channel=channel, last_error=diagnostics["last_error"])
        self.channel_state_repository.append_audit(
            scope=f"channel:{channel}",
            action="health_check",
            actor_id=actor,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key or "",
            payload={"channel": channel, **diagnostics},
        )
        self.audit_repository.append(
            None,
            "configuration.channel_health_checked",
            diagnostics,
            actor_id=actor,
            actor_source="mapsi-studio",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key or "",
            new_state={"channel": channel},
            channel=channel,
            result="SUCCESS" if not diagnostics["last_error"] else "ERROR",
        )
        return self._channel_summary(channel, record=record, diagnostics=diagnostics)

    def enable_channel(
        self,
        channel: str,
        *,
        actor: str,
        correlation_id: str,
        idempotency_key: str | None,
        confirmation: str,
        expires_in_minutes: int | None = None,
    ) -> StudioAdminChannel:
        catalog = self._channel_catalog_entry(channel)
        if catalog["real_publisher_available"]:
            self._require_confirmation(confirmation, action=f"enable {channel}")
        current = self.channel_state_repository.get_channel(channel)
        expires_at = datetime.now(UTC) + timedelta(minutes=expires_in_minutes) if expires_in_minutes else None
        record = self.channel_state_repository.save_channel(
            channel=channel,
            feature_enabled=True,
            feature_expires_at=expires_at,
            emergency_kill_switch=current.emergency_kill_switch if current is not None else False,
            updated_by=actor,
            last_health_check=current.last_health_check if current is not None else None,
            last_error=current.last_error if current is not None else "",
        )
        diagnostics = self._channel_diagnostics(channel)
        self.channel_state_repository.append_audit(
            scope=f"channel:{channel}",
            action="enable",
            actor_id=actor,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key or "",
            payload={"channel": channel, "expires_in_minutes": expires_in_minutes, "feature_enabled": True},
        )
        self.audit_repository.append(
            None,
            "configuration.channel_enabled",
            {"expires_in_minutes": expires_in_minutes},
            actor_id=actor,
            actor_source="mapsi-studio",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key or "",
            previous_state={"feature_enabled": current.feature_enabled if current is not None else self._static_channel_feature_enabled(channel)},
            new_state={"feature_enabled": True, "activation_expires_at": expires_at.isoformat() if expires_at else ""},
            channel=channel,
            result="SUCCESS",
        )
        return self._channel_summary(channel, record=record, diagnostics=diagnostics)

    def disable_channel(
        self,
        channel: str,
        *,
        actor: str,
        correlation_id: str,
        idempotency_key: str | None,
    ) -> StudioAdminChannel:
        self._channel_catalog_entry(channel)
        current = self.channel_state_repository.get_channel(channel)
        record = self.channel_state_repository.save_channel(
            channel=channel,
            feature_enabled=False,
            emergency_kill_switch=current.emergency_kill_switch if current is not None else False,
            updated_by=actor,
            last_health_check=current.last_health_check if current is not None else None,
            last_error=current.last_error if current is not None else "",
        )
        diagnostics = self._channel_diagnostics(channel)
        self.channel_state_repository.append_audit(
            scope=f"channel:{channel}",
            action="disable",
            actor_id=actor,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key or "",
            payload={"channel": channel, "feature_enabled": False},
        )
        self.audit_repository.append(
            None,
            "configuration.channel_disabled",
            {},
            actor_id=actor,
            actor_source="mapsi-studio",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key or "",
            previous_state={"feature_enabled": current.feature_enabled if current is not None else self._static_channel_feature_enabled(channel)},
            new_state={"feature_enabled": False},
            channel=channel,
            result="SUCCESS",
        )
        return self._channel_summary(channel, record=record, diagnostics=diagnostics)

    def activate_channel_kill_switch(
        self,
        channel: str,
        *,
        actor: str,
        correlation_id: str,
        idempotency_key: str | None,
    ) -> StudioAdminChannel:
        self._channel_catalog_entry(channel)
        current = self.channel_state_repository.get_channel(channel)
        record = self.channel_state_repository.save_channel(
            channel=channel,
            feature_enabled=current.feature_enabled if current is not None else self._static_channel_feature_enabled(channel),
            feature_expires_at=current.feature_expires_at if current is not None else None,
            emergency_kill_switch=True,
            updated_by=actor,
            last_health_check=current.last_health_check if current is not None else None,
            last_error=current.last_error if current is not None else "",
        )
        diagnostics = self._channel_diagnostics(channel)
        self.channel_state_repository.append_audit(
            scope=f"channel:{channel}",
            action="activate_kill_switch",
            actor_id=actor,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key or "",
            payload={"channel": channel, "emergency_kill_switch": True},
        )
        self.audit_repository.append(
            None,
            "configuration.channel_kill_switch_activated",
            {},
            actor_id=actor,
            actor_source="mapsi-studio",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key or "",
            previous_state={"emergency_kill_switch": current.emergency_kill_switch if current is not None else False},
            new_state={"emergency_kill_switch": True},
            channel=channel,
            result="SUCCESS",
        )
        return self._channel_summary(channel, record=record, diagnostics=diagnostics)

    def deactivate_channel_kill_switch(
        self,
        channel: str,
        *,
        actor: str,
        correlation_id: str,
        idempotency_key: str | None,
        confirmation: str,
    ) -> StudioAdminChannel:
        self._channel_catalog_entry(channel)
        self._require_confirmation(confirmation, action=f"deactivate {channel} kill switch")
        current = self.channel_state_repository.get_channel(channel)
        record = self.channel_state_repository.save_channel(
            channel=channel,
            feature_enabled=current.feature_enabled if current is not None else self._static_channel_feature_enabled(channel),
            feature_expires_at=current.feature_expires_at if current is not None else None,
            emergency_kill_switch=False,
            updated_by=actor,
            last_health_check=current.last_health_check if current is not None else None,
            last_error=current.last_error if current is not None else "",
        )
        diagnostics = self._channel_diagnostics(channel)
        self.channel_state_repository.append_audit(
            scope=f"channel:{channel}",
            action="deactivate_kill_switch",
            actor_id=actor,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key or "",
            payload={"channel": channel, "emergency_kill_switch": False},
        )
        self.audit_repository.append(
            None,
            "configuration.channel_kill_switch_deactivated",
            {},
            actor_id=actor,
            actor_source="mapsi-studio",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key or "",
            previous_state={"emergency_kill_switch": current.emergency_kill_switch if current is not None else False},
            new_state={"emergency_kill_switch": False},
            channel=channel,
            result="SUCCESS",
        )
        return self._channel_summary(channel, record=record, diagnostics=diagnostics)

    def get_global_kill_switch(self) -> StudioAdminGlobalKillSwitch:
        record = self.channel_state_repository.get_global()
        active = self.channel_state_repository.is_global_kill_switch_active(static_default=self.settings.workflow_kill_switch)
        return StudioAdminGlobalKillSwitch(
            active=active,
            updated_by=record.updated_by if record is not None else "",
            updated_at=record.updated_at if record is not None else None,
        )

    def activate_global_kill_switch(
        self,
        *,
        actor: str,
        correlation_id: str,
        idempotency_key: str | None,
    ) -> StudioAdminGlobalKillSwitch:
        record = self.channel_state_repository.save_global(global_kill_switch=True, updated_by=actor)
        self.channel_state_repository.append_audit(
            scope="global",
            action="activate_global_kill_switch",
            actor_id=actor,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key or "",
            payload={"global_kill_switch": True},
        )
        self.audit_repository.append(
            None,
            "configuration.global_kill_switch_activated",
            {},
            actor_id=actor,
            actor_source="mapsi-studio",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key or "",
            previous_state={"global_kill_switch": False},
            new_state={"global_kill_switch": True},
            result="SUCCESS",
        )
        return StudioAdminGlobalKillSwitch(active=record.global_kill_switch, updated_by=record.updated_by, updated_at=record.updated_at)

    def deactivate_global_kill_switch(
        self,
        *,
        actor: str,
        correlation_id: str,
        idempotency_key: str | None,
        confirmation: str,
    ) -> StudioAdminGlobalKillSwitch:
        self._require_confirmation(confirmation, action="deactivate global kill switch")
        record = self.channel_state_repository.save_global(global_kill_switch=False, updated_by=actor)
        self.channel_state_repository.append_audit(
            scope="global",
            action="deactivate_global_kill_switch",
            actor_id=actor,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key or "",
            payload={"global_kill_switch": False},
        )
        self.audit_repository.append(
            None,
            "configuration.global_kill_switch_deactivated",
            {},
            actor_id=actor,
            actor_source="mapsi-studio",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key or "",
            previous_state={"global_kill_switch": True},
            new_state={"global_kill_switch": False},
            result="SUCCESS",
        )
        return StudioAdminGlobalKillSwitch(active=record.global_kill_switch, updated_by=record.updated_by, updated_at=record.updated_at)

    def list_audit_events(
        self,
        filters: dict[str, object],
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[StudioAdminAuditEvent], int]:
        campaign_id = str(filters.get("campaign_id") or "")
        event_type = str(filters.get("event_type") or filters.get("event") or "")
        asset_id = str(filters.get("asset_id") or "")
        actor_id = str(filters.get("actor_id") or "")
        channel = str(filters.get("channel") or "")
        result = str(filters.get("result") or "")
        period_from = filters.get("period_from")
        period_to = filters.get("period_to")
        all_models = self.audit_repository.list_events(
            campaign_id=campaign_id or None,
            event_type=event_type or None,
            asset_id=asset_id or None,
            actor_id=actor_id or None,
            channel=channel or None,
            result=result or None,
            period_from=period_from,
            period_to=period_to,
            limit=1000,
        )
        integrity_ok = self.audit_repository.verify_integrity()
        all_events = [self._serialize_audit_event(item, integrity_ok=integrity_ok) for item in all_models]
        total = len(all_events)
        events = [StudioAdminAuditEvent(**item) for item in all_events[(page - 1) * page_size : page * page_size]]
        return events, total

    def export_audit_events_csv(self, filters: dict[str, object]) -> str:
        events, _ = self.list_audit_events(filters, page=1, page_size=1000)
        buffer = StringIO()
        writer = csv.DictWriter(
            buffer,
            fieldnames=[
                "event_id",
                "event_type",
                "campaign_id",
                "asset_id",
                "actor_id",
                "actor_source",
                "actor_roles",
                "timestamp",
                "correlation_id",
                "idempotency_key",
                "channel",
                "result",
                "source_ip",
                "previous_state",
                "new_state",
                "metadata",
                "integrity_hash",
                "previous_integrity_hash",
                "integrity_ok",
            ],
        )
        writer.writeheader()
        for event in events:
            writer.writerow(
                {
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "campaign_id": event.campaign_id,
                    "asset_id": event.asset_id,
                    "actor_id": event.actor_id,
                    "actor_source": event.actor_source,
                    "actor_roles": ",".join(event.actor_roles),
                    "timestamp": event.timestamp.isoformat(),
                    "correlation_id": event.correlation_id,
                    "idempotency_key": event.idempotency_key,
                    "channel": event.channel,
                    "result": event.result,
                    "source_ip": event.source_ip,
                    "previous_state": json.dumps(event.previous_state, sort_keys=True, separators=(",", ":")),
                    "new_state": json.dumps(event.new_state, sort_keys=True, separators=(",", ":")),
                    "metadata": json.dumps(event.metadata, sort_keys=True, separators=(",", ":")),
                    "integrity_hash": event.integrity_hash,
                    "previous_integrity_hash": event.previous_integrity_hash,
                    "integrity_ok": str(event.integrity_ok).lower(),
                }
            )
        return buffer.getvalue()

    def health(self) -> StudioAdminHealth:
        metadata = read_contract_metadata()
        return StudioAdminHealth(
            status="ok",
            app_version="0.1.0",
            contract_version=metadata.get("contract_version", "missing"),
            timestamp=datetime.now(UTC),
            operational_mode=self.operation_mode.current_mode(),
            banner_message=self.operation_mode.banner_message(),
        )

    def _load_weekly_pack(self, pack_id: str) -> WeeklyCommunicationPack:
        pack = self.weekly_pack_repository.get(pack_id)
        if pack is None:
            raise WeeklyCommunicationPackNotFoundError(f"Weekly communication pack {pack_id} not found.")
        return pack

    def _load_weekly_pack_campaign(self, pack: WeeklyCommunicationPack, *, campaign_type: str) -> CampaignRun:
        for campaign_id in pack.campaign_ids:
            campaign = self.campaign_service.get_campaign(campaign_id)
            if campaign.campaign_type == campaign_type:
                return campaign
        raise CampaignNotFoundError(f"Campaign type {campaign_type} not found for weekly pack {pack.id}.")

    def _load_editorial_source_pack(self, source_pack_id: str) -> EditorialSourcePack:
        pack = self.editorial_source_pack_repository.get(source_pack_id)
        if pack is None:
            raise EditorialSourcePackNotFoundError(f"Editorial source pack {source_pack_id} not found.")
        return pack

    def _find_editorial_source_item(self, pack: EditorialSourcePack, item_id: str) -> EditorialSourceItem:
        for item in pack.items:
            if item.id == item_id:
                return item
        raise EditorialSourceItemNotFoundError(f"Editorial source item {item_id} not found.")

    def _build_editorial_source_item(
        self,
        source_pack_id: str,
        payload: dict[str, object],
        *,
        existing: EditorialSourceItem | None = None,
    ) -> EditorialSourceItem:
        source_date_value = payload.get("source_date") or (existing.source_date if existing else None)
        if isinstance(source_date_value, str) and source_date_value:
            source_date_value = datetime.fromisoformat(source_date_value.replace("Z", "+00:00"))
        manual_input = dict(payload.get("manual_input") or {})
        factual_summary = str(payload.get("factual_summary") or self._build_manual_factual_summary(manual_input))
        usable_facts = [str(item) for item in (payload.get("usable_facts") or self._build_manual_facts(manual_input, "usable"))]
        anonymized_facts = [str(item) for item in (payload.get("anonymized_facts") or self._build_manual_facts(manual_input, "anonymized"))]
        prohibited_facts = [str(item) for item in (payload.get("prohibited_facts") or self._build_manual_facts(manual_input, "prohibited"))]
        content_hash = sha256_hexdigest(
            json.dumps(
                {
                    "source_type": str(payload.get("source_type") or (existing.source_type if existing else "")),
                    "source_reference": str(payload.get("source_reference") or (existing.source_reference if existing else "")),
                    "source_title": str(payload.get("source_title") or (existing.source_title if existing else "")),
                    "factual_summary": factual_summary,
                    "usable_facts": usable_facts,
                    "anonymized_facts": anonymized_facts,
                    "prohibited_facts": prohibited_facts,
                    "client_name": str(payload.get("client_name") or (existing.client_name if existing else "")),
                    "client_name_usage_authorized": bool(payload.get("client_name_usage_authorized", existing.client_name_usage_authorized if existing else False)),
                    "confidentiality_level": str(payload.get("confidentiality_level") or (existing.confidentiality_level if existing else "INTERNAL")),
                    "source_url": str(payload.get("source_url") or (existing.source_url if existing else "")),
                    "external_source_id": str(payload.get("external_source_id") or (existing.external_source_id if existing else "")),
                    "manual_input": manual_input,
                },
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
        )
        return EditorialSourceItem(
            id=existing.id if existing else str(uuid4()),
            source_pack_id=source_pack_id,
            source_type=str(payload.get("source_type") or (existing.source_type if existing else "MANUAL_NOTE")),
            source_reference=str(payload.get("source_reference") or (existing.source_reference if existing else "")),
            source_title=str(payload.get("source_title") or (existing.source_title if existing else "")),
            source_date=source_date_value,
            source_author=str(payload.get("source_author") or (existing.source_author if existing else "")),
            factual_summary=factual_summary,
            usable_facts=usable_facts,
            anonymized_facts=anonymized_facts,
            prohibited_facts=prohibited_facts,
            client_name=str(payload.get("client_name") or (existing.client_name if existing else "")),
            client_name_usage_authorized=bool(payload.get("client_name_usage_authorized", existing.client_name_usage_authorized if existing else False)),
            confidentiality_level=str(payload.get("confidentiality_level") or (existing.confidentiality_level if existing else "INTERNAL")),
            evidence_quality=str(payload.get("evidence_quality") or (existing.evidence_quality if existing else "medium")),
            source_url=str(payload.get("source_url") or (existing.source_url if existing else "")),
            external_source_id=str(payload.get("external_source_id") or (existing.external_source_id if existing else "")),
            content_hash=content_hash,
            manual_input=manual_input or (dict(existing.manual_input) if existing else {}),
            created_at=existing.created_at if existing else utcnow(),
            updated_at=utcnow(),
            attachment_references=list(existing.attachment_references) if existing else [],
        )

    def _build_manual_factual_summary(self, manual_input: dict[str, object]) -> str:
        parts = [
            str(manual_input.get("project_summary") or ""),
            str(manual_input.get("client_problem") or ""),
            str(manual_input.get("oling_method") or ""),
            str(manual_input.get("desired_cta") or ""),
        ]
        return " ".join(part for part in parts if part).strip()

    def _build_manual_facts(self, manual_input: dict[str, object], mode: str) -> list[str]:
        if mode == "usable":
            facts = []
            facts.extend(str(item) for item in manual_input.get("deliverables_completed", []) if item)
            facts.extend(str(item) for item in manual_input.get("observed_results", []) if item)
            return facts
        if mode == "anonymized":
            return [str(item) for item in manual_input.get("lessons_learned", []) if item]
        return []

    def _editorial_preview_for_item(
        self,
        item: EditorialSourceItem,
    ) -> tuple[list[StudioAdminEditorialPreviewFact], list[StudioAdminEditorialPreviewFact], bool]:
        allowed: list[StudioAdminEditorialPreviewFact] = []
        blocked: list[StudioAdminEditorialPreviewFact] = []
        anonymized = False
        project_like_source = item.source_type in {"PROJECT_DELIVERABLE", "CLIENT_FEEDBACK", "CONSULTANT_NOTE", "EMAIL_THREAD", "TEAMS_MESSAGE", "TEAMS_THREAD"}
        blocked_values = set(item.prohibited_facts)
        for fact in item.prohibited_facts:
            blocked.append(
                StudioAdminEditorialPreviewFact(
                    source_item_id=item.id,
                    source_type=item.source_type,
                    fact=fact,
                    mode="blocked",
                    reason="explicitly_prohibited",
                )
            )
        for fact in item.usable_facts:
            if fact in blocked_values:
                continue
            if item.confidentiality_level in {"CLIENT_CONFIDENTIAL", "STRICTLY_CONFIDENTIAL"}:
                blocked.append(
                    StudioAdminEditorialPreviewFact(
                        source_item_id=item.id,
                        source_type=item.source_type,
                        fact=fact,
                        mode="blocked",
                        reason="confidential_raw_fact",
                    )
                )
                continue
            if project_like_source:
                anonymized = True
                allowed.append(
                    StudioAdminEditorialPreviewFact(
                        source_item_id=item.id,
                        source_type=item.source_type,
                        fact=self._sanitize_client_names(fact, item, force_anonymize=True),
                        mode="anonymized",
                        reason="project_content_default_anonymized",
                    )
                )
                continue
            allowed.append(
                StudioAdminEditorialPreviewFact(
                    source_item_id=item.id,
                    source_type=item.source_type,
                    fact=self._sanitize_client_names(fact, item),
                    mode="direct",
                    reason="usable_fact",
                )
            )
        for fact in item.anonymized_facts:
            if fact in blocked_values:
                continue
            anonymized = True
            allowed.append(
                StudioAdminEditorialPreviewFact(
                    source_item_id=item.id,
                    source_type=item.source_type,
                    fact=self._sanitize_client_names(fact, item, force_anonymize=True),
                    mode="anonymized",
                    reason="requires_anonymization",
                )
            )
        if item.factual_summary and not item.usable_facts and not item.anonymized_facts:
            summary_mode = "anonymized" if item.confidentiality_level in {"CLIENT_CONFIDENTIAL", "STRICTLY_CONFIDENTIAL"} or project_like_source else "direct"
            allowed.append(
                StudioAdminEditorialPreviewFact(
                    source_item_id=item.id,
                    source_type=item.source_type,
                    fact=self._sanitize_client_names(item.factual_summary, item, force_anonymize=summary_mode == "anonymized"),
                    mode=summary_mode,
                    reason="summary_fallback",
                )
            )
            anonymized = anonymized or summary_mode == "anonymized"
        return allowed, blocked, anonymized

    def _sanitize_client_names(self, value: str, item: EditorialSourceItem, *, force_anonymize: bool = False) -> str:
        result = value
        if item.client_name and (force_anonymize or not item.client_name_usage_authorized):
            result = result.replace(item.client_name, "client anonymise")
        return result

    def _editorial_source_pack_summary(self, pack: EditorialSourcePack) -> StudioAdminEditorialSourcePack:
        return StudioAdminEditorialSourcePack(
            id=pack.id,
            weekly_pack_id=pack.weekly_pack_id,
            campaign_type=pack.campaign_type,
            title=pack.title,
            summary=pack.summary,
            status=pack.status,
            confidentiality_level=pack.confidentiality_level,
            created_by=pack.created_by,
            created_at=pack.created_at,
            validated_by=pack.validated_by,
            validated_at=pack.validated_at,
            items=[
                StudioAdminEditorialSourceItem(
                    id=item.id,
                    source_pack_id=item.source_pack_id,
                    source_type=item.source_type,
                    source_reference=item.source_reference,
                    source_title=item.source_title,
                    source_date=item.source_date,
                    source_author=item.source_author,
                    factual_summary=item.factual_summary,
                    usable_facts=list(item.usable_facts),
                    anonymized_facts=list(item.anonymized_facts),
                    prohibited_facts=list(item.prohibited_facts),
                    client_name=item.client_name,
                    client_name_usage_authorized=item.client_name_usage_authorized,
                    confidentiality_level=item.confidentiality_level,
                    evidence_quality=item.evidence_quality,
                    source_url=item.source_url,
                    external_source_id=item.external_source_id,
                    content_hash=item.content_hash,
                    manual_input=dict(item.manual_input),
                    attachments=[
                        StudioAdminEditorialSourceAttachmentReference(
                            id=attachment.id,
                            source_item_id=attachment.source_item_id,
                            file_name=attachment.file_name,
                            media_type=attachment.media_type,
                            storage_reference=attachment.storage_reference,
                            source_url=attachment.source_url,
                            content_hash=attachment.content_hash,
                            created_at=attachment.created_at,
                        )
                        for attachment in item.attachment_references
                    ],
                )
                for item in pack.items
            ],
        )

    def _campaign_audience_description(self, campaign_type: str, *, pilot_mode: bool) -> str:
        if campaign_type == "MAPSI_MARKET":
            return "Audience marche interne pilote uniquement." if pilot_mode else "Audience marche."
        if campaign_type == "OLING_PRACTICE":
            return "Audience pratique Oling pilote uniquement." if pilot_mode else "Audience pratique Oling."
        return "Utilisateurs MAPSI en allowlist pilote." if pilot_mode else "Utilisateurs MAPSI."

    def _generate_weekly_pack_campaign(self, pack: WeeklyCommunicationPack, campaign: CampaignRun) -> CampaignRun:
        if campaign.status in {CampaignStatus.READY_FOR_REVIEW, CampaignStatus.PARTIALLY_APPROVED, CampaignStatus.APPROVED, CampaignStatus.PARTIALLY_PUBLISHED, CampaignStatus.PUBLISHED, CampaignStatus.SKIPPED}:
            return campaign
        campaign.status = CampaignStatus.GENERATING
        campaign.updated_at = utcnow()
        self.campaign_service.repository.save(campaign)
        if not campaign.source_evidences:
            campaign.source_evidences.extend(self._build_weekly_pack_evidences(pack, campaign))
            campaign.status = CampaignStatus.SOURCES_READY
            self.campaign_service.repository.save(campaign)
        brief, assets = self._build_weekly_pack_generation(pack, campaign)
        campaign.mark_generated(brief, assets)
        campaign.status = CampaignStatus.READY_FOR_REVIEW
        campaign.updated_at = utcnow()
        return self.campaign_service.repository.save(campaign)

    def _build_weekly_pack_generation(self, pack: WeeklyCommunicationPack, campaign: CampaignRun) -> tuple[EditorialBrief, list[ContentAsset]]:
        if campaign.campaign_type == "MAPSI_MARKET":
            generated = self.mapsi_market_builder.build(
                weekly_pack_id=pack.id,
                pilot_mode=pack.pilot_mode,
                record_theme_history=True,
                fallback_evidence_ids=[evidence.id for evidence in campaign.source_evidences],
            )
            brief = EditorialBrief(
                campaign_run_id=campaign.id,
                title=generated.brief.selected_topic,
                summary=generated.brief.objective,
            )
            assets: list[ContentAsset] = []
            audience_segment_id = campaign.audience_segments[0].id if campaign.audience_segments else ""
            for asset in generated.assets:
                asset.campaign_run_id = campaign.id
                asset.audience_segment_id = audience_segment_id
                asset.results = {
                    **asset.results,
                    "weekly_pack_id": pack.id,
                    "campaign_type": campaign.campaign_type,
                    "pilot_mode": pack.pilot_mode,
                    "editorial_brief": generated.brief.model_dump(mode="json"),
                    "evaluations": generated.evaluations,
                    "engine_mode": generated.engine_mode,
                }
                asset.ensure_content_hash()
                assets.append(asset)
            return brief, assets
        if campaign.campaign_type == "OLING_PRACTICE":
            generated = self.oling_practice_builder.build(
                weekly_pack_id=pack.id,
                pilot_mode=pack.pilot_mode,
                record_theme_history=True,
                fallback_evidence_ids=[evidence.id for evidence in campaign.source_evidences],
            )
            brief = EditorialBrief(
                campaign_run_id=campaign.id,
                title=generated.brief.practice,
                summary=generated.brief.business_problem,
            )
            assets = []
            audience_segment_id = campaign.audience_segments[0].id if campaign.audience_segments else ""
            for asset in generated.assets:
                asset.campaign_run_id = campaign.id
                asset.audience_segment_id = audience_segment_id
                asset.results = {
                    **asset.results,
                    "weekly_pack_id": pack.id,
                    "campaign_type": campaign.campaign_type,
                    "pilot_mode": pack.pilot_mode,
                    "editorial_brief": generated.brief.model_dump(mode="json"),
                    "evaluations": generated.evaluations,
                    "engine_mode": generated.engine_mode,
                }
                asset.ensure_content_hash()
                assets.append(asset)
            return brief, assets
        if campaign.campaign_type == "MAPSI_USERS":
            generated = self.mapsi_users_builder.build(
                pilot_mode=pack.pilot_mode,
                record_theme_history=True,
                fallback_evidence_ids=[evidence.id for evidence in campaign.source_evidences],
            )
            brief = EditorialBrief(
                campaign_run_id=campaign.id,
                title=generated.content.title,
                summary=generated.content.main_tip,
            )
            asset = generated.asset
            asset.campaign_run_id = campaign.id
            asset.results = {
                **asset.results,
                "weekly_pack_id": pack.id,
                "campaign_type": campaign.campaign_type,
                "pilot_mode": pack.pilot_mode,
                "editorial_brief": generated.content.model_dump(mode="json"),
                "evaluations": generated.evaluations,
                "engine_mode": generated.engine_mode,
            }
            asset.ensure_content_hash()
            return brief, [asset]
        brief = EditorialBrief(
            campaign_run_id=campaign.id,
            title=campaign.name,
            summary=f"Weekly communication pack {pack.week_reference} for {campaign.campaign_type}.",
        )
        return brief, self._build_weekly_pack_assets(pack, campaign)

    def _build_weekly_pack_evidences(self, pack: WeeklyCommunicationPack, campaign: CampaignRun) -> list[SourceEvidence]:
        source_map = {
            "MAPSI_MARKET": ["product_changes", "mapsi_web"],
            "OLING_PRACTICE": ["product_changes", "oling_web"],
            "MAPSI_USERS": ["product_changes", "mapsi_usage"],
        }
        sources = source_map.get(campaign.campaign_type, ["product_changes"])
        evidences: list[SourceEvidence] = []
        for index, source in enumerate(sources, start=1):
            evidences.append(
                SourceEvidence(
                    campaign_run_id=campaign.id,
                    source_system=source,
                    evidence_type="weekly_pack_source",
                    reference=f"{pack.week_reference}:{campaign.campaign_type}:{source}:{index}",
                    payload={
                        "week_reference": pack.week_reference,
                        "campaign_type": campaign.campaign_type,
                        "pilot_mode": pack.pilot_mode,
                    },
                )
            )
        return evidences

    def _build_weekly_pack_assets(self, pack: WeeklyCommunicationPack, campaign: CampaignRun) -> list[ContentAsset]:
        asset_types_by_campaign = {
            "MAPSI_MARKET": ["oling_news_article", "mapsi_news_article", "linkedin_company_post"],
            "OLING_PRACTICE": ["oling_news_article", "linkedin_company_post"],
            "MAPSI_USERS": ["mapsi_user_email"],
        }
        assets: list[ContentAsset] = []
        evidence_ids = [evidence.id for evidence in campaign.source_evidences]
        audience_segment_id = campaign.audience_segments[0].id if campaign.audience_segments else ""
        for asset_type in asset_types_by_campaign.get(campaign.campaign_type, []):
            channel = {
                "oling_news_article": "oling",
                "mapsi_news_article": "mapsi_site",
                "linkedin_company_post": "linkedin",
                "mapsi_user_email": "mapsi_users",
            }[asset_type]
            title = self._weekly_pack_asset_title(pack, campaign, asset_type)
            body = self._weekly_pack_asset_body(pack, campaign, asset_type)
            subject = title if asset_type == "mapsi_user_email" else ""
            results = {
                "weekly_pack_id": pack.id,
                "campaign_type": campaign.campaign_type,
                "pilot_mode": pack.pilot_mode,
            }
            if pack.pilot_mode and asset_type == "linkedin_company_post":
                results["pilot_draft_only"] = True
            if pack.pilot_mode and asset_type == "mapsi_user_email":
                results["pilot_allowlist_only"] = True
            asset = ContentAsset(
                campaign_run_id=campaign.id,
                asset_type=asset_type,
                channel=channel,
                locale="fr-FR",
                title=title,
                subject=subject,
                content_html=body if asset_type != "linkedin_company_post" else None,
                content_text=body if asset_type == "linkedin_company_post" else "",
                excerpt=self._plain_text(body)[:160],
                source_evidence_ids=evidence_ids,
                audience_segment_id=audience_segment_id,
                status=AssetStatus.READY_FOR_REVIEW,
                results=results,
            )
            asset.content_hash = build_content_hash(
                asset.asset_type,
                asset.title,
                asset.body,
                list(asset.source_evidence_ids),
                asset.audience_segment_id,
                locale=asset.locale,
                subject=asset.subject,
                content_html=asset.content_html,
                content_text=asset.content_text,
                excerpt=asset.excerpt,
                call_to_action=asset.call_to_action,
                target_url=asset.target_url,
            )
            assets.append(asset)
        return assets

    def _weekly_pack_asset_title(self, pack: WeeklyCommunicationPack, campaign: CampaignRun, asset_type: str) -> str:
        if asset_type == "mapsi_user_email":
            return f"MAPSI Users Weekly {pack.week_reference}"
        if asset_type == "linkedin_company_post":
            return f"{campaign.campaign_type.replace('_', ' ').title()} {pack.week_reference}"
        if asset_type == "mapsi_news_article":
            return f"MAPSI Weekly Communication Pack {pack.week_reference}"
        return f"Oling Weekly Communication Pack {pack.week_reference}"

    def _weekly_pack_asset_body(self, pack: WeeklyCommunicationPack, campaign: CampaignRun, asset_type: str) -> str:
        if asset_type == "linkedin_company_post":
            suffix = " Publication reelle interdite en mode pilot." if pack.pilot_mode else ""
            return f"{campaign.campaign_type} {pack.week_reference} : synthese hebdomadaire fondee sur des sources dediees.{suffix}"
        audience_note = " Diffusion pilote restreinte." if pack.pilot_mode else ""
        return (
            f"<p>Communication hebdomadaire {pack.week_reference} pour {campaign.campaign_type}.</p>"
            f"<p>Contenu simule structure pour review, approbation et publication independantes.</p>"
            f"<p>{audience_note.strip()}</p>"
        )

    def _campaigns_for_pack(self, pack: WeeklyCommunicationPack) -> list[CampaignRun]:
        return [self.campaign_service.get_campaign(campaign_id) for campaign_id in pack.campaign_ids]

    def _compute_pack_status(self, pack: WeeklyCommunicationPack, *, closed: bool = False) -> str:
        campaigns = self._campaigns_for_pack(pack)
        statuses = {campaign.status.value for campaign in campaigns}
        if all(status == CampaignStatus.PUBLISHED.value for status in statuses):
            return "COMPLETED" if closed else "PUBLISHED"
        if CampaignStatus.FAILED.value in statuses and len(statuses) == 1:
            return "FAILED"
        if any(status in {CampaignStatus.PARTIALLY_PUBLISHED.value, CampaignStatus.PUBLISHED.value} for status in statuses):
            return "PARTIALLY_COMPLETED" if closed else "PARTIALLY_PUBLISHED"
        if any(status in {CampaignStatus.APPROVED.value, CampaignStatus.PARTIALLY_APPROVED.value} for status in statuses):
            return "PARTIALLY_REVIEWED"
        if any(status == CampaignStatus.READY_FOR_REVIEW.value for status in statuses):
            return "READY_FOR_REVIEW"
        if any(status in {CampaignStatus.SOURCES_READY.value, CampaignStatus.GENERATING.value} for status in statuses):
            return "IN_PROGRESS"
        if all(status == CampaignStatus.SKIPPED.value for status in statuses):
            return "SKIPPED"
        return "NOT_STARTED"

    def _all_campaigns_reviewed(self, pack: WeeklyCommunicationPack) -> bool:
        campaigns = self._campaigns_for_pack(pack)
        return bool(campaigns) and all(
            campaign.status in {CampaignStatus.PARTIALLY_APPROVED, CampaignStatus.APPROVED, CampaignStatus.PARTIALLY_PUBLISHED, CampaignStatus.PUBLISHED, CampaignStatus.FAILED, CampaignStatus.SKIPPED}
            for campaign in campaigns
        )

    def _build_weekly_pack_global_summary(self, pack: WeeklyCommunicationPack) -> dict[str, object]:
        campaigns = self._campaigns_for_pack(pack)
        return {
            "campaigns_total": len(campaigns),
            "campaigns_generated": len([campaign for campaign in campaigns if campaign.content_assets]),
            "campaigns_ready_for_review": len([campaign for campaign in campaigns if campaign.status is CampaignStatus.READY_FOR_REVIEW]),
            "campaigns_approved": len([campaign for campaign in campaigns if campaign.status in {CampaignStatus.PARTIALLY_APPROVED, CampaignStatus.APPROVED}]),
            "campaigns_published": len([campaign for campaign in campaigns if campaign.status in {CampaignStatus.PARTIALLY_PUBLISHED, CampaignStatus.PUBLISHED}]),
            "campaigns_failed": len([campaign for campaign in campaigns if campaign.status is CampaignStatus.FAILED]),
        }

    def _weekly_pack_summary(self, pack: WeeklyCommunicationPack) -> StudioAdminWeeklyPack:
        campaigns = self._campaigns_for_pack(pack)
        return StudioAdminWeeklyPack(
            id=pack.id,
            week_reference=pack.week_reference,
            year=pack.year,
            week_number=pack.week_number,
            status=self._compute_pack_status(pack, closed=pack.completed_at is not None),
            created_at=pack.created_at,
            generated_at=pack.generated_at,
            reviewed_at=pack.reviewed_at,
            completed_at=pack.completed_at,
            campaign_ids=list(pack.campaign_ids),
            campaigns=[
                StudioAdminWeeklyPackCampaign(
                    id=campaign.id,
                    campaign_type=campaign.campaign_type,
                    title=campaign.name,
                    status=campaign.status.value,
                    asset_count=len(campaign.content_assets),
                    published_assets=len([asset for asset in campaign.content_assets if asset.status is AssetStatus.PUBLISHED]),
                    errors=[asset.last_error for asset in campaign.content_assets if asset.last_error],
                )
                for campaign in campaigns
            ],
            global_summary=self._build_weekly_pack_global_summary(pack),
            operational_errors=list(pack.operational_errors),
            pilot_mode=pack.pilot_mode,
        )

    def _campaign_summary(self, campaign: CampaignRun) -> StudioAdminCampaignSummary:
        last_event_model = self.audit_repository.latest_event_for_campaign(campaign.id)
        assets = campaign.content_assets
        return StudioAdminCampaignSummary(
            id=campaign.id,
            title=campaign.name,
            objective=campaign.objective,
            status=campaign.status.value,
            created_at=campaign.created_at,
            scheduled_at=min([item.scheduled_at for item in assets if item.scheduled_at], default=None),
            asset_count=len(assets),
            assets_pending_validation=len([item for item in assets if item.status in {AssetStatus.READY_FOR_REVIEW, AssetStatus.QUALITY_CHECK}]),
            assets_approved=len([item for item in assets if item.status is AssetStatus.APPROVED]),
            assets_published=len([item for item in assets if item.status is AssetStatus.PUBLISHED]),
            assets_in_error=len([item for item in assets if item.status is AssetStatus.FAILED]),
            last_event=self._serialize_last_event(last_event_model) if last_event_model is not None else None,
        )

    def _asset_summary(self, campaign: CampaignRun, asset: ContentAsset) -> StudioAdminAssetSummary:
        review = self.review_repository.get_review_by_campaign(campaign.id)
        quality = review.quality_control if review is not None else {"status": "unknown"}
        approval_status = "approved" if asset.approved_at else ("pending_validation" if asset.status in {AssetStatus.READY_FOR_REVIEW, AssetStatus.QUALITY_CHECK} else "not_approved")
        return StudioAdminAssetSummary(
            id=asset.id,
            campaign_id=campaign.id,
            campaign_title=campaign.name,
            channel=asset.channel,
            asset_type=asset.asset_type,
            title=asset.title,
            status=asset.status.value,
            version=asset.content_version,
            content_hash=asset.content_hash,
            approved_content_hash=asset.approved_content_hash,
            quality=dict(quality or {}),
            approval=StudioAdminApproval(status=approval_status, approved_by=asset.approved_by, approved_at=asset.approved_at),
            preview_available=bool(asset.results.get("preview_url")),
            publication_available=bool(asset.external_publication_id or asset.external_publication_url or self._publication_for_asset(campaign, asset)),
            public_url=asset.external_publication_url,
            last_error_message=asset.last_error,
            published_at=asset.published_at,
            created_at=asset.created_at,
        )

    def _evidence_summary(self, evidence) -> StudioAdminEvidence:
        payload = evidence.payload or {}
        reference = payload.get("url") or evidence.reference
        return StudioAdminEvidence(
            source_type=evidence.source_system,
            reference=evidence.reference,
            description=payload.get("summary") or payload.get("title") or evidence.reference,
            confidence_level=str(payload.get("confidence_level") or payload.get("confidence") or "unknown"),
            link=reference if isinstance(reference, str) and reference.startswith("https://github.com/") else "",
        )

    def _channel_catalog(self) -> dict[str, dict[str, object]]:
        return {
            "mautic": {
                "key": "mautic",
                "label": "Mautic",
                "asset_types": ["customer_email", "prospect_newsletter"],
                "supports_preview": True,
                "supports_publication": True,
                "sandbox_available": False,
                "real_publisher_available": True,
            },
            "mapsi_users": {
                "key": "mapsi_users",
                "label": "MAPSI Users",
                "asset_types": ["mapsi_user_email", "customer_email"],
                "supports_preview": True,
                "supports_publication": True,
                "sandbox_available": True,
                "real_publisher_available": False,
            },
            "linkedin": {
                "key": "linkedin",
                "label": "LinkedIn",
                "asset_types": ["linkedin_company_post", "linkedin_personal_draft"],
                "supports_preview": False,
                "supports_publication": True,
                "sandbox_available": True,
                "real_publisher_available": True,
            },
            "oling": {
                "key": "oling",
                "label": "Oling",
                "asset_types": ["website_article", "website_cta", "demonstration_landing_page", "oling_news_article"],
                "supports_preview": True,
                "supports_publication": True,
                "sandbox_available": True,
                "real_publisher_available": True,
            },
            "mapsi_site": {
                "key": "mapsi_site",
                "label": "MAPSI Site",
                "asset_types": ["mapsi_news_article"],
                "supports_preview": True,
                "supports_publication": True,
                "sandbox_available": True,
                "real_publisher_available": True,
            },
            "prospect_newsletter": {
                "key": "prospect_newsletter",
                "label": "Prospect Newsletter",
                "asset_types": ["prospect_newsletter"],
                "supports_preview": True,
                "supports_publication": True,
                "sandbox_available": True,
                "real_publisher_available": False,
            },
        }

    def _channel_catalog_entry(self, channel: str) -> dict[str, object]:
        catalog = self._channel_catalog().get(channel)
        if catalog is None:
            raise CampaignNotFoundError(f"Channel {channel} not found.")
        return catalog

    def _channel_summary(
        self,
        channel: str,
        *,
        record=None,
        diagnostics: dict[str, object] | None = None,
    ) -> StudioAdminChannel:
        catalog = self._channel_catalog_entry(channel)
        record = record or self.channel_state_repository.get_channel(channel)
        diagnostics = diagnostics or self._channel_diagnostics(channel)
        effective_enabled = self.channel_state_repository.is_channel_feature_enabled(
            channel=channel,
            static_default=self._static_channel_feature_enabled(channel),
            safe_default_enabled=self.settings.channel_operational_safe_default_enabled,
        )
        return StudioAdminChannel(
            key=str(catalog["key"]),
            label=str(catalog["label"]),
            asset_types=list(catalog["asset_types"]),
            supports_preview=bool(catalog["supports_preview"]),
            supports_publication=bool(catalog["supports_publication"]),
            enabled=effective_enabled,
            configured=bool(diagnostics["configured"]),
            credentials_valid=bool(diagnostics["credentials_valid"]),
            feature_enabled=effective_enabled,
            emergency_kill_switch=self.channel_state_repository.is_channel_kill_switch_active(channel),
            sandbox_available=bool(catalog["sandbox_available"]),
            real_publisher_available=bool(catalog["real_publisher_available"]),
            last_health_check=record.last_health_check if record is not None else None,
            last_successful_publication=self._last_successful_publication_at(channel),
            last_error=str(record.last_error if record is not None and record.last_error else diagnostics["last_error"]),
            updated_by=record.updated_by if record is not None else "",
            updated_at=record.updated_at if record is not None else None,
            activation_expires_at=record.feature_expires_at if record is not None else None,
            operational_mode=self.operation_mode.current_mode(),
            banner_message=self.operation_mode.banner_message(),
        )

    def _channel_diagnostics(self, channel: str) -> dict[str, object]:
        if channel == "oling":
            details = self.oling_publisher.validate_configuration(channel)
            return {
                "configured": bool(details.get("configured")),
                "credentials_valid": bool(details.get("configured")),
                "last_error": "" if details.get("configured") else f"Missing configuration: {', '.join(details.get('missing', []))}",
            }
        if channel == "mapsi_site":
            details = self.mapsi_publisher.validate_configuration(channel)
            return {
                "configured": bool(details.get("configured")),
                "credentials_valid": bool(details.get("configured")),
                "last_error": "" if details.get("configured") else f"Missing configuration: {', '.join(details.get('missing', []))}",
            }
        if channel == "linkedin":
            config = self.linkedin_publisher.connector.config
            missing = []
            if not config.client_id:
                missing.append("LINKEDIN_CLIENT_ID")
            if not config.client_secret:
                missing.append("LINKEDIN_CLIENT_SECRET")
            if not config.organization_urn:
                missing.append("LINKEDIN_ORGANIZATION_URN")
            token = self.linkedin_publisher.oauth_service.repository.get()
            credentials_valid = token is not None or bool(config.access_token)
            return {
                "configured": not missing,
                "credentials_valid": credentials_valid and not missing,
                "last_error": "" if (not missing and credentials_valid) else f"Missing or invalid LinkedIn credentials: {', '.join(missing or ['access_token'])}",
            }
        if channel == "mautic":
            config = self.campaign_publisher.mautic_connector.config
            missing = []
            if not config.base_url:
                missing.append("MAUTIC_BASE_URL")
            if not config.access_token and not config.username:
                missing.append("MAUTIC_ACCESS_TOKEN|MAUTIC_USERNAME")
            if not config.access_token and config.username and not config.password:
                missing.append("MAUTIC_PASSWORD")
            configured = not missing
            return {
                "configured": configured,
                "credentials_valid": configured,
                "last_error": "" if configured else f"Missing configuration: {', '.join(missing)}",
            }
        if channel == "mapsi_users":
            allowlist = sorted(self.operation_mode.pilot_email_allowlist())
            return {
                "configured": True,
                "credentials_valid": bool(allowlist) if self.operation_mode.is_pilot() else True,
                "last_error": "" if (allowlist or not self.operation_mode.is_pilot()) else "Pilot allowlist is empty.",
            }
        if channel == "prospect_newsletter":
            return {
                "configured": True,
                "credentials_valid": True,
                "last_error": "",
            }
        raise CampaignNotFoundError(f"Channel {channel} not found.")

    def _static_channel_feature_enabled(self, channel: str) -> bool:
        if channel == "oling":
            return self.settings.publish_oling_enabled
        if channel == "mapsi_site":
            return self.settings.publish_mapsi_site_enabled
        if channel == "linkedin":
            return self.settings.publish_linkedin_enabled
        if channel == "mautic":
            return True
        if channel == "mapsi_users":
            return self.settings.send_mapsi_users_enabled
        if channel == "prospect_newsletter":
            return self.settings.send_prospect_newsletter_enabled
        raise CampaignNotFoundError(f"Channel {channel} not found.")

    def _last_successful_publication_at(self, channel: str) -> datetime | None:
        session = self.channel_state_repository.session
        if channel == "oling":
            return session.query(OlingNewsPublicationModel.published_at).filter(OlingNewsPublicationModel.published_at.is_not(None)).order_by(OlingNewsPublicationModel.published_at.desc()).limit(1).scalar()
        if channel == "mapsi_site":
            return session.query(MapsiNewsPublicationModel.published_at).filter(MapsiNewsPublicationModel.published_at.is_not(None)).order_by(MapsiNewsPublicationModel.published_at.desc()).limit(1).scalar()
        if channel == "linkedin":
            return session.query(LinkedInPublicationModel.published_at).filter(LinkedInPublicationModel.published_at.is_not(None)).order_by(LinkedInPublicationModel.published_at.desc()).limit(1).scalar()
        if channel == "mautic":
            return session.query(MauticCampaignPublicationModel.scheduled_at).filter(MauticCampaignPublicationModel.scheduled_at.is_not(None)).order_by(MauticCampaignPublicationModel.scheduled_at.desc()).limit(1).scalar()
        if channel in {"mapsi_users", "prospect_newsletter"}:
            return session.query(MauticCampaignPublicationModel.scheduled_at).filter(MauticCampaignPublicationModel.scheduled_at.is_not(None)).order_by(MauticCampaignPublicationModel.scheduled_at.desc()).limit(1).scalar()
        raise CampaignNotFoundError(f"Channel {channel} not found.")

    def _require_confirmation(self, confirmation: str, *, action: str) -> None:
        if confirmation == self.settings.studio_admin_sensitive_confirmation_phrase:
            return
        raise CampaignPublicationForbiddenError(
            f"Confirmation is required to {action}. Send confirmation={self.settings.studio_admin_sensitive_confirmation_phrase}."
        )

    def _publication_for_asset(self, campaign: CampaignRun, asset: ContentAsset):
        if asset.channel == "oling":
            return self.oling_publications.get_latest_for_asset(asset.id)
        if asset.channel == "mapsi_site":
            return self.mapsi_site_publications.get_latest_for_asset(asset.id)
        if asset.channel == "linkedin":
            return self.linkedin_publications.get_by_asset_hash(asset.id, asset.content_hash)
        if asset.channel == "mautic":
            review = self.review_repository.get_review_by_campaign(campaign.id)
            if review is None:
                return None
            return self.mautic_publications.get(campaign.id, review.content_version, review.segment_version)
        return None

    def _publication_version(self, asset: ContentAsset, publication) -> int:
        if hasattr(publication, "published_content_version") and getattr(publication, "published_content_version"):
            return int(getattr(publication, "published_content_version"))
        if hasattr(publication, "content_version") and getattr(publication, "content_version"):
            return int(getattr(publication, "content_version"))
        return asset.content_version

    def _publication_metadata(self, publication) -> dict[str, object]:
        metadata: dict[str, object] = {}
        for key in (
            "status",
            "mode",
            "mautic_email_id",
            "mautic_segment_id",
            "mautic_campaign_id",
            "linkedin_post_urn",
            "draft_revision_number",
            "published_revision_number",
            "targeted_contacts",
        ):
            value = getattr(publication, key, None)
            if value is not None and value != "" and value != []:
                metadata[key] = value
        if hasattr(publication, "metrics"):
            metadata["metrics"] = dict(getattr(publication, "metrics") or {})
        return metadata

    def _publication_field(self, publication, key: str, default: str = "") -> str:
        value = getattr(publication, key, default)
        return str(value or default)

    def _publication_operation(
        self,
        asset: ContentAsset,
        *,
        requested_action: str,
        status: str,
        correlation_id: str,
        publisher: str = "",
        external_id: str = "",
        preview_url: str = "",
        public_url: str = "",
        scheduled_at: datetime | None = None,
        published_at: datetime | None = None,
        metadata: dict[str, object] | None = None,
        use_asset_public_url_fallback: bool = True,
    ) -> StudioAdminPublicationOperation:
        payload = dict(metadata or {})
        error_message = str(payload.get("last_error") or payload.get("error_message") or asset.last_error or "")
        publication_status = str(payload.get("publication_status") or payload.get("status") or status).upper()
        error_code = ""
        retryable = False
        if error_message:
            error_code = "remote_error"
            retryable = publication_status in {"FAILED", "PUBLISHING", "DRAFT", "PREVIEW_READY"}
        return StudioAdminPublicationOperation(
            operation_id=f"op-{asset.id}-{requested_action}-{uuid4().hex[:8]}",
            asset_id=asset.id,
            channel=asset.channel,
            requested_action=requested_action,
            status=status,
            publisher=publisher or str(asset.results.get("publisher_type", "")),
            external_id=external_id or asset.external_publication_id,
            preview_url=preview_url or str(asset.results.get("preview_url", "")),
            public_url=public_url if public_url != "" or not use_asset_public_url_fallback else asset.external_publication_url,
            scheduled_at=scheduled_at or asset.scheduled_at,
            published_at=published_at or asset.published_at,
            error_code=error_code,
            error_message=error_message,
            retryable=retryable,
            correlation_id=correlation_id,
            metadata=payload,
        )

    def _find_asset(self, asset_id: str) -> tuple[CampaignRun, ContentAsset]:
        for campaign in self.campaign_service.list_campaigns():
            for asset in campaign.content_assets:
                if asset.id == asset_id:
                    return campaign, asset
        raise CampaignNotFoundError(f"Asset {asset_id} not found.")

    def _campaign_pending_validation(self, campaign: CampaignRun) -> bool:
        return any(asset.status in {AssetStatus.READY_FOR_REVIEW, AssetStatus.QUALITY_CHECK} for asset in campaign.content_assets)

    def _filter_campaigns(self, campaigns: list[CampaignRun], filters: dict[str, object]) -> list[CampaignRun]:
        status = str(filters.get("status") or "")
        channel = str(filters.get("channel") or "")
        asset_type = str(filters.get("asset_type") or "")
        campaign_id = str(filters.get("campaign_id") or "")
        period_from = filters.get("period_from")
        period_to = filters.get("period_to")
        published = filters.get("published")
        pending_validation = filters.get("pending_validation")
        in_error = filters.get("in_error")
        filtered: list[CampaignRun] = []
        for campaign in campaigns:
            if campaign_id and campaign.id != campaign_id:
                continue
            if status and campaign.status.value != status:
                continue
            if period_from and campaign.created_at < period_from:
                continue
            if period_to and campaign.created_at > period_to:
                continue
            if published is True and campaign.status not in {CampaignStatus.PARTIALLY_PUBLISHED, CampaignStatus.PUBLISHED}:
                continue
            if published is False and campaign.status in {CampaignStatus.PARTIALLY_PUBLISHED, CampaignStatus.PUBLISHED}:
                continue
            if pending_validation is True and not self._campaign_pending_validation(campaign):
                continue
            if in_error is True and not any(asset.status is AssetStatus.FAILED for asset in campaign.content_assets):
                continue
            if channel and not any(asset.channel == channel for asset in campaign.content_assets):
                continue
            if asset_type and not any(asset.asset_type == asset_type for asset in campaign.content_assets):
                continue
            filtered.append(campaign)
        return filtered

    def _asset_matches(self, asset: ContentAsset, campaign: CampaignRun, filters: dict[str, object]) -> bool:
        status = str(filters.get("status") or "")
        channel = str(filters.get("channel") or "")
        asset_type = str(filters.get("asset_type") or "")
        published = filters.get("published")
        in_error = filters.get("in_error")
        pending_validation = filters.get("pending_validation")
        period_from = filters.get("period_from")
        period_to = filters.get("period_to")
        if status and asset.status.value != status:
            return False
        if channel and asset.channel != channel:
            return False
        if asset_type and asset.asset_type != asset_type:
            return False
        if published is True and asset.status is not AssetStatus.PUBLISHED:
            return False
        if published is False and asset.status is AssetStatus.PUBLISHED:
            return False
        if in_error is True and asset.status is not AssetStatus.FAILED:
            return False
        if pending_validation is True and asset.status not in {AssetStatus.READY_FOR_REVIEW, AssetStatus.QUALITY_CHECK}:
            return False
        if period_from and asset.created_at < period_from:
            return False
        if period_to and asset.created_at > period_to:
            return False
        if filters.get("campaign_id") and campaign.id != filters.get("campaign_id"):
            return False
        return True

    def _sort_items(self, items: list, sort_by: str, sort_order: str) -> list:
        reverse = sort_order.lower() == "desc"
        mapping = {
            "created_at": "created_at",
            "title": "title",
            "status": "status",
            "week_reference": "week_reference",
            "week_number": "week_number",
            "scheduled_at": "scheduled_at",
            "published_at": "published_at",
            "channel": "channel",
            "asset_type": "asset_type",
        }
        attr = mapping.get(sort_by, "created_at")
        return sorted(items, key=lambda item: getattr(item, attr, None) or "", reverse=reverse)

    def _plain_text(self, value: str) -> str:
        return " ".join(value.replace("</p>", " ").replace("<p>", " ").replace("<br>", " ").replace("<br />", " ").split())

    def _serialize_last_event(self, event) -> dict[str, object]:
        payload = dict(event.payload or {})
        return {
            "id": event.id,
            "campaign_id": event.campaign_run_id or "",
            "event_type": event.event_type,
            "created_at": event.created_at,
            "payload": payload,
        }

    def _serialize_audit_event(self, event, *, integrity_ok: bool) -> dict[str, object]:
        return {
            "event_id": event.id,
            "campaign_id": event.campaign_run_id or "",
            "asset_id": event.content_asset_id,
            "actor_id": event.actor_id,
            "actor_source": event.actor_source,
            "actor_roles": list(event.actor_roles or []),
            "event_type": event.event_type,
            "timestamp": event.created_at,
            "correlation_id": event.correlation_id,
            "idempotency_key": event.idempotency_key,
            "previous_state": dict(event.previous_state or {}),
            "new_state": dict(event.new_state or {}),
            "metadata": dict(event.payload or {}),
            "result": event.result,
            "channel": event.channel,
            "source_ip": event.source_ip,
            "integrity_hash": event.integrity_hash,
            "previous_integrity_hash": event.previous_integrity_hash,
            "integrity_ok": integrity_ok,
        }
