> ⚠️ **ARCHIVED 2026-06-21 — historical; NOT current product direction.**
> Superseded by [`../../taskforce-northstar.md`](../../taskforce-northstar.md). Retained for reference only. Future agents: do not treat this as current guidance.

# EnderAI Harness Product Thesis

Date: 2026-04-27

## North Star

EnderAI is not the agent.

EnderAI is the harness that makes agents operational.

The product should turn the rudimentary AI engineering workflow teams have today into a low-touch autonomous engineering system: agents running in the background, carrying context forward, auditing their own work, and escalating to humans only when judgment or control is needed.

Short positioning:

> EnderAI transforms engineering teams into autonomous software factories, with humans overseeing the work instead of driving every step.

More precise positioning:

> EnderAI is the operational harness layer for autonomous engineering teams.

## Problem

Most AI-assisted engineering work is still chat-bound and human-orchestrated.

The typical workflow is:

- a human remembers the background
- a human writes the prompt
- a human pastes context
- the agent works in a single session
- the session ends
- useful lessons disappear unless manually documented
- the next agent starts cold

This does not scale to autonomous engineering. It creates fragile productivity instead of durable throughput.

Teams do not only need stronger agents. They need scaffolding around agents:

- durable memory
- context retrieval
- work queues
- permissions
- policy gates
- audit trails
- recovery loops
- self-review
- escalation
- human override

That scaffolding is the product.

## Product Promise

EnderAI should make autonomous engineering feel controlled rather than chaotic.

The system should let agents work continuously while giving humans enough handholds to trust, inspect, pause, steer, approve, reject, or take over.

EnderAI should answer:

- What is the agent working on?
- What context did it start with?
- Why was that context selected?
- What has it tried?
- What failed?
- What changed?
- What evidence supports the current conclusion?
- What should the next agent know?
- When does a human need to step in?

## Core Pillars

### 1. Harness

The harness is the scaffolding around the agent.

It should provide:

- work queues
- run policies
- repo and tool permissions
- approval gates
- escalation rules
- pause/resume controls
- failure handling
- retries
- handoff between agents

The user should not have to babysit a chat session. The user should configure the operating boundary and let the system run.

### 2. Context

Context Packs are the core artifact of EnderAI's memory system.

A Context Pack should become a cited operational briefing, not just a snapshot of fields.

It should tell the agent and the human:

- relevant prior cases
- current known constraints
- important files and symbols
- prior supported hypotheses
- prior failed approaches
- known risks
- open questions
- freshness status
- confidence
- why this context was selected
- what evidence supports it

The Context Pack is how EnderAI raises historical data into usable future context.

### 3. Autonomy

EnderAI should enable agents to:

- start work from a queue
- hydrate themselves with the right Context Pack
- investigate
- run commands
- update the Case
- self-review
- respond to CI failures
- open or update pull requests
- continue after interruption
- hand off work to another agent

Autonomy should be low-touch, not uncontrolled.

### 4. Audit

Every agent run should produce a durable audit trail.

The audit trail should capture:

- prompt or trigger
- selected Context Pack
- commands run
- files touched
- tool calls
- test output
- hypotheses
- decisions
- failures
- retries
- human interventions
- final outcome

Audit is not a compliance afterthought. It is how the system learns and how humans trust it.

### 5. Human Control

The system should expose explicit handholds:

- pause
- resume
- steer
- approve
- reject
- assign
- escalate
- kill
- replay
- promote a lesson into durable memory
- mark context stale

The right UX is not "fully hands off no matter what." The right UX is autonomous by default with clear control points.

### 6. Learning Loop

EnderAI should continuously shape raw work history into higher-quality memory.

The loop:

1. capture work as Cases and Events
2. synthesize Topic rollups
3. build Context Packs
4. use Context Packs in future runs
5. audit results
6. promote durable lessons
7. mark stale or contradicted knowledge
8. improve the next Context Pack

This is the compounding advantage.

## Current Model Mapping

The existing domain model already points in the right direction.

- Topic: durable workstream, system area, or recurring engineering concern.
- Case: one bounded run, investigation, implementation, or agent session.
- Case Event: append-only operational audit trail.
- Topic Rollup: accumulated workstream memory.
- Context Pack: generated briefing that carries prior knowledge into the next run.

The next product step is to make this model feel like a harness instead of a tracker.

## Product Surface Implications

EnderAI's future UI should emphasize operations, not record browsing.

Important surfaces:

- Agent work queue
- Active runs
- Case timeline
- Context Pack briefing
- Self-audit results
- Human intervention queue
- Topic memory health
- Stale knowledge warnings
- ROI and throughput dashboard

The user should be able to inspect records, but the primary experience should answer: "What is the machine doing, what does it know, and where do I need to intervene?"

## Context Pack Evolution

Context Pack should evolve from snapshot to product artifact.

Context Pack v2 should include:

- stable ID
- version
- source Topic
- source Case or run
- builder version
- created time
- refreshed time
- expiry or stale time
- selected evidence
- omitted evidence
- citations
- freshness checks
- confidence
- why-selected reasoning
- risk notes
- known failed approaches
- next suggested actions
- usage history

The pack should be readable by humans and directly useful to agents.

## Non-Goals

EnderAI should not become:

- a generic notes app
- a generic AI chat app
- a passive task tracker
- a memory viewer with no operational loop
- a single-agent client
- a replacement for GitHub, CI, or issue trackers

EnderAI should integrate with those systems and make them legible to agents.

## Maturity Model

### Level 0: Manual AI Workflow

Humans paste context into agent chats and manually track outcomes.

### Level 1: Captured Workflow

Agent work is recorded as Cases and Events.

### Level 2: Synthesized Workflow

Topic rollups and Context Packs summarize prior work.

### Level 3: Guided Workflow

Agents begin runs with Context Packs, update Cases, and preserve useful discoveries.

### Level 4: Autonomous Workflow

Agents pull work from queues, self-audit, respond to failures, and escalate only when needed.

### Level 5: Compounding Workflow

The system continuously improves its own context quality, detects stale knowledge, and produces measurable throughput gains.

EnderAI is currently between Level 1 and Level 2. The product direction should push toward Level 4 while keeping Level 5 bounded by human policy and review.
