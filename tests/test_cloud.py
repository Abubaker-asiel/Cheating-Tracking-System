import sqlite3

import pytest

from invigil.cloud import CloudConfig, CloudSync
from invigil.db import Database


class Fake:
    def __init__(self, fail=0):
        self.calls, self.fail = [], fail

    def push(self, doc_id, data, files):
        if self.fail:
            self.fail -= 1
            raise ConnectionError("offline")
        self.calls.append((doc_id, dict(data), dict(files)))
        return {k: f"gs://b/{doc_id}/{k}.jpg" for k in files}


def make_event(db, tmp_path, closed=True, session="exam 01/a"):
    run = db.create_run(session, "rules", "v.mp4", 25, "m", {})
    onset, best = tmp_path / "o.jpg", tmp_path / "b.jpg"
    onset.write_bytes(b"x"); best.write_bytes(b"y")
    eid = db.add_event(run, 3, "PHONE_USE", 5.0, 0.7, str(onset))
    if closed:
        db.close_event(eid, 9.0, 0.9, str(best))
    return eid


def test_uploads_once_and_marks_synced(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    eid = make_event(db, tmp_path)
    fake = Fake()
    sync = CloudSync(db, fake)
    sync.enqueue(eid); assert sync.flush(5)
    doc_id, data, files = fake.calls[0]
    assert set(files) == {"onset", "best"} and "/" not in doc_id and " " not in doc_id
    assert data["behavior"] == "PHONE_USE" and data["review_status"] == "pending"
    e = db.get_event(eid)
    assert e["cloud_synced"] == 1 and e["onset_cloud"].startswith("gs://") and e["cloud_error"] is None
    sync.enqueue(eid); sync.flush(5)
    assert fake.calls[1][2] == {}  # nothing re-uploaded, document just rewritten


def test_open_event_stays_pending_until_closed(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    eid = make_event(db, tmp_path, closed=False)
    sync = CloudSync(db, Fake())
    sync.enqueue(eid); sync.flush(5)
    e = db.get_event(eid)
    assert e["onset_cloud"] and e["cloud_synced"] == 0


def test_failure_is_recorded_and_retried(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    eid = make_event(db, tmp_path)
    errors = []
    sync = CloudSync(db, Fake(fail=1), on_error=lambda i, m: errors.append(m))
    sync.enqueue(eid); sync.flush(5)
    assert "offline" in db.get_event(eid)["cloud_error"] and errors
    assert sync.enqueue_pending() == 1 and sync.flush(5)
    e = db.get_event(eid)
    assert e["cloud_synced"] == 1 and e["cloud_error"] is None


def test_review_change_triggers_resync(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    eid = make_event(db, tmp_path)
    fake = Fake(); sync = CloudSync(db, fake)
    sync.enqueue(eid); sync.flush(5)
    assert db.unsynced_event_ids() == []
    db.set_review(eid, "dismissed")
    assert db.unsynced_event_ids() == [eid]
    sync.enqueue_pending(); sync.flush(5)
    assert fake.calls[-1][1]["review_status"] == "dismissed" and db.unsynced_event_ids() == []


def test_stale_review_does_not_mark_synced(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    eid = make_event(db, tmp_path)
    db.set_review(eid, "confirmed")
    db.mark_synced(eid, "pending")  # a sync that read the old state must not win
    assert db.get_event(eid)["cloud_synced"] == 0


def test_old_database_is_migrated(tmp_path):
    p = str(tmp_path / "old.db")
    con = sqlite3.connect(p)
    con.executescript("""CREATE TABLE runs(run_id INTEGER PRIMARY KEY AUTOINCREMENT, session TEXT, tag TEXT, video_path TEXT,
      fps REAL, n_frames INTEGER, duration_s REAL, model_version TEXT, config_json TEXT, created_at TEXT);
      CREATE TABLE events(event_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, track_id INTEGER, behavior TEXT,
      t_start REAL, t_end REAL, peak_conf REAL, onset_shot TEXT, best_shot TEXT,
      review_status TEXT NOT NULL DEFAULT 'pending', reviewed_at TEXT, created_at TEXT);
      INSERT INTO runs(session,tag) VALUES('s','rules');
      INSERT INTO events(run_id,track_id,behavior,t_start,t_end) VALUES(1,1,'PHONE_USE',1,2);""")
    con.commit(); con.close()
    db = Database(p)
    assert db.get_event(1)["cloud_synced"] == 0 and db.unsynced_event_ids() == [1]


def test_config_roundtrip_and_unknown_key(tmp_path):
    p = tmp_path / "firebase.json"
    assert CloudConfig.load(p) is None
    CloudConfig(storage_bucket="x.firebasestorage.app").save(p)
    assert CloudConfig.load(p).storage_bucket == "x.firebasestorage.app"
    p.write_text('{"bucket": "x"}')
    with pytest.raises(ValueError):
        CloudConfig.load(p)


def test_set_cloud_rejects_unknown_fields(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    eid = make_event(db, tmp_path)
    with pytest.raises(ValueError):
        db.set_cloud(eid, review_status="confirmed")
