import math

import numpy as np

from invigil import evaluate as ev
from invigil.rules import GAZE, PHONE


def E(session, behavior, a, b, conf=0.8):
    return {"session": session, "behavior": behavior, "t_start": a, "t_end": b, "peak_conf": conf}


def test_iou_and_match_is_one_to_one():
    assert ev.temporal_iou((0, 10), (5, 15)) == 5 / 15
    gt = [E("s", PHONE, 10, 20)]
    pred = [E("s", PHONE, 10, 19), E("s", PHONE, 11, 20)]  # duplicate detections of one event
    m, fn, fp = ev.match(gt, pred)
    assert len(m) == 1 and fn == [] and len(fp) == 1


def test_counts_and_rates():
    gt = [E("a", PHONE, 10, 20), E("a", PHONE, 100, 110), E("a", GAZE, 50, 60)]
    pred = [E("a", PHONE, 11, 21), E("a", GAZE, 200, 210), E("a", GAZE, 51, 59)]
    r = ev.evaluate(gt, pred, {"a": 3600}, n_boot=10)
    o = r["overall"]
    assert (o["tp"], o["fp"], o["fn"]) == (2, 1, 1)
    assert math.isclose(o["precision"], 2 / 3) and math.isclose(o["recall"], 2 / 3)
    assert math.isclose(o["false_alerts_per_hour"], 1.0)
    assert r["per_behavior"][PHONE]["fn"] == 1 and r["per_behavior"][GAZE]["fp"] == 1
    assert r["ci95"] is None  # one session: no bootstrap


def test_behaviors_do_not_cross_match():
    r = ev.evaluate([E("a", PHONE, 10, 20)], [E("a", GAZE, 10, 20)], {"a": 100}, n_boot=5)
    assert (r["overall"]["tp"], r["overall"]["fp"], r["overall"]["fn"]) == (0, 1, 1)


def test_bootstrap_resamples_sessions():
    gt = [E("a", PHONE, 10, 20), E("b", PHONE, 10, 20), E("c", PHONE, 10, 20)]
    pred = [E("a", PHONE, 10, 20), E("b", PHONE, 10, 20)]  # c missed
    r = ev.evaluate(gt, pred, {"a": 600, "b": 600, "c": 600}, n_boot=200)
    lo, hi = r["ci95"]["overall"]["recall"]
    assert lo <= 2 / 3 <= hi and hi <= 1.0 and lo >= 0.0


def test_missing_run_raises():
    try:
        ev.evaluate([E("zzz", PHONE, 1, 2)], [], {"a": 10})
    except ValueError as e:
        assert "zzz" in str(e)
    else:
        raise AssertionError


def test_kappa_perfect_chance_and_disagreement():
    a = np.array([1, 1, 0, 0, 1, 0], dtype=bool)
    assert ev.cohen_kappa(a, a) == 1.0
    assert ev.cohen_kappa(a, ~a) == -1.0
    rng = np.random.default_rng(0)
    x, y = rng.random(20000) < .5, rng.random(20000) < .5
    assert abs(ev.cohen_kappa(x, y)) < 0.03


def test_agreement_on_bins():
    a = [E("s", PHONE, 10, 19.9)]
    b = [E("s", PHONE, 10, 19.9)]
    k = ev.agreement(a, b, {"s": 100}, ["s"])
    assert k["overall"] == 1.0 and k[PHONE] == 1.0


def test_reviewer_stats():
    rows = [{"review_status": s} for s in ("confirmed", "dismissed", "dismissed", "pending")]
    s = ev.reviewer_stats(rows)
    assert math.isclose(s["dismissal_rate"], 2 / 3) and s["pending"] == 1


def test_report_renders():
    gt = [E("a", PHONE, 10, 20), E("b", PHONE, 10, 20)]
    pred = [E("a", PHONE, 10, 20), E("b", GAZE, 5, 9)]
    res = {"rules": ev.evaluate(gt, pred, {"a": 600, "b": 600}, n_boot=20)}
    md = ev.render_report(res, ev.reviewer_stats([]), {"rules vs rater 1": ev.agreement(pred, gt, {"a": 600, "b": 600}, ["a", "b"])})
    assert "Overall" in md and "most confident false alarms" in md
