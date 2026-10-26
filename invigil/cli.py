from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from pathlib import Path

from .config import Config
from .db import Database


def _read_splits(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    out: dict = {}
    for r in rows:
        s, sp = r["session"].strip(), r["split"].strip()
        if sp not in ("train", "val", "test"):
            raise SystemExit(f"splits: bad split {sp!r} for session {s!r}")
        if s in out and out[s] != sp:
            raise SystemExit(f"splits: session {s!r} appears in both {out[s]} and {sp}")
        out[s] = sp
    return out


def cmd_run(a):
    cfg = Config.load(a.config, mode=a.mode)
    session = a.session or Path(a.video).stem
    splits = _read_splits(Path(a.splits))
    if splits.get(session) == "test" and not a.final:
        raise SystemExit(f"session {session!r} is in the held-out test split. "
                         "Pass --final only when you are done tuning.")
    from .cloud import open_sync
    from .pipeline import Pipeline
    db = Database(a.db)
    sync, msg = (None, "disabled") if a.no_cloud else open_sync(db, a.firebase)
    print("Cloud:", msg)
    summary = Pipeline(cfg, db, a.out).run(a.video, session=session, tag=a.tag, max_frames=a.max_frames,
                                          on_alert=(lambda e: sync.enqueue(e["event_id"])) if sync else None)
    if sync:
        print("Uploading evidence ...", "done" if sync.flush() else "timed out; run again later to retry")
    print(summary)


def cmd_evaluate(a):
    from . import evaluate as ev
    db = Database(a.db)
    gt = ev.load_gt(a.gt)
    results, kappas, durations = {}, {}, {}
    for tag in a.tags:
        durations = {r["session"]: r["duration_s"] for r in db.runs(tag) if r["duration_s"]}
        pred = [e for e in db.events(tag=tag)]
        results[tag] = ev.evaluate(gt, pred, durations, a.iou, a.pad)
        kappas[f"{tag} vs rater 1"] = ev.agreement(pred, gt, durations, results[tag]["sessions"])
    if a.gt2:
        gt2 = ev.load_gt(a.gt2)
        kappas["rater 1 vs rater 2"] = ev.agreement(gt, gt2, durations, results[a.tags[0]]["sessions"])
    reviewer = ev.reviewer_stats(db.events(tag=a.tags[0]))
    md = ev.render_report(results, reviewer, kappas)
    ev.write_outputs(a.report_dir, results, md)
    print(md)


def cmd_check_splits(a):
    path = Path(a.splits)
    splits = _read_splits(path)
    if not splits:
        raise SystemExit(f"no splits found in {path}")
    test = sorted(s for s, sp in splits.items() if sp == "test")
    digest = hashlib.sha256("\n".join(test).encode()).hexdigest()
    lock = path.with_suffix(".lock")
    if a.freeze:
        lock.write_text(digest + "\n")
        print(f"froze test split ({len(test)} sessions) -> {lock}")
    elif lock.exists() and lock.read_text().strip() != digest:
        raise SystemExit("test split changed after it was frozen")
    counts = {sp: sum(1 for v in splits.values() if v == sp) for sp in ("train", "val", "test")}
    print("ok", counts)


def cmd_demo(a):
    from .demo import seed
    print(seed(a.db, a.out))


def cmd_dashboard(a):
    from .dashboard import serve
    from .cloud import open_sync
    db = Database(a.db)
    sync, msg = open_sync(db, a.firebase)
    print("Cloud:", msg)
    serve(db, port=a.port, sync=sync, open_browser=not a.no_open)


def cmd_app(a):
    try:
        from .ui import launch
    except ModuleNotFoundError as e:
        if "PySide6" in str(e):
            raise SystemExit("The desktop app needs PySide6:  pip install PySide6-Essentials")
        raise
    launch(Config.load(a.config), a.db, a.out, a.firebase)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="invigil")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="process one video headlessly")
    r.add_argument("video")
    r.add_argument("--session"); r.add_argument("--tag")
    r.add_argument("--mode", choices=["rules", "baseline_phone"])
    r.add_argument("--config", default="config.yaml"); r.add_argument("--db", default="invigil.db")
    r.add_argument("--out", default="runs"); r.add_argument("--splits", default="data/splits.csv")
    r.add_argument("--final", action="store_true", help="allow processing a held-out test session")
    r.add_argument("--max-frames", type=int)
    r.add_argument("--firebase", default="firebase.json"); r.add_argument("--no-cloud", action="store_true")
    r.set_defaults(fn=cmd_run)

    e = sub.add_parser("evaluate", help="score runs against ground-truth labels")
    e.add_argument("--gt", required=True); e.add_argument("--gt2", help="second rater, for kappa")
    e.add_argument("--tags", nargs="+", default=["rules", "baseline"])
    e.add_argument("--db", default="invigil.db"); e.add_argument("--report-dir", default="reports")
    e.add_argument("--iou", type=float, default=0.3); e.add_argument("--pad", type=float, default=0.5)
    e.set_defaults(fn=cmd_evaluate)

    c = sub.add_parser("check-splits", help="validate session-level splits; --freeze locks the test set")
    c.add_argument("--splits", default="data/splits.csv"); c.add_argument("--freeze", action="store_true")
    c.set_defaults(fn=cmd_check_splits)

    p = sub.add_parser("app", help="launch the desktop app")
    p.add_argument("--config", default="config.yaml"); p.add_argument("--db", default="invigil.db")
    p.add_argument("--out", default="runs"); p.add_argument("--firebase", default="firebase.json")
    p.set_defaults(fn=cmd_app)

    d = sub.add_parser("dashboard", help="open the local web dashboard")
    d.add_argument("--db", default="invigil.db"); d.add_argument("--port", type=int, default=8765)
    d.add_argument("--firebase", default="firebase.json"); d.add_argument("--no-open", action="store_true")
    d.set_defaults(fn=cmd_dashboard)

    m = sub.add_parser("demo", help="create a demo database with fake incidents to preview the UI")
    m.add_argument("--db", default="demo.db"); m.add_argument("--out", default="demo_runs")
    m.set_defaults(fn=cmd_demo)

    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
