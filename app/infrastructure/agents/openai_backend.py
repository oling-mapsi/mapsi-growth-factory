from __future__ import annotations

from pydantic import BaseModel

from app.application.ports.editorial_agents import OutputModelT, StructuredAgentBackendPort


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
    ) -> OutputModelT:
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
        return output_type.model_validate(result.final_output)
