from __future__ import annotations

from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from app.infrastructure.connectors.mapsi_site import MapsiSiteConnector, build_mapsi_site_config
from app.infrastructure.connectors.mapsi_site_contract import get_request_example
from app.mock_mapsi_site_server import app as mapsi_site_mock_app


class ContractMapsiSiteClientTest:
    def setup_method(self) -> None:
        self.spec = yaml.safe_load(Path("contracts/mapsi_site/openapi.yaml").read_text(encoding="utf-8"))

    def test_openapi_request_example_creates_a_valid_draft(self) -> None:
        from app.core.config import get_settings

        settings = get_settings()
        settings.mapsi_site_base_url = "http://testserver"
        settings.mapsi_site_public_base_url = "https://www.mapsi.fr"
        settings.mapsi_site_api_token = "mapsi-site-test-token"
        settings.mapsi_site_verify_tls = False
        connector = MapsiSiteConnector(build_mapsi_site_config(settings), client=TestClient(mapsi_site_mock_app))

        payload = get_request_example("/api/growth/news", "post")
        response = connector.create_draft(payload, correlation_id="contract-mapsi-site")

        schema = self.spec["paths"]["/api/growth/news"]["post"]["responses"]["201"]["content"]["application/json"]["schema"]
        self._assert_schema_matches(schema, response)

    def test_openapi_error_examples_keep_stable_codes(self) -> None:
        responses = self.spec["components"]["responses"]

        assert responses["AuthenticationRequired"]["content"]["application/json"]["example"]["error"]["code"] == "AUTHENTICATION_REQUIRED"
        assert responses["AuthenticationInvalid"]["content"]["application/json"]["example"]["error"]["code"] == "AUTHENTICATION_INVALID"
        assert responses["ArticleNotFound"]["content"]["application/json"]["example"]["error"]["code"] == "ARTICLE_NOT_FOUND"
        assert responses["InvalidContent"]["content"]["application/json"]["example"]["error"]["code"] == "INVALID_CONTENT"
        assert responses["VersionConflict"]["content"]["application/json"]["example"]["error"]["code"] == "VERSION_CONFLICT"
        assert responses["PublicationNotAllowed"]["content"]["application/json"]["example"]["error"]["code"] == "PUBLICATION_NOT_ALLOWED"

    def _assert_schema_matches(self, schema: dict, value) -> None:
        if "$ref" in schema:
            schema = self._resolve_ref(schema["$ref"])
        if schema.get("nullable") and value is None:
            return
        schema_type = schema.get("type")
        if schema_type == "object":
            assert isinstance(value, dict)
            for key in schema.get("required", []):
                assert key in value
            for key, child in schema.get("properties", {}).items():
                if key in value:
                    self._assert_schema_matches(child, value[key])
            return
        if schema_type == "array":
            assert isinstance(value, list)
            for item in value:
                self._assert_schema_matches(schema["items"], item)
            return
        if "enum" in schema and value is not None:
            assert value in schema["enum"]
        if schema_type == "string":
            assert isinstance(value, str)
        elif schema_type == "integer":
            assert isinstance(value, int)
        elif schema_type == "boolean":
            assert isinstance(value, bool)

    def _resolve_ref(self, ref: str) -> dict:
        node = self.spec
        for segment in ref.removeprefix("#/").split("/"):
            node = node[segment]
        return node
