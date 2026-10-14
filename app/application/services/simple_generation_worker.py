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
                campaign = self.service.run_generation(job.campaign_run_id, stage_callback=mark_stage)
                if parameters.get('complete_articles'):
                    from app.application.services.simple_campaign_service import GenerateSimpleImageCommand
                    ids = parameters.get('completion_asset_ids')
                    if ids is None:
                        ids = [asset.id for asset in campaign.content_assets if asset.channel in {'oling', 'mapsi_site'}]
                        job.parameters = {**(job.parameters or {}), 'completion_asset_ids': ids}
                        self.jobs.session.commit()
                    for asset_id in ids:
                        campaign = self.service.get_campaign(job.campaign_run_id)
                        asset = next(item for item in campaign.content_assets if item.id == asset_id)
                        if asset.status.value in {'APPROVED', 'SCHEDULED', 'PUBLISHING', 'PUBLISHED', 'CANCELLED'}:
                            continue
                        prefix = f'{self.service.external_channel(asset.channel)}:{asset.locale}:'
                        if not (asset.results or {}).get('image'):
                            mark_stage(prefix + 'ILLUSTRATION')
                            campaign = self.service.generate_asset_image(campaign.id, asset.id,
                                GenerateSimpleImageCommand(expected_version=asset.content_version), job_id=job.id)
                            asset = next(item for item in campaign.content_assets if item.id == asset_id)
                        if not (asset.results or {}).get('seo_geo'):
                            mark_stage(prefix + 'QUALITY_CHECK')
                            self.service.prepare_asset_seo_geo(campaign.id, asset.id, asset.content_version)
        except Exception as exc:
            self.jobs.mark_failed(job.id, exc)
            logger.warning("Simple generation job failed: %s (%s)", job.id, type(exc).__name__)
            return True
        finally:
            stop.set()
            heartbeat_thread.join(timeout=2)

        self.jobs.mark_succeeded(job.id)
        return True
