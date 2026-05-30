# Codex + Taskforce MCP Brainstorm

Date: 2026-05-21

## Short Version

The better agent flow should separate "look for useful prior work" from
"create or mutate a durable work document."

Today, `enderai_begin_document` is doing both jobs: it searches for related
documents, then either reuses one or creates a new one. That is convenient, but
it causes two product problems:

1. It can create documents too early, before we know whether the user request
   turned into meaningful work.
2. The metrics story is muddy because "a document was created" and "Taskforce
   saved the agent discovery effort" are not the same event.

The ideal Taskforce MCP flow should be:

1. User asks for something.
2. Agent runs a lightweight Taskforce lookup first.
3. If related work exists, Taskforce returns a compact context bundle with
   document IDs, summaries, matching reasons, and evidence anchors.
4. The agent uses that context directly.
5. If the agent performs material work, it updates the matched document or
   creates a new document lazily.
6. Metrics credit savings only when existing context was actually returned and
   used, using a naive but explainable "avoided discovery" estimate.

In other words: lookup is cheap and non-mutating; document writes happen only
when the agent has something worth preserving.

## Product Goal

Taskforce should feel like the agent's memory layer, not another issue tracker
the agent has to remember to maintain.

A normal Codex session should look like this:

```text
User request
  -> Taskforce lookup
      -> related context found?
          yes: hydrate agent with compact context
          no: continue cold, no document yet
  -> agent investigates / edits / answers
      -> material new information?
          yes: update existing doc or create new doc
          no: do not write
  -> finish/pause if durable work happened
```

The important behavioral shift: the agent should not have to decide at the
very beginning whether this request deserves a new durable document. It only
needs to ask, "Is there prior work I should know about?"

## Current Shape

The current V2 document MCP workflow already has strong building blocks:

- `enderai_begin_document` lists documents, scores candidates, self-heals a
  reused doc, or creates a fresh one.
- `enderai_update_document` appends progress, commands, files, decisions,
  changes, and Summary claims backed by Details anchors.
- `enderai_finish_document` records the outcome and clears the active pointer.
- The scoring engine is deterministic and explainable.
- Metrics already records document events, token consumption, cache savings,
  summary-only savings, and reuse savings.

The gap is not that the primitives are wrong. The gap is that "begin" is too
heavy for a universal first step. For every user request, we want lookup. We do
not always want document creation.

## Proposed Tool Model

When the rename happens, I would make the Taskforce V2 MCP surface look like
this:

```text
taskforce_lookup_context
taskforce_begin_work
taskforce_update_document
taskforce_finish_document
```

The existing `enderai_*` tools can remain as aliases during migration.

### `taskforce_lookup_context`

Non-mutating. This is the tool Codex should call at the start of meaningful or
potentially meaningful work.

Inputs:

- `request_summary`
- `goal`
- `files`
- `symbols`
- `errors`
- `contexts`
- `collaborators`
- `max_candidates`
- `reuse_within_seconds`
- `intent`: `answer | investigate | edit | review | merge | deploy | unknown`

Outputs:

- `lookup_id`: durable ID for metrics and follow-up.
- `match_confidence`: `none | low | medium | high | explicit`
- `recommended_action`: `use_existing | start_fresh | ask_human | no_context`
- `context_bundle`: compact, agent-ready context.
- `candidate_summaries`: ranked candidates with reasons and conflicts.
- `matched_anchor_ids`: evidence anchors that explain why the bundle was
  selected.
- `savings_basis`: machine-readable values used by metrics.

This tool should never create a document. It can record a `context.lookup`
metrics event, but that event should not imply useful context was found.

### `taskforce_begin_work`

Mutating only when the agent is about to do material work.

Inputs:

- `lookup_id`, if one exists.
- `document_id`, if reusing.
- `force_new`, if the agent or user wants a fresh document.
- `request_summary`
- `goal`
- initial details.

Behavior:

- If lookup found a high/medium match and the agent chooses it, set that as the
  active document.
- If lookup found no match, create a new document only now.
- If the user asks a quick question and no work happens, this tool is never
  called.

This solves the "documents created for tiny requests" problem.

### `taskforce_update_document`

Mostly the current `enderai_update_document`, but with two additions:

- `used_context_anchor_ids`: anchors from lookup that the agent actually relied
  on.
- `new_information`: boolean or enum: `none | minor | material`.

This lets metrics distinguish "Taskforce returned context" from "the agent used
that context to avoid work."

### `taskforce_finish_document`

Mostly the current `enderai_finish_document`, but it should optionally accept
the `lookup_id` and final `used_context_anchor_ids` if the agent did not update
midstream.

## Context Bundle Shape

The context returned to the agent should be optimized for action, not for full
document fidelity.

Suggested shape:

```json
{
  "lookup_id": "ctx_...",
  "match_confidence": "high",
  "primary_document": {
    "document_id": "doc_...",
    "title": "Stripe checkout wiring",
    "summary": ["..."],
    "why_this_matches": ["price env var overlap", "billing route overlap"],
    "anchors": [
      {
        "anchor_id": "checkout-wiring",
        "heading": "Checkout Wiring",
        "summary": "Backend checkout resolves pro/max to env price IDs.",
        "excerpt": "short excerpt or generated compact summary",
        "files": ["app/api/routes/billing.py"],
        "symbols": ["create_checkout_session"]
      }
    ]
  },
  "related_documents": [
    {
      "document_id": "doc_...",
      "title": "...",
      "reason": "same files, lower recency",
      "confidence": "medium"
    }
  ],
  "savings_basis": {
    "returned_context_tokens": 900,
    "matched_files": 3,
    "matched_symbols": 2,
    "matched_errors": 0,
    "matched_decisions": 2,
    "confidence_multiplier": 2.0
  }
}
```

The agent should not need to read the whole document by default. The bundle
should return Summary plus only the Details anchors that matched the request.

Full Details should be an explicit follow-up:

```text
taskforce_expand_context(lookup_id, anchor_ids)
```

That keeps context small and makes savings more defensible: Taskforce saved
time by returning the exact subset of old work that mattered.

## Document Creation Policy

I would use a lazy creation policy:

| Situation | Lookup? | Create doc? | Update doc? |
|---|---:|---:|---:|
| User asks a trivial fact/question | optional | no | no |
| User asks about prior work and answer is found | yes | no | maybe record context use only |
| User asks for code change, no match exists | yes | yes, at first material edit/update | yes |
| User asks for code change, match exists | yes | no | update matched doc |
| User asks for review, findings only | yes | create/update if findings are material | yes |
| User asks to merge/deploy | yes | update existing work doc if one matches | yes |

The MCP should make this easy for the agent:

- `lookup_context` is always safe.
- `begin_work` is only for material work.
- `update_document` rejects empty updates.
- `finish_document` only runs if a document is active.

## Agent Instruction Contract

Codex should receive a simpler instruction than today's "begin a document for
meaningful work."

Suggested wording:

> Before investigating, editing, reviewing, merging, or answering a question
> that might depend on prior project state, call `taskforce_lookup_context`.
> Use returned context before searching from scratch. Do not create a new
> Taskforce document until you perform material work or learn durable
> information worth preserving. If related context was used, pass
> `used_context_anchor_ids` when updating or finishing.

This matches the actual desired behavior:

- always look first when it might help;
- create only after work exists;
- cite what was actually useful.

## Savings Metrics

The metric we want is not "tokens in the reused document." It is:

```text
tokens avoided by not having to rediscover the information Taskforce returned
```

That needs to be intentionally naive at first. The key is to make it stable,
explainable, and hard to inflate accidentally.

### Proposed Metrics Events

Add or clarify these events:

- `context.lookup`: lookup happened.
- `context.hit`: lookup returned at least one medium/high candidate.
- `context.used`: agent reported that returned anchors informed the work.
- `tokens.saved.discovery`: estimated tokens avoided by context reuse.

Keep the existing:

- `document.created`
- `document.updated`
- `document.reused`
- `document.finished`
- `tokens.consumed`
- `tokens.saved.cache`
- `tokens.saved.summary_only`
- `tokens.saved.reuse`

Over time, `tokens.saved.reuse` can either be folded into
`tokens.saved.discovery` or kept as the old coarse metric. I would make the new
metric the product-facing one.

### MVP Formula

For the first version, calculate discovery savings only when all are true:

1. Lookup returned a medium/high/explicit match.
2. The agent received a context bundle.
3. The agent later reported `used_context_anchor_ids`, or answered directly
   from the bundle with `view_consulted = "summary"` or `context`.

Formula:

```text
base_discovery_tokens =
  800
  + 350 * matched_files
  + 250 * matched_symbols
  + 900 * matched_errors
  + 500 * matched_decisions
  + 300 * matched_commands
  + returned_context_tokens

confidence_multiplier =
  explicit: 2.0
  high:     1.75
  medium:   1.25
  low:      0
  none:     0

gross_saved_tokens =
  base_discovery_tokens * confidence_multiplier

net_saved_tokens =
  gross_saved_tokens - taskforce_lookup_overhead_tokens

tokens_saved.discovery =
  clamp(round(net_saved_tokens), 0, 20000)
```

Why this is better than the current `summary_tokens + details_tokens` reuse
estimate:

- It credits the evidence that actually matched the request.
- It credits concrete avoided work: files, symbols, errors, decisions,
  commands.
- It subtracts lookup overhead.
- It gives zero credit for low/no match.
- It caps the estimate so one giant document cannot produce absurd savings.

The exact constants are not sacred. They just need to be visible in the code
and in the metrics methodology doc.

### Even Simpler Formula

If we want something very easy to ship:

```text
gross_saved_tokens =
  min(20000, returned_context_tokens * multiplier)

multiplier =
  explicit: 4
  high:     3
  medium:   2
  low:      0

net_saved_tokens =
  max(0, gross_saved_tokens - lookup_overhead_tokens)
```

This says: "The agent would have spent roughly 2-4x the returned context size
finding and validating the same information from scratch."

It is less rich, but much easier to defend than a complicated half-parsed
markdown model.

### Better Formula Later

Later, once documents have more structured Details metadata, use evidence
atoms:

```text
saved =
  repo_orientation_cost
  + sum(file_evidence.file_read_cost)
  + sum(command_evidence.command_cost)
  + sum(decision_evidence.reconstruction_cost)
  + sum(error_evidence.reproduction_cost)
  - lookup_overhead
```

Where:

- file read cost can use cached token counts for referenced file excerpts;
- command cost can use a fixed value by command type;
- error reproduction cost can be higher because reproducing a failure is
  expensive;
- decisions get meaningful credit because recovering why a choice was made is
  often harder than finding the final diff.

## Avoiding Bad Metrics

Savings metrics will get distrusted fast if they look inflated. I would add
these guardrails:

- No savings for document creation.
- No discovery savings for low confidence matches.
- No discovery savings unless context was returned to the agent.
- Prefer no savings unless the agent reports `used_context_anchor_ids`.
- Subtract lookup overhead.
- Cap per lookup.
- Store the full calculation basis in `metrics_event.payload`.
- Show the formula in the Metrics methodology panel.
- Split "measured savings" from "estimated savings" in the UI.

Useful UI labels:

- "Cache savings" - measured from provider cache tokens.
- "Summary savings" - estimated from reading Summary instead of Details.
- "Discovery savings" - estimated avoided rediscovery from reused Taskforce
  context.

Do not blend these silently. They answer different questions.

## Lookup And Matching Improvements

The current deterministic scoring engine is a good start. I would extend it
rather than replacing it with an LLM.

Near-term improvements:

- Move matching to the backend when the document list grows large.
- Return matched anchor snippets, not just document-level scores.
- Add a first-class `status` column so terminal-state conflicts do not depend
  on parsing Outcome markdown.
- Track `last_activity_kind`: `investigation`, `implementation`, `review`,
  `merge`, `deployment`, `incident`.
- Add `source_refs` on Details sections: files, PRs, issues, commands, URLs,
  symbols.
- Add `evidence_kind` on Details sections: `decision`, `command`, `change`,
  `error`, `validation`, `open_question`, `outcome`.

The biggest product improvement would be anchor-level matching. A document can
be broadly relevant while only one Details section matters. Returning the exact
section is what makes the agent feel like it "remembered" instead of "searched."

## When To Update Documents

Agents should update documents only when there is durable value:

Update when:

- files changed;
- tests or commands produced a meaningful result;
- a decision was made;
- an assumption was confirmed or rejected;
- the agent found a root cause;
- a PR/merge/deploy happened;
- a human gave a new constraint;
- a blocker or follow-up remains.

Do not update when:

- the agent only answered a generic question;
- lookup found nothing and no work happened;
- the agent repeated information already in the document;
- the only event is a failed exploratory command with no durable conclusion.

This keeps the library from becoming an activity log.

## Suggested Implementation Plan

### Phase 1: Non-mutating Lookup

- Add `taskforce_lookup_context` as a new MCP tool.
- Reuse the current scoring engine.
- Return compact context bundles and candidate summaries.
- Record `context.lookup`, `context.hit`, and lookup overhead tokens if usage
  is available.
- Keep existing `enderai_begin_document` behavior for compatibility.

### Phase 2: Lazy Work Sessions

- Add `taskforce_begin_work`.
- Allow it to accept `lookup_id`.
- If no document exists and material work starts, create the document then.
- If a match exists, set active document without forcing a self-heal unless a
  patch is actually needed.

### Phase 3: Context Use Attribution

- Add `used_context_anchor_ids` to update/finish.
- Add `context.used` and `tokens.saved.discovery`.
- Store the calculation basis in payload.
- Display "Discovery savings" separately from cache and summary savings.

### Phase 4: Anchor-Level Retrieval

- Add source refs and evidence kinds to Details sections.
- Return anchor snippets and compact summaries from lookup.
- Add `taskforce_expand_context` for explicit drill-down.

### Phase 5: Harness Integration

- Make Codex/Claude wrappers call lookup automatically before meaningful work
  where possible.
- Have the harness, not the model, supply actual token usage.
- Let the model supply semantic metadata: files, symbols, errors, and
  used anchors.

## Open Questions

- Should answering from an existing document create a new event even when no
  document is updated? I think yes: `context.used` is a metrics event, not a
  document mutation.
- Should medium-confidence matches be auto-used or require agent judgement? I
  would auto-return the context but make the confidence visible.
- Should low-confidence candidates be returned at all? Probably yes, but in a
  "possible related work" section with zero savings credit.
- Should "Admin"/internal-only information ever appear in public context
  bundles? No. Lookup should respect the same visibility and sanitization rules
  as document reads.
- Should lookup be mandatory for every prompt? No. It should be mandatory for
  meaningful work and optional for tiny chat.

## Concrete Codex Behavior

For Codex specifically, the practical rule should be:

1. Before code changes, PR work, reviews, debugging, deployment, or project
   planning, call `taskforce_lookup_context`.
2. Read the returned context bundle before running broad searches.
3. If the bundle answered the question, cite the used anchors and stop.
4. If work happens, call `taskforce_begin_work` with the lookup ID.
5. Update only with material findings.
6. Finish when the work is done or paused.

That gives Taskforce the data it needs without making the agent spend ceremony
on requests that do not become durable work.

## Naming After Rebrand

Use `taskforce_*` names in docs and UI, but keep `enderai_*` aliases until all
clients migrate.

Suggested final names:

- `taskforce_lookup_context`
- `taskforce_begin_work`
- `taskforce_update_document`
- `taskforce_finish_document`
- `taskforce_expand_context`
- `taskforce_session_info`

The product concept should be "Taskforce context" and "Taskforce documents."
The implementation can keep old EnderAI names internally until the rebrand is
complete.

## Recommendation

Build `taskforce_lookup_context` first.

It is the smallest change that improves the whole product loop:

- agents can look before they leap;
- no unnecessary document creation;
- context reuse becomes explicit;
- savings can be tied to returned evidence;
- the current begin/update/finish tools keep working.

After that, add lazy `begin_work` and discovery-savings attribution. The big
win is not a more complicated document model. The big win is separating
context retrieval from document mutation.
