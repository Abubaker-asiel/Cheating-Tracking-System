"""Push incidents (and their screenshots) to Firebase without ever blocking the video loop.

firebase.json (see firebase.example.json):
  mode "storage"          screenshots go to Cloud Storage, metadata to Firestore
  mode "firestore_inline" no Storage bucket needed: a downsized JPEG is embedded in the Firestore
                          document (fine for review thumbnails; Firestore docs are capped at 1 MiB)

Every job is idempotent: it uploads only files not uploaded yet and rewrites the document, so
re-queueing after a crash, an offline period or a review change is always safe.
"""
from __future__ import annotations

import base64
import json
import queue
import re
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .db import Database


@dataclass
class CloudConfig:
    credentials: str = "serviceAccountKey.json"
    storage_bucket: str = ""
    mode: str = "storage"            # storage | firestore_inline
    collection: str = "incidents"
    prefix: str = "invigil"

    @classmethod
    def load(cls, path: str | Path = "firebase.json") -> "CloudConfig | None":
        p = Path(path)
        if not p.exists():
            return None
        data = json.loads(p.read_text())
        known = set(cls.__dataclass_fields__)
        extra = set(data) - known
        if extra:
            raise ValueError(f"unknown firebase.json keys: {sorted(extra)}")
        return cls(**data)

    def save(self, path: str | Path = "firebase.json"):
        Path(path).write_text(json.dumps(asdict(self), indent=2) + "\n")


class FirebaseBackend:
    def __init__(self, cfg: CloudConfig):
        import firebase_admin
        from firebase_admin import credentials, firestore, storage

        self.cfg = cfg
        if not Path(cfg.credentials).exists():
            raise FileNotFoundError(f"service account key not found: {cfg.credentials}")
        if cfg.mode == "storage" and not cfg.storage_bucket:
            raise ValueError("storage_bucket is required when mode is 'storage'")
        for app in list(firebase_admin._apps.values()):  # settings may have changed since the last connect
            firebase_admin.delete_app(app)
        opts = {"storageBucket": cfg.storage_bucket} if cfg.mode == "storage" else None
        firebase_admin.initialize_app(credentials.Certificate(cfg.credentials), opts)
        self._fs = firestore
        self.db = firestore.client()
        self.bucket = storage.bucket() if cfg.mode == "storage" else None

    def check(self) -> str:
        ref = self.db.collection(self.cfg.collection).document("_invigil_ping")
        ref.set({"ts": self._fs.SERVER_TIMESTAMP})
        ref.delete()
        if self.bucket is not None:
            list(self.bucket.list_blobs(max_results=1))
        return "ok"

    def push(self, doc_id: str, data: dict, files: dict) -> dict:
        refs = {}
        for key, path in files.items():
            if self.cfg.mode == "storage":
                remote = f"{self.cfg.prefix}/{doc_id}/{key}.jpg"
                self.bucket.blob(remote).upload_from_filename(path, content_type="image/jpeg")
                refs[key] = f"gs://{self.bucket.name}/{remote}"
            else:
                data[f"{key}_b64"] = _inline_jpeg(path)
                refs[key] = "firestore:inline"
        data.update({f"{k}_ref": v for k, v in refs.items()})
        self.db.collection(self.cfg.collection).document(doc_id).set(data, merge=True)
        return refs


def _inline_jpeg(path: str, max_side: int = 720, quality: int = 70) -> str:
    import cv2
    img = cv2.imread(path)
    h, w = img.shape[:2]
    k = min(1.0, max_side / max(h, w))
    if k < 1:
        img = cv2.resize(img, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError(f"could not encode {path}")
    return base64.b64encode(buf.tobytes()).decode()


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)[:80]


class CloudSync:
    """Background worker. backend needs push(doc_id, data, files) -> {key: ref}."""

    def __init__(self, db: Database, backend, on_error=None):
        self.db, self.backend, self.on_error = db, backend, on_error
        self.q: queue.Queue = queue.Queue()
        threading.Thread(target=self._loop, daemon=True, name="invigil-cloud").start()

    def enqueue(self, event_id: int):
        self.q.put(event_id)

    def enqueue_pending(self) -> int:
        ids = self.db.unsynced_event_ids()
        for i in ids:
            self.q.put(i)
        return len(ids)

    def pending(self) -> int:
        return self.q.unfinished_tasks

    def flush(self, timeout: float = 120.0) -> bool:
        end = time.monotonic() + timeout
        while self.q.unfinished_tasks and time.monotonic() < end:
            time.sleep(0.1)
        return self.q.unfinished_tasks == 0

    def _loop(self):
        while True:
            eid = self.q.get()
            try:
                self._sync(eid)
            except Exception as exc:  # recorded on the row, retried by enqueue_pending()
                msg = f"{type(exc).__name__}: {exc}"[:300]
                self.db.set_cloud(eid, cloud_error=msg)
                if self.on_error:
                    self.on_error(eid, msg)
            finally:
                self.q.task_done()

    def _sync(self, eid: int):
        e = self.db.get_event(eid)
        files = {}
        for key, shot, done in (("onset", e["onset_shot"], e["onset_cloud"]), ("best", e["best_shot"], e["best_cloud"])):
            if shot and not done and Path(shot).exists():
                files[key] = shot
        doc_id = f"{_safe(e['session'])}-{e['run_id']}-{eid}"
        doc = {"event_id": eid, "session": e["session"], "run_tag": e["tag"], "student_id": e["track_id"],
               "behavior": e["behavior"], "t_start": e["t_start"], "t_end": e["t_end"],
               "signal_strength": e["peak_conf"], "review_status": e["review_status"],
               "reviewed_at": e["reviewed_at"], "created_at": e["created_at"], "model_version": e["model_version"]}
        refs = self.backend.push(doc_id, doc, files)
        fields = {"cloud_error": None}
        if "onset" in refs:
            fields["onset_cloud"] = refs["onset"]
        if "best" in refs:
            fields["best_cloud"] = refs["best"]
        self.db.set_cloud(eid, **fields)
        if e["t_end"] is not None:  # an event that is still open stays pending until it closes
            self.db.mark_synced(eid, e["review_status"])


def open_sync(db: Database, config_path: str | Path = "firebase.json"):
    """-> (CloudSync | None, message). Never raises: cloud problems must not stop monitoring."""
    try:
        cfg = CloudConfig.load(config_path)
        if cfg is None:
            return None, "Not configured"
        backend = FirebaseBackend(cfg)
        return CloudSync(db, backend), f"Connected ({cfg.mode})"
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
