from __future__ import annotations

from datetime import UTC, datetime

from app.infrastructure.db.models import EditorialThemeHistoryModel, ProductChangeModel
from app.knowledge import KnowledgeRepository, validate_knowledge_base


def test_knowledge_validation_passes_on_versioned_files() -> None:
    report = validate_knowledge_base()

    assert report.ok is True
    assert report.version_hash
    assert "dashboard-indicators-export" in report.mapsi_feature_ids
    assert "erp" in report.oling_practice_ids


def test_knowledge_repository_loads_versioned_assets(session) -> None:
    repository = KnowledgeRepository(session)

    feature = repository.getMapsIFeature("dashboard-indicators-export")
    practice = repository.getOlingPractice("erp")
    rules = repository.getEditorialRules()

    assert feature is not None
    assert feature.module == "dashboard"
    assert practice is not None
    assert practice.title == "ERP"
    assert "Positionnement produit MAPSI" in rules.mapsi_product_positioning
    assert rules.knowledge_version_hash


def test_knowledge_repository_reads_product_changes_and_topic_history(session) -> None:
    session.add(
        ProductChangeModel(
            id="pc-1",
            repository_source_id="source-1",
            repository_full_name="oling-mapsi/mapsi-v6",
            sha="MAPSI-2026-010",
            pr_number=2101,
            issue_numbers=[],
            release_tag="",
            deployment_ref="2026-07-01T00:00:00Z",
            production_status="production",
            change_note_path="api/internal/growth/v1/product-changes#MAPSI-2026-010",
            eligible_for_communication=True,
            confidential=False,
            target_client_key="",
            capability_key="dashboard-indicators-export",
            summary="Export du tableau utilisateur",
            contract_version="1.0.0",
            deployment_proven=True,
            collected_at=datetime(2026, 7, 11, tzinfo=UTC),
            raw_payload={},
        )
    )
    session.add(
        EditorialThemeHistoryModel(
            topic="ERP et gouvernance",
            objective="practice_visibility",
            audience_segment_id="oling_practice",
        )
    )
    session.commit()

    repository = KnowledgeRepository(session)
    product_changes = repository.listMapsIProductChangesSince(datetime(2026, 7, 1, tzinfo=UTC).date())
    history = repository.getPublishedTopicHistory()

    assert len(product_changes) == 1
    assert product_changes[0].sha == "MAPSI-2026-010"
    assert len(history) == 1
    assert history[0].topic == "ERP et gouvernance"
