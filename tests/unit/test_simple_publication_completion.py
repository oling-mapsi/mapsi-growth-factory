import pytest

from app.domain.entities import CampaignRun, ContentAsset, Publication
from app.domain.enums import CampaignStatus, AssetStatus
from app.domain.errors import CampaignPublicationForbiddenError


def make_campaign(workflow='SIMPLE'):
    campaign = CampaignRun(workflow_kind=workflow,status=CampaignStatus.PARTIALLY_APPROVED)
    approved = ContentAsset(campaign_run_id=campaign.id,channel='oling',title='Approved French',content_html='<p>Approved</p>',content_text='Approved',status=AssetStatus.APPROVED,results={'editorial_quality':{'passed':True,'issues':[]}})
    approved.ensure_content_hash()
    approved.approved_content_hash=approved.content_hash
    pending = ContentAsset(campaign_run_id=campaign.id,channel='oling',locale='en-US',title='Pending English',status=AssetStatus.READY_FOR_REVIEW)
    campaign.content_assets=[approved,pending]
    return campaign,approved,pending


def test_simple_completion_publishes_only_approved_article_and_is_idempotent():
    campaign,approved,pending=make_campaign()
    publication=Publication(campaign_run_id=campaign.id,content_asset_id=approved.id,channel='oling',external_reference='confirmed-remote',external_url='https://recette.invalid/approved')
    campaign.publish(publication)
    campaign.publish(publication)
    assert approved.status is AssetStatus.PUBLISHED
    assert pending.status is AssetStatus.READY_FOR_REVIEW
    assert len(campaign.publications)==1
    assert campaign.status is CampaignStatus.PARTIALLY_PUBLISHED


@pytest.mark.parametrize('fault',['hash','quality','unapproved','channel'])
def test_simple_completion_keeps_individual_safety_checks(fault):
    campaign,asset,_=make_campaign()
    publication=Publication(content_asset_id=asset.id,channel='oling')
    if fault=='hash': asset.approved_content_hash='old-hash'
    if fault=='quality': asset.results['editorial_quality']['passed']=False
    if fault=='unapproved': asset.status=AssetStatus.READY_FOR_REVIEW
    if fault=='channel': publication.channel='mapsi_site'
    with pytest.raises(CampaignPublicationForbiddenError): campaign.publish(publication)
    assert not campaign.publications


def test_legacy_completion_still_requires_global_campaign_approval():
    campaign,asset,_=make_campaign('LEGACY')
    with pytest.raises(CampaignPublicationForbiddenError):
        campaign.publish(Publication(content_asset_id=asset.id,channel='oling'))


def test_publishing_preserves_edits_to_other_locale(session):
    from app.application.services.growth_campaign_updates import save_publishing_asset
    from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
    repository=SqlAlchemyCampaignRepository(session)
    campaign,approved,pending=make_campaign()
    repository.add(campaign)
    stale=repository.get(campaign.id)
    edited=repository.get(campaign.id)
    english=next(a for a in edited.content_assets if a.id==pending.id)
    english.update_draft(title='English manual edit',content_html='<p>Preserved manual edit</p>')
    repository.save(edited)
    french=next(a for a in stale.content_assets if a.id==approved.id)
    french.mark_published(external_url='https://recette.invalid/fr')
    saved=save_publishing_asset(repository,stale,french)
    assert next(a for a in saved.content_assets if a.id==pending.id).title=='English manual edit'
    assert next(a for a in saved.content_assets if a.id==pending.id).content_version==2
