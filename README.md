# CCAF Day 1

Coursework and practice projects from the CCAF program, tracking daily exercises with the Claude Agent SDK, MCP, and related tooling.

## Layout

| Path | What it is |
| --- | --- |
| `d17/agent_sdk/` | Agent SDK basics |
| `d18/` | Agent SDK + MCP — a Streamlit demo agent backed by Airtable's hosted MCP server (see `d18/Runbook.txt`) |
| `d19/` | Agent SDK with subagents, reading/writing a Google Sheet |
| `D20/` | Agent SDK + MCP + subagents — a support-ticket workflow (order lookups, refund rules, escalation to a human, webhook handoff). See `D20/cmd.txt` for the full runbook |
| `hooks-practice/` | PreToolUse / PostToolUse hook exercises |
| `caching-batching-assignment/` | Prompt caching and message batching practice (Streamlit apps) |
| `country-intelligence/` | React + Vite app |
| `tech-news-dashboard/` | React + Vite app |
| `personal-finance-tracker/` | Vanilla JS/HTML/CSS app |
| `hello_claude.py`, `first_call.py`, `sdk_call.py`, `raw_http.py`, `conversation.py` | Early standalone scripts calling the Claude API directly |

## Setup

This is a [uv](https://docs.astral.sh/uv/) workspace at the root (`caching-batching-assignment` and `d17/agent_sdk` are workspace members); several day folders (`d18`, `d19`, `D20`) are self-contained uv projects with their own `pyproject.toml`.

```bash
# Root project
uv sync

# A specific day (example: D20)
cd D20
uv sync
```

The Agent SDK days also need the Claude Code CLI:

```bash
npm install -g @anthropic-ai/claude-code
```

React app folders (`country-intelligence`, `tech-news-dashboard`) use npm:

```bash
cd country-intelligence
npm install
npm run dev
```

## Credentials

Each project reads secrets from a local `.env` (never committed — see `.gitignore`). Typical variables:

```
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_SHEET_ID=<sheet id>
SERVICE_ACCOUNT_PATH=<absolute path to the service-account JSON>
ESCALATION_WEBHOOK_URL=<optional, D20 only>
```

Google service-account JSON files (`*service-account*.json`) are gitignored everywhere in the repo and must be supplied locally per project.
