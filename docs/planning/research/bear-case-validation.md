# Bear-Case Validation — per-harness vs. cross-vendor

*Created 2026-05-30 (PM-4). Feeds thesis **Addendum D §3**. Pressure-tests the load-bearing assumption behind the cross-vendor moat. Source-linked; **Reddit excluded** (crawler blocked; Alex owns that channel).*

> **The bear case (from Addendum B/C):** the market is building memory **per-harness** (Letta Code, Cursor, Claude Code) — the opposite of our cross-vendor bet. We win **only if** teams (a) run multiple harnesses, (b) feel fragmented-memory pain, and (c) trust a neutral third party over their vendor.

## Verdict: **survivable / partially validated.** Legs (a) and (b) supported; (c) has strong *precedent* plus a real counterweight.

### Leg (a) — Do teams run multiple harnesses? → **Supported (strong)**
- 2025 Stack Overflow Developer Survey: 84% use/plan to use AI tools; AI-native IDEs **Cursor (18%), Claude Code (10%), Windsurf (5%)** appear for the first time *alongside* (not replacing) VS Code — "many devs run both."
- Aggregated industry stats report multi-tool workflows now dominant (a widely-cited figure: **~59% of devs running 3+ AI tools in parallel**), with large enterprises using deliberate multi-tool strategies. *(Secondary aggregators — treat the exact % as directional, not gospel.)*
- Sources: [SO 2025 AI survey](https://survey.stackoverflow.co/2025/ai/) · [Visual Studio Magazine on SO 2025](https://visualstudiomagazine.com/articles/2025/08/01/stack-overflow-dev-survey-visual-studio-vs-code-hold-of-ai-ides-to-remain-on-top.aspx) · [Pragmatic Engineer — AI Tooling 2026](https://newsletter.pragmaticengineer.com/p/ai-tooling-2026) · [index.dev AI pair-programming stats](https://www.index.dev/blog/ai-pair-programming-statistics)

### Leg (b) — Do they feel cross-tool fragmentation pain? → **Supported (strong) — and the market is *already* fighting it**
- The pain is named and concrete: a dev on multiple tools maintains **CLAUDE.md + .cursorrules + .github/copilot-instructions.md** separately; rules "accumulate, duplicate, and conflict."
- **AGENTS.md** emerged as the *neutral, cross-tool* answer — **20,000+ repos**, originated by OpenAI, now governed by the **Linux Foundation's Agentic AI Foundation**; read natively by Codex, Copilot, Cursor, Windsurf, Amp, Devin.
- **Read for us:** the fragmentation pain is real *and* the market demonstrably rallies behind a **neutral** standard to solve it. **But** AGENTS.md solves the **static-config** layer — *what you write down*. The **dynamic, learned-memory** layer (what agents *figure out*) + the **reuse ledger** is the unbuilt neutral slot. That's our line: *AGENTS.md captures what you write down; Taskforce captures what your agents figure out.*
- Sources: [InfoQ — AGENTS.md as open standard](https://www.infoq.com/news/2025/08/agents-md/) · [agents.md](https://agents.md/) · [config-files compared](https://www.tokencentric.app/blog/ai-coding-config-files-compared)

### Leg (c) — Would they trust a *neutral third party* over their vendor? → **Strong precedent + a real counterweight**
- **Precedent the ecosystem adopts neutral cross-vendor layers:** **MCP** (Anthropic, Nov 2024) was adopted by **OpenAI (Mar 2025)** and **Google DeepMind (Apr 2025)**, then **donated to a Linux Foundation fund (Agentic AI Foundation, Dec 2025)** — cross-vendor neutrality, formalized. AGENTS.md is the second instance of the same pattern.
- **Counterweight (respect it):** enterprises are anxious about code context going to third parties ("context-window leakage"); they deploy **context filters** to choose which repos may be sent to external providers. → trust is *earnable, not free*.
- **Why survivable:** that data-trust concern is **our own A3 boundary-scrub problem** (scrub secrets/PII at capture), and it applies to the harness vendors too — it is not unique friction against a neutral layer.
- Sources: [MCP — Wikipedia](https://en.wikipedia.org/wiki/Model_Context_Protocol) · [Anthropic donates MCP to AAIF/Linux Foundation](https://www.anthropic.com/news/donating-the-model-context-protocol-and-establishing-of-the-agentic-ai-foundation) · [The New Stack — why MCP won](https://thenewstack.io/why-the-model-context-protocol-won/) · [Sourcegraph — enterprise AI-coding security](https://sourcegraph.com/blog/security-considerations-for-enterprises-adopting-ai-coding-assistants)

## What this does and doesn't settle
- **Settles:** multi-tool reality and cross-tool pain are real; the ecosystem rewards neutral standards. The cross-vendor thesis is **not** disproven — the opposite.
- **Does NOT settle:** whether teams will pay a *third party* specifically for **dynamic learned-memory + a reuse ledger** (vs. waiting for a free neutral standard to absorb it, the way AGENTS.md absorbed static config). **That** is the real residual risk — and it's exactly what the empty-cell proof (`taskforce-north-star-and-proof-plan.md`) is meant to make undeniable.
