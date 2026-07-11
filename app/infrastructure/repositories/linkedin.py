from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.domain.entities import LinkedInOAuthToken, LinkedInPublication
from app.infrastructure.db.models import LinkedInOAuthTokenModel, LinkedInPublicationModel


class LinkedInOAuthTokenRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, provider: str = "linkedin", subject: str = "organization") -> LinkedInOAuthToken | None:
        model = (
            self.session.query(LinkedInOAuthTokenModel)
            .filter(
                LinkedInOAuthTokenModel.provider == provider,
                LinkedInOAuthTokenModel.subject == subject,
            )
            .one_or_none()
        )
        return self._to_entity(model) if model else None

    def save(self, token: LinkedInOAuthToken) -> LinkedInOAuthToken:
        model = self.session.get(LinkedInOAuthTokenModel, token.id)
        if model is None:
            model = LinkedInOAuthTokenModel(id=token.id)
            self.session.add(model)
        model.provider = token.provider
        model.subject = token.subject
        model.access_token = token.access_token
        model.refresh_token = token.refresh_token
        model.scope = token.scope
        model.expires_at = token.expires_at
        model.refresh_expires_at = token.refresh_expires_at
        model.created_at = token.created_at
        model.updated_at = token.updated_at
        self.session.commit()
        return self._to_entity(model)

    def _to_entity(self, model: LinkedInOAuthTokenModel) -> LinkedInOAuthToken:
        return LinkedInOAuthToken(
            id=model.id,
            provider=model.provider,
            subject=model.subject,
            access_token=model.access_token,
            refresh_token=model.refresh_token,
            scope=model.scope,
            expires_at=model.expires_at,
            refresh_expires_at=model.refresh_expires_at,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )


class LinkedInPublicationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_asset_hash(self, content_asset_id: str, content_hash: str) -> LinkedInPublication | None:
        model = (
            self.session.query(LinkedInPublicationModel)
            .filter(
                LinkedInPublicationModel.content_asset_id == content_asset_id,
                LinkedInPublicationModel.content_hash == content_hash,
            )
            .one_or_none()
        )
        return self._to_entity(model) if model else None

    def list_by_campaign(self, campaign_id: str) -> list[LinkedInPublication]:
        models = (
            self.session.query(LinkedInPublicationModel)
            .filter(LinkedInPublicationModel.campaign_run_id == campaign_id)
            .order_by(LinkedInPublicationModel.created_at.asc())
            .all()
        )
        return [self._to_entity(model) for model in models]

    def save(self, publication: LinkedInPublication) -> LinkedInPublication:
        model = self.session.get(LinkedInPublicationModel, publication.id)
        if model is None:
            model = LinkedInPublicationModel(id=publication.id)
            self.session.add(model)
        model.campaign_run_id = publication.campaign_run_id
        model.content_asset_id = publication.content_asset_id
        model.content_hash = publication.content_hash
        model.asset_type = publication.asset_type
        model.organization_urn = publication.organization_urn
        model.linkedin_post_urn = publication.linkedin_post_urn
        model.status = publication.status
        model.mode = publication.mode
        model.idempotency_key = publication.idempotency_key
        model.last_error = publication.last_error
        model.metrics = publication.metrics
        model.published_at = publication.published_at
        model.metrics_collected_at = publication.metrics_collected_at
        model.created_at = publication.created_at
        model.updated_at = publication.updated_at
        self.session.commit()
        return self._to_entity(model)

    def _to_entity(self, model: LinkedInPublicationModel) -> LinkedInPublication:
        return LinkedInPublication(
            id=model.id,
            campaign_run_id=model.campaign_run_id,
            content_asset_id=model.content_asset_id,
            content_hash=model.content_hash,
            asset_type=model.asset_type,
            organization_urn=model.organization_urn,
            linkedin_post_urn=model.linkedin_post_urn,
            status=model.status,
            mode=model.mode,
            idempotency_key=model.idempotency_key,
            last_error=model.last_error,
            metrics=dict(model.metrics or {}),
            published_at=model.published_at,
            metrics_collected_at=model.metrics_collected_at,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
