from __future__ import annotations

from app.application.services.mapsi_market_campaign_builder import MapsiMarketCampaignBuilder
from app.domain.entities import EditorialSourceItem, EditorialSourcePack, ProductChange, SourceEvidence
from app.infrastructure.db.models import EditorialThemeHistoryModel
from app.infrastructure.repositories.editorial_pipeline import EditorialPipelineRepository
from app.infrastructure.repositories.editorial_source_packs import EditorialSourcePackRepository
from app.infrastructure.repositories.product_intelligence import SqlAlchemyProductChangeRepository, SqlAlchemySourceEvidenceRepository


def _builder(session) -> MapsiMarketCampaignBuilder:
    return MapsiMarketCampaignBuilder(
        editorial_repository=EditorialPipelineRepository(session),
        editorial_source_packs=EditorialSourcePackRepository(session),
    )


def _seed_product_change(session, *, capability_key: str, summary: str) -> str:
    change = ProductChange(
        repository_source_id="repo-1",
        repository_full_name="mapsi/mapsi-v6",
        sha=f"sha-{capability_key}",
        change_note_path=f"growth/change-notes/{capability_key}.yaml",
        capability_key=capability_key,
        summary=summary,
        eligible_for_communication=True,
        confidential=False,
        contract_version="1.0.0",
        production_status="production",
        deployment_proven=True,
    )
    SqlAlchemyProductChangeRepository(session).save_many([change])
    evidence = SourceEvidence(
        product_change_id=change.id,
        source_system="github",
        evidence_type="deployment",
        reference=f"deploy:{capability_key}",
        payload={"proof": "ok"},
    )
    SqlAlchemySourceEvidenceRepository(session).save_many([evidence])
    return evidence.id


def test_mapsi_market_builder_selects_product_change_and_produces_distinct_assets(session) -> None:
    _seed_product_change(session, capability_key="dashboard_export", summary="Export des indicateurs depuis le tableau utilisateur")

    result = _builder(session).build(fallback_evidence_ids=["fallback-evidence"])

    assert result.brief.canonical_article_target == "mapsi.fr"
    assert len(result.assets) == 3
    by_type = {asset.asset_type: asset for asset in result.assets}
    assert by_type["oling_news_article"].title != by_type["mapsi_news_article"].title
    assert by_type["oling_news_article"].content_text != by_type["mapsi_news_article"].content_text
    assert "mapsi.fr/actualites/" in by_type["linkedin_company_post"].target_url
    assert all(asset.source_evidence_ids for asset in result.assets)
    assert all(item["passed"] for item in result.evaluations.values())


def test_mapsi_market_builder_skips_recent_theme_when_selecting_topic(session) -> None:
    _seed_product_change(session, capability_key="exports", summary="Export des indicateurs depuis le tableau utilisateur")
    _seed_product_change(session, capability_key="workflow", summary="Validation simplifiee des demandes")
    session.add(
        EditorialThemeHistoryModel(
            topic="exports Export des indicateurs depuis le tableau utilisateur",
            objective="market_visibility",
            audience_segment_id="mapsi_market",
        )
    )
    session.commit()

    result = _builder(session).build(fallback_evidence_ids=["fallback-evidence"])

    assert "Validation simplifiee des demandes" in result.brief.selected_topic


def test_mapsi_market_builder_uses_validated_source_pack_as_fallback(session) -> None:
    EditorialSourcePackRepository(session).add(
        EditorialSourcePack(
            weekly_pack_id="pack-1",
            campaign_type="MAPSI_MARKET",
            title="Base editoriale",
            summary="Sources internes",
            status="VALIDATED",
            items=[
                EditorialSourceItem(
                    source_type="MANUAL_NOTE",
                    source_reference="manual:1",
                    source_title="Structurer une revue hebdomadaire MAPSI",
                    factual_summary="Bonnes pratiques MAPSI",
                    anonymized_facts=["Formaliser la revue hebdomadaire", "Partager les points d'attention"],
                )
            ],
        )
    )

    result = _builder(session).build(weekly_pack_id="pack-1")

    assert result.brief.canonical_article_target == "oling.fr"
    assert result.brief.product_change_ids == []
    assert result.brief.source_evidence_ids
    assert "oling.fr/ressources/" in {asset.target_url for asset in result.assets if asset.asset_type == "linkedin_company_post"}.pop()


def test_mapsi_market_builder_uses_generic_fallback_with_existing_evidences(session) -> None:
    result = _builder(session).build(fallback_evidence_ids=["evidence-a", "evidence-b"])

    assert result.brief.selected_topic == "Bonnes pratiques d'adoption MAPSI"
    assert result.brief.canonical_article_target == "oling.fr"
    assert result.brief.source_evidence_ids == ["evidence-a", "evidence-b"]


def test_mapsi_market_builder_marks_linkedin_as_draft_only_in_pilot_mode(session) -> None:
    _seed_product_change(session, capability_key="analytics", summary="Suivi analytique des parcours utilisateurs")

    result = _builder(session).build(pilot_mode=True, fallback_evidence_ids=["fallback-evidence"])

    linkedin_asset = next(asset for asset in result.assets if asset.asset_type == "linkedin_company_post")
    assert linkedin_asset.results["pilot_draft_only"] is True
    assert linkedin_asset.results["publication_mode_requested"] == "draft_only"
