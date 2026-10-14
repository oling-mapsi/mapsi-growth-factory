from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.domain.entities import ProductChange
from app.infrastructure.db.models import EditorialThemeHistoryModel, ProductChangeModel
from app.knowledge.models import EditorialRules, MapsiFeature, OlingPractice, PublishedTopicHistoryEntry
from app.knowledge.validation import load_feature_catalog, load_oling_practice, read_knowledge_text, resolve_knowledge_root


class KnowledgeRepository:
    def __init__(self, session: Session | None = None, *, root: Path | None = None) -> None:
        self.session = session
        self.root = resolve_knowledge_root(root)

    def listMapsIProductChangesSince(self, since: date) -> list[ProductChange]:
        if self.session is None:
            return []
        since_at = datetime.combine(since, datetime.min.time(), tzinfo=UTC)
        rows = (
            self.session.query(ProductChangeModel)
            .filter(ProductChangeModel.collected_at >= since_at)
            .order_by(ProductChangeModel.collected_at.desc(), ProductChangeModel.id.asc())
            .all()
        )
        return [
            ProductChange(
                id=row.id,
                repository_source_id=row.repository_source_id,
                repository_full_name=row.repository_full_name,
                sha=row.sha,
                pr_number=row.pr_number,
                issue_numbers=list(row.issue_numbers or []),
                release_tag=row.release_tag,
                deployment_ref=row.deployment_ref,
                production_status=row.production_status,
                change_note_path=row.change_note_path,
                eligible_for_communication=row.eligible_for_communication,
                confidential=row.confidential,
                target_client_key=row.target_client_key,
                capability_key=row.capability_key,
                summary=row.summary,
                contract_version=row.contract_version,
                deployment_proven=row.deployment_proven,
                collected_at=row.collected_at,
                raw_payload=dict(row.raw_payload or {}),
            )
            for row in rows
        ]

    def listMapsIFeatures(self) -> list[MapsiFeature]:
        return load_feature_catalog(self.root / "mapsi" / "feature-catalog.yaml")

    def getMapsIFeature(self, feature_id: str) -> MapsiFeature | None:
        return next((item for item in self.listMapsIFeatures() if item.feature_id == feature_id), None)

    def listOlingPractices(self) -> list[OlingPractice]:
        practices_dir = self.root / "oling" / "practices"
        return [load_oling_practice(path) for path in sorted(practices_dir.glob("*.md"))]

    def getOlingPractice(self, practice_id: str) -> OlingPractice | None:
        return next((item for item in self.listOlingPractices() if item.practice_id == practice_id), None)

    def getEditorialRules(self) -> EditorialRules:
        return EditorialRules(
            mapsi_product_positioning=read_knowledge_text(self.root / "mapsi" / "product-positioning.md"),
            mapsi_terminology=read_knowledge_text(self.root / "mapsi" / "terminology.md"),
            mapsi_target_personas=read_knowledge_text(self.root / "mapsi" / "target-personas.md"),
            mapsi_forbidden_claims=read_knowledge_text(self.root / "mapsi" / "forbidden-claims.md"),
            oling_company_profile=read_knowledge_text(self.root / "oling" / "company-profile.md"),
            oling_editorial_style=read_knowledge_text(self.root / "oling" / "editorial-style.md"),
            oling_target_clients=read_knowledge_text(self.root / "oling" / "target-clients.md"),
            oling_differentiators=read_knowledge_text(self.root / "oling" / "differentiators.md"),
            oling_forbidden_claims=read_knowledge_text(self.root / "oling" / "forbidden-claims.md"),
            knowledge_version_hash=read_knowledge_text(self.root / "version.sha256").strip(),
        )

    def getPublishedTopicHistory(self, limit: int = 10) -> list[PublishedTopicHistoryEntry]:
        if self.session is None:
            return []
        rows = (
            self.session.query(EditorialThemeHistoryModel)
            .order_by(EditorialThemeHistoryModel.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            PublishedTopicHistoryEntry(
                topic=row.topic,
                objective=row.objective,
                audience_segment_id=row.audience_segment_id,
                created_at=row.created_at,
            )
            for row in rows
        ]
