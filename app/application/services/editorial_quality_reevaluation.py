import json
import re

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.models.editorial_v1 import EditorialArticle, EditorialGenerationContext, EditorialQualityIssue
from app.application.services.editorial_engine_v1 import EditorialQualityValidator
from app.domain.errors import CampaignNotFoundError, InvalidStateTransitionError, OptimisticLockError
from app.infrastructure.db.models import CampaignRunModel, ContentAssetModel, SimpleGenerationJobModel
from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository


def _visible(value: str) -> str:
    return re.sub(r"\s+", " ", BeautifulSoup(value or "", "html.parser").get_text()).strip()


class EditorialQualityReevaluationService:
    def __init__(self, session: Session):
        self.session = session

    def reevaluate(self, asset_id: str, *, expected_version: int, expected_hash: str, actor: str, apply: bool = False):
        campaign_id = self.session.scalar(select(ContentAssetModel.campaign_run_id).where(ContentAssetModel.id == asset_id))
        if not campaign_id:
            raise CampaignNotFoundError("Editorial asset not found.")
        campaign = self.session.scalar(select(CampaignRunModel).where(CampaignRunModel.id == campaign_id).with_for_update().execution_options(populate_existing=True))
        row = self.session.scalar(select(ContentAssetModel).where(ContentAssetModel.id == asset_id).with_for_update().execution_options(populate_existing=True))
        if row.content_version != expected_version or not expected_hash or row.content_hash != expected_hash:
            raise OptimisticLockError("Article version or content hash changed; quality reevaluation refused.")
        if row.status in {"PUBLISHING", "PUBLISHED", "APPROVED"}:
            raise InvalidStateTransitionError("Do not replace the quality report of a publishing or approved version.")
        active = self.session.scalar(select(SimpleGenerationJobModel.id).where(SimpleGenerationJobModel.campaign_run_id == campaign_id, SimpleGenerationJobModel.status.in_(["PENDING", "RUNNING"])))
        if active:
            raise InvalidStateTransitionError("Wait until the campaign editorial job finishes.")
        results = dict(row.results or {})
        context_payload = dict(results.get("builder_context") or {})
        if not context_payload.get("publication_channel") and row.channel in {"oling", "oling_site", "mapsi_site"}:
            context_payload["publication_channel"] = "mapsi_site" if row.channel == "mapsi_site" else "oling_site"
        context = EditorialGenerationContext.model_validate_json(json.dumps(context_payload))
        stored = EditorialArticle.model_validate(results.get("editorial_article") or {})
        current = stored.model_copy(deep=True, update={"title": row.title, "body_html": row.content_html, "body_text": row.content_text, "excerpt": row.excerpt})
        report = EditorialQualityValidator().validate(current, context)
        plain = re.sub(r"\s+", " ", row.content_text).strip()
        stored_plain = re.sub(r"\s+", " ", stored.body_text).strip()
        html_plain = re.sub(r"\s+", " ", BeautifulSoup(row.content_html, "html.parser").get_text(" ", strip=True)).strip()
        consistent = (row.title == stored.title and row.excerpt == stored.excerpt
                      and _visible(row.content_html) == _visible(stored.body_html)
                      and plain in {stored_plain, html_plain})
        if not consistent:
            report.issues.append(EditorialQualityIssue(code="editorial_content_mismatch", message="Current article differs from its sourced editorial record; human review is required.", severity="error"))
            report.passed = False
        before_status = row.status
        if apply:
            old_quality = results.get("editorial_quality") or {}
            row.results = {**results, "editorial_quality": report.model_dump(mode="json")}
            if report.passed and row.status == "QUALITY_FAILED":
                row.status = "READY_FOR_REVIEW"
            elif not report.passed:
                row.status = "QUALITY_FAILED"
            if report.passed and campaign.status == "FAILED":
                campaign.status = "READY_FOR_REVIEW"
            try:
                SqlAlchemyAuditLogRepository(self.session).append(campaign_id, "editorial.asset_quality_reevaluated", {"version": expected_version, "content_hash": expected_hash, "provider_calls": 0}, asset_id=asset_id, actor_id=actor, actor_source="oling-admin", previous_state={"status":before_status,"editorial_quality":old_quality}, new_state={"status":row.status,"editorial_quality":report.model_dump(mode="json")}, result="SUCCESS" if report.passed else "BLOCKED")
            except Exception:
                self.session.rollback()
                raise
        return {"asset_id": asset_id, "version": expected_version, "content_hash": expected_hash, "applied": apply, "content_consistent": consistent, "status": row.status, "quality": report.model_dump(mode="json")}
