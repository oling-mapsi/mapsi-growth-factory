from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.domain.entities import MauticCampaignPublication
from app.infrastructure.db.models import MauticCampaignPublicationModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MauticPublicationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, campaign_id: str, content_version: int, segment_version: int) -> MauticCampaignPublication | None:
        model = (
            self.session.query(MauticCampaignPublicationModel)
            .filter(
                MauticCampaignPublicationModel.campaign_run_id == campaign_id,
                MauticCampaignPublicationModel.content_version == content_version,
                MauticCampaignPublicationModel.segment_version == segment_version,
            )
            .one_or_none()
        )
        if model is None:
            return None
        return self._to_entity(model)

    def save(self, publication: MauticCampaignPublication) -> MauticCampaignPublication:
        model = self.session.get(MauticCampaignPublicationModel, publication.id)
        if model is None:
            model = MauticCampaignPublicationModel(id=publication.id)
            self.session.add(model)
        model.campaign_run_id = publication.campaign_run_id
        model.content_version = publication.content_version
        model.segment_version = publication.segment_version
        model.status = publication.status
        model.mautic_email_id = publication.mautic_email_id
        model.mautic_segment_id = publication.mautic_segment_id
        model.mautic_campaign_id = publication.mautic_campaign_id
        model.scheduled_at = publication.scheduled_at
        model.idempotency_key = publication.idempotency_key
        model.target_instance_ids = publication.target_instance_ids
        model.target_client_ids = publication.target_client_ids
        model.targeted_contacts = publication.targeted_contacts
        model.last_error = publication.last_error
        model.created_at = publication.created_at
        model.updated_at = utcnow()
        self.session.commit()
        self.session.refresh(model)
        return self._to_entity(model)

    def _to_entity(self, model: MauticCampaignPublicationModel) -> MauticCampaignPublication:
        return MauticCampaignPublication(
            id=model.id,
            campaign_run_id=model.campaign_run_id,
            content_version=model.content_version,
            segment_version=model.segment_version,
            status=model.status,
            mautic_email_id=model.mautic_email_id,
            mautic_segment_id=model.mautic_segment_id,
            mautic_campaign_id=model.mautic_campaign_id,
            scheduled_at=model.scheduled_at,
            idempotency_key=model.idempotency_key,
            target_instance_ids=list(model.target_instance_ids or []),
            target_client_ids=list(model.target_client_ids or []),
            targeted_contacts=model.targeted_contacts,
            last_error=model.last_error,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
