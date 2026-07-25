from __future__ import annotations

from sqlalchemy.orm import Session

from app.domain.entities import AssetRevisionSnapshot, ContentAsset
from app.infrastructure.db.models import AssetRevisionSnapshotModel


class AssetRevisionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def snapshot_asset(self, asset: ContentAsset) -> AssetRevisionSnapshot:
        snapshot = AssetRevisionSnapshot(
            content_asset_id=asset.id,
            campaign_run_id=asset.campaign_run_id,
            version=asset.content_version,
            status=asset.status.value,
            title=asset.title,
            subject=asset.subject,
            content_html=asset.content_html or asset.body,
            content_text=asset.content_text,
            excerpt=asset.excerpt,
            call_to_action=asset.call_to_action,
            target_url=asset.target_url,
            content_hash=asset.content_hash,
            approved_content_hash=asset.approved_content_hash,
            results=dict(asset.results or {}),
        )
        self.session.add(self._to_model(snapshot))
        self.session.commit()
        return snapshot

    def list_for_asset(self, asset_id: str) -> list[AssetRevisionSnapshot]:
        rows = (
            self.session.query(AssetRevisionSnapshotModel)
            .filter(AssetRevisionSnapshotModel.content_asset_id == asset_id)
            .order_by(AssetRevisionSnapshotModel.version.desc(), AssetRevisionSnapshotModel.created_at.desc())
            .all()
        )
        return [self._to_entity(row) for row in rows]

    def _to_model(self, snapshot: AssetRevisionSnapshot) -> AssetRevisionSnapshotModel:
        return AssetRevisionSnapshotModel(
            id=snapshot.id,
            content_asset_id=snapshot.content_asset_id,
            campaign_run_id=snapshot.campaign_run_id,
            version=snapshot.version,
            status=snapshot.status,
            title=snapshot.title,
            subject=snapshot.subject,
            content_html=snapshot.content_html,
            content_text=snapshot.content_text,
            excerpt=snapshot.excerpt,
            call_to_action=snapshot.call_to_action,
            target_url=snapshot.target_url,
            content_hash=snapshot.content_hash,
            approved_content_hash=snapshot.approved_content_hash,
            results=snapshot.results,
            created_at=snapshot.created_at,
        )

    def _to_entity(self, model: AssetRevisionSnapshotModel) -> AssetRevisionSnapshot:
        return AssetRevisionSnapshot(
            id=model.id,
            content_asset_id=model.content_asset_id,
            campaign_run_id=model.campaign_run_id,
            version=model.version,
            status=model.status,
            title=model.title,
            subject=model.subject,
            content_html=model.content_html,
            content_text=model.content_text,
            excerpt=model.excerpt,
            call_to_action=model.call_to_action,
            target_url=model.target_url,
            content_hash=model.content_hash,
            approved_content_hash=model.approved_content_hash,
            results=dict(model.results or {}),
            created_at=model.created_at,
        )
