from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.application.dto_github import WebhookProcessingResult
from app.application.ports.product_intelligence import (
    ProductChangeRepositoryPort,
    RepositoryCursorRepositoryPort,
    RepositorySourceRepositoryPort,
    SourceEvidenceRepositoryPort,
    WebhookDeliveryRepositoryPort,
)
from app.application.ports.tasks import TaskQueuePort
from app.domain.entities import ProductChange, SourceEvidence, WebhookDelivery
from app.domain.errors import IncompatibleContractVersionError, UnauthorizedRepositoryError, WebhookSignatureInvalidError
from app.infrastructure.connectors.github import GitHubConnector
from app.infrastructure.observability import incr, structured_log


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GitHubIntelligenceService:
    def __init__(
        self,
        connector: GitHubConnector,
        repository_sources: RepositorySourceRepositoryPort,
        repository_cursors: RepositoryCursorRepositoryPort,
        product_changes: ProductChangeRepositoryPort,
        source_evidences: SourceEvidenceRepositoryPort,
        webhook_deliveries: WebhookDeliveryRepositoryPort,
        task_queue: TaskQueuePort,
    ) -> None:
        self.connector = connector
        self.repository_sources = repository_sources
        self.repository_cursors = repository_cursors
        self.product_changes = product_changes
        self.source_evidences = source_evidences
        self.webhook_deliveries = webhook_deliveries
        self.task_queue = task_queue

    def process_webhook(
        self,
        *,
        delivery_id: str,
        event_type: str,
        signature: str | None,
        body: bytes,
        payload: dict[str, Any],
    ) -> WebhookProcessingResult:
        repository_full_name = payload.get("repository", {}).get("full_name", "")
        delivery, created = self.webhook_deliveries.create_if_absent(
            WebhookDelivery(
                delivery_id=delivery_id,
                event_type=event_type,
                repository_full_name=repository_full_name,
                signature_valid=False,
                processed=False,
                status="received",
                payload=payload,
            )
        )
        if not created:
            incr("github.webhook.duplicate")
            structured_log("github.webhook.duplicate", delivery_id=delivery_id, repository=repository_full_name)
            return WebhookProcessingResult(accepted=True, status="duplicate", product_changes_created=0)
        try:
            self.connector.verify_signature(body, signature)
            self.webhook_deliveries.mark(delivery.delivery_id, "signature-verified", False, True)
            self.connector.ensure_repository_allowed(repository_full_name)
        except WebhookSignatureInvalidError:
            self.webhook_deliveries.mark(delivery.delivery_id, "invalid-signature", True, False)
            raise
        except UnauthorizedRepositoryError:
            self.webhook_deliveries.mark(delivery.delivery_id, "unauthorized-repository", True, True)
            raise
        source = self.repository_sources.get_or_create(
            full_name=repository_full_name,
            installation_id=str(payload.get("installation", {}).get("id", "")),
            default_branch=payload.get("repository", {}).get("default_branch", "main"),
        )
        try:
            collected = self.connector.collect_product_changes(event_type, payload)
        except IncompatibleContractVersionError:
            self.webhook_deliveries.mark(delivery.delivery_id, "invalid-schema", True, True)
            raise
        persisted_changes = self.product_changes.save_many(
            [
                ProductChange(
                    repository_source_id=source.id,
                    repository_full_name=item.repository_full_name,
                    sha=item.sha,
                    pr_number=item.pr_number,
                    issue_numbers=item.issue_numbers,
                    release_tag=item.release_tag,
                    deployment_ref=item.deployment_ref,
                    production_status=item.production_status,
                    change_note_path=item.change_note_path,
                    eligible_for_communication=item.eligible_for_communication,
                    confidential=item.confidential,
                    target_client_key=item.target_client_key,
                    capability_key=item.capability_key,
                    summary=item.summary,
                    contract_version=item.contract_version,
                    deployment_proven=item.deployment_proven,
                    raw_payload=item.raw_payload,
                )
                for item in collected
            ]
        )
        evidences = [
            SourceEvidence(
                product_change_id=change.id,
                source_system="github",
                evidence_type="deployment_proof",
                reference=f"{change.repository_full_name}:{change.sha}",
                payload={
                    "repository": change.repository_full_name,
                    "sha": change.sha,
                    "pr_number": change.pr_number,
                    "release_tag": change.release_tag,
                    "deployment_ref": change.deployment_ref,
                    "production_status": change.production_status,
                },
            )
            for change in persisted_changes
        ]
        self.source_evidences.save_many(evidences)
        last_sha = persisted_changes[-1].sha if persisted_changes else payload.get("after", "")
        self.repository_cursors.upsert(
            source.id,
            "webhook",
            last_sha,
            delivery.delivery_id,
        )
        self.webhook_deliveries.mark(delivery.delivery_id, "processed", True, True)
        self.task_queue.enqueue("github.weekly_backfill", {"repository_source_id": source.id})
        incr("github.webhook.processed")
        incr("github.product_changes.created", len(persisted_changes))
        structured_log(
            "github.webhook.processed",
            delivery_id=delivery.delivery_id,
            repository=repository_full_name,
            event_type=event_type,
            product_changes_created=len(persisted_changes),
        )
        return WebhookProcessingResult(
            accepted=True,
            status="processed",
            product_changes_created=len(persisted_changes),
        )

    def run_weekly_backfill(self) -> int:
        processed = 0
        now = utcnow()
        for source in self.repository_sources.list_all():
            cursor = self.repository_cursors.get(source.id, "weekly_poll")
            if cursor is not None and now - cursor.last_polled_at < timedelta(days=7):
                continue
            changes = self.connector.poll_product_changes(source.full_name, cursor.last_seen_sha if cursor else "")
            persisted_changes = self.product_changes.save_many(
                [
                    ProductChange(
                        repository_source_id=source.id,
                        repository_full_name=item.repository_full_name,
                        sha=item.sha,
                        pr_number=item.pr_number,
                        issue_numbers=item.issue_numbers,
                        release_tag=item.release_tag,
                        deployment_ref=item.deployment_ref,
                        production_status=item.production_status,
                        change_note_path=item.change_note_path,
                        eligible_for_communication=item.eligible_for_communication,
                        confidential=item.confidential,
                        target_client_key=item.target_client_key,
                        capability_key=item.capability_key,
                        summary=item.summary,
                        contract_version=item.contract_version,
                        deployment_proven=item.deployment_proven,
                        raw_payload=item.raw_payload,
                    )
                    for item in changes
                ]
            )
            last_sha = persisted_changes[-1].sha if persisted_changes else (cursor.last_seen_sha if cursor else "")
            self.repository_cursors.upsert(source.id, "weekly_poll", last_sha, "")
            processed += len(persisted_changes)
        incr("github.weekly_backfill.processed", processed)
        structured_log("github.weekly_backfill.processed", count=processed)
        return processed
