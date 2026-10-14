from __future__ import annotations

from app.application.services.oling_practice_campaign_builder import OlingPracticeCampaignBuilder
from app.domain.entities import EditorialSourceItem, EditorialSourcePack
from app.infrastructure.db.models import EditorialThemeHistoryModel
from app.infrastructure.repositories.editorial_pipeline import EditorialPipelineRepository
from app.infrastructure.repositories.editorial_source_packs import EditorialSourcePackRepository


def _builder(session) -> OlingPracticeCampaignBuilder:
    return OlingPracticeCampaignBuilder(
        editorial_repository=EditorialPipelineRepository(session),
        editorial_source_packs=EditorialSourcePackRepository(session),
    )


def _validated_pack(*, weekly_pack_id: str, item: EditorialSourceItem) -> EditorialSourcePack:
    return EditorialSourcePack(
        weekly_pack_id=weekly_pack_id,
        campaign_type="OLING_PRACTICE",
        title="Sources pratique",
        summary="Pack de sources",
        status="VALIDATED",
        items=[item],
    )


def test_oling_practice_builder_builds_from_validated_source_pack(session) -> None:
    EditorialSourcePackRepository(session).add(
        _validated_pack(
            weekly_pack_id="pack-1",
            item=EditorialSourceItem(
                source_type="PROJECT_DELIVERABLE",
                source_reference="DELIV-1",
                source_title="AMOA ERP pour un client",
                factual_summary="Accompagnement d'un projet ERP pour un client.",
                usable_facts=["Acme a structure la gouvernance du projet ERP."],
                anonymized_facts=["Un client a structure la gouvernance du projet ERP."],
                client_name="Acme",
                client_name_usage_authorized=False,
                confidentiality_level="CLIENT_CONFIDENTIAL",
                evidence_quality="high",
                manual_input={
                    "client_problem": "Le pilotage ERP manquait de cadre.",
                    "oling_method": "Ateliers de cadrage et gouvernance progressive.",
                    "deliverables_completed": ["Cadrage", "Feuille de route"],
                    "observed_results": ["Vision partagee"],
                    "lessons_learned": ["Prioriser le cadrage"],
                    "desired_cta": "Demander un cadrage OLING",
                },
            ),
        )
    )

    result = _builder(session).build(weekly_pack_id="pack-1")

    assert result.brief.practice == "ERP"
    assert result.brief.authorized_client_name == ""
    assert result.brief.anonymization_required is True
    assert len(result.assets) == 2
    article = next(asset for asset in result.assets if asset.asset_type == "oling_news_article")
    linkedin = next(asset for asset in result.assets if asset.asset_type == "linkedin_company_post")
    assert "Acme" not in article.content_text
    assert "oling.fr/ressources/" in linkedin.target_url
    assert all(item["passed"] for item in result.evaluations.values())


def test_oling_practice_builder_never_keeps_raw_teams_wording(session) -> None:
    EditorialSourcePackRepository(session).add(
        _validated_pack(
            weekly_pack_id="pack-2",
            item=EditorialSourceItem(
                source_type="TEAMS_MESSAGE",
                source_reference="TEAMS-1",
                source_title="Retour terrain cybersécurité",
                factual_summary="Message Teams sur un chantier cyber.",
                usable_facts=["Le message Teams synthétise une approche de securisation progressive."],
                anonymized_facts=["Une equipe a formalise une approche de securisation progressive."],
                confidentiality_level="INTERNAL",
                evidence_quality="high",
            ),
        )
    )

    result = _builder(session).build(weekly_pack_id="pack-2")

    article = next(asset for asset in result.assets if asset.asset_type == "oling_news_article")
    linkedin = next(asset for asset in result.assets if asset.asset_type == "linkedin_company_post")
    assert "teams" not in article.content_text.casefold()
    assert "teams" not in linkedin.content_text.casefold()


def test_oling_practice_builder_skips_recent_theme(session) -> None:
    repository = EditorialSourcePackRepository(session)
    repository.add(
        _validated_pack(
            weekly_pack_id="pack-3",
            item=EditorialSourceItem(
                source_type="PROJECT_DELIVERABLE",
                source_reference="DELIV-31",
                source_title="Approche ERP",
                factual_summary="Projet ERP",
                anonymized_facts=["Un client a clarifie la gouvernance ERP."],
                evidence_quality="high",
            ),
        )
    )
    repository.add(
        _validated_pack(
            weekly_pack_id="pack-3",
            item=EditorialSourceItem(
                source_type="CONSULTANT_NOTE",
                source_reference="NOTE-31",
                source_title="Accompagnement DSI",
                factual_summary="Pilotage DSI",
                anonymized_facts=["Une DSI a clarifie ses priorites projet."],
                evidence_quality="high",
            ),
        )
    )
    session.add(
        EditorialThemeHistoryModel(
            topic="ERP Approche ERP",
            objective="practice_visibility",
            audience_segment_id="oling_practice",
        )
    )
    session.commit()

    result = _builder(session).build(weekly_pack_id="pack-3")

    assert result.brief.practice != "ERP"


def test_oling_practice_builder_marks_linkedin_as_draft_only_in_pilot_mode(session) -> None:
    result = _builder(session).build(pilot_mode=True, fallback_evidence_ids=["fallback-a"])

    linkedin = next(asset for asset in result.assets if asset.asset_type == "linkedin_company_post")
    assert linkedin.results["pilot_draft_only"] is True
    assert linkedin.results["publication_mode_requested"] == "draft_only"
