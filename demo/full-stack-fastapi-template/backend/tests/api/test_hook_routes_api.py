from fastapi.testclient import TestClient


def test_openapi_exposes_critical_mcp_hook_routes(client: TestClient) -> None:
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200, response.text

    paths = response.json()["paths"]
    # V1 (topics/cases/skills/context-packs) was removed; the MCP tools now
    # operate over V2 documents. Guard that those routes stay exposed.
    required_paths = {
        "/api/v1/utils/health-check/",
        "/api/v1/v2/documents/",
        "/api/v1/v2/documents/{document_id}",
    }

    missing_paths = sorted(required_paths.difference(paths))
    assert not missing_paths, f"Missing critical MCP hook routes: {missing_paths}"
