from __future__ import annotations

import json

from pydantic import BaseModel

from app.application.models.editorial_agents import EditorialExecutionMetadata, EditorialTokenUsage
from app.application.ports.editorial_agents import EditorialRunResult, OutputModelT, StructuredAgentBackendPort


class OpenAIAgentsBackend(StructuredAgentBackendPort):
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
        try:
            from agents import Agent, ModelSettings, Runner
        except ImportError as exc:
            raise RuntimeError("OpenAI Agents SDK is not installed.") from exc
        agent = Agent(
            name=agent_name,
            instructions=prompt,
            output_type=output_type,
            model=model_name,
            model_settings=ModelSettings(temperature=temperature),
        )
        result = Runner.run_sync(agent, input=input_model.model_dump_json())
        output = output_type.model_validate(result.final_output)
        usage = getattr(result, "usage", None)
        if usage is None:
            token_usage = self._estimate_usage(prompt=prompt, input_model=input_model, output=output.model_dump(mode="json"))
        else:
            input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
            output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
            token_usage = EditorialTokenUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
            )
        return EditorialRunResult(
            output=output,
            metadata=EditorialExecutionMetadata(
                agent_name=agent_name,
                provider_type="openai",
                model_name=model_name,
                prompt_version=prompt_version,
                schema_name=output_type.__name__,
                execution_params={"temperature": temperature},
                token_usage=token_usage,
            ),
        )

    def _estimate_usage(self, *, prompt: str, input_model: BaseModel, output: dict) -> EditorialTokenUsage:
        input_tokens = self._estimate_tokens(prompt) + self._estimate_tokens(input_model.model_dump(mode="json"))
        output_tokens = self._estimate_tokens(output)
        return EditorialTokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        )

    def _estimate_tokens(self, value) -> int:
        serialized = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        return max(1, len(serialized) // 4)
