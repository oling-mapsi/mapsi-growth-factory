from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.application.services.editorial_engine_v1 import OpenAIEditorialGenerator, build_editorial_generation_service
from app.domain.enums import AssetStatus
from app.domain.errors import EditorialGenerationBlockedError
from app.infrastructure.agents.fake_backend import FakeStructuredAgentBackend
from app.infrastructure.db.models import ContentAssetModel, EditorialThemeHistoryModel, ProductChangeModel


def _quality_pair(session, text):
    from app.application.models.editorial_v1 import EditorialArticle
    context = build_editorial_generation_service(session, force_mode="simulated")._build_oling_context(practice_id="erp")
    payload = _article_payload(topic="ERP", article_type="OLING_PRACTICE", source_ids=[context.sources[0].source_id], body_text=("Un cadrage rigoureux facilite les decisions et la preparation du projet. " * 12) + text)
    return EditorialArticle.model_validate(payload), context


@pytest.mark.parametrize("text", [
    "Un client peut rencontrer des difficultes.", "Les besoins du client.",
    "Le systeme d'information du client.", "Aucun cas client de fusion.",
    "Chez un client.", "Chez nos clients.", "Chez OLING.",
    "Customer requirements.", "Client needs.", "Client teams clarify requirements.",
    "A client can review its processes.", "Las necesidades del cliente.",
    "El cliente puede revisar sus necesidades.", "Los requisitos de nuestros clientes.",
])
def test_client_detector_allows_ordinary_multilingual_business_prose(session, text):
    from app.application.services.editorial_engine_v1 import EditorialQualityValidator
    article, context = _quality_pair(session, text)
    assert EditorialQualityValidator().validate(article, context).passed


@pytest.mark.parametrize("field", ["title", "excerpt", "body_text", "body_html", "meta_title", "meta_description", "claims", "warnings"])
@pytest.mark.parametrize("text", ["Chez Acme, nous avons deploye un ERP.", "Client Globex.", "Testimonial from Umbrella.", "Cliente Contoso.", "Client Fusion."])
def test_named_clients_are_blocked_in_editorial_fields_with_exact_location(session, field, text):
    from app.application.services.editorial_engine_v1 import EditorialQualityValidator
    article, context = _quality_pair(session, "")
    if field == "claims":
        article.claims[0].text = text
    elif field == "warnings":
        article.warnings = [text]
    else:
        setattr(article, field, "<p>"+text+"</p>" if field == "body_html" else text)
    issues = [issue for issue in EditorialQualityValidator().validate(article, context).issues if issue.code == "unauthorized_client_reference"]
    assert issues and any(field in issue.message and '"' in issue.message and "offset" in issue.message for issue in issues)


def test_client_detector_ignores_source_identifiers_and_html_technical_attributes(session):
    from app.application.models.editorial_v1 import EditorialSourceDescriptor
    from app.application.services.editorial_engine_v1 import EditorialQualityValidator
    article, context = _quality_pair(session, "")
    source_id = "source:client Acme"
    context.sources = [EditorialSourceDescriptor(source_id=source_id,source_type="knowledge_file",label="Client Acme",reference="knowledge/client-acme.md",summary="Technical source record")]
    article.source_ids = [source_id]
    article.claims[0].source_ids = [source_id]
    article.body_html = '<div data-source="client Acme">'+article.body_html+'</div>'
    assert EditorialQualityValidator().validate(article, context).passed


@pytest.mark.parametrize("documented", [True, False])
def test_named_reference_needs_explicit_authorization_and_verified_matching_sources(session, documented):
    from app.application.models.editorial_v1 import AuthorizedClientReference, EditorialSourceDescriptor
    from app.application.services.editorial_engine_v1 import EditorialQualityValidator
    article, context = _quality_pair(session, "Chez Globex, nous avons accompagne le cadrage.")
    source_id = "knowledge:authorized-reference:globex"
    context.sources.append(EditorialSourceDescriptor(source_id=source_id,source_type="knowledge_file",label="Autorisation Globex",reference="knowledge/authorized-references/globex.md",summary="Autorisation de citer Globex et son projet de cadrage."))
    article.source_ids.append(source_id)
    article.claims[0].source_ids.append(source_id)
    ids = [source_id] if documented else ["unknown-authorization"]
    context.authorized_client_references = [AuthorizedClientReference(name="Globex",source_ids=ids)]
    article.claims[0].text = "Le cadrage chez Globex est documente."
    issues = EditorialQualityValidator().validate(article, context).issues
    assert any(issue.code == "unauthorized_client_reference" for issue in issues) is not documented


def test_client_reference_is_not_authorized_by_unrelated_knowledge_source(session):
    from app.application.models.editorial_v1 import AuthorizedClientReference
    from app.application.services.editorial_engine_v1 import EditorialQualityValidator
    article, context = _quality_pair(session, "Client Globex.")
    context.authorized_client_references = [AuthorizedClientReference(name="Globex",source_ids=article.source_ids)]
    article.claims[0].text = "Globex est un client."
    assert not EditorialQualityValidator().validate(article, context).passed


def test_fictional_testimonial_is_not_authorized_by_generated_claim_flags(session):
    from app.application.services.editorial_engine_v1 import EditorialQualityValidator
    article, context = _quality_pair(session, "Chez Acme, nous avons deploye un ERP.")
    article.claims[0].text = "Acme recommande notre realisation."
    article.claims[0].verified = True
    assert not EditorialQualityValidator().validate(article, context).passed


class RewriteFailingBackend(FakeStructuredAgentBackend):
    def run_structured(self, **kwargs):
        if kwargs["agent_name"] == "EditorialArticleRewriteAgent":
            self.calls.append({"agent_name": kwargs["agent_name"]})
            raise TimeoutError("rewrite timeout")
        return super().run_structured(**kwargs)


def _seed_recent_product_change(session, *, collected_at: datetime | None = None, summary: str = "Export du tableau utilisateur") -> None:
    from tests.support_sources import ensure_repository_source
    ensure_repository_source(session,'source-1','oling-mapsi/mapsi-v6')
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
    text = body_text or "Cet article explique un sujet prouve, ses usages et ses bonnes pratiques sans promesse excessive. " * 18
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


def _rewrite_pair(payload: dict) -> list[dict]:
    return [payload, payload]


def test_generate_mapsi_recent_novelty_persists_draft(session) -> None:
    _seed_recent_product_change(session)
    backend = FakeStructuredAgentBackend(_rewrite_pair(_article_payload(topic="Export des indicateurs du tableau utilisateur", article_type="MAPSI_PRODUCT", source_ids=["knowledge:mapsi:feature:dashboard-indicators-export", "product_change:pc-1"])), provider_type="openai")
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
    backend = FakeStructuredAgentBackend(_rewrite_pair(_article_payload(topic="Export des indicateurs du tableau utilisateur", article_type="MAPSI_PRODUCT", source_ids=["knowledge:mapsi:feature:dashboard-indicators-export", "product_change:pc-1"], body_text="Export des indicateurs du tableau utilisateur et usages. " * 8)), provider_type="openai")
    service = build_editorial_generation_service(session, force_mode="shadow")
    service.generator = OpenAIEditorialGenerator(backend)

    with pytest.raises(EditorialGenerationBlockedError, match="content_too_similar"):
        service.generate_mapsi(destination="mapsi", persist=False)


def test_generate_oling_practice_works(session) -> None:
    backend = FakeStructuredAgentBackend(_rewrite_pair(_article_payload(topic="ERP", article_type="OLING_PRACTICE", source_ids=["knowledge:oling:practice:erp", "knowledge:oling:profile"])), provider_type="openai")
    service = build_editorial_generation_service(session, force_mode="shadow")
    service.generator = OpenAIEditorialGenerator(backend)

    record = service.generate_oling(practice_id="erp", persist=False)

    assert record.article.article_type == "OLING_PRACTICE"
    assert record.quality.passed is True


def test_article_prompt_is_distinct_between_mapsi_site_and_oling_site(session) -> None:
    _seed_recent_product_change(session)
    backend = FakeStructuredAgentBackend([], provider_type="openai")
    service = build_editorial_generation_service(session, force_mode="shadow")
    generator = OpenAIEditorialGenerator(backend)
    service.generator = generator

    mapsi_prompt = generator._build_prompt(service._build_mapsi_context(article_type="MAPSI_PRODUCT", destination="mapsi"))
    consulting_prompt = generator._build_prompt(service._build_mapsi_context(article_type="MAPSI_CONSULTING", destination="oling"))
    oling_prompt = generator._build_prompt(service._build_oling_context(practice_id="rgpd-et-dpo"))

    assert "Canal article: mapsi_site" in mapsi_prompt
    assert "publication MAPSI.fr" in mapsi_prompt
    assert "Canal article: oling_site" in consulting_prompt
    assert "publication Oling.fr" in consulting_prompt
    assert "article de cabinet sur une pratique OLING" in oling_prompt
    rewrite_prompt = generator._build_rewrite_prompt(service._build_mapsi_context(article_type="MAPSI_PRODUCT", destination="mapsi"))
    assert "EditorialArticleRewriteAgent" in rewrite_prompt
    assert "Voix finale: editorial produit premium" in rewrite_prompt


def test_generate_blocks_claim_without_valid_source(session) -> None:
    _seed_recent_product_change(session)
    payload = _article_payload(topic="Export des indicateurs du tableau utilisateur", article_type="MAPSI_PRODUCT", source_ids=["knowledge:mapsi:feature:dashboard-indicators-export"])
    payload["claims"][0]["source_ids"] = ["unknown-source"]
    backend = FakeStructuredAgentBackend(_rewrite_pair(payload), provider_type="openai")
    service = build_editorial_generation_service(session, force_mode="real")
    service.generator = OpenAIEditorialGenerator(backend)

    with pytest.raises(EditorialGenerationBlockedError, match="claim_unknown_source"):
        service.generate_mapsi(destination="mapsi", persist=False)


def test_generate_blocks_invented_client_reference(session) -> None:
    _seed_recent_product_change(session)
    payload = _article_payload(topic="Export des indicateurs du tableau utilisateur", article_type="MAPSI_PRODUCT", source_ids=["knowledge:mapsi:feature:dashboard-indicators-export", "product_change:pc-1"], body_text="Chez Acme, cette fonctionnalite change tout. " * 8)
    backend = FakeStructuredAgentBackend(_rewrite_pair(payload), provider_type="openai")
    service = build_editorial_generation_service(session, force_mode="real")
    service.generator = OpenAIEditorialGenerator(backend)

    with pytest.raises(EditorialGenerationBlockedError, match="unauthorized_client_reference"):
        service.generate_mapsi(destination="oling", persist=False)


def test_generate_blocks_unverified_claim(session) -> None:
    _seed_recent_product_change(session)
    backend = FakeStructuredAgentBackend(_rewrite_pair(_article_payload(topic="Export des indicateurs du tableau utilisateur", article_type="MAPSI_PRODUCT", source_ids=["knowledge:mapsi:feature:dashboard-indicators-export", "product_change:pc-1"], claim_verified=False)), provider_type="openai")
    service = build_editorial_generation_service(session, force_mode="shadow")
    service.generator = OpenAIEditorialGenerator(backend)

    with pytest.raises(EditorialGenerationBlockedError, match="unverified_claim"):
        service.generate_mapsi(destination="mapsi", persist=False)


def test_generate_blocks_source_insufficient(session) -> None:
    _seed_recent_product_change(session)
    payload = _article_payload(topic="Export des indicateurs du tableau utilisateur", article_type="MAPSI_PRODUCT", source_ids=[])
    payload["claims"] = []
    backend = FakeStructuredAgentBackend(_rewrite_pair(payload), provider_type="openai")
    service = build_editorial_generation_service(session, force_mode="real")
    service.generator = OpenAIEditorialGenerator(backend)

    with pytest.raises(EditorialGenerationBlockedError, match="missing_sources"):
        service.generate_mapsi(destination="mapsi", persist=False)


def test_similarity_checks_against_existing_article_assets(session) -> None:
    from app.domain.entities import CampaignRun
    from app.infrastructure.repositories.campaigns import SqlAlchemyCampaignRepository
    SqlAlchemyCampaignRepository(session).add(CampaignRun(id='campaign-1',name='Synthetic history',campaign_type='MAPSI_MARKETING'))
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
    backend = FakeStructuredAgentBackend(_rewrite_pair(_article_payload(topic="Export des indicateurs du tableau utilisateur", article_type="MAPSI_PRODUCT", source_ids=["knowledge:mapsi:feature:dashboard-indicators-export", "product_change:pc-1"], body_text="Export des indicateurs du tableau utilisateur et usages. " * 8)), provider_type="openai")
    service = build_editorial_generation_service(session, force_mode="real")
    service.generator = OpenAIEditorialGenerator(backend)

    with pytest.raises(EditorialGenerationBlockedError, match="content_too_similar"):
        service.generate_mapsi(destination="mapsi", persist=False)


def test_generate_articles_uses_two_openai_passes(session) -> None:
    _seed_recent_product_change(session)
    payload = _article_payload(
        topic="Export des indicateurs du tableau utilisateur",
        article_type="MAPSI_PRODUCT",
        source_ids=["knowledge:mapsi:feature:dashboard-indicators-export", "product_change:pc-1"],
    )
    backend = FakeStructuredAgentBackend(_rewrite_pair(payload), provider_type="openai")
    service = build_editorial_generation_service(session, force_mode="real")
    service.generator = OpenAIEditorialGenerator(backend)

    service.generate_mapsi(destination="mapsi", persist=False)

    assert [call["agent_name"] for call in backend.calls] == [
        "EditorialArticleGenerator",
        "EditorialArticleRewriteAgent",
    ]


def test_generate_articles_keeps_draft_when_rewrite_times_out(session) -> None:
    _seed_recent_product_change(session)
    payload = _article_payload(
        topic="Export des indicateurs du tableau utilisateur",
        article_type="MAPSI_PRODUCT",
        source_ids=["knowledge:mapsi:feature:dashboard-indicators-export", "product_change:pc-1"],
    )
    backend = RewriteFailingBackend([payload], provider_type="openai")
    service = build_editorial_generation_service(session, force_mode="real")
    service.generator = OpenAIEditorialGenerator(backend)

    record = service.generate_mapsi(destination="mapsi", persist=False)

    assert record.article.title == payload["title"]
    assert [call["agent_name"] for call in backend.calls] == [
        "EditorialArticleGenerator",
        "EditorialArticleRewriteAgent",
    ]
