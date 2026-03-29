# Coding Conventions

**Analysis Date:** 2026-03-28

## Naming Patterns

**Files:**
- TypeScript files under `mcp/enderai-api-mcp/src` use lower camelCase module names for multi-word files, such as `mcp/enderai-api-mcp/src/httpServer.ts`, `mcp/enderai-api-mcp/src/mcpAuth.ts`, and `mcp/enderai-api-mcp/src/deprecatedPathRewrite.ts`.
- TypeScript tests under `mcp/enderai-api-mcp/test` keep the source stem and append `.test.ts`, such as `mcp/enderai-api-mcp/test/http.test.ts` and `mcp/enderai-api-mcp/test/sessionAuth.test.ts`.
- Python application and test files use snake_case throughout `demo/full-stack-fastapi-template/backend/app` and `demo/full-stack-fastapi-template/backend/tests`, such as `demo/full-stack-fastapi-template/backend/app/core/topics.py` and `demo/full-stack-fastapi-template/backend/tests/api/test_topic_rollups_api.py`.

**Functions:**
- TypeScript functions use camelCase with explicit return types on exported APIs and most helpers, for example `loadConfig()` in `mcp/enderai-api-mcp/src/config.ts`, `enderaiFetch()` in `mcp/enderai-api-mcp/src/http.ts`, and `validateIncomingMcpBearerToken()` in `mcp/enderai-api-mcp/src/mcpAuth.ts`.
- Python functions use snake_case, including route handlers and helpers such as `read_topics()` in `demo/full-stack-fastapi-template/backend/app/api/routes/topics.py`, `apply_case_update()` in `demo/full-stack-fastapi-template/backend/app/core/cases.py`, and `authentication_token_from_email()` in `demo/full-stack-fastapi-template/backend/tests/utils/user.py`.
- Python tests use long behavior-first names that encode the scenario, such as `test_topic_access_and_matching_are_scoped_to_the_current_user()` in `demo/full-stack-fastapi-template/backend/tests/api/test_topic_rollups_api.py`.

**Variables:**
- TypeScript locals and parameters use camelCase, while module constants use `UPPER_SNAKE_CASE`; see `AUDIT_MAX_BYTES`, `TERMINAL_CASE_STATUSES`, and `DEFAULT_REUSE_WINDOW_SECONDS` in `mcp/enderai-api-mcp/src/mcpServer.ts`.
- Environment variable identifiers remain uppercase string literals in both subtrees, such as `ENDERAI_BASE_URL` in `mcp/enderai-api-mcp/src/config.ts` and `SECRET_KEY` / `POSTGRES_SERVER` in `demo/full-stack-fastapi-template/backend/app/core/config.py`.
- Python locals use snake_case; one-off module constants like `BACKEND_DIR` in `demo/full-stack-fastapi-template/backend/tests/conftest.py` still use uppercase.

**Types:**
- TypeScript favors `type` aliases over `interface`; every exported shape in `mcp/enderai-api-mcp/src/config.ts`, `mcp/enderai-api-mcp/src/http.ts`, `mcp/enderai-api-mcp/src/mcpAuth.ts`, and `mcp/enderai-api-mcp/src/deprecatedPathRewrite.ts` is declared with `export type`.
- TypeScript type names are PascalCase, including unions such as `McpAuthorizationResult` in `mcp/enderai-api-mcp/src/mcpAuth.ts`.
- Python models, DTOs, and ORM records use PascalCase class names in `demo/full-stack-fastapi-template/backend/app/models.py`, with suffixes that communicate role: `Create`, `Update`, `Public`, `Result`, and `View`.

## Code Style

**Formatting:**
- No committed ESLint, Prettier, or Biome config was detected for `mcp/enderai-api-mcp`; match the existing TypeScript house style in `mcp/enderai-api-mcp/src/*.ts`: double quotes, semicolons, trailing commas, and one blank line between import groups.
- TypeScript is statically enforced through `strict: true` in `mcp/enderai-api-mcp/tsconfig.json`; keep new source under `mcp/enderai-api-mcp/src` compatible with that setting.
- Python formatting is explicitly defined in `demo/full-stack-fastapi-template/backend/pyproject.toml` and executed via `demo/full-stack-fastapi-template/backend/scripts/format.sh`.
- `demo/full-stack-fastapi-template/backend/pyproject.toml` sets Ruff `target-version = "py310"` and ignores `E501`, `B008`, `W191`, and `B904`; preserve those expectations when editing Python files.

**Linting:**
- For Python, use `mypy app`, `ruff check app`, and `ruff format app --check` exactly as scripted in `demo/full-stack-fastapi-template/backend/scripts/lint.sh`.
- The Ruff rule set in `demo/full-stack-fastapi-template/backend/pyproject.toml` includes `E`, `W`, `F`, `I`, `B`, `C4`, `UP`, `ARG001`, and `T201`; avoid stray `print()` calls outside explicitly exempted files.
- For TypeScript, the primary committed gate is the compiler via `npm run build` in `mcp/enderai-api-mcp/package.json`; there is no separate lint command in that package.

## Import Organization

**Order:**
1. TypeScript files group Node built-ins first, package imports second, and relative imports last, as shown in `mcp/enderai-api-mcp/src/httpServer.ts`, `mcp/enderai-api-mcp/src/mcpServer.ts`, and `mcp/enderai-api-mcp/test/caseWorkflowTools.test.ts`.
2. Python files group standard-library imports first, third-party imports second, and `app.*` / `tests.*` imports last, as shown in `demo/full-stack-fastapi-template/backend/app/api/deps.py`, `demo/full-stack-fastapi-template/backend/app/core/config.py`, and `demo/full-stack-fastapi-template/backend/tests/conftest.py`.
3. Keep blank lines between import groups in both subtrees. The existing files do this consistently.

**Path Aliases:**
- No TypeScript path aliases are configured in `mcp/enderai-api-mcp/tsconfig.json`; use relative imports such as `./config.js` and `../src/http.js`.
- Python uses absolute package imports rooted at `app` and `tests`, such as `from app.core.config import settings` in `demo/full-stack-fastapi-template/backend/app/main.py` and `from tests.utils.user import authentication_token_from_email` in `demo/full-stack-fastapi-template/backend/tests/api/test_topic_rollups_api.py`.

## Error Handling

**Patterns:**
- TypeScript helper modules throw plain `Error` for invalid configuration or unsafe inputs, for example `loadConfig()` in `mcp/enderai-api-mcp/src/config.ts` and `assertPathIsSafe()` in `mcp/enderai-api-mcp/src/http.ts`.
- TypeScript boundary modules catch and translate failures close to the transport edge: CLI entrypoints in `mcp/enderai-api-mcp/src/index.ts` and `mcp/enderai-api-mcp/src/httpServer.ts` log to `console.error` and exit, while tool handlers in `mcp/enderai-api-mcp/src/mcpServer.ts` format failures through `toolError()`.
- `mcp/enderai-api-mcp/src/mcpServer.ts` validates structured tool inputs with `zod` schemas before making backend calls. New MCP tools should follow that pattern rather than hand-rolling unchecked `unknown` access.
- Python API boundaries raise `HTTPException` with explicit `status_code` and `detail` in `demo/full-stack-fastapi-template/backend/app/api/deps.py`, `demo/full-stack-fastapi-template/backend/app/api/routes/topics.py`, `demo/full-stack-fastapi-template/backend/app/api/routes/cases.py`, and related route modules.
- Python core helpers raise `ValueError` for internal misuse or invalid parameters, as in `demo/full-stack-fastapi-template/backend/app/core/config.py`, `demo/full-stack-fastapi-template/backend/app/core/search.py`, and `demo/full-stack-fastapi-template/backend/app/core/topics.py`. Keep transport-layer exceptions out of core modules.
- When mutating Pydantic/SQLModel-backed payloads, Python routes use `model_dump(exclude_unset=True)` or `model_dump(mode="json")` before applying updates, as shown in `demo/full-stack-fastapi-template/backend/app/api/routes/topics.py` and `demo/full-stack-fastapi-template/backend/app/api/routes/cases.py`.

## Logging

**Framework:** Mixed: `console` in the TypeScript MCP package and the standard `logging` module in the FastAPI template.

**Patterns:**
- Keep TypeScript logging at entrypoints and smoke scripts only. `mcp/enderai-api-mcp/src/index.ts`, `mcp/enderai-api-mcp/src/httpServer.ts`, `mcp/enderai-api-mcp/test/smoke.ts`, and `mcp/enderai-api-mcp/test/streamableHttpSmoke.ts` all use direct console logging, often behind `eslint-disable-next-line no-console`.
- Python startup and utility scripts use module loggers initialized with `logging.basicConfig(level=logging.INFO)` in `demo/full-stack-fastapi-template/backend/app/backend_pre_start.py`, `demo/full-stack-fastapi-template/backend/app/tests_pre_start.py`, `demo/full-stack-fastapi-template/backend/app/initial_data.py`, and `demo/full-stack-fastapi-template/backend/app/utils.py`.
- No cross-cutting structured logging wrapper is present. New code should follow the local subsystem’s existing practice instead of introducing a third style.

## Comments

**When to Comment:**
- TypeScript comments are brief and intent-focused. Keep comments for security, platform quirks, and compatibility notes, as seen in `mcp/enderai-api-mcp/src/http.ts`, `mcp/enderai-api-mcp/src/httpServer.ts`, and `mcp/enderai-api-mcp/src/deprecatedPathRewrite.ts`.
- Python uses fewer comments and leans on naming. Inline comments mostly explain configuration exceptions or operational caveats, such as the secret-handling note in `demo/full-stack-fastapi-template/backend/app/core/config.py`.

**JSDoc/TSDoc:**
- Not used in the TypeScript MCP package. New TS code should prefer clear naming plus short inline comments over large docblocks.
- Python docstrings exist selectively in tests and helpers, for example `authentication_token_from_email()` in `demo/full-stack-fastapi-template/backend/tests/utils/user.py` and password-hash upgrade tests in `demo/full-stack-fastapi-template/backend/tests/api/routes/test_login.py`.

## Function Design

**Size:** 
- Keep small pure helpers for normalization and transformation, as in `mcp/enderai-api-mcp/src/http.ts`, `mcp/enderai-api-mcp/src/sessionAuth.ts`, and `demo/full-stack-fastapi-template/backend/app/core/cases.py`.
- Larger orchestrators are accepted at boundary layers when they coordinate transport or persistence, such as `createMcpServer()` in `mcp/enderai-api-mcp/src/mcpServer.ts`, `main()` in `mcp/enderai-api-mcp/src/httpServer.ts`, and `refresh_topic_rollup()` in `demo/full-stack-fastapi-template/backend/app/core/topics.py`.

**Parameters:**
- TypeScript prefers options objects once a function needs more than one contextual argument, for example `validateIncomingMcpBearerToken(args)` in `mcp/enderai-api-mcp/src/mcpAuth.ts` and `resolveSessionBackendBearerToken({ mcpAuth })` in `mcp/enderai-api-mcp/src/sessionAuth.ts`.
- Python routes rely on FastAPI dependency injection and typed parameters in function signatures, as in `demo/full-stack-fastapi-template/backend/app/api/routes/cases.py` and `demo/full-stack-fastapi-template/backend/app/api/routes/topics.py`.
- Python non-route helpers sometimes use keyword-only sections with `*` for clarity, especially in `demo/full-stack-fastapi-template/backend/app/core/topics.py` and `demo/full-stack-fastapi-template/backend/tests/utils/user.py`.

**Return Values:**
- TypeScript functions return typed objects or discriminated unions rather than throwing for expected auth outcomes; see `McpAuthorizationResult` in `mcp/enderai-api-mcp/src/mcpAuth.ts`.
- Python domain and route functions return SQLModel/Pydantic models, lists of models, or simple tuples, such as `tuple[CaseRecord, Topic]` from `_get_visible_case_and_topic()` in `demo/full-stack-fastapi-template/backend/app/api/routes/cases.py`.

## Module Design

**Exports:**
- TypeScript modules use named exports only. Follow the source pattern in `mcp/enderai-api-mcp/src/config.ts`, `mcp/enderai-api-mcp/src/http.ts`, and `mcp/enderai-api-mcp/src/mcpServer.ts`.
- Python organizes code by layer: route registration in `demo/full-stack-fastapi-template/backend/app/api/main.py`, dependency helpers in `demo/full-stack-fastapi-template/backend/app/api/deps.py`, domain logic in `demo/full-stack-fastapi-template/backend/app/core/*.py`, and schema/model definitions in `demo/full-stack-fastapi-template/backend/app/models.py`.

**Barrel Files:**
- Not detected in `mcp/enderai-api-mcp/src`; import directly from the defining module.
- Python uses package-level router assembly in `demo/full-stack-fastapi-template/backend/app/api/main.py`, but otherwise imports concrete modules directly.

---

*Convention analysis: 2026-03-28*
