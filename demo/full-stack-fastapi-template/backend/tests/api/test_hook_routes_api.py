from fastapi.testclient import TestClient


def test_openapi_exposes_critical_mcp_hook_routes(client: TestClient) -> None:
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200, response.text

    paths = response.json()["paths"]
    required_paths = {
        "/api/v1/utils/health-check/",
        "/api/v1/topics/",
        "/api/v1/topics/{topic_id}/rollup",
        "/api/v1/context-packs/build",
        "/api/v1/cases/",
        "/api/v1/cases/{case_id}",
        "/api/v1/cases/{case_id}/memo",
        "/api/v1/cases/{case_id}/hydration",
        "/api/v1/threads/",
        "/api/v1/executions/",
        "/api/v1/executions/start",
        "/api/v1/executions/{execution_id}/events",
    }

    missing_paths = sorted(required_paths.difference(paths))
    assert not missing_paths, f"Missing critical MCP hook routes: {missing_paths}"
