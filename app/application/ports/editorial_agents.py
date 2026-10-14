from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import BaseModel

from app.application.models.editorial_agents import EditorialExecutionMetadata

OutputModelT = TypeVar("OutputModelT", bound=BaseModel)


@dataclass(slots=True)
class EditorialRunResult(Generic[OutputModelT]):
    output: OutputModelT
    metadata: EditorialExecutionMetadata


class EditorialProvider(ABC):
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
    ) -> EditorialRunResult[OutputModelT]:
        raise NotImplementedError


StructuredAgentBackendPort = EditorialProvider
