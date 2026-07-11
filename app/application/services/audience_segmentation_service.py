from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import jsonschema

from app.core.config import get_settings
from app.domain.entities import (
    AudienceFact,
    AudienceSegmentAuditEntry,
    AudienceSegmentPreview,
    AudienceSegmentRule,
    SegmentCondition,
)
from app.infrastructure.repositories.audience_segments import AudienceSegmentationRepository


class AudienceSegmentationService:
    def __init__(
        self,
        repository: AudienceSegmentationRepository,
        *,
        rules_dir: Path | None = None,
        schema_path: Path | None = None,
        min_size: int | None = None,
        max_size: int | None = None,
    ) -> None:
        settings = get_settings()
        root = Path(__file__).resolve().parents[3]
        self.repository = repository
        self.rules_dir = rules_dir or root / "config" / "audience-segments"
        self.schema_path = schema_path or self.rules_dir / "schema.json"
        self.min_size = settings.audience_segment_min_size if min_size is None else min_size
        self.max_size = settings.audience_segment_max_size if max_size is None else max_size

    def list_segments(self, *, enabled_only: bool = True) -> list[AudienceSegmentRule]:
        rules = [self._load_rule(path) for path in sorted(self.rules_dir.glob("*.json")) if path.name != "schema.json"]
        if enabled_only:
            return [rule for rule in rules if rule.enabled]
        return rules

    def preview_segment(self, segment_id: str, *, persist: bool = True, allow_disabled: bool = False) -> AudienceSegmentPreview:
        rule = next((item for item in self.list_segments(enabled_only=False) if item.id == segment_id), None)
        if rule is None:
            raise ValueError(f"Unknown audience segment: {segment_id}")
        if not rule.enabled and not allow_disabled:
            raise ValueError(f"Segment {segment_id} is disabled.")
        return self._preview_rule(rule, persist=persist)

    def preview_proposed_segment(self, payload: dict, *, persist: bool = False) -> AudienceSegmentPreview:
        rule = self._rule_from_payload(payload)
        if rule.enabled:
            raise ValueError("Proposed audience segment must be disabled.")
        return self._preview_rule(rule, persist=persist)

    def _preview_rule(self, rule: AudienceSegmentRule, *, persist: bool) -> AudienceSegmentPreview:
        facts = self.repository.list_audience_facts()
        included: list[AudienceFact] = []
        audits: list[AudienceSegmentAuditEntry] = []
        exclusions = Counter()
        for fact in facts:
            decision = self._evaluate_fact(rule, fact)
            if decision["included"]:
                included.append(fact)
            else:
                for reason in decision["reasons"]:
                    exclusions[reason] += 1
            audits.append(
                AudienceSegmentAuditEntry(
                    membership_id=fact.membership_id,
                    included=decision["included"],
                    reasons=decision["reasons"],
                    role_key=fact.role_key,
                    client_key=fact.client_key,
                )
            )
        blocked_reasons = self._blocked_reasons(rule, included)
        status = "blocked" if blocked_reasons else "ready"
        preview = AudienceSegmentPreview(
            segment_id=rule.id,
            segment_label=rule.label,
            legal_basis=rule.legal_basis,
            enabled=rule.enabled,
            status=status,
            blocked_reasons=blocked_reasons,
            total_volume=len(facts),
            eligible_volume=len(included),
            exclusions_by_reason=dict(exclusions),
            role_distribution=dict(Counter(fact.role_key for fact in included)),
            module_distribution=dict(Counter(module for fact in included for module in fact.module_keys)),
            client_distribution=dict(Counter(fact.client_key for fact in included)),
            audits=audits,
        )
        if persist:
            self.repository.save_preview(preview)
        return preview

    def _evaluate_fact(self, rule: AudienceSegmentRule, fact: AudienceFact) -> dict:
        reasons: list[str] = []
        for condition in rule.conditions_all:
            if not self._matches(condition, fact):
                reasons.append(f"condition_failed:{condition.field}:{condition.operator}")
        if rule.conditions_any and not any(self._matches(condition, fact) for condition in rule.conditions_any):
            reasons.append("condition_failed:any")
        if not reasons:
            for exclusion in rule.exclusions:
                if self._is_excluded(exclusion, fact):
                    reasons.append(f"excluded:{exclusion}")
        if reasons:
            return {"included": False, "reasons": reasons}
        return {"included": True, "reasons": ["included"]}

    def _blocked_reasons(self, rule: AudienceSegmentRule, included: list[AudienceFact]) -> list[str]:
        reasons: list[str] = []
        if not rule.legal_basis.strip():
            reasons.append("missing_legal_basis")
        if not included:
            reasons.append("audience_empty")
        if included and len(included) < self.min_size:
            reasons.append("audience_below_min_threshold")
        if len(included) > self.max_size:
            reasons.append("audience_above_max_threshold")
        if any(fact.opted_out for fact in included):
            reasons.append("contains_oppositions")
        return reasons

    def _matches(self, condition: SegmentCondition, fact: AudienceFact) -> bool:
        current = self._field_value(fact, condition.field)
        operator = condition.operator
        expected = condition.value
        if operator == "equals":
            return current == expected
        if operator == "greater_than":
            return current > expected
        if operator == "greater_or_equal":
            return current >= expected
        if operator == "less_than":
            return current < expected
        if operator == "less_or_equal":
            return current <= expected
        if operator == "in":
            return current in expected
        if operator == "contains_any":
            return any(item in current for item in expected)
        raise ValueError(f"Unsupported operator: {operator}")

    def _field_value(self, fact: AudienceFact, field: str):
        now = datetime.now(UTC)
        if field == "active":
            return fact.active
        if field == "communication_eligible":
            return fact.communication_eligible
        if field == "opted_out":
            return fact.opted_out
        if field == "role_key":
            return fact.role_key
        if field == "instance_key":
            return fact.instance_key
        if field == "client_key":
            return fact.client_key
        if field == "module_keys":
            return fact.module_keys
        if field == "last_login_days":
            if fact.last_activity_at is None:
                return 10**9
            return max(0, int((now - fact.last_activity_at.astimezone(UTC)).days))
        if field == "account_age_days":
            return max(0, int((now - fact.created_at.astimezone(UTC)).days))
        if field == "total_feature_events_7d":
            return sum(fact.module_events.values())
        if field.startswith("module_events."):
            return fact.module_events.get(field.split(".", 1)[1], 0)
        raise ValueError(f"Unsupported field: {field}")

    def _is_excluded(self, exclusion: str, fact: AudienceFact) -> bool:
        if exclusion == "opted_out":
            return fact.opted_out
        if exclusion == "invalid_email":
            return fact.invalid_email
        if exclusion == "account_suspended":
            return fact.account_suspended
        raise ValueError(f"Unsupported exclusion: {exclusion}")

    def _load_rule(self, path: Path) -> AudienceSegmentRule:
        return self._rule_from_payload(json.loads(path.read_text(encoding="utf-8")))

    def _rule_from_payload(self, payload: dict) -> AudienceSegmentRule:
        schema = json.loads(self.schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(payload, schema)
        return AudienceSegmentRule(
            id=payload["id"],
            label=payload["label"],
            enabled=payload["enabled"],
            legal_basis=payload.get("legal_basis", ""),
            description=payload.get("description", ""),
            conditions_all=[SegmentCondition(**item) for item in payload.get("conditions", {}).get("all", [])],
            conditions_any=[SegmentCondition(**item) for item in payload.get("conditions", {}).get("any", [])],
            exclusions=payload.get("exclusions", []),
        )
