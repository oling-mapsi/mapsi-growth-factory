from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
import json
from typing import Any
from uuid import uuid4

from app.domain.enums import AssetStatus, CampaignStatus
from app.domain.errors import (
    ApprovalPrerequisiteError,
    CampaignPublicationForbiddenError,
    InvalidStateTransitionError,
    OptimisticLockError,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _html_to_text(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", text).strip()


def build_content_hash(
    asset_type: str,
    title: str,
    body: str,
    evidence_ids: list[str],
    audience_segment_id: str,
    *,
    locale: str = "",
    subject: str = "",
    content_html: str | None = None,
    content_text: str | None = None,
    excerpt: str = "",
    call_to_action: str = "",
    target_url: str = "",
) -> str:
    from app.core.security import sha256_hexdigest

    html = content_html if content_html is not None else body
    text = content_text if content_text is not None else _html_to_text(body) or body
    return sha256_hexdigest(
        json.dumps(
            {
                "asset_type": asset_type,
                "locale": locale,
                "title": title,
                "subject": subject,
                "content_html": html,
                "content_text": text,
                "excerpt": excerpt,
                "call_to_action": call_to_action,
                "target_url": target_url,
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
    locale: str = "fr-FR"
    title: str = ""
    subject: str = ""
    content_html: str | None = None
    content_text: str = ""
    excerpt: str = ""
    call_to_action: str = ""
    target_url: str = ""
    source_evidence_ids: list[str] = field(default_factory=list)
    audience_segment_id: str = ""
    status: AssetStatus = AssetStatus.DRAFT
    content_version: int = 1
    content_hash: str = ""
    approved_content_hash: str = ""
    approved_by: str = ""
    approved_at: datetime | None = None
    scheduled_at: datetime | None = None
    published_at: datetime | None = None
    external_publication_id: str = ""
    external_publication_url: str = ""
    last_error: str = ""
    retry_count: int = 0
    results: dict[str, Any] = field(default_factory=dict)
    body: str = ""
    evidence_ids: list[str] = field(default_factory=list)
    revision: int = 1
    created_at: datetime = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        self._sync_legacy_fields()

    @property
    def campaign_id(self) -> str:
        return self.campaign_run_id

    @campaign_id.setter
    def campaign_id(self, value: str) -> None:
        self.campaign_run_id = value

    def _sync_legacy_fields(self) -> None:
        if self.body:
            if self.content_html is None or self.content_html != self.body:
                self.content_html = self.body
            self.content_text = _html_to_text(self.body) or self.body
        elif self.content_html is not None:
            self.body = self.content_html
        else:
            self.body = self.content_text
        if self.evidence_ids and self.evidence_ids != self.source_evidence_ids:
            self.source_evidence_ids = list(self.evidence_ids)
        elif self.source_evidence_ids and not self.evidence_ids:
            self.evidence_ids = list(self.source_evidence_ids)
        if self.revision != 1 and self.content_version == 1:
            self.content_version = self.revision
        else:
            self.revision = self.content_version

    def ensure_content_hash(self) -> str:
        self._sync_legacy_fields()
        new_hash = build_content_hash(
            self.asset_type,
            self.title,
            self.body,
            list(self.source_evidence_ids),
            self.audience_segment_id,
            locale=self.locale,
            subject=self.subject,
            content_html=self.content_html,
            content_text=self.content_text,
            excerpt=self.excerpt,
            call_to_action=self.call_to_action,
            target_url=self.target_url,
        )
        changed = self.content_hash and self.content_hash != new_hash
        self.content_hash = new_hash
        if changed and self.approved_content_hash and self.approved_content_hash != new_hash:
            self.approved_content_hash = ""
            self.approved_by = ""
            self.approved_at = None
            if self.status in {AssetStatus.APPROVED, AssetStatus.SCHEDULED, AssetStatus.PUBLISHING}:
                self.status = AssetStatus.READY_FOR_REVIEW
        return self.content_hash

    def approve(self, decided_by: str) -> None:
        self.ensure_content_hash()
        self.approved_content_hash = self.content_hash
        self.approved_by = decided_by
        self.approved_at = utcnow()
        self.status = AssetStatus.APPROVED
        self.last_error = ""

    def request_changes(self) -> None:
        self.content_version += 1
        self.revision = self.content_version
        self.approved_content_hash = ""
        self.approved_by = ""
        self.approved_at = None
        self.status = AssetStatus.CHANGES_REQUESTED

    def assert_expected_version(self, expected_version: int) -> None:
        if self.content_version != expected_version:
            raise OptimisticLockError(
                f"Asset {self.id} version mismatch: expected {expected_version}, current {self.content_version}."
            )

    def update_draft(
        self,
        *,
        title: str | None = None,
        subject: str | None = None,
        content_html: str | None = None,
        content_text: str | None = None,
        excerpt: str | None = None,
        call_to_action: str | None = None,
        target_url: str | None = None,
    ) -> None:
        self.content_version += 1
        self.revision = self.content_version
        if title is not None:
            self.title = title
        if subject is not None:
            self.subject = subject
        if content_html is not None:
            self.content_html = content_html
            self.body = content_html
        if content_text is not None:
            self.content_text = content_text
        if excerpt is not None:
            self.excerpt = excerpt
        if call_to_action is not None:
            self.call_to_action = call_to_action
        if target_url is not None:
            self.target_url = target_url
        self.last_error = ""
        self.ensure_content_hash()
        if self.status not in {AssetStatus.PUBLISHED, AssetStatus.CANCELLED}:
            self.status = AssetStatus.READY_FOR_REVIEW

    def mark_scheduled(self) -> None:
        self.status = AssetStatus.SCHEDULED
        self.last_error = ""

    def mark_publishing(self) -> None:
        self.status = AssetStatus.PUBLISHING
        self.last_error = ""

    def mark_published(self, *, external_id: str = "", external_url: str = "", published_at: datetime | None = None) -> None:
        self.status = AssetStatus.PUBLISHED
        self.published_at = published_at or utcnow()
        self.external_publication_id = external_id
        self.external_publication_url = external_url
        self.last_error = ""

    def mark_failed(self, error: str) -> None:
        self.status = AssetStatus.FAILED
        self.last_error = error
        self.retry_count += 1

    def cancel(self) -> None:
        self.status = AssetStatus.CANCELLED


@dataclass
class AssetRevisionSnapshot:
    id: str = field(default_factory=lambda: str(uuid4()))
    content_asset_id: str = ""
    campaign_run_id: str = ""
    version: int = 1
    status: str = ""
    title: str = ""
    subject: str = ""
    content_html: str = ""
    content_text: str = ""
    excerpt: str = ""
    call_to_action: str = ""
    target_url: str = ""
    content_hash: str = ""
    approved_content_hash: str = ""
    results: dict[str, Any] = field(default_factory=dict)
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
    content_asset_id: str = ""
    channel: str = ""
    external_reference: str = ""
    external_url: str = ""
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
class OlingNewsPublication:
    id: str = field(default_factory=lambda: str(uuid4()))
    campaign_run_id: str = ""
    content_asset_id: str = ""
    external_id: str = ""
    content_hash: str = ""
    status: str = "draft"
    mode: str = "mock"
    publication_mode_requested: str = ""
    publication_mode_executed: str = ""
    publisher_type: str = ""
    publication_status: str = "DRAFT"
    idempotency_key: str = ""
    preview_url: str = ""
    public_url: str = ""
    public_slug: str = ""
    draft_revision_number: int | None = None
    published_revision_number: int | None = None
    published_content_version: int | None = None
    published_at: datetime | None = None
    unpublished_at: datetime | None = None
    last_error: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


@dataclass
class MapsiNewsPublication:
    id: str = field(default_factory=lambda: str(uuid4()))
    campaign_run_id: str = ""
    content_asset_id: str = ""
    external_id: str = ""
    content_hash: str = ""
    status: str = "draft"
    mode: str = "mock"
    publication_mode_requested: str = ""
    publication_mode_executed: str = ""
    publisher_type: str = ""
    publication_status: str = "DRAFT"
    idempotency_key: str = ""
    preview_url: str = ""
    public_url: str = ""
    public_slug: str = ""
    draft_revision_number: int | None = None
    published_revision_number: int | None = None
    published_content_version: int | None = None
    published_at: datetime | None = None
    unpublished_at: datetime | None = None
    last_error: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


@dataclass
class CampaignRun:
    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    objective: str = ""
    theme: str = ""
    campaign_type: str = ""
    workflow_kind: str = "LEGACY"
    selected_channels: list[str] = field(default_factory=list)
    weekly_pack_id: str = ""
    week_reference: str = ""
    week_year: int = 0
    week_number: int = 0
    pilot_mode: bool = False
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

    def _find_asset(self, asset_id: str) -> ContentAsset:
        for asset in self.content_assets:
            if asset.id == asset_id:
                return asset
        raise ApprovalPrerequisiteError(f"Campaign {self.id} has no asset {asset_id}.")

    def _sync_status_from_assets(self) -> None:
        published_assets = [asset for asset in self.content_assets if asset.status is AssetStatus.PUBLISHED]
        active_assets = [asset for asset in self.content_assets if asset.status is not AssetStatus.CANCELLED]
        approved_assets = [asset for asset in active_assets if asset.status in {AssetStatus.APPROVED, AssetStatus.SCHEDULED, AssetStatus.PUBLISHING, AssetStatus.PUBLISHED}]
        reviewable_assets = [asset for asset in active_assets if asset.status in {AssetStatus.READY_FOR_REVIEW, AssetStatus.QUALITY_CHECK, AssetStatus.CHANGES_REQUESTED, AssetStatus.DRAFT}]
        failed_assets = [asset for asset in active_assets if asset.status is AssetStatus.FAILED]
        if published_assets:
            if active_assets and len(published_assets) == len(active_assets):
                self.status = CampaignStatus.PUBLISHED
            else:
                self.status = CampaignStatus.PARTIALLY_PUBLISHED
        elif approved_assets:
            if active_assets and len(approved_assets) == len(active_assets):
                self.status = CampaignStatus.APPROVED
            else:
                self.status = CampaignStatus.PARTIALLY_APPROVED
        elif any(asset.status is AssetStatus.CHANGES_REQUESTED for asset in active_assets):
            self.status = CampaignStatus.CHANGES_REQUESTED
        elif reviewable_assets:
            self.status = CampaignStatus.READY_FOR_REVIEW
        elif failed_assets:
            self.status = CampaignStatus.FAILED
        elif self.content_assets:
            self.status = CampaignStatus.GENERATED
        self.updated_at = utcnow()

    def _transition_to(self, next_status: CampaignStatus, allowed_from: set[CampaignStatus]) -> None:
        if self.status not in allowed_from:
            raise InvalidStateTransitionError(
                f"Cannot transition campaign {self.id} from {self.status} to {next_status}."
            )
        self.status = next_status
        self.updated_at = utcnow()

    def mark_generated(self, brief: EditorialBrief, assets: list[ContentAsset]) -> None:
        self._transition_to(
            CampaignStatus.GENERATED,
            {
                CampaignStatus.DRAFT,
                CampaignStatus.CHANGES_REQUESTED,
                CampaignStatus.NOT_STARTED,
                CampaignStatus.SOURCES_READY,
                CampaignStatus.GENERATING,
                CampaignStatus.FAILED,
                CampaignStatus.GENERATED,
                CampaignStatus.READY_FOR_REVIEW,
                CampaignStatus.PARTIALLY_APPROVED,
                CampaignStatus.APPROVED,
            },
        )
        self.editorial_briefs = [brief]
        self.content_assets = [
            ContentAsset(
                id=asset.id,
                campaign_run_id=asset.campaign_run_id,
                asset_type=asset.asset_type,
                channel=asset.channel,
                locale=asset.locale,
                title=asset.title,
                subject=asset.subject,
                content_html=asset.content_html if asset.content_html is not None else asset.body,
                content_text=asset.content_text or _html_to_text(asset.body) or asset.body,
                excerpt=asset.excerpt,
                call_to_action=asset.call_to_action,
                target_url=asset.target_url,
                source_evidence_ids=list(asset.source_evidence_ids or asset.evidence_ids),
                audience_segment_id=asset.audience_segment_id,
                status=AssetStatus.READY_FOR_REVIEW,
                content_version=asset.content_version or asset.revision,
                content_hash=asset.content_hash
                or build_content_hash(
                    asset.asset_type,
                    asset.title,
                    asset.body,
                    list(asset.source_evidence_ids or asset.evidence_ids),
                    asset.audience_segment_id,
                    locale=asset.locale,
                    subject=asset.subject,
                    content_html=asset.content_html,
                    content_text=asset.content_text,
                    excerpt=asset.excerpt,
                    call_to_action=asset.call_to_action,
                    target_url=asset.target_url,
                ),
                approved_content_hash=asset.approved_content_hash,
                approved_by=asset.approved_by,
                approved_at=asset.approved_at,
                scheduled_at=asset.scheduled_at,
                published_at=asset.published_at,
                external_publication_id=asset.external_publication_id,
                external_publication_url=asset.external_publication_url,
                last_error=asset.last_error,
                retry_count=asset.retry_count,
                results=dict(asset.results),
                created_at=asset.created_at,
            )
            for asset in assets
        ]
        for asset in self.content_assets:
            asset.ensure_content_hash()

    def request_changes(self, comment: str, decided_by: str) -> ApprovalDecision:
        if self.status not in {CampaignStatus.GENERATED, CampaignStatus.APPROVED, CampaignStatus.CHANGES_REQUESTED}:
            raise InvalidStateTransitionError(
                f"Cannot transition campaign {self.id} from {self.status} to {CampaignStatus.CHANGES_REQUESTED}."
            )
        for asset in self.content_assets:
            if asset.status in {
                AssetStatus.DRAFT,
                AssetStatus.QUALITY_CHECK,
                AssetStatus.READY_FOR_REVIEW,
                AssetStatus.APPROVED,
                AssetStatus.SCHEDULED,
                AssetStatus.FAILED,
            }:
                asset.request_changes()
        decision = ApprovalDecision(
            campaign_run_id=self.id,
            decision=CampaignStatus.CHANGES_REQUESTED.value,
            decided_by=decided_by,
            comment=comment,
        )
        self.approval_decisions.append(decision)
        self._sync_status_from_assets()
        return decision

    def approve(self, comment: str, decided_by: str) -> ApprovalDecision:
        if not self.content_assets:
            raise ApprovalPrerequisiteError(f"Campaign {self.id} has no content assets to approve.")
        if not self.source_evidences:
            raise ApprovalPrerequisiteError(f"Campaign {self.id} has no source evidence to approve.")
        for asset in self.content_assets:
            if asset.status in {AssetStatus.READY_FOR_REVIEW, AssetStatus.QUALITY_CHECK, AssetStatus.CHANGES_REQUESTED, AssetStatus.DRAFT}:
                asset.approve(decided_by)
        decision = ApprovalDecision(
            campaign_run_id=self.id,
            decision=CampaignStatus.APPROVED.value,
            decided_by=decided_by,
            comment=comment,
        )
        self.approval_decisions.append(decision)
        self._sync_status_from_assets()
        return decision

    def approve_asset(self, asset_id: str, comment: str, decided_by: str) -> ApprovalDecision:
        if not self.source_evidences:
            raise ApprovalPrerequisiteError(f"Campaign {self.id} has no source evidence to approve.")
        asset = self._find_asset(asset_id)
        asset.approve(decided_by)
        decision = ApprovalDecision(
            campaign_run_id=self.id,
            decision=CampaignStatus.APPROVED.value,
            decided_by=decided_by,
            comment=comment,
        )
        self.approval_decisions.append(decision)
        self._sync_status_from_assets()
        return decision

    def request_asset_changes(self, asset_id: str, comment: str, decided_by: str) -> ApprovalDecision:
        asset = self._find_asset(asset_id)
        asset.request_changes()
        decision = ApprovalDecision(
            campaign_run_id=self.id,
            decision=CampaignStatus.CHANGES_REQUESTED.value,
            decided_by=decided_by,
            comment=comment,
        )
        self.approval_decisions.append(decision)
        self._sync_status_from_assets()
        return decision

    def reject_asset(self, asset_id: str, comment: str, decided_by: str) -> ApprovalDecision:
        asset = self._find_asset(asset_id)
        asset.request_changes()
        decision = ApprovalDecision(
            campaign_run_id=self.id,
            decision=CampaignStatus.REJECTED.value,
            decided_by=decided_by,
            comment=comment,
        )
        self.approval_decisions.append(decision)
        self._sync_status_from_assets()
        return decision

    def request_asset_regeneration(self, asset_id: str, comment: str, decided_by: str) -> ApprovalDecision:
        asset = self._find_asset(asset_id)
        asset.request_changes()
        decision = ApprovalDecision(
            campaign_run_id=self.id,
            decision="REGENERATION_REQUESTED",
            decided_by=decided_by,
            comment=comment,
        )
        self.approval_decisions.append(decision)
        self._sync_status_from_assets()
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
        if self.status not in {CampaignStatus.APPROVED, CampaignStatus.PARTIALLY_PUBLISHED, CampaignStatus.PUBLISHED}:
            raise CampaignPublicationForbiddenError(
                f"Campaign {self.id} must be APPROVED before publication."
            )
        publication_asset_id = getattr(publication, "content_asset_id", "")
        for existing in self.publications:
            if publication_asset_id:
                if existing.channel == publication.channel and existing.content_asset_id == publication_asset_id:
                    return
            elif existing.channel == publication.channel:
                return
        self.publications.append(publication)
        if publication_asset_id:
            asset = self._find_asset(publication_asset_id)
            asset.mark_published(
                external_id=publication.external_reference,
                external_url=getattr(publication, "external_url", ""),
                published_at=publication.published_at,
            )
        self._sync_status_from_assets()


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
class WeeklyCommunicationPack:
    id: str = field(default_factory=lambda: str(uuid4()))
    week_reference: str = ""
    year: int = 0
    week_number: int = 0
    status: str = "NOT_STARTED"
    created_at: datetime = field(default_factory=utcnow)
    generated_at: datetime | None = None
    reviewed_at: datetime | None = None
    completed_at: datetime | None = None
    campaign_ids: list[str] = field(default_factory=list)
    global_summary: dict[str, Any] = field(default_factory=dict)
    operational_errors: list[dict[str, Any]] = field(default_factory=list)
    pilot_mode: bool = False


@dataclass
class FeatureCommunicationCatalogEntry:
    feature_id: str = ""
    module: str = ""
    title: str = ""
    functional_description: str = ""
    user_benefit: str = ""
    target_roles: list[str] = field(default_factory=list)
    target_modules: list[str] = field(default_factory=list)
    minimum_version: str = ""
    availability: str = "general"
    deep_link_template: str = ""
    communication_priority: int = 100
    last_communicated_at: datetime | None = None
    minimum_repeat_delay: int = 14
    source_evidence_ids: list[str] = field(default_factory=list)
    enabled: bool = True


@dataclass
class EditorialSourceAttachmentReference:
    id: str = field(default_factory=lambda: str(uuid4()))
    source_item_id: str = ""
    file_name: str = ""
    media_type: str = ""
    storage_reference: str = ""
    source_url: str = ""
    content_hash: str = ""
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class EditorialSourceItem:
    id: str = field(default_factory=lambda: str(uuid4()))
    source_pack_id: str = ""
    source_type: str = "MANUAL_NOTE"
    source_reference: str = ""
    source_title: str = ""
    source_date: datetime | None = None
    source_author: str = ""
    factual_summary: str = ""
    usable_facts: list[str] = field(default_factory=list)
    anonymized_facts: list[str] = field(default_factory=list)
    prohibited_facts: list[str] = field(default_factory=list)
    client_name: str = ""
    client_name_usage_authorized: bool = False
    confidentiality_level: str = "INTERNAL"
    evidence_quality: str = "medium"
    source_url: str = ""
    external_source_id: str = ""
    content_hash: str = ""
    manual_input: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    attachment_references: list[EditorialSourceAttachmentReference] = field(default_factory=list)


@dataclass
class EditorialSourcePack:
    id: str = field(default_factory=lambda: str(uuid4()))
    weekly_pack_id: str = ""
    campaign_type: str = ""
    title: str = ""
    summary: str = ""
    status: str = "DRAFT"
    confidentiality_level: str = "INTERNAL"
    created_by: str = ""
    created_at: datetime = field(default_factory=utcnow)
    validated_by: str = ""
    validated_at: datetime | None = None
    items: list[EditorialSourceItem] = field(default_factory=list)


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
