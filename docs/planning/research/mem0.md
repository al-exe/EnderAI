# Mem0 — Competitor Teardown

*Last updated: 2026-05-30. Lane: agent-memory layer (category leader by adoption).*
*Feeds: `~/dev/docs/thesis.md` Addendum A. Every claim source-linked.*

## TL;DR
The most-adopted memory layer (41k GitHub stars, 14M downloads, **AWS Agent SDK's exclusive memory provider**, $24M Series A). It has a **real, open-sourced, per-question eval framework** — so the earlier "they don't prove it" was wrong. **But** the savings story is a **benchmark counterfactual vs full-context** (read-side only; write/extraction cost reported separately), it's **single-system**, and its accuracy is actually *lower* than full-context. No cross-vendor/cross-person reuse, no ROI ledger. Its A.U.D.N. consolidation **deletes** — incompatible with an append-only system-of-record.

## What / stage
- YC; launched Jan 2024. **$24M total** ($3.9M seed + $20M Series A, Jul 2025; Basis Set Ventures, Peak XV, GitHub Fund, YC; angels incl. CEOs of Datadog/Supabase/PostHog, Dharmesh Shah, Scott Belsky). [[PRNewswire](https://www.prnewswire.com/news-releases/mem0-raises-24m-series-a-to-build-memory-layer-for-ai-agents-302597157.html)]
- Traction: 41k stars, 14M downloads, API calls **35M→186M** (Q1→Q3 2025), 80k+ cloud signups; **AWS chose Mem0 as exclusive memory provider for its Agent SDK.** [[Built In SF](https://www.builtinsf.com/articles/mem0-raises-24m-AI-memory-infrastructure-20251103)]
- **Apache-2.0** OSS + managed platform (Hobby free → Starter $19 → Growth $79 → **Pro $249**/mo). Gated to paid: analytics, on-prem, **audit logs** (Growth+), **SSO** (Pro). Graph memory positioned as a higher-tier/managed feature. [[pricing](https://mem0.ai/pricing)]

## Mechanism
- LLM **fact extraction** → **A.U.D.N.** consolidation (Add / Update / **Delete** / No-op): retrieve top-K similar memories, LLM picks the action. Vector + optional graph + rerank retrieval.
- Scoped per-user / per-agent / per-app; "unlimited end users." No cross-tool / cross-org shared record.
- ⚠️ **Deletes** obsolete memories — breaks an append-only provenance ledger (the cited artifact disappears).

## How they measure (the part you wanted — hard evidence)
- **Open-sourced eval** ("anyone can reproduce"), three axes: **accuracy** (LLM-as-judge), **cost** (context tokens/query, tiktoken `cl100k`), **latency**. Benchmarks: **LoCoMo, LongMemEval, BEAM (1M/10M tokens).** [[eval doc](https://docs.mem0.ai/core-concepts/memory-evaluation)]
- Token efficiency: **~6,700–6,956 mean tokens/query** vs full-context **"25,000+ tokens/query."** Per-question output logs retrieval metrics, prompt/completion token counts, and judge score+reasoning; cutoffs at top-10/50/200. → **per-instance auditable on the benchmark.**
- Paper (arxiv 2504.19413, GPT-4o-mini): **">90% token cost saved" + "91% lower p95 latency" (1.44s vs 17.12s)** vs full-context; **+26% LLM-as-judge over OpenAI memory** (66.9 vs 52.9). [[arxiv](https://arxiv.org/abs/2504.19413)]
- **Caveats = the gap:**
  1. ">90%" is **read-side only**; memory extraction/write (~7K tokens/conversation) is reported separately (§4.5), *not netted into the headline*.
  2. Full-context scores **higher accuracy (~73% vs Mem0 67%)** — the real pitch is "competitive accuracy at a fraction of tokens/latency," not "better answers."
  3. It's a **benchmark/synthetic counterfactual**, not measured *production* reuse with provenance.
- **Credibility war:** Mem0 re-evaluated **Zep's claimed 84% LoCoMo down to 58.44%** (category-inclusion math error + non-standard prompts + single-run reporting). → numbers in this space are self-reported and **don't replicate**. [[zep-papers #5](https://github.com/getzep/zep-papers/issues/5)]

## Overlap / blindspots / our cut points
- **Overlap:** long-term memory + the token-efficiency claim + the category buyers already know.
- **Cut points:** (1) **benchmark counterfactual ≠ production reuse-with-provenance**; (2) **single-system / single-tool** — no cross-vendor or cross-person reuse (the number no single vendor can show); (3) **no ROI ledger** (token-efficiency, not attributed confirmed-reuse); (4) **deletes** — cannot be a system-of-record.
- **Take:** their **eval rigor** (per-question token+judge logging, open-sourced) is a good bar; learn the **extraction prompt pattern** — but never adopt the delete.

## Sources
[Series A](https://www.prnewswire.com/news-releases/mem0-raises-24m-series-a-to-build-memory-layer-for-ai-agents-302597157.html) · [Traction](https://www.builtinsf.com/articles/mem0-raises-24m-AI-memory-infrastructure-20251103) · [Eval methodology](https://docs.mem0.ai/core-concepts/memory-evaluation) · [Paper 2504.19413](https://arxiv.org/abs/2504.19413) · [Zep benchmark dispute](https://github.com/getzep/zep-papers/issues/5) · [Pricing](https://mem0.ai/pricing) · [GitHub](https://github.com/mem0ai/mem0)
