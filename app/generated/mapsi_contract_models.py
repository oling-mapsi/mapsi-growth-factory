from __future__ import annotations

from pydantic import BaseModel


class HealthStatus(BaseModel):
    status: str
    instance_id: str
    contract_version: str


class Capability(BaseModel):
    capability_key: str
    enabled: bool
    version: str


class CapabilitySnapshot(BaseModel):
    instance_id: str
    contract_version: str
    generated_at: str
    capabilities: list[Capability]


class UsageModule(BaseModel):
    module_key: str
    events_last_7_days: int


class UsageUser(BaseModel):
    user_id: str
    tenant_id: str
    active: bool
    role_key: str
    last_activity_at: str
    communication_eligible: bool | None = None
    opted_out: bool | None = None
    modules: list[UsageModule]


class UsageSnapshotPage(BaseModel):
    instance_id: str
    contract_version: str
    captured_at: str
    cursor: str | None = None
    next_cursor: str | None = None
    has_more: bool
    users: list[UsageUser]


class ContactEntry(BaseModel):
    user_id: str
    tenant_id: str
    email: str
    communication_eligible: bool
    active: bool
    opted_out: bool | None = None
    role_key: str | None = None
    opt_out_reason: str | None = None


class ContactSnapshotPage(BaseModel):
    instance_id: str
    contract_version: str
    generated_at: str
    cursor: str | None = None
    next_cursor: str | None = None
    has_more: bool
    contacts: list[ContactEntry]


class ProductChange(BaseModel):
    id: str
    title: str
    summary: str
    url: str | None = None
    published_at: str | None = None
    tags: list[str]
    communicable: bool


class ProductChangeCollection(BaseModel):
    contract_version: str
    generated_at: str
    items: list[ProductChange]
