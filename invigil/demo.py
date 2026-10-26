"""Fill a database with realistic-looking incidents and synthetic evidence frames.

    python -m invigil demo      # then: python -m invigil app --db demo.db  /  dashboard --db demo.db

The frames are drawn, not real footage. This is for previewing the UI only.
"""
from __future__ import annotations

import random
from pathlib import Path

import cv2
import numpy as np

from .db import Database
from .features import Person
from .pipeline import Pipeline
from .rules import BEHAVIORS


def _frame(rng, flagged_id: int, behavior: str, t: float):
    w, h = 960, 540
    img = np.zeros((h, w, 3), np.uint8)
    img[:] = np.linspace(70, 40, h)[:, None, None].astype(np.uint8) + np.array([6, 8, 10], np.uint8)
    cv2.rectangle(img, (0, int(h * .62)), (w, h), (52, 62, 74), -1)  # desks
    persons = []
    for i in range(6):
        x = 40 + i * 150 + rng.randint(-8, 8)
        box = (x, 120 + rng.randint(-10, 10), x + 125, 470)
        cv2.ellipse(img, (x + 62, box[1] + 60), (34, 42), 0, 0, 360, (150 - i * 6, 170 - i * 5, 190), -1)
        cv2.rectangle(img, (x + 18, box[1] + 105), (x + 108, 470), (96 + i * 8, 90, 84), -1)
        persons.append(Person(i + 1, tuple(float(v) for v in box)))
    return Pipeline._draw(img, persons, [], {flagged_id: {behavior}}, t)


def seed(db_path: str = "demo.db", out: str = "demo_runs", n: int = 18, rng_seed: int = 7) -> dict:
    rng = random.Random(rng_seed)
    db = Database(db_path)
    out_dir = Path(out) / "demo_exam_01" / "rules"
    out_dir.mkdir(parents=True, exist_ok=True)
    run = db.create_run("demo_exam_01", "rules", "demo_exam_01.mp4", 25.0, "demo", {})
    db.finish_run(run, 45000, 1800.0)
    weights = {BEHAVIORS[0]: 5, BEHAVIORS[1]: 9, BEHAVIORS[2]: 4}
    kinds = [b for b, k in weights.items() for _ in range(k)]
    times = sorted(rng.uniform(20, 1700) for _ in range(n))
    for t in times:
        beh, tid = rng.choice(kinds), rng.randint(1, 6)
        dur, conf = rng.uniform(1.2, 9.0), rng.uniform(0.35, 0.95)
        stem = f"t{t:08.2f}_id{tid}_{beh}"
        onset, best = out_dir / f"{stem}_onset.jpg", out_dir / f"{stem}_best.jpg"
        cv2.imwrite(str(onset), _frame(rng, tid, beh, t))
        cv2.imwrite(str(best), _frame(rng, tid, beh, t + dur / 2))
        eid = db.add_event(run, tid, beh, t, conf, str(onset))
        db.close_event(eid, t + dur, conf, str(best))
        r = rng.random()
        if r < .25:
            db.set_review(eid, "confirmed")
        elif r < .4:
            db.set_review(eid, "dismissed")
    return {"db": db_path, "events": n, "frames_dir": str(out_dir)}
