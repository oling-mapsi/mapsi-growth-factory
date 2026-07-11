from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel

from app.application.models.editorial_agents import (
    CustomerEmailWriterInput,
    CustomerEmailWriterOutput,
    EditorialStrategyInput,
    EditorialStrategyOutput,
    LinkedInWriterInput,
    LinkedInWriterOutput,
    MarketEditorialStrategyInput,
    MarketEditorialStrategyOutput,
    ProductIntelligenceInput,
    ProductIntelligenceOutput,
    QualityControlInput,
    QualityControlOutput,
    SeoQualityInput,
    SeoQualityOutput,
    NewsletterWriterInput,
    NewsletterWriterOutput,
    UsageIntelligenceInput,
    UsageIntelligenceOutput,
    WebsiteArticleWriterInput,
    WebsiteArticleWriterOutput,
)
from app.application.ports.editorial_agents import OutputModelT, StructuredAgentBackendPort
from app.core.config import get_settings

ROOT = Path(__file__).resolve().parents[3]
PROMPTS_ROOT = ROOT / "prompts"


class PromptedStructuredAgent:
    agent_name = "Agent"
    prompt_dir = ""
    prompt_version = "v1"
    output_type: type[BaseModel]

    def __init__(self, backend: StructuredAgentBackendPort) -> None:
        self.backend = backend
        settings = get_settings()
        self.model_name = settings.editorial_agent_model
        self.temperature = settings.editorial_agent_temperature

    def run(self, input_model: BaseModel) -> OutputModelT:
        prompt = (PROMPTS_ROOT / self.prompt_dir / f"{self.prompt_version}.txt").read_text(encoding="utf-8")
        return self.backend.run_structured(
            agent_name=self.agent_name,
            prompt=prompt,
            input_model=input_model,
            output_type=self.output_type,  # type: ignore[arg-type]
            model_name=self.model_name,
            prompt_version=self.prompt_version,
            temperature=self.temperature,
        )


class ProductIntelligenceAgent(PromptedStructuredAgent):
    agent_name = "ProductIntelligenceAgent"
    prompt_dir = "product-intelligence-agent"
    output_type = ProductIntelligenceOutput


class UsageIntelligenceAgent(PromptedStructuredAgent):
    agent_name = "UsageIntelligenceAgent"
    prompt_dir = "usage-intelligence-agent"
    output_type = UsageIntelligenceOutput


class EditorialStrategyAgent(PromptedStructuredAgent):
    agent_name = "EditorialStrategyAgent"
    prompt_dir = "editorial-strategy-agent"
    output_type = EditorialStrategyOutput


class CustomerEmailWriterAgent(PromptedStructuredAgent):
    agent_name = "CustomerEmailWriterAgent"
    prompt_dir = "customer-email-writer-agent"
    output_type = CustomerEmailWriterOutput


class QualityControlAgent(PromptedStructuredAgent):
    agent_name = "QualityControlAgent"
    prompt_dir = "quality-control-agent"
    output_type = QualityControlOutput


class MarketEditorialStrategyAgent(PromptedStructuredAgent):
    agent_name = "MarketEditorialStrategyAgent"
    prompt_dir = "market-editorial-strategy-agent"
    output_type = MarketEditorialStrategyOutput


class NewsletterWriterAgent(PromptedStructuredAgent):
    agent_name = "NewsletterWriterAgent"
    prompt_dir = "newsletter-writer-agent"
    output_type = NewsletterWriterOutput


class LinkedInWriterAgent(PromptedStructuredAgent):
    agent_name = "LinkedInWriterAgent"
    prompt_dir = "linkedin-writer-agent"
    output_type = LinkedInWriterOutput


class WebsiteArticleWriterAgent(PromptedStructuredAgent):
    agent_name = "WebsiteArticleWriterAgent"
    prompt_dir = "website-article-writer-agent"
    output_type = WebsiteArticleWriterOutput


class SeoQualityAgent(PromptedStructuredAgent):
    agent_name = "SeoQualityAgent"
    prompt_dir = "seo-quality-agent"
    output_type = SeoQualityOutput


def contains_pii(payload: dict) -> bool:
    text = str(payload)
    return bool(re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text, flags=re.IGNORECASE))
