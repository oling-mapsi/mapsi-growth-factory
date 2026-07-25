from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import NAMESPACE_URL, uuid4, uuid5

from pydantic import BaseModel

from app.application.models.editorial_agents import EditorialExecutionMetadata, EditorialTokenUsage
from app.application.models.editorial_v1 import (
    EditorialArticle,
    EditorialBuilderSelection,
    EditorialClaim,
    EditorialGenerationContext,
    EditorialGenerationResult,
    EditorialGenerationRecord,
    EditorialQualityIssue,
    EditorialQualityReport,
    EditorialSourceDescriptor,
    MapsiFeatureContext,
    OlingPracticeContext,
    ProductChangeContext,
    PublishedArticleContext,
)
from app.application.ports.editorial_agents import EditorialProvider
from app.core.config import get_settings
from app.core.security import sha256_hexdigest
from app.domain.entities import CampaignRun, ContentAsset, EditorialBrief, ProductChange, SourceEvidence
from app.domain.enums import AssetStatus, CampaignStatus
from app.domain.errors import EditorialGenerationBlockedError
from app.infrastructure.observability import incr, structured_log
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
from app.infrastructure.repositories.editorial_pipeline import EditorialPipelineRepository
from app.knowledge import KnowledgeRepository

ROOT = Path(__file__).resolve().parents[3]
PROMPTS_ROOT = ROOT / "prompts"
EDITORIAL_PROMPT_VERSION = "v1"

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
TOKEN_RE = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|[A-Za-z0-9_-]{24,}\.[A-Za-z0-9._-]{8,})\b")
SCRIPT_RE = re.compile(r"<\s*(script|iframe)\b", re.IGNORECASE)
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
CLIENT_RE = re.compile(r"\b(?:acme|client [a-z0-9_-]+|chez [a-z0-9_-]+)\b", re.IGNORECASE)


@dataclass(frozen=True)
class EditorialGenerationEnvelope:
    article: EditorialArticle
    metadata: EditorialExecutionMetadata
    duration_ms: int
    input_hash: str
    output_hash: str
    estimated_cost_usd: float


class EditorialGeneratorInterface(ABC):
    @abstractmethod
    def generate(self, context: EditorialGenerationContext) -> EditorialGenerationEnvelope:
        raise NotImplementedError


class OpenAIEditorialGenerator(EditorialGeneratorInterface):
    agent_name = "EditorialArticleGenerator"

    def __init__(self, provider: EditorialProvider) -> None:
        self.provider = provider
        settings = get_settings()
        self.model_name = settings.editorial_agent_model
        self.temperature = settings.editorial_agent_temperature

    def generate(self, context: EditorialGenerationContext) -> EditorialGenerationEnvelope:
        prompt = self._build_prompt(context)
        input_hash = sha256_hexdigest(context.model_dump_json())
        started = time.perf_counter()
        result = self.provider.run_structured(
            agent_name=self.agent_name,
            prompt=prompt,
            input_model=context,
            output_type=EditorialArticle,
            model_name=self.model_name,
            prompt_version=EDITORIAL_PROMPT_VERSION,
            temperature=self.temperature,
        )
        duration_ms = max(1, int((time.perf_counter() - started) * 1000))
        output_hash = sha256_hexdigest(result.output.model_dump_json())
        cost = _estimate_cost(result.metadata.token_usage)
        return EditorialGenerationEnvelope(
            article=result.output,
            metadata=result.metadata,
            duration_ms=duration_ms,
            input_hash=input_hash,
            output_hash=output_hash,
            estimated_cost_usd=cost,
        )

    def _build_prompt(self, context: EditorialGenerationContext) -> str:
        base_prompt = (PROMPTS_ROOT / "editorial-article-generator" / f"{EDITORIAL_PROMPT_VERSION}.txt").read_text(encoding="utf-8")
        mode_instructions = {
            "MAPSI_PRODUCT": "Ecrire un article produit MAPSI ancre sur fonctionnalites et changements recents, pour publication cible mapsi.fr.",
            "MAPSI_CONSULTING": "Ecrire un article de conseil OLING ancre sur une fonctionnalite MAPSI prouvee, pour publication cible oling.fr.",
            "OLING_PRACTICE": "Ecrire un article practice OLING ancre sur la fiche de pratique, sans aucun contenu client specifique.",
        }
        return f"{base_prompt}\n\nMode actif: {context.article_type}\n{mode_instructions[context.article_type]}"


class SimulatedEditorialGenerator(EditorialGeneratorInterface):
    def generate(self, context: EditorialGenerationContext) -> EditorialGenerationEnvelope:
        article = self._article_for(context)
        output_hash = sha256_hexdigest(article.model_dump_json())
        input_hash = sha256_hexdigest(context.model_dump_json())
        token_usage = EditorialTokenUsage(input_tokens=max(1, len(context.model_dump_json()) // 4), output_tokens=max(1, len(article.model_dump_json()) // 4), total_tokens=max(2, len(context.model_dump_json()) // 4 + len(article.model_dump_json()) // 4))
        return EditorialGenerationEnvelope(
            article=article,
            metadata=EditorialExecutionMetadata(
                agent_name="EditorialArticleGenerator",
                provider_type="simulated",
                model_name="simulated-editorial-v1",
                prompt_version=EDITORIAL_PROMPT_VERSION,
                schema_name="EditorialArticle",
                execution_params={"temperature": 0.0},
                token_usage=token_usage,
            ),
            duration_ms=1,
            input_hash=input_hash,
            output_hash=output_hash,
            estimated_cost_usd=0.0,
        )

    def _article_for(self, context: EditorialGenerationContext) -> EditorialArticle:
        claims: list[EditorialClaim] = []
        source_ids = [source.source_id for source in context.sources]
        if context.article_type in {"MAPSI_PRODUCT", "MAPSI_CONSULTING"} and context.mapsi_feature is not None:
            claims.append(
                EditorialClaim(
                    text=context.mapsi_feature.functional_description,
                    source_ids=[source_ids[0]],
                    claim_type="product_fact",
                    verified=True,
                )
            )
        if context.article_type == "OLING_PRACTICE" and context.oling_practice is not None:
            claims.append(
                EditorialClaim(
                    text=context.oling_practice.oling_approach,
                    source_ids=[source_ids[0]],
                    claim_type="practice_fact",
                    verified=True,
                )
            )
        if context.article_type in {"MAPSI_PRODUCT", "MAPSI_CONSULTING"} and context.recent_product_changes:
            claims.append(
                EditorialClaim(
                    text=context.recent_product_changes[0].summary,
                    source_ids=context.recent_product_changes[0].source_ids,
                    claim_type="product_fact",
                    verified=True,
                )
            )
        body_text = self._body_text(context)
        title = context.desired_title.strip() or self._title(context)
        excerpt = body_text[:157] + "..." if len(body_text) > 160 else body_text
        slug = _slugify(title)
        return EditorialArticle(
            topic=context.topic,
            article_type=context.article_type,
            title=title,
            slug=slug,
            excerpt=excerpt,
            body_html=self._body_html(context),
            body_text=body_text,
            meta_title=title[:60],
            meta_description=excerpt[:160],
            target_personas=list(context.target_personas),
            primary_keyword=context.topic,
            secondary_keywords=[item for item in list(context.target_personas)[:3] if item != context.topic],
            call_to_action_label="Demander un echange",
            call_to_action_url="https://www.oling.fr/contact" if context.destination_site == "oling.fr" else "https://www.mapsi.fr",
            source_ids=source_ids,
            claims=claims,
            warnings=[],
        )

    def _title(self, context: EditorialGenerationContext) -> str:
        if context.article_type == "MAPSI_PRODUCT":
            return f"{context.topic} : un usage MAPSI plus clair, plus simple, plus efficace"
        if context.article_type == "MAPSI_CONSULTING":
            return f"{context.topic} : prendre du recul pour mieux transformer l'usage"
        return f"{context.topic} : cadrer le sujet, structurer l'action, faire avancer la decision"

    def _body_text(self, context: EditorialGenerationContext) -> str:
        if context.article_type in {"MAPSI_PRODUCT", "MAPSI_CONSULTING"} and context.mapsi_feature is not None:
            benefits = ", ".join(context.mapsi_feature.user_benefits[:3]) or "mieux comprendre les usages et gagner en lisibilite"
            use_cases = ", ".join(context.mapsi_feature.typical_use_cases[:3]) or "des cas d'usage concrets du quotidien"
            recent_change = context.recent_product_changes[0].summary if context.recent_product_changes else context.mapsi_feature.short_description
            return "\n\n".join(
                [
                    f"{context.topic}\n\n{context.mapsi_feature.business_problem}",
                    (
                        f"Ce sujet merite une communication de fond, parce qu'il relie directement le besoin metier, "
                        f"la facon d'utiliser MAPSI et la capacite des equipes a produire une information plus lisible. "
                        f"{context.mapsi_feature.functional_description}"
                    ),
                    (
                        f"Concretement, les gains attendus portent sur {benefits}. "
                        f"Dans la pratique, les usages les plus parlants sont {use_cases}. "
                        f"Le changement recent a retenir est le suivant : {recent_change}."
                    ),
                    (
                        "Ce type de contenu doit rester utile, nuance et exploitable. "
                        "Il ne s'agit pas de surpromettre, mais de montrer comment une fonctionnalite bien expliquee "
                        "peut reduire les frictions, clarifier l'action et renforcer l'adoption."
                    ),
                    (
                        f"Pour {context.destination_site}, l'angle editorial doit articuler la promesse, la preuve et le rythme. "
                        "Le lecteur doit comprendre rapidement ce que le sujet change, pour qui il compte et dans quels cas "
                        "il devient vraiment utile au quotidien."
                    ),
                ]
            )
        if context.oling_practice is not None:
            problems = ", ".join(context.oling_practice.common_client_problems[:3])
            steps = ", ".join(context.oling_practice.mission_steps[:3])
            deliverables = ", ".join(context.oling_practice.usual_deliverables[:3])
            return "\n\n".join(
                [
                    f"{context.topic}\n\n{context.oling_practice.description}",
                    (
                        f"Le fond du sujet tient souvent a quelques difficultes recurrentes : {problems}. "
                        f"L'enjeu n'est pas seulement de produire un cadrage, mais de poser une methode qui permette "
                        "d'avancer sans perdre la main sur les arbitrages, les livrables et les priorites."
                    ),
                    (
                        f"Chez OLING, l'approche se structure autour de {steps}. "
                        f"Elle se traduit ensuite par des livrables concrets comme {deliverables}, avec une posture de conseil "
                        "qui vise autant la clarte de decision que l'execution."
                    ),
                    (
                        "Un bon contenu editorial sur ce type de sujet doit installer une respiration : poser le probleme, "
                        "montrer la methode, donner a voir les points de vigilance, puis ouvrir une perspective de passage a l'action."
                    ),
                    (
                        "L'objectif n'est pas de faire technique pour faire technique, mais de montrer une expertise "
                        "suffisamment structuree pour inspirer confiance a un lecteur exigeant."
                    ),
                ]
            )
        return context.topic

    def _body_html(self, context: EditorialGenerationContext) -> str:
        paragraphs = [part.strip() for part in self._body_text(context).split("\n\n") if part.strip()]
        if context.article_type in {"MAPSI_PRODUCT", "MAPSI_CONSULTING"} and context.mapsi_feature is not None:
            bullets = context.mapsi_feature.user_benefits[:3] or context.mapsi_feature.typical_use_cases[:3]
        elif context.oling_practice is not None:
            bullets = context.oling_practice.mission_steps[:3] or context.oling_practice.usual_deliverables[:3]
        else:
            bullets = [context.topic]
        bullet_html = "".join(f"<li>{item}</li>" for item in bullets)
        rendered = [
            f"<h1>{context.desired_title.strip() or self._title(context)}</h1>",
            f"<p>{paragraphs[0]}</p>" if paragraphs else "",
            "<h2>Ce qu'il faut retenir</h2>",
            f"<ul>{bullet_html}</ul>",
        ]
        for paragraph in paragraphs[1:]:
            rendered.append(f"<p>{paragraph}</p>")
        rendered.append(
            f"<p><strong>Prochaine etape :</strong> {('Demander un echange' if context.destination_site == 'oling.fr' else 'Decouvrir le sujet dans MAPSI')}.</p>"
        )
        return "".join(rendered)


class EditorialQualityValidator:
    def __init__(self) -> None:
        settings = get_settings()
        self.min_body_length = settings.editorial_article_min_chars
        self.max_body_length = settings.editorial_article_max_chars
        self.similarity_threshold = settings.editorial_similarity_threshold

    def validate(self, article: EditorialArticle, context: EditorialGenerationContext) -> EditorialQualityReport:
        issues: list[EditorialQualityIssue] = []
        sanitized_html = _sanitize_html(article.body_html)
        if sanitized_html != article.body_html:
            article.body_html = sanitized_html
            article.warnings.append("html_sanitized")
        if not article.title.strip():
            issues.append(self._issue("missing_title", "Title is required."))
        if not article.body_text.strip():
            issues.append(self._issue("empty_body", "Body text is required."))
        if len(article.body_text) < self.min_body_length:
            issues.append(self._issue("body_too_short", "Body text is below minimum length."))
        if len(article.body_text) > self.max_body_length:
            issues.append(self._issue("body_too_long", "Body text exceeds maximum length."))
        if not article.meta_title.strip():
            issues.append(self._issue("missing_meta_title", "Meta title is required."))
        if not article.meta_description.strip():
            issues.append(self._issue("missing_meta_description", "Meta description is required."))
        if not article.call_to_action_label.strip() or not article.call_to_action_url.strip():
            issues.append(self._issue("missing_cta", "CTA label and URL are required."))
        if not article.source_ids:
            issues.append(self._issue("missing_sources", "At least one source is required."))
        if EMAIL_RE.search(article.model_dump_json()) or TOKEN_RE.search(article.model_dump_json()):
            issues.append(self._issue("secret_or_email_detected", "Emails or secrets are forbidden."))
        if CLIENT_RE.search(article.model_dump_json()):
            issues.append(self._issue("unauthorized_client_reference", "Client references are forbidden in generated content."))
        if any(not claim.verified for claim in article.claims):
            issues.append(self._issue("unverified_claim", "All claims must be verified."))
        allowed_source_ids = {source.source_id for source in context.sources}
        if any(source_id not in allowed_source_ids for source_id in article.source_ids):
            issues.append(self._issue("unknown_source_id", "Article source ids must come from context sources."))
        for claim in article.claims:
            if not claim.source_ids:
                issues.append(self._issue("claim_without_source", "Every claim must include source ids."))
            if any(source_id not in allowed_source_ids for source_id in claim.source_ids):
                issues.append(self._issue("claim_unknown_source", "Claim source ids must come from context sources."))
        if not SLUG_RE.match(article.slug):
            issues.append(self._issue("invalid_slug", "Slug format is invalid."))
        if SCRIPT_RE.search(article.body_html):
            issues.append(self._issue("unsafe_html", "Unsafe HTML is forbidden."))
        similarity_score, closest_match = _max_similarity(article, context.published_topic_history)
        if similarity_score >= self.similarity_threshold:
            issues.append(self._issue("content_too_similar", "Generated content is too similar to existing history."))
        return EditorialQualityReport(
            passed=not any(item.severity == "error" for item in issues),
            issues=issues,
            similarity_score=round(similarity_score, 4),
            closest_match=closest_match,
        )

    def _issue(self, code: str, message: str, severity: str = "error") -> EditorialQualityIssue:
        return EditorialQualityIssue(code=code, message=message, severity=cast(str, severity))


class EditorialGenerationService:
    def __init__(
        self,
        *,
        generator: EditorialGeneratorInterface,
        knowledge_repository: KnowledgeRepository,
        editorial_repository: EditorialPipelineRepository,
        campaign_repository: SqlAlchemyCampaignRepository,
    ) -> None:
        self.generator = generator
        self.knowledge_repository = knowledge_repository
        self.editorial_repository = editorial_repository
        self.campaign_repository = campaign_repository
        self.validator = EditorialQualityValidator()

    def generate_mapsi(self, *, destination: str, persist: bool = True) -> EditorialGenerationRecord:
        article_type = "MAPSI_PRODUCT" if destination == "mapsi" else "MAPSI_CONSULTING"
        context = self._build_mapsi_context(article_type=article_type, destination=destination)
        return self._generate(context=context, persist=persist)

    def generate_oling(self, *, practice_id: str, persist: bool = True) -> EditorialGenerationRecord:
        context = self._build_oling_context(practice_id=practice_id)
        return self._generate(context=context, persist=persist)

    def generate_from_context(
        self,
        *,
        context: EditorialGenerationContext,
        persist: bool = False,
        selection: EditorialBuilderSelection | None = None,
        allow_failed_quality: bool = False,
    ) -> EditorialGenerationResult:
        envelope = self.generator.generate(context)
        quality = self.validator.validate(envelope.article, context)
        record = EditorialGenerationRecord(
            article=envelope.article,
            quality=quality,
            model_name=envelope.metadata.model_name,
            prompt_version=envelope.metadata.prompt_version,
            knowledge_version=context.knowledge_version,
            input_hash=envelope.input_hash,
            output_hash=envelope.output_hash,
            input_tokens=envelope.metadata.token_usage.input_tokens,
            output_tokens=envelope.metadata.token_usage.output_tokens,
            total_tokens=envelope.metadata.token_usage.total_tokens,
            estimated_cost_usd=envelope.estimated_cost_usd,
            duration_ms=envelope.duration_ms,
            provider_type=envelope.metadata.provider_type,
        )
        self._log_execution(context=context, record=record)
        if not quality.passed and not allow_failed_quality:
            raise EditorialGenerationBlockedError(f"Editorial article validation failed: {[item.code for item in quality.issues]}")
        if persist and quality.passed:
            self._persist_record(context=context, record=record)
        incr("editorial.article.generated", 1)
        structured_log(
            "editorial.article.generated",
            article_type=context.article_type,
            provider=envelope.metadata.provider_type,
            total_tokens=envelope.metadata.token_usage.total_tokens,
            quality_passed=quality.passed,
        )
        return EditorialGenerationResult(context=context, record=record, selection=selection)

    def _generate(self, *, context: EditorialGenerationContext, persist: bool) -> EditorialGenerationRecord:
        return self.generate_from_context(context=context, persist=persist).record

    def _build_mapsi_context(self, *, article_type: str, destination: str) -> EditorialGenerationContext:
        cutoff = datetime.now(UTC).date() - timedelta(days=180)
        recent_changes = self.knowledge_repository.listMapsIProductChangesSince(cutoff)
        if not recent_changes:
            raise EditorialGenerationBlockedError("No recent MAPSI product changes found in the last 180 days.")
        features = self.knowledge_repository.listMapsIFeatures()
        selected_change = recent_changes[0]
        selected_feature = self._select_mapsi_feature(features, selected_change)
        if selected_feature is None:
            raise EditorialGenerationBlockedError("No MAPSI knowledge feature could be matched to recent product changes.")
        rules = self.knowledge_repository.getEditorialRules()
        history = self._build_history()
        sources = self._mapsi_sources(selected_feature.feature_id, selected_change)
        topic = selected_feature.title
        return EditorialGenerationContext(
            topic=topic,
            article_type=cast(str, article_type),
            destination_site=cast(str, "mapsi.fr" if destination == "mapsi" else "oling.fr"),
            target_personas=selected_feature.target_roles or ["direction_metier", "responsable_transformation"],
            knowledge_version=rules.knowledge_version_hash,
            positioning=rules.mapsi_product_positioning,
            terminology=rules.mapsi_terminology,
            editorial_rules=rules.mapsi_forbidden_claims,
            forbidden_claims=selected_feature.forbidden_claims,
            mapsi_feature=MapsiFeatureContext(
                feature_id=selected_feature.feature_id,
                module=selected_feature.module,
                title=selected_feature.title,
                short_description=selected_feature.short_description,
                business_problem=selected_feature.business_problem,
                functional_description=selected_feature.functional_description,
                user_benefits=selected_feature.user_benefits,
                typical_use_cases=selected_feature.typical_use_cases,
                target_roles=selected_feature.target_roles,
                forbidden_claims=selected_feature.forbidden_claims,
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
                for change in recent_changes[:5]
            ],
            published_topic_history=history,
            sources=sources,
        )

    def _build_oling_context(self, *, practice_id: str) -> EditorialGenerationContext:
        practice = self.knowledge_repository.getOlingPractice(practice_id)
        if practice is None:
            raise EditorialGenerationBlockedError(f"Unknown OLING practice: {practice_id}")
        rules = self.knowledge_repository.getEditorialRules()
        history = self._build_history()
        sources = self._oling_sources(practice.practice_id)
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
            published_topic_history=history,
            sources=sources,
        )

    def _select_mapsi_feature(self, features, product_change: ProductChange):
        change_text = f"{product_change.summary} {product_change.capability_key} {product_change.change_note_path}".casefold()
        ranked: list[tuple[int, object]] = []
        for feature in features:
            score = 0
            haystack = f"{feature.title} {feature.module} {feature.short_description} {feature.functional_description}".casefold()
            if feature.module and feature.module.casefold() in change_text:
                score += 5
            score += len(set(_tokenize(haystack)).intersection(set(_tokenize(change_text))))
            ranked.append((score, feature))
        ranked.sort(key=lambda item: item[0], reverse=True)
        if not ranked or ranked[0][0] <= 0:
            return None
        return ranked[0][1]

    def _build_history(self) -> list[PublishedArticleContext]:
        history = [
            PublishedArticleContext(
                topic=item.topic,
                objective=item.objective,
                audience_segment_id=item.audience_segment_id,
                created_at=item.created_at,
            )
            for item in self.knowledge_repository.getPublishedTopicHistory(limit=20)
        ]
        for item in self.editorial_repository.list_recent_article_history(limit=20):
            history.append(
                PublishedArticleContext(
                    topic=item["topic"],
                    objective=item["objective"],
                    audience_segment_id=item["audience_segment_id"],
                    title=item["title"],
                    slug=item["slug"],
                    excerpt=item["excerpt"],
                    created_at=item["created_at"],
                )
            )
        return history

    def _mapsi_sources(self, feature_id: str, change: ProductChange) -> list[EditorialSourceDescriptor]:
        return [
            EditorialSourceDescriptor(
                source_id=f"knowledge:mapsi:feature:{feature_id}",
                source_type="knowledge_file",
                label=f"Feature {feature_id}",
                reference=f"knowledge/mapsi/feature-catalog.yaml#{feature_id}",
                summary="Base de connaissances MAPSI validee.",
            ),
            EditorialSourceDescriptor(
                source_id="knowledge:mapsi:positioning",
                source_type="knowledge_file",
                label="MAPSI positioning",
                reference="knowledge/mapsi/product-positioning.md",
                summary="Positionnement produit MAPSI.",
            ),
            EditorialSourceDescriptor(
                source_id="knowledge:mapsi:terminology",
                source_type="knowledge_file",
                label="MAPSI terminology",
                reference="knowledge/mapsi/terminology.md",
                summary="Terminologie MAPSI.",
            ),
            EditorialSourceDescriptor(
                source_id=f"product_change:{change.id}",
                source_type="product_change",
                label=change.summary,
                reference=change.change_note_path or change.sha,
                summary=change.summary,
            ),
        ]

    def _oling_sources(self, practice_id: str) -> list[EditorialSourceDescriptor]:
        return [
            EditorialSourceDescriptor(
                source_id=f"knowledge:oling:practice:{practice_id}",
                source_type="knowledge_file",
                label=f"Practice {practice_id}",
                reference=f"knowledge/oling/practices/{practice_id}.md",
                summary="Fiche practice OLING.",
            ),
            EditorialSourceDescriptor(
                source_id="knowledge:oling:profile",
                source_type="knowledge_file",
                label="OLING profile",
                reference="knowledge/oling/company-profile.md",
                summary="Profil d'entreprise OLING.",
            ),
            EditorialSourceDescriptor(
                source_id="knowledge:oling:differentiators",
                source_type="knowledge_file",
                label="OLING differentiators",
                reference="knowledge/oling/differentiators.md",
                summary="Differenciateurs OLING.",
            ),
            EditorialSourceDescriptor(
                source_id="knowledge:oling:targets",
                source_type="knowledge_file",
                label="OLING target clients",
                reference="knowledge/oling/target-clients.md",
                summary="Cibles OLING.",
            ),
        ]

    def _persist_record(self, *, context: EditorialGenerationContext, record: EditorialGenerationRecord) -> None:
        campaign = CampaignRun(
            name=record.article.title,
            objective="editorial_article_generation",
            campaign_type="MAPSI_MARKET" if context.article_type in {"MAPSI_PRODUCT", "MAPSI_CONSULTING"} else "OLING_PRACTICE",
            status=CampaignStatus.DRAFT,
        )
        evidences = self._build_source_evidences(campaign.id, context.sources)
        asset = ContentAsset(
            campaign_run_id=campaign.id,
            asset_type="mapsi_news_article" if context.destination_site == "mapsi.fr" else "oling_news_article",
            channel="mapsi_site" if context.destination_site == "mapsi.fr" else "oling",
            locale="fr-FR",
            title=record.article.title,
            subject="",
            content_html=record.article.body_html,
            content_text=record.article.body_text,
            excerpt=record.article.excerpt,
            call_to_action=record.article.call_to_action_label,
            target_url=record.article.call_to_action_url,
            source_evidence_ids=[item.id for item in evidences if item.reference in {source.reference for source in context.sources if source.source_id in record.article.source_ids}],
            audience_segment_id=context.article_type.casefold(),
            status=AssetStatus.READY_FOR_REVIEW,
            results={
                "editorial_article": record.article.model_dump(mode="json"),
                "editorial_quality": record.quality.model_dump(mode="json"),
                "editorial_execution": {
                    "model": record.model_name,
                    "prompt_version": record.prompt_version,
                    "knowledge_version": record.knowledge_version,
                    "input_hash": record.input_hash,
                    "output_hash": record.output_hash,
                    "tokens": {
                        "input": record.input_tokens,
                        "output": record.output_tokens,
                        "total": record.total_tokens,
                    },
                    "cost_usd": record.estimated_cost_usd,
                    "duration_ms": record.duration_ms,
                    "provider_type": record.provider_type,
                    "mode": get_settings().editorial_engine_mode,
                },
            },
        )
        campaign.editorial_briefs = [EditorialBrief(campaign_run_id=campaign.id, title=record.article.title, summary=record.article.excerpt)]
        campaign.content_assets = [asset]
        campaign.source_evidences = evidences
        self.campaign_repository.add(campaign)
        self.editorial_repository.append_theme_history(record.article.topic, "editorial_article_generation", context.article_type.casefold())

    def _build_source_evidences(self, campaign_id: str, sources: list[EditorialSourceDescriptor]) -> list[SourceEvidence]:
        return [
            SourceEvidence(
                id=str(uuid5(NAMESPACE_URL, f"{campaign_id}:{source.source_id}")),
                campaign_run_id=campaign_id,
                source_system=source.source_type,
                evidence_type="knowledge_source" if source.source_type == "knowledge_file" else "product_change_source",
                reference=source.reference,
                payload=source.model_dump(mode="json"),
            )
            for source in sources
        ]

    def _log_execution(self, *, context: EditorialGenerationContext, record: EditorialGenerationRecord) -> None:
        self.editorial_repository.log_agent_execution(
            agent_name="EditorialArticleGenerator",
            model_name=record.model_name,
            prompt_version=record.prompt_version,
            execution_params={
                "article_type": context.article_type,
                "destination_site": context.destination_site,
                "knowledge_version": record.knowledge_version,
                "input_hash": record.input_hash,
                "output_hash": record.output_hash,
                "duration_ms": record.duration_ms,
                "estimated_cost_usd": record.estimated_cost_usd,
                "quality_passed": record.quality.passed,
                "quality_issues": [item.model_dump(mode="json") for item in record.quality.issues],
                "mode": get_settings().editorial_engine_mode,
            },
            input_payload=context.model_dump(mode="json"),
            output_payload=record.article.model_dump(mode="json"),
        )


def build_editorial_generation_service(session, *, force_mode: str | None = None) -> EditorialGenerationService:
    settings = get_settings()
    effective_mode = force_mode or settings.editorial_engine_mode
    provider: EditorialGeneratorInterface
    if effective_mode in {"real", "shadow"} or settings.editorial_agent_backend == "openai":
        from app.infrastructure.agents.openai_backend import OpenAIAgentsBackend

        provider = OpenAIEditorialGenerator(OpenAIAgentsBackend())
    else:
        provider = SimulatedEditorialGenerator()
    return EditorialGenerationService(
        generator=provider,
        knowledge_repository=KnowledgeRepository(session),
        editorial_repository=EditorialPipelineRepository(session),
        campaign_repository=SqlAlchemyCampaignRepository(session),
    )


def _sanitize_html(value: str) -> str:
    sanitized = re.sub(r"<\s*/?\s*(script|iframe)[^>]*>", "", value, flags=re.IGNORECASE)
    sanitized = re.sub(r"\son[a-z]+\s*=\s*(['\"]).*?\1", "", sanitized, flags=re.IGNORECASE)
    return sanitized


def _estimate_cost(usage: EditorialTokenUsage) -> float:
    settings = get_settings()
    return round(
        (usage.input_tokens / 1_000_000) * settings.editorial_agent_input_cost_per_1m_tokens
        + (usage.output_tokens / 1_000_000) * settings.editorial_agent_output_cost_per_1m_tokens,
        6,
    )


def _slugify(value: str) -> str:
    lowered = value.casefold()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return re.sub(r"-{2,}", "-", slug) or f"article-{uuid4().hex[:8]}"


def _tokenize(value: str) -> list[str]:
    return [item for item in re.split(r"[^a-z0-9]+", value.casefold()) if item]


def _similarity(a: str, b: str) -> float:
    left = Counter(_tokenize(a))
    right = Counter(_tokenize(b))
    if not left or not right:
        return 0.0
    numerator = sum(min(left[token], right[token]) for token in set(left) | set(right))
    denominator = sum(max(left[token], right[token]) for token in set(left) | set(right))
    return numerator / denominator if denominator else 0.0


def _max_similarity(article: EditorialArticle, history: list[PublishedArticleContext]) -> tuple[float, str]:
    candidate = f"{article.topic} {article.title} {article.excerpt} {article.body_text[:280]}"
    best_score = 0.0
    best_label = ""
    for item in history:
        reference = " ".join(part for part in [item.topic, item.title, item.excerpt] if part).strip()
        if not reference:
            continue
        if item.topic and item.topic.casefold() == article.topic.casefold():
            return 1.0, item.topic
        if item.title and item.title.casefold() == article.title.casefold():
            return 1.0, item.title
        if item.slug and item.slug == article.slug:
            return 1.0, item.slug
        score = _similarity(candidate, reference)
        if score > best_score:
            best_score = score
            best_label = item.topic or item.title
    return best_score, best_label
