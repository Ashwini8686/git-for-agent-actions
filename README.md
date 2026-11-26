# Git for Agent Actions

An MCP gateway that lets an AI agent **propose** changes, shows you one diff, and only runs them after
**you** approve. If any step fails, everything is rolled back exactly. A committed batch can be reverted later.

```
AI agent (MCP client) -> [ gateway: reads run, writes are STAGED ] -> SQLite (batches, actions, log)
                                                                              |
Human: CLI or web page  -> diff -> approve -> commit (saga, idempotent) -> verify -> revert
                                                |
                                  adapters: files, calendar, mail (undo = exact coded inverse)
```

## What is built and tested
| Feature | How it works |
|---|---|
| Stage and diff | Write tools only record the action. Real data is untouched until approval. |
| Effect classes | `read` runs now, `reversible` is staged with an undo, `irreversible` (email) needs explicit confirmation and runs last. Unknown tools count as irreversible. |
| Atomic commit | Actions run in order. On any failure the earlier ones are undone in reverse order (saga). |
| Deterministic undo | Each adapter returns an exact undo record when it applies a change. No LLM is involved. |
| Verify | After commit, real state is re-read and compared with what was approved. A mismatch triggers rollback. |
| Idempotency | Each action has a unique key and a batch can only be committed once. |
| Crash recovery | A batch left half-committed is rolled back automatically on the next start. |
| Stale-diff check | If data changed after staging, the commit is refused. |
| Revert | One command or button undoes a whole committed batch. |
| Audit log | Every stage, commit, rollback and revert is recorded in SQLite. |

Not built yet: a Google Calendar adapter (the calendar here is a local JSON file with the same interface),
and proxying to other MCP servers. Both fit the adapter interface in `agentgit/adapters.py`.

## Setup (step by step)
```bash
git clone https://github.com/Ashwini8686/git-for-agent-actions.git
cd git-for-agent-actions
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt      # only needed for the MCP gateway
export AGENTGIT_HOME=$PWD/data       # Windows PowerShell: $env:AGENTGIT_HOME="$PWD\data"
```

## Try it without any AI (CLI)
```bash
python -m agentgit.cli seed          # fake files and calendar
python -m agentgit.cli demo          # stage the 7-step example workflow
python -m agentgit.cli diff          # nothing has changed yet
python -m agentgit.cli commit --fail-at 5   # pull the plug at step 5 -> automatic rollback
python -m agentgit.cli state         # identical to the start
python -m agentgit.cli demo && python -m agentgit.cli commit   # now a real commit
python -m agentgit.cli history
python -m agentgit.cli revert 2      # undo the whole batch
python -m agentgit.cli web           # approval page at http://127.0.0.1:8765
```

## Tests and the numbers for your pitch
```bash
python -m unittest discover -s tests -v   # 10 tests
python scripts/chaos.py                   # failure and crash injection at every step
```
Measured on the 7-action workflow: a plain agent recovered cleanly in 1 of 7 runs (step 1 is trivial),
the gateway in 7 of 7 injected errors and 7 of 7 injected crashes. Re-run it yourself and quote your own output.

## Connect an AI agent (MCP, stdio)
Add to your MCP client's server config (for Claude Desktop this is `claude_desktop_config.json`):
```json
{"mcpServers": {"git-for-agent-actions": {
  "command": "/ABSOLUTE/PATH/.venv/bin/python",
  "args": ["-m", "agentgit.mcp_server"],
  "cwd": "/ABSOLUTE/PATH/git-for-agent-actions",
  "env": {"AGENTGIT_HOME": "/ABSOLUTE/PATH/git-for-agent-actions/data"}}}}
```
Restart the client, then ask: *"Move maths_notes.pdf to Study/ and add a Maths exam on 2026-12-10T10:00."*
The agent replies that the changes are staged. Open the web page or run `diff`, then approve.
There is no commit tool on purpose, so the agent cannot approve its own changes.
Debug the server with `mcp dev agentgit/mcp_server.py`.

## Layout
`agentgit/engine.py` transactions | `adapters.py` files, calendar, mail | `db.py` SQLite | `mcp_server.py` gateway |
`cli.py` | `webui.py` approval page | `seed.py` demo data | `tests/` | `scripts/chaos.py`
