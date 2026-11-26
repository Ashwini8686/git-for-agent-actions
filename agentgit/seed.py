"""Creates the fake demo data (safe to delete and recreate any time)."""
import json
import shutil

from .db import home


def seed():
    h = home()
    for p in (h / "workspace", h / "calendar.json", h / "outbox.jsonl", h / "agentgit.db"):
        shutil.rmtree(p) if p.is_dir() else p.unlink(missing_ok=True)
    ws = h / "workspace"
    ws.mkdir(parents=True)
    for n in ["maths_notes.pdf", "assignment.docx", "holiday.jpg", "timetable.xlsx", "todo.txt"]:
        (ws / n).write_text(f"sample content of {n}\n")
    events = [
        {"id": "ev_study1", "title": "study block", "start": "2026-11-25T18:00", "end": "2026-11-25T19:00"},
        {"id": "ev_study2", "title": "study block", "start": "2026-11-26T18:00", "end": "2026-11-26T19:00"},
        {"id": "ev_study3", "title": "study block", "start": "2026-11-27T18:00", "end": "2026-11-27T19:00"},
        {"id": "ev_gym", "title": "gym", "start": "2026-11-26T07:00", "end": "2026-11-26T08:00"},
        {"id": "ev_proj", "title": "project submission", "start": "2026-11-27T17:00", "end": "2026-11-27T18:00"},
    ]
    (h / "calendar.json").write_text(json.dumps(events, indent=1))
    return h


WORKFLOW = [  # the example task: "organize my files and plan my exam week"
    ("move_file", {"src": "maths_notes.pdf", "dst": "Study/"}),
    ("move_file", {"src": "assignment.docx", "dst": "Study/"}),
    ("move_file", {"src": "holiday.jpg", "dst": "Photos/"}),
    ("add_event", {"title": "Maths exam", "start": "2026-12-10T10:00"}),
    ("add_event", {"title": "Physics exam", "start": "2026-12-12T10:00"}),
    ("delete_event", {"event_id": "ev_study1"}),
    ("delete_file", {"path": "todo.txt"}),
]
