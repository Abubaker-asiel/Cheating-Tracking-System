from __future__ import annotations

import threading
import time
import webbrowser
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtGui import QIcon, QImage
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFileDialog, QHBoxLayout, QLabel, QMainWindow,
                               QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from ..cloud import CloudConfig, open_sync
from ..config import Config
from ..dashboard import serve
from ..db import Database
from .pages import EvidenceDialog, IncidentsPage, MonitorPage, SettingsPage
from .theme import QSS

ICON = Path(__file__).resolve().parent.parent / "assets" / "icon.png"


class Bus(QObject):
    changed = Signal()
    review_requested = Signal(int, str)
    cloud_state = Signal(str, str, str)  # kind, headline, detail


class Worker(QThread):
    frame = Signal(QImage, float, dict)
    alert = Signal(dict)
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, cfg, db, out_dir, path, sync):
        super().__init__()
        self.cfg, self.db, self.out_dir, self.path, self.sync = cfg, db, out_dir, path, sync
        self.stop_flag = threading.Event()

    def run(self):
        try:
            import cv2
            from ..pipeline import Pipeline
            last = [0.0]

            def on_frame(img, t, idx, info):
                now = time.monotonic()
                if now - last[0] < 0.04:  # ~25 fps to the screen at most
                    return
                last[0] = now
                rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                h, w = rgb.shape[:2]
                self.frame.emit(QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy(), t, {**info, "idx": idx})

            def on_alert(e):
                if self.sync:
                    self.sync.enqueue(e["event_id"])
                self.alert.emit(e)

            self.done.emit(Pipeline(self.cfg, self.db, self.out_dir).run(
                self.path, on_frame=on_frame, on_alert=on_alert, stop=self.stop_flag))
        except Exception as exc:  # shown to the user, never swallowed
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class MainWindow(QMainWindow):
    def __init__(self, cfg: Config, db_path: str, out_dir: str, firebase_path: str = "firebase.json"):
        super().__init__()
        self.cfg, self.out_dir, self.firebase_path = cfg, out_dir, firebase_path
        self.db = Database(db_path)
        self.bus = Bus()
        self.sync = None
        self.worker: Worker | None = None
        self._dash = None
        self.setWindowTitle("Invigil")
        self.resize(1440, 900)
        self.setMinimumSize(1180, 720)

        root = QWidget(); root.setObjectName("root")
        lay = QHBoxLayout(root); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        lay.addWidget(self._sidebar())
        self.stack = QStackedWidget(); lay.addWidget(self.stack, 1)
        self.monitor, self.incidents, self.settings = MonitorPage(), IncidentsPage(self.db), SettingsPage()
        for p in (self.monitor, self.incidents, self.settings):
            self.stack.addWidget(p)
        self.setCentralWidget(root)

        self.monitor.upload_requested.connect(self.upload)
        self.monitor.stop_requested.connect(lambda: self.worker and self.worker.stop_flag.set())
        for src in (self.monitor, self.incidents):
            src.review.connect(self.bus.review_requested)
            src.inspect.connect(self.inspect)
        self.bus.review_requested.connect(self.review)
        self.bus.changed.connect(self.incidents.refresh)
        self.bus.changed.connect(lambda: self.monitor.refresh_cards(self.db))
        self.bus.cloud_state.connect(self._cloud_state)
        self.settings.save_cloud.connect(self.save_cloud)
        self.settings.sync_now.connect(self.sync_now)
        self.settings.open_dashboard.connect(self.open_dashboard)

        self.settings.load(CloudConfig.load(firebase_path) if Path(firebase_path).exists() else None)
        self.connect_cloud()
        self.incidents.refresh()
        self._go(0)

    # ---------------------------------------------------------------- layout
    def _sidebar(self) -> QWidget:
        side = QWidget(); side.setObjectName("sidebar"); side.setFixedWidth(236)
        lay = QVBoxLayout(side); lay.setContentsMargins(18, 26, 18, 18); lay.setSpacing(4)
        mark = QLabel("Invigil"); mark.setObjectName("wordmark")
        tag = QLabel("exam review desk"); tag.setObjectName("tagline")
        lay.addWidget(mark); lay.addWidget(tag); lay.addSpacing(26)
        self.nav = QButtonGroup(self); self.nav.setExclusive(True)
        for i, name in enumerate(("Monitor", "Incidents", "Settings")):
            b = QPushButton(name); b.setObjectName("nav"); b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            self.nav.addButton(b, i); lay.addWidget(b)
        self.nav.idClicked.connect(self._go)
        lay.addStretch()
        link = QPushButton("Open web dashboard  ↗"); link.setObjectName("sideLink")
        link.setCursor(Qt.CursorShape.PointingHandCursor); link.clicked.connect(self.open_dashboard)
        lay.addWidget(link)
        self.cloud_chip = QLabel("Firebase · checking"); self.cloud_chip.setObjectName("sideChip")
        lay.addWidget(self.cloud_chip)
        return side

    def _go(self, i: int):
        self.nav.button(i).setChecked(True)
        self.stack.setCurrentIndex(i)
        if i == 1:
            self.incidents.refresh()

    # ---------------------------------------------------------------- run
    def upload(self):
        if self.worker and self.worker.isRunning():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Exam video", "", "Video (*.mp4 *.avi *.mov *.mkv);;All files (*)")
        if path:
            self.start(path)

    def start(self, path: str):
        cfg = replace(self.cfg, mode=self.monitor.mode_value())
        self.monitor.start_run(Path(path).name)
        self.worker = Worker(cfg, self.db, self.out_dir, path, self.sync)
        self.worker.frame.connect(self.monitor.show_frame)
        self.worker.alert.connect(self._on_alert)
        self.worker.done.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _on_alert(self, e: dict):
        self.monitor.add_alert(e)
        self.bus.changed.emit()
        if e["kind"] == "open":
            QApplication.beep()

    def _done(self, s: dict):
        self.monitor.end_run(f"Done: {s['events']} alert(s) in {s['duration_s']:.0f} s of video ({s['tag']}).")
        self.bus.changed.emit()

    def _failed(self, msg: str):
        self.monitor.end_run("Failed.")
        QMessageBox.critical(self, "Processing failed", msg)

    def inspect(self, event_id: int):
        EvidenceDialog(self.db, event_id, self.bus, self).exec()

    def review(self, event_id: int, status: str):
        self.db.set_review(event_id, status)
        if self.sync:
            self.sync.enqueue(event_id)
        self.bus.changed.emit()

    # ---------------------------------------------------------------- cloud
    def connect_cloud(self):
        self.sync, msg = open_sync(self.db, self.firebase_path)
        if self.sync is None:
            kind = "off" if msg == "Not configured" else "error"
            self.bus.cloud_state.emit(kind, "Firebase · off" if kind == "off" else "Firebase · error", msg)
            return
        self.bus.cloud_state.emit("busy", "Firebase · checking", "Testing the connection…")
        sync = self.sync

        def check():
            try:
                sync.backend.check()
                n = sync.enqueue_pending()
                self.bus.cloud_state.emit("ok", "Firebase · connected", msg + (f". Uploading {n} pending incident(s)." if n else "."))
            except Exception as exc:
                self.bus.cloud_state.emit("error", "Firebase · error", f"{type(exc).__name__}: {exc}")

        threading.Thread(target=check, daemon=True).start()

    def _cloud_state(self, kind: str, headline: str, detail: str):
        self.cloud_chip.setText(headline)
        self.settings.set_state(kind, headline.split("· ")[-1].capitalize(), detail)

    def save_cloud(self, cfg: CloudConfig):
        cfg.save(self.firebase_path)
        self.connect_cloud()

    def sync_now(self):
        if not self.sync:
            QMessageBox.information(self, "Firebase", "Firebase is not connected yet. Save your settings first.")
            return
        n = self.sync.enqueue_pending()
        self.bus.cloud_state.emit("ok", "Firebase · connected", f"Queued {n} incident(s) for upload.")

    # ---------------------------------------------------------------- dashboard
    def open_dashboard(self):
        if self._dash is None:
            for port in (8765, 0):
                try:
                    self._dash = serve(self.db, port=port, sync=self.sync, block=False)
                    break
                except OSError:
                    continue
        if self._dash is None:
            QMessageBox.warning(self, "Dashboard", "Could not start the dashboard server.")
            return
        webbrowser.open(f"http://127.0.0.1:{self._dash.server_address[1]}")

    def closeEvent(self, ev):
        if self.worker and self.worker.isRunning():
            self.worker.stop_flag.set()
            self.worker.wait(4000)
        if self.sync:
            self.sync.flush(5)
        super().closeEvent(ev)


def launch(cfg: Config, db_path: str, out_dir: str, firebase_path: str = "firebase.json"):
    import sys
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Invigil")
    app.setStyleSheet(QSS)
    if ICON.exists():
        app.setWindowIcon(QIcon(str(ICON)))  # also sets the Dock icon on macOS
    win = MainWindow(cfg, db_path, out_dir, firebase_path)
    win.show()
    sys.exit(app.exec())
