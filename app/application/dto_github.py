from dataclasses import dataclass, field
from typing import Any


@dataclass
class CollectedProductChange:
    repository_full_name: str
    sha: str
    change_note_path: str
    capability_key: str
    summary: str
    eligible_for_communication: bool
    confidential: bool
    target_client_key: str
    contract_version: str
    pr_number: int | None = None
    issue_numbers: list[int] = field(default_factory=list)
    release_tag: str = ""
    deployment_ref: str = ""
    production_status: str = ""
    deployment_proven: bool = False
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class WebhookProcessingResult:
    accepted: bool
    status: str
    product_changes_created: int = 0
