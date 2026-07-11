from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.domain.entities import SourceEvidence
from app.infrastructure.db.models import (
    AgentExecutionLogModel,
    EditorialThemeHistoryModel,
    ProductChangeModel,
    SourceEvidenceModel,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EditorialPipelineRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_communicable_product_changes(self) -> list[dict]:
        rows = (
            self.session.query(ProductChangeModel, SourceEvidenceModel)
            .join(SourceEvidenceModel, SourceEvidenceModel.product_change_id == ProductChangeModel.id)
            .filter(ProductChangeModel.eligible_for_communication.is_(True))
            .filter(ProductChangeModel.confidential.is_(False))
            .filter(ProductChangeModel.deployment_proven.is_(True))
            .all()
        )
        grouped: dict[str, dict] = {}
        for change, evidence in rows:
            item = grouped.setdefault(
                change.id,
                {
                    "product_change_id": change.id,
                    "capability_key": change.capability_key,
                    "summary": change.summary,
                    "module_key": change.capability_key,
                    "eligible_for_communication": change.eligible_for_communication,
                    "confidential": change.confidential,
                    "client_scope": "restricted" if change.target_client_key else "global",
                    "deployed": change.deployment_proven and change.production_status == "production",
                    "restrictions": [],
                    "evidences": [],
                },
            )
            if change.target_client_key:
                item["restrictions"].append("restricted_client_scope")
            item["evidences"].append(
                {
                    "evidence_id": evidence.id,
                    "source_system": evidence.source_system,
                    "reference": evidence.reference,
                    "summary": change.summary,
                    "deployed": item["deployed"],
                    "client_scope": item["client_scope"],
                }
            )
        return list(grouped.values())

    def list_theme_history(self, limit: int = 10) -> list[dict]:
        rows = (
            self.session.query(EditorialThemeHistoryModel)
            .order_by(EditorialThemeHistoryModel.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "topic": row.topic,
                "objective": row.objective,
                "audience_segment_id": row.audience_segment_id,
                "created_at": row.created_at,
            }
            for row in rows
        ]

    def append_theme_history(self, topic: str, objective: str, audience_segment_id: str) -> None:
        self.session.add(
            EditorialThemeHistoryModel(
                topic=topic,
                objective=objective,
                audience_segment_id=audience_segment_id,
            )
        )
        self.session.commit()

    def log_agent_execution(
        self,
        *,
        agent_name: str,
        model_name: str,
        prompt_version: str,
        execution_params: dict,
        input_payload: dict,
        output_payload: dict,
    ) -> None:
        self.session.add(
            AgentExecutionLogModel(
                agent_name=agent_name,
                model_name=model_name,
                prompt_version=prompt_version,
                execution_params=execution_params,
                input_payload=input_payload,
                output_payload=output_payload,
            )
        )
        self.session.commit()

    def count_agent_logs(self) -> int:
        return self.session.query(AgentExecutionLogModel).count()
