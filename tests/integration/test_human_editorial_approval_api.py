from uuid import uuid4

from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
from tests.support_auth import auth_headers
from tests.unit.test_human_editorial_acceptance import fixture_campaign


def headers(role):
    return auth_headers(roles=[role], jti=str(uuid4()))


def test_api_human_confirmation_is_explicit_permitted_versioned_and_independent(client,session):
    campaign,asset,other=fixture_campaign()
    SqlAlchemyCampaignRepository(session).add(campaign)
    path=f'/studio-simple/campaigns/{campaign.id}/assets/{asset.id}'
    assert client.post(path+'/review',headers=headers('ROLE_GROWTH_REVIEW'),json={'expected_version':1}).status_code==200
    assert client.post(path+'/approve',headers=headers('ROLE_GROWTH_VIEWER'),json={'expected_version':1,'confirm_editorial_review':True}).status_code==403
    assert client.post(path+'/approve',headers=headers('ROLE_GROWTH_APPROVE'),json={'expected_version':2,'confirm_editorial_review':True}).status_code==409
    assert client.post(path+'/approve',headers=headers('ROLE_GROWTH_APPROVE'),json={'expected_version':1}).status_code==409
    response=client.post(path+'/approve',headers=headers('ROLE_GROWTH_APPROVE'),json={'expected_version':1,'confirm_editorial_review':True})
    assert response.status_code==200,response.text
    current=next(item for item in response.json()['content_assets'] if item['id']==asset.id)
    assert current['status']=='APPROVED' and current['editorial_quality']['passed'] is False
    assert current['quality_blocking'] is False
    pending=next(item for item in response.json()['content_assets'] if item['id']==other.id)
    assert pending['status']!='APPROVED'
    session.expire_all()
    stored=SqlAlchemyCampaignRepository(session).get(campaign.id)
    accepted=next(item for item in stored.content_assets if item.id==asset.id)
    assert accepted.results['human_editorial_acceptance']['actor']
    assert accepted.results['human_editorial_acceptance']['content_hash']==accepted.approved_content_hash
