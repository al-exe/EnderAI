from datetime import timedelta
from typing import Any

from sqlmodel import Session, select

from app.core.cases import is_terminal_case_status, normalize_context_pack_snapshot
from app.models import CaseRecord, Topic, User, get_datetime_utc

DEMO_SEED_VERSION = 1
ALLOWED_CHANGE_KINDS = {"code", "config", "infra", "docs", "test"}
CHANGE_KIND_ALIASES = {"sql": "config"}


def _command(cmd: str, purpose: str, result: str) -> dict[str, Any]:
    return {
        "cmd": cmd,
        "purpose": purpose,
        "salient_result": result,
    }


def _hypothesis(statement: str, status: str, evidence: str) -> dict[str, Any]:
    return {
        "statement": statement,
        "status": status,
        "evidence": evidence,
    }


def _change(
    kind: str,
    summary: str,
    files: list[str],
    refs: list[str],
) -> dict[str, Any]:
    normalized_kind = CHANGE_KIND_ALIASES.get(kind, kind)
    if normalized_kind not in ALLOWED_CHANGE_KINDS:
        normalized_kind = "code"

    return {
        "kind": normalized_kind,
        "summary": summary,
        "files": files,
        "refs": refs,
    }


def _case(
    *,
    title: str,
    status: str,
    source: str,
    input_summary: str,
    summary_current: str,
    files: list[str],
    symbols: list[str],
    errors: list[str],
    symptoms: list[str],
    commands: list[dict[str, Any]],
    hypotheses: list[dict[str, Any]],
    changes: list[dict[str, Any]],
    outcome: str,
    next_steps: list[str],
    matched_signals: list[str],
    opened_days_ago: int,
    updated_days_ago: int,
) -> dict[str, Any]:
    return {
        "title": title,
        "status": status,
        "source": source,
        "input_summary": input_summary,
        "summary_current": summary_current,
        "files": files,
        "symbols": symbols,
        "errors": errors,
        "symptoms": symptoms,
        "commands": commands,
        "hypotheses": hypotheses,
        "changes": changes,
        "outcome": outcome,
        "next_steps": next_steps,
        "matched_signals": matched_signals,
        "opened_days_ago": opened_days_ago,
        "updated_days_ago": updated_days_ago,
    }


def _topic(
    *,
    key: str,
    title: str,
    description: str,
    aliases: list[str],
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "description": description,
        "aliases": aliases,
        "cases": cases,
    }


DEMO_TOPICS: list[dict[str, Any]] = [
    _topic(
        key="postgres-connection-storms",
        title="Postgres Connection Storm Under Autoscaling",
        description="Investigations into pool saturation, replica lag, and ORM behavior during traffic spikes.",
        aliases=["database scaling", "pool exhaustion", "pgbouncer"],
        cases=[
            _case(
                title="Pgbouncer saturation after worker autoscaling",
                status="resolved",
                source="codex",
                input_summary="API latency jumped after scaling background workers; pods were healthy but new requests stalled waiting on DB sockets.",
                summary_current="The worker autoscaler amplified burst concurrency faster than pgbouncer transaction pools could recycle connections.",
                files=[
                    "backend/app/db/pool.py",
                    "infra/k8s/worker-hpa.yaml",
                    "infra/terraform/rds.tf",
                ],
                symbols=["PoolManager", "open_transaction", "max_client_conn"],
                errors=["remaining connection slots are reserved", "too many clients already"],
                symptoms=["p95 latency spiked after autoscale", "idle pods still showed blocked requests"],
                commands=[
                    _command("kubectl top pods -n api", "compare load before and after scale-out", "CPU stayed modest; request wait time moved to DB"),
                    _command("psql -c \"select * from pg_stat_activity\"", "inspect connection pressure", "most sessions were waiting on client read/write"),
                    _command("kubectl logs deploy/pgbouncer", "verify pool churn", "pool wait time grew with worker count"),
                ],
                hypotheses=[
                    _hypothesis("The autoscaler is outpacing transaction-pool recycling.", "supported", "Wait metrics grew linearly with worker replica count."),
                    _hypothesis("RDS max_connections was mis-sized for the instance class.", "open", "Headroom was thin but not the first trigger."),
                ],
                changes=[
                    _change("infra", "Capped worker burst scaling and raised pgbouncer reserve pool.", ["infra/k8s/worker-hpa.yaml", "infra/terraform/rds.tf"], ["PR-418"]),
                    _change("code", "Moved a long-lived report query off the request path.", ["backend/app/db/pool.py"], ["KAN-124"]),
                ],
                outcome="Autoscaling no longer creates a self-inflicted connection storm during burst traffic.",
                next_steps=["Add pool wait time to the default dashboard", "Load-test replica promotion behavior"],
                matched_signals=["pgbouncer", "connection slots", "autoscaling"],
                opened_days_ago=18,
                updated_days_ago=17,
            ),
            _case(
                title="Prepared statement churn with Prisma on transaction pooling",
                status="done",
                source="cursor",
                input_summary="Intermittent query failures only appeared behind pgbouncer transaction pooling and clustered around prepared statements.",
                summary_current="Prisma was assuming session-level prepared statements, which transaction pooling invalidated between requests.",
                files=[
                    "services/orders/prisma/schema.prisma",
                    "services/orders/src/db.ts",
                    "ops/pgbouncer/pgbouncer.ini",
                ],
                symbols=["PrismaClient", "pgbouncer", "statement_cache_size"],
                errors=["prepared statement does not exist", "cached plan must not change result type"],
                symptoms=["query retries hid the issue for low traffic", "only pooled environments failed"],
                commands=[
                    _command("bun test services/orders/test/db.integration.ts", "reproduce prepared statement errors in CI config", "transaction pooling reproduced the failure"),
                    _command("SHOW CONFIG", "compare pgbouncer flags", "max_prepared_statements was disabled"),
                ],
                hypotheses=[
                    _hypothesis("The ORM is relying on session affinity that transaction pooling breaks.", "supported", "Errors disappeared after disabling prepared statements."),
                    _hypothesis("The issue is Postgres version specific.", "disproven", "It reproduced on both 14 and 16."),
                ],
                changes=[
                    _change("config", "Disabled prepared statements for pooled production traffic.", ["services/orders/src/db.ts", "ops/pgbouncer/pgbouncer.ini"], ["PR-426"]),
                ],
                outcome="Order-service traffic stopped flaking under pooled production traffic.",
                next_steps=["Benchmark the perf hit from disabled prepared statements", "Revisit session pooling for write-heavy jobs"],
                matched_signals=["prepared statement", "prisma", "transaction pooling"],
                opened_days_ago=15,
                updated_days_ago=14,
            ),
            _case(
                title="Replica lag looked like primary connection exhaustion",
                status="done",
                source="incident-review",
                input_summary="Read traffic started timing out after a failover drill even though the primary had spare connections.",
                summary_current="The app retried replica reads against the primary, creating a misleading connection-exhaustion signature.",
                files=[
                    "backend/app/read_router.py",
                    "backend/app/retry.py",
                    "dashboards/postgres-replica.json",
                ],
                symbols=["select_replica", "RetryPolicy", "replicaLagSeconds"],
                errors=["read timed out", "replica replay lag exceeded threshold"],
                symptoms=["primary connections rose only after replica lag", "timeouts clustered on analytics endpoints"],
                commands=[
                    _command("psql -c \"select now()-pg_last_xact_replay_timestamp()\"", "measure replay lag", "lag peaked above 90 seconds"),
                    _command("curl -H 'x-debug-route: 1' /api/v1/reports", "trace replica fallback path", "retries escalated to the primary after lag checks"),
                ],
                hypotheses=[
                    _hypothesis("Fallback retries are making a replica problem look like a primary problem.", "supported", "Primary traffic jumped only after fallback engaged."),
                ],
                changes=[
                    _change("code", "Short-circuited stale replicas instead of retrying them through the primary.", ["backend/app/read_router.py", "backend/app/retry.py"], ["PR-430"]),
                ],
                outcome="Replica lag alarms now surface before the primary is flooded with fallback reads.",
                next_steps=["Wire replay lag into autoscaling constraints"],
                matched_signals=["replica lag", "retry policy", "read router"],
                opened_days_ago=12,
                updated_days_ago=11,
            ),
        ],
    ),
    _topic(
        key="react-hydration-mismatch",
        title="React Hydration Mismatch on Marketing Pages",
        description="Frontend investigations into SSR drift, random IDs, and edge-delivered feature flags.",
        aliases=["hydration", "ssr drift", "edge cache"],
        cases=[
            _case(
                title="Locale-sensitive timestamps broke hydration",
                status="done",
                source="codex",
                input_summary="The pricing page hydrated differently by region because server-side and client-side locale formatting diverged.",
                summary_current="Rendering user-visible dates during SSR introduced region-specific text drift that React treated as a hydration mismatch.",
                files=[
                    "frontend/src/routes/pricing.tsx",
                    "frontend/src/lib/formatDate.ts",
                    "frontend/src/components/HeroStats.tsx",
                ],
                symbols=["formatRelativeDate", "HeroStats", "Intl.DateTimeFormat"],
                errors=["Hydration failed because the initial UI does not match what was rendered on the server."],
                symptoms=["only reproed on non-US locales", "error disappeared after hard refresh"],
                commands=[
                    _command("pnpm test:e2e pricing.spec.ts --project=webkit", "reproduce mismatch with locale emulation", "fr-FR and ja-JP failed consistently"),
                    _command("pnpm build && pnpm preview", "verify production rendering path", "SSR markup contained localized timestamps"),
                ],
                hypotheses=[
                    _hypothesis("Locale formatting is happening on both server and client with different timezones.", "supported", "Server rendered UTC while clients rendered local time."),
                ],
                changes=[
                    _change("code", "Deferred humanized timestamps until after hydration and kept SSR copy stable.", ["frontend/src/lib/formatDate.ts", "frontend/src/components/HeroStats.tsx"], ["PR-512"]),
                ],
                outcome="Marketing pages now hydrate cleanly across locales.",
                next_steps=["Audit remaining relative-time components"],
                matched_signals=["hydration failed", "locale", "timestamp"],
                opened_days_ago=21,
                updated_days_ago=20,
            ),
            _case(
                title="Random IDs inside chart gradients caused SSR drift",
                status="resolved",
                source="cursor",
                input_summary="A hero chart introduced random SVG gradient IDs that changed between server render and client hydration.",
                summary_current="Non-deterministic SVG IDs inside the chart library created DOM mismatches even though the numeric data was stable.",
                files=[
                    "frontend/src/components/Marketing/FunnelChart.tsx",
                    "frontend/src/lib/chartIds.ts",
                ],
                symbols=["FunnelChart", "buildGradientId", "useId"],
                errors=["Expected server HTML to contain a matching <defs>"],
                symptoms=["hydration warnings only on pages with SVG charts", "rerenders fixed the paint after hydration"],
                commands=[
                    _command("pnpm test FunnelChart.test.tsx", "lock down deterministic IDs", "snapshot failed before useId migration"),
                ],
                hypotheses=[
                    _hypothesis("The chart library is generating IDs with Math.random().", "supported", "Replacing it with useId removed the drift."),
                ],
                changes=[
                    _change("code", "Replaced random gradient IDs with React useId and stable prefixes.", ["frontend/src/components/Marketing/FunnelChart.tsx", "frontend/src/lib/chartIds.ts"], ["PR-519"]),
                    _change("test", "Added hydration snapshot coverage for the hero chart.", ["frontend/src/components/Marketing/FunnelChart.test.tsx"], ["PR-519"]),
                ],
                outcome="The hero chart now hydrates without broken gradients or console noise.",
                next_steps=["Review other inline SVG components for random IDs"],
                matched_signals=["svg", "gradient id", "useId"],
                opened_days_ago=19,
                updated_days_ago=18,
            ),
            _case(
                title="Stale edge flags rendered the wrong hero variant",
                status="done",
                source="chat",
                input_summary="The edge cache served one feature-flag variant while the browser fetched a fresher flag set and swapped the hero during hydration.",
                summary_current="Hydration drift came from inconsistent feature-flag snapshots between the edge response and the client boot payload.",
                files=[
                    "frontend/src/routes/index.tsx",
                    "frontend/src/lib/flags.ts",
                    "edge/worker/flags.ts",
                ],
                symbols=["loadFlags", "serializeFlags", "edgeFlagSnapshot"],
                errors=["Text content does not match server-rendered HTML"],
                symptoms=["wrong CTA appeared for a split second", "only pages behind edge worker reproed"],
                commands=[
                    _command("wrangler dev", "compare edge snapshot to client bootstrap payload", "edge flags lagged one deploy behind"),
                    _command("pnpm test flags.integration.ts", "validate flag serialization contract", "bootstrap payload ignored worker snapshot"),
                ],
                hypotheses=[
                    _hypothesis("The client is discarding the edge-provided flag snapshot.", "supported", "Hydration stabilized after bootstrapping from the serialized flags."),
                ],
                changes=[
                    _change("code", "Bootstrapped client flags from the edge snapshot and tightened cache invalidation.", ["frontend/src/lib/flags.ts", "edge/worker/flags.ts"], ["PR-523"]),
                ],
                outcome="The hero variant stays stable between SSR and hydration.",
                next_steps=["Expose flag snapshot age in debug headers"],
                matched_signals=["feature flag", "edge cache", "hydration"],
                opened_days_ago=16,
                updated_days_ago=15,
            ),
        ],
    ),
    _topic(
        key="hosted-mcp-oauth-rotation",
        title="Hosted MCP OAuth Token Rotation",
        description="Hosted agent auth investigations spanning refresh tokens, cached sessions, and audience validation.",
        aliases=["oauth", "hosted mcp", "token rotation"],
        cases=[
            _case(
                title="Refresh tokens invalid after provider key rollover",
                status="resolved",
                source="codex",
                input_summary="Hosted MCP sessions started failing refresh after the identity provider rotated signing keys and revoked stale offline sessions.",
                summary_current="The refresh path assumed long-lived provider sessions that were invalidated during the key rollover window.",
                files=[
                    "backend/app/api/routes/agent_credentials.py",
                    "mcp/enderai-api-mcp/src/sessionAuth.ts",
                    "docs/hosted-mcp-onboarding.md",
                ],
                symbols=["rotateHostedCredential", "refreshHostedSession", "sessionAuth"],
                errors=["invalid_grant", "refresh token revoked"],
                symptoms=["existing agents failed silently until command execution", "new logins worked"],
                commands=[
                    _command("npm test sessionAuth.test.ts", "replay revoked refresh token flow", "client stayed in a bad cached state"),
                    _command("curl /api/v1/agent-credentials/issue", "verify credential issuance after relogin", "fresh sessions recovered immediately"),
                ],
                hypotheses=[
                    _hypothesis("The hosted client is not distinguishing revoked refresh tokens from transient transport errors.", "supported", "It kept retrying with a dead token."),
                ],
                changes=[
                    _change("code", "Forced credential re-issue on invalid_grant and surfaced relogin guidance.", ["backend/app/api/routes/agent_credentials.py", "mcp/enderai-api-mcp/src/sessionAuth.ts"], ["PR-602"]),
                    _change("docs", "Expanded onboarding docs for expired hosted sessions.", ["docs/hosted-mcp-onboarding.md"], ["PR-602"]),
                ],
                outcome="Hosted agents now recover cleanly from provider-side refresh token revocation.",
                next_steps=["Add telemetry for refresh-failure reasons by provider"],
                matched_signals=["invalid_grant", "refresh token", "oauth rotation"],
                opened_days_ago=13,
                updated_days_ago=12,
            ),
            _case(
                title="Audience mismatch at the MCP edge proxy",
                status="done",
                source="cursor",
                input_summary="Valid tokens were rejected in hosted environments because the proxy validated the audience against the API origin instead of the MCP origin.",
                summary_current="The edge proxy and backend disagreed about the expected OAuth audience after the hosted MCP split into a dedicated origin.",
                files=[
                    "mcp/enderai-api-mcp/src/httpServer.ts",
                    "backend/app/api/deps.py",
                    "infra/cloudflare/mcp-proxy.tf",
                ],
                symbols=["validateAudience", "TokenPayload", "MCP_PUBLIC_URL"],
                errors=["invalid audience", "token is not intended for this resource"],
                symptoms=["hosted MCP failed but local HTTP flow passed", "retrying from the CLI changed nothing"],
                commands=[
                    _command("npm test http.test.ts", "lock expected audience behavior", "hosted proxy path failed"),
                    _command("terraform plan", "inspect MCP proxy env wiring", "audience env var pointed at API host"),
                ],
                hypotheses=[
                    _hypothesis("The proxy is validating against the wrong audience after the origin split.", "supported", "Switching to the MCP origin fixed both CLI and Cursor flows."),
                ],
                changes=[
                    _change("config", "Aligned hosted MCP audience validation with the MCP origin.", ["infra/cloudflare/mcp-proxy.tf", "mcp/enderai-api-mcp/src/httpServer.ts"], ["PR-607"]),
                ],
                outcome="Hosted MCP tokens validate consistently across proxy and backend layers.",
                next_steps=["Add an integration test that exercises the full hosted proxy path"],
                matched_signals=["audience", "mcp proxy", "hosted origin"],
                opened_days_ago=10,
                updated_days_ago=9,
            ),
            _case(
                title="Revoked credential stayed cached inside the CLI session",
                status="done",
                source="incident-review",
                input_summary="Users rotated their hosted credential but the local MCP client kept sending the revoked token from an in-memory cache.",
                summary_current="The CLI session cache outlived credential rotation, so revoked tokens continued to fail until the process restarted.",
                files=[
                    "mcp/enderai-api-mcp/src/mcpServer.ts",
                    "mcp/enderai-api-mcp/src/sessionAuth.ts",
                    "mcp/enderai-api-mcp/test/sessionAuth.test.ts",
                ],
                symbols=["cachedCredential", "clearCachedCredential", "refreshSessionToken"],
                errors=["Could not validate credentials", "credential revoked"],
                symptoms=["rotation looked broken until the client restarted", "one machine failed while another worked"],
                commands=[
                    _command("npm test mcpAuth.test.ts", "reproduce stale in-memory session cache", "revoked token stayed hot in memory"),
                ],
                hypotheses=[
                    _hypothesis("The client only refreshes tokens on expiry, not on server-side revocation.", "supported", "Explicit cache clears fixed the session immediately."),
                ],
                changes=[
                    _change("code", "Cleared cached hosted credentials when the backend returned revocation errors.", ["mcp/enderai-api-mcp/src/mcpServer.ts", "mcp/enderai-api-mcp/src/sessionAuth.ts"], ["PR-611"]),
                ],
                outcome="Credential rotation no longer requires restarting the CLI client.",
                next_steps=["Emit a user-facing toast when a rotation invalidates the local session"],
                matched_signals=["credential revoked", "cached session", "rotation"],
                opened_days_ago=8,
                updated_days_ago=7,
            ),
        ],
    ),
    _topic(
        key="playwright-checkout-flakes",
        title="Flaky Playwright Checkout Tests",
        description="Cross-browser UI test investigations involving network-idle races, timers, and autofill behavior.",
        aliases=["playwright", "checkout", "webkit flakes"],
        cases=[
            _case(
                title="Network-idle wait hid a background analytics race",
                status="resolved",
                source="codex",
                input_summary="Checkout tests intermittently hung on network-idle even though the form was ready for interaction.",
                summary_current="A background analytics beacon kept the page from reaching network-idle, making the wait strategy fundamentally unstable.",
                files=[
                    "frontend/tests/checkout.spec.ts",
                    "frontend/src/lib/analytics.ts",
                ],
                symbols=["waitForLoadState", "sendCheckoutBeacon", "completeCheckout"],
                errors=["Timeout 30000ms exceeded while waiting for networkidle"],
                symptoms=["failures clustered on CI and not locally", "retrying often passed immediately"],
                commands=[
                    _command("bunx playwright test checkout.spec.ts --repeat-each=30", "measure flake pattern", "timeouts disappeared when analytics was mocked"),
                ],
                hypotheses=[
                    _hypothesis("Network-idle is the wrong readiness signal for checkout.", "supported", "Waiting on the submit button state removed the flake."),
                ],
                changes=[
                    _change("test", "Replaced network-idle waits with explicit checkout readiness assertions.", ["frontend/tests/checkout.spec.ts"], ["PR-701"]),
                    _change("code", "Marked analytics beacons as fire-and-forget in test environments.", ["frontend/src/lib/analytics.ts"], ["PR-701"]),
                ],
                outcome="Checkout tests now wait on user-visible readiness instead of incidental network silence.",
                next_steps=["Audit the rest of the suite for network-idle waits"],
                matched_signals=["networkidle", "analytics beacon", "flake"],
                opened_days_ago=14,
                updated_days_ago=13,
            ),
            _case(
                title="WebKit autofill focus stole the card input cursor",
                status="done",
                source="cursor",
                input_summary="Only WebKit intermittently typed card digits into the wrong field after the billing zip code autofilled.",
                summary_current="WebKit fired an autofill focus event after the script advanced to the card input, re-targeting typing into the zip field.",
                files=[
                    "frontend/tests/checkout.spec.ts",
                    "frontend/src/components/Checkout/BillingForm.tsx",
                ],
                symbols=["fillCardForm", "BillingForm", "onAutoFill"],
                errors=["locator.fill: element is not editable"],
                symptoms=["only WebKit reproed", "video showed focus bouncing between fields"],
                commands=[
                    _command("bunx playwright test checkout.spec.ts --project=webkit --debug", "inspect focus transitions", "zip autofill landed after card focus"),
                ],
                hypotheses=[
                    _hypothesis("A delayed autofill event is stealing focus after the test script moves on.", "supported", "Waiting for the final zip autofill stabilized the sequence."),
                ],
                changes=[
                    _change("test", "Inserted explicit focus assertions before typing card digits.", ["frontend/tests/checkout.spec.ts"], ["PR-706"]),
                ],
                outcome="WebKit checkout runs no longer type card data into the wrong field.",
                next_steps=["Add a reusable helper for autofill-heavy forms"],
                matched_signals=["webkit", "autofill", "focus"],
                opened_days_ago=11,
                updated_days_ago=10,
            ),
            _case(
                title="Promo timer test depended on wall-clock time",
                status="done",
                source="incident-review",
                input_summary="A countdown banner test failed around midnight UTC because the promo expiration calculation used the real clock.",
                summary_current="The checkout promo test assumed a stable wall clock, but the client and mocked API crossed the day boundary during CI runs.",
                files=[
                    "frontend/tests/promo-banner.spec.ts",
                    "frontend/src/lib/promoWindow.ts",
                ],
                symbols=["promoEndsAt", "shouldShowPromo", "PromoBanner"],
                errors=["Expected countdown to contain 1h", "received 0h"],
                symptoms=["failures concentrated around one UTC boundary", "retries often passed a few minutes later"],
                commands=[
                    _command("bunx playwright test promo-banner.spec.ts --workers=1", "replay boundary timing failure", "countdown crossed a date boundary"),
                ],
                hypotheses=[
                    _hypothesis("The test should freeze the clock instead of sampling real time.", "supported", "Using a fixed browser clock eliminated the midnight flake."),
                ],
                changes=[
                    _change("test", "Mocked the browser clock and promo window in countdown tests.", ["frontend/tests/promo-banner.spec.ts"], ["PR-710"]),
                ],
                outcome="Promo countdown coverage is now deterministic regardless of CI wall-clock time.",
                next_steps=["Move all date-sensitive UI tests onto the shared clock helper"],
                matched_signals=["countdown", "midnight", "clock"],
                opened_days_ago=9,
                updated_days_ago=8,
            ),
        ],
    ),
    _topic(
        key="ledger-billing-migration",
        title="Ledger Service Billing Migration",
        description="Migration work across invoice backfills, idempotency keys, and event-driven ledger writes.",
        aliases=["billing migration", "ledger", "backfill"],
        cases=[
            _case(
                title="Backfill created duplicate invoice line items",
                status="resolved",
                source="codex",
                input_summary="Historical invoice backfills replayed the same line item when the source order emitted both legacy and new billing events.",
                summary_current="The migration backfill double-counted orders that were mirrored into the ledger during the cutover window.",
                files=[
                    "services/ledger/backfill_invoices.py",
                    "services/ledger/src/reconcile.py",
                    "sql/ledger/dedupe_invoice_lines.sql",
                ],
                symbols=["backfill_invoices", "reconcile_invoice", "invoice_line_hash"],
                errors=["duplicate key value violates unique constraint invoice_line_hash"],
                symptoms=["customer totals were doubled for cutover-day orders", "re-running the backfill worsened the issue"],
                commands=[
                    _command("uv run python services/ledger/backfill_invoices.py --dry-run", "inspect duplicate generation path", "mirror events were replayed twice"),
                    _command("psql -f sql/ledger/dedupe_invoice_lines.sql", "measure duplicate scope", "duplicates were isolated to the cutover window"),
                ],
                hypotheses=[
                    _hypothesis("Mirror events from the legacy bus were not de-duplicated during backfill.", "supported", "Hash collisions mapped exactly to mirrored orders."),
                ],
                changes=[
                    _change("code", "Added deterministic invoice-line hashes and skipped mirrored duplicates during backfill.", ["services/ledger/backfill_invoices.py", "services/ledger/src/reconcile.py"], ["PR-810"]),
                    _change("sql", "Added one-off dedupe cleanup for the affected invoices.", ["sql/ledger/dedupe_invoice_lines.sql"], ["PR-810"]),
                ],
                outcome="Invoice backfills are now idempotent across the cutover window.",
                next_steps=["Add replay-safety checks to the migration runbook"],
                matched_signals=["backfill", "duplicate invoice lines", "cutover"],
                opened_days_ago=22,
                updated_days_ago=21,
            ),
            _case(
                title="Missing idempotency key on refund writes",
                status="done",
                source="cursor",
                input_summary="Refund retries occasionally wrote duplicate compensating entries because the idempotency key was only attached to charge creation.",
                summary_current="The refund path bypassed the shared idempotency wrapper, so transport retries produced multiple ledger compensations.",
                files=[
                    "services/billing/src/refunds.py",
                    "services/ledger/src/client.py",
                    "services/billing/tests/test_refunds.py",
                ],
                symbols=["create_refund", "LedgerClient", "Idempotency-Key"],
                errors=["duplicate compensation detected"],
                symptoms=["refund totals drifted by small amounts", "manual replay reproduced the duplicate"],
                commands=[
                    _command("pytest services/billing/tests/test_refunds.py -k duplicate", "reproduce retry behavior", "duplicate compensations reproduced on network timeout"),
                ],
                hypotheses=[
                    _hypothesis("Refund retries are missing the shared idempotency wrapper.", "supported", "Refund requests omitted the header entirely."),
                ],
                changes=[
                    _change("code", "Routed refund writes through the shared ledger idempotency helper.", ["services/billing/src/refunds.py", "services/ledger/src/client.py"], ["PR-818"]),
                    _change("test", "Added explicit retry coverage for refund idempotency.", ["services/billing/tests/test_refunds.py"], ["PR-818"]),
                ],
                outcome="Refund retries no longer create duplicate compensating ledger entries.",
                next_steps=["Backfill idempotency coverage for write-off flows"],
                matched_signals=["refund", "idempotency", "duplicate compensation"],
                opened_days_ago=18,
                updated_days_ago=17,
            ),
            _case(
                title="Outbox lag delayed invoice posting after cutover",
                status="done",
                source="incident-review",
                input_summary="Invoices stayed pending for several minutes because the outbox poller fell behind during the first cutover batch.",
                summary_current="The cutover batch saturated the outbox poller, delaying ledger publication and making the new system appear inconsistent.",
                files=[
                    "services/ledger/src/outbox.py",
                    "infra/k8s/ledger-worker.yaml",
                    "dashboards/ledger-outbox.json",
                ],
                symbols=["poll_outbox", "publish_invoice_created", "outboxLagSeconds"],
                errors=["outbox lag above SLA"],
                symptoms=["invoices remained pending despite successful writes", "lag drained only after traffic subsided"],
                commands=[
                    _command("kubectl top deploy ledger-worker", "measure worker saturation", "CPU pinned during batch replay"),
                    _command("psql -c \"select count(*) from ledger_outbox where published_at is null\"", "measure queue depth", "queue depth rose with batch size"),
                ],
                hypotheses=[
                    _hypothesis("The poller concurrency is too low for the cutover batch profile.", "supported", "Doubling workers drained the queue immediately."),
                ],
                changes=[
                    _change("infra", "Raised ledger worker concurrency and added outbox lag alerts.", ["infra/k8s/ledger-worker.yaml", "dashboards/ledger-outbox.json"], ["PR-823"]),
                ],
                outcome="Ledger publishing now keeps up with the migration batch profile.",
                next_steps=["Model outbox backlog during quarter-end invoice volume"],
                matched_signals=["outbox lag", "pending invoices", "cutover batch"],
                opened_days_ago=15,
                updated_days_ago=14,
            ),
        ],
    ),
    _topic(
        key="vector-search-relevance",
        title="Vector Search Relevance Regression",
        description="Search quality work spanning re-embedding, chunking, metadata filters, and recall evaluation.",
        aliases=["semantic search", "embeddings", "retrieval quality"],
        cases=[
            _case(
                title="Re-embedding with a smaller model hurt code recall",
                status="resolved",
                source="codex",
                input_summary="Search latency improved after a cheaper embedding model swap, but developers reported worse recall for code-heavy queries.",
                summary_current="The smaller embedding model compressed code syntax too aggressively, which tanked recall for stack-trace and symbol searches.",
                files=[
                    "search/reindex_embeddings.py",
                    "search/eval/code_recall.yaml",
                    "search/src/embed.py",
                ],
                symbols=["reindex_embeddings", "run_code_recall_eval", "embed_chunks"],
                errors=["relevance regression", "top-5 recall below threshold"],
                symptoms=["natural-language queries were fine", "symbol-heavy queries dropped sharply"],
                commands=[
                    _command("uv run python search/reindex_embeddings.py --sample 5000", "compare embedding families", "cheap model underperformed on code queries"),
                    _command("uv run python search/eval/run.py code_recall", "measure recall deltas", "top-5 recall dropped 17 points"),
                ],
                hypotheses=[
                    _hypothesis("The smaller model preserves prose semantics better than code structure.", "supported", "Regression was worst on stack traces and file paths."),
                ],
                changes=[
                    _change("config", "Restored the larger embedding model for code-heavy corpora and split evals by content type.", ["search/src/embed.py", "search/eval/code_recall.yaml"], ["PR-911"]),
                ],
                outcome="Code recall recovered without reverting all latency work for prose queries.",
                next_steps=["Try mixed-model retrieval with content-type routing"],
                matched_signals=["embedding model", "code recall", "relevance regression"],
                opened_days_ago=17,
                updated_days_ago=16,
            ),
            _case(
                title="Chunker split fenced code blocks mid-function",
                status="done",
                source="cursor",
                input_summary="Search excerpts looked incoherent because the chunker split markdown code fences in the middle of functions.",
                summary_current="The markdown chunker optimized for token count and ignored fenced code-block boundaries, which fragmented retrieval context.",
                files=[
                    "search/src/chunk_markdown.py",
                    "search/tests/test_chunk_markdown.py",
                ],
                symbols=["chunk_markdown", "split_fenced_block", "ChunkBoundary"],
                errors=["excerpt lost function signature"],
                symptoms=["search hits started in the middle of code blocks", "reranking could not repair missing context"],
                commands=[
                    _command("pytest search/tests/test_chunk_markdown.py", "reproduce fence-splitting behavior", "chunker cut through fenced blocks"),
                ],
                hypotheses=[
                    _hypothesis("The chunker is ignoring markdown fences and only counting tokens.", "supported", "Fence-aware chunking fixed the broken excerpts."),
                ],
                changes=[
                    _change("code", "Made markdown chunking fence-aware and added regression tests for code blocks.", ["search/src/chunk_markdown.py", "search/tests/test_chunk_markdown.py"], ["PR-917"]),
                ],
                outcome="Retrieved chunks now preserve full code blocks and produce coherent excerpts.",
                next_steps=["Backfill the reindex for docs-heavy repositories"],
                matched_signals=["chunker", "code fence", "excerpt"],
                opened_days_ago=13,
                updated_days_ago=12,
            ),
            _case(
                title="Metadata filters excluded newly migrated docs",
                status="done",
                source="incident-review",
                input_summary="Recently migrated docs stopped appearing in search because the metadata filter expected the old repository labels.",
                summary_current="The metadata filter logic still targeted legacy repository taxonomies, silently excluding fresh content from retrieval.",
                files=[
                    "search/src/filters.py",
                    "search/src/index_metadata.py",
                    "search/eval/migrated_docs.yaml",
                ],
                symbols=["build_filter_query", "index_metadata", "repositoryLabel"],
                errors=["zero hits for migrated docs"],
                symptoms=["query expansion still returned nothing", "older docs remained searchable"],
                commands=[
                    _command("uv run python search/eval/run.py migrated_docs", "measure migrated-doc recall", "filter path removed all newly migrated content"),
                ],
                hypotheses=[
                    _hypothesis("Repository labels changed during migration but filter mapping did not.", "supported", "Normalizing labels restored migrated-doc hits."),
                ],
                changes=[
                    _change("code", "Normalized repository metadata before filter construction.", ["search/src/filters.py", "search/src/index_metadata.py"], ["PR-922"]),
                ],
                outcome="Migrated documentation reappeared in vector search results.",
                next_steps=["Add schema checks on metadata ingestion"],
                matched_signals=["metadata filter", "migrated docs", "zero hits"],
                opened_days_ago=9,
                updated_days_ago=8,
            ),
        ],
    ),
    _topic(
        key="offline-sync-conflicts",
        title="Offline Sync Conflict Resolution in Mobile App",
        description="Mobile investigations into tombstones, clock drift, and optimistic-merge behavior after offline edits.",
        aliases=["offline sync", "conflict resolution", "mobile"],
        cases=[
            _case(
                title="Delete tombstones were overwritten by stale edits",
                status="resolved",
                source="codex",
                input_summary="Offline clients occasionally resurrected deleted tasks after reconnect because stale patches beat tombstones in merge order.",
                summary_current="Delete tombstones lacked a stronger precedence rule, so reconnecting edits could replay over a server-side delete.",
                files=[
                    "mobile/src/sync/mergeEngine.ts",
                    "backend/app/api/routes/tasks.py",
                    "mobile/tests/sync/tombstones.spec.ts",
                ],
                symbols=["mergeTaskPatch", "applyTombstone", "SyncRevision"],
                errors=["deleted task reappeared after sync"],
                symptoms=["only happened after long offline windows", "server logs showed valid delete events"],
                commands=[
                    _command("pnpm test tombstones.spec.ts", "reproduce stale patch overwrite", "offline patch replay resurrected the deleted task"),
                ],
                hypotheses=[
                    _hypothesis("Tombstones need stronger precedence than stale field patches.", "supported", "Applying tombstones first eliminated resurrection."),
                ],
                changes=[
                    _change("code", "Gave tombstones terminal precedence during sync merge.", ["mobile/src/sync/mergeEngine.ts", "backend/app/api/routes/tasks.py"], ["PR-1008"]),
                    _change("test", "Added regression coverage for reconnecting stale edits after delete.", ["mobile/tests/sync/tombstones.spec.ts"], ["PR-1008"]),
                ],
                outcome="Deleted records stay deleted even after long offline edit sessions.",
                next_steps=["Audit other entity types for tombstone precedence"],
                matched_signals=["tombstone", "offline edit", "resurrected record"],
                opened_days_ago=20,
                updated_days_ago=19,
            ),
            _case(
                title="Clock drift reordered conflicting edits",
                status="done",
                source="cursor",
                input_summary="Two offline devices disagreed about edit order because one device clock drifted several minutes into the future.",
                summary_current="Last-write-wins based on wall-clock timestamps amplified device clock drift into incorrect merge ordering.",
                files=[
                    "mobile/src/sync/revisionClock.ts",
                    "mobile/src/sync/mergeEngine.ts",
                ],
                symbols=["nextRevision", "compareRevisions", "HybridLogicalClock"],
                errors=["newer edit lost after reconnect"],
                symptoms=["only one device class reproed", "merge order disagreed with server receive time"],
                commands=[
                    _command("pnpm test revisionClock.spec.ts", "simulate skewed device clocks", "future-skewed device won incorrect conflicts"),
                ],
                hypotheses=[
                    _hypothesis("Wall-clock timestamps are insufficient for offline conflict resolution.", "supported", "Hybrid logical clocks fixed the ordering drift."),
                ],
                changes=[
                    _change("code", "Switched sync revisions from wall-clock timestamps to a hybrid logical clock.", ["mobile/src/sync/revisionClock.ts", "mobile/src/sync/mergeEngine.ts"], ["PR-1013"]),
                ],
                outcome="Conflict ordering is now stable even with skewed device clocks.",
                next_steps=["Roll HLC adoption across attachments sync"],
                matched_signals=["clock drift", "merge order", "hybrid logical clock"],
                opened_days_ago=16,
                updated_days_ago=15,
            ),
            _case(
                title="Optimistic patch merge diverged from server reconciliation",
                status="done",
                source="incident-review",
                input_summary="The mobile app showed a merged note body that the server later rejected, causing a jarring overwrite when sync completed.",
                summary_current="Client-side optimistic merging accepted patch combinations that the backend reconciliation step later rejected as invalid.",
                files=[
                    "mobile/src/sync/optimisticMerge.ts",
                    "backend/app/core/conflicts.py",
                    "mobile/tests/sync/optimistic-merge.spec.ts",
                ],
                symbols=["optimisticMerge", "reconcile_conflict", "ConflictResolutionError"],
                errors=["conflict reconciliation rejected client patch"],
                symptoms=["notes visibly rewrote themselves after reconnect", "support tickets mentioned disappearing bullet points"],
                commands=[
                    _command("pytest backend/tests/test_conflicts.py", "compare backend reconciliation to optimistic merge", "backend rejected combinations the client accepted"),
                    _command("pnpm test optimistic-merge.spec.ts", "reproduce jarring overwrite behavior", "UI showed divergent merge previews"),
                ],
                hypotheses=[
                    _hypothesis("Client optimistic merge rules drifted from backend reconciliation.", "supported", "Sharing the merge rule table fixed the divergence."),
                ],
                changes=[
                    _change("code", "Aligned optimistic merge rules with backend reconciliation tables.", ["mobile/src/sync/optimisticMerge.ts", "backend/app/core/conflicts.py"], ["PR-1019"]),
                    _change("test", "Added cross-platform fixtures for shared merge-rule validation.", ["mobile/tests/sync/optimistic-merge.spec.ts"], ["PR-1019"]),
                ],
                outcome="Optimistic merge previews now match the server’s eventual reconciliation result.",
                next_steps=["Export shared conflict fixtures from the backend package"],
                matched_signals=["optimistic merge", "reconciliation", "overwrite"],
                opened_days_ago=12,
                updated_days_ago=11,
            ),
        ],
    ),
]


def ensure_demo_workspace(session: Session, user: User) -> bool:
    if user.demo_seeded_at is not None:
        return False

    owner_id = user.id
    owner_id_str = str(owner_id)
    existing_demo_topics = [
        topic
        for topic in session.exec(select(Topic).where(Topic.is_demo.is_(True))).all()
        if owner_id_str in topic.owner_ids
    ]
    if existing_demo_topics:
        user.demo_seeded_at = get_datetime_utc()
        session.add(user)
        return True

    seeded_at = get_datetime_utc()
    suffix = owner_id_str.split("-")[0]

    for topic_seed in DEMO_TOPICS:
        topic = Topic(
            title=topic_seed["title"],
            slug=f"{topic_seed['key']}-{suffix}",
            workflow_key=f"{topic_seed['key']}-{suffix}",
            description=topic_seed["description"],
            aliases=topic_seed["aliases"],
            status="open",
            is_demo=True,
            owner_ids=[owner_id_str],
            created_at=seeded_at,
            updated_at=seeded_at,
            last_used_at=seeded_at,
        )
        session.add(topic)
        session.flush()

        latest_case_update = seeded_at
        for case_seed in topic_seed["cases"]:
            opened_at = seeded_at - timedelta(days=case_seed["opened_days_ago"])
            updated_at = seeded_at - timedelta(days=case_seed["updated_days_ago"])
            closed_at = updated_at if is_terminal_case_status(case_seed["status"]) else None
            case_record = CaseRecord(
                topic_id=topic.id,
                title=case_seed["title"],
                opened_at=opened_at,
                updated_at=updated_at,
                closed_at=closed_at,
                status=case_seed["status"],
                actor_id=owner_id,
                source=case_seed["source"],
                input_summary=case_seed["input_summary"],
                summary_current=case_seed["summary_current"],
                case_data={
                    "files": case_seed["files"],
                    "symbols": case_seed["symbols"],
                    "errors": case_seed["errors"],
                    "symptoms": case_seed["symptoms"],
                    "commands": case_seed["commands"],
                    "hypotheses": case_seed["hypotheses"],
                    "changes": case_seed["changes"],
                    "outcome": case_seed["outcome"],
                    "next_steps": case_seed["next_steps"],
                },
            )
            session.add(case_record)
            session.flush()
            case_record.context_pack_snapshot = normalize_context_pack_snapshot(
                {
                    "confidence": "high",
                    "topic_summary": topic_seed["description"],
                    "matched_signals": case_seed["matched_signals"],
                    "canonical_files": case_seed["files"][:4],
                    "canonical_symbols": case_seed["symbols"][:4],
                    "canonical_errors": case_seed["errors"][:4],
                    "canonical_symptoms": case_seed["symptoms"][:4],
                    "pinned_takeaways": [case_seed["outcome"]],
                    "questions": case_seed["next_steps"][:3],
                    "builder_version": f"demo-v{DEMO_SEED_VERSION}",
                    "created_at": updated_at,
                },
                topic_id=topic.id,
                case_id=case_record.id,
            ).model_dump(mode="json")
            session.add(case_record)
            if updated_at > latest_case_update:
                latest_case_update = updated_at

        topic.last_used_at = latest_case_update
        topic.updated_at = latest_case_update
        session.add(topic)

    user.demo_seeded_at = seeded_at
    session.add(user)
    return True
