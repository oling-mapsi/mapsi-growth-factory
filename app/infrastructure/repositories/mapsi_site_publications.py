from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.domain.entities import MapsiNewsPublication
from app.infrastructure.db.models import MapsiNewsPublicationModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MapsiNewsPublicationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_asset_hash(self, content_asset_id: str, content_hash: str) -> MapsiNewsPublication | None:
        model = (
            self.session.query(MapsiNewsPublicationModel)
            .filter(
                MapsiNewsPublicationModel.content_asset_id == content_asset_id,
                MapsiNewsPublicationModel.content_hash == content_hash,
            )
            .one_or_none()
        )
        return self._to_entity(model) if model else None

    def get_latest_for_asset(self, content_asset_id: str) -> MapsiNewsPublication | None:
        model = (
            self.session.query(MapsiNewsPublicationModel)
            .filter(MapsiNewsPublicationModel.content_asset_id == content_asset_id)
            .order_by(MapsiNewsPublicationModel.updated_at.desc())
            .first()
        )
        return self._to_entity(model) if model else None

    def save(self, publication: MapsiNewsPublication) -> MapsiNewsPublication:
        model = self.session.get(MapsiNewsPublicationModel, publication.id)
        if model is None:
            model = MapsiNewsPublicationModel(id=publication.id)
            self.session.add(model)
        model.campaign_run_id = publication.campaign_run_id
        model.content_asset_id = publication.content_asset_id
        model.external_id = publication.external_id
        model.content_hash = publication.content_hash
        model.status = publication.status
        model.mode = publication.mode
        model.publication_mode_requested = publication.publication_mode_requested
        model.publication_mode_executed = publication.publication_mode_executed
        model.publisher_type = publication.publisher_type
        model.publication_status = publication.publication_status
        model.idempotency_key = publication.idempotency_key
        model.preview_url = publication.preview_url
        model.public_url = publication.public_url
        model.public_slug = publication.public_slug
        model.draft_revision_number = publication.draft_revision_number
        model.published_revision_number = publication.published_revision_number
        model.published_content_version = publication.published_content_version
        model.published_at = publication.published_at
        model.unpublished_at = publication.unpublished_at
        model.last_error = publication.last_error
        model.metrics = publication.metrics
        model.created_at = publication.created_at
        model.updated_at = utcnow()
        self.session.commit()
        self.session.refresh(model)
        return self._to_entity(model)

    def _to_entity(self, model: MapsiNewsPublicationModel) -> MapsiNewsPublication:
        return MapsiNewsPublication(
            id=model.id,
            campaign_run_id=model.campaign_run_id,
            content_asset_id=model.content_asset_id,
            external_id=model.external_id,
            content_hash=model.content_hash,
            status=model.status,
            mode=model.mode,
            publication_mode_requested=model.publication_mode_requested,
            publication_mode_executed=model.publication_mode_executed,
            publisher_type=model.publisher_type,
            publication_status=model.publication_status,
            idempotency_key=model.idempotency_key,
            preview_url=model.preview_url,
            public_url=model.public_url,
            public_slug=model.public_slug,
            draft_revision_number=model.draft_revision_number,
            published_revision_number=model.published_revision_number,
            published_content_version=model.published_content_version,
            published_at=model.published_at,
            unpublished_at=model.unpublished_at,
            last_error=model.last_error,
            metrics=dict(model.metrics or {}),
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
