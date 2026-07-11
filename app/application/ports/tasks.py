from abc import ABC, abstractmethod


class TaskQueuePort(ABC):
    @abstractmethod
    def enqueue(self, task_name: str, payload: dict) -> str:
        raise NotImplementedError

    @abstractmethod
    def dequeue(self, timeout: int = 1) -> dict | None:
        raise NotImplementedError
