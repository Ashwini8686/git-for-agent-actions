"""ANY agent, ANY framework: this tiny agent talks to AgentGit over plain HTTP.

Replace decide() with a call to your LLM (OpenAI, Anthropic, Gemini, a local model, LangChain...).
Fetch tool schemas in the format your LLM wants:  GET /api/v1/tools?format=openai | anthropic | mcp
Then send each tool call the LLM makes to:        POST /api/v1/call {"agent": "...", "tool": "...", "args": {...}}
The agent token can stage changes but can never approve them.
"""
import json
import os
import urllib.request

BASE = os.environ.get("AGENTGIT_URL", "http://127.0.0.1:8765")
TOKEN = os.environ.get("AGENTGIT_AGENT_TOKEN", "")


def api(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None)
    if TOKEN:
        req.add_header("Authorization", "Bearer " + TOKEN)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def decide(tools):
    """Stand-in for an LLM choosing tool calls from the schemas it was given."""
    return [("list_events", {}),
            ("add_event", {"title": "Maths exam", "start": "2026-12-10T10:00"}),
            ("delete_event", {"event_id": "ev_study1"}),
            ("move_file", {"src": "maths_notes.pdf", "dst": "Study/"})]


if __name__ == "__main__":
    tools = api("GET", "/api/v1/tools?format=openai")
    print(f"Fetched {len(tools)} tool schemas in OpenAI function-calling format.")
    for tool, args in decide(tools):
        r = api("POST", "/api/v1/call", {"agent": "my-http-agent", "tool": tool, "args": args})
        print(f"{tool}: {r['message']}")
    print("\nNow open the dashboard and approve or reject the batch.")
