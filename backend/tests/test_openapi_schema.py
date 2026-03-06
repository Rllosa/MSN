"""Schema contract tests for the OpenAPI spec.

Calls app.openapi() directly — no DB, no network, no env vars required.
These tests fail if any endpoint loses its response model or /health is removed.
"""

from __future__ import annotations

from app.main import app


def test_health_endpoint_in_schema() -> None:
    schema = app.openapi()
    assert "/health" in schema["paths"]


def test_health_has_200_with_json_response() -> None:
    schema = app.openapi()
    responses = schema["paths"]["/health"]["get"]["responses"]
    assert "200" in responses
    assert "application/json" in responses["200"]["content"]


def test_all_routes_have_200_response_model() -> None:
    schema = app.openapi()
    for path, methods in schema["paths"].items():
        for method, operation in methods.items():
            assert "200" in operation.get(
                "responses", {}
            ), f"{method.upper()} {path} missing 200 response model"
