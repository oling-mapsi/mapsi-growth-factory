from __future__ import annotations

import json

from pydantic import BaseModel

from app.application.models.editorial_agents import (
    EditorialExecutionMetadata,
    EditorialTokenUsage,
    CustomerEmailWriterOutput,
    EditorialStrategyOutput,
    LinkedInWriterOutput,
    MarketEditorialStrategyOutput,
    NewsletterWriterOutput,
    ProductIntelligenceOutput,
    QualityControlOutput,
    QualityIssue,
    SeoQualityOutput,
    UsageIntelligenceOutput,
    WebsiteArticleWriterOutput,
)
from app.application.ports.editorial_agents import EditorialRunResult, OutputModelT, StructuredAgentBackendPort


class SimulatedEditorialBackend(StructuredAgentBackendPort):
    def run_structured(
        self,
        *,
        agent_name: str,
        prompt: str,
        input_model: BaseModel,
        output_type: type[OutputModelT],
        model_name: str,
        prompt_version: str,
        temperature: float,
    ) -> EditorialRunResult[OutputModelT]:
        if output_type is ProductIntelligenceOutput:
            feature = input_model.features[0]
            payload = {
                "candidates": [
                    {
                        "capability_key": feature.capability_key,
                        "candidate_feature": feature.summary,
                        "user_benefit": f"Adopter {feature.capability_key} avec moins de friction.",
                        "evidence_ids": feature.evidence_ids,
                        "restrictions": feature.restrictions,
                    }
                ]
            }
        elif output_type is UsageIntelligenceOutput:
            segment = input_model.segments[0]
            payload = {
                "recommendations": [
                    {
                        "segment_id": segment.segment_id,
                        "usage_problem": "Usage partiel de la fonctionnalite cle.",
                        "education_opportunity": "Montrer un cas d'usage concret et une action simple.",
                    }
                ]
            }
        elif output_type is EditorialStrategyOutput:
            candidate = input_model.product_candidates[0]
            recommendation = input_model.usage_recommendations[0]
            payload = {
                "topic": candidate.candidate_feature,
                "objective": "feature_adoption",
                "audience_segment_id": recommendation.segment_id,
                "evidence_ids": candidate.evidence_ids,
                "key_messages": [
                    candidate.user_benefit,
                    recommendation.education_opportunity,
                ],
                "cta_type": "open_feature",
            }
        elif output_type is CustomerEmailWriterOutput:
            payload = {
                "subject": input_model.topic,
                "preheader": "Un usage simple a activer cette semaine",
                "headline": input_model.topic,
                "introduction": "Voici un cas d'usage concret pour gagner du temps.",
                "body_html": "<p>Voici un cas d'usage concret pour gagner du temps.</p>",
                "body_text": "Voici un cas d'usage concret pour gagner du temps.",
                "cta_label": "Ouvrir la fonctionnalite",
                "cta_url_template": "https://mapsi.example/features/{feature}",
                "evidence_ids": [evidence.evidence_id for evidence in input_model.evidences],
            }
        elif output_type is QualityControlOutput:
            payload = {"passed": True, "issues": []}
        elif output_type is MarketEditorialStrategyOutput:
            evidence_ids = [evidence.evidence_id for evidence in input_model.evidences[:1]]
            payload = {
                "plans": [
                    {
                        "asset_type": "mapsi_user_email",
                        "title": f"{input_model.topic} activation utilisateur",
                        "angle": "Activation simple cote utilisateurs",
                        "audience_segment_id": input_model.audience_segment_id,
                        "evidence_ids": evidence_ids,
                        "benefits": [{"statement": "Action produit demontree", "claim_type": "demonstrated", "evidence_ids": evidence_ids}],
                        "client_mentions": [],
                    },
                    {
                        "asset_type": "prospect_newsletter",
                        "title": f"{input_model.topic} newsletter",
                        "angle": "Pedagogie produit pour prospects",
                        "audience_segment_id": input_model.audience_segment_id,
                        "evidence_ids": evidence_ids,
                        "benefits": [{"statement": "Gain de temps observable", "claim_type": "demonstrated", "evidence_ids": evidence_ids}],
                        "client_mentions": [],
                    },
                    {
                        "asset_type": "linkedin_company_post",
                        "title": f"{input_model.topic} LinkedIn",
                        "angle": "Signal marche court",
                        "audience_segment_id": input_model.audience_segment_id,
                        "evidence_ids": evidence_ids,
                        "benefits": [{"statement": "Reduction attendue de friction", "claim_type": "expected", "evidence_ids": evidence_ids}],
                        "client_mentions": [],
                    },
                    {
                        "asset_type": "website_article",
                        "title": f"{input_model.topic} article",
                        "angle": "Explication longue avec preuve",
                        "audience_segment_id": input_model.audience_segment_id,
                        "evidence_ids": evidence_ids,
                        "benefits": [{"statement": "Cas d'usage demontre", "claim_type": "demonstrated", "evidence_ids": evidence_ids}],
                        "client_mentions": [],
                    },
                    {
                        "asset_type": "mapsi_news_article",
                        "title": f"{input_model.topic} article MAPSI",
                        "angle": "Article produit orienté adoption",
                        "audience_segment_id": input_model.audience_segment_id,
                        "evidence_ids": evidence_ids,
                        "benefits": [{"statement": "Evolution deployee", "claim_type": "demonstrated", "evidence_ids": evidence_ids}],
                        "client_mentions": [],
                    },
                    {
                        "asset_type": "mapsi_studio_news",
                        "title": f"{input_model.topic} studio",
                        "angle": "Annonce interne Studio",
                        "audience_segment_id": input_model.audience_segment_id,
                        "evidence_ids": evidence_ids,
                        "benefits": [{"statement": "Message internalise sans promesse", "claim_type": "demonstrated", "evidence_ids": evidence_ids}],
                        "client_mentions": [],
                    },
                    {
                        "asset_type": "oling_news_article",
                        "title": f"{input_model.topic} Oling",
                        "angle": "Version Oling orientee marche",
                        "audience_segment_id": input_model.audience_segment_id,
                        "evidence_ids": evidence_ids,
                        "benefits": [{"statement": "Valeur prouvee pour le marche", "claim_type": "demonstrated", "evidence_ids": evidence_ids}],
                        "client_mentions": [],
                    },
                ]
            }
        elif output_type is NewsletterWriterOutput:
            payload = {
                "subject": input_model.plan.title,
                "preheader": "Une nouveaute utile a comprendre",
                "body_html": "<p>Contenu newsletter prospect.</p>",
                "body_text": "Contenu newsletter prospect.",
                "cta_label": "Demander une demo",
                "cta_url_template": "https://oling.example/demo",
                "evidence_ids": input_model.plan.evidence_ids,
            }
        elif output_type is LinkedInWriterOutput:
            payload = {
                "post_text": "Un post LinkedIn factuel fonde sur des preuves.",
                "hook": input_model.plan.title,
                "cta_label": "Voir l'article",
                "cta_url_template": "https://oling.example/article",
                "evidence_ids": input_model.plan.evidence_ids,
            }
        elif output_type is WebsiteArticleWriterOutput:
            payload = {
                "headline": input_model.plan.title,
                "summary": "Article de fond oriente preuve et benefices.",
                "body_html": "<p>Article de fond oriente preuve et benefices.</p>",
                "body_text": "Article de fond oriente preuve et benefices.",
                "seo_title": input_model.plan.title,
                "meta_description": "Synthese d'une evolution produit fondee sur preuves.",
                "cta_label": "Demander une demonstration",
                "cta_url_template": "https://oling.example/demo",
                "evidence_ids": input_model.plan.evidence_ids,
            }
        elif output_type is SeoQualityOutput:
            payload = {"passed": True, "issues": []}
        else:
            raise ValueError(f"Unsupported simulated output type: {output_type}")
        output = output_type.model_validate(payload)
        usage = self._estimate_usage(prompt=prompt, input_model=input_model, payload=payload)
        return EditorialRunResult(
            output=output,
            metadata=EditorialExecutionMetadata(
                agent_name=agent_name,
                provider_type="simulated",
                model_name=model_name,
                prompt_version=prompt_version,
                schema_name=output_type.__name__,
                execution_params={"temperature": temperature},
                token_usage=usage,
            ),
        )

    def _estimate_usage(self, *, prompt: str, input_model: BaseModel, payload: dict) -> EditorialTokenUsage:
        input_tokens = self._estimate_tokens(prompt) + self._estimate_tokens(input_model.model_dump(mode="json"))
        output_tokens = self._estimate_tokens(payload)
        return EditorialTokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        )

    def _estimate_tokens(self, value) -> int:
        serialized = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        return max(1, len(serialized) // 4)
