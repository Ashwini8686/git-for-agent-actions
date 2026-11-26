# Testing Git for Agent Actions (for friends)

Needs Python 3.9+ and Git. Nothing to pip install.

**Windows (PowerShell), one line at a time:**
```powershell
git clone https://github.com/Ashwini8686/git-for-agent-actions.git
cd git-for-agent-actions
python -m venv .venv
.\.venv\Scripts\Activate.ps1
$env:AGENTGIT_HOME = "$PWD\data"
python -m agentgit.cli web
```
macOS/Linux: `python3 -m venv .venv && source .venv/bin/activate`, `export AGENTGIT_HOME=$PWD/data`, then the same last command.
Open http://127.0.0.1:8765

## 6-step dashboard test
1. Click **Simulate an agent request**. Check the Data tab: nothing changed yet. Note the risk badge.
2. Type **5** in "Chaos lab: fail step" and **Approve**. Expect: rolled back to the exact starting state.
3. Simulate again, leave the box empty, **Approve**. Expect: committed and verified; files and calendar changed.
4. In History click **Revert**. Expect: everything back as before.
5. Simulate again and **Reject**. Expect: no change.
6. Open the Agents, Tools and Capsules tabs. Save a committed batch as a capsule and run it again.

## Automated checks
```bash
python -m unittest discover -s tests -v    # expect 22 tests, OK
python scripts/chaos.py                    # expect gateway clean in every row
python -m agentgit.cli audit               # expect ok: True
```

## Try to break it
- Stage something, edit `data/workspace` by hand, then approve: it must refuse or roll back.
- Kill the terminal while committing, restart: the half-done batch is rolled back.
- Edit a row in `data/agentgit.db` log table by hand: the dashboard chain badge turns red.
- `python -m agentgit.cli stage send_email to=a@b.c subject=Hi`: approving without the irreversible checkbox is refused.
- Use the agent token against `/api/v1/approve`: must return 403.

## Same Wi-Fi hosting
```powershell
python -m agentgit.cli web --host 0.0.0.0 --admin-token PICK-A-PASSWORD --agent-token ANOTHER-ONE
ipconfig     # friends open http://YOUR-IPV4:8765 and use the admin password
```
It refuses to start on the network without an admin token. No HTTPS: trusted Wi-Fi, short sessions only.

## Report bugs
What you did / expected / happened / OS + Python version / last 10 lines of terminal output.
