from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.application.services.audience_segmentation_service import AudienceSegmentationService
from app.application.services.mautic_contact_sync_service import MauticContactSyncService
from app.core.security import encrypt_contact_value
from app.infrastructure.connectors.mautic import MauticConnector, MauticConnectorConfig
from app.infrastructure.db.models import ContactMembershipModel, MauticContactLinkModel
from app.infrastructure.repositories.audience_segments import AudienceSegmentationRepository
from app.infrastructure.repositories.mautic_sync import MauticSyncRepository
from app.infrastructure.repositories.mapsi_usage import MapsiUsageRepository
from app.mock_mautic_server import STATE, app as mautic_mock_app


def reset_mock_state() -> None:
    for key in STATE:
        STATE[key].clear()


def seed_contact(
    session,
    *,
    instance_key: str,
    customer_id: str,
    external_user_id: str,
    email: str,
    role_key: str,
    active: bool,
    communication_eligible: bool,
    opted_out: bool,
    modules: dict[str, int],
    created_at: datetime,
    last_activity_at: datetime | None,
) -> None:
    repository = MapsiUsageRepository(session)
    instance = repository.upsert_instance(
        instance_key=instance_key,
        base_url=f"https://{instance_key}.example",
        secret_ref=f"vault://mapsi/{instance_key}/growth-token",
        enabled=True,
        contract_version="1.3.0",
    )
    account = repository.upsert_customer_account(instance.id, customer_id)
    identity = repository.upsert_contact_identity(
        email_hash=f"hash:{email.lower()}",
        encrypted_email=encrypt_contact_value(email),
        email_valid="@" in email and "." in email.rsplit("@", 1)[-1],
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
    row = session.get(ContactMembershipModel, membership.id)
    row.created_at = created_at
    row.updated_at = created_at
    session.commit()
    snapshot = repository.create_snapshot_if_absent(instance.id, "usage", f"{external_user_id}:usage", "1.3.0", created_at)
    for module_key, events in modules.items():
        repository.upsert_feature_adoption(snapshot.id, membership.id, module_key, events)


def build_service(session) -> MauticContactSyncService:
    reset_mock_state()
    connector = MauticConnector(
        MauticConnectorConfig(
            base_url="http://testserver",
            username="",
            password="",
            access_token="sandbox-token",
            verify_tls=False,
        ),
        client=TestClient(mautic_mock_app),
    )
    segmentation = AudienceSegmentationService(AudienceSegmentationRepository(session))
    return MauticContactSyncService(connector, MauticSyncRepository(session), segmentation)


def test_provision_is_idempotent(session) -> None:
    service = build_service(session)

    first = service.provision(dry_run=False)
    second = service.provision(dry_run=False)

    assert first["custom_fields"] == second["custom_fields"]
    assert len(STATE["fields"]) == first["custom_fields"]
    assert len(STATE["lists"]) >= first["segments"]
    assert len(STATE["campaigns"]) == 1


def test_sync_only_eligible_contacts_and_report_has_no_email(session) -> None:
    now = datetime.now(UTC)
    seed_contact(
        session,
        instance_key="gpmlm",
        customer_id="tenant-a",
        external_user_id="u1",
        email="eligible@example.test",
        role_key="administrator",
        active=True,
        communication_eligible=True,
        opted_out=False,
        modules={"planning": 1},
        created_at=now - timedelta(days=10),
        last_activity_at=now - timedelta(days=1),
    )
    seed_contact(
        session,
        instance_key="gpmlm",
        customer_id="tenant-a",
        external_user_id="u2",
        email="optout@example.test",
        role_key="viewer",
        active=True,
        communication_eligible=True,
        opted_out=True,
        modules={"planning": 0},
        created_at=now - timedelta(days=10),
        last_activity_at=now - timedelta(days=1),
    )

    service = build_service(session)
    service.provision(dry_run=False)
    report = service.sync_contacts(dry_run=False)

    assert report["contacts_seen"] == 2
    assert report["contacts_synced"] == 1
    assert report["contacts_skipped"] == 1
    assert "eligible@example.test" not in str(report)
    assert len(STATE["contacts"]) == 1


def test_existing_remote_contact_is_set_dnc_and_never_reactivated(session) -> None:
    now = datetime.now(UTC)
    seed_contact(
        session,
        instance_key="gpmlm",
        customer_id="tenant-a",
        external_user_id="u1",
        email="person@example.test",
        role_key="viewer",
        active=True,
        communication_eligible=True,
        opted_out=False,
        modules={"planning": 1},
        created_at=now - timedelta(days=10),
        last_activity_at=now - timedelta(days=1),
    )
    service = build_service(session)
    service.provision(dry_run=False)
    service.sync_contacts(dry_run=False)
    contact = next(iter(STATE["contacts"].values()))
    contact["unsubscribed"] = True

    report = service.sync_contacts(dry_run=False)

    assert report["contacts_dnc"] == 1
    assert session.query(MauticContactLinkModel).one().remote_unsubscribed is True
    assert len(STATE["contacts"]) == 1


def test_same_email_across_instances_merges_into_single_mautic_contact(session) -> None:
    now = datetime.now(UTC)
    seed_contact(
        session,
        instance_key="gpmlm",
        customer_id="tenant-a",
        external_user_id="u1",
        email="shared@example.test",
        role_key="administrator",
        active=True,
        communication_eligible=True,
        opted_out=False,
        modules={"planning": 1},
        created_at=now - timedelta(days=10),
        last_activity_at=now - timedelta(days=1),
    )
    seed_contact(
        session,
        instance_key="gpmg",
        customer_id="tenant-b",
        external_user_id="u2",
        email="shared@example.test",
        role_key="quality_manager",
        active=True,
        communication_eligible=True,
        opted_out=False,
        modules={"risk": 2},
        created_at=now - timedelta(days=8),
        last_activity_at=now - timedelta(days=2),
    )

    service = build_service(session)
    service.provision(dry_run=False)
    report = service.sync_contacts(dry_run=False)
    contact = next(iter(STATE["contacts"].values()))

    assert report["contacts_seen"] == 1
    assert report["contacts_synced"] == 1
    assert len(STATE["contacts"]) == 1
    assert set(contact["mapsi_instance_ids"].split(",")) == {"gpmlm", "gpmg"}
    assert set(contact["mapsi_customer_ids"].split(",")) == {"tenant-a", "tenant-b"}


def test_sync_is_idempotent(session) -> None:
    now = datetime.now(UTC)
    seed_contact(
        session,
        instance_key="gpmlm",
        customer_id="tenant-a",
        external_user_id="u1",
        email="idem@example.test",
        role_key="administrator",
        active=True,
        communication_eligible=True,
        opted_out=False,
        modules={"planning": 3},
        created_at=now - timedelta(days=5),
        last_activity_at=now - timedelta(days=1),
    )

    service = build_service(session)
    service.provision(dry_run=False)
    first = service.sync_contacts(dry_run=False)
    second = service.sync_contacts(dry_run=False)

    assert first["contacts_synced"] == 1
    assert second["contacts_synced"] == 1
    assert len(STATE["contacts"]) == 1
    assert session.query(MauticContactLinkModel).count() == 1
