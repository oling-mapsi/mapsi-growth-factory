from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "contracts" / "mapsi"
FORBIDDEN_KEYS = {"password", "medical_record", "salary", "social_security_number", "token", "secret"}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_no_forbidden_keys(payload: object) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in FORBIDDEN_KEYS:
                raise SystemExit(f"Forbidden key found in contract example: {key}")
            ensure_no_forbidden_keys(value)
    elif isinstance(payload, list):
        for item in payload:
            ensure_no_forbidden_keys(item)


def validate_required_fields(openapi_doc: dict) -> None:
    schemas = openapi_doc["components"]["schemas"]
    for schema_name in ("UsageSnapshotPage", "ContactSnapshotPage", "CapabilitySnapshot", "ProductChangeCollection"):
        required = schemas[schema_name].get("required", [])
        if not required:
            raise SystemExit(f"{schema_name} must expose required fields.")


def main() -> int:
    openapi_doc = yaml.safe_load((CONTRACTS / "openapi.yaml").read_text(encoding="utf-8"))
    validate_required_fields(openapi_doc)
    pairs = [
        ("usage-snapshot.schema.json", "examples/usage-snapshot.example.json"),
        ("contact-snapshot.schema.json", "examples/contact-snapshot.example.json"),
        ("product-change.schema.json", "examples/product-change.example.json"),
    ]
    for schema_path, example_path in pairs:
        schema = load_json(CONTRACTS / schema_path)
        example = load_json(CONTRACTS / example_path)
        jsonschema.validate(example, schema)
        ensure_no_forbidden_keys(example)
    print("MAPSI contract checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
