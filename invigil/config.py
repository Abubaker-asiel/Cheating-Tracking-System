"""All tunable numbers live here so a run can be reproduced from config.yaml."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from pathlib import Path

import yaml


@dataclass
class Config:
    # --- models -------------------------------------------------------
    pose_weights: str = "yolov8n-pose.pt"      # persons + 17 keypoints
    detector_weights: str = "yolov8n.pt"       # COCO detector, used for 'cell phone'
    tracker: str = "bytetrack.yaml"            # or botsort.yaml
    imgsz: int = 960
    phone_imgsz: int = 1280                    # phones are small, give them pixels
    person_conf: float = 0.40
    phone_conf: float = 0.25
    kp_conf: float = 0.35                      # min keypoint confidence to be used
    frame_stride: int = 2                      # process every Nth frame
    model_version: str = "yolov8n-pose+yolov8n/bytetrack"

    # --- behaviour rules ---------------------------------------------
    mode: str = "rules"                        # rules | baseline_phone

    # PHONE_USE: phone near a student's wrist for phone_min_s
    phone_min_s: float = 1.5
    phone_release_s: float = 1.0               # gap tolerated before the event closes
    phone_wrist_frac: float = 0.8              # max phone-wrist distance in shoulder widths

    # GAZE_NEIGHBOR: head turned toward a seated neighbour for gaze_min_s
    yaw_threshold: float = 0.20                # |nose offset| / shoulder width. CALIBRATE.
    gaze_min_s: float = 3.0
    gaze_release_s: float = 1.0
    neighbor_max_gap: float = 2.5              # neighbour must be within N box-widths

    # HAND_TO_NEIGHBOR: a wrist inside another student's box for hand_min_s
    hand_min_s: float = 1.0
    hand_release_s: float = 0.8

    # --- events -------------------------------------------------------
    peak_eps: float = 0.02                     # confidence gain needed to replace best screenshot

    @classmethod
    def load(cls, path: str | Path | None = None, **overrides) -> "Config":
        data: dict = {}
        if path:
            data = yaml.safe_load(Path(path).read_text()) or {}
        data.update({k: v for k, v in overrides.items() if v is not None})
        unknown = set(data) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"unknown config keys: {sorted(unknown)}")
        return cls(**data)

    def to_dict(self) -> dict:
        return asdict(self)
