---
title: Working in the web app
slug: /docs/web-app
order: 5
audience: all
---

# Working in the web app

Your agents write to Taskforce; the web app
([www.taskforce.tools](https://www.taskforce.tools)) is where you and your team
*read, search, curate, and prove* it. Here's what each area is for.

---

## Library — your documents

The Library is the home for everything your agents have captured.

- **Browse & open** any document. Each renders as a **Summary** with expandable,
  anchored **Details** sections — open a section to see the exact evidence behind a
  claim.
- **Folders** organize documents by area, project, or team.
- **Shares** control who can see a document. Sharing into the organization is how a
  document written on your machine becomes your *team's* knowledge.
- **Favorites** keep the documents you reach for often within reach.
- **"Referenced by"** rows on a document show every later session that reused it —
  the visible proof a document is pulling its weight.

Curation matters here: tidy, well-titled, deduplicated documents retrieve better.
A document with honest open questions and a clear outcome is worth more to the next
person than a sprawling transcript.

---

## Search — ask your knowledge

Search is a chat interface over everything Taskforce has captured. Ask a question in
natural language and get an answer **with citations** back to the source documents
and anchors — so you can verify any claim, not just trust it.

**BYOK (bring your own key):** you can point Search at your own model provider key.
The setup lives in Search; once configured, your queries run against your key.

Use Search when you want the answer without opening a coding agent — "how did we
handle webhook retries?", "what did we decide about JWT refresh?", "has anyone hit
this error before?"

---

## Agents / Profiles — reusable operating context

The **Agents** area is where profiles live. A profile detail page shows:

- The profile's operating context and **routing triggers** (what kinds of requests
  it gets brought in for).
- **Invocations** — when this profile was matched into a session and by whom.
- **Linked knowledge** — the documents this profile carries with it.

Remember: a profile is portable operating context that any tool/model can adopt, not
an autonomous worker. It's "how we do X here," made reusable across harnesses and
people.

---

## Metrics & Ledger — the proof

The **Metrics** page shows what reuse has been worth — tokens and dollars saved,
where the savings came from, and the measured-vs-estimated split. The **Ledger** is
the event-level view: individual reuse events with provenance, exportable. There's a
**Methodology** page that spells out exactly how every number is computed.

This area gets its own page: **[Metrics & the ROI ledger](06-metrics-and-ledger.md)**.

---

## Settings — credentials & connection

**Settings → Connect Agent** is where you create and rotate the MCP tokens your
agents use, see when each was last used, and copy the setup snippets (covered in the
[Quickstart](01-quickstart.md)). Rotate a credential any time; old tokens stop
working immediately.

Next: **[Metrics & the ROI ledger →](06-metrics-and-ledger.md)**
