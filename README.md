# Taskforce

**Mission control for your AI coding agents.**

Your team runs AI agents in Claude Code, Codex and Cursor. Taskforce puts them all in one place, lets you steer them, and keeps what they learn so the next agent starts ahead.

### See every agent your team is running

![The Sessions page: every agent, grouped by project, with what it's doing right now](docs/media/taskforce-sessions.png)

### Send a waiting agent a message

It picks up your note on its next step.

![An idle Codex agent with a message queued for it](docs/media/taskforce-steer.png)

### Keep what agents learn

Fixes become short notes the whole team can search, so the next agent, in any tool, starts from there.

![A team note written in Claude Code and reused in Codex](docs/media/taskforce-library.png)

<sub>Screenshots show sample data.</sub>

---

**Try it:** [taskforce.tools](https://www.taskforce.tools) · [Quickstart](docs/user-guide/01-quickstart.md) · [User guide](docs/user-guide/README.md)

**This repo** is the backend: the API (`demo/full-stack-fastapi-template/backend`), the hosted MCP server (`mcp/`), the agent hooks for Claude Code, Codex and Cursor (`scripts/`), and the product docs (`docs/`). The web app lives in [EnderAI-frontend](https://github.com/al-exe/EnderAI-frontend).
