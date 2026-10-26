"""Frame flags -> episodes (hysteresis) -> open/peak/close signals. Pure Python."""
from __future__ import annotations

from .config import Config
from .features import (Person, Phone, head_yaw_proxy, neighbor_in_direction,
                       phone_owner, visible_wrists, wrist_owner)

PHONE, GAZE, HAND = "PHONE_USE", "GAZE_NEIGHBOR", "HAND_TO_NEIGHBOR"
BEHAVIORS = (PHONE, GAZE, HAND)


class EpisodeTracker:
    """Turns noisy per-frame booleans into one event with a start, end and peak.

    - opens once the flag has persisted for min_s
    - dropouts shorter than release_s do not split an event (this is the merge rule)
    - event start is the first flagged frame, not the moment it opened
    """

    def __init__(self, min_s: float, release_s: float, peak_eps: float = 0.02):
        self.min_s, self.release_s, self.peak_eps = min_s, release_s, peak_eps
        self._reset()

    def _reset(self):
        self.first = self.last = self.peak_t = None
        self.peak_conf = 0.0
        self.is_open = False

    @property
    def idle(self) -> bool:
        return self.first is None

    def _info(self, end=None) -> dict:
        return {"t_start": self.first, "t_end": end, "peak_conf": self.peak_conf, "peak_t": self.peak_t}

    def update(self, t: float, active: bool, conf: float = 0.0) -> list:
        out = []
        if active:
            improved = False
            if self.first is None:
                self.first, self.peak_conf, self.peak_t = t, conf, t
            elif conf > self.peak_conf + self.peak_eps:
                self.peak_conf, self.peak_t, improved = conf, t, True
            self.last = t
            if not self.is_open and t - self.first >= self.min_s:
                self.is_open = True
                out.append(("open", self._info()))
            elif self.is_open and improved:
                out.append(("peak", self._info()))
        elif self.first is not None and t - self.last > self.release_s:
            if self.is_open:
                out.append(("close", self._info(end=self.last)))
            self._reset()
        return out

    def flush(self) -> list:
        out = [("close", self._info(end=self.last))] if self.is_open else []
        self._reset()
        return out


def frame_flags(cfg: Config, persons: list, phones: list) -> dict:
    """{(track_id, behavior): confidence} for everything active in this frame."""
    flags: dict = {}

    def put(key, conf):
        flags[key] = max(flags.get(key, 0.0), float(conf))

    baseline = cfg.mode == "baseline_phone"
    for ph in phones:
        owner = phone_owner(ph, persons, cfg.kp_conf, cfg.phone_wrist_frac, require_wrist=not baseline)
        if owner is not None:
            put((owner, PHONE), ph.conf)
    if baseline:
        return flags

    for p in persons:
        y = head_yaw_proxy(p, cfg.kp_conf)
        if y is not None and abs(y[0]) >= cfg.yaw_threshold:
            if neighbor_in_direction(p, persons, 1 if y[0] > 0 else -1, cfg.neighbor_max_gap) is not None:
                put((p.track_id, GAZE), min(1.0, abs(y[0]) / (2 * cfg.yaw_threshold)) * y[1])
        for x, yy, c in visible_wrists(p, cfg.kp_conf):
            owner = wrist_owner(x, yy, persons)
            if owner is not None and owner != p.track_id:
                put((p.track_id, HAND), c)
    return flags


class BehaviorEngine:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.trackers: dict = {}

    def _params(self, behavior: str) -> tuple:
        c = self.cfg
        if c.mode == "baseline_phone":
            return 0.0, c.phone_release_s
        return {PHONE: (c.phone_min_s, c.phone_release_s),
                GAZE: (c.gaze_min_s, c.gaze_release_s),
                HAND: (c.hand_min_s, c.hand_release_s)}[behavior]

    def step(self, t: float, persons: list, phones: list) -> list:
        flags = frame_flags(self.cfg, persons, phones)
        signals = []

        def emit(key, results):
            for sig, info in results:
                signals.append({"signal": sig, "track_id": key[0], "behavior": key[1], **info})

        for key, conf in flags.items():
            tr = self.trackers.get(key)
            if tr is None:
                tr = self.trackers[key] = EpisodeTracker(*self._params(key[1]), peak_eps=self.cfg.peak_eps)
            emit(key, tr.update(t, True, conf))
        for key, tr in list(self.trackers.items()):
            if key in flags:
                continue
            emit(key, tr.update(t, False))
            if tr.idle:
                del self.trackers[key]
        return signals

    def flagged_behaviors(self) -> dict:
        out: dict = {}
        for (tid, b), tr in self.trackers.items():
            if tr.is_open:
                out.setdefault(tid, set()).add(b)
        return out

    def flush(self) -> list:
        signals = []
        for key, tr in self.trackers.items():
            for sig, info in tr.flush():
                signals.append({"signal": sig, "track_id": key[0], "behavior": key[1], **info})
        self.trackers.clear()
        return signals
