from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class StudioAdminCampaignSummary:
    id: str
    title: str
    objective: str
    status: str
    created_at: datetime
    scheduled_at: datetime | None
    asset_count: int
    assets_pending_validation: int
    assets_approved: int
    assets_published: int
    assets_in_error: int
    last_event: dict[str, object] | None


@dataclass
class StudioAdminApproval:
    status: str
    approved_by: str = ""
    approved_at: datetime | None = None


@dataclass
class StudioAdminAssetSummary:
    id: str
    campaign_id: str
    campaign_title: str
    channel: str
    asset_type: str
    title: str
    status: str
    version: int
    content_hash: str
    approved_content_hash: str
    quality: dict[str, object]
    approval: StudioAdminApproval
    preview_available: bool
    publication_available: bool
    public_url: str
    last_error_message: str
    published_at: datetime | None
    created_at: datetime


@dataclass
class StudioAdminAssetVersion:
    version: int
    label: str
    status: str
    content_hash: str
    approved_content_hash: str
    published_at: datetime | None
    created_at: datetime | None
    title: str = ""
    subject: str = ""
    content_html: str = ""
    content_text: str = ""
    excerpt: str = ""
    call_to_action: str = ""
    target_url: str = ""
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class StudioAdminEvidence:
    source_type: str
    reference: str
    description: str
    confidence_level: str
    link: str = ""


@dataclass
class StudioAdminPreview:
    asset_id: str
    available: bool
    preview_url: str
    preview_type: str
    generated_at: datetime | None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class StudioAdminPublication:
    asset_id: str
    available: bool
    publisher_type: str
    publication_mode_requested: str
    publication_mode_executed: str
    publication_status: str
    external_publication_id: str
    external_publication_url: str
    idempotency_key: str
    published_at: datetime | None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class StudioAdminChannel:
    key: str
    label: str
    asset_types: list[str]
    supports_preview: bool
    supports_publication: bool
    enabled: bool
    configured: bool = False
    credentials_valid: bool = False
    feature_enabled: bool = False
    emergency_kill_switch: bool = False
    sandbox_available: bool = False
    real_publisher_available: bool = False
    last_health_check: datetime | None = None
    last_successful_publication: datetime | None = None
    last_error: str = ""
    updated_by: str = ""
    updated_at: datetime | None = None
    activation_expires_at: datetime | None = None
    operational_mode: str = "safe"
    banner_message: str = ""


@dataclass
class StudioAdminGlobalKillSwitch:
    active: bool
    updated_by: str = ""
    updated_at: datetime | None = None


@dataclass
class StudioAdminAuditEvent:
    event_id: str
    campaign_id: str
    asset_id: str
    actor_id: str
    actor_source: str
    actor_roles: list[str]
    event_type: str
    timestamp: datetime
    correlation_id: str
    idempotency_key: str
    previous_state: dict[str, object]
    new_state: dict[str, object]
    metadata: dict[str, object]
    result: str
    channel: str
    source_ip: str
    integrity_hash: str
    previous_integrity_hash: str
    integrity_ok: bool


@dataclass
class StudioAdminDashboard:
    campaigns_total: int
    campaigns_pending_validation: int
    campaigns_approved: int
    campaigns_published: int
    campaigns_in_error: int
    assets_total: int
    assets_pending_validation: int
    assets_approved: int
    assets_published: int
    assets_in_error: int
    last_event: dict[str, object] | None
    operational_mode: str = "safe"
    banner_message: str = ""


@dataclass
class StudioAdminHealth:
    status: str
    app_version: str
    contract_version: str
    timestamp: datetime
    operational_mode: str = "safe"
    banner_message: str = ""


@dataclass
class StudioAdminBulkDecisionResult:
    campaign_id: str
    decision: str
    comment: str
    processed_at: datetime
    assets: list[StudioAdminAssetSummary]


@dataclass
class StudioAdminPublicationOperation:
    operation_id: str
    asset_id: str
    channel: str
    requested_action: str
    status: str
    publisher: str
    external_id: str
    preview_url: str
    public_url: str
    scheduled_at: datetime | None
    published_at: datetime | None
    error_code: str = ""
    error_message: str = ""
    retryable: bool = False
    correlation_id: str = ""
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class StudioAdminWeeklyPackCampaign:
    id: str
    campaign_type: str
    title: str
    status: str
    asset_count: int
    published_assets: int
    errors: list[str] = field(default_factory=list)


@dataclass
class StudioAdminWeeklyPack:
    id: str
    week_reference: str
    year: int
    week_number: int
    status: str
    created_at: datetime
    generated_at: datetime | None
    reviewed_at: datetime | None
    completed_at: datetime | None
    campaign_ids: list[str]
    campaigns: list[StudioAdminWeeklyPackCampaign]
    global_summary: dict[str, object] = field(default_factory=dict)
    operational_errors: list[dict[str, object]] = field(default_factory=list)
    pilot_mode: bool = False


@dataclass
class StudioAdminEditorialSourceAttachmentReference:
    id: str
    source_item_id: str
    file_name: str
    media_type: str
    storage_reference: str
    source_url: str
    content_hash: str
    created_at: datetime


@dataclass
class StudioAdminEditorialSourceItem:
    id: str
    source_pack_id: str
    source_type: str
    source_reference: str
    source_title: str
    source_date: datetime | None
    source_author: str
    factual_summary: str
    usable_facts: list[str]
    anonymized_facts: list[str]
    prohibited_facts: list[str]
    client_name: str
    client_name_usage_authorized: bool
    confidentiality_level: str
    evidence_quality: str
    source_url: str
    external_source_id: str
    content_hash: str
    manual_input: dict[str, object] = field(default_factory=dict)
    attachments: list[StudioAdminEditorialSourceAttachmentReference] = field(default_factory=list)


@dataclass
class StudioAdminEditorialSourcePack:
    id: str
    weekly_pack_id: str
    campaign_type: str
    title: str
    summary: str
    status: str
    confidentiality_level: str
    created_by: str
    created_at: datetime
    validated_by: str
    validated_at: datetime | None
    items: list[StudioAdminEditorialSourceItem] = field(default_factory=list)


@dataclass
class StudioAdminEditorialPreviewFact:
    source_item_id: str
    source_type: str
    fact: str
    mode: str
    reason: str = ""


@dataclass
class StudioAdminEditorialSourcePreview:
    source_pack_id: str
    allowed_facts: list[StudioAdminEditorialPreviewFact] = field(default_factory=list)
    blocked_facts: list[StudioAdminEditorialPreviewFact] = field(default_factory=list)
    redaction_summary: dict[str, object] = field(default_factory=dict)
