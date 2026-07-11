from __future__ import annotations

from collections import defaultdict

import pytest
from sqlalchemy import func

from app.application.services.mapsi_usage_collection_service import MapsiUsageCollectionService
from app.generated.mapsi_contract_models import Capability, CapabilitySnapshot, ContactEntry, ContactSnapshotPage, HealthStatus, UsageModule, UsageSnapshotPage, UsageUser
from app.infrastructure.connectors.mapsi_usage import MapsiInstanceConfig
from app.infrastructure.db.models import ContactIdentityModel, ContactMembershipModel, FeatureAdoptionModel
from app.infrastructure.repositories.mapsi_usage import MapsiUsageRepository


class FakeMapsiUsageConnector:
    def __init__(
        self,
        *,
        contract_version: str = "1.3.0",
        contact_pages: list[ContactSnapshotPage] | None = None,
        usage_pages: list[UsageSnapshotPage] | None = None,
        fail_on_usage_cursor: str | None = None,
        unavailable: bool = False,
    ) -> None:
        self.contract_version = contract_version
        self.contact_pages = contact_pages or []
        self.usage_pages = usage_pages or []
        self.fail_on_usage_cursor = fail_on_usage_cursor
        self.unavailable = unavailable

    def health(self) -> HealthStatus:
        if self.unavailable:
            raise RuntimeError("Instance unavailable")
        return HealthStatus(status="ok", instance_id="gpmlm", contract_version=self.contract_version)

    def capabilities(self) -> CapabilitySnapshot:
        return CapabilitySnapshot(
            instance_id="gpmlm",
            contract_version=self.contract_version,
            generated_at="2026-07-11T09:30:00Z",
            capabilities=[Capability(capability_key="planning", enabled=True, version="2026.07.1")],
        )

    def contact_page(self, cursor: str | None = None, page_size: int = 100) -> ContactSnapshotPage:
        index = int(cursor or "0")
        return self.contact_pages[index]

    def usage_page(self, cursor: str | None = None, page_size: int = 100) -> UsageSnapshotPage:
        if self.fail_on_usage_cursor is not None and (cursor or "") == self.fail_on_usage_cursor:
            raise RuntimeError("Pagination interrupted")
        index = int(cursor or "0")
        return self.usage_pages[index]


def contact_page(*contacts: ContactEntry, cursor: str = "", next_cursor: str = "", has_more: bool = False) -> ContactSnapshotPage:
    return ContactSnapshotPage(
        instance_id="gpmlm",
        contract_version="1.3.0",
        generated_at="2026-07-11T09:30:00Z",
        cursor=cursor,
        next_cursor=next_cursor,
        has_more=has_more,
        contacts=list(contacts),
    )


def usage_page(*users: UsageUser, cursor: str = "", next_cursor: str = "", has_more: bool = False, version: str = "1.3.0") -> UsageSnapshotPage:
    return UsageSnapshotPage(
        instance_id="gpmlm",
        contract_version=version,
        captured_at="2026-07-11T09:30:00Z",
        cursor=cursor,
        next_cursor=next_cursor,
        has_more=has_more,
        users=list(users),
    )


def make_service(session, connector: FakeMapsiUsageConnector, instance_key: str = "gpmlm") -> MapsiUsageCollectionService:
    return MapsiUsageCollectionService(
        connector=connector,
        repository=MapsiUsageRepository(session),
        instance_config=MapsiInstanceConfig(
            id=instance_key,
            base_url=f"https://{instance_key}.example",
            secret_ref=f"vault://mapsi/{instance_key}/growth-token",
            enabled=True,
        ),
    )


def test_instance_unavailable(session) -> None:
    service = make_service(session, FakeMapsiUsageConnector(unavailable=True))
    with pytest.raises(RuntimeError, match="Instance unavailable"):
        service.collect(dry_run=True)


def test_contract_incompatible(session) -> None:
    service = make_service(session, FakeMapsiUsageConnector(contract_version="2.0.0"))
    with pytest.raises(RuntimeError, match="Incompatible MAPSI contract version"):
        service.collect(dry_run=True)


def test_pagination_interrupted_and_resume(session) -> None:
    contacts = [
        contact_page(
            ContactEntry(user_id="u1", tenant_id="t1", email="a@example.test", communication_eligible=True, active=True, opted_out=False, role_key="manager"),
            cursor="",
            next_cursor="1",
            has_more=True,
        ),
        contact_page(
            ContactEntry(user_id="u2", tenant_id="t1", email="b@example.test", communication_eligible=True, active=True, opted_out=False, role_key="manager"),
            cursor="1",
            next_cursor="",
            has_more=False,
        ),
    ]
    usage_pages = [
        usage_page(
            UsageUser(user_id="u1", tenant_id="t1", active=True, role_key="manager", last_activity_at="2026-07-10T10:00:00Z", communication_eligible=True, opted_out=False, modules=[UsageModule(module_key="planning", events_last_7_days=2)]),
            cursor="",
            next_cursor="1",
            has_more=True,
        ),
        usage_page(
            UsageUser(user_id="u2", tenant_id="t1", active=True, role_key="manager", last_activity_at="2026-07-10T10:00:00Z", communication_eligible=True, opted_out=False, modules=[UsageModule(module_key="planning", events_last_7_days=3)]),
            cursor="1",
            next_cursor="",
            has_more=False,
        ),
    ]
    first = make_service(session, FakeMapsiUsageConnector(contact_pages=contacts, usage_pages=usage_pages, fail_on_usage_cursor="1"))
    with pytest.raises(RuntimeError, match="Pagination interrupted"):
        first.collect(dry_run=False)

    second = make_service(session, FakeMapsiUsageConnector(contact_pages=contacts, usage_pages=usage_pages))
    report = second.collect(dry_run=False)
    assert report["active_users"] >= 1


def test_duplicate_import_is_idempotent(session) -> None:
    contacts = [contact_page(ContactEntry(user_id="u1", tenant_id="t1", email="dup@example.test", communication_eligible=True, active=True, opted_out=False, role_key="manager"))]
    usage = [usage_page(UsageUser(user_id="u1", tenant_id="t1", active=True, role_key="manager", last_activity_at="2026-07-10T10:00:00Z", communication_eligible=True, opted_out=False, modules=[UsageModule(module_key="planning", events_last_7_days=2)]))]
    service = make_service(session, FakeMapsiUsageConnector(contact_pages=contacts, usage_pages=usage))
    service.collect(dry_run=False)
    service.collect(dry_run=False)
    assert session.query(func.count(ContactIdentityModel.id)).scalar() == 1
    assert session.query(func.count(ContactMembershipModel.id)).scalar() == 1
    assert session.query(func.count(FeatureAdoptionModel.id)).scalar() == 1


def test_same_email_present_in_two_instances(session) -> None:
    contacts = [contact_page(ContactEntry(user_id="u1", tenant_id="t1", email="shared@example.test", communication_eligible=True, active=True, opted_out=False, role_key="manager"))]
    usage = [usage_page(UsageUser(user_id="u1", tenant_id="t1", active=True, role_key="manager", last_activity_at="2026-07-10T10:00:00Z", communication_eligible=True, opted_out=False, modules=[UsageModule(module_key="planning", events_last_7_days=2)]))]
    make_service(session, FakeMapsiUsageConnector(contact_pages=contacts, usage_pages=usage), "gpmlm").collect(dry_run=False)
    make_service(session, FakeMapsiUsageConnector(contact_pages=contacts, usage_pages=usage), "gpmg").collect(dry_run=False)
    assert session.query(func.count(ContactIdentityModel.id)).scalar() == 1
    assert session.query(func.count(ContactMembershipModel.id)).scalar() == 2


def test_disabled_user_and_opt_out_are_excluded(session) -> None:
    contacts = [
        contact_page(
            ContactEntry(user_id="u1", tenant_id="t1", email="disabled@example.test", communication_eligible=False, active=False, opted_out=True, role_key="viewer"),
        )
    ]
    usage = [
        usage_page(
            UsageUser(user_id="u1", tenant_id="t1", active=False, role_key="viewer", last_activity_at="2026-07-10T10:00:00Z", communication_eligible=False, opted_out=True, modules=[UsageModule(module_key="planning", events_last_7_days=0)]),
        )
    ]
    report = make_service(session, FakeMapsiUsageConnector(contact_pages=contacts, usage_pages=usage)).collect(dry_run=False)
    assert report["eligible_users"] == 0
    assert report["exclusions"]["disabled"] == 1
    assert report["exclusions"]["opted_out"] == 1


def test_role_change_and_module_change_are_persisted(session) -> None:
    contacts = [contact_page(ContactEntry(user_id="u1", tenant_id="t1", email="role@example.test", communication_eligible=True, active=True, opted_out=False, role_key="viewer"))]
    first_usage = [usage_page(UsageUser(user_id="u1", tenant_id="t1", active=True, role_key="viewer", last_activity_at="2026-07-10T10:00:00Z", communication_eligible=True, opted_out=False, modules=[UsageModule(module_key="planning", events_last_7_days=1)]))]
    second_usage = [usage_page(UsageUser(user_id="u1", tenant_id="t1", active=True, role_key="manager", last_activity_at="2026-07-11T10:00:00Z", communication_eligible=True, opted_out=False, modules=[UsageModule(module_key="crm", events_last_7_days=4)]))]
    service = make_service(session, FakeMapsiUsageConnector(contact_pages=contacts, usage_pages=first_usage))
    service.collect(dry_run=False)
    service = make_service(session, FakeMapsiUsageConnector(contact_pages=contacts, usage_pages=second_usage))
    service.collect(dry_run=False)
    membership = session.query(ContactMembershipModel).one()
    modules = {row.module_key for row in session.query(FeatureAdoptionModel).all()}
    assert membership.role_key == "manager"
    assert "crm" in modules
