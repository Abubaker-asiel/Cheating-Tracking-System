"""Video -> detections/tracks -> behaviour events -> screenshots + database rows."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .config import Config
from .db import Database
from .features import Person, Phone
from .rules import BehaviorEngine

# BGR
GREEN, RED, AMBER, WHITE = (91, 143, 47), (43, 67, 216), (0, 165, 240), (255, 255, 255)
PHONE_CLASS = 67  # COCO 'cell phone'
_MODELS: dict = {}


def _model(weights: str):
    if weights not in _MODELS:
        from ultralytics import YOLO
        _MODELS[weights] = YOLO(weights)
    return _MODELS[weights]


def _fmt(t: float) -> str:
    return f"{int(t // 60):02d}:{t % 60:04.1f}"


class Pipeline:
    def __init__(self, cfg: Config, db: Database, shots_root: str | Path = "runs"):
        self.cfg, self.db, self.shots_root = cfg, db, Path(shots_root)

    # -- model calls ----------------------------------------------------
    def _persons(self, frame) -> list:
        c = self.cfg
        r = self.pose.track(frame, persist=True, tracker=c.tracker, conf=c.person_conf,
                            classes=[0], imgsz=c.imgsz, verbose=False)[0]
        if r.boxes is None or len(r.boxes) == 0 or r.boxes.id is None:
            return []  # untracked detections cannot carry an episode
        xyxy = r.boxes.xyxy.cpu().numpy()
        ids = r.boxes.id.int().cpu().tolist()
        kp = r.keypoints.data.cpu().numpy() if r.keypoints is not None else None
        return [Person(ids[i], tuple(float(v) for v in xyxy[i]), kp[i] if kp is not None else None)
                for i in range(len(ids))]

    def _phones(self, frame) -> list:
        c = self.cfg
        r = self.det.predict(frame, conf=c.phone_conf, classes=[PHONE_CLASS], imgsz=c.phone_imgsz, verbose=False)[0]
        if r.boxes is None or len(r.boxes) == 0:
            return []
        xyxy, conf = r.boxes.xyxy.cpu().numpy(), r.boxes.conf.cpu().numpy()
        return [Phone(tuple(float(v) for v in xyxy[i]), float(conf[i])) for i in range(len(conf))]

    # -- drawing ----------------------------------------------------------
    @staticmethod
    def _draw(frame, persons, phones, flagged: dict, t: float):
        import cv2
        for ph in phones:
            x1, y1, x2, y2 = map(int, ph.box)
            cv2.rectangle(frame, (x1, y1), (x2, y2), AMBER, 1)
        for p in persons:
            beh = flagged.get(p.track_id)
            color = RED if beh else GREEN
            x1, y1, x2, y2 = map(int, p.box)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3 if beh else 2)
            label = f"#{p.track_id}" + (" " + ", ".join(sorted(beh)) if beh else "")
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
            cv2.rectangle(frame, (x1, max(0, y1 - th - 8)), (x1 + tw + 8, y1), color, -1)
            cv2.putText(frame, label, (x1 + 4, max(th, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, WHITE, 1, cv2.LINE_AA)
        cv2.putText(frame, _fmt(t), (12, frame.shape[0] - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.7, WHITE, 2, cv2.LINE_AA)
        return frame

    # -- main loop --------------------------------------------------------
    def run(self, video_path, session: str | None = None, tag: str | None = None,
            on_frame=None, on_alert=None, stop=None, max_frames: int | None = None) -> dict:
        import cv2
        cfg = self.cfg
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise IOError(f"cannot open video: {video_path}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        session = session or Path(video_path).stem
        tag = tag or ("baseline" if cfg.mode == "baseline_phone" else "rules")

        self.pose, self.det = _model(cfg.pose_weights), _model(cfg.detector_weights)
        self.pose.predictor = None  # fresh tracker state for every video
        run_id = self.db.create_run(session, tag, video_path, fps, cfg.model_version, cfg.to_dict())
        shots = self.shots_root / session / tag
        shots.mkdir(parents=True, exist_ok=True)

        engine = BehaviorEngine(cfg)
        event_ids: dict = {}
        best: dict = {}
        n_events = 0
        idx, last_vis, last_t = -1, None, 0.0

        def handle(sig: dict, vis):
            nonlocal n_events
            key = (sig["track_id"], sig["behavior"])
            stem = f"t{sig['t_start']:08.2f}_id{key[0]}_{key[1]}"
            if sig["signal"] == "open":
                path = shots / f"{stem}_onset.jpg"
                cv2.imwrite(str(path), vis)
                event_ids[key] = self.db.add_event(run_id, key[0], key[1], sig["t_start"], sig["peak_conf"], str(path))
                best[key] = vis.copy()
                n_events += 1
                if on_alert:
                    on_alert({**self.db.get_event(event_ids[key]), "kind": "open"})
            elif sig["signal"] == "peak" and key in event_ids:
                best[key] = vis.copy()
            elif sig["signal"] == "close" and key in event_ids:
                path = shots / f"{stem}_best.jpg"
                cv2.imwrite(str(path), best.pop(key, vis))
                eid = event_ids.pop(key)
                self.db.close_event(eid, sig["t_end"], sig["peak_conf"], str(path))
                if on_alert:
                    on_alert({**self.db.get_event(eid), "kind": "close"})

        try:
            while True:
                ok, frame = cap.read()
                if not ok or (max_frames is not None and idx + 1 >= max_frames):
                    break
                idx += 1
                if idx % cfg.frame_stride:
                    continue
                t = idx / fps
                persons, phones = self._persons(frame), self._phones(frame)
                signals = engine.step(t, persons, phones)
                vis = self._draw(frame.copy(), persons, phones, engine.flagged_behaviors(), t)
                for s in signals:
                    handle(s, vis)
                last_vis, last_t = vis, t
                if on_frame:
                    flagged = engine.flagged_behaviors()
                    on_frame(vis, t, idx, {"persons": len(persons), "flagged": len(flagged), "total": total})
                if stop is not None and stop.is_set():
                    break
        finally:
            if last_vis is not None:
                for s in engine.flush():
                    handle(s, last_vis)
            cap.release()
            self.db.finish_run(run_id, idx + 1, (idx + 1) / fps)
        return {"run_id": run_id, "session": session, "tag": tag, "events": n_events,
                "frames": idx + 1, "duration_s": (idx + 1) / fps, "fps": fps}
