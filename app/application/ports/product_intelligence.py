from abc import ABC, abstractmethod

from app.domain.entities import ProductChange, RepositoryCursor, RepositorySource, SourceEvidence, WebhookDelivery


class RepositorySourceRepositoryPort(ABC):
    @abstractmethod
    def get_or_create(self, full_name: str, installation_id: str, default_branch: str) -> RepositorySource:
        raise NotImplementedError

    @abstractmethod
    def list_all(self) -> list[RepositorySource]:
        raise NotImplementedError


class RepositoryCursorRepositoryPort(ABC):
    @abstractmethod
    def upsert(self, source_id: str, cursor_type: str, last_seen_sha: str, last_delivery_id: str) -> RepositoryCursor:
        raise NotImplementedError

    @abstractmethod
    def get(self, source_id: str, cursor_type: str) -> RepositoryCursor | None:
        raise NotImplementedError


class ProductChangeRepositoryPort(ABC):
    @abstractmethod
    def save_many(self, changes: list[ProductChange]) -> list[ProductChange]:
        raise NotImplementedError


class SourceEvidenceRepositoryPort(ABC):
    @abstractmethod
    def save_many(self, evidences: list[SourceEvidence]) -> list[SourceEvidence]:
        raise NotImplementedError


class WebhookDeliveryRepositoryPort(ABC):
    @abstractmethod
    def create_if_absent(self, delivery: WebhookDelivery) -> tuple[WebhookDelivery, bool]:
        raise NotImplementedError

    @abstractmethod
    def mark(self, delivery_id: str, status: str, processed: bool, signature_valid: bool) -> None:
        raise NotImplementedError
