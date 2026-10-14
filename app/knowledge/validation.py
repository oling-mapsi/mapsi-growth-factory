from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from app.core.security import sha256_hexdigest
from app.knowledge.models import KnowledgeValidationResult, MapsiFeature, OlingPractice

EMAIL_RE = re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b")
TOKEN_RE = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|[A-Za-z0-9_-]{32,}\.[A-Za-z0-9._-]{10,})\b")
SECRET_KEY_RE = re.compile(r"(secret|token|password|api[_-]?key)", re.IGNORECASE)
FRONT_MATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)
IDENTIFIER_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def resolve_knowledge_root(root: Path | None = None) -> Path:
    if root is not None:
        return root
    return Path(__file__).resolve().parents[2] / "knowledge"


def read_knowledge_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def load_feature_catalog(path: Path) -> list[MapsiFeature]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return [MapsiFeature(**item) for item in payload]


def load_oling_practice(path: Path) -> OlingPractice:
    metadata = _parse_markdown_front_matter(path)
    return OlingPractice(
        practice_id=str(metadata["practice_id"]),
        title=str(metadata["title"]),
        description=str(metadata["description"]),
        common_client_problems=[str(item) for item in metadata["common_client_problems"]],
        intervention_context=str(metadata["intervention_context"]),
        oling_approach=str(metadata["oling_approach"]),
        mission_steps=[str(item) for item in metadata["mission_steps"]],
        usual_deliverables=[str(item) for item in metadata["usual_deliverables"]],
        vigilance_points=[str(item) for item in metadata["vigilance_points"]],
        success_factors=[str(item) for item in metadata["success_factors"]],
        concerned_sectors=[str(item) for item in metadata["concerned_sectors"]],
        allowed_ctas=[str(item) for item in metadata["allowed_ctas"]],
        forbidden_claims=[str(item) for item in metadata["forbidden_claims"]],
        sources=[str(item) for item in metadata["sources"]],
    )


def validate_knowledge_base(root: Path | None = None) -> KnowledgeValidationResult:
    knowledge_root = resolve_knowledge_root(root)
    required_files = _required_files(knowledge_root)
    errors: list[str] = []
    checked_files: list[str] = []
    for path in required_files:
        if not path.exists():
            errors.append(f"Missing required file: {path.relative_to(knowledge_root)}")
        else:
            checked_files.append(str(path.relative_to(knowledge_root)))
    if errors:
        return KnowledgeValidationResult(False, "", checked_files, errors, [], [])

    feature_schema = _load_json_schema(knowledge_root / "schemas" / "mapsi-feature-catalog.schema.json")
    practice_schema = _load_json_schema(knowledge_root / "schemas" / "oling-practice.schema.json")

    feature_path = knowledge_root / "mapsi" / "feature-catalog.yaml"
    feature_payload = _load_yaml(feature_path, errors, "mapsi/feature-catalog.yaml")
    if feature_payload is None:
        feature_payload = []
    else:
        _validate_json_schema(feature_payload, feature_schema, errors, "mapsi/feature-catalog.yaml")

    mapsi_features = load_feature_catalog(feature_path) if not errors else []
    feature_ids: list[str] = []
    seen_feature_ids: set[str] = set()
    for feature in mapsi_features:
        feature_ids.append(feature.feature_id)
        if feature.feature_id in seen_feature_ids:
            errors.append(f"Duplicate feature_id: {feature.feature_id}")
        seen_feature_ids.add(feature.feature_id)
        if not feature.source_references:
            errors.append(f"Feature {feature.feature_id} must define source_references.")
        if not IDENTIFIER_RE.match(feature.feature_id):
            errors.append(f"Invalid feature_id format: {feature.feature_id}")

    oling_practice_ids: list[str] = []
    for path in sorted((knowledge_root / "oling" / "practices").glob("*.md")):
        relative_path = str(path.relative_to(knowledge_root))
        metadata = _parse_markdown_front_matter(path, errors, relative_path)
        if metadata is None:
            continue
        _validate_json_schema(metadata, practice_schema, errors, relative_path)
        practice = load_oling_practice(path)
        oling_practice_ids.append(practice.practice_id)
        if path.stem != practice.practice_id:
            errors.append(f"Practice id mismatch in {relative_path}: expected {path.stem}, got {practice.practice_id}")
        if not IDENTIFIER_RE.match(practice.practice_id):
            errors.append(f"Invalid practice_id format: {practice.practice_id}")
        for field_name in (
            "common_client_problems",
            "mission_steps",
            "usual_deliverables",
            "vigilance_points",
            "success_factors",
            "allowed_ctas",
            "forbidden_claims",
            "sources",
        ):
            value = getattr(practice, field_name)
            if not value:
                errors.append(f"Practice {practice.practice_id} must define a non-empty {field_name}.")

    for path in checked_files:
        absolute_path = knowledge_root / path
        content = absolute_path.read_text(encoding="utf-8")
        if EMAIL_RE.search(content):
            errors.append(f"Email detected in {path}")
        if TOKEN_RE.search(content):
            errors.append(f"Token-like value detected in {path}")
        if absolute_path.suffix in {".yaml", ".yml"}:
            payload = yaml.safe_load(content)
            _scan_secrets(payload, errors, path)
        elif absolute_path.suffix == ".md":
            metadata = _parse_markdown_front_matter(absolute_path)
            if metadata:
                _scan_secrets(metadata, errors, path)

    computed_hash = compute_knowledge_version_hash(knowledge_root)
    stored_hash = read_knowledge_text(knowledge_root / "version.sha256")
    if stored_hash != computed_hash:
        errors.append("knowledge/version.sha256 does not match computed knowledge hash.")

    return KnowledgeValidationResult(
        ok=not errors,
        version_hash=computed_hash,
        checked_files=checked_files,
        errors=errors,
        mapsi_feature_ids=feature_ids,
        oling_practice_ids=oling_practice_ids,
    )


def compute_knowledge_version_hash(root: Path | None = None) -> str:
    knowledge_root = resolve_knowledge_root(root)
    parts: list[str] = []
    for path in sorted(knowledge_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(knowledge_root)
        if relative.as_posix() == "version.sha256":
            continue
        parts.append(f"## {relative.as_posix()}\n{path.read_text(encoding='utf-8')}")
    return sha256_hexdigest("\n".join(parts))


def _required_files(root: Path) -> list[Path]:
    files = [
        root / "mapsi" / "feature-catalog.yaml",
        root / "mapsi" / "product-positioning.md",
        root / "mapsi" / "terminology.md",
        root / "mapsi" / "target-personas.md",
        root / "mapsi" / "forbidden-claims.md",
        root / "oling" / "company-profile.md",
        root / "oling" / "editorial-style.md",
        root / "oling" / "target-clients.md",
        root / "oling" / "differentiators.md",
        root / "oling" / "forbidden-claims.md",
        root / "schemas" / "mapsi-feature-catalog.schema.json",
        root / "schemas" / "oling-practice.schema.json",
        root / "version.sha256",
    ]
    for practice_id in (
        "amoa",
        "direction-de-projet",
        "dsi-deleguee",
        "erp",
        "gmao",
        "ged-et-dematerialisation",
        "facturation-electronique",
        "infrastructures-et-reseaux",
        "cybersecurite",
        "rgpd-et-dpo",
        "pca-et-pra",
        "qualite-et-systemes-iso",
        "data-et-bi",
        "controle-interne",
        "marches-publics",
    ):
        files.append(root / "oling" / "practices" / f"{practice_id}.md")
    return files


def _load_yaml(path: Path, errors: list[str], label: str):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        errors.append(f"Invalid YAML in {label}: {exc}")
        return None


def _load_json_schema(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_json_schema(payload: object, schema: dict, errors: list[str], label: str) -> None:
    validator = Draft202012Validator(schema)
    for error in sorted(validator.iter_errors(payload), key=str):
        location = ".".join(str(part) for part in error.absolute_path)
        suffix = f" at {location}" if location else ""
        errors.append(f"Schema validation failed for {label}{suffix}: {error.message}")


def _parse_markdown_front_matter(path: Path, errors: list[str] | None = None, label: str | None = None) -> dict | None:
    content = path.read_text(encoding="utf-8")
    match = FRONT_MATTER_RE.match(content)
    if match is None:
        if errors is not None:
            errors.append(f"Missing YAML front matter in {label or path.name}")
        return None
    try:
        return yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        if errors is not None:
            errors.append(f"Invalid YAML front matter in {label or path.name}: {exc}")
        return None


def _scan_secrets(payload: object, errors: list[str], label: str, *, parents: tuple[str, ...] = ()) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            next_parents = parents + (str(key),)
            if SECRET_KEY_RE.search(str(key)) and value not in ("", None, [], {}):
                errors.append(f"Secret-like field forbidden in {label}: {'.'.join(next_parents)}")
            _scan_secrets(value, errors, label, parents=next_parents)
        return
    if isinstance(payload, list):
        for index, value in enumerate(payload):
            _scan_secrets(value, errors, label, parents=parents + (str(index),))

