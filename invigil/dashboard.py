"""Local web dashboard: stdlib HTTP server + one static page. No Node, no extra dependencies.

    python -m invigil dashboard            # http://127.0.0.1:8765

Reads the same SQLite file as the desktop app. Review buttons write to it directly.
"""
from __future__ import annotations

import csv
import io
import json
import mimetypes
import threading
import webbrowser
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .db import Database
from .labels import BEHAVIOR_LABELS, STATUS_LABELS, colors, label

WEB = Path(__file__).parent / "web"
ASSETS = Path(__file__).parent / "assets"


def _cloud_state(e: dict) -> str:
    if e.get("cloud_synced"):
        return "synced"
    if e.get("cloud_error"):
        return "error"
    return "pending" if (e.get("onset_cloud") or e.get("best_cloud")) else "local"


def incident_row(e: dict) -> dict:
    strong, soft = colors(e["behavior"])
    return {
        "id": e["event_id"], "session": e["session"], "tag": e["tag"], "student": e["track_id"],
        "behavior": e["behavior"], "behavior_label": label(e["behavior"]), "color": strong, "soft": soft,
        "t_start": e["t_start"], "t_end": e["t_end"], "signal": e["peak_conf"],
        "status": e["review_status"], "status_label": STATUS_LABELS.get(e["review_status"], e["review_status"]),
        "created_at": e["created_at"], "reviewed_at": e["reviewed_at"], "cloud": _cloud_state(e),
        "has_best": bool(e["best_shot"]), "has_onset": bool(e["onset_shot"]),
    }


def filtered(db: Database, status="", behavior="", session="", q="", limit=500) -> list:
    out = []
    for e in db.events(newest_first=True):
        if status and e["review_status"] != status:
            continue
        if behavior and e["behavior"] != behavior:
            continue
        if session and e["session"] != session:
            continue
        if q and q.lower() not in f"{e['session']} student {e['track_id']} {label(e['behavior'])}".lower():
            continue
        out.append(e)
        if len(out) >= limit:
            break
    return out


def summary(db: Database, session: str = "") -> dict:
    events = [e for e in db.events() if not session or e["session"] == session]
    status = Counter(e["review_status"] for e in events)
    reviewed = status["confirmed"] + status["dismissed"]
    runs = [r for r in db.runs() if not session or r["session"] == session]
    by_b = Counter(e["behavior"] for e in events)
    per_min = Counter(int(e["t_start"] // 60) for e in events)
    span = (max(per_min) + 1) if per_min else 0
    return {
        "kpis": {"total": len(events), "pending": status["pending"], "confirmed": status["confirmed"],
                 "dismissed": status["dismissed"],
                 "false_alarm_rate": (status["dismissed"] / reviewed) if reviewed else None,
                 "hours": sum((r["duration_s"] or 0) for r in runs) / 3600,
                 "per_hour": (len(events) / (sum((r["duration_s"] or 0) for r in runs) / 3600))
                 if sum((r["duration_s"] or 0) for r in runs) else None},
        "by_behavior": [{"key": k, "label": label(k), "color": colors(k)[0], "count": by_b.get(k, 0)}
                        for k in list(BEHAVIOR_LABELS) + [b for b in by_b if b not in BEHAVIOR_LABELS]],
        "timeline": [{"minute": m, "count": per_min.get(m, 0)} for m in range(span)],
        "cloud": dict(Counter(_cloud_state(e) for e in events)),
        "sessions": sorted({r["session"] for r in db.runs()}),
        "behaviors": [{"key": k, "label": v} for k, v in BEHAVIOR_LABELS.items()],
    }


def export_csv(rows: list) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "session", "student", "behavior", "t_start", "t_end", "signal", "status", "created_at"])
    for e in rows:
        w.writerow([e["event_id"], e["session"], e["track_id"], e["behavior"], e["t_start"], e["t_end"],
                    e["peak_conf"], e["review_status"], e["created_at"]])
    return buf.getvalue()


def make_handler(db: Database, sync=None):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # keep the console quiet
            pass

        def _send(self, body: bytes, ctype: str, code: int = 200):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200):
            self._send(json.dumps(obj).encode(), "application/json", code)

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path in ("/", "/index.html"):
                    return self._send((WEB / "index.html").read_bytes(), "text/html; charset=utf-8")
                if u.path == "/icon.png":
                    return self._send((ASSETS / "icon.png").read_bytes(), "image/png")
                if u.path == "/api/summary":
                    return self._json(summary(db, q.get("session", "")))
                if u.path == "/api/incidents":
                    rows = filtered(db, q.get("status", ""), q.get("behavior", ""), q.get("session", ""),
                                    q.get("q", ""), int(q.get("limit", 500)))
                    return self._json([incident_row(e) for e in rows])
                if u.path == "/api/export.csv":
                    rows = filtered(db, q.get("status", ""), q.get("behavior", ""), q.get("session", ""), q.get("q", ""), 100000)
                    return self._send(export_csv(rows).encode(), "text/csv; charset=utf-8")
                if u.path.startswith("/shot/"):
                    _, _, eid, kind = u.path.split("/")
                    e = db.get_event(int(eid))
                    path = e["best_shot"] if kind == "best" and e["best_shot"] else e["onset_shot"]
                    if not path or not Path(path).is_file():
                        return self._send(b"no screenshot", "text/plain", 404)
                    return self._send(Path(path).read_bytes(), mimetypes.guess_type(path)[0] or "image/jpeg")
            except (IndexError, ValueError):
                return self._send(b"not found", "text/plain", 404)
            self._send(b"not found", "text/plain", 404)

        def do_POST(self):
            if urlparse(self.path).path != "/api/review":
                return self._send(b"not found", "text/plain", 404)
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                eid, status = int(body["event_id"]), body["status"]
                db.set_review(eid, status)
                if sync:
                    sync.enqueue(eid)
                self._json(incident_row(db.get_event(eid)))
            except (KeyError, ValueError, IndexError, json.JSONDecodeError) as exc:
                self._json({"error": str(exc)}, 400)

    return H


def serve(db: Database, port: int = 8765, host: str = "127.0.0.1", sync=None, block: bool = True, open_browser: bool = False):
    """Bound to localhost by default: exam evidence should not be reachable from the network."""
    server = ThreadingHTTPServer((host, port), make_handler(db, sync))
    url = f"http://{host}:{server.server_address[1]}"
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    if block:
        print(f"Invigil dashboard on {url}  (Ctrl+C to stop)")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        return server
    threading.Thread(target=server.serve_forever, daemon=True, name="invigil-dashboard").start()
    return server
