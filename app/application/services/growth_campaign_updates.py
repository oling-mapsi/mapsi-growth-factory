from app.domain.errors import OptimisticLockError


def save_publishing_asset(repository, campaign, asset):
    if campaign.workflow_kind.upper() != 'SIMPLE':
        return repository.save(campaign)
    from app.infrastructure.db.models import CampaignRunModel
    session = repository.session
    session.commit()
    session.expire_all()
    session.query(CampaignRunModel).filter(CampaignRunModel.id == campaign.id).with_for_update().first()
    latest = repository.get(campaign.id)
    current = next(item for item in latest.content_assets if item.id == asset.id)
    if current.content_version != asset.content_version:
        session.rollback()
        raise OptimisticLockError('Article changed during publication; existing drafts were preserved.')
    latest.content_assets = [asset if item.id == asset.id else item for item in latest.content_assets]
    known = {(item.content_asset_id, item.channel) for item in latest.publications}
    latest.publications.extend(item for item in campaign.publications if (item.content_asset_id,item.channel) not in known)
    latest._sync_status_from_assets()
    saved = repository.save(latest)
    for field in ('content_assets','publications','approval_decisions','source_evidences','editorial_briefs','status'):
        setattr(campaign,field,getattr(saved,field))
    campaign.content_assets = [asset if item.id == asset.id else item for item in campaign.content_assets]
    return saved
