import pytest

from invigil.cli import _read_splits, main
from invigil.db import Database


def test_db_roundtrip_and_review(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    run = db.create_run("s1", "rules", "v.mp4", 25.0, "m", {"a": 1})
    eid = db.add_event(run, 3, "PHONE_USE", 12.0, 0.7, "onset.jpg")
    db.close_event(eid, 20.0, 0.9, "best.jpg")
    db.finish_run(run, 500, 20.0)
    e = db.get_event(eid)
    assert (e["session"], e["tag"], e["t_end"], e["best_shot"], e["review_status"]) == ("s1", "rules", 20.0, "best.jpg", "pending")
    db.set_review(eid, "dismissed")
    assert db.events(tag="rules")[0]["review_status"] == "dismissed"
    assert db.runs("rules")[0]["duration_s"] == 20.0
    with pytest.raises(ValueError):
        db.set_review(eid, "maybe")


def test_split_leak_is_rejected(tmp_path):
    p = tmp_path / "splits.csv"
    p.write_text("session,split\ns1,train\ns1,test\n")
    with pytest.raises(SystemExit):
        _read_splits(p)


def test_freeze_detects_changed_test_set(tmp_path, capsys):
    p = tmp_path / "splits.csv"
    p.write_text("session,split\ns1,train\ns2,val\ns3,test\n")
    main(["check-splits", "--splits", str(p), "--freeze"])
    main(["check-splits", "--splits", str(p)])
    p.write_text("session,split\ns1,train\ns2,test\ns3,test\n")
    with pytest.raises(SystemExit):
        main(["check-splits", "--splits", str(p)])


def test_run_refuses_held_out_session(tmp_path):
    p = tmp_path / "splits.csv"
    p.write_text("session,split\nhold,test\n")
    with pytest.raises(SystemExit) as e:
        main(["run", "x.mp4", "--session", "hold", "--splits", str(p), "--db", str(tmp_path / "d.db"), "--config", "config.yaml"])
    assert "held-out" in str(e.value)
