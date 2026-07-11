from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from typing import Any
from uuid import uuid4

from app.domain.enums import AssetStatus, CampaignStatus
from app.domain.errors import (
    ApprovalPrerequisiteError,
    CampaignPublicationForbiddenError,
    InvalidStateTransitionError,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def build_content_hash(asset_type: str, title: str, body: str, evidence_ids: list[str], audience_segment_id: str) -> str:
    from app.core.security import sha256_hexdigest

    return sha256_hexdigest(
        json.dumps(
            {
                "asset_type": asset_type,
                "title": title,
                "body": body,
                "evidence_ids": evidence_ids,
                "audience_segment_id": audience_segment_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )


@dataclass
class EditorialBrief:
    id: str = field(default_factory=lambda: str(uuid4()))
    campaign_run_id: str = ""
    title: str = ""
    summary: str = ""
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class ContentAsset:
    id: str = field(default_factory=lambda: str(uuid4()))
    campaign_run_id: str = ""
    asset_type: str = "article"
    channel: str = "web"
    title: str = ""
    body: str = ""
    evidence_ids: list[str] = field(default_factory=list)
    audience_segment_id: str = ""
    status: AssetStatus = AssetStatus.DRAFT
    content_hash: str = ""
    approved_by: str = ""
    approved_at: datetime | None = None
    scheduled_at: datetime | None = None
    results: dict[str, Any] = field(default_factory=dict)
    revision: int = 1
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class AudienceSegment:
    id: str = field(default_factory=lambda: str(uuid4()))
    campaign_run_id: str = ""
    name: str = ""
    description: str = ""
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class ApprovalDecision:
    id: str = field(default_factory=lambda: str(uuid4()))
    campaign_run_id: str = ""
    decision: str = ""
    decided_by: str = ""
    comment: str = ""
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class Publication:
    id: str = field(default_factory=lambda: str(uuid4()))
    campaign_run_id: str = ""
    channel: str = ""
    external_reference: str = ""
    published_at: datetime = field(default_factory=utcnow)


@dataclass
class Interaction:
    id: str = field(default_factory=lambda: str(uuid4()))
    campaign_run_id: str = ""
    interaction_type: str = ""
    occurred_at: datetime = field(default_factory=utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Lead:
    id: str = field(default_factory=lambda: str(uuid4()))
    campaign_run_id: str = ""
    email: str = ""
    full_name: str = ""
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class SourceEvidence:
    id: str = field(default_factory=lambda: str(uuid4()))
    campaign_run_id: str = ""
    product_change_id: str = ""
    source_system: str = ""
    evidence_type: str = ""
    reference: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class RepositorySource:
    id: str = field(default_factory=lambda: str(uuid4()))
    full_name: str = ""
    installation_id: str = ""
    default_branch: str = "main"
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class RepositoryCursor:
    id: str = field(default_factory=lambda: str(uuid4()))
    repository_source_id: str = ""
    cursor_type: str = "weekly_poll"
    last_seen_sha: str = ""
    last_delivery_id: str = ""
    last_polled_at: datetime = field(default_factory=utcnow)


@dataclass
class ProductChange:
    id: str = field(default_factory=lambda: str(uuid4()))
    repository_source_id: str = ""
    repository_full_name: str = ""
    sha: str = ""
    pr_number: int | None = None
    issue_numbers: list[int] = field(default_factory=list)
    release_tag: str = ""
    deployment_ref: str = ""
    production_status: str = ""
    change_note_path: str = ""
    eligible_for_communication: bool = False
    confidential: bool = False
    target_client_key: str = ""
    capability_key: str = ""
    summary: str = ""
    contract_version: str = ""
    deployment_proven: bool = False
    collected_at: datetime = field(default_factory=utcnow)
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class WebhookDelivery:
    id: str = field(default_factory=lambda: str(uuid4()))
    delivery_id: str = ""
    event_type: str = ""
    repository_full_name: str = ""
    signature_valid: bool = False
    processed: bool = False
    status: str = "received"
    payload: dict[str, Any] = field(default_factory=dict)
    received_at: datetime = field(default_factory=utcnow)


@dataclass
class MapsiInstance:
    id: str = field(default_factory=lambda: str(uuid4()))
    instance_key: str = ""
    base_url: str = ""
    secret_ref: str = ""
    enabled: bool = True
    contract_version: str = ""
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class CustomerAccount:
    id: str = field(default_factory=lambda: str(uuid4()))
    mapsi_instance_id: str = ""
    external_account_id: str = ""
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class ContactIdentity:
    id: str = field(default_factory=lambda: str(uuid4()))
    email_hash: str = ""
    encrypted_email: str = ""
    email_valid: bool = True
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class ContactMembership:
    id: str = field(default_factory=lambda: str(uuid4()))
    contact_identity_id: str = ""
    customer_account_id: str = ""
    external_user_id: str = ""
    role_key: str = ""
    active: bool = True
    communication_eligible: bool = False
    opted_out: bool = False
    last_activity_at: datetime | None = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


@dataclass
class UsageSnapshotRecord:
    id: str = field(default_factory=lambda: str(uuid4()))
    mapsi_instance_id: str = ""
    snapshot_kind: str = ""
    source_cursor: str = ""
    contract_version: str = ""
    collected_at: datetime = field(default_factory=utcnow)
    source_generated_at: datetime | None = None


@dataclass
class FeatureAdoption:
    id: str = field(default_factory=lambda: str(uuid4()))
    usage_snapshot_id: str = ""
    contact_membership_id: str = ""
    module_key: str = ""
    events_last_7_days: int = 0
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class InstanceCapability:
    id: str = field(default_factory=lambda: str(uuid4()))
    mapsi_instance_id: str = ""
    capability_key: str = ""
    enabled: bool = False
    version: str = ""
    collected_at: datetime = field(default_factory=utcnow)


@dataclass
class CollectionRun:
    id: str = field(default_factory=lambda: str(uuid4()))
    mapsi_instance_id: str = ""
    status: str = "started"
    dry_run: bool = False
    started_at: datetime = field(default_factory=utcnow)
    finished_at: datetime | None = None
    last_usage_cursor: str = ""
    last_contact_cursor: str = ""
    report: dict[str, Any] = field(default_factory=dict)


@dataclass
class AudienceFact:
    membership_id: str
    customer_account_id: str
    client_key: str
    role_key: str
    active: bool
    communication_eligible: bool
    opted_out: bool
    module_keys: list[str]
    module_events: dict[str, int]
    instance_key: str
    created_at: datetime
    last_activity_at: datetime | None = None
    invalid_email: bool = False
    account_suspended: bool = False


@dataclass
class SegmentCondition:
    field: str
    operator: str
    value: Any


@dataclass
class AudienceSegmentRule:
    id: str
    label: str
    enabled: bool
    legal_basis: str
    conditions_all: list[SegmentCondition] = field(default_factory=list)
    conditions_any: list[SegmentCondition] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    description: str = ""


@dataclass
class AudienceSegmentAuditEntry:
    membership_id: str
    included: bool
    reasons: list[str]
    role_key: str
    client_key: str


@dataclass
class AudienceSegmentPreview:
    id: str = field(default_factory=lambda: str(uuid4()))
    segment_id: str = ""
    segment_label: str = ""
    legal_basis: str = ""
    enabled: bool = True
    status: str = "ready"
    blocked_reasons: list[str] = field(default_factory=list)
    total_volume: int = 0
    eligible_volume: int = 0
    exclusions_by_reason: dict[str, int] = field(default_factory=dict)
    role_distribution: dict[str, int] = field(default_factory=dict)
    module_distribution: dict[str, int] = field(default_factory=dict)
    client_distribution: dict[str, int] = field(default_factory=dict)
    audits: list[AudienceSegmentAuditEntry] = field(default_factory=list)
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class MauticContactLink:
    id: str = field(default_factory=lambda: str(uuid4()))
    contact_identity_id: str = ""
    mautic_contact_id: str = ""
    email_hash: str = ""
    dnc_applied: bool = False
    remote_unsubscribed: bool = False
    last_sync_status: str = "pending"
    last_synced_at: datetime | None = None
    last_source_updated_at: datetime | None = None
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class MauticCampaignPublication:
    id: str = field(default_factory=lambda: str(uuid4()))
    campaign_run_id: str = ""
    content_version: int = 1
    segment_version: int = 1
    status: str = "draft"
    mautic_email_id: str = ""
    mautic_segment_id: str = ""
    mautic_campaign_id: str = ""
    scheduled_at: datetime | None = None
    idempotency_key: str = ""
    target_instance_ids: list[str] = field(default_factory=list)
    target_client_ids: list[str] = field(default_factory=list)
    targeted_contacts: int = 0
    last_error: str = ""
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


@dataclass
class LinkedInOAuthToken:
    id: str = field(default_factory=lambda: str(uuid4()))
    provider: str = "linkedin"
    subject: str = "organization"
    access_token: str = ""
    refresh_token: str = ""
    scope: str = ""
    expires_at: datetime | None = None
    refresh_expires_at: datetime | None = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


@dataclass
class LinkedInPublication:
    id: str = field(default_factory=lambda: str(uuid4()))
    campaign_run_id: str = ""
    content_asset_id: str = ""
    content_hash: str = ""
    asset_type: str = ""
    organization_urn: str = ""
    linkedin_post_urn: str = ""
    status: str = "draft"
    mode: str = "mock"
    idempotency_key: str = ""
    last_error: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    published_at: datetime | None = None
    metrics_collected_at: datetime | None = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


@dataclass
class CampaignRun:
    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    objective: str = ""
    status: CampaignStatus = CampaignStatus.DRAFT
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    editorial_briefs: list[EditorialBrief] = field(default_factory=list)
    content_assets: list[ContentAsset] = field(default_factory=list)
    audience_segments: list[AudienceSegment] = field(default_factory=list)
    approval_decisions: list[ApprovalDecision] = field(default_factory=list)
    publications: list[Publication] = field(default_factory=list)
    interactions: list[Interaction] = field(default_factory=list)
    leads: list[Lead] = field(default_factory=list)
    source_evidences: list[SourceEvidence] = field(default_factory=list)

    def _transition_to(self, next_status: CampaignStatus, allowed_from: set[CampaignStatus]) -> None:
        if self.status not in allowed_from:
            raise InvalidStateTransitionError(
                f"Cannot transition campaign {self.id} from {self.status} to {next_status}."
            )
        self.status = next_status
        self.updated_at = utcnow()

    def mark_generated(self, brief: EditorialBrief, assets: list[ContentAsset]) -> None:
        self._transition_to(CampaignStatus.GENERATED, {CampaignStatus.DRAFT, CampaignStatus.CHANGES_REQUESTED})
        self.editorial_briefs = [brief]
        self.content_assets = [
            ContentAsset(
                id=asset.id,
                campaign_run_id=asset.campaign_run_id,
                asset_type=asset.asset_type,
                channel=asset.channel,
                title=asset.title,
                body=asset.body,
                evidence_ids=list(asset.evidence_ids),
                audience_segment_id=asset.audience_segment_id,
                status=AssetStatus.READY_FOR_REVIEW,
                content_hash=asset.content_hash
                or build_content_hash(
                    asset.asset_type,
                    asset.title,
                    asset.body,
                    list(asset.evidence_ids),
                    asset.audience_segment_id,
                ),
                approved_by=asset.approved_by,
                approved_at=asset.approved_at,
                scheduled_at=asset.scheduled_at,
                results=dict(asset.results),
                revision=asset.revision,
                created_at=asset.created_at,
            )
            for asset in assets
        ]

    def request_changes(self, comment: str, decided_by: str) -> ApprovalDecision:
        self._transition_to(
            CampaignStatus.CHANGES_REQUESTED,
            {CampaignStatus.GENERATED, CampaignStatus.APPROVED},
        )
        for asset in self.content_assets:
            asset.status = AssetStatus.CHANGES_REQUESTED
            asset.revision += 1
        decision = ApprovalDecision(
            campaign_run_id=self.id,
            decision=CampaignStatus.CHANGES_REQUESTED.value,
            decided_by=decided_by,
            comment=comment,
        )
        self.approval_decisions.append(decision)
        return decision

    def approve(self, comment: str, decided_by: str) -> ApprovalDecision:
        if not self.content_assets:
            raise ApprovalPrerequisiteError(f"Campaign {self.id} has no content assets to approve.")
        if not self.source_evidences:
            raise ApprovalPrerequisiteError(f"Campaign {self.id} has no source evidence to approve.")
        self._transition_to(
            CampaignStatus.APPROVED,
            {CampaignStatus.GENERATED, CampaignStatus.CHANGES_REQUESTED},
        )
        for asset in self.content_assets:
            asset.status = AssetStatus.APPROVED
        decision = ApprovalDecision(
            campaign_run_id=self.id,
            decision=CampaignStatus.APPROVED.value,
            decided_by=decided_by,
            comment=comment,
        )
        self.approval_decisions.append(decision)
        return decision

    def reject(self, comment: str, decided_by: str) -> ApprovalDecision:
        self._transition_to(
            CampaignStatus.REJECTED,
            {CampaignStatus.GENERATED, CampaignStatus.CHANGES_REQUESTED, CampaignStatus.APPROVED},
        )
        decision = ApprovalDecision(
            campaign_run_id=self.id,
            decision=CampaignStatus.REJECTED.value,
            decided_by=decided_by,
            comment=comment,
        )
        self.approval_decisions.append(decision)
        return decision

    def publish(self, publication: Publication) -> None:
        if self.status not in {CampaignStatus.APPROVED, CampaignStatus.PUBLISHED}:
            raise CampaignPublicationForbiddenError(
                f"Campaign {self.id} must be APPROVED before publication."
            )
        for existing in self.publications:
            if existing.channel == publication.channel:
                return
        self.status = CampaignStatus.PUBLISHED
        self.updated_at = utcnow()
        self.publications.append(publication)


@dataclass
class CampaignReview:
    id: str = field(default_factory=lambda: str(uuid4()))
    campaign_run_id: str = ""
    theme: str = ""
    objective: str = ""
    segment_id: str = ""
    segment_label: str = ""
    segment_version: int = 1
    audience_volume: int = 0
    exclusions: dict[str, int] = field(default_factory=dict)
    evidence_ids: list[str] = field(default_factory=list)
    email_subject: str = ""
    email_preheader: str = ""
    email_html: str = ""
    email_text: str = ""
    quality_control: dict[str, Any] = field(default_factory=dict)
    proposed_at: datetime = field(default_factory=utcnow)
    content_version: int = 1
    approved_content_hash: str = ""
    approved_audience_hash: str = ""
    approved_by: str = ""
    approved_at: datetime | None = None
    rejected_at: datetime | None = None
    rejected_by: str = ""


@dataclass
class ReviewToken:
    id: str = field(default_factory=lambda: str(uuid4()))
    campaign_review_id: str = ""
    token_hash: str = ""
    expires_at: datetime = field(default_factory=utcnow)
    max_uses: int = 1
    used_count: int = 0
    revoked_at: datetime | None = None
    created_at: datetime = field(default_factory=utcnow)
