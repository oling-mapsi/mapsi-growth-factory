from copy import deepcopy
from pathlib import Path

import pytest

from app.domain.editorial_publication import editorial_readiness
from app.domain.entities import CampaignRun, ContentAsset, Publication, SourceEvidence
from app.domain.enums import AssetStatus
from app.domain.errors import ApprovalPrerequisiteError, CampaignPublicationForbiddenError, InvalidStateTransitionError


def fixture_campaign(workflow='SIMPLE'):
    campaign=CampaignRun(workflow_kind=workflow, source_evidences=[SourceEvidence(reference='knowledge:amoa')])
    asset=ContentAsset(campaign_run_id=campaign.id,channel='oling',locale='en-US',title='ERP framing',
        content_html='<p>Clarify business requirements before system configuration.</p>',
        content_text='Clarify business requirements before system configuration.',status=AssetStatus.QUALITY_FAILED,
        results={'editorial_quality':{'passed':False,'issues':[{'code':'claim_without_source','severity':'error','message':'Missing source ids'}]},
                 'editorial_article':{'claims':[{'text':'Clarify business requirements before system configuration.',
                     'source_ids':[],'verified':False,'claim_type':'generic_guidance'}]}})
    asset.ensure_content_hash()
    other=ContentAsset(campaign_run_id=campaign.id,channel='mapsi_site',locale='fr-FR',title='Pending MAPSI',status=AssetStatus.QUALITY_FAILED)
    campaign.content_assets=[asset,other]
    return campaign,asset,other


def test_explicit_human_acceptance_keeps_report_and_claims_unchanged_and_publishes_only_one_asset():
    campaign,asset,other=fixture_campaign()
    report=deepcopy(asset.results['editorial_quality']);claims=deepcopy(asset.results['editorial_article'])
    with pytest.raises(ApprovalPrerequisiteError):campaign.approve_asset(asset.id,'','admin')
    assert editorial_readiness(asset)['human_review_pending']
    campaign.approve_asset(asset.id,'Human confirmation','admin',confirm_editorial_review=True)
    receipt=asset.results['human_editorial_acceptance']
    assert receipt['actor']=='admin' and receipt['confirmed_at'] and receipt['version']==1
    assert receipt['content_hash']==asset.approved_content_hash==asset.content_hash
    assert receipt['accepted_warnings']==report['issues']
    assert asset.results['editorial_quality']==report and asset.results['editorial_article']==claims
    assert not editorial_readiness(asset)['quality_blocking']
    campaign.publish(Publication(content_asset_id=asset.id,channel='oling',external_reference='isolated',external_url='http://localhost/en/erp'))
    assert asset.status is AssetStatus.PUBLISHED and other.status is AssetStatus.QUALITY_FAILED


@pytest.mark.parametrize('fault',['hash','version','quality','claims'])
def test_acceptance_is_invalidated_by_any_content_or_quality_change(fault):
    campaign,asset,_=fixture_campaign()
    campaign.approve_asset(asset.id,'','admin',confirm_editorial_review=True)
    if fault=='hash':asset.update_draft(title='Changed')
    if fault=='version':asset.content_version+=1
    if fault=='quality':asset.results['editorial_quality']['issues'][0]['message']='Updated quality report'
    if fault=='claims':asset.results['editorial_article']['claims'][0]['text']='Changed guidance'
    assert editorial_readiness(asset)['quality_blocking']
    with pytest.raises(CampaignPublicationForbiddenError):campaign.publish(Publication(content_asset_id=asset.id,channel='oling'))


@pytest.mark.parametrize('code',['unauthorized_client_reference','unsafe_html','secret_or_email_detected','unverified_claim','claim_unknown_source','unknown_failure'])
def test_critical_issues_cannot_be_accepted_even_by_human(code):
    campaign,asset,_=fixture_campaign()
    asset.results['editorial_quality']['issues'].append({'code':code,'severity':'error'})
    with pytest.raises(ApprovalPrerequisiteError):campaign.approve_asset(asset.id,'','admin',confirm_editorial_review=True)


@pytest.mark.parametrize('fault',['product_fact','practice_fact','sensitive','no_claims','mismatched_count'])
def test_missing_source_acceptance_is_limited_to_noncritical_correlated_guidance(fault):
    campaign,asset,_=fixture_campaign()
    claim=asset.results['editorial_article']['claims'][0]
    if fault in {'product_fact','practice_fact'}:claim['claim_type']=fault
    if fault=='sensitive':claim['text']='This method guarantees a 50% revenue increase.'
    if fault=='no_claims':asset.results['editorial_article']['claims']=[]
    if fault=='mismatched_count':asset.results['editorial_quality']['issues']*=2
    with pytest.raises(ApprovalPrerequisiteError):campaign.approve_asset(asset.id,'','admin',confirm_editorial_review=True)


def test_legacy_workflow_remains_strict():
    campaign,asset,_=fixture_campaign('LEGACY')
    with pytest.raises(ApprovalPrerequisiteError):campaign.approve_asset(asset.id,'','admin',confirm_editorial_review=True)


def test_simple_review_and_approval_bind_human_acceptance_without_rewriting(session):
    from app.application.services.simple_campaign_service import SimpleCampaignService, ReviewSimpleAssetCommand, ApproveSimpleAssetCommand
    from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
    from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository
    from app.infrastructure.tasks import InMemoryTaskQueue
    campaign,asset,_=fixture_campaign()
    repository=SqlAlchemyCampaignRepository(session);repository.add(campaign)
    service=SimpleCampaignService(repository,None,SqlAlchemyAuditLogRepository(session),InMemoryTaskQueue(),project_root=Path('.'))
    service.review_asset(campaign.id,asset.id,ReviewSimpleAssetCommand(expected_version=1,actor='admin'))
    with pytest.raises(InvalidStateTransitionError):service.approve_asset(campaign.id,asset.id,ApproveSimpleAssetCommand(expected_version=1,actor='admin'))
    result=service.approve_asset(campaign.id,asset.id,ApproveSimpleAssetCommand(expected_version=1,actor='admin',confirm_editorial_review=True))
    current=next(item for item in result.content_assets if item.id==asset.id)
    assert current.status is AssetStatus.APPROVED
    assert current.results['editorial_quality']['passed'] is False
    assert current.results['human_editorial_acceptance']['actor']=='admin'


def test_reusing_french_image_changes_only_target_and_keeps_localized_alt(session,tmp_path,monkeypatch):
    from app.application.services.simple_campaign_service import SimpleCampaignService
    from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
    from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository
    from app.infrastructure.tasks import InMemoryTaskQueue
    campaign,asset,_=fixture_campaign()
    french=ContentAsset(campaign_run_id=campaign.id,channel='oling',locale='fr-FR',title='French',status=AssetStatus.PUBLISHED,
        content_html='<p>Published French</p>',external_publication_url='http://localhost/fr/original',
        results={'image':{'storage_path':'storage/french.png','model':'existing'}})
    french.ensure_content_hash();campaign.content_assets.append(french)
    repository=SqlAlchemyCampaignRepository(session);repository.add(campaign)
    service=SimpleCampaignService(repository,None,SqlAlchemyAuditLogRepository(session),InMemoryTaskQueue(),project_root=tmp_path)
    image=tmp_path/'french.png';image.write_bytes(b'fixture')
    monkeypatch.setattr(service,'get_asset_image_reference',lambda _: (image,'image/png',''))
    before=deepcopy(french)
    result=service.reuse_asset_image(campaign.id,asset.id,french.id,1,'admin')
    target=next(item for item in result.content_assets if item.id==asset.id)
    original=next(item for item in result.content_assets if item.id==french.id)
    assert target.content_version==2 and target.results['image']['alt_text'].startswith('Editorial illustration: ')
    assert target.results['image']['storage_path']=='storage/french.png' and '<img' in target.content_html
    assert original.content_hash==before.content_hash and original.content_version==before.content_version
    assert original.content_html==before.content_html and original.external_publication_url==before.external_publication_url
