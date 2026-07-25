from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.application.services.audience_segmentation_service import AudienceSegmentationService
from app.application.services.editorial_agents import (
    CustomerEmailWriterAgent,
    EditorialStrategyAgent,
    ProductIntelligenceAgent,
    QualityControlAgent,
    UsageIntelligenceAgent,
)
from app.application.services.weekly_campaign_generation_service import WeeklyCampaignGenerationService
from app.core.security import encrypt_contact_value
from app.domain.entities import ProductChange, SourceEvidence
from app.domain.errors import EditorialGenerationBlockedError
from app.infrastructure.agents.fake_backend import FakeStructuredAgentBackend
from app.infrastructure.db.models import EditorialThemeHistoryModel, SourceEvidenceModel
from app.infrastructure.repositories.audience_segments import AudienceSegmentationRepository
from app.infrastructure.repositories.editorial_pipeline import EditorialPipelineRepository
from app.infrastructure.repositories.mapsi_usage import MapsiUsageRepository
from app.infrastructure.repositories.product_intelligence import SqlAlchemyProductChangeRepository, SqlAlchemySourceEvidenceRepository


def seed_segment_data(session) -> None:
    repository = MapsiUsageRepository(session)
    instance = repository.upsert_instance(
        instance_key="gpmlm",
        base_url="https://gpmlm.example",
        secret_ref="vault://mapsi/gpmlm/growth-token",
        enabled=True,
        contract_version="1.3.0",
    )
    account = repository.upsert_customer_account(instance.id, "tenant-a")
    identity = repository.upsert_contact_identity(
        "hash:segment",
        encrypt_contact_value("masked@example.test"),
        True,
    )
    membership = repository.upsert_contact_membership(
        contact_identity_id=identity.id,
        customer_account_id=account.id,
        external_user_id="u1",
        role_key="risk_manager",
        active=True,
        communication_eligible=True,
        opted_out=False,
        last_activity_at=datetime.now(UTC) - timedelta(days=3),
    )
    snapshot = repository.create_snapshot_if_absent(instance.id, "usage", "risk", "1.3.0", datetime.now(UTC))
    repository.upsert_feature_adoption(snapshot.id, membership.id, "risk", 1)


def seed_product_data(session) -> None:
    changes = SqlAlchemyProductChangeRepository(session)
    evidences = SqlAlchemySourceEvidenceRepository(session)
    change = ProductChange(
        repository_source_id="repo-1",
        repository_full_name="mapsi/mapsi-v6",
        sha="abc123",
        change_note_path="growth/change-notes/risk.yaml",
        capability_key="risk",
        summary="Creer un plan d'action depuis un risque",
        eligible_for_communication=True,
        confidential=False,
        target_client_key="",
        contract_version="1.0.0",
        production_status="production",
        deployment_proven=True,
    )
    changes.save_many([change])
    evidences.save_many(
        [
            SourceEvidence(
                product_change_id=change.id,
                source_system="github",
                evidence_type="deployment",
                reference="deploy:abc123",
                payload={"proof": "ok"},
            )
        ]
    )


def build_service(session, responses, *, provider_type: str = "fake") -> WeeklyCampaignGenerationService:
    backend = FakeStructuredAgentBackend(responses, provider_type=provider_type)
    segmentation = AudienceSegmentationService(AudienceSegmentationRepository(session))
    repository = EditorialPipelineRepository(session)
    return WeeklyCampaignGenerationService(
        product_agent=ProductIntelligenceAgent(backend),
        usage_agent=UsageIntelligenceAgent(backend),
        strategy_agent=EditorialStrategyAgent(backend),
        writer_agent=CustomerEmailWriterAgent(backend),
        quality_agent=QualityControlAgent(backend),
        segmentation_service=segmentation,
        repository=repository,
    )


def test_generate_weekly_campaign_dry_run(session) -> None:
    seed_segment_data(session)
    seed_product_data(session)
    real_evidence_id = session.query(SourceEvidenceModel).one().id
    service = build_service(
        session,
        [
            {
                "candidates": [
                    {
                        "capability_key": "risk",
                        "candidate_feature": "Creer un plan d'action depuis un risque",
                        "user_benefit": "Eviter la double saisie",
                        "evidence_ids": [real_evidence_id],
                        "restrictions": [],
                    }
                ]
            },
            {
                "recommendations": [
                    {
                        "segment_id": "risk_managers",
                        "usage_problem": "Les plans d'action sont peu ouverts.",
                        "education_opportunity": "Montrer le lien risque-action.",
                    }
                ]
            },
            {
                "topic": "Creer un plan d'action depuis un risque",
                "objective": "feature_adoption",
                "audience_segment_id": "risk_managers",
                "evidence_ids": [real_evidence_id],
                "key_messages": ["Eviter la double saisie", "Conserver le lien entre risque et action"],
                "cta_type": "open_feature",
            },
            {
                "subject": "Creer un plan d'action depuis un risque",
                "preheader": "Activez une pratique simple",
                "headline": "Creer un plan d'action depuis un risque",
                "introduction": "Un cas d'usage utile cette semaine.",
                "body_html": "<p>Un cas d'usage utile cette semaine.</p>",
                "body_text": "Un cas d'usage utile cette semaine.",
                "cta_label": "Ouvrir la fonctionnalite",
                "cta_url_template": "https://mapsi.example/risk",
                "evidence_ids": [real_evidence_id],
            },
            {"passed": True, "issues": []},
        ],
    )

    report = service.generate(dry_run=True)

    assert report["objective"] == "feature_adoption"
    assert report["audience_segment_id"] == "risk_managers"
    assert report["quality"]["passed"] is True
    assert report["evaluations"]["absence_of_personal_data"]["passed"] is True
    assert report["engine"]["consumption"]["used_tokens"] > 0
    assert service.repository.count_agent_logs() == 5


def test_generate_weekly_campaign_marks_real_mode_when_openai_provider_is_used(session) -> None:
    seed_segment_data(session)
    seed_product_data(session)
    evidence_id = session.query(SourceEvidenceModel).one().id
    service = build_service(
        session,
        [
            {
                "candidates": [
                    {
                        "capability_key": "risk",
                        "candidate_feature": "Creer un plan d'action depuis un risque",
                        "user_benefit": "Eviter la double saisie",
                        "evidence_ids": [evidence_id],
                        "restrictions": [],
                    }
                ]
            },
            {
                "recommendations": [
                    {
                        "segment_id": "risk_managers",
                        "usage_problem": "Les plans d'action sont peu ouverts.",
                        "education_opportunity": "Montrer le lien risque-action.",
                    }
                ]
            },
            {
                "topic": "Creer un plan d'action depuis un risque",
                "objective": "feature_adoption",
                "audience_segment_id": "risk_managers",
                "evidence_ids": [evidence_id],
                "key_messages": ["Eviter la double saisie", "Conserver le lien entre risque et action"],
                "cta_type": "open_feature",
            },
            {
                "subject": "Creer un plan d'action depuis un risque",
                "preheader": "Activez une pratique simple",
                "headline": "Creer un plan d'action depuis un risque",
                "introduction": "Un cas d'usage utile cette semaine.",
                "body_html": "<p>Un cas d'usage utile cette semaine.</p>",
                "body_text": "Un cas d'usage utile cette semaine.",
                "cta_label": "Ouvrir la fonctionnalite",
                "cta_url_template": "https://mapsi.example/risk",
                "evidence_ids": [evidence_id],
            },
            {"passed": True, "issues": []},
        ],
        provider_type="openai",
    )

    report = service.generate(dry_run=True)

    assert report["engine"]["mode"] == "real"


def test_generate_weekly_campaign_blocks_on_repeated_theme(session) -> None:
    seed_segment_data(session)
    seed_product_data(session)
    session.add(
        EditorialThemeHistoryModel(
            topic="Creer un plan d'action depuis un risque",
            objective="feature_adoption",
            audience_segment_id="risk_managers",
        )
    )
    session.commit()
    evidence_id = session.query(SourceEvidenceModel).one().id
    service = build_service(
        session,
        [
            {
                "candidates": [
                    {
                        "capability_key": "risk",
                        "candidate_feature": "Creer un plan d'action depuis un risque",
                        "user_benefit": "Eviter la double saisie",
                        "evidence_ids": [evidence_id],
                        "restrictions": [],
                    }
                ]
            },
            {
                "recommendations": [
                    {
                        "segment_id": "risk_managers",
                        "usage_problem": "Les plans d'action sont peu ouverts.",
                        "education_opportunity": "Montrer le lien risque-action.",
                    }
                ]
            },
            {
                "topic": "Creer un plan d'action depuis un risque",
                "objective": "feature_adoption",
                "audience_segment_id": "risk_managers",
                "evidence_ids": [evidence_id],
                "key_messages": ["Eviter la double saisie", "Conserver le lien entre risque et action"],
                "cta_type": "open_feature",
            },
        ],
    )

    with pytest.raises(EditorialGenerationBlockedError, match="repeats a recent theme"):
        service.generate(dry_run=True)


def test_generate_weekly_campaign_blocks_on_quality_failure(session) -> None:
    seed_segment_data(session)
    seed_product_data(session)
    evidence_id = session.query(SourceEvidenceModel).one().id
    service = build_service(
        session,
        [
            {
                "candidates": [
                    {
                        "capability_key": "risk",
                        "candidate_feature": "Creer un plan d'action depuis un risque",
                        "user_benefit": "Eviter la double saisie",
                        "evidence_ids": [evidence_id],
                        "restrictions": [],
                    }
                ]
            },
            {
                "recommendations": [
                    {
                        "segment_id": "risk_managers",
                        "usage_problem": "Les plans d'action sont peu ouverts.",
                        "education_opportunity": "Montrer le lien risque-action.",
                    }
                ]
            },
            {
                "topic": "Creer un plan d'action depuis un risque",
                "objective": "feature_adoption",
                "audience_segment_id": "risk_managers",
                "evidence_ids": [evidence_id],
                "key_messages": ["Eviter la double saisie", "Conserver le lien entre risque et action"],
                "cta_type": "open_feature",
            },
            {
                "subject": "Creer un plan d'action depuis un risque",
                "preheader": "Activez une pratique simple",
                "headline": "Creer un plan d'action depuis un risque",
                "introduction": "Un cas d'usage utile cette semaine.",
                "body_html": "<p>Un cas d'usage utile cette semaine.</p>",
                "body_text": "Un cas d'usage utile cette semaine.",
                "cta_label": "Ouvrir la fonctionnalite",
                "cta_url_template": "https://mapsi.example/risk",
                "evidence_ids": [evidence_id],
            },
            {
                "passed": False,
                "issues": [{"code": "unsupported_claim", "message": "Unsupported claim.", "severity": "error"}],
            },
        ],
    )

    with pytest.raises(EditorialGenerationBlockedError, match="Quality control failed"):
        service.generate(dry_run=True)
