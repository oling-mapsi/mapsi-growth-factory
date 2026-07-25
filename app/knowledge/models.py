from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from app.domain.entities import ProductChange


@dataclass(frozen=True)
class MapsiFeature:
    feature_id: str
    module: str
    title: str
    short_description: str
    business_problem: str
    functional_description: str
    user_benefits: list[str] = field(default_factory=list)
    typical_use_cases: list[str] = field(default_factory=list)
    target_roles: list[str] = field(default_factory=list)
    communication_priority: int = 100
    communication_enabled: bool = True
    minimum_repeat_delay_days: int = 14
    source_references: list[str] = field(default_factory=list)
    forbidden_claims: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class OlingPractice:
    practice_id: str
    title: str
    description: str
    common_client_problems: list[str]
    intervention_context: str
    oling_approach: str
    mission_steps: list[str]
    usual_deliverables: list[str]
    vigilance_points: list[str]
    success_factors: list[str]
    concerned_sectors: list[str]
    allowed_ctas: list[str]
    forbidden_claims: list[str]
    sources: list[str]


@dataclass(frozen=True)
class EditorialRules:
    mapsi_product_positioning: str
    mapsi_terminology: str
    mapsi_target_personas: str
    mapsi_forbidden_claims: str
    oling_company_profile: str
    oling_editorial_style: str
    oling_target_clients: str
    oling_differentiators: str
    oling_forbidden_claims: str
    knowledge_version_hash: str


@dataclass(frozen=True)
class PublishedTopicHistoryEntry:
    topic: str
    objective: str
    audience_segment_id: str
    created_at: datetime


@dataclass(frozen=True)
class KnowledgeValidationResult:
    ok: bool
    version_hash: str
    checked_files: list[str]
    errors: list[str]
    mapsi_feature_ids: list[str]
    oling_practice_ids: list[str]


@dataclass(frozen=True)
class KnowledgeSnapshot:
    mapsi_features: list[MapsiFeature]
    oling_practices: list[OlingPractice]
    version_hash: str


@dataclass(frozen=True)
class MapsiKnowledgeQuery:
    since: date
    product_changes: list[ProductChange]
