from __future__ import annotations

import json
from pathlib import Path

EXPECTED_WORKFLOWS = {
    "L1-01-Collect-Product-Changes",
    "L1-02-Collect-MapsI-Usage",
    "L1-03-Sync-Mautic-Contacts",
    "L1-04-Generate-Campaign",
    "L1-05-Request-Approval",
    "L1-06-Publish-Approved-Campaign",
    "L1-07-Collect-Campaign-Metrics",
    "L1-08-Failure-Notification",
}


def workflow_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "n8n" / "workflows"


def load_workflows() -> list[dict]:
    items = []
    for path in sorted(workflow_dir().glob("*.json")):
        items.append(json.loads(path.read_text(encoding="utf-8")))
    return items


def validate_workflow(workflow: dict) -> list[str]:
    errors: list[str] = []
    if workflow.get("name") not in EXPECTED_WORKFLOWS:
        errors.append(f"unexpected workflow name: {workflow.get('name')}")
    if not isinstance(workflow.get("nodes"), list) or not workflow["nodes"]:
        errors.append("missing nodes")
        return errors
    if "connections" not in workflow:
        errors.append("missing connections")
    manual_present = False
    for node in workflow["nodes"]:
        node_type = str(node.get("type", ""))
        if "function" in node_type.casefold():
            errors.append(f"forbidden function node in {workflow['name']}")
        if node_type == "n8n-nodes-base.manualTrigger":
            manual_present = True
        if node_type == "n8n-nodes-base.scheduleTrigger":
            timezone = node.get("parameters", {}).get("timezone")
            if timezone != "Europe/Paris":
                errors.append(f"invalid timezone in {workflow['name']}")
        if node_type == "n8n-nodes-base.httpRequest":
            url = str(node.get("parameters", {}).get("url", ""))
            if not url.startswith("={{ $env.N8N_GROWTH_BASE_URL"):
                errors.append(f"unexpected http target in {workflow['name']}")
    if not manual_present:
        errors.append(f"missing manual trigger in {workflow['name']}")
    serialized = json.dumps(workflow)
    if "@mapsi.fr" in serialized or "54.37.230.240" in serialized:
        errors.append(f"forbidden real identifier in {workflow['name']}")
    return errors


def validate_all() -> list[str]:
    workflows = load_workflows()
    names = {workflow.get("name") for workflow in workflows}
    errors: list[str] = []
    if names != EXPECTED_WORKFLOWS:
        missing = EXPECTED_WORKFLOWS - names
        extra = names - EXPECTED_WORKFLOWS
        if missing:
            errors.append(f"missing workflows: {sorted(missing)}")
        if extra:
            errors.append(f"unexpected workflows: {sorted(extra)}")
    for workflow in workflows:
        errors.extend(validate_workflow(workflow))
    return errors


def main() -> int:
    errors = validate_all()
    if errors:
        for error in errors:
            print(error)
        return 1
    print("n8n workflows valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
