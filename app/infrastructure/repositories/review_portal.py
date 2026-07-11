from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.domain.entities import CampaignReview, ReviewToken
from app.infrastructure.db.models import CampaignReviewModel, ReviewTokenModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class ReviewPortalRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save_review(self, review: CampaignReview) -> CampaignReview:
        model = self.session.query(CampaignReviewModel).filter(CampaignReviewModel.campaign_run_id == review.campaign_run_id).one_or_none()
        if model is None:
            model = CampaignReviewModel(id=review.id, campaign_run_id=review.campaign_run_id)
            self.session.add(model)
        for key, value in review.__dict__.items():
            setattr(model, key, value)
        self.session.commit()
        self.session.refresh(model)
        return self._to_review(model)

    def get_review_by_campaign(self, campaign_run_id: str) -> CampaignReview | None:
        model = self.session.query(CampaignReviewModel).filter(CampaignReviewModel.campaign_run_id == campaign_run_id).one_or_none()
        return self._to_review(model) if model else None

    def get_review_by_id(self, review_id: str) -> CampaignReview | None:
        model = self.session.query(CampaignReviewModel).filter(CampaignReviewModel.id == review_id).one_or_none()
        return self._to_review(model) if model else None

    def create_token(self, token: ReviewToken) -> ReviewToken:
        model = ReviewTokenModel(
            id=token.id,
            campaign_review_id=token.campaign_review_id,
            token_hash=token.token_hash,
            expires_at=token.expires_at,
            max_uses=token.max_uses,
            used_count=token.used_count,
            revoked_at=token.revoked_at,
            created_at=token.created_at,
        )
        self.session.add(model)
        self.session.commit()
        self.session.refresh(model)
        return self._to_token(model)

    def get_token(self, token_hash: str) -> ReviewToken | None:
        model = self.session.query(ReviewTokenModel).filter(ReviewTokenModel.token_hash == token_hash).one_or_none()
        return self._to_token(model) if model else None

    def consume_token(self, token_hash: str) -> ReviewToken:
        model = self.session.query(ReviewTokenModel).filter(ReviewTokenModel.token_hash == token_hash).one()
        model.used_count += 1
        self.session.commit()
        self.session.refresh(model)
        return self._to_token(model)

    def revoke_token(self, token_hash: str) -> None:
        model = self.session.query(ReviewTokenModel).filter(ReviewTokenModel.token_hash == token_hash).one()
        model.revoked_at = utcnow()
        self.session.commit()

    def _to_review(self, model: CampaignReviewModel) -> CampaignReview:
        return CampaignReview(
            id=model.id,
            campaign_run_id=model.campaign_run_id,
            theme=model.theme,
            objective=model.objective,
            segment_id=model.segment_id,
            segment_label=model.segment_label,
            segment_version=model.segment_version,
            audience_volume=model.audience_volume,
            exclusions=model.exclusions,
            evidence_ids=model.evidence_ids,
            email_subject=model.email_subject,
            email_preheader=model.email_preheader,
            email_html=model.email_html,
            email_text=model.email_text,
            quality_control=model.quality_control,
            proposed_at=ensure_utc(model.proposed_at) or utcnow(),
            content_version=model.content_version,
            approved_content_hash=model.approved_content_hash,
            approved_audience_hash=model.approved_audience_hash,
            approved_by=model.approved_by,
            approved_at=ensure_utc(model.approved_at),
            rejected_at=ensure_utc(model.rejected_at),
            rejected_by=model.rejected_by,
        )

    def _to_token(self, model: ReviewTokenModel) -> ReviewToken:
        return ReviewToken(
            id=model.id,
            campaign_review_id=model.campaign_review_id,
            token_hash=model.token_hash,
            expires_at=ensure_utc(model.expires_at) or utcnow(),
            max_uses=model.max_uses,
            used_count=model.used_count,
            revoked_at=ensure_utc(model.revoked_at),
            created_at=ensure_utc(model.created_at) or utcnow(),
        )
