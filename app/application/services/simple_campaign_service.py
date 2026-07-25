from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from app.application.models.editorial_v1 import (
    EditorialBuilderSelection,
    EditorialGenerationContext,
    EditorialGenerationResult,
    MapsiFeatureContext,
    OlingPracticeContext,
    ProductChangeContext,
)
from app.application.ports.audit import AuditLogPort
from app.application.ports.connectors import PublisherPort
from app.application.ports.repositories import CampaignRepositoryPort
from app.application.ports.tasks import TaskQueuePort
from app.application.services.editorial_engine_v1 import EditorialGenerationService
from app.domain.entities import CampaignRun, ContentAsset, EditorialBrief, ProductChange, Publication, SourceEvidence
from app.domain.enums import AssetStatus
from app.domain.errors import CampaignNotFoundError, CampaignPublicationForbiddenError, InvalidStateTransitionError
from app.knowledge import KnowledgeRepository
from app.knowledge.models import MapsiFeature, OlingPractice


SIMPLE_WORKFLOW_KIND = "SIMPLE"
SIMPLE_CAMPAIGN_TYPES = {"MAPSI_USERS", "MAPSI_MARKETING", "OLING"}
SIMPLE_CHANNEL_RULES: dict[str, set[str]] = {
    "MAPSI_USERS": {"mapsi_site", "linkedin_manual"},
    "MAPSI_MARKETING": {"mapsi_site", "oling_site", "linkedin_manual"},
    "OLING": {"oling_site", "linkedin_manual"},
}
CHANNEL_TO_INTERNAL = {
    "mapsi_site": "mapsi_site",
    "oling_site": "oling",
    "linkedin_manual": "linkedin_manual",
}
CHANNEL_FROM_INTERNAL = {value: key for key, value in CHANNEL_TO_INTERNAL.items()}


@dataclass
class CreateSimpleCampaignCommand:
    name: str
    campaign_type: str
    selected_channels: list[str]
    theme: str = ""


@dataclass
class UpdateSimpleAssetCommand:
    title: str | None = None
    content_html: str | None = None
    content_text: str | None = None
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
    ) -> None:
        self.repository = repository
        self.publisher = publisher
        self.audit_log = audit_log
        self.task_queue = task_queue
        self.project_root = project_root
        self.editorial_service = editorial_service
        self.knowledge_repository = knowledge_repository

    def create_campaign(self, command: CreateSimpleCampaignCommand) -> CampaignRun:
        campaign_type = command.campaign_type.strip().upper()
        self._validate_campaign_type(campaign_type)
        selected_channels = self._normalize_selected_channels(campaign_type, command.selected_channels)
        theme = self._resolve_theme(campaign_type, command.theme)
        campaign = CampaignRun(
            name=command.name.strip(),
            objective=theme,
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

    def list_campaigns(self) -> list[CampaignRun]:
        return [campaign for campaign in self.repository.list() if campaign.workflow_kind == SIMPLE_WORKFLOW_KIND]

    def get_campaign(self, campaign_id: str) -> CampaignRun:
        campaign = self.repository.get(campaign_id)
        if campaign is None:
            raise CampaignNotFoundError(f"Campaign {campaign_id} not found.")
        self._assert_simple_campaign(campaign)
        return campaign

    def generate_campaign(self, campaign_id: str) -> CampaignRun:
        campaign = self.get_campaign(campaign_id)
        self._assert_simple_campaign(campaign)
        brief, assets, evidence = self._build_generation_payload(campaign)
        campaign.source_evidences = evidence
        campaign.mark_generated(brief, assets)
        for asset in campaign.content_assets:
            asset.approve("studio-simple")
        campaign._sync_status_from_assets()
        saved = self.repository.save(campaign)
        self.audit_log.append(
            saved.id,
            "simple_campaign.generated",
            {"asset_count": len(saved.content_assets), "channels": saved.selected_channels},
            actor_source="studio-simple",
            previous_state={"status": "DRAFT"},
            new_state={"status": saved.status.value},
            result="SUCCESS",
        )
        return saved

    def _build_generation_payload(self, campaign: CampaignRun) -> tuple[EditorialBrief, list[ContentAsset], list[SourceEvidence]]:
        if self.editorial_service is None or self.knowledge_repository is None:
            brief = EditorialBrief(
                campaign_run_id=campaign.id,
                title=f"{campaign.name} - {campaign.theme}",
                summary=f"Campagne {campaign.campaign_type} sur le theme {campaign.theme}.",
            )
            evidence = self._build_evidence(campaign)
            assets = self._build_assets(campaign, evidence)
            return brief, assets, evidence

        results: dict[str, EditorialGenerationResult] = {}
        if "mapsi_site" in campaign.selected_channels:
            results["mapsi_site"] = self.editorial_service.generate_from_context(
                context=self._build_mapsi_context(campaign, destination_site="mapsi.fr", article_type="MAPSI_PRODUCT"),
                selection=self._mapsi_selection(campaign),
                allow_failed_quality=True,
            )
        if "oling_site" in campaign.selected_channels:
            if campaign.campaign_type == "OLING":
                results["oling_site"] = self.editorial_service.generate_from_context(
                    context=self._build_oling_context(campaign),
                    selection=self._oling_selection(campaign),
                    allow_failed_quality=True,
                )
            else:
                results["oling_site"] = self.editorial_service.generate_from_context(
                    context=self._build_mapsi_context(campaign, destination_site="oling.fr", article_type="MAPSI_CONSULTING"),
                    selection=self._mapsi_selection(campaign),
                    allow_failed_quality=True,
                )

        primary_result = results.get("mapsi_site") or results.get("oling_site")
        if primary_result is None:
            primary_result = self.editorial_service.generate_from_context(
                context=self._fallback_context_for_linkedin_only(campaign),
                allow_failed_quality=True,
            )

        evidence = self._collect_editorial_evidence(campaign.id, [result.context for result in [*results.values(), primary_result]])
        assets: list[ContentAsset] = []
        if "mapsi_site" in results:
            assets.append(self._asset_from_editorial_result(campaign, "mapsi_site", results["mapsi_site"], evidence))
        if "oling_site" in results:
            assets.append(self._asset_from_editorial_result(campaign, "oling_site", results["oling_site"], evidence))
        if "linkedin_manual" in campaign.selected_channels:
            assets.append(self._linkedin_asset_from_editorial(campaign, primary_result, evidence))
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
            content_html=command.content_html,
            content_text=command.content_text,
        )
        asset.approve("studio-simple")
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

    def publish_campaign(self, campaign_id: str, command: PublishSimpleCampaignCommand) -> CampaignRun:
        campaign = self.get_campaign(campaign_id)
        self._assert_simple_campaign(campaign)
        channels = self._normalize_selected_channels(campaign.campaign_type, command.channels)
        for channel in channels:
            internal_channel = CHANNEL_TO_INTERNAL[channel]
            assets = [
                asset
                for asset in campaign.content_assets
                if asset.channel == internal_channel and asset.status in {AssetStatus.APPROVED, AssetStatus.FAILED}
            ]
            if not assets:
                raise CampaignPublicationForbiddenError(
                    f"Campaign {campaign.id} has no READY asset for channel {channel}."
                )
            for asset in assets:
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

    def list_oling_themes(self) -> list[str]:
        practices_dir = self.project_root / "knowledge" / "oling" / "practices"
        return sorted(path.stem for path in practices_dir.glob("*.md"))

    def external_channel(self, channel: str) -> str:
        return CHANNEL_FROM_INTERNAL.get(channel, channel)

    def simple_status(self, campaign: CampaignRun) -> str:
        if campaign.status.value == "DRAFT":
            return "DRAFT"
        if campaign.status.value in {"PUBLISHED", "PARTIALLY_PUBLISHED"}:
            return campaign.status.value
        if campaign.status.value == "FAILED":
            return "ERROR"
        return "READY"

    def simple_asset_status(self, asset: ContentAsset) -> str:
        if asset.status is AssetStatus.PUBLISHED:
            return "PUBLISHED"
        if asset.status is AssetStatus.FAILED:
            return "ERROR"
        if asset.status is AssetStatus.DRAFT:
            return "DRAFT"
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
            rewrite_instruction=(
                "Produire un article de conseil OLING a forte valeur editoriale, structure, demonstration, nuances et "
                "credibilite terrain. Eviter les formulations creuses ou generiques."
            ),
            desired_title=campaign.theme,
            length_directive="longer",
            angle_directive=f"Traiter le theme libre utilisateur suivant avec la practice {practice.title}: {campaign.theme}",
        )

    def _fallback_context_for_linkedin_only(self, campaign: CampaignRun) -> EditorialGenerationContext:
        if campaign.campaign_type == "OLING":
            return self._build_oling_context(campaign)
        return self._build_mapsi_context(campaign, destination_site="mapsi.fr", article_type="MAPSI_PRODUCT")

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
            content_html=article.body_html,
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
        body = self._build_linkedin_from_article(campaign, article)
        asset = ContentAsset(
            campaign_run_id=campaign.id,
            asset_type="linkedin_manual_post",
            channel=CHANNEL_TO_INTERNAL["linkedin_manual"],
            locale="fr-FR",
            title="Publication manuelle LinkedIn",
            content_text=body,
            excerpt=self._editorial_image_suggestion(campaign, article),
            audience_segment_id=campaign.campaign_type.casefold(),
            source_evidence_ids=evidence_ids,
            evidence_ids=evidence_ids,
            results={
                "source_article": article.model_dump(mode="json"),
                "illustration_suggestion": self._editorial_image_suggestion(campaign, article),
            },
        )
        asset.ensure_content_hash()
        return asset

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
            return "Ton recommande : valeur, clarte, demonstration par les usages et la execution."
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
