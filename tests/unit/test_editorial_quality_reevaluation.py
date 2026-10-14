import copy

import pytest
from sqlalchemy import select

from app.application.services.editorial_quality_reevaluation import EditorialQualityReevaluationService
from app.application.services.editorial_engine_v1 import OpenAIEditorialGenerator
from app.application.services.growth_article_media import attach_illustration
from app.domain.entities import CampaignRun, ContentAsset
from app.domain.enums import AssetStatus, CampaignStatus
from app.domain.errors import InvalidStateTransitionError, OptimisticLockError
from app.infrastructure.db.models import AuditLogModel, ContentAssetModel, SimpleGenerationJobModel
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
from tests.unit.test_editorial_engine_v1 import _quality_pair


def _fixture(session):
    article, context = _quality_pair(session, "Aucun cas client de fusion.")
    article.warnings = ["Aucun cas client de fusion n'est documente."]
    campaign = CampaignRun(name="Synthetic editorial reevaluation",workflow_kind="SIMPLE",campaign_type="OLING",selected_channels=["oling_site"],status=CampaignStatus.FAILED)
    asset = ContentAsset(campaign_run_id=campaign.id,channel="oling",asset_type="oling_news_article",title=article.title,excerpt=article.excerpt,content_html=article.body_html,content_text=article.body_text,content_version=4,status=AssetStatus.QUALITY_FAILED,results={"editorial_article":article.model_dump(mode="json"),"builder_context":context.model_dump(mode="json"),"editorial_quality":{"passed":False,"issues":[{"code":"unauthorized_client_reference","severity":"error","message":"old false positive"}]},"image":{"storage_path":"storage/growth-images/retained.png","alt_text":"ERP"},"seo_geo":{"metadata":{"canonical":"https://oling.fr/ressources/erp"}}})
    asset.content_html=attach_illustration(asset.content_html,asset_id=asset.id,alt="ERP")
    asset.ensure_content_hash()
    other=ContentAsset(campaign_run_id=campaign.id,channel="oling",locale="en-US",title="Unrelated English",content_html="<p>Unrelated</p>",content_text="Unrelated",content_version=7,status=AssetStatus.READY_FOR_REVIEW,results={"image":{"id":"keep"},"editorial_quality":{"passed":False}})
    campaign.content_assets=[asset,other]
    SqlAlchemyCampaignRepository(session).add(campaign)
    return asset,other


def _reevaluate(session,asset,**kwargs):
    return EditorialQualityReevaluationService(session).reevaluate(asset.id,expected_version=asset.content_version,expected_hash=asset.content_hash,actor="synthetic-admin",**kwargs)


def test_quality_reevaluation_is_atomic_preserves_version_hash_media_seo_and_other_locale(session,monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError("Reevaluation must not call an AI provider")
    monkeypatch.setattr(OpenAIEditorialGenerator,"rewrite_existing",forbidden)
    asset,other=_fixture(session)
    row=session.get(ContentAssetModel,asset.id);before=(row.content_version,row.content_hash,row.content_html,row.content_text,copy.deepcopy(row.results["image"]),copy.deepcopy(row.results["seo_geo"]))
    other_before={k:copy.deepcopy(v) for k,v in vars(session.get(ContentAssetModel,other.id)).items() if not k.startswith('_') and k!='campaign'}
    result=_reevaluate(session,asset,apply=True)
    assert result['quality']['passed'] and result['status']=='READY_FOR_REVIEW'
    session.expire_all();row=session.get(ContentAssetModel,asset.id)
    assert (row.content_version,row.content_hash,row.content_html,row.content_text,row.results['image'],row.results['seo_geo'])==before
    assert not row.approved_at and not row.approved_content_hash
    assert {k:v for k,v in vars(session.get(ContentAssetModel,other.id)).items() if not k.startswith('_') and k!='campaign'}==other_before
    event=session.scalar(select(AuditLogModel).where(AuditLogModel.event_type=='editorial.asset_quality_reevaluated'))
    assert event.content_asset_id==asset.id and event.payload['provider_calls']==0


def test_quality_reevaluation_dry_run_does_not_persist(session):
    asset,_=_fixture(session)
    result=_reevaluate(session,asset)
    assert result['quality']['passed'] and not result['applied']
    session.expire_all()
    assert session.get(ContentAssetModel,asset.id).results['editorial_quality']['passed'] is False
    assert not session.scalar(select(AuditLogModel.id))


@pytest.mark.parametrize('change',['version','hash'])
def test_quality_reevaluation_refuses_a_concurrent_version_or_hash_change(session,change):
    asset,_=_fixture(session);row=session.get(ContentAssetModel,asset.id)
    if change=='version':row.content_version+=1
    else:row.content_hash='changed'
    session.commit()
    with pytest.raises(OptimisticLockError):_reevaluate(session,asset,apply=True)
    assert row.results['editorial_quality']['passed'] is False


def test_quality_reevaluation_keeps_real_source_errors_and_content_mismatch(session):
    asset,_=_fixture(session);row=session.get(ContentAssetModel,asset.id);results=copy.deepcopy(row.results)
    results['editorial_article']['claims'][0]['source_ids']=['unknown-source'];row.results=results
    row.content_html += '<p>Unsupported human edit.</p>'
    session.commit()
    result=_reevaluate(session,asset,apply=True)
    assert not result['quality']['passed']
    assert {'claim_unknown_source','editorial_content_mismatch'}<={x['code'] for x in result['quality']['issues']}
    assert row.content_version==4 and row.status=='QUALITY_FAILED'


def test_quality_reevaluation_refuses_approved_articles(session):
    asset,_=_fixture(session);row=session.get(ContentAssetModel,asset.id);row.status='APPROVED';session.commit()
    with pytest.raises(InvalidStateTransitionError):_reevaluate(session,asset,apply=True)


def test_audit_failure_rolls_back_quality_and_status_atomically(session,monkeypatch):
    from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository
    asset,_=_fixture(session)
    def fail(*args,**kwargs):raise RuntimeError("Synthetic audit failure")
    monkeypatch.setattr(SqlAlchemyAuditLogRepository,'append',fail)
    with pytest.raises(RuntimeError,match='audit failure'):_reevaluate(session,asset,apply=True)
    session.commit();session.expire_all()
    assert session.get(ContentAssetModel,asset.id).status=='QUALITY_FAILED'
    assert session.get(ContentAssetModel,asset.id).results['editorial_quality']['passed'] is False
