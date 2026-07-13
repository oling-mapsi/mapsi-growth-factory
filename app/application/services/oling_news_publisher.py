from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.application.ports.connectors import OlingSiteConnectorPort
from app.application.services.review_portal_service import ReviewPortalService
from app.core.config import get_settings
from app.domain.entities import CampaignRun, ContentAsset, OlingNewsPublication, Publication, utcnow
from app.domain.enums import AssetStatus
from app.domain.errors import (
    CampaignNotFoundError,
    CampaignPublicationForbiddenError,
    DuplicateCampaignPublicationError,
    EmergencyStopActiveError,
    ExternalConnectorError,
)
from app.infrastructure.connectors.oling import OlingConnector
from app.infrastructure.observability import incr, structured_log
from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
from app.infrastructure.repositories.channel_operational_state import ChannelOperationalStateRepository
from app.infrastructure.repositories.oling import OlingNewsPublicationRepository


class OlingNewsPublisher(OlingSiteConnectorPort):
    def __init__(
        self,
        *,
        campaign_repository: SqlAlchemyCampaignRepository,
        publication_repository: OlingNewsPublicationRepository,
        connector: OlingConnector,
        audit_log: SqlAlchemyAuditLogRepository,
        review_portal: ReviewPortalService | None = None,
    ) -> None:
        self.campaign_repository = campaign_repository
        self.publication_repository = publication_repository
        self.connector = connector
        self.audit_log = audit_log
        self.review_portal = review_portal
        self.settings = get_settings()

    def validate_configuration(self, channel: str) -> dict:
        details = self.connector.validate_configuration()
        operational = self._operational_repository()
        return {
            "channel": channel,
            "enabled": operational.is_channel_feature_enabled(
                channel="oling",
                static_default=self.settings.publish_oling_enabled,
                safe_default_enabled=self.settings.channel_operational_safe_default_enabled,
            ),
            "mode": self.settings.oling_mode,
            **details,
        }

    def create_preview(self, campaign: CampaignRun, asset: ContentAsset) -> dict:
        publication = self._upsert_draft(campaign, asset, operation="preview")
        preview = self.connector.get_preview_url(asset.id, correlation_id=self._correlation_id(campaign, asset, "preview-url"))
        publication.preview_url = preview.get("preview_url", "")
        publication.status = "draft"
        publication.publication_mode_requested = "preview"
        publication.publication_mode_executed = self._executed_mode("preview")
        publication.publisher_type = self._publisher_type()
        publication.publication_status = "PREVIEW_READY"
        publication.last_error = ""
        publication.metrics = {**publication.metrics, "preview_expires_at": preview.get("expires_at")}
        publication = self.publication_repository.save(publication)
        self._apply_asset_results(asset, publication)
        self._save_campaign_asset(campaign, asset)
        self.audit_log.append(
            campaign.id,
            "publication.preview_created",
            {"preview_url": publication.preview_url},
            asset_id=asset.id,
            actor_source="system",
            correlation_id=self._correlation_id(campaign, asset, "preview"),
            previous_state={"status": asset.status.value},
            new_state={"status": asset.status.value},
            channel="oling",
            result="SUCCESS",
        )
        return self._serialize(publication)

    def publish(self, campaign: CampaignRun, asset: ContentAsset, *, idempotency_key: str = "") -> Publication:
        existing = self.publication_repository.get_by_asset_hash(asset.id, asset.content_hash)
        if existing is not None and existing.publication_status == "PUBLISHED":
            self._apply_asset_results(asset, existing)
            self._ensure_campaign_publication(campaign, asset, existing)
            self._save_campaign_asset(campaign, asset)
            return self._build_publication(campaign, asset, existing)
        if self.settings.oling_mode == "preview-only":
            raise CampaignPublicationForbiddenError("Oling preview-only mode forbids public publication.")
        self._assert_publishable(campaign, asset)
        publication = self._upsert_draft(campaign, asset, operation="publish")
        publication.publication_mode_requested = "publish"
        publication.publication_mode_executed = self._executed_mode("publish")
        publication.publisher_type = self._publisher_type()
        publication.idempotency_key = self._resolved_idempotency_key(asset, idempotency_key)
        publication.publication_status = "PUBLISHING"
        publication.last_error = ""
        if asset.status is not AssetStatus.PUBLISHED:
            asset.mark_publishing()
        self._apply_asset_results(asset, publication)
        self._save_campaign_asset(campaign, asset)
        preview = self.connector.get_preview_url(asset.id, correlation_id=self._correlation_id(campaign, asset, "preview-url"))
        try:
            status = self.connector.publish(asset.id, correlation_id=self._correlation_id(campaign, asset, "publish"))
        except ExternalConnectorError as exc:
            status = self._reconcile_after_publish_error(campaign, asset, publication, exc)
        publication.preview_url = preview.get("preview_url", publication.preview_url)
        self._apply_status(publication, asset, status)
        publication.published_content_version = asset.content_version
        publication.last_error = ""
        publication = self.publication_repository.save(publication)
        self._apply_asset_results(asset, publication)
        self._ensure_campaign_publication(campaign, asset, publication)
        self._save_campaign_asset(campaign, asset)
        self.audit_log.append(
            campaign.id,
            "publication.published",
            {
                "external_id": publication.external_id,
                "published_revision_number": publication.published_revision_number,
                "publication_mode_requested": publication.publication_mode_requested,
                "publication_mode_executed": publication.publication_mode_executed,
                "publisher_type": publication.publisher_type,
            },
            asset_id=asset.id,
            actor_source="system",
            correlation_id=self._correlation_id(campaign, asset, "publish"),
            idempotency_key=publication.idempotency_key,
            previous_state={"status": "APPROVED"},
            new_state={"status": asset.status.value},
            channel="oling",
            result="SUCCESS",
        )
        structured_log(
            "campaign.oling_published",
            campaign_id=campaign.id,
            asset_id=asset.id,
            external_id=publication.external_id,
            correlation_id=self._correlation_id(campaign, asset, "publish"),
            mode=self.settings.oling_mode,
        )
        incr("oling.publish.success")
        return self._build_publication(campaign, asset, publication)

    def update(self, campaign: CampaignRun, asset: ContentAsset) -> Publication:
        self._assert_content_ready(asset)
        publication = self.publication_repository.get_latest_for_asset(asset.id)
        if publication is None:
            publication = self._upsert_draft(campaign, asset, operation="update")
        else:
            self._push_draft(asset, campaign, method="PATCH")
            publication = self.publication_repository.get_latest_for_asset(asset.id) or publication
        status = self.connector.get_status(asset.id, correlation_id=self._correlation_id(campaign, asset, "status"))
        self._apply_status(publication, asset, status)
        publication.published_content_version = asset.content_version if publication.published_revision_number else publication.published_content_version
        publication.last_error = ""
        publication = self.publication_repository.save(publication)
        self._apply_asset_results(asset, publication)
        self._save_campaign_asset(campaign, asset)
        return Publication(
            campaign_run_id=campaign.id,
            content_asset_id=asset.id,
            channel="oling",
            external_reference=publication.external_id,
            external_url=publication.public_url,
        )

    def unpublish(self, campaign: CampaignRun, asset: ContentAsset) -> bool:
        publication = self.publication_repository.get_latest_for_asset(asset.id)
        if publication is None:
            raise CampaignPublicationForbiddenError("Oling publication not found for this asset.")
        status = self.connector.unpublish(asset.id, correlation_id=self._correlation_id(campaign, asset, "unpublish"))
        self._apply_status(publication, asset, status)
        publication.status = status.get("publication_status", "unpublished")
        publication = self.publication_repository.save(publication)
        self._apply_asset_results(asset, publication)
        self._save_campaign_asset(campaign, asset)
        self.audit_log.append(
            campaign.id,
            "publication.unpublished",
            {"external_id": publication.external_id},
            asset_id=asset.id,
            actor_source="system",
            correlation_id=self._correlation_id(campaign, asset, "unpublish"),
            previous_state={"status": "PUBLISHED"},
            new_state={"status": asset.status.value},
            channel="oling",
            result="SUCCESS",
        )
        return True

    def get_publication_status(self, campaign: CampaignRun, asset: ContentAsset) -> dict:
        status = self.connector.get_status(asset.id, correlation_id=self._correlation_id(campaign, asset, "status"))
        publication = self.publication_repository.get_latest_for_asset(asset.id) or OlingNewsPublication(
            campaign_run_id=campaign.id,
            content_asset_id=asset.id,
            external_id=asset.id,
            content_hash=asset.content_hash,
            mode=self.settings.oling_mode,
        )
        if not publication.publisher_type:
            publication.publisher_type = self._publisher_type()
        if not publication.publication_mode_executed:
            publication.publication_mode_executed = self._executed_mode("status")
        if not publication.publication_mode_requested:
            publication.publication_mode_requested = "status"
        self._apply_status(publication, asset, status)
        publication.last_error = ""
        publication = self.publication_repository.save(publication)
        self._apply_asset_results(asset, publication)
        self._save_campaign_asset(campaign, asset)
        return self._serialize(publication)

    def collect_metrics(self, campaign: CampaignRun, asset: ContentAsset) -> dict:
        details = self.get_publication_status(campaign, asset)
        incr("oling.metrics.collected")
        self.audit_log.append(
            campaign.id,
            "publication.metrics_collected",
            {"publication_status": details["publication_status"]},
            asset_id=asset.id,
            actor_source="system",
            correlation_id=self._correlation_id(campaign, asset, "metrics"),
            channel="oling",
            result="SUCCESS",
        )
        return {
            "campaign_id": campaign.id,
            "asset_id": asset.id,
            "publication_status": details["publication_status"],
            "published_revision_number": details["published_revision_number"],
            "published_at": details["published_at"],
        }

    def publish_asset(
        self,
        campaign_id: str,
        asset_id: str,
        *,
        dry_run: bool = False,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        campaign = self.campaign_repository.get(campaign_id)
        if campaign is None:
            raise CampaignNotFoundError(f"Campaign {campaign_id} not found.")
        asset = next((item for item in campaign.content_assets if item.id == asset_id), None)
        if asset is None or asset.channel != "oling":
            raise CampaignPublicationForbiddenError("Oling asset not found.")
        if dry_run:
            config = self.validate_configuration("oling")
            preview = self.create_preview(campaign, asset)
            preview["publication_mode_requested"] = "dry_run"
            preview["publication_mode_executed"] = self._executed_mode("dry_run")
            return {"dry_run": True, "configuration": config, "preview": preview}
        publication = self.publish(campaign, asset, idempotency_key=idempotency_key)
        current = self.publication_repository.get_latest_for_asset(asset.id)
        return {
            "dry_run": False,
            "publication": {
                "channel": publication.channel,
                "external_reference": publication.external_reference,
                "external_url": publication.external_url,
            },
            "details": self._serialize(current) if current is not None else {},
        }

    def _assert_publishable(self, campaign: CampaignRun, asset: ContentAsset) -> None:
        operational = self._operational_repository()
        if asset.channel != "oling":
            raise CampaignPublicationForbiddenError("Asset is not an Oling asset.")
        if asset.status is not AssetStatus.APPROVED:
            raise CampaignPublicationForbiddenError("Oling publication requires an APPROVED asset.")
        if asset.content_hash != asset.approved_content_hash:
            raise CampaignPublicationForbiddenError("Approved content hash no longer matches the current asset.")
        if not operational.is_channel_feature_enabled(
            channel="oling",
            static_default=self.settings.publish_oling_enabled,
            safe_default_enabled=self.settings.channel_operational_safe_default_enabled,
        ):
            raise CampaignPublicationForbiddenError("PUBLISH_OLING_ENABLED is false.")
        if operational.is_channel_kill_switch_active("oling"):
            raise EmergencyStopActiveError("Channel publication kill switch is active.")
        if operational.is_global_kill_switch_active(static_default=self.settings.workflow_kill_switch):
            raise EmergencyStopActiveError("Global publication kill switch is active.")
        self._assert_content_ready(asset)
        self._assert_quality_control(campaign)
        config = self.connector.validate_configuration()
        if not config["configured"]:
            raise CampaignPublicationForbiddenError(f"Oling configuration is incomplete: {', '.join(config['missing'])}")

    def _operational_repository(self) -> ChannelOperationalStateRepository:
        return ChannelOperationalStateRepository(self.campaign_repository.session)

    def _assert_content_ready(self, asset: ContentAsset) -> None:
        body = (asset.content_html or asset.body or asset.content_text).strip()
        if not asset.title.strip() or not body:
            raise CampaignPublicationForbiddenError("Oling content requires both title and body.")

    def _assert_quality_control(self, campaign: CampaignRun) -> None:
        if self.review_portal is None:
            return
        review = self.review_portal.review_repository.get_review_by_campaign(campaign.id)
        if review is None:
            return
        qc = review.quality_control or {}
        if qc.get("passed") is False or qc.get("status") == "failed":
            raise CampaignPublicationForbiddenError("Quality control failed.")

    def _upsert_draft(self, campaign: CampaignRun, asset: ContentAsset, *, operation: str) -> OlingNewsPublication:
        existing = self.publication_repository.get_latest_for_asset(asset.id)
        same_hash = self.publication_repository.get_by_asset_hash(asset.id, asset.content_hash)
        if same_hash and same_hash.status in {"published", "draft", "unpublished"}:
            self._refresh_preview(campaign, asset, same_hash)
            return same_hash
        publication = existing or OlingNewsPublication(
            campaign_run_id=campaign.id,
            content_asset_id=asset.id,
            external_id=asset.id,
            content_hash=asset.content_hash,
            mode=self.settings.oling_mode,
            publication_mode_requested=operation,
            publication_mode_executed=self._executed_mode(operation),
            publisher_type=self._publisher_type(),
            publication_status="DRAFT",
            idempotency_key=self._resolved_idempotency_key(asset, ""),
        )
        if existing and existing.content_hash == asset.content_hash and operation == "publish" and existing.status == "published":
            raise DuplicateCampaignPublicationError("This Oling asset version has already been published.")
        payload = self._payload_for(campaign, asset)
        self._push_draft(asset, campaign, method="PATCH" if existing else "POST", payload=payload)
        status = self.connector.get_status(asset.id, correlation_id=self._correlation_id(campaign, asset, "status"))
        publication.content_hash = asset.content_hash
        publication.mode = self.settings.oling_mode
        publication.publication_mode_requested = operation
        publication.publication_mode_executed = self._executed_mode(operation)
        publication.publisher_type = self._publisher_type()
        self._apply_status(publication, asset, status)
        publication.last_error = ""
        publication = self.publication_repository.save(publication)
        self._apply_asset_results(asset, publication)
        return publication

    def _push_draft(
        self,
        asset: ContentAsset,
        campaign: CampaignRun,
        *,
        method: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = payload or self._payload_for(campaign, asset)
        correlation_id = self._correlation_id(campaign, asset, f"draft-{method.lower()}")
        try:
            if method == "PATCH":
                return self.connector.update_draft(asset.id, body, correlation_id=correlation_id)
            return self.connector.create_draft(body, correlation_id=correlation_id)
        except ExternalConnectorError as exc:
            asset.mark_failed(str(exc))
            self._save_campaign_asset(campaign, asset)
            raise

    def _refresh_preview(self, campaign: CampaignRun, asset: ContentAsset, publication: OlingNewsPublication) -> None:
        preview = self.connector.get_preview_url(asset.id, correlation_id=self._correlation_id(campaign, asset, "preview-url"))
        publication.preview_url = preview.get("preview_url", publication.preview_url)
        publication.publication_mode_requested = "preview"
        publication.publication_mode_executed = self._executed_mode("preview")
        publication.publisher_type = self._publisher_type()
        if publication.publication_status != "PUBLISHED":
            publication.publication_status = "PREVIEW_READY"
        publication.metrics = {**publication.metrics, "preview_expires_at": preview.get("expires_at")}
        self.publication_repository.save(publication)

    def _payload_for(self, campaign: CampaignRun, asset: ContentAsset) -> dict[str, Any]:
        excerpt = asset.excerpt or asset.content_text[:280]
        content_html = asset.content_html or asset.body or f"<p>{asset.content_text}</p>"
        return {
            "external_id": asset.id,
            "title": asset.title,
            "slug": self._slugify(asset.title),
            "excerpt": excerpt,
            "content_html": content_html,
            "meta_title": asset.title,
            "meta_description": excerpt,
            "canonical_url": "",
            "featured_image": None,
            "categories": [],
            "tags": [],
            "publication_date": (asset.scheduled_at or utcnow()).isoformat(),
            "status": "draft",
            "author_display_name": "Growth Factory",
            "source_campaign_id": campaign.id,
        }

    def _slugify(self, value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower())
        slug = re.sub(r"-{2,}", "-", slug).strip("-")
        return slug or "actualite-growth"

    def _apply_status(self, publication: OlingNewsPublication, asset: ContentAsset, status: dict[str, Any]) -> None:
        publication.external_id = asset.id
        publication.public_slug = status.get("public_slug", publication.public_slug)
        publication.status = status.get("publication_status", publication.status)
        publication.publication_status = self._publication_status_from_remote(status, publication.preview_url)
        publication.draft_revision_number = status.get("draft_revision_number", publication.draft_revision_number)
        publication.published_revision_number = status.get("published_revision_number", publication.published_revision_number)
        publication.published_at = self._parse_dt(status.get("published_at")) or publication.published_at
        publication.unpublished_at = self._parse_dt(status.get("unpublished_at")) or publication.unpublished_at
        publication.public_url = self._public_url(publication.public_slug)
        publication.metrics = {**publication.metrics, **status}

    def _public_url(self, public_slug: str) -> str:
        if not public_slug:
            return ""
        return f"{self.settings.oling_site_base_url.rstrip('/')}/ressources/{public_slug}"

    def _parse_dt(self, value: Any):
        if not value:
            return None
        return datetime.fromisoformat(str(value))

    def _serialize(self, publication: OlingNewsPublication | None) -> dict[str, Any]:
        if publication is None:
            return {}
        return {
            "campaign_id": publication.campaign_run_id,
            "content_asset_id": publication.content_asset_id,
            "external_id": publication.external_id,
            "status": publication.status,
            "mode": publication.mode,
            "publication_mode_requested": publication.publication_mode_requested,
            "publication_mode_executed": publication.publication_mode_executed,
            "publisher_type": publication.publisher_type,
            "publication_status": publication.publication_status,
            "external_publication_id": publication.external_id,
            "external_publication_url": publication.public_url,
            "idempotency_key": publication.idempotency_key,
            "preview_url": publication.preview_url,
            "public_url": publication.public_url,
            "public_slug": publication.public_slug,
            "draft_revision_number": publication.draft_revision_number,
            "published_revision_number": publication.published_revision_number,
            "published_content_version": publication.published_content_version,
            "published_at": publication.published_at.isoformat() if publication.published_at else None,
            "unpublished_at": publication.unpublished_at.isoformat() if publication.unpublished_at else None,
            "last_error": publication.last_error,
            "metrics": publication.metrics,
        }

    def _apply_asset_results(self, asset: ContentAsset, publication: OlingNewsPublication) -> None:
        asset.external_publication_id = publication.external_id
        asset.external_publication_url = publication.public_url
        asset.published_at = publication.published_at
        asset.last_error = publication.last_error
        if publication.publication_status == "PUBLISHED":
            asset.mark_published(
                external_id=publication.external_id,
                external_url=publication.public_url,
                published_at=publication.published_at,
            )
        elif publication.publication_status == "FAILED":
            asset.mark_failed(publication.last_error or "Oling publication failed.")
        asset.results = {
            **asset.results,
            "publication_mode_requested": publication.publication_mode_requested,
            "publication_mode_executed": publication.publication_mode_executed,
            "publisher_type": publication.publisher_type,
            "publication_status": publication.publication_status,
            "external_publication_id": publication.external_id,
            "external_publication_url": publication.public_url,
            "idempotency_key": publication.idempotency_key,
            "preview_url": publication.preview_url,
            "public_url": publication.public_url,
            "public_slug": publication.public_slug,
            "draft_revision_number": publication.draft_revision_number,
            "published_revision_number": publication.published_revision_number,
            "published_content_version": publication.published_content_version,
        }

    def _save_campaign_asset(self, campaign: CampaignRun, asset: ContentAsset) -> None:
        for index, current in enumerate(campaign.content_assets):
            if current.id == asset.id:
                campaign.content_assets[index] = asset
                break
        self.campaign_repository.save(campaign)

    def _correlation_id(self, campaign: CampaignRun, asset: ContentAsset, operation: str) -> str:
        return f"oling:{campaign.id}:{asset.id}:{operation}"

    def _publisher_type(self) -> str:
        return "oling_mock" if self.settings.oling_mode == "mock" else "oling_api"

    def _executed_mode(self, operation: str) -> str:
        if self.settings.oling_mode == "mock":
            return "sandbox"
        if operation in {"preview", "dry_run"} or self.settings.oling_mode == "preview-only":
            return "preview"
        return "live"

    def _publication_status_from_remote(self, status: dict[str, Any], preview_url: str) -> str:
        remote = str(status.get("publication_status", "")).lower()
        if remote == "published":
            return "PUBLISHED"
        if remote == "unpublished":
            return "UNPUBLISHED"
        if remote == "draft" and preview_url:
            return "PREVIEW_READY"
        if remote == "draft":
            return "DRAFT"
        return remote.upper() or "DRAFT"

    def _resolved_idempotency_key(self, asset: ContentAsset, idempotency_key: str) -> str:
        return idempotency_key or f"oling:{asset.id}:{asset.content_hash}"

    def _build_publication(self, campaign: CampaignRun, asset: ContentAsset, publication: OlingNewsPublication) -> Publication:
        return Publication(
            campaign_run_id=campaign.id,
            content_asset_id=asset.id,
            channel="oling",
            external_reference=publication.external_id,
            external_url=publication.public_url,
            published_at=publication.published_at or utcnow(),
        )

    def _ensure_campaign_publication(self, campaign: CampaignRun, asset: ContentAsset, publication: OlingNewsPublication) -> None:
        if publication.publication_status != "PUBLISHED":
            return
        campaign.publish(self._build_publication(campaign, asset, publication))

    def _reconcile_after_publish_error(
        self,
        campaign: CampaignRun,
        asset: ContentAsset,
        publication: OlingNewsPublication,
        error: ExternalConnectorError,
    ) -> dict[str, Any]:
        try:
            status = self.connector.get_status(asset.id, correlation_id=self._correlation_id(campaign, asset, "status-after-error"))
        except ExternalConnectorError:
            publication.last_error = str(error)
            publication.publication_status = "FAILED"
            publication.status = "failed"
            publication = self.publication_repository.save(publication)
            self._apply_asset_results(asset, publication)
            self._save_campaign_asset(campaign, asset)
            raise error
        if self._publication_status_from_remote(status, publication.preview_url) == "PUBLISHED":
            return status
        publication.last_error = str(error)
        publication.publication_status = "FAILED"
        publication.status = "failed"
        publication = self.publication_repository.save(publication)
        self._apply_asset_results(asset, publication)
        self._save_campaign_asset(campaign, asset)
        raise error
