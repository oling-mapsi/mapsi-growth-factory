from __future__ import annotations

from dataclasses import dataclass
import re

from app.application.models.editorial_agents import OlingPracticeEditorialBrief
from app.core.security import sha256_hexdigest
from app.domain.entities import ContentAsset, EditorialSourceItem
from app.domain.enums import AssetStatus
from app.domain.errors import EditorialGenerationBlockedError
from app.infrastructure.repositories.editorial_pipeline import EditorialPipelineRepository
from app.infrastructure.repositories.editorial_source_packs import EditorialSourcePackRepository


PRACTICE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("methode AMOA", ("amoa", "maitrise d'ouvrage")),
    ("gouvernance de projet", ("gouvernance", "pilotage")),
    ("ERP", ("erp", "sage", "odoo", "dynamics")),
    ("GMAO", ("gmao", "maintenance")),
    ("infrastructure", ("infrastructure", "serveur", "hebergement")),
    ("reseau", ("reseau", "wifi", "lan", "wan")),
    ("cybersecurite", ("cyber", "securite")),
    ("RGPD", ("rgpd", "privacy")),
    ("PCA/PRA", ("pca", "pra", "continuite", "reprise")),
    ("qualite", ("qualite", "processus")),
    ("data", ("data", "indicateur", "reporting")),
    ("conduite du changement", ("changement", "adoption", "accompagnement")),
    ("marches publics", ("marche public", "appel d'offres")),
    ("integration et deploiement", ("integration", "deploiement", "mise en production")),
    ("expertise sectorielle", ("secteur", "metier", "specialise")),
    ("accompagnement DSI", ("dsi", "direction des systemes")),
    ("retour d'experience projet", ("retour", "experience", "projet", "lessons learned")),
)

BLOCKED_DETAIL_PATTERNS: tuple[str, ...] = (
    "montant",
    "delai contractuel",
    "incident",
    "vulnerabilite",
    "interlocuteur",
    "architecture",
    "donnee interne",
    "difficulte commerciale",
    "litige",
)


@dataclass
class OlingPracticeCampaignBuildResult:
    brief: OlingPracticeEditorialBrief
    assets: list[ContentAsset]
    evaluations: dict[str, dict[str, object]]
    engine_mode: str = "simulated"


class OlingPracticeCampaignBuilder:
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
    ) -> OlingPracticeCampaignBuildResult:
        theme_history = self.editorial_repository.list_theme_history()
        source_items = self._load_source_items(weekly_pack_id=weekly_pack_id)
        selected = self._select_topic(source_items, theme_history, fallback_evidence_ids=fallback_evidence_ids or [])
        brief = self._build_brief(selected)
        assets = self._build_assets(brief, pilot_mode=pilot_mode)
        evaluations = self._evaluate(brief, assets, pilot_mode=pilot_mode)
        if not all(item.get("passed", False) for item in evaluations.values()):
            failed = [name for name, item in evaluations.items() if not item.get("passed", False)]
            raise EditorialGenerationBlockedError(f"OLING practice quality failed: {failed}")
        if record_theme_history:
            self.editorial_repository.append_theme_history(brief.practice, "practice_visibility", "oling_practice")
        return OlingPracticeCampaignBuildResult(brief=brief, assets=assets, evaluations=evaluations)

    def _load_source_items(self, *, weekly_pack_id: str) -> list[EditorialSourceItem]:
        items: list[EditorialSourceItem] = []
        for pack in self.editorial_source_packs.list_validated(campaign_type="OLING_PRACTICE", weekly_pack_id=weekly_pack_id):
            items.extend(pack.items)
        return items

    def _select_topic(
        self,
        items: list[EditorialSourceItem],
        theme_history: list[dict],
        *,
        fallback_evidence_ids: list[str],
    ) -> dict[str, object]:
        recent_topics = {str(item["topic"]).casefold() for item in theme_history}
        candidates: list[tuple[int, dict[str, object]]] = []
        for item in items:
            communicable = self._communicable_facts(item)
            if not communicable:
                continue
            practice = self._infer_practice(item)
            topic = f"{practice} {item.source_title or item.factual_summary}".strip()
            if topic.casefold() in recent_topics:
                continue
            score = len(communicable) * 10
            if item.evidence_quality == "high":
                score += 15
            if item.manual_input:
                score += 10
            if item.source_type == "PROJECT_DELIVERABLE":
                score += 8
            candidates.append(
                (
                    score,
                    {
                        "practice": practice,
                        "topic": topic,
                        "item": item,
                        "communicable_facts": communicable,
                        "anonymization_required": self._requires_anonymization(item),
                        "authorized_client_name": item.client_name if item.client_name and item.client_name_usage_authorized else "",
                    },
                )
            )
        if candidates:
            return sorted(candidates, key=lambda value: value[0], reverse=True)[0][1]
        if not fallback_evidence_ids:
            raise EditorialGenerationBlockedError("No communicable OLING practice topic available.")
        return {
            "practice": "accompagnement DSI",
            "topic": "Accompagnement DSI et structuration des projets numeriques",
            "item": None,
            "communicable_facts": [
                "Structurer le probleme avant de choisir les outils.",
                "Cadrer les livrables et la conduite du changement des le depart.",
                "Capitaliser sur les enseignements pour accelerer les prochains projets.",
            ],
            "anonymization_required": True,
            "authorized_client_name": "",
            "fallback_evidence_ids": fallback_evidence_ids[:2],
        }

    def _build_brief(self, selected: dict[str, object]) -> OlingPracticeEditorialBrief:
        item = selected.get("item")
        communicable_facts = list(selected["communicable_facts"])
        manual_input = dict(item.manual_input) if item is not None else {}
        deliverables = [str(value) for value in manual_input.get("deliverables_completed", []) if value] or communicable_facts[:2]
        lessons = [str(value) for value in manual_input.get("lessons_learned", []) if value] or communicable_facts[-2:]
        results = [str(value) for value in manual_input.get("observed_results", []) if value] or communicable_facts[1:3]
        evidence_ids = [item.id] if item is not None else list(selected.get("fallback_evidence_ids", []))
        project_context = self._sanitize_value(
            str(item.factual_summary if item is not None else selected["topic"]),
            item,
            force_anonymize=bool(selected["anonymization_required"]),
        )
        client_problem = str(manual_input.get("client_problem") or "") if manual_input else ""
        business_problem = (
            self._sanitize_value(client_problem, item, force_anonymize=bool(selected["anonymization_required"]))
            if client_problem
            else f"Les organisations doivent mieux traiter {str(selected['practice']).casefold()} sans exposer leurs informations sensibles."
        )
        approach = self._sanitize_value(
            str(manual_input.get("oling_method") or f"OLING structure une approche progressive sur {selected['practice']}."),
            item,
            force_anonymize=bool(selected["anonymization_required"]),
        )
        return OlingPracticeEditorialBrief(
            practice=str(selected["practice"]),
            business_problem=business_problem,
            project_context=project_context,
            anonymization_required=bool(selected["anonymization_required"]),
            authorized_client_name=str(selected["authorized_client_name"]),
            approach=approach,
            deliverables=deliverables,
            lessons_learned=lessons,
            demonstrated_results=results,
            unverified_claims_to_exclude=[
                "montant_projet",
                "delai_contractuel",
                "incident_ou_vulnerabilite",
                "noms_interlocuteurs",
                "architecture_precise",
                "litige_ou_difficulte_commerciale",
            ],
            target_personas=["dsi", "responsable_projet", "direction_metier"],
            article_angle=f"Montrer le probleme, la methode OLING, les livrables et les enseignements sur {selected['practice']}.",
            linkedin_angle=f"Accroche courte sur {selected['practice']}, enseignement cle et invitation a lire l'article.",
            CTA=str(manual_input.get("desired_cta") or "Echanger avec OLING sur votre projet"),
            source_evidence_ids=evidence_ids,
        )

    def _build_assets(self, brief: OlingPracticeEditorialBrief, *, pilot_mode: bool) -> list[ContentAsset]:
        slug = self._slugify(brief.practice)
        canonical_url = f"https://www.oling.fr/ressources/{slug}"
        client_clause = f"<p>Contexte client : {brief.authorized_client_name}.</p>" if brief.authorized_client_name else ""
        article_html = (
            f"<p>{brief.business_problem}</p>"
            f"<p>Approche OLING : {brief.approach}</p>"
            f"{client_clause}"
            f"<p>Livrables : {', '.join(brief.deliverables)}.</p>"
            f"<p>Enseignements : {', '.join(brief.lessons_learned)}.</p>"
            f"<p>Resultats observes : {', '.join(brief.demonstrated_results)}.</p>"
            f"<p>Preuves mobilisees : {', '.join(brief.source_evidence_ids)}.</p>"
            f"<p>CTA : {brief.CTA}.</p>"
        )
        linkedin_text = (
            f"{brief.practice} : {brief.business_problem} "
            f"Enseignement cle : {brief.lessons_learned[0] if brief.lessons_learned else brief.practice}. "
            f"Lire l'article : {canonical_url} #OLING #Transformation"
        )
        return [
            self._asset(
                asset_type="oling_news_article",
                channel="oling",
                title=f"{brief.practice} : methode, livrables et enseignements",
                body=article_html,
                evidence_ids=brief.source_evidence_ids,
                target_url=canonical_url,
                metadata={"brief": brief.model_dump(mode="json"), "quality_channel": "oling"},
            ),
            self._asset(
                asset_type="linkedin_company_post",
                channel="linkedin",
                title=f"{brief.practice} sur LinkedIn",
                body=linkedin_text,
                evidence_ids=brief.source_evidence_ids,
                target_url=canonical_url,
                metadata={
                    "brief": brief.model_dump(mode="json"),
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

    def _communicable_facts(self, item: EditorialSourceItem) -> list[str]:
        facts: list[str] = []
        prohibited = set(item.prohibited_facts)
        for fact in item.usable_facts:
            if fact in prohibited:
                continue
            sanitized = self._sanitize_value(fact, item, force_anonymize=self._requires_anonymization(item))
            if sanitized:
                facts.append(sanitized)
        for fact in item.anonymized_facts:
            if fact in prohibited:
                continue
            sanitized = self._sanitize_value(fact, item, force_anonymize=True)
            if sanitized:
                facts.append(sanitized)
        if not facts and item.factual_summary:
            sanitized = self._sanitize_value(item.factual_summary, item, force_anonymize=self._requires_anonymization(item))
            if sanitized:
                facts.append(sanitized)
        return facts[:4]

    def _requires_anonymization(self, item: EditorialSourceItem) -> bool:
        return item.confidentiality_level in {"CLIENT_CONFIDENTIAL", "STRICTLY_CONFIDENTIAL"} or item.source_type in {
            "PROJECT_DELIVERABLE",
            "CLIENT_FEEDBACK",
            "CONSULTANT_NOTE",
            "EMAIL_THREAD",
            "TEAMS_MESSAGE",
            "TEAMS_THREAD",
        }

    def _sanitize_value(self, value: str, item: EditorialSourceItem | None, *, force_anonymize: bool = False) -> str:
        if not value:
            return ""
        result = value
        if item and item.client_name and (force_anonymize or not item.client_name_usage_authorized):
            result = re.sub(re.escape(item.client_name), "un client", result, flags=re.IGNORECASE)
        lowered = result.casefold()
        if any(pattern in lowered for pattern in BLOCKED_DETAIL_PATTERNS):
            return ""
        if item and item.source_type in {"TEAMS_MESSAGE", "TEAMS_THREAD"}:
            result = re.sub(r"\b(message|thread|chat|teams)\b", "retour terrain", result, flags=re.IGNORECASE)
        return " ".join(result.split()).strip()

    def _infer_practice(self, item: EditorialSourceItem) -> str:
        primary_haystack = " ".join([item.source_type, item.source_title, item.factual_summary]).casefold()
        secondary_haystack = " ".join(
            [
                " ".join(item.usable_facts),
                " ".join(item.anonymized_facts),
                " ".join(str(value) for value in item.manual_input.values() if isinstance(value, str)),
            ]
        ).casefold()
        best_match = ""
        best_score = 0
        for practice, keywords in PRACTICE_KEYWORDS:
            score = sum(3 for keyword in keywords if keyword.casefold() in primary_haystack)
            score += sum(1 for keyword in keywords if keyword.casefold() in secondary_haystack)
            if score > best_score:
                best_match = practice
                best_score = score
        if best_match:
            return best_match
        return "retour d'experience projet"

    def _evaluate(
        self,
        brief: OlingPracticeEditorialBrief,
        assets: list[ContentAsset],
        *,
        pilot_mode: bool,
    ) -> dict[str, dict[str, object]]:
        article = next(asset for asset in assets if asset.asset_type == "oling_news_article")
        linkedin = next(asset for asset in assets if asset.asset_type == "linkedin_company_post")
        article_text = self._plain_text(article.body).casefold()
        linkedin_text = self._plain_text(linkedin.body).casefold()
        client_name = brief.authorized_client_name.casefold()
        return {
            "evidence_binding": {"passed": all(asset.source_evidence_ids for asset in assets)},
            "article_quality": {
                "passed": all(term in article_text for term in ("approche oling", "livrables", "enseignements")),
            },
            "linkedin_quality": {
                "passed": len(linkedin.content_text) < len(article.content_text) and "oling.fr/ressources/" in linkedin.target_url and len(re.findall(r"#\w+", linkedin.body)) <= 3,
            },
            "client_anonymization": {"passed": True if client_name else ("un client" in article_text or brief.anonymization_required)},
            "teams_redaction": {"passed": "teams" not in article_text and "teams" not in linkedin_text and "chat" not in article_text},
            "meeting_note_style": {"passed": "compte rendu" not in article_text and "participants" not in article_text and "ordre du jour" not in article_text},
            "pilot_rules": {"passed": (not pilot_mode) or bool(linkedin.results.get("pilot_draft_only"))},
        }

    def _slugify(self, value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
        return slug or "oling-practice-topic"

    def _plain_text(self, value: str) -> str:
        return " ".join(value.replace("</p>", " ").replace("<p>", " ").replace("<br>", " ").replace("<br />", " ").split())
