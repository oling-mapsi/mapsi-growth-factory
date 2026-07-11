from __future__ import annotations

from collections import deque
from typing import Any

from pydantic import BaseModel

from app.application.ports.editorial_agents import OutputModelT, StructuredAgentBackendPort


class FakeStructuredAgentBackend(StructuredAgentBackendPort):
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = deque(responses)
        self.calls: list[dict[str, Any]] = []

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
        return output_type.model_validate(payload)
