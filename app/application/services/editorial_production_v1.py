from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import yaml

from app.application.models.editorial_agents import StrictModel
from app.application.models.editorial_v1 import (
    EditorialArticle,
    EditorialBuilderSelection,
    EditorialGenerationContext,
    EditorialGenerationResult,
    EditorialSourceDescriptor,
    MapsiFeatureContext,
    OlingPracticeContext,
    ProductChangeContext,
)
from app.application.services.editorial_engine_v1 import EditorialGenerationService
from app.core.config import get_settings
from app.core.security import sha256_hexdigest
from app.domain.entities import CampaignRun, ContentAsset, EditorialBrief, ProductChange, SourceEvidence, utcnow
from app.domain.enums import AssetStatus, CampaignStatus
from app.domain.errors import EditorialGenerationBlockedError
from app.infrastructure.repositories.asset_revisions import AssetRevisionRepository
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
from app.infrastructure.repositories.editorial_pipeline import EditorialPipelineRepository
from app.knowledge import KnowledgeRepository
from app.knowledge.models import MapsiFeature, OlingPractice


ROOT = Path(__file__).resolve().parents[3]


class MapsiMarketBrief(StrictModel):
    selected_topic: str
    topic_key: str
    source_ids: list[str]
    objective: str


class OlingPracticeBrief(StrictModel):
    practice: str
    practice_id: str
    source_ids: list[str]
    business_problem: str


@dataclass
class MapsiMarketProductionBuildResult:
    brief: MapsiMarketBrief
    assets: list[ContentAsset]
    evaluations: dict[str, dict[str, object]]
    engine_mode: str


@dataclass
class OlingPracticeProductionBuildResult:
    brief: OlingPracticeBrief
    assets: list[ContentAsset]
    evaluations: dict[str, dict[str, object]]
    engine_mode: str


class EditorialPracticeConfig:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or ROOT / "config" / "editorial_practices.yaml"
        payload = yaml.safe_load(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.payload = payload or {}

    def all(self) -> dict[str, dict[str, object]]:
        return dict(self.payload.get("practices", {}))

    def get(self, practice_id: str) -> dict[str, object]:
        return dict(self.all().get(practice_id, {}))


class MapsiMarketProductionBuilder:
    def __init__(
        self,
        *,
        editorial_service: EditorialGenerationService,
        knowledge_repository: KnowledgeRepository,
        editorial_repository: EditorialPipelineRepository,
        campaign_repository: SqlAlchemyCampaignRepository,
    ) -> None:
        self.editorial_service = editorial_service
        self.knowledge_repository = knowledge_repository
        self.editorial_repository = editorial_repository
        self.campaign_repository = campaign_repository

    def build(
        self,
        *,
        weekly_pack_id: str = "",
        pilot_mode: bool = False,
        record_theme_history: bool = False,
        fallback_evidence_ids: list[str] | None = None,
    ) -> MapsiMarketProductionBuildResult:
        selection = self._select_topic(fallback_evidence_ids=fallback_evidence_ids or [])
        product_context = self._mapsi_context(selection, destination_site="mapsi.fr", article_type="MAPSI_PRODUCT")
        consulting_context = self._mapsi_context(selection, destination_site="oling.fr", article_type="MAPSI_CONSULTING")
        product_result = self.editorial_service.generate_from_context(context=product_context, selection=selection, allow_failed_quality=True)
        consulting_result = self.editorial_service.generate_from_context(context=consulting_context, selection=selection, allow_failed_quality=True)
        evaluations = {
            "mapsi_news_article": product_result.record.quality.model_dump(mode="json"),
            "oling_news_article": consulting_result.record.quality.model_dump(mode="json"),
        }
        if product_result.record.article.slug == consulting_result.record.article.slug:
            evaluations["oling_news_article"] = {
                **evaluations["oling_news_article"],
                "passed": False,
                "issues": [*evaluations["oling_news_article"].get("issues", []), {"code": "duplicate_slug", "message": "Consulting article must differ from product article.", "severity": "error"}],
            }
        if product_result.record.article.title == consulting_result.record.article.title:
            evaluations["oling_news_article"] = {
                **evaluations["oling_news_article"],
                "passed": False,
                "issues": [*evaluations["oling_news_article"].get("issues", []), {"code": "duplicate_title", "message": "Consulting article must differ from product article.", "severity": "error"}],
            }
        asset_product = self._asset_from_result(product_result, asset_type="mapsi_news_article", channel="mapsi_site", audience_segment_id="mapsi_product", extra_results={"weekly_pack_id": weekly_pack_id, "variant": "product"})
        asset_consulting = self._asset_from_result(consulting_result, asset_type="oling_news_article", channel="oling", audience_segment_id="mapsi_consulting", extra_results={"weekly_pack_id": weekly_pack_id, "variant": "consulting"})
        self._apply_quality_status(asset_product, evaluations["mapsi_news_article"])
        self._apply_quality_status(asset_consulting, evaluations["oling_news_article"])
        brief = MapsiMarketBrief(selected_topic=selection.topic, topic_key=selection.topic_key, source_ids=selection.source_ids, objective="market_visibility")
        if record_theme_history:
            self.editorial_repository.append_theme_history(selection.topic, "market_visibility", "mapsi_market")
        return MapsiMarketProductionBuildResult(
            brief=brief,
            assets=[asset_consulting, asset_product],
            evaluations=evaluations,
            engine_mode=get_settings().editorial_engine_mode,
        )

    def _select_topic(self, *, fallback_evidence_ids: list[str]) -> EditorialBuilderSelection:
        cutoff = date.today() - timedelta(days=180)
        changes = self.knowledge_repository.listMapsIProductChangesSince(cutoff)
        features = self.knowledge_repository.listMapsIFeatures()
        history = self.knowledge_repository.getPublishedTopicHistory(limit=40)
        recent_topics = {item.topic.casefold() for item in history}
        ranked: list[tuple[int, ProductChange, MapsiFeature]] = []
        for change in changes:
            if not change.eligible_for_communication or change.confidential or change.target_client_key or not change.deployment_proven:
                continue
            feature = self.editorial_service._select_mapsi_feature(features, change)
            if feature is None or not feature.communication_enabled:
                continue
            if feature.title.casefold() in recent_topics:
                continue
            score = 0
            collected_at = change.collected_at if change.collected_at.tzinfo is not None else change.collected_at.replace(tzinfo=UTC)
            score += max(0, 180 - (datetime.now(UTC) - collected_at).days)
            score += max(0, 50 - feature.communication_priority)
            score += len(feature.user_benefits) * 5
            ranked.append((score, change, feature))
        if ranked:
            ranked.sort(key=lambda item: item[0], reverse=True)
            _, change, feature = ranked[0]
            return EditorialBuilderSelection(
                topic_key=feature.feature_id,
                topic=feature.title,
                selection_type="product_change",
                source_ids=[f"knowledge:mapsi:feature:{feature.feature_id}", f"product_change:{change.id}"],
                rationale=[change.summary, feature.short_description],
            )
        for feature in sorted(features, key=lambda item: item.communication_priority):
            if not feature.communication_enabled or feature.title.casefold() in recent_topics:
                continue
            return EditorialBuilderSelection(
                topic_key=feature.feature_id,
                topic=feature.title,
                selection_type="feature_catalog",
                source_ids=[f"knowledge:mapsi:feature:{feature.feature_id}"],
                rationale=[feature.short_description],
            )
        if not fallback_evidence_ids:
            raise EditorialGenerationBlockedError("No communicable MAPSI market topic available.")
        raise EditorialGenerationBlockedError("No communicable MAPSI market topic available.")

    def _mapsi_context(self, selection: EditorialBuilderSelection, *, destination_site: str, article_type: str) -> EditorialGenerationContext:
        rules = self.knowledge_repository.getEditorialRules()
        feature = self.knowledge_repository.getMapsIFeature(selection.topic_key)
        if feature is None:
            raise EditorialGenerationBlockedError(f"Unknown MAPSI feature: {selection.topic_key}")
        changes = self.knowledge_repository.listMapsIProductChangesSince(date.today() - timedelta(days=180))
        related_changes = [change for change in changes if f"product_change:{change.id}" in selection.source_ids][:5]
        return EditorialGenerationContext(
            topic=feature.title,
            article_type=article_type,
            destination_site=destination_site,
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
                for change in related_changes
            ],
            published_topic_history=self.editorial_service._build_history(),
            sources=self.editorial_service._mapsi_sources(feature.feature_id, related_changes[0] if related_changes else ProductChange(summary=feature.title)),
        )

    def _asset_from_result(self, result: EditorialGenerationResult, *, asset_type: str, channel: str, audience_segment_id: str, extra_results: dict[str, object]) -> ContentAsset:
        evidences = self.editorial_service._build_source_evidences("pending", result.context.sources)
        evidence_ids = [item.id for item in evidences if item.payload.get("source_id") in result.record.article.source_ids]
        asset = ContentAsset(
            asset_type=asset_type,
            channel=channel,
            locale="fr-FR",
            title=result.record.article.title,
            subject="",
            content_html=result.record.article.body_html,
            content_text=result.record.article.body_text,
            excerpt=result.record.article.excerpt,
            call_to_action=result.record.article.call_to_action_label,
            target_url=result.record.article.call_to_action_url,
            source_evidence_ids=evidence_ids,
            audience_segment_id=audience_segment_id,
            status=AssetStatus.DRAFT,
            results={
                "editorial_article": result.record.article.model_dump(mode="json"),
                "editorial_quality": result.record.quality.model_dump(mode="json"),
                "editorial_execution": {
                    "model": result.record.model_name,
                    "prompt_version": result.record.prompt_version,
                    "knowledge_version": result.record.knowledge_version,
                    "input_hash": result.record.input_hash,
                    "output_hash": result.record.output_hash,
                    "tokens": {"input": result.record.input_tokens, "output": result.record.output_tokens, "total": result.record.total_tokens},
                    "cost_usd": result.record.estimated_cost_usd,
                    "duration_ms": result.record.duration_ms,
                    "provider_type": result.record.provider_type,
                    "mode": get_settings().editorial_engine_mode,
                },
                "builder_context": result.context.model_dump(mode="json"),
                "builder_selection": result.selection.model_dump(mode="json") if result.selection else {},
                **extra_results,
            },
        )
        asset.ensure_content_hash()
        return asset

    def _apply_quality_status(self, asset: ContentAsset, quality: dict[str, object]) -> None:
        asset.status = AssetStatus.READY_FOR_REVIEW if quality.get("passed") else AssetStatus.QUALITY_FAILED


class OlingPracticeProductionBuilder:
    def __init__(
        self,
        *,
        editorial_service: EditorialGenerationService,
        knowledge_repository: KnowledgeRepository,
        editorial_repository: EditorialPipelineRepository,
        campaign_repository: SqlAlchemyCampaignRepository,
        practice_config: EditorialPracticeConfig | None = None,
    ) -> None:
        self.editorial_service = editorial_service
        self.knowledge_repository = knowledge_repository
        self.editorial_repository = editorial_repository
        self.campaign_repository = campaign_repository
        self.practice_config = practice_config or EditorialPracticeConfig()

    def build(
        self,
        *,
        weekly_pack_id: str = "",
        pilot_mode: bool = False,
        record_theme_history: bool = False,
        fallback_evidence_ids: list[str] | None = None,
    ) -> OlingPracticeProductionBuildResult:
        selection, practice = self._select_practice()
        context = self._practice_context(practice)
        result = self.editorial_service.generate_from_context(context=context, selection=selection, allow_failed_quality=True)
        asset = MapsiMarketProductionBuilder._asset_from_result(self, result, asset_type="oling_news_article", channel="oling", audience_segment_id="oling_practice", extra_results={"weekly_pack_id": weekly_pack_id, "variant": "practice"})
        self._apply_quality_status(asset, result.record.quality.model_dump(mode="json"))
        brief = OlingPracticeBrief(practice=practice.title, practice_id=practice.practice_id, source_ids=selection.source_ids, business_problem=practice.common_client_problems[0])
        if record_theme_history:
            self.editorial_repository.append_theme_history(practice.title, "practice_visibility", "oling_practice")
        return OlingPracticeProductionBuildResult(
            brief=brief,
            assets=[asset],
            evaluations={"oling_news_article": result.record.quality.model_dump(mode="json")},
            engine_mode=get_settings().editorial_engine_mode,
        )

    def _select_practice(self) -> tuple[EditorialBuilderSelection, OlingPractice]:
        practices = {item.practice_id: item for item in self.knowledge_repository.listOlingPractices()}
        history = self.knowledge_repository.getPublishedTopicHistory(limit=40)
        recent_topics = {item.topic.casefold() for item in history}
        family_counts: dict[str, int] = {}
        for item in history[:8]:
            for practice_id, config in self.practice_config.all().items():
                practice = practices.get(practice_id)
                if practice and practice.title.casefold() == item.topic.casefold():
                    family = str(config.get("family", "general"))
                    family_counts[family] = family_counts.get(family, 0) + 1
        ranked: list[tuple[int, OlingPractice, dict[str, object]]] = []
        for practice_id, practice in practices.items():
            config = self.practice_config.get(practice_id)
            if config.get("enabled", True) is False:
                continue
            if practice.title.casefold() in recent_topics:
                continue
            if not practice.sources or not practice.mission_steps or not practice.allowed_ctas:
                continue
            family = str(config.get("family", "general"))
            priority = int(config.get("priority", 100))
            score = 200 - priority - (family_counts.get(family, 0) * 20) + len(practice.mission_steps) + len(practice.common_client_problems)
            ranked.append((score, practice, config))
        if not ranked:
            raise EditorialGenerationBlockedError("No communicable OLING practice topic available.")
        ranked.sort(key=lambda item: item[0], reverse=True)
        _, practice, config = ranked[0]
        selection = EditorialBuilderSelection(
            topic_key=practice.practice_id,
            topic=practice.title,
            selection_type="oling_practice",
            source_ids=[f"knowledge:oling:practice:{practice.practice_id}"],
            rationale=[str(config.get("family", "general")), practice.description],
        )
        return selection, practice

    def _practice_context(self, practice: OlingPractice) -> EditorialGenerationContext:
        rules = self.knowledge_repository.getEditorialRules()
        return EditorialGenerationContext(
            topic=practice.title,
            article_type="OLING_PRACTICE",
            destination_site="oling.fr",
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
        )

    def _asset_from_result(self, *args, **kwargs):
        return MapsiMarketProductionBuilder._asset_from_result(self, *args, **kwargs)

    def _apply_quality_status(self, *args, **kwargs):
        return MapsiMarketProductionBuilder._apply_quality_status(self, *args, **kwargs)


class EditorialAssetMutationService:
    def __init__(
        self,
        *,
        editorial_service: EditorialGenerationService,
        campaign_repository: SqlAlchemyCampaignRepository,
        revision_repository: AssetRevisionRepository,
        audit_repository,
    ) -> None:
        self.editorial_service = editorial_service
        self.campaign_repository = campaign_repository
        self.revision_repository = revision_repository
        self.audit_repository = audit_repository

    def regenerate(self, asset_id: str, *, actor: str, expected_version: int, instruction: str = "", desired_title: str = "", length_directive: str = "", angle_directive: str = "") -> ContentAsset:
        campaign, asset = self._find(asset_id)
        asset.assert_expected_version(expected_version)
        context_payload = dict(asset.results.get("builder_context") or {})
        if not context_payload:
            raise EditorialGenerationBlockedError("Missing builder context for asset regeneration.")
        self.revision_repository.snapshot_asset(asset)
        context_payload["rewrite_instruction"] = instruction
        context_payload["desired_title"] = desired_title
        context_payload["length_directive"] = length_directive
        context_payload["angle_directive"] = angle_directive
        context = EditorialGenerationContext.model_validate(context_payload)
        result = self.editorial_service.generate_from_context(context=context, allow_failed_quality=True)
        asset.update_draft(
            title=result.record.article.title,
            content_html=result.record.article.body_html,
            content_text=result.record.article.body_text,
            excerpt=result.record.article.excerpt,
            call_to_action=result.record.article.call_to_action_label,
            target_url=result.record.article.call_to_action_url,
        )
        asset.results = {
            **asset.results,
            "editorial_article": result.record.article.model_dump(mode="json"),
            "editorial_quality": result.record.quality.model_dump(mode="json"),
            "editorial_execution": {
                "model": result.record.model_name,
                "prompt_version": result.record.prompt_version,
                "knowledge_version": result.record.knowledge_version,
                "input_hash": result.record.input_hash,
                "output_hash": result.record.output_hash,
                "tokens": {"input": result.record.input_tokens, "output": result.record.output_tokens, "total": result.record.total_tokens},
                "cost_usd": result.record.estimated_cost_usd,
                "duration_ms": result.record.duration_ms,
                "provider_type": result.record.provider_type,
                "mode": get_settings().editorial_engine_mode,
            },
            "builder_context": context.model_dump(mode="json"),
        }
        asset.status = AssetStatus.READY_FOR_REVIEW if result.record.quality.passed else AssetStatus.QUALITY_FAILED
        campaign.status = CampaignStatus.READY_FOR_REVIEW if any(item.status is AssetStatus.READY_FOR_REVIEW for item in campaign.content_assets) else CampaignStatus.FAILED
        saved = self.campaign_repository.save(campaign)
        refreshed = next(item for item in saved.content_assets if item.id == asset.id)
        self.audit_repository.append(campaign.id, "review.asset_regenerated", {"asset_id": asset.id, "instruction": instruction, "desired_title": desired_title, "length_directive": length_directive, "angle_directive": angle_directive}, actor_id=actor, actor_source="studio_admin")
        return refreshed

    def _find(self, asset_id: str) -> tuple[CampaignRun, ContentAsset]:
        for campaign in self.campaign_repository.list():
            for asset in campaign.content_assets:
                if asset.id == asset_id:
                    return campaign, asset
        raise EditorialGenerationBlockedError(f"Asset {asset_id} not found.")
