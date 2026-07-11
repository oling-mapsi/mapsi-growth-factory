from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime, timedelta
from html import unescape

from app.application.ports.audit import AuditLogPort
from app.application.ports.repositories import CampaignRepositoryPort
from app.core.config import get_settings
from app.core.security import hash_review_token, sha256_hexdigest
from app.domain.entities import CampaignReview, ReviewToken
from app.domain.errors import CampaignNotFoundError, CampaignPublicationForbiddenError, EditorialGenerationBlockedError
from app.infrastructure.repositories.review_portal import ReviewPortalRepository


class ReviewPortalService:
    def __init__(
        self,
        campaign_repository: CampaignRepositoryPort,
        review_repository: ReviewPortalRepository,
        audit_log: AuditLogPort,
    ) -> None:
        self.campaign_repository = campaign_repository
        self.review_repository = review_repository
        self.audit_log = audit_log
        self.settings = get_settings()

    def prepare_review(self, campaign_id: str, *, proposed_at: datetime | None = None) -> tuple[CampaignReview, str]:
        campaign = self.campaign_repository.get(campaign_id)
        if campaign is None:
            raise CampaignNotFoundError(f"Campaign {campaign_id} not found.")
        if not campaign.content_assets:
            raise EditorialGenerationBlockedError("Campaign has no content to review.")
        if not campaign.audience_segments:
            raise EditorialGenerationBlockedError("Campaign has no audience segment to review.")
        review = self.review_repository.get_review_by_campaign(campaign_id) or CampaignReview(campaign_run_id=campaign_id)
        primary_asset = campaign.content_assets[0]
        primary_segment = campaign.audience_segments[0]
        review.theme = campaign.name
        review.objective = campaign.objective
        review.segment_id = primary_segment.id
        review.segment_label = primary_segment.name
        review.audience_volume = max(review.audience_volume, 1)
        review.evidence_ids = [item.id for item in campaign.source_evidences]
        review.email_subject = primary_asset.title or campaign.name
        review.email_preheader = review.email_preheader or campaign.objective
        review.email_html = primary_asset.body
        review.email_text = self._html_to_text(primary_asset.body)
        review.quality_control = review.quality_control or {"status": "pending"}
        review.proposed_at = proposed_at or review.proposed_at
        review.content_version = max([asset.revision for asset in campaign.content_assets], default=1)
        review.approved_content_hash = ""
        review.approved_audience_hash = ""
        review.approved_by = ""
        review.approved_at = None
        review.rejected_by = ""
        review.rejected_at = None
        saved = self.review_repository.save_review(review)
        token = self.create_review_token(saved.id)
        self.audit_log.append(campaign_id, "review.bundle_requested", {"campaign_review_id": saved.id})
        return saved, token

    def review_status(self, campaign_id: str) -> dict[str, object]:
        review = self.review_repository.get_review_by_campaign(campaign_id)
        if review is None:
            return {"status": "missing_review"}
        if review.rejected_at is not None:
            return {"status": "rejected", "rejected_at": review.rejected_at, "rejected_by": review.rejected_by}
        if review.approved_at is not None:
            return {
                "status": "approved",
                "approved_at": review.approved_at,
                "approved_by": review.approved_by,
                "content_hash": self.content_hash(review),
                "audience_hash": self.audience_hash(review),
            }
        return {"status": "pending", "content_version": review.content_version, "segment_version": review.segment_version}

    def publication_readiness(self, campaign_id: str, *, scheduled_at: datetime | None = None) -> dict[str, object]:
        campaign = self.campaign_repository.get(campaign_id)
        if campaign is None:
            raise CampaignNotFoundError(f"Campaign {campaign_id} not found.")
        review = self.review_repository.get_review_by_campaign(campaign_id)
        current_status = self.review_status(campaign_id)
        content_hash_unchanged = review is not None and review.approved_content_hash == self.content_hash(review)
        audience_hash_unchanged = review is not None and review.approved_audience_hash == self.audience_hash(review)
        scheduled_at_valid = scheduled_at is None or scheduled_at >= datetime.now(UTC)
        kill_switch_disabled = not self.settings.workflow_kill_switch
        publishable = (
            campaign.status.value in {"APPROVED", "PARTIALLY_PUBLISHED"}
            and current_status["status"] == "approved"
            and content_hash_unchanged
            and audience_hash_unchanged
            and scheduled_at_valid
            and kill_switch_disabled
        )
        return {
            "campaign_id": campaign_id,
            "status": campaign.status.value,
            "review_status": current_status["status"],
            "content_hash": self.content_hash(review) if review is not None else "",
            "approved_content_hash": review.approved_content_hash if review is not None else "",
            "content_hash_unchanged": content_hash_unchanged,
            "audience_hash": self.audience_hash(review) if review is not None else "",
            "approved_audience_hash": review.approved_audience_hash if review is not None else "",
            "audience_hash_unchanged": audience_hash_unchanged,
            "scheduled_at": scheduled_at,
            "scheduled_at_valid": scheduled_at_valid,
            "kill_switch_disabled": kill_switch_disabled,
            "publishable": publishable,
        }

    def create_review_token(self, campaign_review_id: str) -> str:
        raw = secrets.token_urlsafe(24)
        token = ReviewToken(
            campaign_review_id=campaign_review_id,
            token_hash=hash_review_token(raw),
            expires_at=datetime.now(UTC) + timedelta(minutes=self.settings.review_token_ttl_minutes),
            max_uses=self.settings.review_token_max_uses,
        )
        self.review_repository.create_token(token)
        return raw

    def get_review_by_token(self, raw_token: str) -> CampaignReview:
        token = self._require_valid_token(raw_token, consume=False)
        review = self._find_review(token.campaign_review_id)
        return review

    def update_content(self, raw_token: str, *, actor: str, email_subject: str, email_preheader: str, email_html: str, email_text: str) -> CampaignReview:
        token = self._require_valid_token(raw_token, consume=True)
        review = self._find_review(token.campaign_review_id)
        self._ensure_not_sent(review.campaign_run_id)
        review.email_subject = email_subject
        review.email_preheader = email_preheader
        review.email_html = email_html
        review.email_text = email_text
        review.content_version += 1
        review.approved_content_hash = ""
        review.approved_audience_hash = ""
        review.approved_by = ""
        review.approved_at = None
        saved = self.review_repository.save_review(review)
        self.audit_log.append(review.campaign_run_id, "review.content_updated", {"actor": actor, "content_version": saved.content_version})
        return saved

    def request_new_version(self, raw_token: str, *, actor: str, comment: str) -> CampaignReview:
        token = self._require_valid_token(raw_token, consume=True)
        review = self._find_review(token.campaign_review_id)
        self._ensure_not_sent(review.campaign_run_id)
        review.content_version += 1
        review.approved_content_hash = ""
        review.approved_audience_hash = ""
        review.approved_by = ""
        review.approved_at = None
        saved = self.review_repository.save_review(review)
        self.audit_log.append(
            review.campaign_run_id,
            "review.new_version_requested",
            {"actor": actor, "comment": comment, "content_version": saved.content_version},
        )
        return saved

    def approve(self, raw_token: str, *, actor: str) -> CampaignReview:
        token = self._require_valid_token(raw_token, consume=True)
        review = self._find_review(token.campaign_review_id)
        self._ensure_not_sent(review.campaign_run_id)
        if review.approved_at is not None:
            raise EditorialGenerationBlockedError("Review already approved.")
        review.approved_content_hash = self.content_hash(review)
        review.approved_audience_hash = self.audience_hash(review)
        review.approved_by = actor
        review.approved_at = datetime.now(UTC)
        saved = self.review_repository.save_review(review)
        self.audit_log.append(
            review.campaign_run_id,
            "review.approved",
            {
                "actor": actor,
                "approved_content_hash": saved.approved_content_hash,
                "approved_audience_hash": saved.approved_audience_hash,
                "content_version": saved.content_version,
                "segment_version": saved.segment_version,
            },
        )
        return saved

    def reject(self, raw_token: str, *, actor: str, comment: str) -> CampaignReview:
        token = self._require_valid_token(raw_token, consume=True)
        review = self._find_review(token.campaign_review_id)
        self._ensure_not_sent(review.campaign_run_id)
        review.rejected_by = actor
        review.rejected_at = datetime.now(UTC)
        review.approved_content_hash = ""
        review.approved_audience_hash = ""
        review.approved_by = ""
        review.approved_at = None
        saved = self.review_repository.save_review(review)
        self.audit_log.append(review.campaign_run_id, "review.rejected", {"actor": actor, "comment": comment})
        return saved

    def revoke_token(self, raw_token: str, *, actor: str) -> None:
        token_hash = hash_review_token(raw_token)
        token = self.review_repository.get_token(token_hash)
        if token is None:
            raise EditorialGenerationBlockedError("Unknown review token.")
        self.review_repository.revoke_token(token_hash)
        review = self._find_review(token.campaign_review_id)
        self.audit_log.append(review.campaign_run_id, "review.token_revoked", {"actor": actor})

    def ensure_publishable(self, campaign_id: str) -> None:
        review = self.review_repository.get_review_by_campaign(campaign_id)
        if review is None:
            return
        if review.approved_at is None:
            raise CampaignPublicationForbiddenError("Campaign review has not been approved.")
        if review.approved_content_hash != self.content_hash(review) or review.approved_audience_hash != self.audience_hash(review):
            raise CampaignPublicationForbiddenError("Approved review hashes no longer match current content or audience.")

    def content_hash(self, review: CampaignReview) -> str:
        payload = json.dumps(
            {
                "theme": review.theme,
                "objective": review.objective,
                "email_subject": review.email_subject,
                "email_preheader": review.email_preheader,
                "email_html": review.email_html,
                "email_text": review.email_text,
                "content_version": review.content_version,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256_hexdigest(payload)

    def audience_hash(self, review: CampaignReview) -> str:
        payload = json.dumps(
            {
                "segment_id": review.segment_id,
                "segment_label": review.segment_label,
                "segment_version": review.segment_version,
                "audience_volume": review.audience_volume,
                "exclusions": review.exclusions,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256_hexdigest(payload)

    def _require_valid_token(self, raw_token: str, *, consume: bool) -> ReviewToken:
        token = self.review_repository.get_token(hash_review_token(raw_token))
        if token is None:
            raise EditorialGenerationBlockedError("Unknown review token.")
        if token.revoked_at is not None:
            raise EditorialGenerationBlockedError("Review token has been revoked.")
        if token.expires_at <= datetime.now(UTC):
            raise EditorialGenerationBlockedError("Review token has expired.")
        if token.used_count >= token.max_uses:
            raise EditorialGenerationBlockedError("Review token usage limit exceeded.")
        if consume:
            return self.review_repository.consume_token(token.token_hash)
        return token

    def _find_review(self, review_id: str) -> CampaignReview:
        review = self.review_repository.get_review_by_id(review_id)
        if review is None:
            raise EditorialGenerationBlockedError("No review package available for this campaign.")
        return review

    def _ensure_not_sent(self, campaign_id: str) -> None:
        campaign = self.campaign_repository.get(campaign_id)
        if campaign is None:
            raise CampaignNotFoundError(f"Campaign {campaign_id} not found.")
        if campaign.publications:
            raise EditorialGenerationBlockedError("Campaign already sent.")

    def _html_to_text(self, value: str) -> str:
        return unescape(value.replace("<br />", "\n").replace("<br>", "\n").replace("</p>", "\n")).strip()
