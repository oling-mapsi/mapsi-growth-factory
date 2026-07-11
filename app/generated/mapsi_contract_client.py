from __future__ import annotations

from httpx import Client

from app.generated.mapsi_contract_models import (
    CapabilitySnapshot,
    ContactSnapshotPage,
    HealthStatus,
    ProductChangeCollection,
    UsageSnapshotPage,
)


class MapsiContractClient:
    def __init__(self, base_url: str, timeout: float = 10.0, headers: dict[str, str] | None = None) -> None:
        self.client = Client(base_url=base_url.rstrip("/"), timeout=timeout, headers=headers or {})

    def get_health(self) -> HealthStatus:
        response = self.client.get("/health")
        response.raise_for_status()
        return HealthStatus.model_validate(response.json())

    def get_capabilities(self) -> CapabilitySnapshot:
        response = self.client.get("/internal/growth/capabilities")
        response.raise_for_status()
        return CapabilitySnapshot.model_validate(response.json())

    def get_usage_snapshot(self, cursor: str | None = None, page_size: int = 100) -> UsageSnapshotPage:
        params = {"page_size": page_size}
        if cursor:
            params["cursor"] = cursor
        response = self.client.get("/internal/growth/usage-snapshot", params=params)
        response.raise_for_status()
        return UsageSnapshotPage.model_validate(response.json())

    def get_contact_snapshot(self, cursor: str | None = None, page_size: int = 100) -> ContactSnapshotPage:
        params = {"page_size": page_size}
        if cursor:
            params["cursor"] = cursor
        response = self.client.get("/internal/growth/contact-snapshot", params=params)
        response.raise_for_status()
        return ContactSnapshotPage.model_validate(response.json())

    def get_product_changes(self) -> ProductChangeCollection:
        response = self.client.get("/internal/growth/product-changes")
        response.raise_for_status()
        return ProductChangeCollection.model_validate(response.json())
