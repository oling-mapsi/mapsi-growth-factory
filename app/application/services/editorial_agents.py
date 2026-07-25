from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel

from app.application.models.editorial_agents import (
    EditorialExecutionMetadata,
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
from app.application.ports.editorial_agents import EditorialProvider, OutputModelT
from app.core.config import get_settings

ROOT = Path(__file__).resolve().parents[3]
PROMPTS_ROOT = ROOT / "prompts"


class PromptedStructuredAgent:
    agent_name = "Agent"
    prompt_dir = ""
    prompt_version = "v1"
    output_type: type[BaseModel]

    def __init__(self, provider: EditorialProvider) -> None:
        self.provider = provider
        settings = get_settings()
        self.model_name = settings.editorial_agent_model
        self.temperature = settings.editorial_agent_temperature
        self.last_execution: EditorialExecutionMetadata | None = None

    def run(self, input_model: BaseModel) -> OutputModelT:
        prompt = (PROMPTS_ROOT / self.prompt_dir / f"{self.prompt_version}.txt").read_text(encoding="utf-8")
        result = self.provider.run_structured(
            agent_name=self.agent_name,
            prompt=prompt,
            input_model=input_model,
            output_type=self.output_type,  # type: ignore[arg-type]
            model_name=self.model_name,
            prompt_version=self.prompt_version,
            temperature=self.temperature,
        )
        self.last_execution = result.metadata
        return result.output


class ProductChangeAnalyst(PromptedStructuredAgent):
    agent_name = "ProductChangeAnalyst"
    prompt_dir = "product-intelligence-agent"
    output_type = ProductIntelligenceOutput


class ProductIntelligenceAgent(ProductChangeAnalyst):
    agent_name = "ProductIntelligenceAgent"


class UsageIntelligenceAgent(PromptedStructuredAgent):
    agent_name = "UsageIntelligenceAgent"
    prompt_dir = "usage-intelligence-agent"
    output_type = UsageIntelligenceOutput


class EditorialStrategyAgent(PromptedStructuredAgent):
    agent_name = "EditorialStrategyAgent"
    prompt_dir = "editorial-strategy-agent"
    output_type = EditorialStrategyOutput


class MapsiUserEmailWriter(PromptedStructuredAgent):
    agent_name = "MapsiUserEmailWriter"
    prompt_dir = "customer-email-writer-agent"
    output_type = CustomerEmailWriterOutput


class CustomerEmailWriterAgent(MapsiUserEmailWriter):
    agent_name = "CustomerEmailWriterAgent"


class EditorialQualityAgent(PromptedStructuredAgent):
    agent_name = "EditorialQualityAgent"
    prompt_dir = "quality-control-agent"
    output_type = QualityControlOutput


class QualityControlAgent(EditorialQualityAgent):
    agent_name = "QualityControlAgent"


class MarketEditorialStrategyAgent(PromptedStructuredAgent):
    agent_name = "MarketEditorialStrategyAgent"
    prompt_dir = "market-editorial-strategy-agent"
    output_type = MarketEditorialStrategyOutput


class ProspectNewsletterWriter(PromptedStructuredAgent):
    agent_name = "ProspectNewsletterWriter"
    prompt_dir = "newsletter-writer-agent"
    output_type = NewsletterWriterOutput


class NewsletterWriterAgent(ProspectNewsletterWriter):
    agent_name = "NewsletterWriterAgent"


class LinkedInPostWriter(PromptedStructuredAgent):
    agent_name = "LinkedInPostWriter"
    prompt_dir = "linkedin-writer-agent"
    output_type = LinkedInWriterOutput


class LinkedInWriterAgent(LinkedInPostWriter):
    agent_name = "LinkedInWriterAgent"


class OlingArticleWriter(PromptedStructuredAgent):
    agent_name = "OlingArticleWriter"
    prompt_dir = "website-article-writer-agent"
    output_type = WebsiteArticleWriterOutput


class MapsiArticleWriter(PromptedStructuredAgent):
    agent_name = "MapsiArticleWriter"
    prompt_dir = "website-article-writer-agent"
    output_type = WebsiteArticleWriterOutput


class MapsiStudioContentWriter(PromptedStructuredAgent):
    agent_name = "MapsiStudioContentWriter"
    prompt_dir = "website-article-writer-agent"
    output_type = WebsiteArticleWriterOutput


class WebsiteArticleWriterAgent(OlingArticleWriter):
    agent_name = "WebsiteArticleWriterAgent"


class SeoQualityAgent(PromptedStructuredAgent):
    agent_name = "SeoQualityAgent"
    prompt_dir = "seo-quality-agent"
    output_type = SeoQualityOutput


def contains_pii(payload: dict) -> bool:
    text = str(payload)
    return bool(re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text, flags=re.IGNORECASE))


def detect_editorial_policy_violations(payload: dict | str) -> list[str]:
    text = str(payload).casefold()
    violations: list[str] = []
    patterns = {
        "invented_testimonial": [r"\btemoignage\b", r"\bselon\s+[A-Z][a-z]+\b"],
        "compliance_promise": [r"\bconforme\b", r"\bcertifi", r"\bcompliance\b"],
        "guaranteed_result": [r"\bgaranti", r"\bgarantie\b", r"\bresultat[s]?\s+garanti"],
    }
    for code, entries in patterns.items():
        if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in entries):
            violations.append(code)
    return violations
