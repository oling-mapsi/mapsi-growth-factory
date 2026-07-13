from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.application.services.review_portal_service import ReviewPortalService
from app.core.config import get_settings
from app.domain.entities import CampaignRun, ContentAsset, MapsiNewsPublication, Publication, utcnow
from app.domain.enums import AssetStatus
from app.domain.errors import (
    CampaignNotFoundError,
    CampaignPublicationForbiddenError,
    DuplicateCampaignPublicationError,
    EmergencyStopActiveError,
    ExternalConnectorError,
    RemoteUnsupportedError,
)
from app.infrastructure.connectors.mapsi_site import MapsiSiteConnector
from app.infrastructure.connectors.mapsi_site_contract import get_openapi_info, supports_unpublish
from app.infrastructure.observability import incr, structured_log
from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
from app.infrastructure.repositories.channel_operational_state import ChannelOperationalStateRepository
from app.infrastructure.repositories.mapsi_site_publications import MapsiNewsPublicationRepository


class MapsiNewsPublisher:
    def __init__(
        self,
        *,
        campaign_repository: SqlAlchemyCampaignRepository,
        publication_repository: MapsiNewsPublicationRepository,
        connector: MapsiSiteConnector,
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
        operational = ChannelOperationalStateRepository(self.campaign_repository.session)
        contract = get_openapi_info()
        return {
            "channel": channel,
            "enabled": operational.is_channel_feature_enabled(
                channel="mapsi_site",
                static_default=self.settings.publish_mapsi_site_enabled,
                safe_default_enabled=self.settings.channel_operational_safe_default_enabled,
            ),
            "mode": self.settings.mapsi_site_mode,
            "contract_version": contract.get("version", ""),
            "unpublish_supported": supports_unpublish(),
            **details,
        }

    def create_preview(self, campaign: CampaignRun, asset: ContentAsset) -> dict[str, Any]:
        publication = self._upsert_draft(campaign, asset, operation="preview")
        preview = self.connector.get_preview_url(asset.id, correlation_id=self._correlation_id(campaign, asset, "preview-url"))
        publication.preview_url = preview.get("preview_url", "")
        publication.status = "draft"
        publication.publication_mode_requested = "preview"
        publication.publication_mode_executed = self._executed_mode("preview")
        publication.publisher_type = self._publisher_type()
        publication.publication_status = "PREVIEW_READY"
        publication.last_error = ""
        publication.metrics = {
            **publication.metrics,
            "preview_expires_at": preview.get("expires_at"),
            "remote_article_id": preview.get("article_id"),
            "remote_version": preview.get("version"),
            "remote_status": preview.get("status"),
            "remote_slug": preview.get("slug"),
            "correlation_id": preview.get("correlation_id", ""),
            "idempotent_replay": bool(preview.get("idempotent_replay", False)),
            "growth_external_id": preview.get("growth_external_id", asset.id),
        }
        publication = self.publication_repository.save(publication)
        self._apply_asset_results(asset, publication)
        self._save_campaign_asset(campaign, asset)
        return self._serialize(publication)

    def publish(self, campaign: CampaignRun, asset: ContentAsset, *, idempotency_key: str = "") -> Publication:
        existing = self.publication_repository.get_by_asset_hash(asset.id, asset.content_hash)
        if existing is not None and existing.publication_status == "PUBLISHED":
            existing.publication_mode_requested = "publish"
            existing.publication_mode_executed = self._executed_mode("publish")
            existing.publisher_type = self._publisher_type()
            existing.metrics = {
                **existing.metrics,
                "idempotent_replay": True,
                "correlation_id": self._correlation_id(campaign, asset, "publish-replay"),
            }
            existing = self.publication_repository.save(existing)
            self._apply_asset_results(asset, existing)
            self._ensure_campaign_publication(campaign, asset, existing)
            self._save_campaign_asset(campaign, asset)
            return self._build_publication(campaign, asset, existing)
        if self.settings.mapsi_site_mode == "preview-only":
            raise CampaignPublicationForbiddenError("Mapsi Site preview-only mode forbids public publication.")
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
            status = self.connector.publish(
                asset.id,
                correlation_id=self._correlation_id(campaign, asset, "publish"),
                idempotency_key=publication.idempotency_key,
            )
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
        incr("mapsi_site.publish.success")
        structured_log("campaign.mapsi_site_published", campaign_id=campaign.id, asset_id=asset.id, external_id=publication.external_id)
        return self._build_publication(campaign, asset, publication)

    def unpublish(self, campaign: CampaignRun, asset: ContentAsset) -> bool:
        if not supports_unpublish():
            raise CampaignPublicationForbiddenError("Mapsi Site unpublish is unsupported by the remote contract.")
        publication = self.publication_repository.get_latest_for_asset(asset.id)
        if publication is None:
            raise CampaignPublicationForbiddenError("Mapsi Site publication not found for this asset.")
        try:
            status = self.connector.unpublish(asset.id, correlation_id=self._correlation_id(campaign, asset, "unpublish"))
        except RemoteUnsupportedError as exc:
            publication.publication_status = "UNPUBLISH_UNSUPPORTED"
            publication.last_error = str(exc)
            publication.metrics = {**publication.metrics, "unpublish_supported": False}
            self.publication_repository.save(publication)
            self._apply_asset_results(asset, publication)
            self._save_campaign_asset(campaign, asset)
            raise CampaignPublicationForbiddenError("Mapsi Site unpublish is unsupported.") from exc
        self._apply_status(publication, asset, status)
        publication.status = status.get("status", "unpublished")
        publication = self.publication_repository.save(publication)
        self._apply_asset_results(asset, publication)
        self._save_campaign_asset(campaign, asset)
        return True

    def get_publication_status(self, campaign: CampaignRun, asset: ContentAsset) -> dict[str, Any]:
        status = self.connector.get_status(asset.id, correlation_id=self._correlation_id(campaign, asset, "status"))
        publication = self.publication_repository.get_latest_for_asset(asset.id) or MapsiNewsPublication(
            campaign_run_id=campaign.id,
            content_asset_id=asset.id,
            external_id=asset.id,
            content_hash=asset.content_hash,
            mode=self.settings.mapsi_site_mode,
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

    def publish_asset(self, campaign_id: str, asset_id: str, *, dry_run: bool = False, idempotency_key: str = "") -> dict[str, Any]:
        campaign = self.campaign_repository.get(campaign_id)
        if campaign is None:
            raise CampaignNotFoundError(f"Campaign {campaign_id} not found.")
        asset = next((item for item in campaign.content_assets if item.id == asset_id), None)
        if asset is None or asset.channel != "mapsi_site":
            raise CampaignPublicationForbiddenError("Mapsi Site asset not found.")
        if dry_run:
            config = self.validate_configuration("mapsi_site")
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
        operational = ChannelOperationalStateRepository(self.campaign_repository.session)
        if asset.channel != "mapsi_site":
            raise CampaignPublicationForbiddenError("Asset is not a Mapsi Site asset.")
        if asset.asset_type != "mapsi_news_article":
            raise CampaignPublicationForbiddenError("Mapsi Site publication only supports mapsi_news_article assets.")
        if asset.status is not AssetStatus.APPROVED:
            raise CampaignPublicationForbiddenError("Mapsi Site publication requires an APPROVED asset.")
        if asset.content_hash != asset.approved_content_hash:
            raise CampaignPublicationForbiddenError("Approved content hash no longer matches the current asset.")
        if not operational.is_channel_feature_enabled(channel="mapsi_site", static_default=self.settings.publish_mapsi_site_enabled, safe_default_enabled=self.settings.channel_operational_safe_default_enabled):
            raise CampaignPublicationForbiddenError("PUBLISH_MAPSI_SITE_ENABLED is false.")
        if operational.is_channel_kill_switch_active("mapsi_site"):
            raise EmergencyStopActiveError("Channel publication kill switch is active.")
        if operational.is_global_kill_switch_active(static_default=self.settings.workflow_kill_switch):
            raise EmergencyStopActiveError("Global publication kill switch is active.")
        self._assert_content_ready(asset)
        self._assert_quality_control(campaign)
        config = self.connector.validate_configuration()
        if not config["configured"]:
            raise CampaignPublicationForbiddenError(f"Mapsi Site configuration is incomplete: {', '.join(config['missing'])}")

    def _assert_content_ready(self, asset: ContentAsset) -> None:
        body = (asset.content_html or asset.body or asset.content_text).strip()
        if not asset.title.strip() or not body:
            raise CampaignPublicationForbiddenError("Mapsi Site content requires both title and body.")

    def _assert_quality_control(self, campaign: CampaignRun) -> None:
        if self.review_portal is None:
            return
        review = self.review_portal.review_repository.get_review_by_campaign(campaign.id)
        if review is None:
            return
        qc = review.quality_control or {}
        if qc.get("passed") is False or qc.get("status") == "failed":
            raise CampaignPublicationForbiddenError("Quality control failed.")

    def _upsert_draft(self, campaign: CampaignRun, asset: ContentAsset, *, operation: str) -> MapsiNewsPublication:
        existing = self.publication_repository.get_latest_for_asset(asset.id)
        same_hash = self.publication_repository.get_by_asset_hash(asset.id, asset.content_hash)
        if same_hash and same_hash.status in {"published", "draft", "unpublished"}:
            self._refresh_preview(campaign, asset, same_hash)
            return same_hash
        publication = existing or MapsiNewsPublication(
            campaign_run_id=campaign.id,
            content_asset_id=asset.id,
            external_id=asset.id,
            content_hash=asset.content_hash,
            mode=self.settings.mapsi_site_mode,
            publication_mode_requested=operation,
            publication_mode_executed=self._executed_mode(operation),
            publisher_type=self._publisher_type(),
            publication_status="DRAFT",
            idempotency_key=self._resolved_idempotency_key(asset, ""),
        )
        if existing and existing.content_hash == asset.content_hash and operation == "publish" and existing.status == "published":
            raise DuplicateCampaignPublicationError("This Mapsi Site asset version has already been published.")
        self._push_draft(asset, campaign, method="PATCH" if existing else "POST", payload=self._payload_for(campaign, asset))
        status = self.connector.get_status(asset.id, correlation_id=self._correlation_id(campaign, asset, "status"))
        publication.content_hash = asset.content_hash
        publication.mode = self.settings.mapsi_site_mode
        publication.publication_mode_requested = operation
        publication.publication_mode_executed = self._executed_mode(operation)
        publication.publisher_type = self._publisher_type()
        self._apply_status(publication, asset, status)
        publication.last_error = ""
        publication = self.publication_repository.save(publication)
        self._apply_asset_results(asset, publication)
        return publication

    def _push_draft(self, asset: ContentAsset, campaign: CampaignRun, *, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        correlation_id = self._correlation_id(campaign, asset, f"draft-{method.lower()}")
        try:
            if method == "PATCH":
                return self.connector.update_draft(asset.id, payload, correlation_id=correlation_id)
            return self.connector.create_draft(payload, correlation_id=correlation_id)
        except ExternalConnectorError as exc:
            asset.mark_failed(str(exc))
            self._save_campaign_asset(campaign, asset)
            raise

    def _refresh_preview(self, campaign: CampaignRun, asset: ContentAsset, publication: MapsiNewsPublication) -> None:
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
            "categories": ["growth"],
            "tags": ["mapsi", "growth"],
            "publication_date": (asset.scheduled_at or utcnow()).isoformat(),
            "author_display_name": "Growth Factory",
            "source_campaign_id": campaign.id,
        }

    def _slugify(self, value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower())
        slug = re.sub(r"-{2,}", "-", slug).strip("-")
        return slug or "actualite-mapsi"

    def _apply_status(self, publication: MapsiNewsPublication, asset: ContentAsset, status: dict[str, Any]) -> None:
        publication.external_id = str(status.get("article_id") or publication.external_id or "")
        publication.public_slug = status.get("slug", publication.public_slug)
        publication.status = status.get("status", publication.status)
        publication.publication_status = self._publication_status_from_remote(status, publication.preview_url)
        publication.draft_revision_number = status.get("version", publication.draft_revision_number)
        publication.published_revision_number = status.get("published_version") or (
            status.get("version") if status.get("status") == "published" else publication.published_revision_number
        )
        publication.published_at = self._parse_dt(status.get("published_at")) or publication.published_at
        publication.public_url = status.get("public_url") or ""
        if status.get("status") == "unpublished":
            publication.unpublished_at = utcnow()
        publication.metrics = {
            **publication.metrics,
            **status,
            "remote_article_id": status.get("article_id"),
            "remote_version": status.get("version"),
            "remote_published_version": status.get("published_version"),
            "remote_status": status.get("status"),
            "growth_external_id": status.get("growth_external_id", asset.id),
            "correlation_id": status.get("correlation_id", ""),
            "idempotent_replay": bool(status.get("idempotent_replay", False)),
            "has_pending_draft": bool(status.get("has_pending_draft", False)),
        }

    def _parse_dt(self, value: Any):
        if not value:
            return None
        return datetime.fromisoformat(str(value))

    def _public_url(self, public_slug: str) -> str:
        if not public_slug:
            return ""
        return f"{self.settings.mapsi_site_public_base_url.rstrip('/')}/actualites/{public_slug}"

    def _serialize(self, publication: MapsiNewsPublication | None) -> dict[str, Any]:
        if publication is None:
            return {}
        return {
            "campaign_id": publication.campaign_run_id,
            "content_asset_id": publication.content_asset_id,
            "external_id": publication.external_id,
            "growth_external_id": publication.metrics.get("growth_external_id", publication.content_asset_id),
            "status": publication.status,
            "mode": publication.mode,
            "publication_mode_requested": publication.publication_mode_requested,
            "publication_mode_executed": publication.publication_mode_executed,
            "publisher_type": publication.publisher_type,
            "publication_status": publication.publication_status,
            "external_publication_id": publication.external_id,
            "external_publication_url": publication.public_url,
            "idempotency_key": publication.idempotency_key,
            "idempotent_replay": bool(publication.metrics.get("idempotent_replay", False)),
            "correlation_id": publication.metrics.get("correlation_id", ""),
            "preview_url": publication.preview_url,
            "public_url": publication.public_url,
            "public_slug": publication.public_slug,
            "draft_revision_number": publication.draft_revision_number,
            "published_revision_number": publication.published_revision_number,
            "published_content_version": publication.published_content_version,
            "remote_article_id": publication.metrics.get("remote_article_id", publication.external_id),
            "remote_version": publication.metrics.get("remote_version"),
            "remote_status": publication.metrics.get("remote_status", publication.status),
            "has_pending_draft": bool(publication.metrics.get("has_pending_draft", False)),
            "published_at": publication.published_at.isoformat() if publication.published_at else None,
            "unpublished_at": publication.unpublished_at.isoformat() if publication.unpublished_at else None,
            "last_error": publication.last_error,
            "metrics": publication.metrics,
        }

    def _apply_asset_results(self, asset: ContentAsset, publication: MapsiNewsPublication) -> None:
        asset.external_publication_id = publication.external_id
        asset.external_publication_url = publication.public_url
        asset.published_at = publication.published_at
        asset.last_error = publication.last_error
        if publication.publication_status == "PUBLISHED":
            asset.mark_published(external_id=publication.external_id, external_url=publication.public_url, published_at=publication.published_at)
        elif publication.publication_status == "FAILED":
            asset.mark_failed(publication.last_error or "Mapsi Site publication failed.")
        asset.results = {
            **asset.results,
            "publication_mode_requested": publication.publication_mode_requested,
            "publication_mode_executed": publication.publication_mode_executed,
            "publisher_type": publication.publisher_type,
            "publication_status": publication.publication_status,
            "external_publication_id": publication.external_id,
            "external_publication_url": publication.public_url,
            "idempotency_key": publication.idempotency_key,
            "idempotent_replay": bool(publication.metrics.get("idempotent_replay", False)),
            "correlation_id": publication.metrics.get("correlation_id", ""),
            "growth_external_id": publication.metrics.get("growth_external_id", asset.id),
            "preview_url": publication.preview_url,
            "public_url": publication.public_url,
            "public_slug": publication.public_slug,
            "draft_revision_number": publication.draft_revision_number,
            "published_revision_number": publication.published_revision_number,
            "published_content_version": publication.published_content_version,
            "remote_article_id": publication.metrics.get("remote_article_id", publication.external_id),
            "remote_status": publication.metrics.get("remote_status", publication.status),
            "remote_version": publication.metrics.get("remote_version"),
            "has_pending_draft": bool(publication.metrics.get("has_pending_draft", False)),
        }

    def _save_campaign_asset(self, campaign: CampaignRun, asset: ContentAsset) -> None:
        for index, current in enumerate(campaign.content_assets):
            if current.id == asset.id:
                campaign.content_assets[index] = asset
                break
        self.campaign_repository.save(campaign)

    def _publisher_type(self) -> str:
        return "mapsi_site_mock" if self.settings.mapsi_site_mode == "mock" else "mapsi_site_api"

    def _executed_mode(self, operation: str) -> str:
        if self.settings.mapsi_site_mode == "mock":
            return "sandbox"
        if operation in {"preview", "dry_run"} or self.settings.mapsi_site_mode == "preview-only":
            return "preview"
        return "live"

    def _publication_status_from_remote(self, status: dict[str, Any], preview_url: str) -> str:
        remote = str(status.get("status", "")).lower()
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
        return idempotency_key or f"mapsi_site:{asset.id}:{asset.content_hash}"

    def _build_publication(self, campaign: CampaignRun, asset: ContentAsset, publication: MapsiNewsPublication) -> Publication:
        return Publication(
            campaign_run_id=campaign.id,
            content_asset_id=asset.id,
            channel="mapsi_site",
            external_reference=publication.external_id,
            external_url=publication.public_url,
            published_at=publication.published_at or utcnow(),
        )

    def _ensure_campaign_publication(self, campaign: CampaignRun, asset: ContentAsset, publication: MapsiNewsPublication) -> None:
        if publication.publication_status != "PUBLISHED":
            return
        campaign.publish(self._build_publication(campaign, asset, publication))

    def _reconcile_after_publish_error(self, campaign: CampaignRun, asset: ContentAsset, publication: MapsiNewsPublication, error: ExternalConnectorError) -> dict[str, Any]:
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

    def _correlation_id(self, campaign: CampaignRun, asset: ContentAsset, operation: str) -> str:
        return f"mapsi_site:{campaign.id}:{asset.id}:{operation}"
