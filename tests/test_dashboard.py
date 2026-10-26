import json
import urllib.request

import pytest

from invigil.dashboard import serve, summary
from invigil.db import Database
from invigil.demo import seed


@pytest.fixture()
def server(tmp_path):
    db_path = str(tmp_path / "d.db")
    seed(db_path, str(tmp_path / "runs"), n=12)
    db = Database(db_path)
    srv = serve(db, port=0, block=False)
    yield db, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def get(url):
    with urllib.request.urlopen(url) as r:
        return r.status, r.headers.get("Content-Type"), r.read()


def post(url, obj):
    req = urllib.request.Request(url, json.dumps(obj).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def test_pages_and_summary(server):
    db, base = server
    assert get(base + "/")[0] == 200 and b"Invigil" in get(base + "/")[2]
    assert get(base + "/icon.png")[1] == "image/png" if (__import__("pathlib").Path("invigil/assets/icon.png").exists()) else True
    s = json.loads(get(base + "/api/summary")[2])
    k = s["kpis"]
    assert k["total"] == 12 and k["pending"] + k["confirmed"] + k["dismissed"] == 12
    assert sum(b["count"] for b in s["by_behavior"]) == 12
    assert sum(t["count"] for t in s["timeline"]) == 12


def test_filters_and_review_roundtrip(server):
    db, base = server
    rows = json.loads(get(base + "/api/incidents?status=pending")[2])
    assert rows and all(r["status"] == "pending" for r in rows)
    eid = rows[0]["id"]
    out = post(base + "/api/review", {"event_id": eid, "status": "confirmed"})
    assert out["status"] == "confirmed" and db.get_event(eid)["review_status"] == "confirmed"
    assert db.get_event(eid)["cloud_synced"] == 0
    beh = rows[0]["behavior"]
    assert all(r["behavior"] == beh for r in json.loads(get(base + f"/api/incidents?behavior={beh}")[2]))
    assert json.loads(get(base + "/api/incidents?q=zzzz-nothing")[2]) == []


def test_bad_review_is_rejected(server):
    _, base = server
    for body in ({"event_id": 1, "status": "maybe"}, {"status": "confirmed"}):
        with pytest.raises(urllib.error.HTTPError) as e:
            post(base + "/api/review", body)
        assert e.value.code == 400


def test_screenshots_and_csv(server):
    _, base = server
    eid = json.loads(get(base + "/api/incidents")[2])[0]["id"]
    st, ct, body = get(base + f"/shot/{eid}/best")
    assert st == 200 and ct == "image/jpeg" and body[:2] == b"\xff\xd8"
    assert get(base + f"/shot/{eid}/onset")[0] == 200
    with pytest.raises(urllib.error.HTTPError):
        get(base + "/shot/99999/best")
    csv_text = get(base + "/api/export.csv")[2].decode()
    assert csv_text.startswith("id,session,student") and len(csv_text.splitlines()) == 13


def test_summary_on_empty_db(tmp_path):
    s = summary(Database(str(tmp_path / "e.db")))
    assert s["kpis"]["total"] == 0 and s["kpis"]["false_alarm_rate"] is None and s["timeline"] == []
