"""Pure geometry on boxes and COCO-17 keypoints. No model code in here."""
from __future__ import annotations

from dataclasses import dataclass
from math import hypot

import numpy as np

NOSE, L_EYE, R_EYE, L_EAR, R_EAR, L_SH, R_SH, L_WR, R_WR = 0, 1, 2, 3, 4, 5, 6, 9, 10


@dataclass
class Person:
    track_id: int
    box: tuple  # x1, y1, x2, y2
    kpts: np.ndarray | None = None  # (17, 3): x, y, conf

    @property
    def cx(self) -> float:
        return (self.box[0] + self.box[2]) / 2

    @property
    def cy(self) -> float:
        return (self.box[1] + self.box[3]) / 2

    @property
    def w(self) -> float:
        return self.box[2] - self.box[0]

    @property
    def h(self) -> float:
        return self.box[3] - self.box[1]


@dataclass
class Phone:
    box: tuple
    conf: float

    @property
    def center(self) -> tuple:
        return (self.box[0] + self.box[2]) / 2, (self.box[1] + self.box[3]) / 2


def point_in_box(x: float, y: float, box: tuple, margin: float = 0.0) -> bool:
    """margin > 0 grows the box, margin < 0 shrinks it (fraction of w/h per side)."""
    w, h = box[2] - box[0], box[3] - box[1]
    return (box[0] - margin * w <= x <= box[2] + margin * w
            and box[1] - margin * h <= y <= box[3] + margin * h)


def shoulder_width(p: Person, min_conf: float) -> float:
    if p.kpts is not None:
        ls, rs = p.kpts[L_SH], p.kpts[R_SH]
        if ls[2] >= min_conf and rs[2] >= min_conf and abs(ls[0] - rs[0]) > 5:
            return float(abs(ls[0] - rs[0]))
    return 0.6 * p.w


def visible_wrists(p: Person, min_conf: float) -> list:
    if p.kpts is None:
        return []
    return [(float(k[0]), float(k[1]), float(k[2])) for k in (p.kpts[L_WR], p.kpts[R_WR]) if k[2] >= min_conf]


def head_yaw_proxy(p: Person, min_conf: float):
    """Signed yaw proxy in IMAGE coordinates, or None.

    Positive: face turned toward image-right. The value is the nose offset from the
    centre of the visible eyes/ears, divided by shoulder width. It is a proxy, not
    degrees: calibrate the threshold on your own footage. Image-space sign means no
    assumption about which way the camera faces.
    """
    if p.kpts is None:
        return None
    nose = p.kpts[NOSE]
    if nose[2] < min_conf:
        return None
    pts = [p.kpts[i] for i in (L_EYE, R_EYE, L_EAR, R_EAR) if p.kpts[i][2] >= min_conf]
    if not pts:
        return None
    cx = sum(float(k[0]) for k in pts) / len(pts)
    width = shoulder_width(p, min_conf)
    if width <= 1:
        return None
    conf = min([float(nose[2])] + [float(k[2]) for k in pts])
    return (float(nose[0]) - cx) / width, conf


def neighbor_in_direction(p: Person, persons: list, sign: int, max_gap: float):
    """Nearest student roughly in the same row, on the side the head is turned to."""
    best, best_d = None, None
    for o in persons:
        if o.track_id == p.track_id:
            continue
        dx = o.cx - p.cx
        if dx * sign <= 0 or abs(dx) > max_gap * p.w or abs(o.cy - p.cy) > 0.75 * p.h:
            continue
        if best is None or abs(dx) < best_d:
            best, best_d = o, abs(dx)
    return best


def phone_owner(phone: Phone, persons: list, min_conf: float, wrist_frac: float, require_wrist: bool = True):
    """track_id of the student holding the phone, or None."""
    px, py = phone.center
    cands = [p for p in persons if point_in_box(px, py, p.box, 0.1)]
    if not cands:
        return None
    nearest = min(cands, key=lambda p: hypot(px - p.cx, py - p.cy))
    if not require_wrist:
        return nearest.track_id
    best = None
    for p in cands:
        ws = visible_wrists(p, min_conf)
        if not ws:
            continue
        d = min(hypot(px - x, py - y) for x, y, _ in ws) / shoulder_width(p, min_conf)
        if d <= wrist_frac and (best is None or d < best[0]):
            best = (d, p.track_id)
    if best:
        return best[1]
    if all(not visible_wrists(p, min_conf) for p in cands):
        return nearest.track_id  # nobody's hands are visible: fall back to box proximity
    return None


def wrist_owner(x: float, y: float, persons: list):
    """Which student's body region a wrist point falls in (nearest box centre wins)."""
    cands = [p for p in persons if point_in_box(x, y, p.box, -0.05)]
    if not cands:
        return None
    return min(cands, key=lambda p: hypot(x - p.cx, y - p.cy)).track_id
