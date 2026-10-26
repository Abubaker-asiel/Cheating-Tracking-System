"""SQLite store. One row per run (a video processed with a config) and one per event."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(
  run_id INTEGER PRIMARY KEY AUTOINCREMENT,
  session TEXT NOT NULL, tag TEXT NOT NULL, video_path TEXT,
  fps REAL, n_frames INTEGER, duration_s REAL,
  model_version TEXT, config_json TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS events(
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL REFERENCES runs(run_id),
  track_id INTEGER, behavior TEXT NOT NULL,
  t_start REAL NOT NULL, t_end REAL, peak_conf REAL,
  onset_shot TEXT, best_shot TEXT,
  review_status TEXT NOT NULL DEFAULT 'pending', reviewed_at TEXT,
  created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id);
"""

_CLOUD_COLS = {"onset_cloud": "TEXT", "best_cloud": "TEXT",
               "cloud_synced": "INTEGER NOT NULL DEFAULT 0", "cloud_error": "TEXT"}

_EVENT_SELECT = ("SELECT e.*, r.session, r.tag, r.model_version FROM events e "
                 "JOIN runs r USING(run_id)")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str = "invigil.db"):
        self.conn = sqlite3.connect(path, check_same_thread=False, timeout=5)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")  # app + dashboard can share the file
            self.conn.executescript(SCHEMA)
            self._migrate()

    def _migrate(self):
        """Add columns introduced after the first release to an existing database."""
        have = {r[1] for r in self.conn.execute("PRAGMA table_info(events)")}
        for col, typ in _CLOUD_COLS.items():
            if col not in have:
                self.conn.execute(f"ALTER TABLE events ADD COLUMN {col} {typ}")
        self.conn.commit()

    def _exec(self, sql: str, args: tuple = ()):
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur

    def _all(self, sql: str, args: tuple = ()) -> list:
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    # runs
    def create_run(self, session, tag, video_path, fps, model_version, config: dict) -> int:
        cur = self._exec(
            "INSERT INTO runs(session,tag,video_path,fps,model_version,config_json,created_at) VALUES(?,?,?,?,?,?,?)",
            (session, tag, str(video_path), fps, model_version, json.dumps(config), _now()))
        return cur.lastrowid

    def finish_run(self, run_id: int, n_frames: int, duration_s: float):
        self._exec("UPDATE runs SET n_frames=?, duration_s=? WHERE run_id=?", (n_frames, duration_s, run_id))

    def runs(self, tag: str | None = None) -> list:
        if tag:
            return self._all("SELECT * FROM runs WHERE tag=? ORDER BY run_id", (tag,))
        return self._all("SELECT * FROM runs ORDER BY run_id")

    # events
    def add_event(self, run_id, track_id, behavior, t_start, peak_conf, onset_shot) -> int:
        cur = self._exec(
            "INSERT INTO events(run_id,track_id,behavior,t_start,peak_conf,onset_shot,created_at) VALUES(?,?,?,?,?,?,?)",
            (run_id, track_id, behavior, t_start, peak_conf, onset_shot, _now()))
        return cur.lastrowid

    def close_event(self, event_id: int, t_end: float, peak_conf: float, best_shot: str | None):
        self._exec("UPDATE events SET t_end=?, peak_conf=?, best_shot=? WHERE event_id=?",
                   (t_end, peak_conf, best_shot, event_id))

    def get_event(self, event_id: int) -> dict:
        return self._all(_EVENT_SELECT + " WHERE e.event_id=?", (event_id,))[0]

    def events(self, tag: str | None = None, run_id: int | None = None, newest_first: bool = False) -> list:
        sql, args, where = _EVENT_SELECT, [], []
        if tag:
            where.append("r.tag=?"); args.append(tag)
        if run_id:
            where.append("e.run_id=?"); args.append(run_id)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY e.event_id " + ("DESC" if newest_first else "ASC")
        return self._all(sql, tuple(args))

    def set_review(self, event_id: int, status: str):
        if status not in ("pending", "confirmed", "dismissed"):
            raise ValueError(status)
        # cloud_synced=0 so the new review state is pushed on the next sync
        self._exec("UPDATE events SET review_status=?, reviewed_at=?, cloud_synced=0 WHERE event_id=?",
                   (status, _now(), event_id))

    # cloud bookkeeping
    def set_cloud(self, event_id: int, **fields):
        allowed = {"onset_cloud", "best_cloud", "cloud_error"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"not a cloud field: {sorted(bad)}")
        if fields:
            cols = ", ".join(f"{k}=?" for k in fields)
            self._exec(f"UPDATE events SET {cols} WHERE event_id=?", (*fields.values(), event_id))

    def mark_synced(self, event_id: int, review_status_pushed: str):
        """Only if the review state did not change while we were uploading."""
        self._exec("UPDATE events SET cloud_synced=1 WHERE event_id=? AND review_status=?",
                   (event_id, review_status_pushed))

    def unsynced_event_ids(self) -> list:
        return [r["event_id"] for r in self._all(
            "SELECT event_id FROM events WHERE cloud_synced=0 AND t_end IS NOT NULL ORDER BY event_id")]
