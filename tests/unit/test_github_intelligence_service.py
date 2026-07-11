from datetime import datetime, timedelta, timezone

from app.application.dto_github import CollectedProductChange
from app.application.services.github_intelligence_service import GitHubIntelligenceService
from app.domain.entities import RepositoryCursor, RepositorySource
from app.infrastructure.tasks import InMemoryTaskQueue


class FakeConnector:
    def __init__(self, changes: list[CollectedProductChange]) -> None:
        self.changes = changes

    def verify_signature(self, body: bytes, provided_signature: str | None) -> None:
        return None

    def ensure_repository_allowed(self, repository_full_name: str) -> None:
        return None

    def collect_product_changes(self, event_type: str, payload: dict) -> list[CollectedProductChange]:
        return self.changes

    def poll_product_changes(self, repository_full_name: str, last_seen_sha: str = "") -> list[CollectedProductChange]:
        return self.changes


class FakeRepositorySources:
    def __init__(self, source: RepositorySource) -> None:
        self.source = source

    def get_or_create(self, full_name: str, installation_id: str, default_branch: str) -> RepositorySource:
        return self.source

    def list_all(self) -> list[RepositorySource]:
        return [self.source]


class FakeRepositoryCursors:
    def __init__(self, cursor: RepositoryCursor | None = None) -> None:
        self.cursor = cursor
        self.upserts: list[tuple[str, str, str, str]] = []

    def upsert(self, source_id: str, cursor_type: str, last_seen_sha: str, last_delivery_id: str) -> RepositoryCursor:
        self.upserts.append((source_id, cursor_type, last_seen_sha, last_delivery_id))
        self.cursor = RepositoryCursor(
            repository_source_id=source_id,
            cursor_type=cursor_type,
            last_seen_sha=last_seen_sha,
            last_delivery_id=last_delivery_id,
        )
        return self.cursor

    def get(self, source_id: str, cursor_type: str) -> RepositoryCursor | None:
        return self.cursor


class FakeProductChanges:
    def __init__(self) -> None:
        self.saved = []

    def save_many(self, changes):
        self.saved.extend(changes)
        return changes


class FakeSourceEvidences:
    def save_many(self, evidences):
        return evidences


class FakeWebhookDeliveries:
    def create_if_absent(self, delivery):
        return delivery, True

    def mark(self, delivery_id: str, status: str, processed: bool, signature_valid: bool) -> None:
        return None


def test_weekly_backfill_processes_stale_repository() -> None:
    source = RepositorySource(id="src-1", full_name="mapsi/mapsi-v6", installation_id="123")
    cursor = RepositoryCursor(
        repository_source_id="src-1",
        cursor_type="weekly_poll",
        last_seen_sha="old",
        last_delivery_id="",
        last_polled_at=datetime.now(timezone.utc) - timedelta(days=8),
    )
    change = CollectedProductChange(
        repository_full_name="mapsi/mapsi-v6",
        sha="newsha",
        change_note_path="growth/change-notes/change.yaml",
        capability_key="cap",
        summary="Summary",
        eligible_for_communication=True,
        confidential=False,
        target_client_key="",
        contract_version="1.0.0",
        deployment_proven=True,
    )
    cursors = FakeRepositoryCursors(cursor)
    changes = FakeProductChanges()
    service = GitHubIntelligenceService(
        connector=FakeConnector([change]),
        repository_sources=FakeRepositorySources(source),
        repository_cursors=cursors,
        product_changes=changes,
        source_evidences=FakeSourceEvidences(),
        webhook_deliveries=FakeWebhookDeliveries(),
        task_queue=InMemoryTaskQueue(),
    )

    processed = service.run_weekly_backfill()

    assert processed == 1
    assert cursors.upserts[0][2] == "newsha"
