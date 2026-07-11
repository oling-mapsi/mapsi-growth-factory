from __future__ import annotations

from itertools import count

from fastapi import FastAPI, Query

app = FastAPI(title="Mautic Mock", version="1.0.0")

COUNTERS = {
    "fields": count(1),
    "tags": count(1),
    "categories": count(1),
    "lists": count(1),
    "emails": count(1),
    "campaigns": count(1),
    "contacts": count(1),
}
STATE = {
    "fields": {},
    "tags": {},
    "categories": {},
    "lists": {},
    "emails": {},
    "campaigns": {},
    "contacts": {},
    "events": {},
}


def _create(kind: str, payload: dict) -> dict:
    item_id = next(COUNTERS[kind])
    item = {"id": item_id, **payload}
    if kind == "contacts":
        item.setdefault("fields", {"core": {"email": {"value": payload.get("email", "")}}})
        item.setdefault("isDoNotContact", False)
        item.setdefault("unsubscribed", False)
        item.setdefault("doNotContact", [])
    STATE[kind][item_id] = item
    return item


def _update(kind: str, item_id: int, payload: dict) -> dict:
    item = STATE[kind][item_id]
    item.update(payload)
    if kind == "contacts":
        item["fields"] = {"core": {"email": {"value": item.get("email", "")}}}
    return item


@app.get("/api/fields/contact")
def list_fields() -> dict:
    return {"fields": STATE["fields"]}


@app.post("/api/fields/contact/new")
def create_field(payload: dict) -> dict:
    return {"field": _create("fields", payload)}


@app.patch("/api/fields/contact/{item_id}/edit")
@app.post("/api/fields/contact/{item_id}/edit")
def edit_field(item_id: int, payload: dict) -> dict:
    return {"field": _update("fields", item_id, payload)}


@app.get("/api/tags")
def list_tags() -> dict:
    return {"tags": STATE["tags"]}


@app.post("/api/tags/new")
def create_tag(payload: dict) -> dict:
    return {"tag": _create("tags", payload)}


@app.get("/api/categories")
def list_categories() -> dict:
    return {"categories": STATE["categories"]}


@app.post("/api/categories/new")
def create_category(payload: dict) -> dict:
    return {"category": _create("categories", payload)}


@app.get("/api/segments")
def list_segments() -> dict:
    return {"lists": STATE["lists"]}


@app.post("/api/segments/new")
def create_segment(payload: dict) -> dict:
    return {"list": _create("lists", payload)}


@app.patch("/api/segments/{item_id}/edit")
@app.post("/api/segments/{item_id}/edit")
def edit_segment(item_id: int, payload: dict) -> dict:
    return {"list": _update("lists", item_id, payload)}


@app.get("/api/segments/{item_id}")
def get_segment(item_id: int) -> dict:
    return {"list": STATE["lists"][item_id]}


@app.post("/api/segments/{segment_id}/contact/{contact_id}/add")
def add_contact_to_segment(segment_id: int, contact_id: int) -> dict:
    segment = STATE["lists"][segment_id]
    segment.setdefault("contacts", [])
    if contact_id not in segment["contacts"]:
        segment["contacts"].append(contact_id)
    return {"success": True}


@app.get("/api/emails")
def list_emails() -> dict:
    return {"emails": STATE["emails"]}


@app.post("/api/emails/new")
def create_email(payload: dict) -> dict:
    return {"email": _create("emails", payload)}


@app.patch("/api/emails/{item_id}/edit")
@app.post("/api/emails/{item_id}/edit")
def edit_email(item_id: int, payload: dict) -> dict:
    return {"email": _update("emails", item_id, payload)}


@app.get("/api/campaigns")
def list_campaigns() -> dict:
    return {"campaigns": STATE["campaigns"]}


@app.post("/api/campaigns/new")
def create_campaign(payload: dict) -> dict:
    return {"campaign": _create("campaigns", payload)}


@app.patch("/api/campaigns/{item_id}/edit")
@app.post("/api/campaigns/{item_id}/edit")
def edit_campaign(item_id: int, payload: dict) -> dict:
    return {"campaign": _update("campaigns", item_id, payload)}


@app.get("/api/campaigns/{item_id}/events")
def list_campaign_events(item_id: int) -> dict:
    return {"events": STATE["events"].get(item_id, [])}


@app.get("/api/contacts")
def list_contacts(search: str | None = Query(default=None)) -> dict:
    contacts = STATE["contacts"]
    if search:
        values = {
            str(item_id): item
            for item_id, item in contacts.items()
            if item.get("email", "").lower() == search.lower()
        }
        return {"contacts": values}
    return {"contacts": {str(item_id): item for item_id, item in contacts.items()}}


@app.post("/api/contacts/new")
def create_contact(payload: dict) -> dict:
    return {"contact": _create("contacts", payload)}


@app.patch("/api/contacts/{item_id}/edit")
@app.post("/api/contacts/{item_id}/edit")
def edit_contact(item_id: int, payload: dict) -> dict:
    return {"contact": _update("contacts", item_id, payload)}


@app.get("/api/contacts/{item_id}")
def get_contact(item_id: int) -> dict:
    return {"contact": STATE["contacts"][item_id]}


@app.post("/api/contacts/{item_id}/dnc/email/add")
def add_dnc(item_id: int, payload: dict) -> dict:
    contact = STATE["contacts"][item_id]
    contact["isDoNotContact"] = True
    contact.setdefault("doNotContact", [])
    contact["doNotContact"].append(payload)
    return {"success": True}
