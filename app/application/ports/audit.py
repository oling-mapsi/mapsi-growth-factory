from abc import ABC, abstractmethod


class AuditLogPort(ABC):
    @abstractmethod
    def append(
        self,
        aggregate_id: str | None,
        event_type: str,
        payload: dict,
        *,
        asset_id: str = "",
        actor_id: str = "",
        actor_source: str = "system",
        actor_roles: list[str] | None = None,
        correlation_id: str = "",
        idempotency_key: str = "",
        previous_state: dict | None = None,
        new_state: dict | None = None,
        channel: str = "",
        result: str = "",
        source_ip: str = "",
    ) -> None:
        raise NotImplementedError
