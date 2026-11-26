# AgentGit manual

## Start
1. Double-click `start.bat` and keep the black window open.
2. Open http://127.0.0.1:8765 (it opens by itself).
3. Stop with Ctrl+C in that window (answer Y if asked).

## The screens (left icons, top to bottom)
| Icon | Screen | What you do there |
|---|---|---|
| Grid | Overview | Four big numbers, pending changes, recent batches, alerts, latest activity |
| Shield | Approvals | Read the diff. **Commit** (violet) runs it and verifies it. **Reject** discards it. Chaos lab: type a step number to force a failure and watch the automatic rollback |
| Clock | History | Vertical timeline of every batch. **Roll back** (red) asks you to confirm, then undoes the batch. **Save as capsule** keeps it as a repeatable routine |
| Network | Connections | One card per provider (Claude, ChatGPT/OpenAI, MCP clients, custom). Shows the URLs an agent uses and its real counts |
| Pill | Capsules | Replay a saved routine. It still waits for your approval |
| Wrench | Tools | Every tool agents may call, with effect and risk |
| Database | Demo data | The sample files and calendar the demo changes |

## Try it in two minutes
1. Approvals -> **Simulate an agent request**.
2. Type `5` in the Chaos lab box and press Commit. Everything rolls back.
3. Simulate again, leave the box empty, Commit. Open History and press **Roll back**, then confirm.

## Floating panel
Press **Pop out panel** (top right). In Chrome or Edge it opens as a small window that stays on top of other apps; in other browsers it opens as a normal small window. Type a request and press Enter. It is only staged; press **Commit** in the panel to run it. Understood phrases:
- `move maths_notes.pdf to Study/`
- `delete file todo.txt`
- `add event Maths exam at 2026-12-10 10:00`
- `delete event ev_gym`

The panel does not use an AI model. It understands only these phrases. Real AI agents connect through the Connections screen.

## Connect an agent
Give the agent the tool list from `/api/v1/tools?format=anthropic` (Claude), `format=openai` (ChatGPT/OpenAI) or `format=mcp`, and send its calls to `POST /api/v1/call`. Include `"agent": "claude-yourname"` in the body so it shows on the right provider card.

## Problems
Run `python -m agentgit.cli doctor` and paste the output.

## Put it on GitHub
From the project folder (Command Prompt):
```
tar -xf "%USERPROFILE%\Downloads\agentgit-panel.zip" -C "C:\Users\KSEEB\Documents\git-for-agent-actions"
python -m unittest discover -s tests
start.bat
```
If the tests end in OK and the dashboard looks right, press Ctrl+C, then:
```
git add -A
git commit -m "New dark glass dashboard, floating panel, connections and ask endpoints"
git push
```
Friends can then run `git clone <your repo URL>`, open the folder and double-click `start.bat` (they need Python and Git).
