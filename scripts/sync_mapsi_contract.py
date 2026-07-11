from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS_DIR = ROOT / "contracts" / "mapsi"
GENERATED_DIR = ROOT / "app" / "generated"
SUPPORTED_MAJOR = 1
FILES = [
    "openapi.yaml",
    "usage-snapshot.schema.json",
    "contact-snapshot.schema.json",
    "product-change.schema.json",
    "examples/health.example.json",
    "examples/capabilities.example.json",
    "examples/usage-snapshot.example.json",
    "examples/contact-snapshot.example.json",
    "examples/product-change.example.json",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="mapsi/mapsi-v6")
    parser.add_argument("--tag")
    parser.add_argument("--branch")
    parser.add_argument("--sha")
    parser.add_argument("--api-base-url", default="https://api.github.com")
    parser.add_argument("--raw-base-url", default="https://raw.githubusercontent.com")
    parser.add_argument("--contract-path", default="docs/growth-contract/published")
    return parser.parse_args()


def choose_ref(args: argparse.Namespace) -> tuple[str, str]:
    provided = [(name, getattr(args, name)) for name in ("tag", "branch", "sha") if getattr(args, name)]
    if len(provided) != 1:
        raise SystemExit("Provide exactly one of --tag, --branch or --sha.")
    return provided[0]


def resolve_sha(client: httpx.Client, repo: str, ref_type: str, ref_value: str, api_base_url: str) -> str:
    if ref_type == "sha":
        return ref_value
    response = client.get(f"{api_base_url}/repos/{repo}/commits/{ref_value}")
    response.raise_for_status()
    payload = response.json()
    return payload["sha"]


def fetch_text(client: httpx.Client, raw_base_url: str, repo: str, sha: str, contract_path: str, relative_path: str) -> str:
    url = f"{raw_base_url.rstrip('/')}/{repo}/{sha}/{contract_path.strip('/')}/{relative_path}"
    response = client.get(url)
    response.raise_for_status()
    return response.text


def ensure_supported_major(openapi_version: str) -> None:
    major = int(openapi_version.split(".", 1)[0])
    if major != SUPPORTED_MAJOR:
        raise SystemExit(
            f"Incompatible contract major version {major}. Supported major is {SUPPORTED_MAJOR}."
        )


def python_type(schema: dict[str, Any], models: dict[str, dict[str, Any]]) -> str:
    ref = schema.get("$ref")
    if ref:
        return ref.rsplit("/", 1)[-1]
    schema_type = schema.get("type")
    if schema_type == "string":
        return "str"
    if schema_type == "integer":
        return "int"
    if schema_type == "boolean":
        return "bool"
    if schema_type == "array":
        return f"list[{python_type(schema['items'], models)}]"
    if schema_type == "object":
        return "dict[str, object]"
    return "object"


def generate_models(openapi_doc: dict[str, Any]) -> str:
    schemas = openapi_doc["components"]["schemas"]
    lines = [
        "from __future__ import annotations",
        "",
        "from pydantic import BaseModel",
        "",
    ]
    for name, schema in schemas.items():
        lines.append(f"class {name}(BaseModel):")
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))
        if not properties:
            lines.append("    pass")
            lines.append("")
            continue
        for prop_name, prop_schema in properties.items():
            hint = python_type(prop_schema, schemas)
            if prop_name not in required:
                hint = f"{hint} | None = None"
                lines.append(f"    {prop_name}: {hint}")
            else:
                lines.append(f"    {prop_name}: {hint}")
        lines.append("")
    return "\n".join(lines) + "\n"


def generate_client() -> str:
    return """from __future__ import annotations

from httpx import Client

from app.generated.mapsi_contract_models import (
    CapabilitySnapshot,
    ContactSnapshotPage,
    HealthStatus,
    ProductChangeCollection,
    UsageSnapshotPage,
)


class MapsiContractClient:
    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self.client = Client(base_url=base_url.rstrip("/"), timeout=timeout)

    def get_health(self) -> HealthStatus:
        response = self.client.get("/health")
        response.raise_for_status()
        return HealthStatus.model_validate(response.json())

    def get_capabilities(self) -> CapabilitySnapshot:
        response = self.client.get("/internal/growth/capabilities")
        response.raise_for_status()
        return CapabilitySnapshot.model_validate(response.json())

    def get_usage_snapshot(self, cursor: str | None = None, page_size: int = 100) -> UsageSnapshotPage:
        params = {"page_size": page_size}
        if cursor:
            params["cursor"] = cursor
        response = self.client.get("/internal/growth/usage-snapshot", params=params)
        response.raise_for_status()
        return UsageSnapshotPage.model_validate(response.json())

    def get_contact_snapshot(self, cursor: str | None = None, page_size: int = 100) -> ContactSnapshotPage:
        params = {"page_size": page_size}
        if cursor:
            params["cursor"] = cursor
        response = self.client.get("/internal/growth/contact-snapshot", params=params)
        response.raise_for_status()
        return ContactSnapshotPage.model_validate(response.json())

    def get_product_changes(self) -> ProductChangeCollection:
        response = self.client.get("/internal/growth/product-changes")
        response.raise_for_status()
        return ProductChangeCollection.model_validate(response.json())
"""


def write_contract_version(sha: str, ref_value: str, contract_version: str) -> None:
    content = "\n".join(
        [
            f"contract_version={contract_version}",
            f"source_ref={ref_value}",
            f"source_sha={sha}",
        ]
    )
    (CONTRACTS_DIR / "contract-version.txt").write_text(content + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    ref_type, ref_value = choose_ref(args)
    with httpx.Client(timeout=20.0) as client:
        sha = resolve_sha(client, args.repo, ref_type, ref_value, args.api_base_url.rstrip("/"))
        for relative_path in FILES:
            target = CONTRACTS_DIR / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            payload = fetch_text(
                client=client,
                raw_base_url=args.raw_base_url,
                repo=args.repo,
                sha=sha,
                contract_path=args.contract_path,
                relative_path=relative_path,
            )
            target.write_text(payload, encoding="utf-8")

    openapi_doc = yaml.safe_load((CONTRACTS_DIR / "openapi.yaml").read_text(encoding="utf-8"))
    contract_version = openapi_doc["info"]["version"]
    ensure_supported_major(contract_version)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    (GENERATED_DIR / "mapsi_contract_models.py").write_text(generate_models(openapi_doc), encoding="utf-8")
    (GENERATED_DIR / "mapsi_contract_client.py").write_text(generate_client(), encoding="utf-8")
    write_contract_version(sha, ref_value, contract_version)
    print(f"Synchronized MAPSI contract version={contract_version} sha={sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
