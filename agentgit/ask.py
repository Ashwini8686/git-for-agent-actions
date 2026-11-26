"""Turns a typed request from the floating panel into a staged tool call. No LLM: fixed, predictable phrases."""
import re

HELP = ("Try: move maths_notes.pdf to Study/  |  delete file todo.txt  |  "
        "add event Maths exam at 2026-12-10 10:00  |  delete event ev_gym")
_DT = r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})"


def parse(text):
    """Return (tool, args), or None when the sentence is not understood."""
    t = " ".join((text or "").strip().split())
    m = re.fullmatch(r"(?:please )?move (?:file )?(\S+) (?:to|into) (\S+)", t, re.I)
    if m:
        dst = m.group(2)
        return "move_file", {"src": m.group(1), "dst": dst if dst.endswith("/") or "." in dst.split("/")[-1] else dst + "/"}
    m = re.fullmatch(r"(?:please )?delete (?:the )?event (\S+)", t, re.I)
    if m:
        return "delete_event", {"event_id": m.group(1)}
    m = re.fullmatch(r"(?:please )?(?:delete|remove) (?:the )?(?:file )?(\S+\.\w+)", t, re.I)
    if m:
        return "delete_file", {"path": m.group(1)}
    m = re.fullmatch(r"(?:please )?add (?:an )?event (.+?) (?:at|on|for) " + _DT, t, re.I)
    if m:
        return "add_event", {"title": m.group(1), "start": f"{m.group(2)}T{m.group(3)}"}
    return None
