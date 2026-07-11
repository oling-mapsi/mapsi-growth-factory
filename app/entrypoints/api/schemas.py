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
    channel: str | None = Field(default=None, pattern="^(linkedin|oling)$")
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
    channel: str
    title: str
    body: str
    evidence_ids: list[str]
    audience_segment_id: str
    status: str
    content_hash: str
    approved_by: str
    approved_at: datetime | None
    scheduled_at: datetime | None
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
            content_assets=[ContentAssetResponse(**vars(item)) for item in campaign.content_assets],
            audience_segments=[AudienceSegmentResponse(**vars(item)) for item in campaign.audience_segments],
            approval_decisions=[ApprovalDecisionResponse(**vars(item)) for item in campaign.approval_decisions],
            publications=[PublicationResponse(**vars(item)) for item in campaign.publications],
            source_evidences=[SourceEvidenceResponse(**vars(item)) for item in campaign.source_evidences],
        )


class WorkflowOperationResponse(BaseModel):
    correlation_id: str
    status: str
    details: dict
