"""Self-check: python -m agentgit.cli doctor. Says what is wrong and how to fix it."""
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

NEEDED = ["adapters.py", "cli.py", "dashboard.html", "db.py", "engine.py", "gateway.py", "mcpwire.py",
          "policy.py", "seed.py", "server.py"]


def check_python():
    v = sys.version_info
    if v < (3, 9):
        raise RuntimeError(f"Python {v.major}.{v.minor} is too old; install 3.9 or newer")
    return f"{v.major}.{v.minor}.{v.micro}"


def check_files():
    here = Path(__file__).parent
    missing = [n for n in NEEDED if not (here / n).exists()]
    if missing:
        raise RuntimeError(f"missing {', '.join(missing)}; run 'git pull' or extract the zip again")
    return str(here.parent)


def check_data():
    from .db import connect, home
    h = home()
    probe = h / ".probe"
    probe.write_text("ok")
    probe.unlink()
    conn = connect()
    result = conn.execute("PRAGMA quick_check").fetchone()[0]
    conn.close()
    if result != "ok":
        raise RuntimeError(f"database damaged; stop the server, delete {h} and start again")
    return str(h)


def check_config():
    from .adapters import Registry
    from .db import home
    reg = Registry(home())
    try:
        return f"{len(reg.tool_specs())} tools available"  # also starts any upstream MCP servers
    finally:
        reg.close()


def check_port(port):
    with socket.socket() as s:
        s.settimeout(1)
        if s.connect_ex(("127.0.0.1", port)) != 0:
            return f"port {port} is free; the server is NOT running yet (start it with: python -m agentgit.cli web)"
    try:
        server = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3).headers.get("Server", "")
    except urllib.error.HTTPError as e:
        server = e.headers.get("Server", "")  # 401 when passwords are on
    except OSError:
        server = ""
    if "AgentGit/" in server:
        return f"the server is running: http://127.0.0.1:{port}"
    raise RuntimeError(f"another program (or an old copy) is using port {port}; close it or use --port {port + 1}")


def run(port=8765):
    checks = [("Python", check_python), ("Project files", check_files), ("Data folder", check_data),
              ("Tools and config", check_config), ("Server", lambda: check_port(port))]
    failed = 0
    for name, fn in checks:
        try:
            print(f"[ OK ] {name}: {fn()}")
        except Exception as e:
            failed += 1
            print(f"[FAIL] {name}: {e}")
    print("\nEverything looks fine." if not failed else f"\n{failed} problem(s) found. Fix the [FAIL] lines above.")
    return 1 if failed else 0
