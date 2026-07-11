from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

import httpx
import jwt
import yaml

from app.application.dto_github import CollectedProductChange
from app.core.config import Settings
from app.domain.errors import IncompatibleContractVersionError, UnauthorizedRepositoryError, WebhookSignatureInvalidError
from app.infrastructure.observability import incr, structured_log


class GitHubAppTokenProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def build_app_jwt(self) -> str:
        if not self.settings.github_app_private_key or not self.settings.github_app_id:
            raise RuntimeError("GitHub App credentials are not configured.")
        now = int(time.time())
        payload = {"iat": now - 60, "exp": now + 540, "iss": self.settings.github_app_id}
        return jwt.encode(payload, self.settings.github_app_private_key, algorithm="RS256")

    def get_installation_token(self, installation_id: str | None = None) -> str:
        target_installation_id = installation_id or self.settings.github_app_installation_id
        token = self.build_app_jwt()
        with httpx.Client(timeout=20.0) as client:
            response = client.post(
                f"{self.settings.github_api_url}/app/installations/{target_installation_id}/access_tokens",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
            )
            response.raise_for_status()
            return response.json()["token"]


class GitHubConnector:
    def __init__(self, settings: Settings, token_provider: GitHubAppTokenProvider | None = None) -> None:
        self.settings = settings
        self.allowed_repositories = {item.strip() for item in settings.github_allowed_repositories.split(",") if item.strip()}
        self.token_provider = token_provider or GitHubAppTokenProvider(settings)

    def verify_signature(self, body: bytes, provided_signature: str | None) -> None:
        if not provided_signature:
            raise WebhookSignatureInvalidError("Missing GitHub signature.")
        computed = "sha256=" + hmac.new(
            self.settings.github_webhook_secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(computed, provided_signature):
            raise WebhookSignatureInvalidError("Invalid GitHub webhook signature.")

    def ensure_repository_allowed(self, repository_full_name: str) -> None:
        if repository_full_name not in self.allowed_repositories:
            raise UnauthorizedRepositoryError(f"Repository {repository_full_name} is not allowed.")

    def collect_product_changes(self, event_type: str, payload: dict[str, Any]) -> list[CollectedProductChange]:
        repository = payload["repository"]["full_name"]
        self.ensure_repository_allowed(repository)
        changes = self._extract_mock_or_remote_change_notes(event_type, payload)
        result: list[CollectedProductChange] = []
        for change in changes:
            if change["contract_version"].split(".", 1)[0] != "1":
                raise IncompatibleContractVersionError("Unsupported change-note schema major version.")
            if not change["eligible_for_communication"]:
                continue
            if change["confidential"]:
                continue
            if not change["deployment_proven"]:
                continue
            if change.get("target_client_key") and payload.get("target_client_key") and change["target_client_key"] != payload["target_client_key"]:
                continue
            result.append(
                CollectedProductChange(
                    repository_full_name=repository,
                    sha=change["sha"],
                    change_note_path=change["change_note_path"],
                    capability_key=change["capability_key"],
                    summary=change["summary"],
                    eligible_for_communication=change["eligible_for_communication"],
                    confidential=change["confidential"],
                    target_client_key=change.get("target_client_key", ""),
                    contract_version=change["contract_version"],
                    pr_number=change.get("pr_number"),
                    issue_numbers=change.get("issue_numbers", []),
                    release_tag=change.get("release_tag", ""),
                    deployment_ref=change.get("deployment_ref", ""),
                    production_status=change.get("production_status", ""),
                    deployment_proven=change.get("deployment_proven", False),
                    raw_payload=change,
                )
            )
        incr("github.product_changes.filtered", len(result))
        structured_log("github.product_changes.filtered", repository=repository, count=len(result), event_type=event_type)
        return result

    def poll_product_changes(self, repository_full_name: str, last_seen_sha: str = "") -> list[CollectedProductChange]:
        self.ensure_repository_allowed(repository_full_name)
        payload = {
            "repository": {"full_name": repository_full_name, "default_branch": "main"},
            "mock_change_notes": [],
            "after": last_seen_sha,
        }
        return self.collect_product_changes("weekly_poll", payload)

    def _extract_mock_or_remote_change_notes(self, event_type: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        if "mock_change_notes" in payload:
            return payload["mock_change_notes"]
        token = self.token_provider.get_installation_token(str(payload.get("installation", {}).get("id", self.settings.github_app_installation_id)))
        note_files = self._discover_note_files(event_type, payload)
        return [self._fetch_change_note(token, payload["repository"]["full_name"], payload.get("after") or payload.get("deployment", {}).get("sha") or payload.get("release", {}).get("target_commitish") or "", note_path, payload) for note_path in note_files]

    def _discover_note_files(self, event_type: str, payload: dict[str, Any]) -> list[str]:
        files: list[str] = []
        for commit in payload.get("commits", []):
            for item in commit.get("added", []) + commit.get("modified", []):
                if item.startswith(f"{self.settings.github_contract_path}/") and item.endswith(".yaml"):
                    files.append(item)
        if not files and payload.get("pull_request", {}).get("merged"):
            for item in payload.get("pull_request", {}).get("changed_files_list", []):
                if item.startswith(f"{self.settings.github_contract_path}/") and item.endswith(".yaml"):
                    files.append(item)
        return sorted(set(files))

    def _fetch_change_note(
        self,
        installation_token: str,
        repository_full_name: str,
        sha: str,
        note_path: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        owner, repo = repository_full_name.split("/", 1)
        with httpx.Client(timeout=20.0) as client:
            response = client.get(
                f"{self.settings.github_api_url}/repos/{owner}/{repo}/contents/{note_path}",
                params={"ref": sha},
                headers={
                    "Authorization": f"token {installation_token}",
                    "Accept": "application/vnd.github.raw+json",
                },
            )
            response.raise_for_status()
        note = yaml.safe_load(response.text)
        return {
            "sha": sha,
            "change_note_path": note_path,
            "capability_key": note["capability_key"],
            "summary": note["summary"],
            "eligible_for_communication": note["eligible_for_communication"],
            "confidential": note["confidential"],
            "target_client_key": note.get("target_client_key", ""),
            "contract_version": str(note["contract_version"]),
            "pr_number": payload.get("pull_request", {}).get("number"),
            "issue_numbers": payload.get("issue_numbers", []),
            "release_tag": payload.get("release", {}).get("tag_name", ""),
            "deployment_ref": payload.get("deployment", {}).get("sha", ""),
            "production_status": payload.get("deployment_status", {}).get("state", ""),
            "deployment_proven": payload.get("deployment_status", {}).get("environment") == "production"
            and payload.get("deployment_status", {}).get("state") == "success",
        }
