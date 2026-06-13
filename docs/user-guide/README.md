# Taskforce User Guide — source content

First-user documentation, written to be **served on the frontend**
([www.taskforce.tools](https://www.taskforce.tools)). This directory is the
content source of truth; the rendering/design layer is built separately.

## For the design / frontend implementer

Each page is a standalone Markdown file with YAML frontmatter that drives
navigation:

```yaml
---
title: Quickstart — Connect your agent   # nav + page heading
slug: /docs/quickstart                    # intended public route
order: 1                                   # sidebar ordering
audience: developer | champion | all       # for optional audience filtering/badges
---
```

- Read order is the numeric filename prefix (`00`–`09`), which matches `order`.
- Internal links are relative `*.md` references (e.g. `01-quickstart.md`); rewrite
  these to the `slug` routes when rendering.
- Content is GitHub-flavored Markdown: headings, tables, fenced code blocks, and a
  couple of ASCII diagrams. No custom MDX components are required to render it, but
  code-block syntax highlighting and table styling will help.

## Pages

| # | Page | Audience |
|---|---|---|
| 00 | Index / landing | all |
| 01 | Quickstart — connect your agent | developer |
| 02 | How Taskforce works | all |
| 03 | The document workflow | developer |
| 04 | The `/tf` flow (Claude Code) | developer |
| 05 | Working in the web app | all |
| 06 | Metrics & the ROI ledger | champion |
| 07 | Rolling out to your team | champion |
| 08 | Best practices | all |
| 09 | FAQ & troubleshooting | all |

The set is layered: a developer can get value from 01–05 alone; 06–07 are the
champion/rollout track.
