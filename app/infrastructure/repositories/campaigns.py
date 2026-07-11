from sqlalchemy.orm import Session, selectinload

from app.application.ports.repositories import CampaignRepositoryPort
from app.domain.entities import (
    ApprovalDecision,
    AudienceSegment,
    build_content_hash,
    CampaignRun,
    ContentAsset,
    EditorialBrief,
    Interaction,
    Lead,
    Publication,
    SourceEvidence,
)
from app.domain.enums import AssetStatus, CampaignStatus
from app.infrastructure.db.models import (
    ApprovalDecisionModel,
    AudienceSegmentModel,
    CampaignRunModel,
    ContentAssetModel,
    EditorialBriefModel,
    InteractionModel,
    LeadModel,
    PublicationModel,
    SourceEvidenceModel,
)


class SqlAlchemyCampaignRepository(CampaignRepositoryPort):
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, campaign: CampaignRun) -> CampaignRun:
        self._normalize_assets(campaign)
        model = self._to_model(campaign)
        self.session.add(model)
        self.session.commit()
        self.session.refresh(model)
        return self._to_entity(model)

    def get(self, campaign_id: str) -> CampaignRun | None:
        model = (
            self.session.query(CampaignRunModel)
            .options(
                selectinload(CampaignRunModel.editorial_briefs),
                selectinload(CampaignRunModel.content_assets),
                selectinload(CampaignRunModel.audience_segments),
                selectinload(CampaignRunModel.approval_decisions),
                selectinload(CampaignRunModel.publications),
                selectinload(CampaignRunModel.interactions),
                selectinload(CampaignRunModel.leads),
                selectinload(CampaignRunModel.source_evidences),
            )
            .filter(CampaignRunModel.id == campaign_id)
            .one_or_none()
        )
        return self._to_entity(model) if model else None

    def list(self) -> list[CampaignRun]:
        models = self.session.query(CampaignRunModel).order_by(CampaignRunModel.created_at.desc()).all()
        return [self._to_entity(model) for model in models]

    def save(self, campaign: CampaignRun) -> CampaignRun:
        self._normalize_assets(campaign)
        model = self.session.get(CampaignRunModel, campaign.id)
        if model is None:
            return self.add(campaign)
        replacement = self._to_model(campaign)
        self.session.merge(replacement)
        self.session.commit()
        persisted = self.session.get(CampaignRunModel, campaign.id)
        return self._to_entity(persisted)

    def _normalize_assets(self, campaign: CampaignRun) -> None:
        for asset in campaign.content_assets:
            asset.ensure_content_hash()

    def _to_model(self, campaign: CampaignRun) -> CampaignRunModel:
        return CampaignRunModel(
            id=campaign.id,
            name=campaign.name,
            objective=campaign.objective,
            status=campaign.status.value,
            created_at=campaign.created_at,
            updated_at=campaign.updated_at,
            editorial_briefs=[
                EditorialBriefModel(
                    id=item.id,
                    campaign_run_id=campaign.id,
                    title=item.title,
                    summary=item.summary,
                    created_at=item.created_at,
                )
                for item in campaign.editorial_briefs
            ],
            content_assets=[
                ContentAssetModel(
                    id=item.id,
                    campaign_run_id=campaign.id,
                    asset_type=item.asset_type,
                    channel=item.channel,
                    locale=item.locale,
                    title=item.title,
                    subject=item.subject,
                    body=item.body,
                    content_html=item.content_html or item.body,
                    content_text=item.content_text,
                    excerpt=item.excerpt,
                    call_to_action=item.call_to_action,
                    target_url=item.target_url,
                    evidence_ids=item.evidence_ids,
                    source_evidence_ids=item.source_evidence_ids or item.evidence_ids,
                    audience_segment_id=item.audience_segment_id,
                    status=item.status.value,
                    content_version=item.content_version,
                    content_hash=item.content_hash
                    or build_content_hash(
                        item.asset_type,
                        item.title,
                        item.body,
                        item.evidence_ids,
                        item.audience_segment_id,
                        locale=item.locale,
                        subject=item.subject,
                        content_html=item.content_html,
                        content_text=item.content_text,
                        excerpt=item.excerpt,
                        call_to_action=item.call_to_action,
                        target_url=item.target_url,
                    ),
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
                    revision=item.content_version,
                    created_at=item.created_at,
                )
                for item in campaign.content_assets
            ],
            audience_segments=[
                AudienceSegmentModel(
                    id=item.id,
                    campaign_run_id=campaign.id,
                    name=item.name,
                    description=item.description,
                    created_at=item.created_at,
                )
                for item in campaign.audience_segments
            ],
            approval_decisions=[
                ApprovalDecisionModel(
                    id=item.id,
                    campaign_run_id=campaign.id,
                    decision=item.decision,
                    decided_by=item.decided_by,
                    comment=item.comment,
                    created_at=item.created_at,
                )
                for item in campaign.approval_decisions
            ],
            publications=[
                PublicationModel(
                    id=item.id,
                    campaign_run_id=campaign.id,
                    content_asset_id=item.content_asset_id,
                    channel=item.channel,
                    external_reference=item.external_reference,
                    external_url=item.external_url,
                    published_at=item.published_at,
                )
                for item in campaign.publications
            ],
            interactions=[
                InteractionModel(
                    id=item.id,
                    campaign_run_id=campaign.id,
                    interaction_type=item.interaction_type,
                    occurred_at=item.occurred_at,
                    metadata_payload=item.metadata,
                )
                for item in campaign.interactions
            ],
            leads=[
                LeadModel(
                    id=item.id,
                    campaign_run_id=campaign.id,
                    email=item.email,
                    full_name=item.full_name,
                    created_at=item.created_at,
                )
                for item in campaign.leads
            ],
            source_evidences=[
                SourceEvidenceModel(
                    id=item.id,
                    campaign_run_id=campaign.id,
                    product_change_id=item.product_change_id or None,
                    source_system=item.source_system,
                    evidence_type=item.evidence_type,
                    reference=item.reference,
                    payload=item.payload,
                    created_at=item.created_at,
                )
                for item in campaign.source_evidences
            ],
        )

    def _to_entity(self, model: CampaignRunModel) -> CampaignRun:
        return CampaignRun(
            id=model.id,
            name=model.name,
            objective=model.objective,
            status=CampaignStatus(model.status),
            created_at=model.created_at,
            updated_at=model.updated_at,
            editorial_briefs=[
                EditorialBrief(
                    id=item.id,
                    campaign_run_id=item.campaign_run_id,
                    title=item.title,
                    summary=item.summary,
                    created_at=item.created_at,
                )
                for item in model.editorial_briefs
            ],
            content_assets=[
                ContentAsset(
                    id=item.id,
                    campaign_run_id=item.campaign_run_id,
                    asset_type=item.asset_type,
                    channel=item.channel,
                    locale=item.locale,
                    title=item.title,
                    subject=item.subject,
                    content_html=item.content_html or item.body,
                    content_text=item.content_text or item.body,
                    body=item.body,
                    evidence_ids=list(item.evidence_ids or []),
                    excerpt=item.excerpt,
                    call_to_action=item.call_to_action,
                    target_url=item.target_url,
                    source_evidence_ids=list(item.source_evidence_ids or item.evidence_ids or []),
                    audience_segment_id=item.audience_segment_id,
                    status=AssetStatus(item.status),
                    content_version=item.content_version or item.revision,
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
                    results=dict(item.results or {}),
                    revision=item.revision,
                    created_at=item.created_at,
                )
                for item in model.content_assets
            ],
            audience_segments=[
                AudienceSegment(
                    id=item.id,
                    campaign_run_id=item.campaign_run_id,
                    name=item.name,
                    description=item.description,
                    created_at=item.created_at,
                )
                for item in model.audience_segments
            ],
            approval_decisions=[
                ApprovalDecision(
                    id=item.id,
                    campaign_run_id=item.campaign_run_id,
                    decision=item.decision,
                    decided_by=item.decided_by,
                    comment=item.comment,
                    created_at=item.created_at,
                )
                for item in model.approval_decisions
            ],
            publications=[
                Publication(
                    id=item.id,
                    campaign_run_id=item.campaign_run_id,
                    content_asset_id=item.content_asset_id,
                    channel=item.channel,
                    external_reference=item.external_reference,
                    external_url=item.external_url,
                    published_at=item.published_at,
                )
                for item in model.publications
            ],
            interactions=[
                Interaction(
                    id=item.id,
                    campaign_run_id=item.campaign_run_id,
                    interaction_type=item.interaction_type,
                    occurred_at=item.occurred_at,
                    metadata=item.metadata_payload,
                )
                for item in model.interactions
            ],
            leads=[
                Lead(
                    id=item.id,
                    campaign_run_id=item.campaign_run_id,
                    email=item.email,
                    full_name=item.full_name,
                    created_at=item.created_at,
                )
                for item in model.leads
            ],
            source_evidences=[
                SourceEvidence(
                    id=item.id,
                    campaign_run_id=item.campaign_run_id or "",
                    product_change_id=item.product_change_id or "",
                    source_system=item.source_system,
                    evidence_type=item.evidence_type,
                    reference=item.reference,
                    payload=item.payload,
                    created_at=item.created_at,
                )
                for item in model.source_evidences
            ],
        )
