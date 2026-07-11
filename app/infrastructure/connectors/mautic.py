from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from httpx import BasicAuth, Client

from app.core.config import Settings, get_settings


@dataclass
class MauticConnectorConfig:
    base_url: str
    username: str
    password: str
    access_token: str
    verify_tls: bool


def build_mautic_config(settings: Settings | None = None) -> MauticConnectorConfig:
    current = settings or get_settings()
    return MauticConnectorConfig(
        base_url=current.mautic_base_url,
        username=current.mautic_username,
        password=current.mautic_password,
        access_token=current.mautic_access_token,
        verify_tls=current.mautic_verify_tls,
    )


class MauticConnector:
    def __init__(self, config: MauticConnectorConfig, client: Client | None = None) -> None:
        self.config = config
        headers = {"Accept": "application/json"}
        if config.access_token:
            headers["Authorization"] = f"Bearer {config.access_token}"
        auth = None
        if not config.access_token and config.username:
            auth = BasicAuth(config.username, config.password)
        self.client = client or Client(
            base_url=config.base_url.rstrip("/"),
            headers=headers,
            auth=auth,
            timeout=20.0,
            verify=config.verify_tls,
        )

    def ensure_custom_field(self, alias: str, label: str, field_type: str = "text") -> dict[str, Any]:
        existing = self._find_first("/api/fields/contact", "fields", alias=alias)
        payload = {
            "alias": alias,
            "label": label,
            "type": field_type,
            "object": "lead",
            "isPublished": True,
        }
        if existing is not None:
            return self._edit(f"/api/fields/contact/{existing['id']}/edit", payload, "field")
        return self._create("/api/fields/contact/new", payload, "field")

    def ensure_tag(self, name: str) -> dict[str, Any]:
        existing = self._find_first("/api/tags", "tags", tag=name)
        if existing is not None:
            return existing
        return self._create("/api/tags/new", {"tag": name}, "tag")

    def ensure_category(self, title: str, bundle: str) -> dict[str, Any]:
        existing = self._find_first("/api/categories", "categories", title=title, bundle=bundle)
        if existing is not None:
            return existing
        return self._create("/api/categories/new", {"title": title, "bundle": bundle, "isPublished": True}, "category")

    def ensure_segment(self, alias: str, name: str, description: str) -> dict[str, Any]:
        existing = self._find_first("/api/segments", "lists", alias=alias)
        payload = {"alias": alias, "name": name, "description": description, "isPublished": True}
        if existing is not None:
            return self._edit(f"/api/segments/{existing['id']}/edit", payload, "list")
        return self._create("/api/segments/new", payload, "list")

    def ensure_email_template(self, name: str, subject: str, html: str, category_id: int | str) -> dict[str, Any]:
        existing = self._find_first("/api/emails", "emails", name=name)
        payload = {
            "name": name,
            "subject": subject,
            "customHtml": html,
            "template": "",
            "emailType": "template",
            "isPublished": True,
            "category": {"id": int(category_id)},
        }
        if existing is not None:
            return self._edit(f"/api/emails/{existing['id']}/edit", payload, "email")
        return self._create("/api/emails/new", payload, "email")

    def ensure_campaign(self, name: str, category_id: int | str, is_published: bool = False) -> dict[str, Any]:
        existing = self._find_first("/api/campaigns", "campaigns", name=name)
        payload = {"name": name, "isPublished": is_published, "category": {"id": int(category_id)}}
        if existing is not None:
            return self._edit(f"/api/campaigns/{existing['id']}/edit", payload, "campaign")
        return self._create("/api/campaigns/new", payload, "campaign")

    def configure_campaign_delivery(
        self,
        campaign_id: int | str,
        *,
        email_id: int | str,
        segment_id: int | str,
        scheduled_at: str,
        is_published: bool,
    ) -> dict[str, Any]:
        payload = {
            "emailId": int(email_id),
            "segmentId": int(segment_id),
            "scheduledAt": scheduled_at,
            "isPublished": is_published,
        }
        return self._edit(f"/api/campaigns/{campaign_id}/edit", payload, "campaign")

    def find_contact_by_email(self, email: str) -> dict[str, Any] | None:
        response = self.client.get("/api/contacts", params={"search": email})
        response.raise_for_status()
        payload = response.json()
        contacts = payload.get("contacts", {})
        for item in contacts.values():
            if item.get("fields", {}).get("core", {}).get("email", {}).get("value", "").lower() == email.lower():
                return item
        return None

    def upsert_contact(self, email: str, fields: dict[str, Any], tags: list[str]) -> dict[str, Any]:
        existing = self.find_contact_by_email(email)
        payload = {"email": email, "overwriteWithBlank": False, **fields}
        if tags:
            payload["tags"] = tags
        if existing is not None:
            return self._edit(f"/api/contacts/{existing['id']}/edit", payload, "contact")
        return self._create("/api/contacts/new", payload, "contact")

    def add_contact_to_segment(self, contact_id: int | str, segment_id: int | str) -> None:
        response = self.client.post(f"/api/segments/{segment_id}/contact/{contact_id}/add")
        response.raise_for_status()

    def get_segment_contacts(self, segment_id: int | str) -> list[int]:
        response = self.client.get(f"/api/segments/{segment_id}")
        response.raise_for_status()
        payload = response.json()
        return list(payload.get("list", {}).get("contacts", []) or [])

    def get_contact_dnc(self, contact_id: int | str) -> list[dict[str, Any]]:
        response = self.client.get(f"/api/contacts/{contact_id}")
        response.raise_for_status()
        payload = response.json()
        contact = payload.get("contact", {})
        return contact.get("doNotContact", []) or []

    def list_campaign_events(self, campaign_id: int | str) -> list[dict[str, Any]]:
        response = self.client.get(f"/api/campaigns/{campaign_id}/events")
        response.raise_for_status()
        payload = response.json()
        return list(payload.get("events", []))

    def add_do_not_contact(self, contact_id: int | str, reason: str) -> None:
        response = self.client.post(
            f"/api/contacts/{contact_id}/dnc/email/add",
            json={"reason": reason, "channel": "email"},
        )
        response.raise_for_status()

    def _find_first(self, path: str, collection_key: str, **matches: Any) -> dict[str, Any] | None:
        response = self.client.get(path)
        response.raise_for_status()
        payload = response.json()
        items = payload.get(collection_key, {})
        values = items.values() if isinstance(items, dict) else items
        for item in values:
            if all(item.get(key) == value for key, value in matches.items()):
                return item
        return None

    def _create(self, path: str, payload: dict[str, Any], root_key: str) -> dict[str, Any]:
        response = self.client.post(path, json=payload)
        response.raise_for_status()
        return response.json()[root_key]

    def _edit(self, path: str, payload: dict[str, Any], root_key: str) -> dict[str, Any]:
        response = self.client.patch(path, json=payload)
        if response.status_code == 405:
            response = self.client.post(path, json=payload)
        response.raise_for_status()
        return response.json()[root_key]
