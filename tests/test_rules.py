import numpy as np

from invigil.config import Config
from invigil.features import Person, Phone
from invigil.rules import (GAZE, HAND, PHONE, BehaviorEngine, EpisodeTracker)


def run(tr, seq):
    """seq: list of (t, active, conf) -> flat list of signal names"""
    out = []
    for t, a, c in seq:
        out += [(t, s, i) for s, i in tr.update(t, a, c)]
    return out


def test_opens_only_after_min_duration():
    tr = EpisodeTracker(min_s=1.5, release_s=1.0)
    sig = run(tr, [(0.0, True, .5), (0.5, True, .5), (1.0, True, .5), (1.5, True, .5)])
    assert [s[1] for s in sig] == ["open"]
    assert sig[0][0] == 1.5 and sig[0][2]["t_start"] == 0.0  # start is backdated to first flagged frame


def test_blip_shorter_than_min_never_opens():
    tr = EpisodeTracker(min_s=1.5, release_s=1.0)
    sig = run(tr, [(0.0, True, .9), (0.5, True, .9), (1.0, False, 0), (2.5, False, 0)])
    assert sig == [] and tr.idle


def test_short_dropout_does_not_split_event():
    tr = EpisodeTracker(min_s=1.0, release_s=1.0)
    seq = [(0, True, .5), (.5, True, .5), (1.0, True, .5), (1.5, False, 0), (2.0, True, .5), (2.5, True, .5),
           (3.0, False, 0), (4.5, False, 0)]
    names = [s[1] for s in run(tr, seq)]
    assert names == ["open", "close"]


def test_long_gap_splits_into_two_events():
    tr = EpisodeTracker(min_s=0.5, release_s=1.0)
    seq = [(0, True, .5), (.5, True, .5), (1.0, False, 0), (2.5, False, 0),
           (3.0, True, .5), (3.5, True, .5), (4.0, False, 0), (6.0, False, 0)]
    assert [s[1] for s in run(tr, seq)] == ["open", "close", "open", "close"]


def test_close_reports_last_flagged_time_and_peak():
    tr = EpisodeTracker(min_s=0.5, release_s=1.0)
    seq = [(0, True, .4), (.5, True, .4), (1.0, True, .9), (1.5, True, .5), (2.0, False, 0), (3.5, False, 0)]
    sig = run(tr, seq)
    assert [s[1] for s in sig] == ["open", "peak", "close"]
    close = sig[-1][2]
    assert close["t_end"] == 1.5 and close["peak_conf"] == 0.9 and close["peak_t"] == 1.0


def test_flush_closes_open_event():
    tr = EpisodeTracker(min_s=0.0, release_s=1.0)
    tr.update(0.0, True, .5)
    assert [s for s, _ in tr.flush()] == ["close"]


def kp(**pts):
    k = np.zeros((17, 3))
    idx = dict(nose=0, le=1, re=2, ls=5, rs=6, lw=9, rw=10)
    for n, (x, y) in pts.items():
        k[idx[n]] = (x, y, 0.9)
    return k


def test_engine_phone_event_end_to_end():
    cfg = Config(phone_min_s=1.5, phone_release_s=1.0)
    eng = BehaviorEngine(cfg)
    holder = Person(7, (0, 0, 100, 200), kp(ls=(20, 100), rs=(80, 100), rw=(50, 150)))
    phone = [Phone((45, 140, 60, 160), 0.8)]
    sigs = []
    for i in range(0, 8):  # 0..3.5 s at 2 fps
        sigs += eng.step(i * 0.5, [holder], phone)
        if i == 3:
            assert eng.flagged_behaviors() == {7: {PHONE}}
    assert [s["signal"] for s in sigs].count("open") == 1
    for t in (4.0, 5.0, 6.0):
        sigs += eng.step(t, [holder], [])
    assert [s["signal"] for s in sigs if s["signal"] != "peak"] == ["open", "close"]
    assert eng.flagged_behaviors() == {}


def test_engine_gaze_requires_neighbor():
    cfg = Config(gaze_min_s=1.0, gaze_release_s=0.5)
    turned = Person(1, (0, 0, 100, 200), kp(nose=(75, 40), le=(40, 30), re=(60, 30), ls=(20, 100), rs=(80, 100)))
    neighbor = Person(2, (120, 0, 220, 200), None)
    for persons, expect in (([turned, neighbor], True), ([turned], False)):
        eng, opened = BehaviorEngine(cfg), False
        for t in (0, .5, 1.0, 1.5):
            opened |= any(s["signal"] == "open" and s["behavior"] == GAZE for s in eng.step(t, persons, []))
        assert opened is expect


def test_engine_hand_to_neighbor():
    cfg = Config(hand_min_s=1.0)
    reaching = Person(1, (0, 0, 100, 200), kp(rw=(160, 100)))
    neighbor = Person(2, (120, 0, 220, 200), None)
    eng, opened = BehaviorEngine(cfg), []
    for t in (0, .5, 1.0):
        opened += [s for s in eng.step(t, [reaching, neighbor], []) if s["signal"] == "open"]
    assert opened and opened[0]["behavior"] == HAND and opened[0]["track_id"] == 1


def test_baseline_alerts_on_any_phone_immediately():
    cfg = Config(mode="baseline_phone")
    p = Person(1, (0, 0, 100, 200), kp(ls=(20, 100), rs=(80, 100), rw=(90, 400)))  # wrist far away
    sigs = BehaviorEngine(cfg).step(0.0, [p], [Phone((10, 10, 25, 25), 0.6)])
    assert [s["signal"] for s in sigs] == ["open"]
    assert not BehaviorEngine(Config()).step(0.0, [p], [Phone((10, 10, 25, 25), 0.6)])
