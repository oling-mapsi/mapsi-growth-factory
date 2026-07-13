from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class EvidenceReference(StrictModel):
    evidence_id: StrictStr
    source_system: StrictStr
    reference: StrictStr
    summary: StrictStr
    deployed: StrictBool
    client_scope: Literal["global", "restricted"]


class ProductFeatureInput(StrictModel):
    capability_key: StrictStr
    summary: StrictStr
    module_key: StrictStr
    eligible_for_communication: StrictBool
    confidential: StrictBool
    client_scope: Literal["global", "restricted"]
    evidence_ids: list[StrictStr]
    deployed: StrictBool
    restrictions: list[StrictStr]


class ProductIntelligenceInput(StrictModel):
    features: list[ProductFeatureInput]
    evidences: list[EvidenceReference]
    allowed_segments: list[StrictStr]


class ProductCandidateOutput(StrictModel):
    capability_key: StrictStr
    candidate_feature: StrictStr
    user_benefit: StrictStr
    evidence_ids: list[StrictStr]
    restrictions: list[StrictStr]


class ProductIntelligenceOutput(StrictModel):
    candidates: list[ProductCandidateOutput]


class SegmentUsageInput(StrictModel):
    segment_id: StrictStr
    eligible_volume: StrictInt
    role_distribution: dict[StrictStr, StrictInt]
    module_distribution: dict[StrictStr, StrictInt]
    adoption_signals: dict[StrictStr, StrictInt]


class UsageIntelligenceInput(StrictModel):
    segments: list[SegmentUsageInput]


class SegmentRecommendation(StrictModel):
    segment_id: StrictStr
    usage_problem: StrictStr
    education_opportunity: StrictStr


class UsageIntelligenceOutput(StrictModel):
    recommendations: list[SegmentRecommendation]


class EnabledSegmentReference(StrictModel):
    segment_id: StrictStr
    label: StrictStr
    legal_basis: StrictStr
    enabled: StrictBool


class ThemeHistoryEntry(StrictModel):
    topic: StrictStr
    created_at: datetime


class EditorialStrategyInput(StrictModel):
    product_candidates: list[ProductCandidateOutput]
    usage_recommendations: list[SegmentRecommendation]
    enabled_segments: list[EnabledSegmentReference]
    theme_history: list[ThemeHistoryEntry]


class EditorialStrategyOutput(StrictModel):
    topic: StrictStr
    objective: Literal["feature_adoption", "reactivation", "education"]
    audience_segment_id: StrictStr
    evidence_ids: list[StrictStr]
    key_messages: list[StrictStr]
    cta_type: Literal["open_feature", "read_guide", "watch_demo"]


class CustomerEmailWriterInput(StrictModel):
    topic: StrictStr
    objective: StrictStr
    audience_segment_id: StrictStr
    key_messages: list[StrictStr]
    cta_type: StrictStr
    evidences: list[EvidenceReference]


class CustomerEmailWriterOutput(StrictModel):
    subject: StrictStr
    preheader: StrictStr
    headline: StrictStr
    introduction: StrictStr
    body_html: StrictStr
    body_text: StrictStr
    cta_label: StrictStr
    cta_url_template: StrictStr
    evidence_ids: list[StrictStr]


class QualityControlInput(StrictModel):
    strategy: EditorialStrategyOutput
    email: CustomerEmailWriterOutput
    evidences: list[EvidenceReference]
    enabled_segments: list[EnabledSegmentReference]


class QualityIssue(StrictModel):
    code: StrictStr
    message: StrictStr
    severity: Literal["error", "warning"]


class QualityControlOutput(StrictModel):
    passed: StrictBool
    issues: list[QualityIssue]


class AgentExecutionRecord(StrictModel):
    agent_name: StrictStr
    model_name: StrictStr
    prompt_version: StrictStr
    temperature: float = Field(default=0.0)


class EditorialTokenUsage(StrictModel):
    input_tokens: StrictInt = 0
    output_tokens: StrictInt = 0
    total_tokens: StrictInt = 0


class EditorialExecutionMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_name: str
    provider_type: Literal["simulated", "openai", "fake"]
    model_name: str
    prompt_version: str
    schema_name: str
    schema_version: str = "v1"
    execution_params: dict[str, Any] = Field(default_factory=dict)
    token_usage: EditorialTokenUsage = Field(default_factory=EditorialTokenUsage)


class EditorialEvaluationResult(StrictModel):
    name: StrictStr
    passed: StrictBool
    details: dict[str, Any] = Field(default_factory=dict)


class EditorialConsumptionSummary(StrictModel):
    budget_tokens: StrictInt
    used_tokens: StrictInt
    remaining_tokens: StrictInt
    mode: Literal["simulated", "real"]


class BenefitClaim(StrictModel):
    statement: StrictStr
    claim_type: Literal["demonstrated", "expected"]
    evidence_ids: list[StrictStr]


class MarketEditorialStrategyInput(StrictModel):
    topic: StrictStr
    objective: StrictStr
    audience_segment_id: StrictStr
    evidences: list[EvidenceReference]
    authorized_client_mentions: list[StrictStr]


class MarketChannelPlan(StrictModel):
    asset_type: Literal[
        "mapsi_user_email",
        "prospect_newsletter",
        "linkedin_company_post",
        "linkedin_personal_draft",
        "website_article",
        "oling_news_article",
        "mapsi_news_article",
        "mapsi_studio_news",
        "mapsi_studio_tip",
        "website_cta",
        "demonstration_landing_page",
    ]
    title: StrictStr
    angle: StrictStr
    audience_segment_id: StrictStr
    evidence_ids: list[StrictStr]
    benefits: list[BenefitClaim]
    client_mentions: list[StrictStr]


class MarketEditorialStrategyOutput(StrictModel):
    plans: list[MarketChannelPlan]


class NewsletterWriterInput(StrictModel):
    plan: MarketChannelPlan
    evidences: list[EvidenceReference]


class NewsletterWriterOutput(StrictModel):
    subject: StrictStr
    preheader: StrictStr
    body_html: StrictStr
    body_text: StrictStr
    cta_label: StrictStr
    cta_url_template: StrictStr
    evidence_ids: list[StrictStr]


class LinkedInWriterInput(StrictModel):
    plan: MarketChannelPlan
    evidences: list[EvidenceReference]


class LinkedInWriterOutput(StrictModel):
    post_text: StrictStr
    hook: StrictStr
    cta_label: StrictStr
    cta_url_template: StrictStr
    evidence_ids: list[StrictStr]


class WebsiteArticleWriterInput(StrictModel):
    plan: MarketChannelPlan
    evidences: list[EvidenceReference]


class WebsiteArticleWriterOutput(StrictModel):
    headline: StrictStr
    summary: StrictStr
    body_html: StrictStr
    body_text: StrictStr
    seo_title: StrictStr
    meta_description: StrictStr
    cta_label: StrictStr
    cta_url_template: StrictStr
    evidence_ids: list[StrictStr]


class SeoQualityInput(StrictModel):
    article: WebsiteArticleWriterOutput
    evidences: list[EvidenceReference]
    allowed_client_mentions: list[StrictStr]


class SeoQualityOutput(StrictModel):
    passed: StrictBool
    issues: list[QualityIssue]


class MapsiMarketEditorialBrief(StrictModel):
    selected_topic: StrictStr
    objective: StrictStr
    product_change_ids: list[StrictStr]
    source_evidence_ids: list[StrictStr]
    target_personas: list[StrictStr]
    market_problem: StrictStr
    key_messages: list[StrictStr]
    oling_angle: StrictStr
    mapsi_angle: StrictStr
    linkedin_angle: StrictStr
    primary_cta: StrictStr
    canonical_article_target: Literal["oling.fr", "mapsi.fr"]
    risks: list[StrictStr]
    prohibited_claims: list[StrictStr]


class OlingPracticeEditorialBrief(StrictModel):
    practice: StrictStr
    business_problem: StrictStr
    project_context: StrictStr
    anonymization_required: StrictBool
    authorized_client_name: StrictStr = ""
    approach: StrictStr
    deliverables: list[StrictStr]
    lessons_learned: list[StrictStr]
    demonstrated_results: list[StrictStr]
    unverified_claims_to_exclude: list[StrictStr]
    target_personas: list[StrictStr]
    article_angle: StrictStr
    linkedin_angle: StrictStr
    CTA: StrictStr
    source_evidence_ids: list[StrictStr]


class MapsiUserWeeklyEmailContent(StrictModel):
    email_type: Literal["NEW_FEATURE", "FEATURE_REMINDER", "TIP", "ONBOARDING", "REACTIVATION", "WORKFLOW_GUIDE"]
    subject: StrictStr
    preheader: StrictStr
    title: StrictStr
    introduction: StrictStr
    main_tip: StrictStr
    steps: list[StrictStr]
    expected_benefit: StrictStr
    call_to_action: StrictStr
    deep_link: StrictStr = ""
    body_html: StrictStr
    body_text: StrictStr
    source_evidence_ids: list[StrictStr]
    target_segment_id: StrictStr
