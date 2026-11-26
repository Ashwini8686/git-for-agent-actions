"""Command line: python -m agentgit.cli <command>"""
import argparse
import json
import sys
import time

from .db import home
from .engine import agent_message, make_engine
from .seed import WORKFLOW, seed


def main(argv=None):
    ap = argparse.ArgumentParser(prog="agentgit")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed", help="reset the demo data")
    st = sub.add_parser("stage", help="stage one action: stage move_file src=a.pdf dst=Study/  (or --json '{...}')")
    st.add_argument("tool"); st.add_argument("pairs", nargs="*"); st.add_argument("--json")
    sub.add_parser("diff", help="show what is staged")
    cm = sub.add_parser("commit", help="approve and run the staged batch")
    cm.add_argument("--confirm-irreversible", action="store_true")
    cm.add_argument("--fail-at", type=int, help="inject a failure at step N (demo)")
    sub.add_parser("reject", help="discard the staged batch")
    rv = sub.add_parser("revert", help="undo a committed batch"); rv.add_argument("batch", type=int)
    sub.add_parser("history"); sub.add_parser("state"); sub.add_parser("demo", help="stage the example workflow")
    sub.add_parser("audit", help="verify the tamper-evident audit chain")
    sub.add_parser("tools", help="list every tool the gateway exposes, with effect class and risk")
    cp = sub.add_parser("capsule", help="routine capsules: save | run | list")
    cp.add_argument("action", choices=["save", "run", "list"]); cp.add_argument("arg1", nargs="?"); cp.add_argument("arg2", nargs="?")
    wb = sub.add_parser("web", help="dashboard + HTTP API for any agent")
    wb.add_argument("--host", default="127.0.0.1"); wb.add_argument("--port", type=int, default=8765)
    wb.add_argument("--admin-token"); wb.add_argument("--agent-token")
    a = ap.parse_args(argv)

    if a.cmd == "seed":
        print("Demo data created in", seed()); return
    if a.cmd == "web":
        from .server import serve
        serve(a.host, a.port, a.admin_token, a.agent_token); return
    eng = make_engine("human")
    try:
        if a.cmd == "stage":
            args = json.loads(a.json) if a.json else dict(p.split("=", 1) for p in a.pairs)
            print(agent_message(eng.stage(a.tool, args)))
        elif a.cmd == "demo":
            for tool, args in WORKFLOW:
                print("staged:", eng.stage(tool, args, "demo-agent")["description"])
            print("\n" + eng.diff() + "\n\nNothing has changed yet. Run: python -m agentgit.cli commit")
        elif a.cmd == "diff":
            print(eng.diff())
        elif a.cmd == "commit":
            print(eng.commit(confirm_irreversible=a.confirm_irreversible, fail_at=a.fail_at))
        elif a.cmd == "reject":
            print(eng.reject())
        elif a.cmd == "revert":
            print(eng.revert(a.batch))
        elif a.cmd == "history":
            for r in eng.history():
                print(f"#{r['id']:<3} {r['status']:<16} {r['n']} actions  risk {r['risk']:<3} {r['agent']:<14} {time.strftime('%d %b %H:%M', time.localtime(r['created']))}")
        elif a.cmd == "state":
            v = eng.reg.builtin_view()
            print(("Files:\n" + v["files"] + "\nCalendar:\n" + v["calendar"]) if v else "No built-in demo data.")
        elif a.cmd == "audit":
            print(eng.verify_log())
        elif a.cmd == "tools":
            for s in eng.reg.tool_specs():
                print(f"{s['name']:<26} {s['effect']:<13} risk {s['risk']}")
        elif a.cmd == "capsule":
            if a.action == "save":
                print(eng.save_capsule(int(a.arg1), a.arg2))
            elif a.action == "run":
                print(eng.run_capsule(a.arg1, "human"))
            else:
                for c in eng.capsules():
                    print(f"{c['name']:<20} {c['actions']} actions, run {c['runs']}x")
    except Exception as e:
        sys.exit(f"error: {e}")
    finally:
        eng.reg.close()
        eng.close()


if __name__ == "__main__":
    main()
