from datetime import datetime

from pydantic import BaseModel, Field


class AudienceSegmentPayload(BaseModel):
    name: str
    description: str


class CreateCampaignRequest(BaseModel):
    name: str
    objective: str
    audience: AudienceSegmentPayload


class ReviewRequest(BaseModel):
    decided_by: str
    comment: str = ""


class WorkflowCommandRequest(BaseModel):
    correlation_id: str
    dry_run: bool = False


class CollectMapsiUsageRequest(WorkflowCommandRequest):
    instance_id: str | None = None


class RequestApprovalRequest(WorkflowCommandRequest):
    proposed_at: datetime | None = None


class PublishApprovedCampaignRequest(WorkflowCommandRequest):
    scheduled_at: datetime
    channels: list[str]


class MauticPublicationRequest(WorkflowCommandRequest):
    scheduled_at: datetime | None = None


class LinkedInOAuthExchangeRequest(WorkflowCommandRequest):
    code: str


class LinkedInAssetPublishRequest(WorkflowCommandRequest):
    asset_id: str


class FailureNotificationRequest(WorkflowCommandRequest):
    workflow: str
    step: str
    error: str
    retryable: bool = True


class PublishRequest(BaseModel):
    channel: str | None = Field(default=None, pattern="^(linkedin|oling|mapsi_site|mapsi_studio|mapsi_users|prospect_newsletter|mautic)$")
    channels: list[str] | None = None

    def resolved_channels(self) -> list[str]:
        if self.channels:
            return self.channels
        if self.channel:
            return [self.channel]
        raise ValueError("At least one publication channel is required.")


class EditorialBriefResponse(BaseModel):
    id: str
    title: str
    summary: str
    created_at: datetime


class ContentAssetResponse(BaseModel):
    id: str
    asset_type: str
    campaign_id: str
    channel: str
    locale: str
    title: str
    subject: str
    content_html: str | None
    content_text: str
    excerpt: str
    call_to_action: str
    target_url: str
    source_evidence_ids: list[str]
    body: str
    evidence_ids: list[str]
    audience_segment_id: str
    status: str
    content_version: int
    content_hash: str
    approved_content_hash: str
    approved_by: str
    approved_at: datetime | None
    scheduled_at: datetime | None
    published_at: datetime | None
    external_publication_id: str
    external_publication_url: str
    last_error: str
    retry_count: int
    results: dict
    revision: int
    created_at: datetime


class AudienceSegmentResponse(BaseModel):
    id: str
    name: str
    description: str
    created_at: datetime


class ApprovalDecisionResponse(BaseModel):
    id: str
    decision: str
    decided_by: str
    comment: str
    created_at: datetime


class PublicationResponse(BaseModel):
    id: str
    channel: str
    external_reference: str
    published_at: datetime


class SourceEvidenceResponse(BaseModel):
    id: str
    source_system: str
    reference: str
    created_at: datetime


class CampaignResponse(BaseModel):
    id: str
    name: str
    objective: str
    status: str
    created_at: datetime
    updated_at: datetime
    editorial_briefs: list[EditorialBriefResponse]
    content_assets: list[ContentAssetResponse]
    audience_segments: list[AudienceSegmentResponse]
    approval_decisions: list[ApprovalDecisionResponse]
    publications: list[PublicationResponse]
    source_evidences: list[SourceEvidenceResponse]

    @classmethod
    def from_entity(cls, campaign) -> "CampaignResponse":
        return cls(
            id=campaign.id,
            name=campaign.name,
            objective=campaign.objective,
            status=campaign.status.value,
            created_at=campaign.created_at,
            updated_at=campaign.updated_at,
            editorial_briefs=[EditorialBriefResponse(**vars(item)) for item in campaign.editorial_briefs],
            content_assets=[
                ContentAssetResponse(
                    id=item.id,
                    asset_type=item.asset_type,
                    campaign_id=item.campaign_id,
                    channel=item.channel,
                    locale=item.locale,
                    title=item.title,
                    subject=item.subject,
                    content_html=item.content_html,
                    content_text=item.content_text,
                    excerpt=item.excerpt,
                    call_to_action=item.call_to_action,
                    target_url=item.target_url,
                    source_evidence_ids=item.source_evidence_ids,
                    body=item.body,
                    evidence_ids=item.evidence_ids,
                    audience_segment_id=item.audience_segment_id,
                    status=item.status.value,
                    content_version=item.content_version,
                    content_hash=item.content_hash,
                    approved_content_hash=item.approved_content_hash,
                    approved_by=item.approved_by,
                    approved_at=item.approved_at,
                    scheduled_at=item.scheduled_at,
                    published_at=item.published_at,
                    external_publication_id=item.external_publication_id,
                    external_publication_url=item.external_publication_url,
                    last_error=item.last_error,
                    retry_count=item.retry_count,
                    results=item.results,
                    revision=item.revision,
                    created_at=item.created_at,
                )
                for item in campaign.content_assets
            ],
            audience_segments=[AudienceSegmentResponse(**vars(item)) for item in campaign.audience_segments],
            approval_decisions=[ApprovalDecisionResponse(**vars(item)) for item in campaign.approval_decisions],
            publications=[PublicationResponse(**vars(item)) for item in campaign.publications],
            source_evidences=[SourceEvidenceResponse(**vars(item)) for item in campaign.source_evidences],
        )


class WorkflowOperationResponse(BaseModel):
    correlation_id: str
    status: str
    details: dict
