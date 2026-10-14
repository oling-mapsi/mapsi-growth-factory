from __future__ import annotations

import logging
from threading import Event, Thread

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

        stop = Event()
        def heartbeat():
            while not stop.wait(30):
                try:
                    self.jobs.heartbeat(job.id)
                except Exception:
                    logger.warning("Generation heartbeat unavailable for job %s", job.id)
        heartbeat_thread = Thread(target=heartbeat, daemon=True)
        heartbeat_thread.start()

        try:
            parameters = job.parameters or {}
            if parameters.get('operation') == 'repair':
                self.service.run_asset_repair(job.campaign_run_id, parameters['asset_id'], parameters['expected_version'], stage_callback=mark_stage)
            elif parameters.get('operation') == 'image':
                from app.application.services.simple_campaign_service import GenerateSimpleImageCommand
                mark_stage('ILLUSTRATION')
                self.service.generate_asset_image(job.campaign_run_id, parameters['asset_id'], GenerateSimpleImageCommand(visual_brief=parameters['visual_brief'], expected_version=parameters['expected_version']), job_id=job.id)
            else:
                self.service.run_generation(job.campaign_run_id, stage_callback=mark_stage)
        except Exception as exc:
            self.jobs.mark_failed(job.id, exc)
            logger.exception("Simple generation job failed: %s", job.id)
            return True
        finally:
            stop.set()
            heartbeat_thread.join(timeout=2)

        self.jobs.mark_succeeded(job.id)
        return True
