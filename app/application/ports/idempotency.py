from abc import ABC, abstractmethod


class IdempotencyStorePort(ABC):
    @abstractmethod
    def get(self, method: str, path: str, key: str) -> dict | None:
        raise NotImplementedError

    @abstractmethod
    def save(
        self,
        method: str,
        path: str,
        key: str,
        request_fingerprint: str,
        response_status: int,
        response_body: dict,
    ) -> None:
        raise NotImplementedError
