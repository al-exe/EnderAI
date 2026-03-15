# Productionization Backlog

## Purpose

This document consolidates productionization, dead-code reduction, and refactor priorities discovered during the archive PR review pass and recent implementation work.

It is intentionally biased toward reducing long-term complexity rather than adding more compatibility layers.

## Guardrails

- Do not alter the current hosted MCP token flow casually.
- Keep the current file-based Codex token setup intact:
  - `~/.enderai_mcp_token`
  - `chmod 600 ~/.enderai_mcp_token`
  - shell loading from `~/.bashrc`
- Prefer incremental convergence toward Topic / Case over a risky big-bang rename.
- Remove dead/demo behavior when it does not yet have durable backend semantics.

## P0

### Auth and hosted MCP hardening

- Reduce write amplification in agent-token validation and usage tracking.
  - Current issue: request-path auth can update credential usage metadata too eagerly.
  - Goal: preserve auditing while avoiding avoidable per-request write load.
- Add explicit smoke coverage for the full hosted token lifecycle.
  - create credential
  - rotate credential
  - revoke credential
  - validate token through hosted MCP
- Keep the current user-scoped MCP token model as the supported path until a deliberate OAuth-based replacement exists.

### Database lifecycle hardening

- Move remaining memory-table creation and backfill behavior out of startup scripts and into migrations plus operator-run tasks.
- Make boot deterministic so app startup does not quietly perform schema management work.

## P1

### Complete the Topic / Case contract

- Define the canonical persisted Topic / Case document shape.
- Decide which current `Thread` and `Execution` fields survive directly, which move into derived context, and which are removed.
- Keep `Note` contextual rather than reintroducing it as a top-level user-facing navigation concept.

### Simplify API and MCP compatibility layers

- Retire deprecated path rewrite behavior once active clients no longer depend on old names.
- Reduce duplicated route semantics where both old and new naming ideas coexist.
- Move toward clearer high-level MCP workflows on top of the stable backend contract.

### Frontend production hardening

- Split `ConnectAgent` into smaller presentation and logic units.
- Keep the current token-file guidance, but make the UI implementation easier to test and evolve.
- Replace demo-only archive/duplicate item affordances with real backend semantics, or hide/remove them until the backend contract exists.
- Continue paying down route/query naming drift introduced by the Topic/Case transition.

## P2

### Testing and deploy confidence

- Add stronger end-to-end checks around login, Topic/Case navigation, and Connect Agent snippets.
- Keep frontend Pages deployment healthy and current with platform runtime changes.
- Expand MCP smoke coverage for both local and hosted flows.

### Documentation and ownership

- Keep the architecture overview updated when repo boundaries or auth flows change.
- Tie cleanup work to Jira tickets and focused PRs rather than broad sweep refactors.

## Suggested PR Bundles

### Bundle A: Auth and MCP hardening

- credential usage write-throttling
- credential lifecycle smoke coverage
- audit/event coverage review

### Bundle B: Schema lifecycle cleanup

- Alembic-first memory schema management
- backfill/operator scripts separated from boot
- startup path simplification

### Bundle C: Topic / Case convergence

- canonical Topic / Case storage contract
- compatibility mapping plan
- staged route and client cleanup

### Bundle D: Frontend cleanup for production

- `ConnectAgent` refactor
- archive/duplicate behavior cleanup
- route/query naming alignment

## Source of Findings

These priorities were consolidated from:

- archive PR review comments in `EnderAI` and `EnderAI-frontend`
- cleanup backlog issues created from those reviews
- recent Topic/Case documentation and frontend renaming work
