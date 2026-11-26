# Git for Agent Actions

**A transaction layer for ANY AI agent.** The agent proposes; you review one diff; only then does anything run.
If a step fails or the process crashes, everything rolls back exactly. A committed batch can be reverted later.

```
 any MCP client ──MCP stdio──┐                                     ┌─ any MCP server (Calendar, Slack, DB ...)
 any LLM / framework ──HTTP──┤  AgentGit gateway ── engine ────────┤    undo + verify declared in agentgit.json
 (OpenAI, Anthropic, LangChain...)  reads run, writes are STAGED    └─ built-in demo adapters (files, calendar, mail)
                                         │
                       SQLite: batches · actions · tamper-evident audit chain · capsules
                                         │
        Human: dashboard  → risk-scored diff → approve / reject / revert / chaos lab / capsules
```

## Works with any agent (no SDK, no lock-in)
| You use | Connect with |
|---|---|
| Claude Desktop, Cursor, VS Code, any MCP client | `python -m agentgit.gateway` (MCP over stdio) |
| OpenAI / Anthropic / Gemini function calling, LangChain, n8n, scripts | `GET /api/v1/tools?format=openai\|anthropic\|mcp` then `POST /api/v1/call` |
| Any third-party MCP server | list it under `upstreams` in `agentgit.json`; its tools appear as `<name>_<tool>` |

The agent can stage changes but has **no way to approve them**: the MCP gateway has no commit tool, and the HTTP
agent token is rejected (403) on every human endpoint.

## Features
| | |
|---|---|
| Stage and diff | Writes are recorded, never run. One readable diff per batch, with a live preview of what will change. |
| Declared compensation | `undo`, `capture` (before-image), `verify` per tool in config. Deterministic code, never an LLM guess. |
| Effect classes + risk | read / reversible / irreversible, from MCP `readOnlyHint`, name rules and config. Unknown writes are treated as irreversible. Risk score per action and batch. |
| Atomic commit | Saga: any failure undoes earlier steps in reverse. Irreversible steps run last and need explicit confirmation. |
| Verify | After commit, real state is re-read and compared with what was approved. |
| Crash recovery | A half-finished batch is rolled back on the next start. |
| Stale-data check | Refuses to commit if the data changed after staging (when a `snapshot` tool is configured). |
| Policy | `deny` patterns, batch size and delete limits, opt-in autopilot for single low-risk reversible actions. |
| Tamper-evident audit | Every log entry hashes the previous one; the dashboard shows "chain verified". |
| Routine Capsules | Save a verified batch, replay it later with zero LLM calls (a human still approves). |
| Dashboard | KPIs, approval queue, charts, live audit feed, agents, capsules, tools, data, chaos lab. |

## Quick start
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: python -m venv .venv ; .\.venv\Scripts\Activate.ps1
export AGENTGIT_HOME=$PWD/data                          # Windows: $env:AGENTGIT_HOME = "$PWD\data"
python -m agentgit.cli web                              # dashboard: http://127.0.0.1:8765
```
Click **Simulate an agent request**, then **Approve**. Type `5` in the chaos box first to watch an automatic rollback.

## Connect an MCP client (Claude Desktop shown)
```json
{"mcpServers": {"agentgit": {
  "command": "/ABS/PATH/.venv/bin/python", "args": ["-m", "agentgit.gateway"], "cwd": "/ABS/PATH/git-for-agent-actions",
  "env": {"AGENTGIT_HOME": "/ABS/PATH/git-for-agent-actions/data"}}}}
```
Keep `python -m agentgit.cli web` running to approve what the agent stages.

## Wrap another MCP server
Copy `examples/agentgit.example.json` to `$AGENTGIT_HOME/agentgit.json`, set absolute paths, and list your server.
`undo` says which tool reverses a call and how to build its arguments from `{args.x}`, `{result.x}` and `{before.x}`.
Tools with no declared undo are classed irreversible.

## Connect any HTTP agent
```bash
python -m agentgit.cli web --admin-token HUMAN-SECRET --agent-token AGENT-SECRET
AGENTGIT_AGENT_TOKEN=AGENT-SECRET python examples/http_agent.py
```

## Tests and measurements
```bash
python -m unittest discover -s tests -v   # 22 tests: engine, proxy protocol, HTTP roles, audit, capsules, policy
python scripts/chaos.py                   # failure and crash injection at every step, built-in AND third-party MCP server
```

## Honest limits
Tested with a spec-conformant stdio client and a separate MCP server written for the tests, not yet with every real
client. Tools capability only, stdio transport. Undo must be declared per tool; irreversible actions cannot be undone.
Single-user SQLite. The audit chain detects edits and deletions in the middle of the log, not truncation of its end.

## Layout
`agentgit/`: `engine.py` transactions | `adapters.py` built-in + upstream adapters | `gateway.py` MCP proxy |
`server.py` HTTP API | `dashboard.html` UI | `policy.py` config, risk, templates | `mcpwire.py` MCP client | `cli.py`
