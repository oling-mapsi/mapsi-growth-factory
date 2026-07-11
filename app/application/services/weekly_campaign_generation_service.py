from __future__ import annotations

from collections import Counter

from app.application.models.editorial_agents import (
    AgentExecutionRecord,
    CustomerEmailWriterInput,
    EditorialStrategyInput,
    EnabledSegmentReference,
    EvidenceReference,
    ProductFeatureInput,
    ProductIntelligenceInput,
    QualityControlInput,
    QualityIssue,
    QualityControlOutput,
    SegmentUsageInput,
    ThemeHistoryEntry,
    UsageIntelligenceInput,
)
from app.application.services.audience_segmentation_service import AudienceSegmentationService
from app.application.services.editorial_agents import (
    CustomerEmailWriterAgent,
    EditorialStrategyAgent,
    ProductIntelligenceAgent,
    QualityControlAgent,
    UsageIntelligenceAgent,
    contains_pii,
)
from app.domain.errors import EditorialGenerationBlockedError
from app.infrastructure.observability import incr, structured_log
from app.infrastructure.repositories.editorial_pipeline import EditorialPipelineRepository


class WeeklyCampaignGenerationService:
    def __init__(
        self,
        *,
        product_agent: ProductIntelligenceAgent,
        usage_agent: UsageIntelligenceAgent,
        strategy_agent: EditorialStrategyAgent,
        writer_agent: CustomerEmailWriterAgent,
        quality_agent: QualityControlAgent,
        segmentation_service: AudienceSegmentationService,
        repository: EditorialPipelineRepository,
    ) -> None:
        self.product_agent = product_agent
        self.usage_agent = usage_agent
        self.strategy_agent = strategy_agent
        self.writer_agent = writer_agent
        self.quality_agent = quality_agent
        self.segmentation_service = segmentation_service
        self.repository = repository

    def generate(self, dry_run: bool = True) -> dict:
        product_changes = self.repository.list_communicable_product_changes()
        if not product_changes:
            raise EditorialGenerationBlockedError("No communicable product changes available.")
        segments = self.segmentation_service.list_segments(enabled_only=True)
        segment_previews = {segment.id: self.segmentation_service.preview_segment(segment.id, persist=False) for segment in segments}
        evidence_index = {
            evidence["evidence_id"]: EvidenceReference.model_validate(evidence)
            for change in product_changes
            for evidence in change["evidences"]
        }
        enabled_segments = [
            EnabledSegmentReference(
                segment_id=segment.id,
                label=segment.label,
                legal_basis=segment.legal_basis,
                enabled=segment.enabled,
            )
            for segment in segments
        ]
        theme_history = [
            ThemeHistoryEntry(topic=item["topic"], created_at=item["created_at"])
            for item in self.repository.list_theme_history()
        ]
        product_input = ProductIntelligenceInput(
            features=[
                ProductFeatureInput(
                    capability_key=change["capability_key"],
                    summary=change["summary"],
                    module_key=change["module_key"],
                    eligible_for_communication=change["eligible_for_communication"],
                    confidential=change["confidential"],
                    client_scope=change["client_scope"],
                    evidence_ids=[evidence["evidence_id"] for evidence in change["evidences"]],
                    deployed=change["deployed"],
                    restrictions=sorted(set(change["restrictions"])),
                )
                for change in product_changes
            ],
            evidences=list(evidence_index.values()),
            allowed_segments=[segment.segment_id for segment in enabled_segments],
        )
        usage_input = UsageIntelligenceInput(
            segments=[
                SegmentUsageInput(
                    segment_id=segment.id,
                    eligible_volume=segment_previews[segment.id].eligible_volume,
                    role_distribution=segment_previews[segment.id].role_distribution,
                    module_distribution=segment_previews[segment.id].module_distribution,
                    adoption_signals=segment_previews[segment.id].module_distribution,
                )
                for segment in segments
            ]
        )
        product_output = self.product_agent.run(product_input)
        self._log_agent(self.product_agent, product_input, product_output)
        self._validate_product_output(product_output, product_input, evidence_index)
        usage_output = self.usage_agent.run(usage_input)
        self._log_agent(self.usage_agent, usage_input, usage_output)
        strategy_input = EditorialStrategyInput(
            product_candidates=product_output.candidates,
            usage_recommendations=usage_output.recommendations,
            enabled_segments=enabled_segments,
            theme_history=theme_history,
        )
        strategy_output = self.strategy_agent.run(strategy_input)
        self._log_agent(self.strategy_agent, strategy_input, strategy_output)
        self._validate_strategy(strategy_output, enabled_segments, evidence_index, theme_history)
        email_input = CustomerEmailWriterInput(
            topic=strategy_output.topic,
            objective=strategy_output.objective,
            audience_segment_id=strategy_output.audience_segment_id,
            key_messages=strategy_output.key_messages,
            cta_type=strategy_output.cta_type,
            evidences=[evidence_index[evidence_id] for evidence_id in strategy_output.evidence_ids],
        )
        email_output = self.writer_agent.run(email_input)
        self._log_agent(self.writer_agent, email_input, email_output)
        self._validate_email(email_output, strategy_output, evidence_index)
        qc_input = QualityControlInput(
            strategy=strategy_output,
            email=email_output,
            evidences=[evidence_index[evidence_id] for evidence_id in strategy_output.evidence_ids],
            enabled_segments=enabled_segments,
        )
        qc_output = self.quality_agent.run(qc_input)
        qc_output = self._enforce_quality(qc_output, strategy_output, email_output, evidence_index, enabled_segments, theme_history)
        self._log_agent(self.quality_agent, qc_input, qc_output)
        evaluations = self._evaluate(strategy_output, email_output, qc_output, evidence_index, enabled_segments, theme_history)
        if not qc_output.passed:
            raise EditorialGenerationBlockedError(f"Quality control failed: {[issue.code for issue in qc_output.issues]}")
        if not dry_run:
            self.repository.append_theme_history(strategy_output.topic, strategy_output.objective, strategy_output.audience_segment_id)
        incr("editorial.weekly_campaign.generated")
        structured_log(
            "editorial.weekly_campaign.generated",
            topic=strategy_output.topic,
            audience_segment_id=strategy_output.audience_segment_id,
            dry_run=dry_run,
        )
        return {
            "topic": strategy_output.topic,
            "objective": strategy_output.objective,
            "audience_segment_id": strategy_output.audience_segment_id,
            "email": email_output.model_dump(mode="json"),
            "quality": qc_output.model_dump(mode="json"),
            "evaluations": evaluations,
        }

    def _log_agent(self, agent, input_model, output_model) -> None:
        self.repository.log_agent_execution(
            agent_name=agent.agent_name,
            model_name=agent.model_name,
            prompt_version=agent.prompt_version,
            execution_params={"temperature": agent.temperature},
            input_payload=input_model.model_dump(mode="json"),
            output_payload=output_model.model_dump(mode="json"),
        )

    def _validate_product_output(self, output, input_model, evidence_index) -> None:
        allowed_features = {feature.capability_key for feature in input_model.features if feature.deployed}
        for candidate in output.candidates:
            if candidate.capability_key not in allowed_features:
                raise EditorialGenerationBlockedError("Agent proposed non-deployed or unknown feature.")
            if not candidate.evidence_ids or any(evidence_id not in evidence_index for evidence_id in candidate.evidence_ids):
                raise EditorialGenerationBlockedError("Product candidate missing valid evidence.")

    def _validate_strategy(self, strategy, enabled_segments, evidence_index, theme_history) -> None:
        enabled_segment_ids = {segment.segment_id for segment in enabled_segments if segment.enabled}
        if strategy.audience_segment_id not in enabled_segment_ids:
            raise EditorialGenerationBlockedError("Strategy selected a disabled or unknown segment.")
        if not strategy.evidence_ids or any(evidence_id not in evidence_index for evidence_id in strategy.evidence_ids):
            raise EditorialGenerationBlockedError("Strategy contains unsupported evidence ids.")
        history_topics = {item.topic.casefold() for item in theme_history}
        if strategy.topic.casefold() in history_topics:
            raise EditorialGenerationBlockedError("Strategy repeats a recent theme.")

    def _validate_email(self, email, strategy, evidence_index) -> None:
        if set(email.evidence_ids) - set(strategy.evidence_ids):
            raise EditorialGenerationBlockedError("Email cites evidence outside the approved strategy.")
        if any(evidence_id not in evidence_index for evidence_id in email.evidence_ids):
            raise EditorialGenerationBlockedError("Email contains unsupported evidence ids.")
        if contains_pii(email.model_dump(mode="json")):
            raise EditorialGenerationBlockedError("Email output contains personal data.")

    def _enforce_quality(self, qc, strategy, email, evidence_index, enabled_segments, theme_history):
        issues = list(qc.issues)
        if contains_pii(email.model_dump(mode="json")):
            issues.append(QualityIssue(code="no_pii", message="Personal data detected.", severity="error"))
        if strategy.audience_segment_id not in {segment.segment_id for segment in enabled_segments}:
            issues.append(QualityIssue(code="audience_enabled", message="Audience segment is not enabled.", severity="error"))
        if any(not evidence_index[evidence_id].deployed for evidence_id in strategy.evidence_ids):
            issues.append(QualityIssue(code="deployed_only", message="Undeployed evidence referenced.", severity="error"))
        if strategy.topic.casefold() in {item.topic.casefold() for item in theme_history}:
            issues.append(QualityIssue(code="non_repetition", message="Theme already used recently.", severity="error"))
        passed = not any(issue.severity == "error" for issue in issues)
        return QualityControlOutput(passed=passed, issues=issues)

    def _evaluate(self, strategy, email, qc, evidence_index, enabled_segments, theme_history) -> dict:
        return {
            "exactitude": all(evidence_id in evidence_index for evidence_id in strategy.evidence_ids),
            "absence_of_personal_data": not contains_pii(email.model_dump(mode="json")),
            "evidence_compliance": set(email.evidence_ids).issubset(set(strategy.evidence_ids)),
            "audience_coherence": strategy.audience_segment_id in {segment.segment_id for segment in enabled_segments},
            "non_repetition": strategy.topic.casefold() not in {item.topic.casefold() for item in theme_history},
            "ton_oling": "!" not in email.subject and "!" not in email.headline,
            "quality_passed": qc.passed,
        }
