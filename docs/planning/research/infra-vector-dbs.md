# Vector-DB Infra Lane — Pinecone · turbopuffer · Weaviate

*Last updated: 2026-05-30. Lane: vector/search **infrastructure** (the storage substrate) — NOT direct memory-reuse competitors.*
*Feeds `~/dev/docs/thesis.md` Addendum A. Every claim source-linked.*

## Why grouped (and why they don't directly compete)
These are databases, not memory layers. Their "savings" story is **infrastructure cost** ($/GB, $/query) — not **token/knowledge reuse**. None has provenance, reuse-events, or an ROI ledger. Relevant to us as **(a)** a possible build-on substrate, **(b)** evidence of where coding tools already store vectors, **(c)** a contrast: they sell infra cost, the value/ledger layer sits *above* them.

## Pinecone — the incumbent vector DB
- **Stage:** $138M raised; $100M Series B (a16z); **$750M valuation**; ~$26.6M revenue 2024 (+66% YoY); headcount ~127 in 2026 (down from ~200); 2025 acquisition rumors. [[Crunchbase](https://news.crunchbase.com/ai-robotics/startup-venture-funding-database-pinecone/), [Series B](https://www.pinecone.io/blog/series-b/)]
- **Positioning:** managed vector DB, "battle tested for production" — sells performance/scale/reliability/security (SOC2, HIPAA), **not** LLM cost. [[product](https://www.pinecone.io/product/)]
- **Cost claim:** none direct. The "save LLM tokens" narrative is **semantic-caching built on top** (community/partner pattern: cache-hit-rate × avoided call cost; **40–80%** cited) — not Pinecone's own claim. [[semantic cache](https://portkey.ai/blog/reducing-llm-costs-and-latency-semantic-cache/)]
- **Pricing:** Starter free → Builder $20 → Standard $50-min PAYG → Enterprise $500-min; audit logs Enterprise-only.

## turbopuffer — cheap, object-storage-first challenger
- **What:** serverless vector + full-text search on **object storage (S3/GCS)**. Lists **Cursor, Notion, Linear, Anthropic** as customers. [[turbopuffer](https://turbopuffer.com/)]
- **Cost (hard numbers):** **$1/mo per million vectors + $4 per million queries**; storage ~**$70/TB/mo** (S3 + SSD cache) vs ~$600–1,600/TB for RAM-cache incumbents; object storage ~$0.02/GB. **Cursor migrated (Nov 2023) → costs dropped 95%.** [[pmf.show](https://www.pmf.show/blog/how-simon-eskildsen-built-turbopuffer-the-vector-db-powering-cursor-and-notion/), [particula](https://particula.tech/blog/turbopuffer-vs-pinecone-vector-database-migration)]
- **Caveat:** Zilliz argues the object-storage trade-off (cold-latency/consistency) is understated. [[Zilliz](https://zilliz.com/blog/the-cost-of-consequence-what-no-one-tells-you-about-serverless-vector-databases)]
- **For us:** the most attractive **build-on substrate** for cheap vector storage — and notable that our would-be users' harnesses (Cursor/Anthropic) already run on it. No memory/provenance semantics.

## Weaviate — OSS vector DB moving up-stack into "Agents"
- **What:** open-source vector DB (`weaviate/weaviate`) + Weaviate Cloud. Now ships **"Agents": Query, Transformation, Personalization, Database.** "For AI engineers." [[weaviate.io](https://weaviate.io/)]
- **Pricing:** Free trial → **Flex $45/mo** PAYG → **Premium $400/mo**; **Query Agent $30/org/mo** (4k req incl.); Transformation/Personalization Agents unpriced. [[pricing](https://weaviate.io/pricing)]
- **Cost claim:** "4× memory reduction" via RQ-8 rotational quantization — an **infra (RAM) reduction**, not token/LLM savings.
- **For us:** the "Personalization Agent" hints at memory-ish features — watch it, but it's infra-up-stack, not a cross-vendor reuse ledger.

## Net for the thesis
The infra lane sells **$/GB and $/query** — real and measurable, but **storage cost, not knowledge reuse**. None offers provenance, reuse-events, or an ROI ledger → the seam sits *above* the vector DB. If we need a substrate, **turbopuffer** is the most attractive; the **value/ledger layer is ours to build regardless of which DB sits underneath.**
