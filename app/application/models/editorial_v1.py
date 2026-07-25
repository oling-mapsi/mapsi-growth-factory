from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr

from app.application.models.editorial_agents import StrictModel


class EditorialClaim(StrictModel):
    text: StrictStr
    source_ids: list[StrictStr]
    claim_type: Literal["product_fact", "practice_fact", "generic_guidance", "editorial_positioning"]
    verified: StrictBool


class EditorialArticle(StrictModel):
    topic: StrictStr
    article_type: Literal["MAPSI_PRODUCT", "MAPSI_CONSULTING", "OLING_PRACTICE"]
    title: StrictStr
    slug: StrictStr
    excerpt: StrictStr
    body_html: StrictStr
    body_text: StrictStr
    meta_title: StrictStr
    meta_description: StrictStr
    target_personas: list[StrictStr]
    primary_keyword: StrictStr
    secondary_keywords: list[StrictStr]
    call_to_action_label: StrictStr
    call_to_action_url: StrictStr
    source_ids: list[StrictStr]
    claims: list[EditorialClaim]
    warnings: list[StrictStr] = Field(default_factory=list)


class EditorialSourceDescriptor(StrictModel):
    source_id: StrictStr
    source_type: Literal["knowledge_file", "product_change", "editorial_history"]
    label: StrictStr
    reference: StrictStr
    summary: StrictStr


class MapsiFeatureContext(StrictModel):
    feature_id: StrictStr
    module: StrictStr
    title: StrictStr
    short_description: StrictStr
    business_problem: StrictStr
    functional_description: StrictStr
    user_benefits: list[StrictStr]
    typical_use_cases: list[StrictStr]
    target_roles: list[StrictStr]
    forbidden_claims: list[StrictStr]


class ProductChangeContext(StrictModel):
    product_change_id: StrictStr
    capability_key: StrictStr
    summary: StrictStr
    reference: StrictStr
    collected_at: datetime
    source_ids: list[StrictStr]


class OlingPracticeContext(StrictModel):
    practice_id: StrictStr
    title: StrictStr
    description: StrictStr
    common_client_problems: list[StrictStr]
    intervention_context: StrictStr
    oling_approach: StrictStr
    mission_steps: list[StrictStr]
    usual_deliverables: list[StrictStr]
    vigilance_points: list[StrictStr]
    success_factors: list[StrictStr]
    concerned_sectors: list[StrictStr]
    allowed_ctas: list[StrictStr]
    forbidden_claims: list[StrictStr]


class PublishedArticleContext(StrictModel):
    topic: StrictStr
    objective: StrictStr
    audience_segment_id: StrictStr
    title: StrictStr = ""
    slug: StrictStr = ""
    excerpt: StrictStr = ""
    created_at: datetime


class EditorialGenerationContext(StrictModel):
    topic: StrictStr
    article_type: Literal["MAPSI_PRODUCT", "MAPSI_CONSULTING", "OLING_PRACTICE"]
    destination_site: Literal["mapsi.fr", "oling.fr"]
    target_personas: list[StrictStr]
    knowledge_version: StrictStr
    positioning: StrictStr
    terminology: StrictStr = ""
    target_clients: StrictStr = ""
    differentiators: StrictStr = ""
    editorial_rules: StrictStr
    forbidden_claims: list[StrictStr]
    mapsi_feature: MapsiFeatureContext | None = None
    recent_product_changes: list[ProductChangeContext] = Field(default_factory=list)
    oling_practice: OlingPracticeContext | None = None
    published_topic_history: list[PublishedArticleContext] = Field(default_factory=list)
    sources: list[EditorialSourceDescriptor]
    rewrite_instruction: StrictStr = ""
    desired_title: StrictStr = ""
    length_directive: Literal["", "shorter", "longer"] = ""
    angle_directive: StrictStr = ""


class EditorialBuilderSelection(StrictModel):
    topic_key: StrictStr
    topic: StrictStr
    selection_type: Literal["product_change", "feature_catalog", "oling_practice"]
    source_ids: list[StrictStr]
    rationale: list[StrictStr] = Field(default_factory=list)


class EditorialGenerationResult(StrictModel):
    context: EditorialGenerationContext
    record: EditorialGenerationRecord
    selection: EditorialBuilderSelection | None = None


class EditorialQualityIssue(StrictModel):
    code: StrictStr
    message: StrictStr
    severity: Literal["error", "warning"]


class EditorialQualityReport(StrictModel):
    passed: StrictBool
    issues: list[EditorialQualityIssue]
    similarity_score: StrictFloat = 0.0
    closest_match: StrictStr = ""


class EditorialGenerationRecord(StrictModel):
    article: EditorialArticle
    quality: EditorialQualityReport
    model_name: StrictStr
    prompt_version: StrictStr
    knowledge_version: StrictStr
    input_hash: StrictStr
    output_hash: StrictStr
    input_tokens: StrictInt = 0
    output_tokens: StrictInt = 0
    total_tokens: StrictInt = 0
    estimated_cost_usd: StrictFloat = 0.0
    duration_ms: StrictInt = 0
    provider_type: StrictStr
