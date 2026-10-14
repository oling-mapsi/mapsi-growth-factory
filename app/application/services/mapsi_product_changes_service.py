from __future__ import annotations

from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from app.application.ports.product_intelligence import (
    ProductChangeRepositoryPort,
    RepositorySourceRepositoryPort,
    SourceEvidenceRepositoryPort,
)
from app.generated.mapsi_contract_models import ProductChangeCollection
from app.domain.entities import ProductChange, SourceEvidence


@dataclass
class MapsiProductChangesConnectorPort:
    def get_product_changes(self) -> ProductChangeCollection:
        raise NotImplementedError


class MapsiProductChangesService:
    def __init__(
        self,
        *,
        connector: MapsiProductChangesConnectorPort,
        repository_sources: RepositorySourceRepositoryPort,
        product_changes: ProductChangeRepositoryPort,
        source_evidences: SourceEvidenceRepositoryPort,
        repository_full_name: str,
        default_branch: str,
    ) -> None:
        self.connector = connector
        self.repository_sources = repository_sources
        self.product_changes = product_changes
        self.source_evidences = source_evidences
        self.repository_full_name = repository_full_name
        self.default_branch = default_branch

    def collect(self, dry_run: bool = True) -> int:
        payload = self.connector.get_product_changes()
        if payload.contract_version.split(".", 1)[0] != "1":
            raise RuntimeError(f"Incompatible MAPSI product changes contract version {payload.contract_version}.")
        if dry_run:
            return len(payload.items)

        source = self.repository_sources.get_or_create(
            full_name=self.repository_full_name,
            installation_id="mapsi-growth-contract",
            default_branch=self.default_branch,
        )
        changes: list[ProductChange] = []
        evidences: list[SourceEvidence] = []
        for item in payload.items:
            summary = item.summary or item.user_value or item.functional_description or item.title
            communicable = item.communicable if item.communicable is not None else (item.status == "production")
            url = item.url or _build_github_url(self.repository_full_name, item.evidence)
            published_at = item.published_at or item.deployed_at
            tags = list(item.tags or [])
            for value in ("product", item.module, item.status, *(item.audiences or [])):
                if value and value not in tags:
                    tags.append(value)
            change_id = str(uuid5(NAMESPACE_URL, f"{self.repository_full_name}:{item.id}"))
            reference = url or item.id
            pr_number = _parse_pr_number(url)
            change = ProductChange(
                id=change_id,
                repository_source_id=source.id,
                repository_full_name=self.repository_full_name,
                sha=item.id,
                pr_number=pr_number,
                deployment_ref=published_at or "",
                production_status="production",
                change_note_path=f"api/internal/growth/v1/product-changes#{item.id}",
                eligible_for_communication=communicable,
                confidential=False,
                target_client_key="",
                capability_key=item.id,
                summary=summary,
                contract_version=payload.contract_version,
                deployment_proven=True,
                raw_payload={
                    **item.model_dump(mode="json"),
                    "generated_at": payload.generated_at,
                },
            )
            changes.append(change)
            evidences.append(
                SourceEvidence(
                    id=str(uuid5(NAMESPACE_URL, f"{change.id}:{reference}")),
                    product_change_id=change.id,
                    source_system="mapsi-v6",
                    evidence_type="product_change_contract",
                    reference=reference,
                    payload={
                        "title": item.title,
                        "url": url,
                        "published_at": published_at,
                        "tags": tags,
                    },
                )
            )
        self.product_changes.save_many(changes)
        self.source_evidences.save_many(evidences)
        return len(changes)


def _parse_pr_number(url: str | None) -> int | None:
    if not url or "/pull/" not in url:
        return None
    try:
        return int(url.rsplit("/pull/", 1)[1].split("/", 1)[0])
    except ValueError:
        return None


def _build_github_url(repository_full_name: str, evidence: dict | None) -> str | None:
    if not evidence:
        return None
    if evidence.get("pull_request"):
        return f"https://github.com/{repository_full_name}/pull/{evidence['pull_request']}"
    if evidence.get("issue"):
        return f"https://github.com/{repository_full_name}/issues/{evidence['issue']}"
    if evidence.get("commit_sha"):
        return f"https://github.com/{repository_full_name}/commit/{evidence['commit_sha']}"
    return None
