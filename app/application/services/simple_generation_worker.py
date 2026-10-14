from __future__ import annotations

import logging

from app.application.services.simple_campaign_service import SimpleCampaignService
from app.infrastructure.repositories.simple_generation_jobs import SimpleGenerationJobRepository

logger = logging.getLogger(__name__)


class SimpleGenerationWorker:
    def __init__(self, jobs: SimpleGenerationJobRepository, service: SimpleCampaignService) -> None:
        self.jobs = jobs
        self.service = service

    def process_one(self) -> bool:
        job = self.jobs.claim_next()
        if job is None:
            return False

        def mark_stage(stage: str) -> None:
            self.jobs.mark_stage(job.id, stage)

        try:
            self.service.run_generation(job.campaign_run_id, stage_callback=mark_stage)
        except Exception as exc:
            self.jobs.mark_failed(job.id, exc)
            logger.exception("Simple generation job failed: %s", job.id)
            return True

        self.jobs.mark_succeeded(job.id)
        return True
