from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.application.services.audience_segmentation_service import AudienceSegmentationService
from app.core.security import encrypt_contact_value
from app.infrastructure.db.models import AudienceSegmentAuditModel, AudienceSegmentPreviewModel, ContactMembershipModel
from app.infrastructure.repositories.audience_segments import AudienceSegmentationRepository
from app.infrastructure.repositories.mapsi_usage import MapsiUsageRepository


def seed_membership(
    session,
    *,
    instance_key: str,
    client_key: str,
    external_user_id: str,
    role_key: str,
    active: bool,
    communication_eligible: bool,
    opted_out: bool,
    created_at: datetime,
    last_activity_at: datetime | None,
    modules: dict[str, int],
) -> None:
    repository = MapsiUsageRepository(session)
    instance = repository.upsert_instance(
        instance_key=instance_key,
        base_url=f"https://{instance_key}.example",
        secret_ref=f"vault://mapsi/{instance_key}/growth-token",
        enabled=True,
        contract_version="1.3.0",
    )
    account = repository.upsert_customer_account(instance.id, client_key)
    email = f"{external_user_id}@example.test"
    identity = repository.upsert_contact_identity(
        f"hash:{instance_key}:{external_user_id}",
        encrypt_contact_value(email),
        True,
    )
    membership = repository.upsert_contact_membership(
        contact_identity_id=identity.id,
        customer_account_id=account.id,
        external_user_id=external_user_id,
        role_key=role_key,
        active=active,
        communication_eligible=communication_eligible,
        opted_out=opted_out,
        last_activity_at=last_activity_at,
    )
    model = session.get(ContactMembershipModel, membership.id)
    model.created_at = created_at
    model.updated_at = created_at
    session.commit()
    snapshot = repository.create_snapshot_if_absent(instance.id, "usage", f"{external_user_id}:usage", "1.3.0", created_at)
    for module_key, events in modules.items():
        repository.upsert_feature_adoption(snapshot.id, membership.id, module_key, events)


def service(session, *, min_size: int = 1, max_size: int = 10000) -> AudienceSegmentationService:
    return AudienceSegmentationService(
        AudienceSegmentationRepository(session),
        min_size=min_size,
        max_size=max_size,
    )


def test_all_eligible_active_users_preview_is_deterministic(session) -> None:
    now = datetime.now(UTC)
    seed_membership(
        session,
        instance_key="gpmlm",
        client_key="tenant-a",
        external_user_id="u1",
        role_key="administrator",
        active=True,
        communication_eligible=True,
        opted_out=False,
        created_at=now - timedelta(days=7),
        last_activity_at=now - timedelta(days=2),
        modules={"planning": 3, "risk": 1},
    )
    seed_membership(
        session,
        instance_key="gpmlm",
        client_key="tenant-b",
        external_user_id="u2",
        role_key="viewer",
        active=False,
        communication_eligible=True,
        opted_out=False,
        created_at=now - timedelta(days=40),
        last_activity_at=now - timedelta(days=40),
        modules={"planning": 0},
    )

    preview = service(session).preview_segment("all_eligible_active_users", persist=True)

    assert preview.status == "ready"
    assert preview.total_volume == 2
    assert preview.eligible_volume == 1
    assert preview.role_distribution == {"administrator": 1}
    assert preview.module_distribution == {"planning": 1, "risk": 1}
    assert preview.client_distribution == {"tenant-a": 1}
    assert session.query(AudienceSegmentPreviewModel).count() == 1
    assert session.query(AudienceSegmentAuditModel).count() == 2


def test_inactive_30_days_boundary(session) -> None:
    now = datetime.now(UTC)
    seed_membership(
        session,
        instance_key="gpmlm",
        client_key="tenant-a",
        external_user_id="u1",
        role_key="viewer",
        active=True,
        communication_eligible=True,
        opted_out=False,
        created_at=now - timedelta(days=60),
        last_activity_at=now - timedelta(days=30),
        modules={"planning": 1},
    )
    seed_membership(
        session,
        instance_key="gpmlm",
        client_key="tenant-a",
        external_user_id="u2",
        role_key="viewer",
        active=True,
        communication_eligible=True,
        opted_out=False,
        created_at=now - timedelta(days=60),
        last_activity_at=now - timedelta(days=31),
        modules={"planning": 1},
    )

    preview = service(session).preview_segment("inactive_30_days", persist=False)

    assert preview.eligible_volume == 1
    assert preview.audits[0].included is False
    assert preview.audits[1].included is True


def test_max_threshold_blocks_large_audience(session) -> None:
    now = datetime.now(UTC)
    for user_id in ("u1", "u2"):
        seed_membership(
            session,
            instance_key="gpmlm",
            client_key="tenant-a",
            external_user_id=user_id,
            role_key="viewer",
            active=True,
            communication_eligible=True,
            opted_out=False,
            created_at=now - timedelta(days=10),
            last_activity_at=now - timedelta(days=1),
            modules={"planning": 1},
        )

    preview = service(session, max_size=1).preview_segment("all_eligible_active_users", persist=False)

    assert preview.status == "blocked"
    assert "audience_above_max_threshold" in preview.blocked_reasons


def test_segment_without_legal_basis_is_blocked(session) -> None:
    preview = service(session).preview_proposed_segment(
        {
            "id": "draft_segment",
            "label": "Draft",
            "enabled": False,
            "legal_basis": "",
            "conditions": {
                "all": [{"field": "active", "operator": "equals", "value": True}]
            },
            "exclusions": []
        },
        persist=False,
    )

    assert preview.status == "blocked"
    assert "missing_legal_basis" in preview.blocked_reasons
    assert "audience_empty" in preview.blocked_reasons


def test_segment_containing_oppositions_is_blocked(session) -> None:
    now = datetime.now(UTC)
    seed_membership(
        session,
        instance_key="gpmlm",
        client_key="tenant-a",
        external_user_id="u1",
        role_key="viewer",
        active=True,
        communication_eligible=True,
        opted_out=True,
        created_at=now - timedelta(days=10),
        last_activity_at=now - timedelta(days=1),
        modules={"planning": 0},
    )

    preview = service(session).preview_proposed_segment(
        {
            "id": "optout_segment",
            "label": "Optout",
            "enabled": False,
            "legal_basis": "legitimate_interest_growth",
            "conditions": {
                "all": [
                    {"field": "active", "operator": "equals", "value": True},
                    {"field": "communication_eligible", "operator": "equals", "value": True}
                ]
            },
            "exclusions": []
        },
        persist=False,
    )

    assert preview.status == "blocked"
    assert "contains_oppositions" in preview.blocked_reasons


def test_proposed_segment_must_be_disabled_and_sql_is_rejected(session) -> None:
    with pytest.raises(ValueError, match="must be disabled"):
        service(session).preview_proposed_segment(
            {
                "id": "bad_segment",
                "label": "Bad",
                "enabled": True,
                "legal_basis": "legitimate_interest_growth",
                "conditions": {"all": [{"field": "active", "operator": "equals", "value": True}]},
                "exclusions": []
            },
            persist=False,
        )
    with pytest.raises(Exception):
        service(session).preview_proposed_segment(
            {
                "id": "sql_segment",
                "label": "SQL",
                "enabled": False,
                "legal_basis": "legitimate_interest_growth",
                "conditions": {"all": [{"field": "sql", "operator": "equals", "value": "select * from users"}]},
                "exclusions": []
            },
            persist=False,
        )
