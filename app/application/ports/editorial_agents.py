from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel

OutputModelT = TypeVar("OutputModelT", bound=BaseModel)


class StructuredAgentBackendPort(ABC):
    @abstractmethod
    def run_structured(
        self,
        *,
        agent_name: str,
        prompt: str,
        input_model: BaseModel,
        output_type: type[OutputModelT],
        model_name: str,
        prompt_version: str,
        temperature: float,
    ) -> OutputModelT:
        raise NotImplementedError
