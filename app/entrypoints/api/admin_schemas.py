from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StudioAdminPaginationResponse(BaseModel):
    page: int
    page_size: int
    total: int


class StudioAdminEnvelope(BaseModel):
    correlation_id: str


class StudioAdminLastEventResponse(BaseModel):
    id: str
    campaign_id: str
    event_type: str
    created_at: datetime
    payload: dict[str, Any]


class StudioAdminCampaignResponse(BaseModel):
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
    last_event: StudioAdminLastEventResponse | None
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "camp-123",
                "title": "Weekly Adoption Push",
                "objective": "feature_adoption",
                "status": "APPROVED",
                "created_at": "2026-07-12T10:00:00Z",
                "scheduled_at": "2026-07-13T08:00:00Z",
                "asset_count": 3,
                "assets_pending_validation": 1,
                "assets_approved": 1,
                "assets_published": 1,
                "assets_in_error": 0,
                "last_event": {
                    "id": "evt-1",
                    "campaign_id": "camp-123",
                    "event_type": "review.approved",
                    "created_at": "2026-07-12T10:30:00Z",
                    "payload": {"actor": "admin"},
                },
            }
        }
    )


class StudioAdminApprovalResponse(BaseModel):
    status: str
    approved_by: str
    approved_at: datetime | None


class StudioAdminAssetResponse(BaseModel):
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
    quality: dict[str, Any]
    approval: StudioAdminApprovalResponse
    preview_available: bool
    publication_available: bool
    public_url: str
    last_error_message: str
    published_at: datetime | None
    created_at: datetime
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "asset-123",
                "campaign_id": "camp-123",
                "campaign_title": "Weekly Adoption Push",
                "channel": "oling",
                "asset_type": "website_article",
                "title": "What changed in MAPSI Studio",
                "status": "PUBLISHED",
                "version": 2,
                "content_hash": "sha256-current",
                "approved_content_hash": "sha256-approved",
                "quality": {"passed": True, "score": 96},
                "approval": {"status": "approved", "approved_by": "studio-admin", "approved_at": "2026-07-12T10:25:00Z"},
                "preview_available": True,
                "publication_available": True,
                "public_url": "https://www.oling.fr/ressources/mapsi-studio",
                "last_error_message": "",
                "published_at": "2026-07-12T11:00:00Z",
                "created_at": "2026-07-12T09:45:00Z",
            }
        }
    )


class StudioAdminAssetVersionResponse(BaseModel):
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
    metadata: dict[str, Any]


class StudioAdminEvidenceResponse(BaseModel):
    source_type: str
    reference: str
    description: str
    confidence_level: str
    link: str
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "source_type": "github",
                "reference": "MAPSI-2026-010",
                "description": "PR produit communiquable",
                "confidence_level": "high",
                "link": "https://github.com/oling-mapsi/mapsi-v6/pull/2101",
            }
        }
    )


class StudioAdminPreviewResponse(BaseModel):
    asset_id: str
    available: bool
    preview_url: str
    preview_type: str
    generated_at: datetime | None
    metadata: dict[str, Any]
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "asset_id": "asset-123",
                "available": True,
                "preview_url": "https://preview.oling.test/mapsi-studio",
                "preview_type": "remote_url",
                "generated_at": "2026-07-12T10:40:00Z",
                "metadata": {"channel": "oling"},
            }
        }
    )


class StudioAdminPublicationResponse(BaseModel):
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
    metadata: dict[str, Any]
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "asset_id": "asset-123",
                "available": True,
                "publisher_type": "oling_api",
                "publication_mode_requested": "publish",
                "publication_mode_executed": "live",
                "publication_status": "PUBLISHED",
                "external_publication_id": "asset-123",
                "external_publication_url": "https://www.oling.fr/ressources/mapsi-studio",
                "idempotency_key": "oling:asset-123:sha256-current",
                "published_at": "2026-07-12T11:00:00Z",
                "metadata": {"published_revision_number": 2},
            }
        }
    )


class StudioAdminChannelResponse(BaseModel):
    key: str
    label: str
    asset_types: list[str]
    supports_preview: bool
    supports_publication: bool
    enabled: bool
    configured: bool
    credentials_valid: bool
    feature_enabled: bool
    emergency_kill_switch: bool
    sandbox_available: bool
    real_publisher_available: bool
    last_health_check: datetime | None
    last_successful_publication: datetime | None
    last_error: str
    updated_by: str
    updated_at: datetime | None
    activation_expires_at: datetime | None
    operational_mode: str = "safe"
    banner_message: str = ""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "key": "oling",
                "label": "Oling",
                "asset_types": ["website_article", "website_cta"],
                "supports_preview": True,
                "supports_publication": True,
                "enabled": True,
                "configured": True,
                "credentials_valid": True,
                "feature_enabled": True,
                "emergency_kill_switch": False,
                "sandbox_available": True,
                "real_publisher_available": True,
                "last_health_check": "2026-07-12T11:00:00Z",
                "last_successful_publication": "2026-07-12T10:45:00Z",
                "last_error": "",
                "updated_by": "studio-user-1",
                "updated_at": "2026-07-12T11:00:00Z",
                "activation_expires_at": "2026-07-12T11:30:00Z",
                "operational_mode": "pilot",
                "banner_message": "MODE PILOTE",
            }
        }
    )


class StudioAdminChannelMutationRequest(BaseModel):
    expires_in_minutes: int | None = Field(default=None, ge=1, le=1440)
    confirmation: str = ""


class StudioAdminGlobalKillSwitchResponse(BaseModel):
    active: bool
    updated_by: str
    updated_at: datetime | None
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "active": False,
                "updated_by": "studio-user-1",
                "updated_at": "2026-07-12T11:00:00Z",
            }
        }
    )


class StudioAdminAuditEventResponse(BaseModel):
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
    previous_state: dict[str, Any]
    new_state: dict[str, Any]
    metadata: dict[str, Any]
    result: str
    channel: str
    source_ip: str
    integrity_hash: str
    previous_integrity_hash: str
    integrity_ok: bool
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "event_id": "evt-1",
                "campaign_id": "camp-123",
                "asset_id": "asset-123",
                "actor_id": "studio-user-1",
                "actor_source": "mapsi-studio",
                "actor_roles": ["ROLE_GROWTH_PUBLISH"],
                "event_type": "publication.published",
                "timestamp": "2026-07-12T11:00:00Z",
                "correlation_id": "corr-123",
                "idempotency_key": "pub-1",
                "previous_state": {"status": "APPROVED"},
                "new_state": {"status": "PUBLISHED"},
                "metadata": {"external_id": "oling-42"},
                "result": "SUCCESS",
                "channel": "oling",
                "source_ip": "10.0.0.1",
                "integrity_hash": "abc123",
                "previous_integrity_hash": "",
                "integrity_ok": True,
            }
        }
    )


class StudioAdminDashboardResponse(BaseModel):
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
    last_event: StudioAdminLastEventResponse | None
    operational_mode: str = "safe"
    banner_message: str = ""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "campaigns_total": 12,
                "campaigns_pending_validation": 2,
                "campaigns_approved": 3,
                "campaigns_published": 5,
                "campaigns_in_error": 1,
                "assets_total": 24,
                "assets_pending_validation": 4,
                "assets_approved": 6,
                "assets_published": 10,
                "assets_in_error": 1,
                "last_event": {
                    "id": "evt-99",
                    "campaign_id": "camp-123",
                    "event_type": "campaign.oling_published",
                    "created_at": "2026-07-12T11:00:00Z",
                    "payload": {"asset_id": "asset-123"},
                },
                "operational_mode": "pilot",
                "banner_message": "MODE PILOTE",
            }
        }
    )


class StudioAdminHealthResponse(BaseModel):
    status: str
    app_version: str
    contract_version: str
    timestamp: datetime
    operational_mode: str = "safe"
    banner_message: str = ""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "ok",
                "app_version": "0.1.0",
                "contract_version": "1.0.0",
                "timestamp": "2026-07-12T11:00:00Z",
                "operational_mode": "pilot",
                "banner_message": "MODE PILOTE",
            }
        }
    )


class StudioAdminExpectedVersionRequest(BaseModel):
    expected_version: int = Field(..., ge=1)
    comment: str = ""


class StudioAdminAssetDraftUpdateRequest(StudioAdminExpectedVersionRequest):
    title: str | None = None
    subject: str | None = None
    content_html: str | None = None
    content_text: str | None = None
    excerpt: str | None = None
    call_to_action: str | None = None
    target_url: str | None = None


class StudioAdminAssetDecisionRequest(StudioAdminExpectedVersionRequest):
    pass


class StudioAdminAssetCommentDecisionRequest(StudioAdminExpectedVersionRequest):
    comment: str = Field(..., min_length=1)


class StudioAdminBulkDecisionRequest(BaseModel):
    comment: str = ""


class StudioAdminBulkCommentDecisionRequest(BaseModel):
    comment: str = Field(..., min_length=1)


class StudioAdminBulkDecisionResponse(BaseModel):
    campaign_id: str
    decision: str
    comment: str
    processed_at: datetime
    assets: list[StudioAdminAssetResponse]


class StudioAdminPublicationOperationRequest(BaseModel):
    scheduled_at: datetime | None = None
    comment: str = ""


class StudioAdminPublicationRequest(StudioAdminPublicationOperationRequest):
    idempotency_key: str = Field(..., min_length=1)


class StudioAdminPublicationOperationResponse(BaseModel):
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
    error_code: str
    error_message: str
    retryable: bool
    correlation_id: str
    metadata: dict[str, Any]
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "operation_id": "op-asset-123-publish",
                "asset_id": "asset-123",
                "channel": "oling",
                "requested_action": "publish",
                "status": "published",
                "publisher": "oling_api",
                "external_id": "asset-123",
                "preview_url": "https://preview.oling.test/mapsi-studio",
                "public_url": "https://www.oling.fr/ressources/mapsi-studio",
                "scheduled_at": "2026-07-13T08:00:00Z",
                "published_at": "2026-07-13T08:01:00Z",
                "error_code": "",
                "error_message": "",
                "retryable": False,
                "correlation_id": "corr-123",
                "metadata": {"publication_status": "PUBLISHED"},
            }
        }
    )


class StudioAdminWeeklyPackCampaignResponse(BaseModel):
    id: str
    campaign_type: str
    title: str
    status: str
    asset_count: int
    published_assets: int
    errors: list[str]


class StudioAdminWeeklyPackResponse(BaseModel):
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
    campaigns: list[StudioAdminWeeklyPackCampaignResponse]
    global_summary: dict[str, Any]
    operational_errors: list[dict[str, Any]]
    pilot_mode: bool
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "pack-2026-w29",
                "week_reference": "2026-W29",
                "year": 2026,
                "week_number": 29,
                "status": "PARTIALLY_COMPLETED",
                "created_at": "2026-07-13T08:00:00Z",
                "generated_at": "2026-07-13T08:05:00Z",
                "reviewed_at": None,
                "completed_at": None,
                "campaign_ids": ["camp-market", "camp-practice", "camp-users"],
                "campaigns": [
                    {
                        "id": "camp-market",
                        "campaign_type": "MAPSI_MARKET",
                        "title": "MAPSI Market 2026-W29",
                        "status": "READY_FOR_REVIEW",
                        "asset_count": 3,
                        "published_assets": 0,
                        "errors": [],
                    }
                ],
                "global_summary": {"campaigns_total": 3, "campaigns_generated": 2},
                "operational_errors": [],
                "pilot_mode": True,
            }
        }
    )


class StudioAdminWeeklyPackCreateRequest(BaseModel):
    week_reference: str = Field(..., min_length=1)
    year: int = Field(..., ge=2024, le=2100)
    week_number: int = Field(..., ge=1, le=53)
    pilot_mode: bool = False
    force_manual: bool = False


class StudioAdminWeeklyPackGenerateRequest(BaseModel):
    comment: str = ""


class StudioAdminEditorialSourceAttachmentReferenceResponse(BaseModel):
    id: str
    source_item_id: str
    file_name: str
    media_type: str
    storage_reference: str
    source_url: str
    content_hash: str
    created_at: datetime


class StudioAdminEditorialSourceItemResponse(BaseModel):
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
    manual_input: dict[str, Any]
    attachments: list[StudioAdminEditorialSourceAttachmentReferenceResponse]


class StudioAdminEditorialSourcePackResponse(BaseModel):
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
    items: list[StudioAdminEditorialSourceItemResponse]
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "sp-1",
                "weekly_pack_id": "pack-2026-w29",
                "campaign_type": "MAPSI_MARKET",
                "title": "Sources MAPSI market",
                "summary": "Synthese hebdomadaire verifiable.",
                "status": "VALIDATED",
                "confidentiality_level": "INTERNAL",
                "created_by": "studio-user-1",
                "created_at": "2026-07-13T10:00:00Z",
                "validated_by": "studio-user-2",
                "validated_at": "2026-07-13T10:30:00Z",
                "items": [],
            }
        }
    )


class StudioAdminEditorialPreviewFactResponse(BaseModel):
    source_item_id: str
    source_type: str
    fact: str
    mode: str
    reason: str


class StudioAdminEditorialSourcePreviewResponse(BaseModel):
    source_pack_id: str
    allowed_facts: list[StudioAdminEditorialPreviewFactResponse]
    blocked_facts: list[StudioAdminEditorialPreviewFactResponse]
    redaction_summary: dict[str, Any]


class StudioAdminSourcePackRequest(BaseModel):
    weekly_pack_id: str = ""
    campaign_type: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    summary: str = ""
    confidentiality_level: str = "INTERNAL"


class StudioAdminSourcePackValidateRequest(BaseModel):
    comment: str = ""


class StudioAdminManualSourceInput(BaseModel):
    project_summary: str = ""
    client_problem: str = ""
    oling_method: str = ""
    deliverables_completed: list[str] = Field(default_factory=list)
    observed_results: list[str] = Field(default_factory=list)
    lessons_learned: list[str] = Field(default_factory=list)
    desired_cta: str = ""


class StudioAdminSourceItemRequest(BaseModel):
    source_type: str = Field(..., min_length=1)
    source_reference: str = ""
    source_title: str = ""
    source_date: datetime | None = None
    source_author: str = ""
    factual_summary: str = ""
    usable_facts: list[str] = Field(default_factory=list)
    anonymized_facts: list[str] = Field(default_factory=list)
    prohibited_facts: list[str] = Field(default_factory=list)
    client_name: str = ""
    client_name_usage_authorized: bool = False
    confidentiality_level: str = "INTERNAL"
    evidence_quality: str = "medium"
    source_url: str = ""
    external_source_id: str = ""
    manual_input: StudioAdminManualSourceInput | None = None


class StudioAdminDashboardEnvelope(StudioAdminEnvelope):
    data: StudioAdminDashboardResponse


class StudioAdminCampaignListEnvelope(StudioAdminEnvelope):
    data: list[StudioAdminCampaignResponse]
    pagination: StudioAdminPaginationResponse


class StudioAdminCampaignEnvelope(StudioAdminEnvelope):
    data: StudioAdminCampaignResponse


class StudioAdminWeeklyPackListEnvelope(StudioAdminEnvelope):
    data: list[StudioAdminWeeklyPackResponse]
    pagination: StudioAdminPaginationResponse


class StudioAdminWeeklyPackEnvelope(StudioAdminEnvelope):
    data: StudioAdminWeeklyPackResponse


class StudioAdminEditorialSourcePackEnvelope(StudioAdminEnvelope):
    data: StudioAdminEditorialSourcePackResponse


class StudioAdminEditorialSourcePreviewEnvelope(StudioAdminEnvelope):
    data: StudioAdminEditorialSourcePreviewResponse


class StudioAdminAssetListEnvelope(StudioAdminEnvelope):
    data: list[StudioAdminAssetResponse]
    pagination: StudioAdminPaginationResponse


class StudioAdminAssetEnvelope(StudioAdminEnvelope):
    data: StudioAdminAssetResponse


class StudioAdminAssetVersionListEnvelope(StudioAdminEnvelope):
    data: list[StudioAdminAssetVersionResponse]


class StudioAdminEvidenceListEnvelope(StudioAdminEnvelope):
    data: list[StudioAdminEvidenceResponse]


class StudioAdminPreviewEnvelope(StudioAdminEnvelope):
    data: StudioAdminPreviewResponse


class StudioAdminPublicationEnvelope(StudioAdminEnvelope):
    data: StudioAdminPublicationResponse


class StudioAdminChannelListEnvelope(StudioAdminEnvelope):
    data: list[StudioAdminChannelResponse]


class StudioAdminChannelEnvelope(StudioAdminEnvelope):
    data: StudioAdminChannelResponse


class StudioAdminAuditEventListEnvelope(StudioAdminEnvelope):
    data: list[StudioAdminAuditEventResponse]
    pagination: StudioAdminPaginationResponse


class StudioAdminHealthEnvelope(StudioAdminEnvelope):
    data: StudioAdminHealthResponse


class StudioAdminErrorResponse(BaseModel):
    correlation_id: str
    detail: str


class StudioAdminBulkDecisionEnvelope(StudioAdminEnvelope):
    data: StudioAdminBulkDecisionResponse


class StudioAdminPublicationOperationEnvelope(StudioAdminEnvelope):
    data: StudioAdminPublicationOperationResponse


class StudioAdminGlobalKillSwitchEnvelope(StudioAdminEnvelope):
    data: StudioAdminGlobalKillSwitchResponse


class StudioAdminListQuery(BaseModel):
    status: str | None = None
    channel: str | None = None
    asset_type: str | None = None
    campaign_id: str | None = Field(default=None, alias="campaign")
    period_from: datetime | None = None
    period_to: datetime | None = None
    published: bool | None = None
    in_error: bool | None = None
    pending_validation: bool | None = None
    page: int = 1
    page_size: int = 20
    sort_by: str = "created_at"
    sort_order: str = "desc"
