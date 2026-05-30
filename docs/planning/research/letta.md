# Letta (formerly MemGPT) — Competitor Teardown

*Last updated: 2026-05-30. Lane: agent-memory layer / memory-first coding agent.*
*Feeds: `~/dev/docs/thesis.md` Addendum A (competitive landscape). Every claim source-linked.*

> **Assessment: the most directly competitive — and most sophisticated — company in this set.**

## TL;DR
Letta has independently built most of what we'd call "our" novel mechanism: **git-versioned (append-only) memory, offline consolidation ("sleep-time compute"), multi-agent conflict resolution via git merge, and a code-verified cost-per-task benchmark.** Mechanism is, again, not a moat. The **only** durable wedge vs Letta is **neutrality / cross-vendor** (Letta is itself a harness, "Letta Code", competing with Cursor/Claude Code; its memory is scoped to Letta agents — we sit *across* the harness you already use) plus the **reuse/ROI ledger** (they have git-provenance of memory *changes*, not attributed reuse-events with savings). **Bear case:** the market trend is *per-harness* memory, the opposite of our cross-vendor bet.

## What / stage
- Spun out of **MemGPT** (UC Berkeley Sky Computing Lab). Emerged from stealth **Sept 2024, $10M seed** (Felicis, Founders Fund, YC). [[hpcwire](https://www.hpcwire.com/bigdatawire/this-just-in/letta-emerges-from-stealth-with-10m-to-build-ai-agents-with-advanced-memory/)]
- Positioning: "the platform for building **stateful agents**: AI with advanced memory that can learn and self-improve over time." [[GitHub](https://github.com/letta-ai/letta)]
- Open-source core (`letta-ai/letta`, `letta-ai/letta-code`) + **Letta Cloud** (Free: 3 agents BYOK; Pro $20/mo + $20 credits; Max $200/mo; Enterprise custom).

## The mechanism — they've built most of "our" architecture
- **Context Repositories — git-based memory for coding agents (Feb 2026):** "git-backed memory… every change to memory is automatically versioned with informative commit messages." Context lives in the **local filesystem**; the agent uses terminal/coding tools to manage its own context. → **append-only + versioned**, via git. [[blog](https://www.letta.com/blog/context-repositories)]
- **Multi-agent conflict resolution via git:** "each subagent [gets] an isolated worktree, multiple subagents can process and write to memory concurrently, then merge… through git-based conflict resolution." → solves concurrent-write / contradiction handling.
- **Sleep-time compute (arxiv 2504.13171):** offline pre-computation over context before queries — "reduce the amount of test-time compute needed to achieve the same accuracy by ~5x"; "amortizing… across related queries… decrease the average cost per query by 2.5×." → our **in-loop-dumb / out-of-loop-smart + consolidation-as-learning**, named and published. [[arxiv](https://arxiv.org/abs/2504.13171)]
- **Filesystem-as-memory thesis:** blog "Benchmarking AI Agent Memory: Is a Filesystem All You Need?" argues filesystem (not vector/graph) suffices — relevant to our substrate choice. [[blog](https://www.letta.com/blog/benchmarking-ai-agent-memory)]

## How they measure (hard evidence)
- **Context-Bench** (leaderboard.letta.com): benchmarks "agentic context engineering" — Filesystem Suite (chain file ops, trace entities, multi-hop retrieval) + Skills Suite (discover/load skills). Metrics: **accuracy + total cost ($/eval)** via LLM-as-judge on **code-verified ground truths**; compares Anthropic/OpenAI/Google/DeepSeek/Mistral/etc. Token-efficiency/latency not standalone (cost implicitly = tokens). [[leaderboard](https://leaderboard.letta.com/)]
- No "X% token savings" marketing headline; sleep-time-compute's ~5x / 2.5× are **benchmark** results on Stateful GSM-Symbolic / AIME (math reasoning), not production reuse.

## Overlap with us (direct competition)
- Memory **for coding agents**, **git-versioned**, **shared across sessions** (Conversations API, Jan 2026: "shared memory across parallel experiences"). Exact problem space.
- **Provenance-ish via git history** (author/time/diff of every memory change) — erodes part of our provenance claim (but ≠ a reuse-ROI ledger).

## Blindspots / our cut points vs Letta
1. **Letta is a harness, not a neutral layer.** "Letta Code" is their *own* coding agent; memory scoped to Letta agents. Use Cursor/Claude Code and Letta's memory doesn't follow you. → **our wedge: neutral capture *across* the harness you already use.** *(Verify: is Letta memory usable outside Letta agents? Appears Letta-centric.)*
2. **Git-provenance ≠ reuse-ROI ledger.** Git tracks *changes to memory*, not *"this memory was surfaced + used + saved N tokens, attributed across tools/people."* The auditable cross-boundary reuse ledger is still open.
3. **Single-vendor scope.** No cross-vendor / cross-org neutral record.

## Bear case this surfaces (respect it)
The market is investing in **per-harness** memory (Letta Code, Cursor, Claude Code) — the *opposite* of our cross-vendor-neutral bet. We win only if (a) teams genuinely run multiple harnesses and feel fragmented-memory pain, and (b) they'd trust a neutral third party over their harness vendor. **Unvalidated.** Letta's trajectory is the strongest evidence the vertical path is where money/talent is going.

## What we can take (learn, don't copy)
- **Git as the append-only / versioned / conflict-resolution substrate** is a genuinely good idea — evaluate seriously vs. a temporal graph (Graphiti) for our store.
- **"Sleep-time compute"** = citable vocabulary + efficiency result (~2.5×/query amortized) for our offline-consolidation principle.
- **Context-Bench** (code-verified, cost-per-task) is a better measurement model than LoCoMo self-reports.

## Sources
[Funding/stealth](https://www.hpcwire.com/bigdatawire/this-just-in/letta-emerges-from-stealth-with-10m-to-build-ai-agents-with-advanced-memory/) · [Context Repositories](https://www.letta.com/blog/context-repositories) · [Sleep-time Compute (2504.13171)](https://arxiv.org/abs/2504.13171) · [Context-Bench](https://leaderboard.letta.com/) · [Filesystem-memory benchmark](https://www.letta.com/blog/benchmarking-ai-agent-memory) · [GitHub](https://github.com/letta-ai/letta) · [Our next phase](https://www.letta.com/blog/our-next-phase)
