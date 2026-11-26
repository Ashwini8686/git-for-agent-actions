"""Command line: python -m agentgit.cli <command>"""
import argparse
import shlex
import sys
import time

from .db import home
from .engine import make_engine
from .seed import WORKFLOW, seed


def show_state(eng):
    print("Files:\n" + eng.stage("list_files", {"folder": "."})["result"])
    print("Calendar:\n" + eng.stage("list_events", {})["result"])


def main(argv=None):
    ap = argparse.ArgumentParser(prog="agentgit")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed", help="reset the demo data")
    st = sub.add_parser("stage", help="stage one action, e.g. stage move_file src=a.pdf dst=Study/")
    st.add_argument("tool"); st.add_argument("pairs", nargs="*")
    sub.add_parser("diff", help="show what is staged")
    cm = sub.add_parser("commit", help="approve and run the staged batch")
    cm.add_argument("--confirm-irreversible", action="store_true")
    cm.add_argument("--fail-at", type=int, help="inject a failure at step N (demo)")
    sub.add_parser("reject", help="discard the staged batch")
    rv = sub.add_parser("revert", help="undo a committed batch"); rv.add_argument("batch", type=int)
    sub.add_parser("history"); sub.add_parser("state"); sub.add_parser("web", help="open the approval page")
    sub.add_parser("demo", help="stage the example workflow")
    a = ap.parse_args(argv)

    if a.cmd == "seed":
        print("Demo data created in", seed()); return
    if a.cmd == "web":
        from .webui import serve; serve(); return
    eng = make_engine()
    try:
        if a.cmd == "stage":
            args = dict(p.split("=", 1) for p in a.pairs)
            r = eng.stage(a.tool, args)
            print(r.get("result") or f"STAGED (not executed): {r['description']}")
        elif a.cmd == "demo":
            for tool, args in WORKFLOW:
                print("staged:", eng.stage(tool, args)["description"])
            print("\n" + eng.diff() + "\n\nNothing has changed yet. Run: python -m agentgit.cli commit")
        elif a.cmd == "diff":
            print(eng.diff())
        elif a.cmd == "commit":
            r = eng.commit(confirm_irreversible=a.confirm_irreversible, fail_at=a.fail_at)
            print(r)
        elif a.cmd == "reject":
            print(eng.reject())
        elif a.cmd == "revert":
            print(eng.revert(a.batch))
        elif a.cmd == "history":
            for r in eng.history():
                print(f"#{r['id']:<3} {r['status']:<16} {r['n']} actions  {time.strftime('%d %b %H:%M', time.localtime(r['created']))}")
        elif a.cmd == "state":
            show_state(eng)
    except Exception as e:
        sys.exit(f"error: {e}")
    finally:
        eng.close()


if __name__ == "__main__":
    main()
