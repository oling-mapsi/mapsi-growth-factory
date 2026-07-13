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
from app.domain.enums import AssetStatus
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
        self.audit_log.append(
            campaign_id,
            "review.bundle_requested",
            {"campaign_review_id": saved.id},
            actor_source="system",
            new_state={"review_status": "pending", "content_version": saved.content_version},
            result="SUCCESS",
        )
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
        self.audit_log.append(
            review.campaign_run_id,
            "review.content_updated",
            {"content_version": saved.content_version},
            actor_id=actor,
            actor_source="review_portal",
            previous_state={"content_version": saved.content_version - 1},
            new_state={"content_version": saved.content_version},
            result="SUCCESS",
        )
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
            {"comment": comment, "content_version": saved.content_version},
            actor_id=actor,
            actor_source="review_portal",
            previous_state={"content_version": saved.content_version - 1},
            new_state={"content_version": saved.content_version},
            result="SUCCESS",
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
                "approved_content_hash": saved.approved_content_hash,
                "approved_audience_hash": saved.approved_audience_hash,
                "content_version": saved.content_version,
                "segment_version": saved.segment_version,
            },
            actor_id=actor,
            actor_source="review_portal",
            previous_state={"review_status": "pending"},
            new_state={"review_status": "approved"},
            result="SUCCESS",
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
        self.audit_log.append(
            review.campaign_run_id,
            "review.rejected",
            {"comment": comment},
            actor_id=actor,
            actor_source="review_portal",
            previous_state={"review_status": "pending"},
            new_state={"review_status": "rejected"},
            result="SUCCESS",
        )
        return saved

    def update_asset_draft(
        self,
        asset_id: str,
        *,
        actor: str,
        expected_version: int,
        correlation_id: str,
        idempotency_key: str | None,
        comment: str = "",
        title: str | None = None,
        subject: str | None = None,
        content_html: str | None = None,
        content_text: str | None = None,
        excerpt: str | None = None,
        call_to_action: str | None = None,
        target_url: str | None = None,
    ):
        campaign, asset = self._find_campaign_asset(asset_id)
        self._ensure_not_sent(campaign.id)
        asset.assert_expected_version(expected_version)
        previous_version = asset.content_version
        previous_hash = asset.content_hash
        asset.update_draft(
            title=title,
            subject=subject,
            content_html=content_html,
            content_text=content_text,
            excerpt=excerpt,
            call_to_action=call_to_action,
            target_url=target_url,
        )
        self._stamp_asset_review_context(
            asset,
            decision="draft_updated",
            actor=actor,
            comment=comment,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            previous_version=previous_version,
        )
        saved = self.campaign_repository.save(campaign)
        self._invalidate_campaign_review(
            campaign.id,
            actor=actor,
            comment=comment,
            reason="asset_draft_updated",
        )
        self.audit_log.append(
            campaign.id,
            "review.asset_draft_updated",
            {
                "decision": "draft_updated",
                "comment": comment,
                "old_version": previous_version,
                "new_version": asset.content_version,
                "old_content_hash": previous_hash,
                "new_content_hash": asset.content_hash,
                "timestamp": datetime.now(UTC).isoformat(),
            },
            asset_id=asset.id,
            actor_id=actor,
            actor_source="mapsi-studio",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key or "",
            previous_state={"status": "DRAFT", "version": previous_version, "content_hash": previous_hash},
            new_state={"status": asset.status.value, "version": asset.content_version, "content_hash": asset.content_hash},
            channel=asset.channel,
            result="SUCCESS",
        )
        return self._require_campaign_asset(saved.id, asset.id)

    def request_asset_regeneration(
        self,
        asset_id: str,
        *,
        actor: str,
        expected_version: int,
        correlation_id: str,
        idempotency_key: str | None,
        comment: str = "",
    ):
        campaign, asset = self._find_campaign_asset(asset_id)
        self._ensure_not_sent(campaign.id)
        self._assert_reviewable_asset(asset, allow_approved=True)
        asset.assert_expected_version(expected_version)
        previous_version = asset.content_version
        decision = campaign.request_asset_regeneration(asset.id, comment, actor)
        self._stamp_asset_review_context(
            asset,
            decision="regeneration_requested",
            actor=actor,
            comment=comment,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            previous_version=previous_version,
        )
        saved = self.campaign_repository.save(campaign)
        self._invalidate_campaign_review(
            campaign.id,
            actor=actor,
            comment=comment,
            reason="asset_regeneration_requested",
        )
        self.audit_log.append(
            campaign.id,
            "review.asset_regeneration_requested",
            {
                "decision": decision.decision,
                "comment": comment,
                "old_version": previous_version,
                "new_version": asset.content_version,
                "timestamp": datetime.now(UTC).isoformat(),
            },
            asset_id=asset.id,
            actor_id=actor,
            actor_source="mapsi-studio",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key or "",
            previous_state={"status": "APPROVED" if previous_version == asset.content_version else asset.status.value, "version": previous_version},
            new_state={"status": asset.status.value, "version": asset.content_version},
            channel=asset.channel,
            result="SUCCESS",
        )
        return self._require_campaign_asset(saved.id, asset.id)

    def request_asset_changes(
        self,
        asset_id: str,
        *,
        actor: str,
        expected_version: int,
        correlation_id: str,
        idempotency_key: str | None,
        comment: str,
    ):
        if not comment.strip():
            raise ValueError("A comment is required to request changes.")
        campaign, asset = self._find_campaign_asset(asset_id)
        self._ensure_not_sent(campaign.id)
        self._assert_reviewable_asset(asset, allow_approved=True)
        asset.assert_expected_version(expected_version)
        previous_version = asset.content_version
        decision = campaign.request_asset_changes(asset.id, comment, actor)
        self._stamp_asset_review_context(
            asset,
            decision="changes_requested",
            actor=actor,
            comment=comment,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            previous_version=previous_version,
        )
        saved = self.campaign_repository.save(campaign)
        self._invalidate_campaign_review(
            campaign.id,
            actor=actor,
            comment=comment,
            reason="asset_changes_requested",
        )
        self.audit_log.append(
            campaign.id,
            "review.asset_changes_requested",
            {
                "decision": decision.decision,
                "comment": comment,
                "old_version": previous_version,
                "new_version": asset.content_version,
                "timestamp": datetime.now(UTC).isoformat(),
            },
            asset_id=asset.id,
            actor_id=actor,
            actor_source="mapsi-studio",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key or "",
            previous_state={"version": previous_version},
            new_state={"status": asset.status.value, "version": asset.content_version},
            channel=asset.channel,
            result="SUCCESS",
        )
        return self._require_campaign_asset(saved.id, asset.id)

    def approve_asset(
        self,
        asset_id: str,
        *,
        actor: str,
        expected_version: int,
        correlation_id: str,
        idempotency_key: str | None,
        comment: str = "",
    ):
        campaign, asset = self._find_campaign_asset(asset_id)
        self._ensure_not_sent(campaign.id)
        self._assert_quality_control(campaign.id)
        self._assert_reviewable_asset(asset, allow_approved=False)
        asset.assert_expected_version(expected_version)
        if asset.approved_at is not None and asset.approved_content_hash == asset.content_hash:
            raise EditorialGenerationBlockedError("Asset already approved.")
        previous_version = asset.content_version
        decision = campaign.approve_asset(asset.id, comment, actor)
        asset.results["approved_version"] = asset.content_version
        self._stamp_asset_review_context(
            asset,
            decision="approved",
            actor=actor,
            comment=comment,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            previous_version=previous_version,
        )
        saved = self.campaign_repository.save(campaign)
        self._approve_campaign_review_if_ready(campaign.id, actor=actor)
        self.audit_log.append(
            campaign.id,
            "review.asset_approved",
            {
                "decision": decision.decision,
                "comment": comment,
                "old_version": previous_version,
                "new_version": asset.content_version,
                "approved_version": asset.results.get("approved_version"),
                "approved_content_hash": asset.approved_content_hash,
                "timestamp": datetime.now(UTC).isoformat(),
            },
            asset_id=asset.id,
            actor_id=actor,
            actor_source="mapsi-studio",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key or "",
            previous_state={"status": "READY_FOR_REVIEW", "version": previous_version},
            new_state={"status": asset.status.value, "version": asset.content_version, "approved_content_hash": asset.approved_content_hash},
            channel=asset.channel,
            result="SUCCESS",
        )
        return self._require_campaign_asset(saved.id, asset.id)

    def reject_asset(
        self,
        asset_id: str,
        *,
        actor: str,
        expected_version: int,
        correlation_id: str,
        idempotency_key: str | None,
        comment: str,
    ):
        if not comment.strip():
            raise ValueError("A comment is required to reject an asset.")
        campaign, asset = self._find_campaign_asset(asset_id)
        self._ensure_not_sent(campaign.id)
        self._assert_reviewable_asset(asset, allow_approved=True)
        asset.assert_expected_version(expected_version)
        previous_version = asset.content_version
        decision = campaign.reject_asset(asset.id, comment, actor)
        self._stamp_asset_review_context(
            asset,
            decision="rejected",
            actor=actor,
            comment=comment,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            previous_version=previous_version,
        )
        saved = self.campaign_repository.save(campaign)
        self._invalidate_campaign_review(
            campaign.id,
            actor=actor,
            comment=comment,
            reason="asset_rejected",
        )
        self.audit_log.append(
            campaign.id,
            "review.asset_rejected",
            {
                "decision": decision.decision,
                "comment": comment,
                "old_version": previous_version,
                "new_version": asset.content_version,
                "timestamp": datetime.now(UTC).isoformat(),
            },
            asset_id=asset.id,
            actor_id=actor,
            actor_source="mapsi-studio",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key or "",
            previous_state={"version": previous_version},
            new_state={"status": asset.status.value, "version": asset.content_version},
            channel=asset.channel,
            result="SUCCESS",
        )
        return self._require_campaign_asset(saved.id, asset.id)

    def approve_ready_assets(
        self,
        campaign_id: str,
        *,
        actor: str,
        correlation_id: str,
        idempotency_key: str | None,
        comment: str = "",
    ) -> list:
        campaign = self.campaign_repository.get(campaign_id)
        if campaign is None:
            raise CampaignNotFoundError(f"Campaign {campaign_id} not found.")
        self._ensure_not_sent(campaign.id)
        self._assert_quality_control(campaign.id)
        ready_assets = [item for item in campaign.content_assets if item.status in {AssetStatus.READY_FOR_REVIEW, AssetStatus.QUALITY_CHECK}]
        if not ready_assets:
            raise EditorialGenerationBlockedError("Campaign has no ready assets to approve.")
        approved_ids: list[str] = []
        for asset in ready_assets:
            campaign.approve_asset(asset.id, comment, actor)
            asset.results["approved_version"] = asset.content_version
            self._stamp_asset_review_context(
                asset,
                decision="approved",
                actor=actor,
                comment=comment,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                previous_version=asset.content_version,
            )
            approved_ids.append(asset.id)
        saved = self.campaign_repository.save(campaign)
        self._approve_campaign_review_if_ready(campaign.id, actor=actor)
        self.audit_log.append(
            campaign.id,
            "review.ready_assets_approved",
            {
                "actor": actor,
                "decision": "APPROVED",
                "asset_ids": approved_ids,
                "comment": comment,
                "correlation_id": correlation_id,
                "idempotency_key": idempotency_key or "",
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
        reloaded = self.campaign_repository.get(saved.id)
        assert reloaded is not None
        return [item for item in reloaded.content_assets if item.id in approved_ids]

    def reject_ready_assets(
        self,
        campaign_id: str,
        *,
        actor: str,
        correlation_id: str,
        idempotency_key: str | None,
        comment: str,
    ) -> list:
        if not comment.strip():
            raise ValueError("A comment is required to reject ready assets.")
        campaign = self.campaign_repository.get(campaign_id)
        if campaign is None:
            raise CampaignNotFoundError(f"Campaign {campaign_id} not found.")
        self._ensure_not_sent(campaign.id)
        ready_assets = [item for item in campaign.content_assets if item.status in {AssetStatus.READY_FOR_REVIEW, AssetStatus.QUALITY_CHECK}]
        if not ready_assets:
            raise EditorialGenerationBlockedError("Campaign has no ready assets to reject.")
        rejected_ids: list[str] = []
        for asset in ready_assets:
            campaign.reject_asset(asset.id, comment, actor)
            self._stamp_asset_review_context(
                asset,
                decision="rejected",
                actor=actor,
                comment=comment,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                previous_version=asset.content_version - 1,
            )
            rejected_ids.append(asset.id)
        saved = self.campaign_repository.save(campaign)
        self._invalidate_campaign_review(
            campaign.id,
            actor=actor,
            comment=comment,
            reason="ready_assets_rejected",
        )
        self.audit_log.append(
            campaign.id,
            "review.ready_assets_rejected",
            {
                "actor": actor,
                "decision": "REJECTED",
                "asset_ids": rejected_ids,
                "comment": comment,
                "correlation_id": correlation_id,
                "idempotency_key": idempotency_key or "",
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
        reloaded = self.campaign_repository.get(saved.id)
        assert reloaded is not None
        return [item for item in reloaded.content_assets if item.id in rejected_ids]

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

    def _find_campaign_asset(self, asset_id: str):
        for campaign in self.campaign_repository.list():
            for asset in campaign.content_assets:
                if asset.id == asset_id:
                    return campaign, asset
        raise CampaignNotFoundError(f"Asset {asset_id} not found.")

    def _require_campaign_asset(self, campaign_id: str, asset_id: str):
        campaign = self.campaign_repository.get(campaign_id)
        if campaign is None:
            raise CampaignNotFoundError(f"Campaign {campaign_id} not found.")
        for asset in campaign.content_assets:
            if asset.id == asset_id:
                return asset
        raise CampaignNotFoundError(f"Asset {asset_id} not found.")

    def _assert_reviewable_asset(self, asset, *, allow_approved: bool) -> None:
        allowed = {AssetStatus.DRAFT, AssetStatus.READY_FOR_REVIEW, AssetStatus.QUALITY_CHECK, AssetStatus.CHANGES_REQUESTED}
        if allow_approved:
            allowed.add(AssetStatus.APPROVED)
        if asset.status not in allowed:
            raise EditorialGenerationBlockedError(f"Asset {asset.id} cannot be reviewed from status {asset.status.value}.")

    def _assert_quality_control(self, campaign_id: str) -> None:
        review = self.review_repository.get_review_by_campaign(campaign_id)
        if review is None:
            raise EditorialGenerationBlockedError("Campaign review bundle is missing.")
        qc = review.quality_control or {}
        if qc.get("passed") is False or qc.get("status") == "failed":
            raise EditorialGenerationBlockedError("Quality control must pass before approval.")

    def _invalidate_campaign_review(self, campaign_id: str, *, actor: str, comment: str, reason: str) -> None:
        review = self.review_repository.get_review_by_campaign(campaign_id)
        if review is None:
            return
        review.content_version = max(review.content_version, self._campaign_max_content_version(campaign_id))
        review.approved_content_hash = ""
        review.approved_audience_hash = ""
        review.approved_by = ""
        review.approved_at = None
        review.rejected_by = ""
        review.rejected_at = None
        self.review_repository.save_review(review)
        self.audit_log.append(
            campaign_id,
            "review.bundle_invalidated",
            {
                "actor": actor,
                "comment": comment,
                "reason": reason,
                "content_version": review.content_version,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    def _approve_campaign_review_if_ready(self, campaign_id: str, *, actor: str) -> None:
        campaign = self.campaign_repository.get(campaign_id)
        if campaign is None or not campaign.content_assets:
            return
        active_assets = [item for item in campaign.content_assets if item.status is not AssetStatus.CANCELLED]
        if not active_assets or any(item.status is not AssetStatus.APPROVED for item in active_assets):
            return
        review = self.review_repository.get_review_by_campaign(campaign_id)
        if review is None:
            return
        review.content_version = max(review.content_version, self._campaign_max_content_version(campaign_id))
        review.approved_content_hash = self.content_hash(review)
        review.approved_audience_hash = self.audience_hash(review)
        review.approved_by = actor
        review.approved_at = datetime.now(UTC)
        review.rejected_by = ""
        review.rejected_at = None
        self.review_repository.save_review(review)

    def _campaign_max_content_version(self, campaign_id: str) -> int:
        campaign = self.campaign_repository.get(campaign_id)
        if campaign is None:
            raise CampaignNotFoundError(f"Campaign {campaign_id} not found.")
        return max([item.content_version for item in campaign.content_assets], default=1)

    def _stamp_asset_review_context(
        self,
        asset,
        *,
        decision: str,
        actor: str,
        comment: str,
        correlation_id: str,
        idempotency_key: str | None,
        previous_version: int,
    ) -> None:
        asset.results = {
            **asset.results,
            "last_review_actor": actor,
            "last_review_comment": comment,
            "last_review_decision": decision,
            "last_review_correlation_id": correlation_id,
            "last_review_idempotency_key": idempotency_key or "",
            "last_reviewed_at": datetime.now(UTC).isoformat(),
            "previous_content_version": previous_version,
        }

    def _ensure_not_sent(self, campaign_id: str) -> None:
        campaign = self.campaign_repository.get(campaign_id)
        if campaign is None:
            raise CampaignNotFoundError(f"Campaign {campaign_id} not found.")
        if campaign.publications:
            raise EditorialGenerationBlockedError("Campaign already sent.")

    def _html_to_text(self, value: str) -> str:
        return unescape(value.replace("<br />", "\n").replace("<br>", "\n").replace("</p>", "\n")).strip()
