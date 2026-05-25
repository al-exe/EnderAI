# Testing Patterns

**Analysis Date:** 2026-03-28

## Test Framework

**Runner:**
- TypeScript tests in `mcp/enderai-api-mcp/test` run on `vitest` as declared in `mcp/enderai-api-mcp/package.json`.
- No `vitest.config.*` file is committed under `mcp/enderai-api-mcp`; the suite relies on Vitest defaults plus direct test-local setup in files like `mcp/enderai-api-mcp/test/http.test.ts` and `mcp/enderai-api-mcp/test/caseWorkflowTools.test.ts`.
- Python tests in `demo/full-stack-fastapi-template/backend/tests` run on `pytest`, with coverage and lint/test-related configuration embedded in `demo/full-stack-fastapi-template/backend/pyproject.toml`.

**Assertion Library:**
- TypeScript uses Vitest’s built-in `expect` assertions in `mcp/enderai-api-mcp/test/http.test.ts`, `mcp/enderai-api-mcp/test/mcpAuth.test.ts`, and `mcp/enderai-api-mcp/test/caseWorkflowTools.test.ts`.
- Python uses plain `assert` statements, FastAPI `TestClient`, and SQLModel session inspection in `demo/full-stack-fastapi-template/backend/tests/conftest.py`, `demo/full-stack-fastapi-template/backend/tests/api/test_cases_api.py`, and `demo/full-stack-fastapi-template/backend/tests/crud/test_user.py`.

**Run Commands:**
```bash
cd mcp/enderai-api-mcp && npm test              # Run the committed Vitest suite
cd mcp/enderai-api-mcp && npm run smoke:http    # Run the streamable HTTP smoke harness
cd demo/full-stack-fastapi-template/backend && bash scripts/test.sh  # Pytest with coverage report + HTML
```

## Test File Organization

**Location:**
- TypeScript tests live in a separate `mcp/enderai-api-mcp/test` directory instead of being co-located with `src`.
- Python tests live in a separate `demo/full-stack-fastapi-template/backend/tests` tree, partitioned by layer: `api`, `crud`, `scripts`, and `utils`.

**Naming:**
- TypeScript test files use `<subject>.test.ts`, such as `mcp/enderai-api-mcp/test/http.test.ts` and `mcp/enderai-api-mcp/test/mcpAuth.test.ts`.
- Python uses `test_*.py`, such as `demo/full-stack-fastapi-template/backend/tests/api/test_topic_rollups_api.py`, `demo/full-stack-fastapi-template/backend/tests/crud/test_user.py`, and `demo/full-stack-fastapi-template/backend/tests/scripts/test_backend_pre_start.py`.
- Python route tests that target the original FastAPI template endpoints are nested under `demo/full-stack-fastapi-template/backend/tests/api/routes`.

**Structure:**
```text
mcp/enderai-api-mcp/
├── src/
└── test/
    ├── *.test.ts
    ├── hookHealth.ts
    ├── smoke.ts
    └── streamableHttpSmoke.ts

demo/full-stack-fastapi-template/backend/
├── app/
├── scripts/
└── tests/
    ├── conftest.py
    ├── api/
    │   ├── routes/
    │   └── test_*_api.py
    ├── crud/
    ├── scripts/
    └── utils/
```

## Test Structure

**Suite Organization:**
```typescript
describe("validateIncomingMcpBearerToken", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it("validates per-user MCP tokens against the backend", async () => {
    mockFetch.mockResolvedValueOnce(new Response(JSON.stringify({ valid: true }), {
      status: 200,
      headers: { "content-type": "application/json" },
    }));

    const result = await validateIncomingMcpBearerToken({
      providedBearerToken: "user-mcp-token",
      sharedBearerToken: "shared-token",
    });

    expect(result).toEqual({
      ok: true,
      via: "per_user",
      backendBearerToken: "user-mcp-token",
    });
  });
});
```

**Patterns:**
- TypeScript suites use `describe()` / `it()` blocks with `beforeEach()` for mock reset, as shown in `mcp/enderai-api-mcp/test/mcpAuth.test.ts`.
- TypeScript integration-style tests create disposable harnesses and close them in `finally`, as shown in `mcp/enderai-api-mcp/test/caseWorkflowTools.test.ts`.
- Python centralizes heavyweight setup in `demo/full-stack-fastapi-template/backend/tests/conftest.py`: Alembic migrations run once per session, `init_db()` is called once, and cleanup deletes key tables after the session fixture yields.
- Python API tests usually perform a full request sequence, assert status code first, then assert response body fields. See `demo/full-stack-fastapi-template/backend/tests/api/test_topic_rollups_api.py` and `demo/full-stack-fastapi-template/backend/tests/api/test_cases_api.py`.

## Mocking

**Framework:** Vitest `vi.fn()` on the TypeScript side; `unittest.mock.patch` and `MagicMock` on the Python side.

**Patterns:**
```typescript
const mockFetch = vi.fn();
// @ts-expect-error - vitest in Node.
globalThis.fetch = mockFetch;

mockFetch.mockResolvedValueOnce(
  new Response(JSON.stringify({ ok: true }), {
    status: 200,
    headers: { "content-type": "application/json" },
  }),
);
```

```python
with (
    patch("app.backend_pre_start.Session", return_value=session_mock),
    patch("app.backend_pre_start.select", return_value=select1),
    patch.object(logger, "info"),
    patch.object(logger, "error"),
    patch.object(logger, "warn"),
):
    init(engine_mock)
```

**What to Mock:**
- In `mcp/enderai-api-mcp/test/http.test.ts` and `mcp/enderai-api-mcp/test/mcpAuth.test.ts`, mock outbound `fetch` so unit tests do not hit the network.
- In `mcp/enderai-api-mcp/test/caseWorkflowTools.test.ts`, keep loopback `http://127.0.0.1` requests real while mocking backend-facing `fetch` calls. That split is part of the existing harness design.
- In `demo/full-stack-fastapi-template/backend/tests/api/routes/test_login.py` and `demo/full-stack-fastapi-template/backend/tests/api/routes/test_users.py`, patch SMTP-related settings or email send helpers instead of attempting real email delivery.
- In `demo/full-stack-fastapi-template/backend/tests/scripts/test_backend_pre_start.py`, patch the database session and logger around startup probes.

**What NOT to Mock:**
- Do not mock the MCP transport layer when the test is supposed to validate initialization or request routing. `mcp/enderai-api-mcp/test/caseWorkflowTools.test.ts` and `mcp/enderai-api-mcp/test/streamableHttpSmoke.ts` intentionally boot real in-process HTTP/MCP transport objects.
- Do not mock the FastAPI app or route stack in API tests. `demo/full-stack-fastapi-template/backend/tests/conftest.py` supplies a real `TestClient(app)` and real SQLModel session.
- Do not bypass OpenAPI route checks with synthetic objects when validating hook exposure. `demo/full-stack-fastapi-template/backend/tests/api/test_hook_routes_api.py` uses the real `/api/v1/openapi.json` response.

## Fixtures and Factories

**Test Data:**
```python
@pytest.fixture(scope="module")
def normal_user_token_headers(client: TestClient, db: Session) -> dict[str, str]:
    return authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )

def random_email() -> str:
    return f"{random_lower_string()}@{random_lower_string()}.com"
```

**Location:**
- Shared pytest fixtures live in `demo/full-stack-fastapi-template/backend/tests/conftest.py`.
- Python helper factories and auth helpers live in `demo/full-stack-fastapi-template/backend/tests/utils/user.py` and `demo/full-stack-fastapi-template/backend/tests/utils/utils.py`.
- TypeScript helper functions are test-local rather than centralized. `mcp/enderai-api-mcp/test/caseWorkflowTools.test.ts` defines `jsonResponse()` and `createHarness()` inside the test file, while `mcp/enderai-api-mcp/test/hookHealth.ts` holds shared smoke/assert helpers.

## Coverage

**Requirements:** No numeric threshold is enforced in committed config.

**View Coverage:**
```bash
cd demo/full-stack-fastapi-template/backend && bash scripts/test.sh
```

- Python coverage is configured in `demo/full-stack-fastapi-template/backend/pyproject.toml` with `source = ["app"]`, `dynamic_context = "test_function"`, `show_missing = true`, and HTML output enabled.
- TypeScript has no dedicated coverage command, coverage thresholds, or Vitest coverage config in `mcp/enderai-api-mcp/package.json` or adjacent config files.
- Coverage signals are strongest for backend API flows and MCP workflow integration; there is less infrastructure around measuring TS unit coverage formally.

## Test Types

**Unit Tests:**
- TypeScript unit tests target small helpers and boundary logic, such as `mcp/enderai-api-mcp/test/http.test.ts`, `mcp/enderai-api-mcp/test/mcpAuth.test.ts`, and `mcp/enderai-api-mcp/test/sessionAuth.test.ts`.
- Python CRUD and utility behavior is covered by focused tests like `demo/full-stack-fastapi-template/backend/tests/crud/test_user.py` and `demo/full-stack-fastapi-template/backend/tests/scripts/test_backend_pre_start.py`.

**Integration Tests:**
- `mcp/enderai-api-mcp/test/caseWorkflowTools.test.ts` is the strongest TypeScript integration suite. It brings up a real in-process MCP server/client harness and validates the guided begin/update/finish workflow.
- Python API tests in `demo/full-stack-fastapi-template/backend/tests/api/test_cases_api.py`, `demo/full-stack-fastapi-template/backend/tests/api/test_topic_rollups_api.py`, `demo/full-stack-fastapi-template/backend/tests/api/test_search_api.py`, and `demo/full-stack-fastapi-template/backend/tests/api/test_demo_mode_api.py` exercise full request/response flows against the real FastAPI app.

**E2E Tests:**
- No browser/UI E2E framework is present in this repo snapshot.
- The closest end-to-end checks are the smoke programs `mcp/enderai-api-mcp/test/smoke.ts` and `mcp/enderai-api-mcp/test/streamableHttpSmoke.ts`, which validate MCP tool listing and required backend hook routes.

## Common Patterns

**Async Testing:**
```typescript
it("rejects non-absolute path", async () => {
  await expect(
    enderaiFetch({ method: "GET", path: "https://example.com" }),
  ).rejects.toThrow(/must start with/);
});
```

```python
response = client.post("/api/v1/context-packs/build", headers=headers, json=payload)
assert response.status_code == 200, response.text
assert response.json()["selected_topic_ids"] == [topic_id]
```

- TypeScript async tests await promise assertions directly, as in `mcp/enderai-api-mcp/test/http.test.ts`.
- Python API tests are synchronous at the callsite because they use `fastapi.testclient.TestClient`, even when validating async routes like `health_check()` in `demo/full-stack-fastapi-template/backend/app/api/routes/utils.py`.

**Error Testing:**
```typescript
const beforeBegin = await harness.client.callTool({
  name: "enderai_update_case",
  arguments: { summary_current: "Should fail before begin" },
});
expect(summarizeToolText(beforeBegin.content)).toContain(
  "Run enderai_begin_case first or provide case_id",
);
```

```python
response = client.get(f"/api/v1/topics/{topic_id}", headers=other_headers)
assert response.status_code == 404, response.text
```

- TypeScript error tests often validate a user-facing error string after exercising the real tool entrypoint, as in `mcp/enderai-api-mcp/test/caseWorkflowTools.test.ts`.
- Python error tests assert the transport status code and, when relevant, the response body detail, as in `demo/full-stack-fastapi-template/backend/tests/api/test_topic_rollups_api.py`, `demo/full-stack-fastapi-template/backend/tests/api/routes/test_login.py`, and `demo/full-stack-fastapi-template/backend/tests/api/routes/test_agent_credentials.py`.

---

*Testing analysis: 2026-03-28*
