# xMemory (xmemory.ai) — Competitor Teardown

*Last updated: 2026-05-30. Lane: agent-memory layer (schema-grounded). **The closest competitor to our provenance angle.***
*Feeds: `~/dev/docs/thesis.md` Addendum A. Every claim source-linked.*

## TL;DR
Schema-based memory that converts NL writes into "typed, validated, queryable state." Competes on **correctness** (state-tracking), not just token savings. Its headline **"3×+ fewer tokens" is an admitted *symbolic engineering estimate***, not measured. Crucially, it ships **first-class provenance/lineage** (trace IDs, record→session/source links) — the **closest competitor to our "provenance envelope."** Research-grade; MIT-licensed code.

## What / stage
- Origin paper: "From Unstructured Recall to Schema-Grounded Memory: Reliable AI Memory via Iterative, Schema-Aware Extraction" (arxiv 2604.27906). Positioned as "schema-based memory for AI agents." MIT license (commercial-friendly). [[xmemory.ai](https://xmemory.ai/), [arxiv](https://arxiv.org/abs/2604.27906)]

## Mechanism
- **Iterative, schema-aware write path:** object detection → field detection → field-value extraction, with **validation gates, local retries, stateful prompt control.** Typed/validated state vs free text.
- Field critique: "Embedding retrieval returns a ranked subset, not an exhaustive, constraint-satisfying result… semantic similarity over unstructured text is insufficient by construction." → argues *against* top-K vector retrieval.

## How they measure (hard evidence)
- **Headline "3×+" is illustrative:** `S = (w_t + R·r_t)/(w_x + R·r_x) = (3 + 10·6)/(10 + 10·1) = 63/20 ≈ 3.15`, under *assumed* ratios (R=10 reads/write). Paper states it's **"an engineering estimate, not a benchmark result,"** and the write-side assumption "may understate effective write-side work."
- **Measured numbers (smaller, and honest about write cost):** vs A-Mem, 9,103→4,711 tokens (~48%); GPT-5-nano 9,155→6,581 (~28%); LoCoMo (Qwen3-8B) ~29% fewer tokens. Benchmarks are **custom** (insurance-claims extraction; corporate/edu/medical/finance; Splitwise) — explicitly **excludes** standard LoCoMo/PerLTQA from main eval. **Includes the full write-path cost** (more honest than Mem0's read-only headline).
- **Correctness focus:** **97.10% F1 vs Mem0 (no graph) 87.24%** on state/mutation tracking; "all third-party systems without schema constraints accumulate substantial state errors." Graph variants gave "no meaningful help" on mutation tracking.

## Provenance (the notable overlap with us)
- First-class: **"links from records to the sessions (and, by extension, actors and sources) from which facts were derived,"** plus "conflict handling and diff computation as explicit operations." Site adds an **operations explorer, write inspection with lineage, trace IDs to sessions/sources, and field-level access control.** → **the closest competitor to our provenance-envelope idea.**

## Overlap / blindspots / our cut points
- **Overlap:** provenance/lineage + write-side validation + a reliability story. Ahead of Mem0 on provenance.
- **Cut points:** (1) provenance here serves **memory-operation reliability/debugging within one system**, *not* a cross-vendor reuse-ROI ledger; (2) **single-system** — no cross-tool / cross-person capture; (3) savings are illustrative or single-system benchmark, not production reuse; (4) schema-heavy write path = friction (their own tradeoff: "write-path complexity vs read-path simplicity").
- **Take:** schema-grounded extraction + explicit provenance is the *right instinct* — it validates our envelope. **Watch them as the most architecturally-aligned competitor.**

## Sources
[xmemory.ai](https://xmemory.ai/) · [Paper 2604.27906](https://arxiv.org/abs/2604.27906) · [VentureBeat](https://venturebeat.com/orchestration/how-xmemory-cuts-token-costs-and-context-bloat-in-ai-agents) · [Maxim deep-dive](https://www.getmaxim.ai/blog/xmemory-why-top-k-retrieval-breaks-for-agent-memory/)
