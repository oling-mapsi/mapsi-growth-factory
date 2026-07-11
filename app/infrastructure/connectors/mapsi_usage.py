from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

from app.generated.mapsi_contract_client import MapsiContractClient
from app.generated.mapsi_contract_models import CapabilitySnapshot, ContactSnapshotPage, HealthStatus, UsageSnapshotPage


def default_secret_resolver(secret_ref: str) -> str:
    key = secret_ref.replace("vault://", "").replace("/", "__").replace("-", "_").upper()
    env_name = f"SECRET__{key}"
    value = os.getenv(env_name)
    if not value:
        raise RuntimeError(f"Missing secret for {secret_ref} via {env_name}.")
    return value


@dataclass
class MapsiInstanceConfig:
    id: str
    base_url: str
    secret_ref: str
    enabled: bool


class MapsiUsageConnector:
    def __init__(
        self,
        instance: MapsiInstanceConfig,
        secret_resolver: Callable[[str], str] = default_secret_resolver,
        client_factory: Callable[..., MapsiContractClient] = MapsiContractClient,
    ) -> None:
        self.instance = instance
        token = secret_resolver(instance.secret_ref)
        self.client = client_factory(
            instance.base_url,
            headers={"Authorization": f"Bearer {token}"},
        )

    def health(self) -> HealthStatus:
        return self.client.get_health()

    def capabilities(self) -> CapabilitySnapshot:
        return self.client.get_capabilities()

    def usage_page(self, cursor: str | None = None, page_size: int = 100) -> UsageSnapshotPage:
        return self.client.get_usage_snapshot(cursor=cursor, page_size=page_size)

    def contact_page(self, cursor: str | None = None, page_size: int = 100) -> ContactSnapshotPage:
        return self.client.get_contact_snapshot(cursor=cursor, page_size=page_size)
