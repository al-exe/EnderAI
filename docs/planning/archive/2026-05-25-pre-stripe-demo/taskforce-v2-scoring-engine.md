# Taskforce V2 Scoring Engine

Last updated: 2026-05-18

Companion to [`taskforce-v2-architecture.md`](./taskforce-v2-architecture.md). The architecture writeup covers the full lifecycle; this one zooms in on the **congruence scoring engine** that decides whether `enderai_begin_document` reuses an existing V2 document or creates a new one.

Everything described here lives under `EnderAI/mcp/enderai-api-mcp/src/v2Documents/scoring/`:

```
scoring/
├── index.ts      — barrel
├── types.ts      — SignalName, SignalResult, CongruenceScore, Decision
├── config.ts     — DEFAULT_CONFIG (weights, bands, thresholds)
├── engine.ts     — scoreCongruence(), decide()
└── signals.ts    — the twelve default scorers + shared text utilities
```

## 1. Why A Scoring Engine

The product question the engine answers is: *given a new agent request and the user's existing V2 documents, should we reuse one of them or create a new one?*

Three design commitments shape everything below:

1. **Deterministic.** Same request + same candidate set → same decision. No LLM in the loop. This is what makes the choice auditable to both the agent and the user.
2. **Explainable.** Every signal produces a human-readable `reason`. Every decision returns its reasons and the full sorted candidate list with scores. `enderai_begin_document` surfaces them in `match_reasons` and `candidate_summaries`.
3. **Conservative on false reuse.** Most false reuses are not "low overall score" — they're "high score on the wrong axis". The engine has dedicated **conflict signals** with large negative weights specifically to dominate that failure mode.

## 2. Inputs And Outputs

The engine consumes a normalized `MatchRequest` (built by `tools.ts:normalizeRequest`):

```ts
type MatchRequest = {
  request_summary: string;
  title?: string;
  goal?: string;
  acceptance_criteria?: string;
  collaborators: string[];
  files: string[];
  symbols: string[];
  errors: string[];
  contexts: string[];
  visibility?: "private" | "organization";
  reuse_within_seconds?: number;  // default 30 days
  force_new?: boolean;            // honored by caller, not engine
  document_id?: string;           // honored by caller, not engine
  demo?: boolean;
};
```

…and a `candidates: V2Document[]` list (already filtered by demo/visibility upstream).

It returns a `Decision`:

```ts
type Decision = {
  action: "reuse" | "create";
  documentId?: string;        // when action === "reuse"
  score?: CongruenceScore;    // top candidate's score, when reusing
  candidates: ScoredCandidate[]; // full sorted list, scores included
  reason: string;             // engine's own one-line justification
};
```

The engine **does not** handle the `force_new` or explicit `document_id` paths — `tools.ts:beginDocument` short-circuits both before calling `decide()`. The engine's job starts at "we already chose to score".

## 3. Shared Text Toolkit

A handful of utilities in `signals.ts` are reused across signals; understanding them up front makes the per-signal sections short.

### `tokenize(value)`
Lowercases, replaces any non-`[L N _ . / -]` character with whitespace, splits on whitespace, drops tokens of length ≤ 1, and drops a small English stopword set (`the`, `a`, `and`, `to`, `in`, …). Note that `.`, `/`, `-`, and `_` are preserved — so file paths and dotted identifiers survive tokenization.

### `jaccard(a, b)`
Standard set-Jaccard: `|a ∩ b| / |a ∪ b|`. Returns 0 if either set is empty. Used only by `title-overlap`.

### `docCorpus(doc)`
Concatenates `title`, `description`, `human_summary`, `ai_generated_summary`, the flattened `main_body` text, and the flattened `details_markdown_sections` markdown into one big string. Several signals do substring lookups against this corpus rather than tokenizing it — that's deliberate, because they're matching things like file paths or error strings that lose meaning under tokenization.

### `ratio(matched, requested)`
`min(1, matched / requested)`, with `requested === 0 → 0`. The standard "what fraction of the requested items did we find" denominator.

### `anchorTokens(value)`
A second tokenizer used only by `anchor-overlap`. Splits on whitespace **and** `/ _ . -`, so an anchor id like `db-migration_2026-05` becomes `{db, migration, 2026, 05}`. This is intentionally more aggressive than the main `tokenize()` because anchor ids are slugged identifiers, not natural prose.

### Stopwords
The full set: `the, a, an, and, or, but, of, to, in, on, for, with, by, is, are, was, were, be, been, being, this, that, these, those, it, its, as, at, from`. Small, hardcoded, English-only. Anything outside English will mostly survive intact because nothing else gets dropped.

## 4. Positive Signals

Eight positive scorers. Each returns `strength ∈ [0, 1]`; the engine multiplies by the configured weight. Default weights sum to **100** — a perfect candidate scores 100 before any conflict penalty.

| Signal | Default weight | What it measures |
|---|---:|---|
| `title-overlap` | 25 | Title↔request title/summary token similarity |
| `file-overlap` | 20 | Fraction of request files mentioned anywhere in the doc |
| `error-overlap` | 15 | Fraction of request error strings present in the doc |
| `symbol-overlap` | 10 | Fraction of request symbols present in the doc |
| `recency` | 10 | Linear decay of `updated_at` over the reuse window |
| `intent-phrase` | 10 | "continue", "follow up", "same issue", etc. in request |
| `anchor-overlap` | 5 | Request hints touch existing Details anchor ids |
| `collaborator-overlap` | 5 | Fraction of request collaborators on the doc |

### 4.1 `title-overlap` — weight 25

The single highest-weighted positive. Two-tier behavior:

- **Exact match** (case-folded, trimmed) → `strength = 1`, reason `Exact title match: "..."`.
- **Otherwise** → Jaccard between the tokenized candidate title and either `request.title` (if present) or `request.request_summary`. Reports up to six matched tokens for the reason string.

Why exact-match is special-cased: Jaccard penalizes longer titles even when the short request title is a strict subset, so two titles that humans would call "the same" can score < 1 on tokens alone. The exact-match short-circuit recovers that case.

### 4.2 `file-overlap` — weight 20

For each `request.files[i]`, looks for either the full normalized path **or** the basename inside the candidate's lowercased `docCorpus`. `strength = ratio(matched, requested)`. Reason: `Doc mentions M/N request files`.

Notable: the basename fallback means a request for `src/auth/login.ts` matches a doc that only ever wrote `login.ts`. That's usually what you want, but it can over-fire on common basenames like `index.ts` or `README.md`. There is no path-stem dedup today.

### 4.3 `symbol-overlap` — weight 10

Case-insensitive substring lookup for each `request.symbols[i]` inside `docCorpus(candidate)`. `strength = ratio(matched, requested)`.

Because it's a substring match on the raw corpus, a symbol like `User` will also match `Username`, `UserService`, etc. — a feature for fuzzy product terms, occasionally a bug for short symbol names. Pass longer/more-distinctive symbols when you care.

### 4.4 `error-overlap` — weight 15

Same shape as `symbol-overlap` but for `request.errors`. Weighted higher because shared error strings are a strong "same incident" signal — they're usually distinctive enough that a substring hit really does mean "the doc talks about this error".

### 4.5 `anchor-overlap` — weight 5

The cleverest positive scorer.

1. Build a `hintTokens` set from the request's `files + symbols + errors + contexts + title`, run through the slug-aware `anchorTokens()` splitter.
2. For each Details section's `anchor_id`, tokenize it the same way and check whether any token appears in `hintTokens`.
3. `strength = ratio(matchedAnchors, min(numAnchors, max(1, numHints)))`.

The denominator is deliberately asymmetric: it caps at the smaller of "available anchors" or "supplied hints", so a doc with one anchor that matches one of three hints still scores 1.0, not 0.33. The intuition: anchor overlap is a coarse "the doc is organized around the things this request mentions" check, not a coverage check.

Returns strength 0 with an explicit reason when the doc has no anchors or the request has no hints. Both happen often enough that silent zeros would be confusing.

### 4.6 `collaborator-overlap` — weight 5

Case-insensitive set membership: `strength = ratio(matched, requested)`. Returns 0 when either side has an empty list — collaborator overlap is informative when present, but its absence is not.

### 4.7 `recency` — weight 10

Linear decay over the reuse window:

```
ageSeconds = max(0, (now - updated_at_ms) / 1000)
strength   = max(0, 1 - ageSeconds / windowSeconds)
```

`windowSeconds` is `request.reuse_within_seconds ?? 30 days`. Returns 0 with an explicit reason when `updated_at` is missing or unparseable. The reason string reports age in days (`Updated N days ago`) or `Updated outside the N-day reuse window`.

Linear decay rather than exponential is intentional: it's easy to predict and easy to explain in the UI. A doc updated yesterday scores ~0.97, one updated 15 days ago scores 0.5, one updated 30+ days ago scores 0.

### 4.8 `intent-phrase` — weight 10

Substring scan of `request_summary + goal` for a small phrase list:

```
continue, continuing, follow up, follow-up, followup, same issue,
same incident, still, again, update on, previous, ongoing, as before
```

`strength = min(1, matchedCount / 2)`. So one phrase gives 0.5, two or more give 1.0.

This signal does **not** depend on the candidate at all — it's a request-side flag that says "the user thinks of this as continuing prior work, so weight reuse higher". The same value is added to every candidate; it just lifts the band threshold globally for that request.

It also interacts with the terminal-state conflict (§5.4) — a request that explicitly says "continue" turns off the terminal-state conflict for an otherwise-terminal doc.

## 5. Conflict Signals

Four conflict scorers. Each returns `strength ∈ [0, 1]` and is multiplied by a **negative** weight. Conflicts can pull the raw total deep negative; the engine then clamps to `[0, 100]`. The clamp matters: a conflict won't push a score below 0, but it absolutely will drown out positives.

| Signal | Default weight | Fires when |
|---|---:|---|
| `tenant-conflict` | -60 | Request and doc both name tenants, and they're disjoint |
| `repo-conflict` | -30 | Request files and doc file-style references share no top-level dir |
| `error-family-conflict` | -25 | Request and doc both mention error families, all disjoint |
| `terminal-state-conflict` | -25 | Doc looks terminal and the request reads as new work |

A conflict at strength 1 with weight -60 cancels the entire positive ceiling — that's the point.

### 5.1 `tenant-conflict` — weight -60

Mechanism:

1. Pull tenant hints out of `request.contexts` by matching `^(tenant|customer|client|account|org)\s*[:=]\s*(.+)$`. So `"customer: acme"` and `"tenant=acme"` are extracted as `acme`.
2. If the request supplied no tenant hints → strength 0 ("Request has no explicit tenant/customer context"). The engine never invents tenant identity from free text.
3. Otherwise, scan the doc's lowercased corpus with the regex `(tenant|customer|client|account|org)\s*[:=]?\s*['"\`]?([a-z0-9_-]+)` and collect every matched identifier.
4. If the doc mentions no tenants → 0. If any request tenant appears in the doc's tenant set → 0 with reason "Tenant matches". Otherwise → **strength 1**, with both sets in the reason for transparency.

The largest conflict weight in the system. The shape — "fires only when both sides explicitly name tenants, and they're disjoint" — is what keeps it safe. It will never fire on a generic doc that just happens to lack tenant tags.

### 5.2 `repo-conflict` — weight -30

1. If the request has no files → 0 (no signal to derive).
2. Extract file-style references from the doc's corpus with `/[a-z0-9_.-]+\/[a-z0-9_./-]+/g`.
3. Compute `topDirectories()` — first path segment, lowercased — for both sides.
4. If the request's top-dir set is empty → 0. If the doc and request top-dirs intersect → 0. Otherwise → **strength 1**.

"Top-level directory" is a proxy for "which repo or subsystem this is about". Imperfect — monorepos and shared `src/` make it noisier — but the conflict shape (only fires on full disjointness) keeps false positives down. The reason string reports up to four doc top-dirs so the agent can see what got matched.

### 5.3 `error-family-conflict` — weight -25

The most coarse-grained conflict. Token list:

```
timeout, permission, auth, 401, 403, 404, 500, 502, 503, 504,
syntax, null, undefined, deadlock, oom, memory, cors, ssl, tls, dns
```

1. Build `requestFamilies = { fam ∈ list : some request error contains fam }`.
2. If empty → 0.
3. Build `docFamilies` by tokenizing the candidate corpus and keeping tokens in the list.
4. If empty → 0. If `requestFamilies ∩ docFamilies` non-empty → 0. Otherwise → **strength 1**.

The mechanism distinguishes "5xx incident doc" from "401 auth doc" without trying to be clever about it. It's intentionally a closed list: novel error families add nothing to either side and so cannot trigger a false conflict.

### 5.4 `terminal-state-conflict` — weight -25

1. Scan `flattenDetailsText(doc).toLowerCase()` for markers: `## outcome`, `## resolution`, `status: done`, `status: closed`, `status: resolved`, `status: superseded`, `marked complete`, `incident closed`.
2. No matches → 0.
3. If the request text matches any of the `CONTINUE_PHRASES` from §4.8 → 0 (with reason "Doc is terminal but request explicitly continues prior work").
4. Otherwise → **strength 1**.

This is the conflict that fires when an agent tries to "drop more work into" a doc that already concluded. The interaction with continuation phrases is the escape valve — if the user really does mean "continue the same incident", the doc can be reused.

> **Concrete example from this session:** when `enderai_begin_document` was called for *this* writeup, the previous architecture doc had already been finalized (its Details contains a `## Outcome` section with `status: done`). The scorer returned `terminal-state-conflict` at strength 1 and the doc scored 18/100, so a fresh document was created. The Begin tool's response showed: `conflicts: ["terminal-state-conflict"]`, `total: 18`, `band: "low"`. That is the engine working exactly as intended.

## 6. The Engine Math

`scoreCongruence(candidate, request, config)` from `engine.ts`:

```ts
raw = Σ over signals: result.strength * config.weights[result.name]
total = round(clamp(raw, 0, 100))
band  = bandFor(total)
```

`bandFor`:

```
total ≥ 70  → "high"
total ≥ 45  → "medium"
otherwise   → "low"
```

Two derived fields go into the returned `CongruenceScore`:

- `weakSignals`: positive signals where `kind === "positive"`, `weight > 0`, and `strength < weakSignalThreshold` (default **0.3**). Consumed by the self-heal planner — these are the dimensions the reused doc *didn't* already cover, so they're what the planner seeds into the new Current Work section.
- `conflicts`: every signal where `kind === "conflict"` and `strength > 0`. Returned in full so the agent can see exactly which conflicts fired even when the total clamped to a high-ish number.

`rawTotal` (pre-clamp) is also stored. Today it's only used in tests, but it's the right field to read if you ever want to know "by how much did conflicts pull this down" — a doc that scored 100 positive and -45 conflict and a doc that scored 60 positive and -5 conflict both clamp to 55, and only `rawTotal` tells them apart.

## 7. The Decision Rules

`decide({candidates, request, config})` from `engine.ts`:

1. Score every candidate, sort by `total` desc.
2. **Zero candidates** → `create`, reason `"No candidate documents to score"`.
3. **Top is `low`** → `create`, reason `Best candidate scored N (low band)…`.
4. **Top is `high`** → `reuse`, even if a runner-up is close. Rationale: the high band (≥ 70) already requires substantial positive coverage; tie-breaking inside it would just add noise.
5. **Top is `medium`** with any conflict signal fired → `create`. A medium score with a conflict is the textbook "high score on the wrong axis" failure mode the conflicts exist to catch.
6. **Top is `medium`**, no conflict, but `(top.total - runnerUp.total) < ambiguousLeadMargin` (default **10**) → `create`. Tied medium candidates are the second false-reuse mode: better to fork and let the user merge later than to silently pick one.
7. Otherwise → `reuse`.

Every branch sets a `reason` string. `tools.ts` prepends that reason to up to four "top positive signal reasons" from `reasonsFromScore()` and any conflict reasons, then returns the result as `match_reasons[]`. So the agent always sees both the meta-decision ("medium with clear lead") and the underlying signals that drove it.

## 8. Tuning Surface

`config.ts:DEFAULT_CONFIG` is the entire tuning surface. `scoreCongruence` and `decide` both accept an optional `config` arg, so callers (tests, future per-tenant configs) can swap the whole thing.

The knobs and what they do, ordered by how much they change behavior:

| Knob | Default | Effect when raised |
|---|---:|---|
| `bands.high` | 70 | Fewer auto-reuses in the high band |
| `bands.medium` | 45 | More creates at the low/medium boundary |
| `weights["tenant-conflict"]` | -60 | Stronger tenant isolation; can be lowered for single-tenant orgs |
| `weights["title-overlap"]` | 25 | Title becomes a stronger / weaker reuse driver |
| `weights["recency"]` | 10 | Older docs become harder / easier to reuse |
| `ambiguousLeadMargin` | 10 | Stricter / looser tie-breaking in medium band |
| `weakSignalThreshold` | 0.3 | Affects only self-heal: changes what gets seeded into Current Work |
| `signals` | `DEFAULT_SIGNALS` | Add custom scorers; the engine just walks the array |

Custom scorers only need to be `SignalScorer` functions returning a `SignalResult` with one of the named `SignalName` values (or a new name added to the type union and the weights map). The engine has no per-signal special cases.

## 9. Known Limits

Honest list of where the engine is weak today:

- **English-only stopwords and intent phrases.** Both `STOPWORDS` and `CONTINUE_PHRASES` are short hardcoded English lists. A Spanish-speaking team's "continuación" won't trip `intent-phrase`, but their files and symbols will still score normally.
- **Substring matching can over-fire on short tokens.** `symbol-overlap` substring-matches the corpus, so `User` matches `Username`. Usually fine, occasionally noisy. There's no symbol-boundary check.
- **Repo conflict is monorepo-naive.** A repo with everything under `src/` will see `src` as the top dir for both sides almost always. The conflict simply won't fire — which is the safe failure direction, but it's a real blind spot for monorepos.
- **No per-tenant config wiring.** Custom `ScoringConfig` works programmatically but nothing in `tools.ts` plumbs a tenant-specific config through. Today every user gets `DEFAULT_CONFIG`.
- **No persisted scoring telemetry.** Decisions are returned to the agent and recorded into Details on self-heal, but there's no aggregate "how often does the engine reuse vs create" feedback loop yet, which makes weight tuning more guess-than-measure.
- **Cold corpus scan is O(candidates × corpus_length).** Fine at current library sizes, but the engine isn't indexed. If V2 documents grow to thousands per user, the right answer is the deferred backend `/v2/documents/match` endpoint (see the architecture writeup's open areas), not optimizing this scorer.

## 10. File Map

```
EnderAI/mcp/enderai-api-mcp/src/v2Documents/scoring/
├── index.ts     —  barrel re-exports
├── types.ts     —  SignalName, SignalResult, ScoredCandidate, Decision
├── config.ts    —  DEFAULT_CONFIG (weights, bands, thresholds)
├── engine.ts    —  scoreCongruence(), decide()
└── signals.ts   —  tokenize/jaccard/docCorpus + the 12 default scorers + DEFAULT_SIGNALS
```

Related writeups in this directory:

- [`taskforce-v2-architecture.md`](./taskforce-v2-architecture.md) — full V2 lifecycle (begin/update/finish), self-heal, evidence contract.
- [`taskforce-v2-mcp-document-generation-plan.md`](./taskforce-v2-mcp-document-generation-plan.md) — original design plan; useful as a "what we set out to build" reference.
