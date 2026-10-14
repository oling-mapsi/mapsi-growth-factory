from app.infrastructure.repositories.simple_generation_jobs import SimpleGenerationJobRepository
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
from app.domain.entities import CampaignRun
from app.domain.entities import ContentAsset
from app.domain.enums import AssetStatus
from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository
from app.infrastructure.tasks import InMemoryTaskQueue
from app.application.services.simple_campaign_service import SimpleCampaignService, GenerateSimpleImageCommand
from app.application.services.growth_image_generation import GrowthImageResult
import pytest


def test_targeted_repair_job_is_durable_and_duplicate_click_reuses_it(session):
    campaign = SqlAlchemyCampaignRepository(session).add(CampaignRun(name='Synthetic ERP', campaign_type='OLING', selected_channels=['oling_site']))
    repository = SimpleGenerationJobRepository(session)
    parameters = {'operation':'repair','asset_id':'synthetic-asset','expected_version':3}
    first = repository.ensure_pending(campaign.id,parameters=parameters)
    duplicate = repository.ensure_pending(campaign.id,parameters=parameters)
    assert first.id == duplicate.id and duplicate.parameters == parameters
    claimed = repository.claim_next()
    assert claimed.parameters['asset_id'] == 'synthetic-asset'
    repository.mark_stage(claimed.id,'oling_site:es-ES:REWRITING')
    repository.mark_failed(claimed.id,RuntimeError('synthetic provider failure'))
    assert claimed.stage == 'oling_site:es-ES:FAILED'
    resumed = repository.ensure_pending(campaign.id,parameters=parameters)
    assert resumed.id == first.id and resumed.status == 'PENDING'


def test_image_result_survives_failed_attachment_without_second_provider_call(session, tmp_path, monkeypatch):
    repository = SqlAlchemyCampaignRepository(session)
    campaign = CampaignRun(name='Synthetic illustration',workflow_kind='SIMPLE',campaign_type='OLING',selected_channels=['oling_site'])
    asset = ContentAsset(campaign_run_id=campaign.id,asset_type='oling_news_article',channel='oling',title='ERP',content_html='<p>ERP</p>',content_text='ERP',status=AssetStatus.READY_FOR_REVIEW)
    campaign.content_assets = [asset]
    repository.add(campaign)
    jobs = SimpleGenerationJobRepository(session)
    calls = []
    class Provider:
        def generate(self, **kwargs):
            calls.append(kwargs)
            return GrowthImageResult(model='test-image',prompt='synthetic',alt_text='ERP',storage_path='storage/growth-images/synthetic.png',data_url='',output_format='png',duration_ms=1,tokens={})
    service = SimpleCampaignService(repository,None,SqlAlchemyAuditLogRepository(session),InMemoryTaskQueue(),project_root=tmp_path,image_service=Provider(),generation_jobs=jobs)
    command = GenerateSimpleImageCommand(expected_version=asset.content_version)
    service.enqueue_asset_image(campaign.id,asset.id,command)
    job = jobs.claim_next()
    original_save = repository.save
    def fail_save(*args):
        raise RuntimeError('Synthetic attachment failure')
    monkeypatch.setattr(repository,'save',fail_save)
    with pytest.raises(RuntimeError,match='attachment failure'):
        service.generate_asset_image(campaign.id,asset.id,command,job_id=job.id)
    assert job.parameters['generated_image']['storage_path'].endswith('synthetic.png')
    assert 'data_url' not in job.parameters['generated_image']
    jobs.mark_failed(job.id,RuntimeError('Synthetic attachment failure'))
    service.enqueue_asset_image(campaign.id,asset.id,command)
    assert jobs.latest_for_campaign(campaign.id).id==job.id
    monkeypatch.setattr(repository,'save',original_save)
    saved = service.generate_asset_image(campaign.id,asset.id,command,job_id=job.id)
    assert len(calls)==1
    assert '<figure>' in saved.content_assets[0].content_html
    assert saved.content_assets[0].content_version==command.expected_version+1
