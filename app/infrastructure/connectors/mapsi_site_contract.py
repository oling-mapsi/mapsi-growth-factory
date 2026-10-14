from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = ROOT / "contracts" / "mapsi_site" / "openapi.yaml"


@lru_cache
def load_mapsi_site_contract() -> dict[str, Any]:
    return yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))


def get_openapi_info() -> dict[str, Any]:
    return dict(load_mapsi_site_contract().get("info", {}))


def get_request_example(path: str, method: str, example_name: str = "default") -> dict[str, Any]:
    operation = load_mapsi_site_contract()["paths"][path][method.lower()]
    examples = operation["requestBody"]["content"]["application/json"].get("examples", {})
    payload = examples.get(example_name, {}).get("value", {})
    return dict(payload)


def supports_unpublish() -> bool:
    return "/api/growth/news/{externalId}/unpublish" in load_mapsi_site_contract().get("paths", {})
