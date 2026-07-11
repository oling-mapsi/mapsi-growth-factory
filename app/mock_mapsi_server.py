from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "contracts" / "mapsi"
SYNTHETIC_SHA = "1111111111111111111111111111111111111111"

app = FastAPI(title="MAPSI Contract Mock", version="1.0.0")


def _load_json(relative: str) -> dict:
    return json.loads((FIXTURES / relative).read_text(encoding="utf-8"))


def _paginate(items: list[dict], cursor: str | None, page_size: int) -> tuple[list[dict], str | None]:
    start = int(cursor or "0")
    end = start + page_size
    next_cursor = str(end) if end < len(items) else None
    return items[start:end], next_cursor


@app.get("/repos/{owner}/{repo}/commits/{ref_name}")
def get_commit(owner: str, repo: str, ref_name: str) -> dict:
    return {"sha": SYNTHETIC_SHA, "ref": ref_name, "repository": f"{owner}/{repo}"}


@app.get("/raw/{owner}/{repo}/{sha}/{resource_path:path}")
def get_raw_file(owner: str, repo: str, sha: str, resource_path: str):
    target = FIXTURES / resource_path
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    if target.suffix in {".json"}:
        return json.loads(target.read_text(encoding="utf-8"))
    return PlainTextResponse(target.read_text(encoding="utf-8"))


@app.get("/health")
def health() -> dict:
    return _load_json("examples/health.example.json")


@app.get("/internal/growth/capabilities")
def capabilities() -> dict:
    return _load_json("examples/capabilities.example.json")


@app.get("/internal/growth/usage-snapshot")
def usage_snapshot(cursor: str | None = Query(default=None), page_size: int = Query(default=100)) -> dict:
    payload = _load_json("examples/usage-snapshot.example.json")
    items, next_cursor = _paginate(payload["users"], cursor, page_size)
    payload["users"] = items
    payload["cursor"] = cursor or ""
    payload["next_cursor"] = next_cursor or ""
    payload["has_more"] = next_cursor is not None
    return payload


@app.get("/internal/growth/contact-snapshot")
def contact_snapshot(cursor: str | None = Query(default=None), page_size: int = Query(default=100)) -> dict:
    payload = _load_json("examples/contact-snapshot.example.json")
    items, next_cursor = _paginate(payload["contacts"], cursor, page_size)
    payload["contacts"] = items
    payload["cursor"] = cursor or ""
    payload["next_cursor"] = next_cursor or ""
    payload["has_more"] = next_cursor is not None
    return payload


@app.get("/internal/growth/product-changes")
def product_changes() -> dict:
    return _load_json("examples/product-change.example.json")
