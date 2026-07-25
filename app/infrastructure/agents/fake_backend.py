from __future__ import annotations

from collections import deque
from typing import Any

from pydantic import BaseModel

from app.application.models.editorial_agents import EditorialExecutionMetadata, EditorialTokenUsage
from app.application.ports.editorial_agents import EditorialRunResult, OutputModelT, StructuredAgentBackendPort


class FakeStructuredAgentBackend(StructuredAgentBackendPort):
    def __init__(self, responses: list[dict[str, Any]], *, provider_type: str = "fake") -> None:
        self.responses = deque(responses)
        self.calls: list[dict[str, Any]] = []
        self.provider_type = provider_type

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
        self.calls.append(
            {
                "agent_name": agent_name,
                "prompt": prompt,
                "input": input_model.model_dump(mode="json"),
                "model_name": model_name,
                "prompt_version": prompt_version,
                "temperature": temperature,
            }
        )
        payload = self.responses.popleft()
        output = output_type.model_validate(payload)
        return EditorialRunResult(
            output=output,
            metadata=EditorialExecutionMetadata(
                agent_name=agent_name,
                provider_type=self.provider_type,  # type: ignore[arg-type]
                model_name=model_name,
                prompt_version=prompt_version,
                schema_name=output_type.__name__,
                execution_params={"temperature": temperature},
                token_usage=EditorialTokenUsage(input_tokens=1, output_tokens=1, total_tokens=2),
            ),
        )
