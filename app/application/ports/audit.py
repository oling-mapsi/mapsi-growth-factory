from abc import ABC, abstractmethod


class AuditLogPort(ABC):
    @abstractmethod
    def append(self, aggregate_id: str, event_type: str, payload: dict) -> None:
        raise NotImplementedError
