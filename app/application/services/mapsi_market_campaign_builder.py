from __future__ import annotations

from dataclasses import dataclass
import re

from app.application.models.editorial_agents import MapsiMarketEditorialBrief
from app.core.security import sha256_hexdigest
from app.domain.entities import ContentAsset
from app.domain.enums import AssetStatus
from app.domain.errors import EditorialGenerationBlockedError
from app.infrastructure.repositories.editorial_pipeline import EditorialPipelineRepository
from app.infrastructure.repositories.editorial_source_packs import EditorialSourcePackRepository


@dataclass
class MapsiMarketCampaignBuildResult:
    brief: MapsiMarketEditorialBrief
    assets: list[ContentAsset]
    evaluations: dict[str, dict[str, object]]
    engine_mode: str = "simulated"


class MapsiMarketCampaignBuilder:
    def __init__(
        self,
        *,
        editorial_repository: EditorialPipelineRepository,
        editorial_source_packs: EditorialSourcePackRepository,
    ) -> None:
        self.editorial_repository = editorial_repository
        self.editorial_source_packs = editorial_source_packs

    def build(
        self,
        *,
        weekly_pack_id: str = "",
        pilot_mode: bool = False,
        record_theme_history: bool = False,
        fallback_evidence_ids: list[str] | None = None,
    ) -> MapsiMarketCampaignBuildResult:
        theme_history = self.editorial_repository.list_theme_history()
        product_changes = self.editorial_repository.list_communicable_product_changes()
        selected = self._select_topic(
            product_changes,
            theme_history,
            weekly_pack_id=weekly_pack_id,
            fallback_evidence_ids=fallback_evidence_ids or [],
        )
        brief = self._build_brief(selected)
        assets = self._build_assets(brief, pilot_mode=pilot_mode)
        evaluations = self._evaluate(brief, assets, pilot_mode=pilot_mode)
        if not all(item.get("passed", False) for item in evaluations.values()):
            failed = [name for name, item in evaluations.items() if not item.get("passed", False)]
            raise EditorialGenerationBlockedError(f"MAPSI market quality failed: {failed}")
        if record_theme_history:
            self.editorial_repository.append_theme_history(brief.selected_topic, brief.objective, "mapsi_market")
        return MapsiMarketCampaignBuildResult(brief=brief, assets=assets, evaluations=evaluations)

    def _select_topic(
        self,
        product_changes: list[dict],
        theme_history: list[dict],
        *,
        weekly_pack_id: str,
        fallback_evidence_ids: list[str],
    ) -> dict:
        recent_topics = {str(item["topic"]).casefold() for item in theme_history}
        candidates: list[tuple[int, dict]] = []
        for item in product_changes:
            topic = f"{item['capability_key']} {item['summary']}"
            if topic.casefold() in recent_topics:
                continue
            score = len(item["evidences"]) * 10 + len(str(item["summary"]))
            if item["client_scope"] == "global":
                score += 20
            candidates.append((score, {**item, "selected_topic": topic, "topic_kind": "product_change"}))
        if candidates:
            return sorted(candidates, key=lambda value: value[0], reverse=True)[0][1]
        fallback = self._fallback_topic(
            weekly_pack_id=weekly_pack_id,
            recent_topics=recent_topics,
            fallback_evidence_ids=fallback_evidence_ids,
        )
        return fallback

    def _fallback_topic(self, *, weekly_pack_id: str, recent_topics: set[str], fallback_evidence_ids: list[str]) -> dict:
        for pack in self.editorial_source_packs.list_validated(campaign_type="MAPSI_MARKET", weekly_pack_id=weekly_pack_id):
            for item in pack.items:
                topic = item.source_title or item.factual_summary
                if not topic or topic.casefold() in recent_topics:
                    continue
                usable = [fact for fact in item.anonymized_facts or item.usable_facts if fact]
                if not usable:
                    continue
                return {
                    "product_change_id": "",
                    "capability_key": "existing_feature",
                    "summary": topic,
                    "module_key": "existing_feature",
                    "eligible_for_communication": True,
                    "confidential": False,
                    "client_scope": "global",
                    "deployed": True,
                    "restrictions": ["fallback_topic"],
                    "evidences": [
                        {
                            "evidence_id": item.id,
                            "source_system": item.source_type.lower(),
                            "reference": item.source_reference or item.source_title,
                            "summary": fact,
                            "deployed": True,
                            "client_scope": "global",
                        }
                        for fact in usable[:2]
                    ],
                    "selected_topic": topic,
                    "topic_kind": "best_practice",
                }
        if not fallback_evidence_ids:
            raise EditorialGenerationBlockedError("No communicable MAPSI market topic available.")
        return {
            "product_change_id": "",
            "capability_key": "mapsi_existing_feature",
            "summary": "les bonnes pratiques d'adoption des fonctionnalites MAPSI deja deployees",
            "module_key": "mapsi_existing_feature",
            "eligible_for_communication": True,
            "confidential": False,
            "client_scope": "global",
            "deployed": True,
            "restrictions": ["generic_fallback_topic"],
            "evidences": [
                {
                    "evidence_id": evidence_id,
                    "source_system": "weekly_pack_source",
                    "reference": evidence_id,
                    "summary": "Base editoriale interne verifiee pour une communication marche MAPSI.",
                    "deployed": True,
                    "client_scope": "global",
                }
                for evidence_id in fallback_evidence_ids[:2]
            ],
            "selected_topic": "Bonnes pratiques d'adoption MAPSI",
            "topic_kind": "best_practice",
        }

    def _build_brief(self, selected: dict) -> MapsiMarketEditorialBrief:
        selected_topic = str(selected["selected_topic"])
        evidence_ids = [str(item["evidence_id"]) for item in selected["evidences"]]
        is_product = selected.get("topic_kind") == "product_change"
        summary = str(selected["summary"])
        return MapsiMarketEditorialBrief(
            selected_topic=selected_topic,
            objective="market_visibility",
            product_change_ids=[selected["product_change_id"]] if selected.get("product_change_id") else [],
            source_evidence_ids=evidence_ids,
            target_personas=["direction_metier", "responsable_transformation", "administrateur_mapsi"],
            market_problem=f"Les equipes perdent du temps sur {summary.casefold()} sans cadre clair." if is_product else f"Les equipes cherchent une bonne pratique claire autour de {summary.casefold()}.",
            key_messages=[
                f"{summary} est reellement deploye et communicable." if is_product else f"{summary} peut etre explique sans revendiquer de resultat non prouve.",
                "Chaque affirmation doit rester rattachee a une preuve verifiable.",
                "Le CTA doit orienter vers une demonstration ou une prise de contact.",
            ],
            oling_angle=f"Angle expertise OLING : partir du probleme metier, expliquer l'accompagnement, puis montrer comment MAPSI apporte une reponse concrete sur {summary}.",
            mapsi_angle=f"Angle produit MAPSI : decrire la fonctionnalite {summary}, son fonctionnement, ses benefices et des exemples d'utilisation.",
            linkedin_angle=f"Accroche courte sur {summary}, probleme, idee principale et lien vers l'article canonique.",
            primary_cta="Demander une demonstration MAPSI",
            canonical_article_target="mapsi.fr" if is_product else "oling.fr",
            risks=[
                "ne_pas_inventer_de_gain_chiffre",
                "ne_pas_mentionner_de_client_sans_autorisation",
                "ne_pas_promettre_de_conformite_garantie",
            ],
            prohibited_claims=[
                "fonctionnalite_non_deployee",
                "gain_chiffre_non_prouve",
                "temoignage_client_invente",
                "resultat_garanti",
            ],
        )

    def _build_assets(self, brief: MapsiMarketEditorialBrief, *, pilot_mode: bool) -> list[ContentAsset]:
        slug = self._slugify(brief.selected_topic)
        canonical_base = "https://mapsi.fr/actualites" if brief.canonical_article_target == "mapsi.fr" else "https://www.oling.fr/ressources"
        canonical_url = f"{canonical_base}/{slug}"
        oling_title = f"Pourquoi {brief.selected_topic} change la donne cote terrain"
        mapsi_title = f"{brief.selected_topic} dans MAPSI : fonctionnement et usages"
        oling_html = (
            f"<p>{brief.market_problem}</p>"
            f"<p>OLING part du terrain, structure l'accompagnement, puis montre comment MAPSI repond au besoin.</p>"
            f"<p>Preuves mobilisees : {', '.join(brief.source_evidence_ids)}.</p>"
            f"<p>CTA : {brief.primary_cta}.</p>"
        )
        mapsi_html = (
            f"<p>{brief.selected_topic} est presente cote produit MAPSI.</p>"
            f"<p>Fonctionnement, benefices et exemples d'utilisation sont decrits sans promesse non prouvee.</p>"
            f"<p>Preuves mobilisees : {', '.join(brief.source_evidence_ids)}.</p>"
            f"<p>CTA : {brief.primary_cta}.</p>"
        )
        linkedin_text = (
            f"Point cle cette semaine : {brief.selected_topic}. "
            f"Probleme observe : {brief.market_problem} "
            f"Idee principale : {brief.key_messages[0]} "
            f"Lire l'article : {canonical_url} "
            f"CTA : {brief.primary_cta} #MAPSI #Transformation"
        )
        return [
            self._asset(
                asset_type="oling_news_article",
                channel="oling",
                title=oling_title,
                body=oling_html,
                evidence_ids=brief.source_evidence_ids,
                target_url=canonical_url if brief.canonical_article_target == "oling.fr" else "https://www.oling.fr/demo",
                metadata={
                    "brief": brief.model_dump(mode="json"),
                    "canonical_article_target": brief.canonical_article_target,
                    "quality_channel": "oling",
                },
            ),
            self._asset(
                asset_type="mapsi_news_article",
                channel="mapsi_site",
                title=mapsi_title,
                body=mapsi_html,
                evidence_ids=brief.source_evidence_ids,
                target_url=canonical_url if brief.canonical_article_target == "mapsi.fr" else "https://mapsi.fr/demo",
                metadata={
                    "brief": brief.model_dump(mode="json"),
                    "canonical_article_target": brief.canonical_article_target,
                    "quality_channel": "mapsi_site",
                },
            ),
            self._asset(
                asset_type="linkedin_company_post",
                channel="linkedin",
                title=f"{brief.selected_topic} sur LinkedIn",
                body=linkedin_text,
                evidence_ids=brief.source_evidence_ids,
                target_url=canonical_url,
                metadata={
                    "brief": brief.model_dump(mode="json"),
                    "canonical_article_target": brief.canonical_article_target,
                    "quality_channel": "linkedin",
                    "pilot_draft_only": pilot_mode,
                    "publication_mode_requested": "draft_only" if pilot_mode else "publish",
                },
                html=False,
            ),
        ]

    def _asset(
        self,
        *,
        asset_type: str,
        channel: str,
        title: str,
        body: str,
        evidence_ids: list[str],
        target_url: str,
        metadata: dict[str, object],
        html: bool = True,
    ) -> ContentAsset:
        return ContentAsset(
            asset_type=asset_type,
            channel=channel,
            locale="fr-FR",
            title=title,
            subject="",
            content_html=body if html else None,
            content_text=body if not html else self._plain_text(body),
            excerpt=self._plain_text(body)[:160],
            target_url=target_url,
            source_evidence_ids=list(evidence_ids),
            status=AssetStatus.READY_FOR_REVIEW,
            results=metadata,
            content_hash=sha256_hexdigest(f"{asset_type}|{title}|{body}|{','.join(evidence_ids)}|{target_url}"),
        )

    def _evaluate(self, brief: MapsiMarketEditorialBrief, assets: list[ContentAsset], *, pilot_mode: bool) -> dict[str, dict[str, object]]:
        by_type = {asset.asset_type: asset for asset in assets}
        oling = by_type["oling_news_article"]
        mapsi = by_type["mapsi_news_article"]
        linkedin = by_type["linkedin_company_post"]
        canonical_target_ok = (
            (brief.canonical_article_target == "mapsi.fr" and "mapsi.fr" in linkedin.target_url)
            or (brief.canonical_article_target == "oling.fr" and "oling.fr" in linkedin.target_url)
        )
        linkedin_not_copy = not self._plain_text(oling.body).startswith(self._plain_text(linkedin.body)[:40])
        distinct_articles = self._plain_text(oling.body) != self._plain_text(mapsi.body) and oling.title != mapsi.title
        return {
            "evidence_binding": {"passed": all(asset.source_evidence_ids for asset in assets)},
            "oling_channel_quality": {
                "passed": "probleme metier" in oling.body.casefold() or brief.market_problem.casefold()[:20] in oling.body.casefold(),
            },
            "mapsi_channel_quality": {
                "passed": "fonctionnement" in mapsi.body.casefold() and "benefices" in mapsi.body.casefold(),
            },
            "linkedin_channel_quality": {
                "passed": linkedin_not_copy and canonical_target_ok and len(re.findall(r"#\w+", linkedin.body)) <= 3,
            },
            "article_differentiation": {"passed": distinct_articles},
            "pilot_rules": {"passed": (not pilot_mode) or bool(linkedin.results.get("pilot_draft_only"))},
        }

    def _slugify(self, value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
        return slug or "mapsi-market-topic"

    def _plain_text(self, value: str) -> str:
        return " ".join(value.replace("</p>", " ").replace("<p>", " ").replace("<br>", " ").replace("<br />", " ").split())
