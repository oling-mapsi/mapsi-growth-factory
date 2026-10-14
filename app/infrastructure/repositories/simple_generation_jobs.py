from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4
import re

from sqlalchemy.orm import Session

from app.infrastructure.db.models import SimpleGenerationJobModel


ACTIVE_STATUSES = {"PENDING", "RUNNING"}


class SimpleGenerationJobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def latest_for_campaign(self, campaign_id: str) -> SimpleGenerationJobModel | None:
        return (
            self.session.query(SimpleGenerationJobModel)
            .filter(SimpleGenerationJobModel.campaign_run_id == campaign_id)
            .order_by(SimpleGenerationJobModel.status.in_(ACTIVE_STATUSES).desc(), SimpleGenerationJobModel.updated_at.desc(), SimpleGenerationJobModel.created_at.desc(), SimpleGenerationJobModel.id.desc())
            .first()
        )

    def ensure_pending(self, campaign_id: str, *, stale_after_seconds: int = 600, parameters: dict | None = None) -> SimpleGenerationJobModel:
        from app.infrastructure.db.models import CampaignRunModel
        self.session.query(CampaignRunModel).filter(CampaignRunModel.id == campaign_id).with_for_update().first()
        latest = self.latest_for_campaign(campaign_id)
        now = datetime.now(UTC)
        if latest and latest.status == "RUNNING" and self._is_stale(latest, now, stale_after_seconds):
            latest.status = "PENDING"
            latest.stage = "WAITING"
            latest.error_type = "StaleGenerationJob"
            latest.error_message = "Previous generation worker run became stale and was requeued."
            latest.updated_at = now
            self.session.commit()
            self.session.refresh(latest)
            return latest
        if latest and latest.status in ACTIVE_STATUSES:
            return latest
        identity = {key: value for key, value in (latest.parameters or {}).items() if key != 'generated_image'} if latest else {}
        if latest and latest.status == "FAILED" and (identity or None) == (parameters or None):
            latest.status = "PENDING"
            latest.stage = "WAITING"
            latest.error_type = ""
            latest.error_message = ""
            latest.updated_at = now
            self.session.commit()
            self.session.refresh(latest)
            return latest
        job = SimpleGenerationJobModel(
            id=str(uuid4()),
            campaign_run_id=campaign_id,
            parameters=parameters,
            status="PENDING",
            stage="WAITING",
            error_type="",
            error_message="",
            attempts=0,
            created_at=now,
            updated_at=now,
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return job

    def _is_stale(self, job: SimpleGenerationJobModel, now: datetime, stale_after_seconds: int) -> bool:
        updated_at = job.updated_at
        if updated_at is None:
            return True
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)
        return updated_at < now - timedelta(seconds=stale_after_seconds)

    def heartbeat(self, job_id: str) -> None:
        with Session(bind=self.session.get_bind()) as session:
            session.query(SimpleGenerationJobModel).filter(SimpleGenerationJobModel.id == job_id, SimpleGenerationJobModel.status == 'RUNNING').update({'updated_at': datetime.now(UTC)})
            session.commit()

    def claim_next(self) -> SimpleGenerationJobModel | None:
        job = (
            self.session.query(SimpleGenerationJobModel)
            .filter(SimpleGenerationJobModel.status == "PENDING")
            .order_by(SimpleGenerationJobModel.created_at.asc())
            .with_for_update(skip_locked=True)
            .first()
        )
        if job is None:
            return None
        now = datetime.now(UTC)
        job.status = "RUNNING"
        job.stage = "DRAFTING"
        job.attempts += 1
        job.started_at = now
        job.updated_at = now
        self.session.commit()
        self.session.refresh(job)
        return job

    def mark_stage(self, job_id: str, stage: str) -> None:
        job = self.session.get(SimpleGenerationJobModel, job_id)
        if job is None:
            return
        job.stage = stage
        job.updated_at = datetime.now(UTC)
        self.session.commit()

    def mark_succeeded(self, job_id: str) -> None:
        job = self.session.get(SimpleGenerationJobModel, job_id)
        if job is None:
            return
        now = datetime.now(UTC)
        job.status = "SUCCEEDED"
        job.stage = "READY_FOR_REVIEW"
        job.updated_at = now
        job.completed_at = now
        self.session.commit()

    def mark_failed(self, job_id: str, exc: Exception) -> None:
        job = self.session.get(SimpleGenerationJobModel, job_id)
        if job is None:
            return
        now = datetime.now(UTC)
        job.status = "FAILED"
        parts = job.stage.split(':')
        job.stage = ':'.join(parts[:-1] + ['FAILED']) if len(parts) == 3 else 'FAILED'
        job.error_type = type(exc).__name__
        message = str(exc)
        if re.search(r'insufficient_quota|credit_balance_exhausted', message, re.I):
            message = 'Crédit API OpenAI épuisé — génération suspendue'
        else:
            message = re.sub(r'sk-[A-Za-z0-9_.-]+', '[cle API masquee]', message)
            message = re.sub(r'Bearer\s+[A-Za-z0-9_.-]+', 'Bearer [masque]', message, flags=re.I)
        job.error_message = message[:4000]
        job.updated_at = now
        job.completed_at = now
        self.session.commit()
