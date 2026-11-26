"""MCP gateway. The agent connects here. Reads run; writes are only STAGED.

There is deliberately no commit tool: only a human can approve (CLI or web page).
Run:  python -m agentgit.mcp_server      (stdio transport)
Never print() to stdout in this file: stdout carries the MCP protocol.
"""
from mcp.server.fastmcp import FastMCP

from .engine import make_engine

mcp = FastMCP("git-for-agent-actions")


def _stage(tool, args):
    eng = make_engine()
    try:
        r = eng.stage(tool, args)
    except Exception as e:
        return f"ERROR: {e}"
    finally:
        eng.close()
    if r["effect"] == "read":
        return r["result"]
    return (f"STAGED, NOT EXECUTED (batch #{r['batch']}, step {r['seq']}): {r['description']}. "
            "Nothing has changed yet. The user must review and approve the batch in the AgentGit diff page.")


@mcp.tool()
def list_files(folder: str = ".") -> str:
    """List files in a workspace folder."""
    return _stage("list_files", {"folder": folder})


@mcp.tool()
def move_file(src: str, dst: str) -> str:
    """Move a file (staged until the user approves). dst may be a folder like 'Study/'."""
    return _stage("move_file", {"src": src, "dst": dst})


@mcp.tool()
def delete_file(path: str) -> str:
    """Delete a file (staged; kept in a trash folder so it can be restored)."""
    return _stage("delete_file", {"path": path})


@mcp.tool()
def list_events() -> str:
    """List calendar events with their ids."""
    return _stage("list_events", {})


@mcp.tool()
def add_event(title: str, start: str, end: str = "") -> str:
    """Add a calendar event (staged). start/end look like 2026-12-10T10:00."""
    return _stage("add_event", {"title": title, "start": start, "end": end})


@mcp.tool()
def delete_event(event_id: str) -> str:
    """Delete a calendar event by id (staged)."""
    return _stage("delete_event", {"event_id": event_id})


@mcp.tool()
def send_email(to: str, subject: str, body: str = "") -> str:
    """Send an email. Irreversible, so it is held and needs separate explicit confirmation."""
    return _stage("send_email", {"to": to, "subject": subject, "body": body})


@mcp.tool()
def preview_changes() -> str:
    """Show the pending diff (read-only)."""
    eng = make_engine()
    try:
        return eng.diff()
    finally:
        eng.close()


if __name__ == "__main__":
    mcp.run()
