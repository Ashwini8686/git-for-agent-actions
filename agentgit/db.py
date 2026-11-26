"""SQLite storage: batches, actions and an audit log."""
import os
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS batches(
  id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL,
  created REAL, updated REAL, note TEXT);
CREATE TABLE IF NOT EXISTS actions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id INTEGER NOT NULL, seq INTEGER NOT NULL,
  tool TEXT NOT NULL, args TEXT NOT NULL, effect TEXT NOT NULL, status TEXT NOT NULL,
  idem TEXT NOT NULL UNIQUE, desc TEXT, ord INTEGER, undo TEXT, error TEXT,
  UNIQUE(batch_id, seq));
CREATE TABLE IF NOT EXISTS log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, batch_id INTEGER, event TEXT, detail TEXT);
"""


def home() -> Path:
    """Data folder. Set AGENTGIT_HOME so the gateway, CLI and web page share one place."""
    p = Path(os.environ.get("AGENTGIT_HOME", "data")).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(home() / "agentgit.db")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
