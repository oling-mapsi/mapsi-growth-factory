from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.application.services.audience_segmentation_service import AudienceSegmentationService
from app.application.services.mapsi_user_weekly_email_builder import MapsiUserWeeklyEmailBuilder
from app.core.security import encrypt_contact_value
from app.domain.entities import FeatureCommunicationCatalogEntry, ProductChange, SourceEvidence
from app.infrastructure.db.models import EditorialThemeHistoryModel
from app.infrastructure.repositories.audience_segments import AudienceSegmentationRepository
from app.infrastructure.repositories.editorial_pipeline import EditorialPipelineRepository
from app.infrastructure.repositories.feature_communication_catalog import FeatureCommunicationCatalogRepository
from app.infrastructure.repositories.mapsi_usage import MapsiUsageRepository
from app.infrastructure.repositories.product_intelligence import SqlAlchemyProductChangeRepository, SqlAlchemySourceEvidenceRepository


def _seed_membership(session, *, instance_key: str, external_user_id: str, role_key: str, modules: dict[str, int], active: bool = True, last_activity_days: int = 3) -> None:
    repository = MapsiUsageRepository(session)
    instance = repository.upsert_instance(
        instance_key=instance_key,
        base_url=f"https://{instance_key}.example",
        secret_ref=f"vault://mapsi/{instance_key}/token",
        enabled=True,
        contract_version="1.3.0",
    )
    account = repository.upsert_customer_account(instance.id, f"tenant-{instance_key}")
    identity = repository.upsert_contact_identity(
        f"hash:{instance_key}:{external_user_id}",
        encrypt_contact_value(f"{external_user_id}@example.test"),
        True,
    )
    membership = repository.upsert_contact_membership(
        contact_identity_id=identity.id,
        customer_account_id=account.id,
        external_user_id=external_user_id,
        role_key=role_key,
        active=active,
        communication_eligible=True,
        opted_out=False,
        last_activity_at=datetime.now(UTC) - timedelta(days=last_activity_days),
    )
    snapshot = repository.create_snapshot_if_absent(instance.id, "usage", f"{external_user_id}:usage", "1.3.0", datetime.now(UTC))
    for module_key, events in modules.items():
        repository.upsert_feature_adoption(snapshot.id, membership.id, module_key, events)
        repository.upsert_capability(instance.id, module_key, True, "1.3.0")


def _builder(session) -> MapsiUserWeeklyEmailBuilder:
    return MapsiUserWeeklyEmailBuilder(
        editorial_repository=EditorialPipelineRepository(session),
        catalog_repository=FeatureCommunicationCatalogRepository(session),
        segmentation_service=AudienceSegmentationService(AudienceSegmentationRepository(session)),
        mapsi_usage_repository=MapsiUsageRepository(session),
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


def test_mapsi_users_builder_selects_available_product_change(session) -> None:
    _seed_membership(session, instance_key="gpmlm", external_user_id="u1", role_key="administrator", modules={"planning": 3})
    _seed_product_change(session, capability_key="planning", summary="Nouveau pilotage simplifie dans le module planning")

    result = _builder(session).build(fallback_evidence_ids=["fallback-evidence"])

    assert result.content.email_type == "NEW_FEATURE"
    assert result.content.target_segment_id == "all_eligible_active_users"
    assert "Nouvelle fonctionnalite MAPSI" in result.content.subject
    assert result.content.source_evidence_ids
    assert all(item["passed"] for item in result.evaluations.values())


def test_mapsi_users_builder_falls_back_to_catalog(session) -> None:
    _seed_membership(session, instance_key="gpmlm", external_user_id="u1", role_key="risk_manager", modules={"risk": 2})
    FeatureCommunicationCatalogRepository(session).save(
        FeatureCommunicationCatalogEntry(
            feature_id="risk-workflow-tip",
            module="risk",
            title="Mieux suivre votre workflow risque",
            functional_description="Le module risque aide a structurer une revue simple chaque semaine.",
            user_benefit="Garder une revue plus reguliere des risques.",
            target_roles=["risk_manager"],
            target_modules=["risk"],
            minimum_version="1.0.0",
            availability="targeted",
            deep_link_template="https://{instance_key}.example/risk",
            communication_priority=10,
            minimum_repeat_delay=21,
            source_evidence_ids=["catalog:risk"],
            enabled=True,
        )
    )

    result = _builder(session).build(fallback_evidence_ids=["fallback-evidence"])

    assert result.content.email_type == "FEATURE_REMINDER"
    assert result.content.title == "Mieux suivre votre workflow risque"
    assert result.content.deep_link == "https://gpmlm.example/risk"
    assert result.content.target_segment_id == "risk_managers"


def test_mapsi_users_builder_skips_recent_catalog_topic(session) -> None:
    _seed_membership(session, instance_key="gpmlm", external_user_id="u1", role_key="quality_manager", modules={"quality": 1})
    repository = FeatureCommunicationCatalogRepository(session)
    repository.save(
        FeatureCommunicationCatalogEntry(
            feature_id="quality-recent",
            module="quality",
            title="Astuce qualite recente",
            functional_description="Recent",
            user_benefit="Recent",
            target_roles=["quality_manager"],
            target_modules=["quality"],
            last_communicated_at=datetime.now(UTC),
            minimum_repeat_delay=30,
            source_evidence_ids=["catalog:recent"],
            enabled=True,
        )
    )
    repository.save(
        FeatureCommunicationCatalogEntry(
            feature_id="quality-older",
            module="quality",
            title="Astuce qualite durable",
            functional_description="Older",
            user_benefit="Older",
            target_roles=["quality_manager"],
            target_modules=["quality"],
            communication_priority=20,
            source_evidence_ids=["catalog:older"],
            enabled=True,
        )
    )

    result = _builder(session).build(fallback_evidence_ids=["fallback-evidence"])

    assert result.content.title == "Astuce qualite durable"


def test_mapsi_users_builder_marks_pilot_mode_and_generic_preview(session) -> None:
    result = _builder(session).build(pilot_mode=True, fallback_evidence_ids=["fallback-a", "fallback-b"])

    assert result.content.email_type == "TIP"
    assert result.asset.results["pilot_allowlist_only"] is True
    assert result.asset.results["test_email"] is True
    assert result.asset.results["preview_html_available"] is True
    assert result.asset.results["preview_text_available"] is True
    assert result.content.subject.startswith("[PILOT]")


def test_mapsi_users_builder_skips_recent_product_theme(session) -> None:
    _seed_membership(session, instance_key="gpmlm", external_user_id="u1", role_key="administrator", modules={"planning": 3})
    _seed_product_change(session, capability_key="planning", summary="Nouveau pilotage simplifie dans le module planning")
    session.add(
        EditorialThemeHistoryModel(
            topic="planning Nouveau pilotage simplifie dans le module planning",
            objective="new_feature",
            audience_segment_id="all_eligible_active_users",
        )
    )
    session.commit()
    FeatureCommunicationCatalogRepository(session).save(
        FeatureCommunicationCatalogEntry(
            feature_id="planning-tip",
            module="planning",
            title="Rappel utile sur le module planning",
            functional_description="Un rappel simple sur l'usage de planning.",
            user_benefit="Retrouver plus vite vos reperes dans planning.",
            target_modules=["planning"],
            source_evidence_ids=["catalog:planning"],
            enabled=True,
        )
    )

    result = _builder(session).build(fallback_evidence_ids=["fallback-evidence"])

    assert result.content.email_type != "NEW_FEATURE"
