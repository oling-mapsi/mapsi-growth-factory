from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.application.models.editorial_agents import MapsiUserWeeklyEmailContent
from app.application.services.audience_segmentation_service import AudienceSegmentationService
from app.core.security import sha256_hexdigest
from app.domain.entities import AudienceFact, ContentAsset, FeatureCommunicationCatalogEntry
from app.domain.enums import AssetStatus
from app.domain.errors import EditorialGenerationBlockedError
from app.infrastructure.repositories.editorial_pipeline import EditorialPipelineRepository
from app.infrastructure.repositories.feature_communication_catalog import FeatureCommunicationCatalogRepository
from app.infrastructure.repositories.mapsi_usage import MapsiUsageRepository


@dataclass
class MapsiUserWeeklyEmailBuildResult:
    content: MapsiUserWeeklyEmailContent
    asset: ContentAsset
    evaluations: dict[str, dict[str, object]]
    engine_mode: str = "simulated"


class MapsiUserWeeklyEmailBuilder:
    def __init__(
        self,
        *,
        editorial_repository: EditorialPipelineRepository,
        catalog_repository: FeatureCommunicationCatalogRepository,
        segmentation_service: AudienceSegmentationService,
        mapsi_usage_repository: MapsiUsageRepository,
    ) -> None:
        self.editorial_repository = editorial_repository
        self.catalog_repository = catalog_repository
        self.segmentation_service = segmentation_service
        self.mapsi_usage_repository = mapsi_usage_repository

    def build(
        self,
        *,
        pilot_mode: bool = False,
        record_theme_history: bool = False,
        fallback_evidence_ids: list[str] | None = None,
    ) -> MapsiUserWeeklyEmailBuildResult:
        theme_history = self.editorial_repository.list_theme_history()
        segment_contexts = self._segment_contexts()
        capabilities = self._capability_index()
        selection = self._select_topic(theme_history, segment_contexts, capabilities, fallback_evidence_ids or [])
        content = self._build_content(selection, pilot_mode=pilot_mode)
        asset = self._build_asset(content, pilot_mode=pilot_mode)
        evaluations = self._evaluate(content, asset, pilot_mode=pilot_mode)
        if not all(item.get("passed", False) for item in evaluations.values()):
            failed = [name for name, item in evaluations.items() if not item.get("passed", False)]
            raise EditorialGenerationBlockedError(f"MAPSI users email quality failed: {failed}")
        if record_theme_history:
            self.editorial_repository.append_theme_history(content.title, content.email_type.casefold(), content.target_segment_id)
            if selection.get("catalog_entry") is not None:
                self.catalog_repository.mark_communicated(selection["catalog_entry"].feature_id, datetime.now(UTC))
        return MapsiUserWeeklyEmailBuildResult(content=content, asset=asset, evaluations=evaluations)

    def _segment_contexts(self) -> list[dict[str, object]]:
        facts = {fact.membership_id: fact for fact in self.segmentation_service.repository.list_audience_facts()}
        contexts: list[dict[str, object]] = []
        for segment in self.segmentation_service.list_segments(enabled_only=True):
            preview = self.segmentation_service.preview_segment(segment.id, persist=False)
            included = [facts[audit.membership_id] for audit in preview.audits if audit.included and audit.membership_id in facts]
            contexts.append({"segment": segment, "preview": preview, "facts": included})
        return contexts

    def _capability_index(self) -> dict[str, dict[str, str]]:
        instance_lookup = {instance.id: instance.instance_key for instance in self.mapsi_usage_repository.list_instances()}
        capabilities: dict[str, dict[str, str]] = {}
        for item in self.mapsi_usage_repository.list_capabilities():
            instance_key = instance_lookup.get(item.mapsi_instance_id, "")
            if not instance_key or not item.enabled:
                continue
            capabilities.setdefault(instance_key, {})[item.capability_key] = item.version
        return capabilities

    def _select_topic(
        self,
        theme_history: list[dict],
        segment_contexts: list[dict[str, object]],
        capabilities: dict[str, dict[str, str]],
        fallback_evidence_ids: list[str],
    ) -> dict[str, object]:
        recent_topics = {str(item["topic"]).casefold() for item in theme_history}
        product_selection = self._select_product_change(recent_topics, segment_contexts, capabilities)
        if product_selection is not None:
            return product_selection
        catalog_selection = self._select_catalog_entry(recent_topics, segment_contexts, capabilities)
        if catalog_selection is not None:
            return catalog_selection
        if not fallback_evidence_ids:
            raise EditorialGenerationBlockedError("No MAPSI user weekly email topic available.")
        return {
            "email_type": "TIP",
            "title": "Astuce MAPSI de la semaine",
            "segment_id": "all_eligible_active_users",
            "source_evidence_ids": list(fallback_evidence_ids[:2]),
            "introduction": "Une action simple peut faciliter l'usage quotidien de MAPSI.",
            "main_tip": "Commencez par le module le plus utile pour votre priorite du moment.",
            "steps": [
                "Ouvrez votre module principal dans MAPSI.",
                "Verifiez les informations a jour.",
                "Enregistrez un premier usage simple cette semaine.",
            ],
            "expected_benefit": "Prendre rapidement de meilleurs reperes dans MAPSI.",
            "call_to_action": "Ouvrir MAPSI",
            "deep_link": "",
            "selection_kind": "generic_fallback",
        }

    def _select_product_change(self, recent_topics: set[str], segment_contexts: list[dict[str, object]], capabilities: dict[str, dict[str, str]]) -> dict[str, object] | None:
        candidates: list[tuple[int, dict[str, object]]] = []
        for change in self.editorial_repository.list_communicable_product_changes():
            topic = f"{change['capability_key']} {change['summary']}"
            if topic.casefold() in recent_topics:
                continue
            for context in segment_contexts:
                facts = list(context["facts"])
                preview = context["preview"]
                if not facts:
                    continue
                if not self._available_for_facts(change["capability_key"], facts, capabilities):
                    continue
                score = int(preview.eligible_volume) + len(change["evidences"]) * 10
                if context["segment"].id == "all_eligible_active_users":
                    score += 15
                candidates.append(
                    (
                        score,
                        {
                            "email_type": "NEW_FEATURE",
                            "title": change["summary"],
                            "segment_id": context["segment"].id,
                            "source_evidence_ids": [item["evidence_id"] for item in change["evidences"]],
                            "capability_key": change["capability_key"],
                            "change_summary": change["summary"],
                            "selection_kind": "product_change",
                        },
                    )
                )
        if not candidates:
            return None
        return sorted(candidates, key=lambda item: item[0], reverse=True)[0][1]

    def _select_catalog_entry(
        self,
        recent_topics: set[str],
        segment_contexts: list[dict[str, object]],
        capabilities: dict[str, dict[str, str]],
    ) -> dict[str, object] | None:
        now = datetime.now(UTC)
        candidates: list[tuple[int, dict[str, object]]] = []
        for entry in self.catalog_repository.list_enabled():
            if entry.title.casefold() in recent_topics:
                continue
            last_communicated_at = entry.last_communicated_at
            if last_communicated_at and last_communicated_at.tzinfo is None:
                last_communicated_at = last_communicated_at.replace(tzinfo=UTC)
            if last_communicated_at and last_communicated_at + timedelta(days=entry.minimum_repeat_delay) > now:
                continue
            for context in segment_contexts:
                facts = list(context["facts"])
                preview = context["preview"]
                segment = context["segment"]
                if not facts:
                    continue
                if entry.target_roles and not any(fact.role_key in entry.target_roles for fact in facts):
                    continue
                if entry.target_modules and not any(module in fact.module_keys for fact in facts for module in entry.target_modules):
                    continue
                if not self._catalog_available(entry, facts, capabilities):
                    continue
                score = 200 - entry.communication_priority + int(preview.eligible_volume)
                if entry.target_roles:
                    matching_roles = sum(count for role, count in preview.role_distribution.items() if role in entry.target_roles)
                    score += matching_roles * 50
                    if preview.role_distribution and set(preview.role_distribution).issubset(set(entry.target_roles)):
                        score += 100
                    if any(condition.field == "role_key" for condition in segment.conditions_all + segment.conditions_any):
                        score += 200
                if entry.target_modules:
                    matching_modules = sum(count for module, count in preview.module_distribution.items() if module in entry.target_modules)
                    score += matching_modules * 20
                    if any(
                        condition.field == "module_keys" or condition.field.startswith("module_events.")
                        for condition in segment.conditions_all + segment.conditions_any
                    ):
                        score += 80
                if entry.target_roles or entry.target_modules:
                    score += 10
                candidates.append(
                    (
                        score,
                        {
                            "email_type": self._catalog_email_type(entry, context["segment"].id),
                            "title": entry.title,
                            "segment_id": context["segment"].id,
                            "source_evidence_ids": list(entry.source_evidence_ids),
                            "catalog_entry": entry,
                            "selection_kind": "catalog",
                            "facts": facts,
                        },
                    )
                )
        if not candidates:
            return None
        return sorted(candidates, key=lambda item: item[0], reverse=True)[0][1]

    def _available_for_facts(self, capability_key: str, facts: list[AudienceFact], capabilities: dict[str, dict[str, str]]) -> bool:
        instance_keys = {fact.instance_key for fact in facts}
        return bool(instance_keys) and all(capability_key in capabilities.get(instance_key, {}) for instance_key in instance_keys)

    def _catalog_available(self, entry: FeatureCommunicationCatalogEntry, facts: list[AudienceFact], capabilities: dict[str, dict[str, str]]) -> bool:
        if not entry.target_modules and not entry.module:
            return True
        required_keys = set(entry.target_modules or ([entry.module] if entry.module else []))
        instance_keys = {fact.instance_key for fact in facts}
        return bool(instance_keys) and all(any(key in capabilities.get(instance_key, {}) for key in required_keys) for instance_key in instance_keys)

    def _catalog_email_type(self, entry: FeatureCommunicationCatalogEntry, segment_id: str) -> str:
        if segment_id == "new_users_14_days":
            return "ONBOARDING"
        if segment_id in {"inactive_30_days", "inactive_60_days"}:
            return "REACTIVATION"
        if entry.communication_priority <= 20:
            return "FEATURE_REMINDER"
        if "workflow" in entry.title.casefold():
            return "WORKFLOW_GUIDE"
        return "TIP"

    def _build_content(self, selection: dict[str, object], *, pilot_mode: bool) -> MapsiUserWeeklyEmailContent:
        title = str(selection["title"])
        email_type = str(selection["email_type"])
        segment_id = str(selection["segment_id"])
        deep_link = self._deep_link(selection)
        if selection["selection_kind"] == "product_change":
            subject = f"{'[PILOT] ' if pilot_mode else ''}Nouvelle fonctionnalite MAPSI : {title}"
            preheader = "Une nouveaute utile a tester cette semaine dans MAPSI."
            introduction = f"Cette semaine, MAPSI evolue avec une nouveaute autour de {title.casefold()}."
            main_tip = f"Utilisez {title} pour gagner en clarte sur votre usage quotidien."
            steps = [
                "Ouvrez MAPSI depuis votre espace habituel.",
                f"Reperez la fonctionnalite {title}.",
                "Testez-la sur un cas simple cette semaine.",
            ]
            expected_benefit = "Mieux utiliser MAPSI avec une fonctionnalite deja disponible pour votre environnement."
            cta = "Ouvrir la fonctionnalite"
        elif selection["selection_kind"] == "catalog":
            entry: FeatureCommunicationCatalogEntry = selection["catalog_entry"]
            subject = f"{'[PILOT] ' if pilot_mode else ''}{entry.title}"
            preheader = entry.user_benefit
            introduction = entry.functional_description
            main_tip = entry.user_benefit
            steps = [
                f"Allez dans le module {entry.module}.",
                "Appliquez cette action sur un premier cas simple.",
                "Verifiez le resultat dans votre workflow habituel.",
            ]
            expected_benefit = entry.user_benefit
            cta = "Ouvrir MAPSI"
        else:
            subject = f"{'[PILOT] ' if pilot_mode else ''}Astuce MAPSI de la semaine"
            preheader = "Une seule action pour mieux utiliser MAPSI."
            introduction = str(selection["introduction"])
            main_tip = str(selection["main_tip"])
            steps = list(selection["steps"])
            expected_benefit = str(selection["expected_benefit"])
            cta = str(selection["call_to_action"])
        footer_html = "<p style='font-size:12px;color:#666'>Vous pouvez vous opposer a ces communications via votre provider.</p>"
        footer_text = "Vous pouvez vous opposer a ces communications via votre provider."
        body_html = (
            f"<h1>{title}</h1>"
            f"<p>{introduction}</p>"
            f"<p><strong>Idee principale :</strong> {main_tip}</p>"
            f"<ol>{''.join(f'<li>{step}</li>' for step in steps)}</ol>"
            f"<p><strong>Benefice attendu :</strong> {expected_benefit}</p>"
            f"<p><strong>CTA :</strong> {cta}</p>"
            f"{footer_html}"
        )
        body_text = "\n".join([title, introduction, f"Idee principale : {main_tip}", *[f"{index}. {step}" for index, step in enumerate(steps, start=1)], f"Benefice attendu : {expected_benefit}", f"CTA : {cta}", footer_text])
        return MapsiUserWeeklyEmailContent(
            email_type=email_type,  # type: ignore[arg-type]
            subject=subject,
            preheader=preheader,
            title=title,
            introduction=introduction,
            main_tip=main_tip,
            steps=steps,
            expected_benefit=expected_benefit,
            call_to_action=cta,
            deep_link=deep_link,
            body_html=body_html,
            body_text=body_text,
            source_evidence_ids=list(selection["source_evidence_ids"]),
            target_segment_id=segment_id,
        )

    def _deep_link(self, selection: dict[str, object]) -> str:
        if selection.get("selection_kind") != "catalog":
            return ""
        entry: FeatureCommunicationCatalogEntry = selection["catalog_entry"]
        if not entry.deep_link_template:
            return ""
        facts: list[AudienceFact] = list(selection.get("facts") or [])
        instance_keys = {fact.instance_key for fact in facts}
        if len(instance_keys) != 1:
            return ""
        return entry.deep_link_template.replace("{instance_key}", next(iter(instance_keys)))

    def _build_asset(self, content: MapsiUserWeeklyEmailContent, *, pilot_mode: bool) -> ContentAsset:
        asset = ContentAsset(
            asset_type="mapsi_user_email",
            channel="mapsi_users",
            locale="fr-FR",
            title=content.title,
            subject=content.subject,
            content_html=content.body_html,
            content_text=content.body_text,
            excerpt=content.preheader,
            call_to_action=content.call_to_action,
            target_url=content.deep_link,
            source_evidence_ids=list(content.source_evidence_ids),
            audience_segment_id=content.target_segment_id,
            status=AssetStatus.READY_FOR_REVIEW,
            results={
                "email_type": content.email_type,
                "preheader": content.preheader,
                "main_tip": content.main_tip,
                "steps": list(content.steps),
                "pilot_allowlist_only": pilot_mode,
                "test_email": pilot_mode,
                "preview_html_available": True,
                "preview_text_available": True,
                "auto_send_enabled": False,
            },
        )
        asset.content_hash = sha256_hexdigest(f"{content.subject}|{content.body_html}|{content.body_text}|{','.join(content.source_evidence_ids)}|{content.target_segment_id}")
        return asset

    def _evaluate(self, content: MapsiUserWeeklyEmailContent, asset: ContentAsset, *, pilot_mode: bool) -> dict[str, dict[str, object]]:
        return {
            "single_main_idea": {"passed": len(content.steps) <= 3 and bool(content.main_tip)},
            "no_aggressive_marketing": {"passed": all(token not in content.subject.casefold() for token in ("urgent", "promo", "offre"))},
            "no_personal_data": {"passed": "@" not in content.body_text and "utilisateur " not in content.body_text.casefold()},
            "cta_present": {"passed": bool(content.call_to_action)},
            "unsubscribe_notice": {"passed": "opposer" in content.body_text.casefold() or "desabonnement" in content.body_text.casefold()},
            "preview_modes": {"passed": bool(asset.content_html) and bool(asset.content_text)},
            "pilot_rules": {"passed": (not pilot_mode) or (asset.results.get("pilot_allowlist_only") and asset.results.get("test_email"))},
        }
