from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.application.services.editorial_engine_v1 import OpenAIEditorialGenerator, build_editorial_generation_service
from app.domain.enums import AssetStatus
from app.domain.errors import EditorialGenerationBlockedError
from app.infrastructure.agents.fake_backend import FakeStructuredAgentBackend
from app.infrastructure.db.models import ContentAssetModel, EditorialThemeHistoryModel, ProductChangeModel


def _seed_recent_product_change(session, *, collected_at: datetime | None = None, summary: str = "Export du tableau utilisateur") -> None:
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
            summary=summary,
            contract_version="1.0.0",
            deployment_proven=True,
            collected_at=collected_at or datetime(2026, 7, 11, tzinfo=UTC),
            raw_payload={},
        )
    )
    session.commit()


def _article_payload(*, topic: str, article_type: str, source_ids: list[str], body_text: str | None = None, claim_verified: bool = True) -> dict:
    text = body_text or "Cet article explique un sujet prouve, ses usages et ses bonnes pratiques sans promesse excessive. " * 5
    claim_sources = [source_ids[0]] if source_ids else []
    return {
        "topic": topic,
        "article_type": article_type,
        "title": f"{topic} en pratique",
        "slug": "export-du-tableau-utilisateur-en-pratique",
        "excerpt": "Un article de synthese prudent et source.",
        "body_html": f"<p>{text}</p>",
        "body_text": text,
        "meta_title": f"{topic} en pratique",
        "meta_description": "Meta description de synthese, prudente et sourcee.",
        "target_personas": ["direction_metier", "responsable_transformation"],
        "primary_keyword": topic,
        "secondary_keywords": ["mapsi", "adoption"],
        "call_to_action_label": "Demander un echange",
        "call_to_action_url": "https://www.oling.fr/contact",
        "source_ids": source_ids,
        "claims": [
            {
                "text": "La fonctionnalite est decrite dans la base de connaissances.",
                "source_ids": claim_sources,
                "claim_type": "product_fact" if article_type != "OLING_PRACTICE" else "practice_fact",
                "verified": claim_verified,
            }
        ],
        "warnings": [],
    }


def test_generate_mapsi_recent_novelty_persists_draft(session) -> None:
    _seed_recent_product_change(session)
    backend = FakeStructuredAgentBackend([_article_payload(topic="Export des indicateurs du tableau utilisateur", article_type="MAPSI_PRODUCT", source_ids=["knowledge:mapsi:feature:dashboard-indicators-export", "product_change:pc-1"])], provider_type="openai")
    service = build_editorial_generation_service(session, force_mode="real")
    service.generator = OpenAIEditorialGenerator(backend)

    record = service.generate_mapsi(destination="mapsi", persist=True)

    assert record.quality.passed is True
    assert record.provider_type == "openai"
    persisted = session.query(ContentAssetModel).all()
    assert len(persisted) == 1
    assert persisted[0].asset_type == "mapsi_news_article"


def test_generate_mapsi_blocks_when_no_recent_novelty(session) -> None:
    service = build_editorial_generation_service(session, force_mode="simulated")

    with pytest.raises(EditorialGenerationBlockedError, match="No recent MAPSI product changes found"):
        service.generate_mapsi(destination="mapsi", persist=False)


def test_generate_mapsi_blocks_already_treated_topic(session) -> None:
    _seed_recent_product_change(session)
    session.add(
        EditorialThemeHistoryModel(
            topic="Export des indicateurs du tableau utilisateur",
            objective="editorial_article_generation",
            audience_segment_id="mapsi_product",
        )
    )
    session.commit()
    backend = FakeStructuredAgentBackend([_article_payload(topic="Export des indicateurs du tableau utilisateur", article_type="MAPSI_PRODUCT", source_ids=["knowledge:mapsi:feature:dashboard-indicators-export", "product_change:pc-1"], body_text="Export des indicateurs du tableau utilisateur et usages. " * 8)], provider_type="openai")
    service = build_editorial_generation_service(session, force_mode="shadow")
    service.generator = OpenAIEditorialGenerator(backend)

    with pytest.raises(EditorialGenerationBlockedError, match="content_too_similar"):
        service.generate_mapsi(destination="mapsi", persist=False)


def test_generate_oling_practice_works(session) -> None:
    backend = FakeStructuredAgentBackend([_article_payload(topic="ERP", article_type="OLING_PRACTICE", source_ids=["knowledge:oling:practice:erp", "knowledge:oling:profile"])], provider_type="openai")
    service = build_editorial_generation_service(session, force_mode="shadow")
    service.generator = OpenAIEditorialGenerator(backend)

    record = service.generate_oling(practice_id="erp", persist=False)

    assert record.article.article_type == "OLING_PRACTICE"
    assert record.quality.passed is True


def test_generate_blocks_claim_without_valid_source(session) -> None:
    _seed_recent_product_change(session)
    payload = _article_payload(topic="Export des indicateurs du tableau utilisateur", article_type="MAPSI_PRODUCT", source_ids=["knowledge:mapsi:feature:dashboard-indicators-export"])
    payload["claims"][0]["source_ids"] = ["unknown-source"]
    backend = FakeStructuredAgentBackend([payload], provider_type="openai")
    service = build_editorial_generation_service(session, force_mode="real")
    service.generator = OpenAIEditorialGenerator(backend)

    with pytest.raises(EditorialGenerationBlockedError, match="claim_unknown_source"):
        service.generate_mapsi(destination="mapsi", persist=False)


def test_generate_blocks_invented_client_reference(session) -> None:
    _seed_recent_product_change(session)
    payload = _article_payload(topic="Export des indicateurs du tableau utilisateur", article_type="MAPSI_PRODUCT", source_ids=["knowledge:mapsi:feature:dashboard-indicators-export", "product_change:pc-1"], body_text="Chez Acme, cette fonctionnalite change tout. " * 8)
    backend = FakeStructuredAgentBackend([payload], provider_type="openai")
    service = build_editorial_generation_service(session, force_mode="real")
    service.generator = OpenAIEditorialGenerator(backend)

    with pytest.raises(EditorialGenerationBlockedError, match="unauthorized_client_reference"):
        service.generate_mapsi(destination="oling", persist=False)


def test_generate_blocks_unverified_claim(session) -> None:
    _seed_recent_product_change(session)
    backend = FakeStructuredAgentBackend([_article_payload(topic="Export des indicateurs du tableau utilisateur", article_type="MAPSI_PRODUCT", source_ids=["knowledge:mapsi:feature:dashboard-indicators-export", "product_change:pc-1"], claim_verified=False)], provider_type="openai")
    service = build_editorial_generation_service(session, force_mode="shadow")
    service.generator = OpenAIEditorialGenerator(backend)

    with pytest.raises(EditorialGenerationBlockedError, match="unverified_claim"):
        service.generate_mapsi(destination="mapsi", persist=False)


def test_generate_blocks_source_insufficient(session) -> None:
    _seed_recent_product_change(session)
    payload = _article_payload(topic="Export des indicateurs du tableau utilisateur", article_type="MAPSI_PRODUCT", source_ids=[])
    payload["claims"] = []
    backend = FakeStructuredAgentBackend([payload], provider_type="openai")
    service = build_editorial_generation_service(session, force_mode="real")
    service.generator = OpenAIEditorialGenerator(backend)

    with pytest.raises(EditorialGenerationBlockedError, match="missing_sources"):
        service.generate_mapsi(destination="mapsi", persist=False)


def test_similarity_checks_against_existing_article_assets(session) -> None:
    _seed_recent_product_change(session)
    session.add(
        ContentAssetModel(
            id="asset-1",
            campaign_run_id="campaign-1",
            asset_type="mapsi_news_article",
            channel="mapsi_site",
            locale="fr-FR",
            title="Export des indicateurs du tableau utilisateur en pratique",
            subject="",
            body="<p>Export des indicateurs du tableau utilisateur et usages.</p>",
            content_html="<p>Export des indicateurs du tableau utilisateur et usages.</p>",
            content_text="Export des indicateurs du tableau utilisateur et usages.",
            excerpt="Export des indicateurs du tableau utilisateur et usages.",
            call_to_action="",
            target_url="https://www.mapsi.fr",
            evidence_ids=[],
            source_evidence_ids=[],
            audience_segment_id="mapsi_product",
            status=AssetStatus.READY_FOR_REVIEW.value,
            content_version=1,
            content_hash="hash",
            approved_content_hash="",
            approved_by="",
            approved_at=None,
            scheduled_at=None,
            published_at=None,
            external_publication_id="",
            external_publication_url="",
            last_error="",
            retry_count=0,
            results={"editorial_article": {"slug": "export-du-tableau-utilisateur-en-pratique"}},
            revision=1,
            created_at=datetime(2026, 7, 18, tzinfo=UTC),
        )
    )
    session.commit()
    backend = FakeStructuredAgentBackend([_article_payload(topic="Export des indicateurs du tableau utilisateur", article_type="MAPSI_PRODUCT", source_ids=["knowledge:mapsi:feature:dashboard-indicators-export", "product_change:pc-1"], body_text="Export des indicateurs du tableau utilisateur et usages. " * 8)], provider_type="openai")
    service = build_editorial_generation_service(session, force_mode="real")
    service.generator = OpenAIEditorialGenerator(backend)

    with pytest.raises(EditorialGenerationBlockedError, match="content_too_similar"):
        service.generate_mapsi(destination="mapsi", persist=False)
