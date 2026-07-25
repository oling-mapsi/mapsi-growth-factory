from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, JSON, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CampaignRunModel(Base):
    __tablename__ = "campaign_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    theme: Mapped[str] = mapped_column(Text, nullable=False, default="")
    campaign_type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    workflow_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="LEGACY")
    selected_channels: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    weekly_pack_id: Mapped[str] = mapped_column(String(36), nullable=False, default="")
    week_reference: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    week_year: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    week_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pilot_mode: Mapped[bool] = mapped_column(nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    editorial_briefs: Mapped[list[EditorialBriefModel]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
    )
    content_assets: Mapped[list[ContentAssetModel]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
    )
    audience_segments: Mapped[list[AudienceSegmentModel]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
    )
    approval_decisions: Mapped[list[ApprovalDecisionModel]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
    )
    publications: Mapped[list[PublicationModel]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
    )
    interactions: Mapped[list[InteractionModel]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
    )
    leads: Mapped[list[LeadModel]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
    )
    source_evidences: Mapped[list[SourceEvidenceModel]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
    )
    audit_logs: Mapped[list[AuditLogModel]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
    )


class WeeklyCommunicationPackModel(Base):
    __tablename__ = "weekly_communication_packs"
    __table_args__ = (UniqueConstraint("year", "week_number", name="uq_weekly_communication_packs_year_week"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    week_reference: Mapped[str] = mapped_column(String(32), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    week_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="NOT_STARTED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    campaign_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    global_summary: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    operational_errors: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    pilot_mode: Mapped[bool] = mapped_column(nullable=False, default=False)


class FeatureCommunicationCatalogModel(Base):
    __tablename__ = "feature_communication_catalog"

    feature_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    module: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    functional_description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    user_benefit: Mapped[str] = mapped_column(Text, nullable=False, default="")
    target_roles: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    target_modules: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    minimum_version: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    availability: Mapped[str] = mapped_column(String(64), nullable=False, default="general")
    deep_link_template: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    communication_priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    last_communicated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    minimum_repeat_delay: Mapped[int] = mapped_column(Integer, nullable=False, default=14)
    source_evidence_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)


class EditorialSourcePackModel(Base):
    __tablename__ = "editorial_source_packs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    weekly_pack_id: Mapped[str] = mapped_column(String(36), nullable=False, default="")
    campaign_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")
    confidentiality_level: Mapped[str] = mapped_column(String(32), nullable=False, default="INTERNAL")
    created_by: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    validated_by: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    items: Mapped[list[EditorialSourceItemModel]] = relationship(
        cascade="all, delete-orphan",
    )


class EditorialSourceItemModel(Base):
    __tablename__ = "editorial_source_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source_pack_id: Mapped[str] = mapped_column(ForeignKey("editorial_source_packs.id"), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_reference: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    source_title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    source_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_author: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    factual_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    usable_facts: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    anonymized_facts: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    prohibited_facts: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    client_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    client_name_usage_authorized: Mapped[bool] = mapped_column(nullable=False, default=False)
    confidentiality_level: Mapped[str] = mapped_column(String(32), nullable=False, default="INTERNAL")
    evidence_quality: Mapped[str] = mapped_column(String(32), nullable=False, default="medium")
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    external_source_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    manual_input: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    attachments: Mapped[list[EditorialSourceAttachmentReferenceModel]] = relationship(
        back_populates="source_item",
        cascade="all, delete-orphan",
    )


class EditorialSourceAttachmentReferenceModel(Base):
    __tablename__ = "editorial_source_attachment_references"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source_item_id: Mapped[str] = mapped_column(ForeignKey("editorial_source_items.id"), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    media_type: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    storage_reference: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    source_item: Mapped[EditorialSourceItemModel] = relationship(back_populates="attachments")


class EditorialBriefModel(Base):
    __tablename__ = "editorial_briefs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    campaign_run_id: Mapped[str] = mapped_column(ForeignKey("campaign_runs.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    campaign: Mapped[CampaignRunModel] = relationship(back_populates="editorial_briefs")


class ContentAssetModel(Base):
    __tablename__ = "content_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    campaign_run_id: Mapped[str] = mapped_column(ForeignKey("campaign_runs.id"), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(String(64), nullable=False)
    locale: Mapped[str] = mapped_column(String(16), nullable=False, default="fr-FR")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    content_html: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    excerpt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    call_to_action: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    target_url: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    source_evidence_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    audience_segment_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    content_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    approved_content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    approved_by: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    external_publication_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    external_publication_url: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    results: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    campaign: Mapped[CampaignRunModel] = relationship(back_populates="content_assets")


class AssetRevisionSnapshotModel(Base):
    __tablename__ = "asset_revision_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    content_asset_id: Mapped[str] = mapped_column(ForeignKey("content_assets.id"), nullable=False)
    campaign_run_id: Mapped[str] = mapped_column(ForeignKey("campaign_runs.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    subject: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    content_html: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    excerpt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    call_to_action: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    target_url: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    approved_content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    results: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AudienceSegmentModel(Base):
    __tablename__ = "audience_segments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    campaign_run_id: Mapped[str] = mapped_column(ForeignKey("campaign_runs.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    campaign: Mapped[CampaignRunModel] = relationship(back_populates="audience_segments")


class ApprovalDecisionModel(Base):
    __tablename__ = "approval_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    campaign_run_id: Mapped[str] = mapped_column(ForeignKey("campaign_runs.id"), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    decided_by: Mapped[str] = mapped_column(String(255), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    campaign: Mapped[CampaignRunModel] = relationship(back_populates="approval_decisions")


class PublicationModel(Base):
    __tablename__ = "publications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    campaign_run_id: Mapped[str] = mapped_column(ForeignKey("campaign_runs.id"), nullable=False)
    content_asset_id: Mapped[str] = mapped_column(String(36), nullable=False, default="")
    channel: Mapped[str] = mapped_column(String(64), nullable=False)
    external_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    external_url: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    campaign: Mapped[CampaignRunModel] = relationship(back_populates="publications")


class InteractionModel(Base):
    __tablename__ = "interactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    campaign_run_id: Mapped[str] = mapped_column(ForeignKey("campaign_runs.id"), nullable=False)
    interaction_type: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_payload: Mapped[dict] = mapped_column("metadata", JSON, default=dict, nullable=False)
    campaign: Mapped[CampaignRunModel] = relationship(back_populates="interactions")


class LeadModel(Base):
    __tablename__ = "leads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    campaign_run_id: Mapped[str] = mapped_column(ForeignKey("campaign_runs.id"), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    campaign: Mapped[CampaignRunModel] = relationship(back_populates="leads")


class SourceEvidenceModel(Base):
    __tablename__ = "source_evidences"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    campaign_run_id: Mapped[str | None] = mapped_column(ForeignKey("campaign_runs.id"), nullable=True)
    product_change_id: Mapped[str] = mapped_column(ForeignKey("product_changes.id"), nullable=True)
    source_system: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    reference: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    campaign: Mapped[CampaignRunModel | None] = relationship(back_populates="source_evidences")


class RepositorySourceModel(Base):
    __tablename__ = "repository_sources"
    __table_args__ = (UniqueConstraint("full_name", name="uq_repository_sources_full_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    installation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    default_branch: Mapped[str] = mapped_column(String(255), nullable=False, default="main")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class RepositoryCursorModel(Base):
    __tablename__ = "repository_cursors"
    __table_args__ = (
        UniqueConstraint("repository_source_id", "cursor_type", name="uq_repository_cursors_source_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    repository_source_id: Mapped[str] = mapped_column(ForeignKey("repository_sources.id"), nullable=False)
    cursor_type: Mapped[str] = mapped_column(String(64), nullable=False)
    last_seen_sha: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    last_delivery_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    last_polled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ProductChangeModel(Base):
    __tablename__ = "product_changes"
    __table_args__ = (
        UniqueConstraint("repository_source_id", "sha", "change_note_path", name="uq_product_changes_source_sha_note"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    repository_source_id: Mapped[str] = mapped_column(ForeignKey("repository_sources.id"), nullable=False)
    repository_full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    sha: Mapped[str] = mapped_column(String(64), nullable=False)
    pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    issue_numbers: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    release_tag: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    deployment_ref: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    production_status: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    change_note_path: Mapped[str] = mapped_column(String(255), nullable=False)
    eligible_for_communication: Mapped[bool] = mapped_column(nullable=False, default=False)
    confidential: Mapped[bool] = mapped_column(nullable=False, default=False)
    target_client_key: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    capability_key: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    contract_version: Mapped[str] = mapped_column(String(32), nullable=False)
    deployment_proven: Mapped[bool] = mapped_column(nullable=False, default=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class WebhookDeliveryModel(Base):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (UniqueConstraint("delivery_id", name="uq_webhook_deliveries_delivery_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    delivery_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    repository_full_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    signature_valid: Mapped[bool] = mapped_column(nullable=False, default=False)
    processed: Mapped[bool] = mapped_column(nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="received")
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class MapsiInstanceModel(Base):
    __tablename__ = "mapsi_instances"
    __table_args__ = (UniqueConstraint("instance_key", name="uq_mapsi_instances_instance_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    instance_key: Mapped[str] = mapped_column(String(64), nullable=False)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    secret_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    contract_version: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class CustomerAccountModel(Base):
    __tablename__ = "customer_accounts"
    __table_args__ = (
        UniqueConstraint("mapsi_instance_id", "external_account_id", name="uq_customer_accounts_instance_external"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    mapsi_instance_id: Mapped[str] = mapped_column(ForeignKey("mapsi_instances.id"), nullable=False)
    external_account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ContactIdentityModel(Base):
    __tablename__ = "contact_identities"
    __table_args__ = (UniqueConstraint("email_hash", name="uq_contact_identities_email_hash"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    email_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    encrypted_email: Mapped[str] = mapped_column(Text, nullable=False, default="")
    email_valid: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ContactMembershipModel(Base):
    __tablename__ = "contact_memberships"
    __table_args__ = (
        UniqueConstraint(
            "contact_identity_id",
            "customer_account_id",
            "external_user_id",
            name="uq_contact_memberships_identity_account_user",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    contact_identity_id: Mapped[str] = mapped_column(ForeignKey("contact_identities.id"), nullable=False)
    customer_account_id: Mapped[str] = mapped_column(ForeignKey("customer_accounts.id"), nullable=False)
    external_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    role_key: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    active: Mapped[bool] = mapped_column(nullable=False, default=True)
    communication_eligible: Mapped[bool] = mapped_column(nullable=False, default=False)
    opted_out: Mapped[bool] = mapped_column(nullable=False, default=False)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class UsageSnapshotModel(Base):
    __tablename__ = "usage_snapshots"
    __table_args__ = (
        UniqueConstraint("mapsi_instance_id", "snapshot_kind", "source_cursor", name="uq_usage_snapshots_instance_kind_cursor"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    mapsi_instance_id: Mapped[str] = mapped_column(ForeignKey("mapsi_instances.id"), nullable=False)
    snapshot_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    source_cursor: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    contract_version: Mapped[str] = mapped_column(String(32), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    source_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FeatureAdoptionModel(Base):
    __tablename__ = "feature_adoptions"
    __table_args__ = (
        UniqueConstraint(
            "usage_snapshot_id",
            "contact_membership_id",
            "module_key",
            name="uq_feature_adoptions_snapshot_membership_module",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    usage_snapshot_id: Mapped[str] = mapped_column(ForeignKey("usage_snapshots.id"), nullable=False)
    contact_membership_id: Mapped[str] = mapped_column(ForeignKey("contact_memberships.id"), nullable=False)
    module_key: Mapped[str] = mapped_column(String(128), nullable=False)
    events_last_7_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class InstanceCapabilityModel(Base):
    __tablename__ = "instance_capabilities"
    __table_args__ = (
        UniqueConstraint("mapsi_instance_id", "capability_key", name="uq_instance_capabilities_instance_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    mapsi_instance_id: Mapped[str] = mapped_column(ForeignKey("mapsi_instances.id"), nullable=False)
    capability_key: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class CollectionRunModel(Base):
    __tablename__ = "collection_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    mapsi_instance_id: Mapped[str] = mapped_column(ForeignKey("mapsi_instances.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="started")
    dry_run: Mapped[bool] = mapped_column(nullable=False, default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_usage_cursor: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    last_contact_cursor: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    report: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class AudienceSegmentPreviewModel(Base):
    __tablename__ = "audience_segment_previews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    segment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    segment_label: Mapped[str] = mapped_column(String(255), nullable=False)
    legal_basis: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ready")
    blocked_reasons: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    total_volume: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    eligible_volume: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    exclusions_by_reason: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    role_distribution: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    module_distribution: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    client_distribution: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AudienceSegmentAuditModel(Base):
    __tablename__ = "audience_segment_audits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    preview_id: Mapped[str] = mapped_column(ForeignKey("audience_segment_previews.id"), nullable=False)
    contact_membership_id: Mapped[str] = mapped_column(ForeignKey("contact_memberships.id"), nullable=False)
    included: Mapped[bool] = mapped_column(nullable=False, default=False)
    reasons: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    role_key: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    client_key: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class MauticContactLinkModel(Base):
    __tablename__ = "mautic_contact_links"
    __table_args__ = (
        UniqueConstraint("contact_identity_id", name="uq_mautic_contact_links_identity"),
        UniqueConstraint("mautic_contact_id", name="uq_mautic_contact_links_mautic_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    contact_identity_id: Mapped[str] = mapped_column(ForeignKey("contact_identities.id"), nullable=False)
    mautic_contact_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    email_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    dnc_applied: Mapped[bool] = mapped_column(nullable=False, default=False)
    remote_unsubscribed: Mapped[bool] = mapped_column(nullable=False, default=False)
    last_sync_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class MauticCampaignPublicationModel(Base):
    __tablename__ = "mautic_campaign_publications"
    __table_args__ = (
        UniqueConstraint("campaign_run_id", "content_version", "segment_version", name="uq_mautic_campaign_publication_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    campaign_run_id: Mapped[str] = mapped_column(ForeignKey("campaign_runs.id"), nullable=False)
    content_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    segment_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    mautic_email_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    mautic_segment_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    mautic_campaign_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    target_instance_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    target_client_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    targeted_contacts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class LinkedInOAuthTokenModel(Base):
    __tablename__ = "linkedin_oauth_tokens"
    __table_args__ = (UniqueConstraint("provider", "subject", name="uq_linkedin_oauth_provider_subject"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="linkedin")
    subject: Mapped[str] = mapped_column(String(64), nullable=False, default="organization")
    access_token: Mapped[str] = mapped_column(Text, nullable=False, default="")
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False, default="")
    scope: Mapped[str] = mapped_column(Text, nullable=False, default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refresh_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class LinkedInPublicationModel(Base):
    __tablename__ = "linkedin_publications"
    __table_args__ = (
        UniqueConstraint("content_asset_id", "content_hash", name="uq_linkedin_publications_asset_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    campaign_run_id: Mapped[str] = mapped_column(ForeignKey("campaign_runs.id"), nullable=False)
    content_asset_id: Mapped[str] = mapped_column(ForeignKey("content_assets.id"), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(64), nullable=False)
    organization_urn: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    linkedin_post_urn: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="mock")
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metrics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metrics_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class OlingNewsPublicationModel(Base):
    __tablename__ = "oling_news_publications"
    __table_args__ = (
        UniqueConstraint("content_asset_id", "content_hash", name="uq_oling_news_publications_asset_hash"),
        UniqueConstraint("external_id", name="uq_oling_news_publications_external_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    campaign_run_id: Mapped[str] = mapped_column(ForeignKey("campaign_runs.id"), nullable=False)
    content_asset_id: Mapped[str] = mapped_column(String(36), nullable=False)
    external_id: Mapped[str] = mapped_column(String(190), nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="mock")
    publication_mode_requested: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    publication_mode_executed: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    publisher_type: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    publication_status: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    preview_url: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    public_url: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    public_slug: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    draft_revision_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_revision_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_content_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    unpublished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metrics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class MapsiNewsPublicationModel(Base):
    __tablename__ = "mapsi_news_publications"
    __table_args__ = (
        UniqueConstraint("content_asset_id", "content_hash", name="uq_mapsi_news_publications_asset_hash"),
        UniqueConstraint("external_id", name="uq_mapsi_news_publications_external_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    campaign_run_id: Mapped[str] = mapped_column(ForeignKey("campaign_runs.id"), nullable=False)
    content_asset_id: Mapped[str] = mapped_column(String(36), nullable=False)
    external_id: Mapped[str] = mapped_column(String(190), nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="mock")
    publication_mode_requested: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    publication_mode_executed: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    publisher_type: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    publication_status: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    preview_url: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    public_url: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    public_slug: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    draft_revision_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_revision_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_content_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    unpublished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metrics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class EditorialThemeHistoryModel(Base):
    __tablename__ = "editorial_theme_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    objective: Mapped[str] = mapped_column(String(64), nullable=False)
    audience_segment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AgentExecutionLogModel(Base):
    __tablename__ = "agent_execution_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    agent_name: Mapped[str] = mapped_column(String(128), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_params: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    input_payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    output_payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class CampaignReviewModel(Base):
    __tablename__ = "campaign_reviews"
    __table_args__ = (UniqueConstraint("campaign_run_id", name="uq_campaign_reviews_campaign_run_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    campaign_run_id: Mapped[str] = mapped_column(ForeignKey("campaign_runs.id"), nullable=False)
    theme: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    objective: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    segment_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    segment_label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    segment_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    audience_volume: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    exclusions: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    email_subject: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    email_preheader: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    email_html: Mapped[str] = mapped_column(Text, nullable=False, default="")
    email_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    quality_control: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    proposed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    content_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    approved_content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    approved_audience_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    approved_by: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_by: Mapped[str] = mapped_column(String(255), nullable=False, default="")


class ReviewTokenModel(Base):
    __tablename__ = "review_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    campaign_review_id: Mapped[str] = mapped_column(ForeignKey("campaign_reviews.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    max_uses: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AuditLogModel(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    campaign_run_id: Mapped[str | None] = mapped_column(ForeignKey("campaign_runs.id"), nullable=True)
    content_asset_id: Mapped[str] = mapped_column(String(36), nullable=False, default="")
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    actor_source: Mapped[str] = mapped_column(String(64), nullable=False, default="system")
    actor_roles: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    channel: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    result: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    source_ip: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    previous_state: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    new_state: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    previous_integrity_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    integrity_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    campaign: Mapped[CampaignRunModel | None] = relationship(back_populates="audit_logs")


class IdempotencyKeyModel(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("method", "path", "idempotency_key", name="uq_idempotency_method_path_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class StudioAdminJtiModel(Base):
    __tablename__ = "studio_admin_jti_records"
    __table_args__ = (UniqueConstraint("jti", name="uq_studio_admin_jti_records_jti"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    jti: Mapped[str] = mapped_column(String(255), nullable=False)
    issuer: Mapped[str] = mapped_column(String(255), nullable=False)
    audience: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    key_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class StudioAdminAccessAuditModel(Base):
    __tablename__ = "studio_admin_access_audits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_roles: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    actor_permissions: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="mapsi-studio")
    jti: Mapped[str] = mapped_column(String(255), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    source_ip: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    path: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    method: Mapped[str] = mapped_column(String(16), nullable=False, default="GET")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ChannelOperationalStateModel(Base):
    __tablename__ = "channel_operational_states"
    __table_args__ = (UniqueConstraint("channel", name="uq_channel_operational_states_channel"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    channel: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_enabled: Mapped[bool] = mapped_column(nullable=False, default=False)
    feature_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    emergency_kill_switch: Mapped[bool] = mapped_column(nullable=False, default=False)
    last_health_check: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class GlobalOperationalStateModel(Base):
    __tablename__ = "global_operational_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    global_kill_switch: Mapped[bool] = mapped_column(nullable=False, default=False)
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ChannelOperationalAuditModel(Base):
    __tablename__ = "channel_operational_audits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    correlation_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
