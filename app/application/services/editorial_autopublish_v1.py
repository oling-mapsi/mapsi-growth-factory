from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import perf_counter
from zoneinfo import ZoneInfo

from app.application.services.studio_admin_service import StudioAdminService
from app.core.config import get_settings
from app.core.security import sha256_hexdigest
from app.domain.entities import CampaignRun, ContentAsset, build_content_hash
from app.domain.enums import AssetStatus, CampaignStatus


@dataclass
class EditorialAutopublishService:
    studio_admin_service: StudioAdminService

    def __post_init__(self) -> None:
        self.settings = get_settings()

    def run_weekly(self, *, mode: str, actor: str, correlation_id: str) -> dict[str, object]:
        started = perf_counter()
        report = {
            "mode": mode,
            "started_at": datetime.now(UTC).isoformat(),
            "timezone": self.settings.editorial_timezone,
            "schedules": {
                "mapsi_market": self.settings.mapsi_market_schedule,
                "oling_practice": self.settings.oling_practice_schedule,
            },
            "auto_publish": {
                "web_enabled": self.settings.auto_publish_web_enabled,
                "mapsi_market": self.settings.auto_publish_mapsi_market,
                "oling_practice": self.settings.auto_publish_oling_practice,
                "min_quality_score": self._min_quality_score(),
                "block_on_warning": self.settings.auto_publish_block_on_warning,
                "delay_minutes": self.settings.auto_publish_delay_minutes,
            },
            "campaigns": [],
            "errors": [],
            "publications": [],
            "replays": [],
        }
        report["campaigns"].append(self._run_mapsi_market(mode=mode, actor=actor, correlation_id=correlation_id))
        report["campaigns"].append(self._run_oling_practice(mode=mode, actor=actor, correlation_id=correlation_id))
        report["duration_ms"] = max(1, int((perf_counter() - started) * 1000))
        return report

    def return_to_safe_mode(self, *, actor: str, correlation_id: str) -> dict[str, object]:
        previous = {
            "AUTO_PUBLISH_WEB_ENABLED": self.settings.auto_publish_web_enabled,
            "AUTO_PUBLISH_MAPSI_MARKET": self.settings.auto_publish_mapsi_market,
            "AUTO_PUBLISH_OLING_PRACTICE": self.settings.auto_publish_oling_practice,
        }
        safe_report = self.studio_admin_service.return_to_safe_mode(actor=actor, correlation_id=correlation_id)
        return {
            "flags_before": previous,
            "flags_after": {
                "AUTO_PUBLISH_WEB_ENABLED": False,
                "AUTO_PUBLISH_MAPSI_MARKET": False,
                "AUTO_PUBLISH_OLING_PRACTICE": False,
            },
            "global_controls": safe_report,
            "articles_unpublished": False,
            "generated_at": datetime.now(UTC).isoformat(),
        }

    def _run_mapsi_market(self, *, mode: str, actor: str, correlation_id: str) -> dict[str, object]:
        summary = self.studio_admin_service.generate_mapsi_market(actor=actor, correlation_id=correlation_id)
        campaign = self.studio_admin_service.campaign_service.get_campaign(summary.id)
        assets = [asset for asset in campaign.content_assets if asset.channel in {"oling", "mapsi_site"}]
        item = self._campaign_report(campaign, assets)
        item["campaign_type"] = "MAPSI_MARKET"
        item["destination_channels"] = [asset.channel for asset in assets]
        item["selected_topic"] = campaign.editorial_briefs[0].title if campaign.editorial_briefs else campaign.name
        item["result"] = self._process_campaign(mode=mode, campaign=campaign, assets=assets, actor=actor, correlation_id=correlation_id, specific_flag=self.settings.auto_publish_mapsi_market, require_all=True)
        return item

    def _run_oling_practice(self, *, mode: str, actor: str, correlation_id: str) -> dict[str, object]:
        summary = self.studio_admin_service.generate_oling_practice(actor=actor, correlation_id=correlation_id)
        campaign = self.studio_admin_service.campaign_service.get_campaign(summary.id)
        assets = [asset for asset in campaign.content_assets if asset.channel == "oling"]
        item = self._campaign_report(campaign, assets)
        item["campaign_type"] = "OLING_PRACTICE"
        item["selected_topic"] = campaign.editorial_briefs[0].title if campaign.editorial_briefs else campaign.name
        item["result"] = self._process_campaign(mode=mode, campaign=campaign, assets=assets, actor=actor, correlation_id=correlation_id, specific_flag=self.settings.auto_publish_oling_practice, require_all=False)
        return item

    def _process_campaign(
        self,
        *,
        mode: str,
        campaign: CampaignRun,
        assets: list[ContentAsset],
        actor: str,
        correlation_id: str,
        specific_flag: bool,
        require_all: bool,
    ) -> dict[str, object]:
        checks = [self._evaluate_asset(asset) for asset in assets]
        previews: list[dict[str, object]] = []
        preview_ok = True
        for asset, check in zip(assets, checks, strict=True):
            if check["eligible"]:
                op = self.studio_admin_service.create_asset_preview(asset.id, actor=actor, correlation_id=correlation_id)
                previews.append({"asset_id": asset.id, "preview_url": op.preview_url, "status": op.status})
                preview_ok = preview_ok and bool(op.preview_url)
            else:
                previews.append({"asset_id": asset.id, "preview_url": "", "status": "skipped", "errors": check["blocking_reasons"]})
                preview_ok = False
        publish_allowed = (
            mode == "publish"
            and self.settings.auto_publish_web_enabled
            and specific_flag
            and (all(check["eligible"] for check in checks) if require_all else checks and checks[0]["eligible"])
            and preview_ok
        )
        publications: list[dict[str, object]] = []
        publication_errors: list[dict[str, object]] = []
        if publish_allowed:
            for asset, check in zip(assets, checks, strict=True):
                if not check["eligible"]:
                    continue
                before = self.studio_admin_service.get_asset_publication(asset.id)
                idempotency_key = self._idempotency_key(campaign, asset)
                try:
                    operation = self.studio_admin_service.publish_asset_operation(asset.id, actor=actor, correlation_id=correlation_id, idempotency_key=idempotency_key)
                    after = self.studio_admin_service.get_asset_publication(asset.id)
                    publications.append(
                        {
                            "asset_id": asset.id,
                            "channel": asset.channel,
                            "status": operation.status,
                            "preview_url": operation.preview_url,
                            "public_url": operation.public_url,
                            "published_at": operation.published_at.isoformat() if operation.published_at else None,
                            "idempotency_key": idempotency_key,
                            "already_published": bool(before.publication_status == "PUBLISHED"),
                            "replay": bool(before.idempotency_key and before.idempotency_key == after.idempotency_key),
                        }
                    )
                except Exception as exc:
                    after = self.studio_admin_service.get_asset_publication(asset.id)
                    if "timeout" in str(exc).casefold() and after.publication_status == "PUBLISHED":
                        publications.append(
                            {
                                "asset_id": asset.id,
                                "channel": asset.channel,
                                "status": "published",
                                "preview_url": after.metadata.get("preview_url", ""),
                                "public_url": after.external_publication_url,
                                "published_at": after.published_at.isoformat() if after.published_at else None,
                                "idempotency_key": idempotency_key,
                                "already_published": False,
                                "replay": True,
                            }
                        )
                        continue
                    publication_errors.append({"asset_id": asset.id, "channel": asset.channel, "error": str(exc)})
                    asset.last_error = str(exc)
                    self.studio_admin_service.campaign_service.repository.save(campaign)
                    if require_all:
                        break
        elif mode == "publish":
            publication_errors.append(
                {
                    "campaign_id": campaign.id,
                    "error": "Autopublish blocked by flags or editorial guards.",
                    "flags": {
                        "AUTO_PUBLISH_WEB_ENABLED": self.settings.auto_publish_web_enabled,
                        "specific_flag": specific_flag,
                    },
                }
            )
        return {
            "checks": checks,
            "previews": previews,
            "preview_ok": preview_ok,
            "publish_allowed": publish_allowed,
            "publications": publications,
            "publication_errors": publication_errors,
            "final_status": self.studio_admin_service.campaign_service.get_campaign(campaign.id).status.value,
            "partial_alert": bool(publication_errors and publications),
        }

    def _evaluate_asset(self, asset: ContentAsset) -> dict[str, object]:
        article = dict(asset.results.get("editorial_article") or {})
        quality = dict(asset.results.get("editorial_quality") or {})
        issues = list(quality.get("issues") or [])
        warnings = [item for item in issues if item.get("severity") == "warning"]
        errors = [item for item in issues if item.get("severity") == "error"]
        claims = list(article.get("claims") or [])
        score = self._quality_score(quality)
        blocking_reasons: list[str] = []
        if not asset.source_evidence_ids:
            blocking_reasons.append("missing_sources")
        if not quality.get("passed", False):
            blocking_reasons.append("quality_refused")
        if self.settings.auto_publish_block_on_warning and warnings:
            blocking_reasons.append("blocking_warning")
        if self._min_quality_score() is not None and score < self._min_quality_score():
            blocking_reasons.append("quality_score_too_low")
        if any(not claim.get("verified", False) for claim in claims):
            blocking_reasons.append("unverified_claim")
        if any(item.get("code") == "content_too_similar" for item in issues):
            blocking_reasons.append("duplicate")
        if not asset.content_hash:
            blocking_reasons.append("missing_content_hash")
        recomputed_hash = build_content_hash(
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
        if asset.content_hash != recomputed_hash:
            blocking_reasons.append("content_hash_mismatch")
        execution = dict(asset.results.get("editorial_execution") or {})
        if not execution.get("knowledge_version"):
            blocking_reasons.append("missing_knowledge_version")
        channel_summary = self.studio_admin_service.get_channel(asset.channel)
        if not channel_summary.enabled:
            blocking_reasons.append("channel_disabled")
        if channel_summary.emergency_kill_switch:
            blocking_reasons.append("channel_kill_switch")
        if self.studio_admin_service.get_global_kill_switch().active:
            blocking_reasons.append("global_kill_switch")
        if not channel_summary.configured or (channel_summary.last_error or "").strip():
            blocking_reasons.append("publisher_unhealthy")
        return {
            "asset_id": asset.id,
            "channel": asset.channel,
            "title": asset.title,
            "quality_passed": bool(quality.get("passed", False)),
            "quality_score": score,
            "warnings": warnings,
            "errors": errors,
            "blocking_reasons": blocking_reasons,
            "eligible": not blocking_reasons,
            "cost_usd": execution.get("cost_usd", 0.0),
            "knowledge_version": execution.get("knowledge_version", ""),
        }

    def _campaign_report(self, campaign: CampaignRun, assets: list[ContentAsset]) -> dict[str, object]:
        return {
            "campaign_id": campaign.id,
            "campaign_status": campaign.status.value,
            "topic": campaign.editorial_briefs[0].title if campaign.editorial_briefs else campaign.name,
            "articles_generated": [
                {
                    "asset_id": asset.id,
                    "channel": asset.channel,
                    "title": asset.title,
                    "quality": dict(asset.results.get("editorial_quality") or {}),
                    "cost_usd": dict(asset.results.get("editorial_execution") or {}).get("cost_usd", 0.0),
                }
                for asset in assets
            ],
        }

    def _quality_score(self, quality: dict[str, object]) -> int:
        issues = list(quality.get("issues") or [])
        score = 100
        for item in issues:
            score -= 25 if item.get("severity") == "error" else 10
        if quality.get("passed", False):
            score = max(score, 80)
        return max(0, min(score, 100))

    def _min_quality_score(self) -> int | None:
        raw = (self.settings.auto_publish_min_quality_score or "").strip()
        if not raw:
            return None
        return int(raw)

    def _idempotency_key(self, campaign: CampaignRun, asset: ContentAsset) -> str:
        delay = max(0, int(self.settings.auto_publish_delay_minutes))
        scheduled_at = datetime.now(ZoneInfo(self.settings.editorial_timezone)) + timedelta(minutes=delay)
        seed = f"{campaign.id}:{asset.id}:{asset.content_hash}:{scheduled_at.isoformat()}"
        return f"auto-web-{sha256_hexdigest(seed)[:24]}"
