from __future__ import annotations

from datetime import UTC, datetime

from app.application.services.editorial_engine_v1 import OpenAIEditorialGenerator, build_editorial_generation_service
from app.application.services.editorial_production_v1 import EditorialAssetMutationService, MapsiMarketProductionBuilder, OlingPracticeProductionBuilder
from app.domain.entities import AudienceSegment, CampaignRun, ContentAsset
from app.domain.enums import AssetStatus, CampaignStatus
from app.infrastructure.agents.fake_backend import FakeStructuredAgentBackend
from app.infrastructure.db.models import ProductChangeModel
from app.infrastructure.repositories.asset_revisions import AssetRevisionRepository
from app.infrastructure.repositories.audit import SqlAlchemyAuditLogRepository
from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
from app.infrastructure.repositories.editorial_pipeline import EditorialPipelineRepository
from app.knowledge import KnowledgeRepository


def _seed_recent_product_change(session, *, change_id: str = "pc-1", summary: str = "Export du tableau utilisateur") -> None:
    session.add(
        ProductChangeModel(
            id=change_id,
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
            collected_at=datetime(2026, 7, 11, tzinfo=UTC),
            raw_payload={},
        )
    )
    session.commit()


def _article_payload(*, topic: str, article_type: str, slug: str, title: str, source_ids: list[str]) -> dict:
    text = "Cet article explique un sujet prouve, ses usages et ses bonnes pratiques sans promesse excessive. " * 5
    return {
        "topic": topic,
        "article_type": article_type,
        "title": title,
        "slug": slug,
        "excerpt": "Un article de synthese prudent et source.",
        "body_html": f"<p>{text}</p>",
        "body_text": text,
        "meta_title": title[:60],
        "meta_description": "Meta description de synthese, prudente et sourcee.",
        "target_personas": ["direction_metier", "responsable_transformation"],
        "primary_keyword": topic,
        "secondary_keywords": ["mapsi", "adoption"],
        "call_to_action_label": "Demander un echange",
        "call_to_action_url": "https://www.oling.fr/contact",
        "source_ids": source_ids,
        "claims": [{"text": "La fonctionnalite est decrite dans la base de connaissances.", "source_ids": source_ids[:1], "claim_type": "product_fact" if article_type != "OLING_PRACTICE" else "practice_fact", "verified": True}],
        "warnings": [],
    }


def test_mapsi_market_production_builder_creates_two_distinct_articles(session) -> None:
    _seed_recent_product_change(session)
    backend = FakeStructuredAgentBackend(
        [
            _article_payload(
                topic="Export des indicateurs du tableau utilisateur",
                article_type="MAPSI_PRODUCT",
                slug="export-indicateurs-mapsi",
                title="Export des indicateurs du tableau utilisateur dans MAPSI",
                source_ids=["knowledge:mapsi:feature:dashboard-indicators-export", "product_change:pc-1"],
            ),
            _article_payload(
                topic="Export des indicateurs du tableau utilisateur",
                article_type="MAPSI_CONSULTING",
                slug="export-indicateurs-conseil",
                title="Mieux exploiter l'export des indicateurs du tableau utilisateur",
                source_ids=["knowledge:mapsi:feature:dashboard-indicators-export", "product_change:pc-1"],
            ),
        ],
        provider_type="openai",
    )
    editorial_service = build_editorial_generation_service(session, force_mode="real")
    editorial_service.generator = OpenAIEditorialGenerator(backend)
    builder = MapsiMarketProductionBuilder(
        editorial_service=editorial_service,
        knowledge_repository=KnowledgeRepository(session),
        editorial_repository=EditorialPipelineRepository(session),
        campaign_repository=SqlAlchemyCampaignRepository(session),
    )

    result = builder.build(record_theme_history=False)

    assert len(result.assets) == 2
    assert {item.asset_type for item in result.assets} == {"mapsi_news_article", "oling_news_article"}
    assert all(item.status is AssetStatus.READY_FOR_REVIEW for item in result.assets)
    assert result.assets[0].title != result.assets[1].title


def test_oling_practice_production_builder_selects_enabled_practice(session) -> None:
    backend = FakeStructuredAgentBackend(
        [
            _article_payload(
                topic="Facturation electronique",
                article_type="OLING_PRACTICE",
                slug="facturation-electronique-oling",
                title="Facturation electronique : cadrer sans promettre trop vite",
                source_ids=["knowledge:oling:practice:facturation-electronique", "knowledge:oling:profile"],
            )
        ],
        provider_type="openai",
    )
    editorial_service = build_editorial_generation_service(session, force_mode="real")
    editorial_service.generator = OpenAIEditorialGenerator(backend)
    builder = OlingPracticeProductionBuilder(
        editorial_service=editorial_service,
        knowledge_repository=KnowledgeRepository(session),
        editorial_repository=EditorialPipelineRepository(session),
        campaign_repository=SqlAlchemyCampaignRepository(session),
    )

    result = builder.build(record_theme_history=False)

    assert len(result.assets) == 1
    assert result.assets[0].asset_type == "oling_news_article"
    assert result.assets[0].status is AssetStatus.READY_FOR_REVIEW


def test_editorial_asset_mutation_service_snapshots_and_rewrites(session) -> None:
    campaigns = SqlAlchemyCampaignRepository(session)
    audit = SqlAlchemyAuditLogRepository(session)
    _seed_recent_product_change(session)
    campaign = CampaignRun(name="Rewrite campaign", objective="market_visibility", status=CampaignStatus.READY_FOR_REVIEW)
    campaign.audience_segments.append(AudienceSegment(campaign_run_id=campaign.id, name="reviewers", description="reviewers"))
    asset = ContentAsset(
        campaign_run_id=campaign.id,
        asset_type="mapsi_news_article",
        channel="mapsi_site",
        title="Titre initial",
        content_html="<p>Corps initial suffisamment long pour passer les controles de longueur.</p>" * 3,
        content_text="Corps initial suffisamment long pour passer les controles de longueur. " * 3,
        excerpt="Extrait initial",
        call_to_action="Demander un echange",
        target_url="https://mapsi.fr",
        audience_segment_id=campaign.audience_segments[0].id,
        status=AssetStatus.READY_FOR_REVIEW,
        results={
            "builder_context": {
                "topic": "Export des indicateurs du tableau utilisateur",
                "article_type": "MAPSI_PRODUCT",
                "destination_site": "mapsi.fr",
                "target_personas": ["direction_metier"],
                "knowledge_version": "test",
                "positioning": "positioning",
                "terminology": "terminology",
                "target_clients": "",
                "differentiators": "",
                "editorial_rules": "rules",
                "forbidden_claims": [],
                "mapsi_feature": {
                    "feature_id": "dashboard-indicators-export",
                    "module": "dashboard",
                    "title": "Export des indicateurs du tableau utilisateur",
                    "short_description": "Export des indicateurs",
                    "business_problem": "Eviter des retraitements manuels.",
                    "functional_description": "Export depuis le tableau utilisateur.",
                    "user_benefits": ["Gain de temps"],
                    "typical_use_cases": ["Partage interne"],
                    "target_roles": ["responsable"],
                    "forbidden_claims": [],
                },
                "recent_product_changes": [],
                "oling_practice": None,
                "published_topic_history": [],
                "sources": [
                    {
                        "source_id": "knowledge:mapsi:feature:dashboard-indicators-export",
                        "source_type": "knowledge_file",
                        "label": "Feature dashboard-indicators-export",
                        "reference": "knowledge/mapsi/feature-catalog.yaml#dashboard-indicators-export",
                        "summary": "Base de connaissances MAPSI validee.",
                    }
                ],
                "rewrite_instruction": "",
                "desired_title": "",
                "length_directive": "",
                "angle_directive": "",
            }
        },
    )
    asset.ensure_content_hash()
    campaign.content_assets.append(asset)
    campaign = campaigns.add(campaign)
    backend = FakeStructuredAgentBackend(
        [
            _article_payload(
                topic="Export des indicateurs du tableau utilisateur",
                article_type="MAPSI_PRODUCT",
                slug="export-indicateurs-rewrite",
                title="Titre reecrit",
                source_ids=["knowledge:mapsi:feature:dashboard-indicators-export"],
            )
        ],
        provider_type="openai",
    )
    editorial_service = build_editorial_generation_service(session, force_mode="real")
    editorial_service.generator = OpenAIEditorialGenerator(backend)
    service = EditorialAssetMutationService(
        editorial_service=editorial_service,
        campaign_repository=campaigns,
        revision_repository=AssetRevisionRepository(session),
        audit_repository=audit,
    )

    rewritten = service.regenerate(campaign.content_assets[0].id, actor="tester", expected_version=1, instruction="Raccourcir")

    snapshots = AssetRevisionRepository(session).list_for_asset(asset.id)
    assert rewritten.content_version == 2
    assert rewritten.title == "Titre reecrit"
    assert len(snapshots) == 1
    assert snapshots[0].title == "Titre initial"
