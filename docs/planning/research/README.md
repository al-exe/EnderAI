# Competitor Research — Taskforce

*Last updated: 2026-05-30. Lens: the Taskforce thesis (`~/dev/docs/thesis.md`, esp. Addendum A/B) — claim-vs-proof, capture, cross-vendor/team scope, provenance, the ROI ledger, open-core gates, and the seams left open.*
*Standard: every claim in these files is source-linked. **Reddit/community sentiment is NOT covered** — Anthropic's crawler is blocked from reddit.com; Alex owns that channel in parallel.*

## Files
| File | Company | Lane | Relevance |
|---|---|---|---|
| [letta.md](letta.md) | **Letta** (MemGPT) | Memory layer | 🔴 **Highest — closest + most sophisticated competitor** |
| [xmemory.md](xmemory.md) | **xMemory** | Memory layer (schema) | 🟠 High — closest to our **provenance** angle |
| [mem0.md](mem0.md) | **Mem0** | Memory layer | 🟠 High — category leader by adoption |
| [infra-vector-dbs.md](infra-vector-dbs.md) | **Pinecone · turbopuffer · Weaviate** | Vector infra | 🟡 Substrate, not direct rivals |
| *(pending)* | Subconscious / Isara | — | ⏸️ off-thesis name-collisions — awaiting confirmation |

> **Zep / Graphiti** is covered in thesis Addendum A (bi-temporal graph, invalidate-not-delete, Apache-2.0 — the build-on candidate).

## The one big finding
**The memory *mechanism* is table stakes — proven three ways this pass.** Consolidation, invalidation, versioning, offline-compute, even provenance are *already shipped*:
- **Mem0** → A.U.D.N. consolidation + open-sourced per-question eval
- **Zep/Graphiti** → bi-temporal invalidate-not-delete
- **xMemory** → schema-grounded extraction + first-class lineage
- **Letta** → git-versioned memory + **"sleep-time compute"** (offline consolidation) + git-merge conflict resolution + code-verified cost benchmark

Every "our mechanism is novel" claim collapsed on inspection. **The moat is not the mechanism.**

## How each measures "savings" (the question that kicked this off)
| Company | Claim | How measured | Auditable? | Gap vs our ledger |
|---|---|---|---|---|
| **Mem0** | ">90% token cost saved" vs full-context | LoCoMo/LongMemEval/BEAM; tiktoken per-query; open-sourced | ✅ per-question **on benchmark** | Read-side only; **benchmark counterfactual**; single-system |
| **xMemory** | "3×+ fewer tokens" | **Illustrative formula** (`≈3.15`); paper has *measured* ~28–48% on custom sets | ⚠️ headline illustrative | Single-system; provenance = debugging, not ROI |
| **Letta** | ~5× / 2.5× compute | Stateful GSM/AIME; Context-Bench = **$/task, code-verified** | ✅ per-task | Benchmark, not production reuse; single-harness |
| **Pinecone** | none (infra) | semantic-cache hit-rate (partner pattern) | ✅ per-hit | Response-caching, not knowledge reuse |
| **turbopuffer** | "10× cheaper" | $1/M vectors + $4/M queries; Cursor "−95%" | ✅ billing | Storage cost, not reuse |
| **Weaviate** | "4× memory reduction" | RQ-8 quantization (RAM) | ✅ infra | Infra memory, not tokens/reuse |

**Pattern:** everyone measures a **benchmark/synthetic counterfactual**, an **illustrative model**, or **infra cost** — *single-system, self-reported, non-replicating* (Mem0 re-ran **Zep 84% → 58.44%**). **Nobody measures real production reuse attributed via provenance, across tools/people.**

## The surviving wedge (corrected & sharpened)
Not "we measure / they don't" (false). The defensible cut points:
1. **Neutrality / cross-vendor.** Every competitor is single-system or *is a harness* (Letta). None captures across Claude Code + Cursor + Copilot into one neutral store. **The seam.**
2. **Cross-person / cross-time reuse** — the number no single vendor structurally shows.
3. **The reuse-ROI ledger** — provenance-attributed *confirmed reuse* (not token-efficiency, not git-change-history).
4. **Neutral, standardized, auditable measurement** — the benchmark-credibility war (84%→58%) makes a *neutral* measure valuable.

## The bear case (respect it — flagged in thesis Addendum B)
The market is building **per-harness** memory (Letta Code, Cursor, Claude Code) — the *opposite* of cross-vendor neutrality. Our bet wins only if teams (a) run multiple harnesses, (b) feel fragmented-memory pain, (c) trust a neutral third party over their vendor. Letta is the strongest evidence the vertical path is where capital/talent flow.

> **Update — 2026-05-30 (PM-4): pressure-tested → survivable / partially validated.** See [bear-case-validation.md](bear-case-validation.md). (a) multi-harness is the norm and (b) cross-tool pain is real *and already fought* via the neutral **AGENTS.md** standard; (c) neutral cross-vendor layers have strong precedent (**MCP**) plus a data-trust counterweight. The residual risk is narrower than "is the thesis real": it's whether teams pay a third party for **dynamic learned-memory + a reuse ledger** vs. waiting for a free neutral standard to absorb it (as AGENTS.md absorbed static config). The proven cross-tool pain is at the **static-config** layer; the **learned-memory + ledger** slot is unbuilt — that's ours.

## What to take (learn, don't copy)
- **Git** as the append-only/versioned/conflict substrate (Letta) — evaluate vs Graphiti's temporal graph.
- **Mem0's** open-sourced per-question eval rigor; its extraction prompt pattern (drop the delete).
- **xMemory's** schema + explicit lineage validates our provenance envelope.
- **turbopuffer** as a cheap vector substrate if one is needed.
