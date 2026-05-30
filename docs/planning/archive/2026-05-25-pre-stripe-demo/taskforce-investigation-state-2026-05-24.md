# Taskforce Investigation State - 2026-05-24

## OpenAI embeddings traceback

### Symptom

Production logs showed:

```text
openai.RateLimitError: Error code: 429 - insufficient_quota
```

The traceback was adjacent to:

```text
OPTIONS /api/v1/login/firebase-token HTTP/1.1" 400
```

### Finding

The OpenAI traceback is from the background Taskforce Search indexer, not the Firebase login route.

Call path:

```text
app.main lifespan
  -> app.core.search.indexing.run_forever
  -> sweep_documents_once
  -> upsert_record
  -> safe_embed_batch
  -> embed_batch
  -> OpenAI embeddings API
```

`app.main` starts the search indexer whenever `OPENAI_API_KEY` is configured. The failing API response is OpenAI `insufficient_quota`, which means the configured key has no usable quota or billing allowance for embeddings.

### Work completed

Local branch/worktree:

```text
/home/alexlee/dev/WORKTREE-taskforce-org-member-removal-backend
branch: feature/org-member-removal
```

Changed:

```text
demo/full-stack-fastapi-template/backend/app/core/search/embeddings.py
demo/full-stack-fastapi-template/backend/tests/core/test_search_embeddings.py
```

Behavior after patch:

- OpenAI SDK quota/rate/auth failures are translated into `EmbeddingsUnavailableError`.
- Search requests keep using the existing clean 503 path for embedding outages.
- The background indexer logs a warning instead of a full raw SDK traceback for known OpenAI outage modes.
- Non-OpenAI unexpected exceptions still propagate to the existing defensive logging path.

Validation run:

```bash
uv run ruff check app/core/search/embeddings.py tests/core/test_search_embeddings.py
env PROJECT_NAME=Taskforce POSTGRES_SERVER=localhost POSTGRES_USER=postgres POSTGRES_PASSWORD=postgres FIRST_SUPERUSER=test@example.com FIRST_SUPERUSER_PASSWORD=testpassword SECRET_KEY=testsecret uv run pytest --confcutdir=tests/core tests/core/test_search_embeddings.py
env PROJECT_NAME=Taskforce POSTGRES_SERVER=localhost POSTGRES_USER=postgres POSTGRES_PASSWORD=postgres FIRST_SUPERUSER=test@example.com FIRST_SUPERUSER_PASSWORD=testpassword SECRET_KEY=testsecret uv run mypy app/core/search/embeddings.py
git diff --check
```

Focused pytest result:

```text
2 passed
```

Full normal pytest is blocked in this local environment because the repo autouse fixture runs migrations against Postgres and no Postgres service is listening on `localhost:5432`.

### Remaining production action

The code patch improves failure handling, but it does not restore embeddings. To restore Search indexing/query embeddings, fix the Render `OPENAI_API_KEY` billing/quota or temporarily unset `OPENAI_API_KEY` to stop the background indexer from starting.

## Firebase login CORS failure after URL switch

### Symptom

Browser console from `https://taskforce.tools`:

```text
Access to XMLHttpRequest at 'https://enderai-backend.onrender.com/api/v1/login/firebase-token'
from origin 'https://taskforce.tools' has been blocked by CORS policy:
Response to preflight request doesn't pass access control check:
No 'Access-Control-Allow-Origin' header is present on the requested resource.

POST https://enderai-backend.onrender.com/api/v1/login/firebase-token net::ERR_FAILED
```

### Live verification

Command:

```bash
curl -i -X OPTIONS 'https://enderai-backend.onrender.com/api/v1/login/firebase-token' \
  -H 'Origin: https://taskforce.tools' \
  -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: content-type'
```

Observed:

```text
HTTP/2 400
...
Disallowed CORS origin
```

Additional live checks:

- `https://enderai-backend.onrender.com/api/v1/utils/health-check/` returns `HTTP 200`, so the backend is up.
- `Origin: http://localhost:5173` is allowed.
- `Origin: https://taskforce.tools`, `https://www.taskforce.tools`, `https://enderai.xyz`, and `https://www.enderai.xyz` are currently rejected.

That means the deployed backend is running with a CORS allowlist equivalent to local defaults, not the new production frontend origin.

### Local code/config finding

Backend CORS is configured in:

```text
demo/full-stack-fastapi-template/backend/app/main.py
demo/full-stack-fastapi-template/backend/app/core/config.py
render.yaml
```

`app.main` installs Starlette `CORSMiddleware` with `settings.all_cors_origins`.

Before the fix, checked-in `render.yaml` still used:

```text
BACKEND_CORS_ORIGINS=https://enderai.xyz,https://www.enderai.xyz
FRONTEND_HOST=https://www.enderai.xyz
```

Also, `expand_cors_origin_aliases()` only knew the `enderai.xyz` apex/www pair.

### Work completed

Changed:

```text
render.yaml
demo/full-stack-fastapi-template/backend/app/core/config.py
```

New blueprint values:

```text
BACKEND_CORS_ORIGINS=https://taskforce.tools,https://www.taskforce.tools,https://enderai.xyz,https://www.enderai.xyz
FRONTEND_HOST=https://taskforce.tools
```

New alias behavior:

```text
https://taskforce.tools -> https://www.taskforce.tools
https://www.taskforce.tools -> https://taskforce.tools
```

### Remaining production action

This will not fix the already-deployed Render service until the backend env/config is applied and the service redeploys.

Fastest dashboard fix:

```text
Render -> enderai-backend -> Environment

BACKEND_CORS_ORIGINS=https://taskforce.tools,https://www.taskforce.tools,https://enderai.xyz,https://www.enderai.xyz
FRONTEND_HOST=https://taskforce.tools
```

Then redeploy `enderai-backend`.

Post-redeploy verification:

```bash
curl -i -X OPTIONS 'https://enderai-backend.onrender.com/api/v1/login/firebase-token' \
  -H 'Origin: https://taskforce.tools' \
  -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: content-type'
```

Expected:

```text
HTTP/2 200
access-control-allow-origin: https://taskforce.tools
```

If Firebase auth still fails after CORS is fixed, verify Firebase Authentication authorized domains include:

```text
taskforce.tools
www.taskforce.tools
```
