from __future__ import annotations

from app.application.services.mapsi_product_changes_service import MapsiProductChangesService
from app.generated.mapsi_contract_models import ProductChange, ProductChangeCollection
from app.infrastructure.db.models import ProductChangeModel, RepositorySourceModel, SourceEvidenceModel
from app.infrastructure.repositories.product_intelligence import (
    SqlAlchemyProductChangeRepository,
    SqlAlchemyRepositorySourceRepository,
    SqlAlchemySourceEvidenceRepository,
)


class FakeMapsiProductChangesConnector:
    def __init__(self, payload: ProductChangeCollection) -> None:
        self.payload = payload

    def get_product_changes(self) -> ProductChangeCollection:
        return self.payload


def make_payload(version: str = "1.0.0") -> ProductChangeCollection:
    return ProductChangeCollection(
        contract_version=version,
        generated_at="2026-07-11T15:00:00+00:00",
        items=[
            ProductChange(
                id="MAPSI-2026-010",
                title="Export des indicateurs du tableau utilisateur",
                summary="Les responsables peuvent exporter les indicateurs visibles depuis le tableau utilisateur sans retraitement manuel.",
                url="https://github.com/oling-mapsi/mapsi-v6/pull/2101",
                published_at="2026-07-01T00:00:00Z",
                tags=["product", "release", "dashboard"],
                communicable=True,
            )
        ],
    )


def build_service(session, payload: ProductChangeCollection) -> MapsiProductChangesService:
    return MapsiProductChangesService(
        connector=FakeMapsiProductChangesConnector(payload),
        repository_sources=SqlAlchemyRepositorySourceRepository(session),
        product_changes=SqlAlchemyProductChangeRepository(session),
        source_evidences=SqlAlchemySourceEvidenceRepository(session),
        repository_full_name="oling-mapsi/mapsi-v6",
        default_branch="master",
    )


def test_collect_product_changes_persists_contract_items(session) -> None:
    service = build_service(session, make_payload())

    count = service.collect(dry_run=False)

    assert count == 1
    source = session.query(RepositorySourceModel).one()
    change = session.query(ProductChangeModel).one()
    evidence = session.query(SourceEvidenceModel).one()
    assert source.full_name == "oling-mapsi/mapsi-v6"
    assert change.repository_source_id == source.id
    assert change.sha == "MAPSI-2026-010"
    assert change.capability_key == "MAPSI-2026-010"
    assert change.eligible_for_communication is True
    assert change.deployment_proven is True
    assert change.pr_number == 2101
    assert evidence.source_system == "mapsi-v6"
    assert evidence.reference == "https://github.com/oling-mapsi/mapsi-v6/pull/2101"
    assert evidence.campaign_run_id is None


def test_collect_product_changes_is_idempotent_with_stable_ids(session) -> None:
    service = build_service(session, make_payload())

    first = service.collect(dry_run=False)
    second = service.collect(dry_run=False)

    assert first == 1
    assert second == 1
    assert session.query(ProductChangeModel).count() == 1
    assert session.query(SourceEvidenceModel).count() == 1


def test_collect_product_changes_rejects_incompatible_contract_version(session) -> None:
    service = build_service(session, make_payload(version="2.0.0"))

    try:
        service.collect(dry_run=False)
    except RuntimeError as exc:
        assert "Incompatible MAPSI product changes contract version 2.0.0." == str(exc)
    else:
        raise AssertionError("Incompatible contract version was not rejected.")


def test_collect_product_changes_accepts_prod_payload_shape(session) -> None:
    payload = ProductChangeCollection.model_validate(
        {
            "contract_version": "1.0.0",
            "generated_at": "2026-07-11T16:35:46-04:00",
            "items": [
                {
                    "id": "MAPSI-2026-000",
                    "title": "Export synthetique des activites Courbex",
                    "module": "courbex",
                    "status": "production",
                    "audiences": ["manager", "administrator"],
                    "user_value": "L utilisateur peut exporter un resume d activite Courbex.",
                    "functional_description": "Un export dedie est disponible.",
                    "availability": {"type": "all_customers"},
                    "feature_flag": None,
                    "minimum_version": "6.18.0",
                    "deployed_at": None,
                    "evidence": {"pull_request": 1842, "issue": 1720, "commit_sha": "301f950460747537677859e945900dd8cfb94caf"},
                }
            ],
        }
    )
    service = build_service(session, payload)

    count = service.collect(dry_run=False)

    assert count == 1
    change = session.query(ProductChangeModel).one()
    evidence = session.query(SourceEvidenceModel).one()
    assert change.summary == "L utilisateur peut exporter un resume d activite Courbex."
    assert change.pr_number == 1842
    assert change.eligible_for_communication is True
    assert evidence.reference == "https://github.com/oling-mapsi/mapsi-v6/pull/1842"
    assert evidence.campaign_run_id is None
