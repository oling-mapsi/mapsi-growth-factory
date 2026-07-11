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
