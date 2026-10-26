from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QFileDialog, QFormLayout, QFrame, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QProgressBar, QPushButton,
                               QScrollArea, QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..cloud import CloudConfig
from ..labels import BEHAVIOR_LABELS, STATUS_LABELS, colors, label
from .theme import P
from .widgets import (AlertCard, Card, Kpi, VideoView, behavior_chip, chip, fmt_time, fmt_when, segmented, status_chip,
                      strength_cell, thumb, wrap)


def _title(title: str, sub: str) -> QVBoxLayout:
    box = QVBoxLayout()
    box.setSpacing(2)
    h = QLabel(title); h.setObjectName("h1")
    s = QLabel(sub); s.setObjectName("muted"); s.setWordWrap(True)
    box.addWidget(h); box.addWidget(s)
    return box


def _page_layout(page: QWidget) -> QVBoxLayout:
    page.setObjectName("page")
    lay = QVBoxLayout(page)
    lay.setContentsMargins(32, 28, 32, 24)
    lay.setSpacing(18)
    return lay


# ------------------------------------------------------------------ monitor
class MonitorPage(QWidget):
    upload_requested = Signal()
    stop_requested = Signal()
    review = Signal(int, str)
    inspect = Signal(int)

    def __init__(self):
        super().__init__()
        lay = _page_layout(self)
        head = QHBoxLayout()
        head.addLayout(_title("Monitor", "Upload an exam recording. Students are tracked; flagged moments become alerts you can review."), 1)
        self.mode = QComboBox()
        self.mode.addItem("Rules (recommended)", "rules")
        self.mode.addItem("Baseline: any phone = alert", "baseline_phone")
        self.btn_stop = QPushButton("Stop"); self.btn_stop.setObjectName("ghost"); self.btn_stop.setEnabled(False)
        self.btn_upload = QPushButton("Upload video"); self.btn_upload.setObjectName("primary")
        self.btn_upload.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_upload.clicked.connect(self.upload_requested)
        self.btn_stop.clicked.connect(self.stop_requested)
        for w in (self.mode, self.btn_stop, self.btn_upload):
            head.addWidget(w, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(head)

        krow = QHBoxLayout(); krow.setSpacing(14)
        self.k_students = Kpi("Students tracked", P["ink"])
        self.k_flagged = Kpi("Flagged right now", P["red"])
        self.k_alerts = Kpi("Alerts this run", P["amber"])
        self.k_clock = Kpi("Video position", P["green"])
        for k in (self.k_students, self.k_flagged, self.k_alerts, self.k_clock):
            krow.addWidget(k)
        lay.addLayout(krow)
        self._reset_kpis()

        body = QHBoxLayout(); body.setSpacing(16)
        left = Card(); ll = QVBoxLayout(left); ll.setContentsMargins(14, 14, 14, 12); ll.setSpacing(10)
        self.video = VideoView(); ll.addWidget(self.video, 1)
        self.progress = QProgressBar(); self.progress.setTextVisible(False); self.progress.setRange(0, 1000)
        ll.addWidget(self.progress)
        self.status = QLabel("Ready."); self.status.setObjectName("muted"); ll.addWidget(self.status)
        body.addWidget(left, 1)

        right = Card(); right.setFixedWidth(440)
        rl = QVBoxLayout(right); rl.setContentsMargins(16, 14, 16, 14); rl.setSpacing(10)
        hrow = QHBoxLayout()
        t = QLabel("Live alerts"); t.setObjectName("h2"); hrow.addWidget(t); hrow.addStretch()
        self.count = QLabel("0"); self.count.setObjectName("muted"); hrow.addWidget(self.count)
        rl.addLayout(hrow)
        self.empty = QLabel("Nothing flagged yet.\nAlerts appear here the moment they happen.")
        self.empty.setObjectName("muted"); self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rl.addWidget(self.empty, 1)
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True); self.scroll.hide()
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QWidget(); self.cards = QVBoxLayout(host); self.cards.setContentsMargins(0, 0, 4, 0); self.cards.setSpacing(10)
        self.cards.addStretch()
        self.scroll.setWidget(host)
        rl.addWidget(self.scroll, 1)
        body.addWidget(right)
        lay.addLayout(body, 1)
        self._cards: dict = {}

    def _reset_kpis(self):
        self.k_students.set("–", "in view"); self.k_flagged.set("–", "confirmed episodes")
        self.k_alerts.set(0, "since upload"); self.k_clock.set("00:00", "of video")

    def mode_value(self) -> str:
        return self.mode.currentData()

    def start_run(self, name: str):
        for c in self._cards.values():
            c.deleteLater()
        self._cards.clear()
        self.count.setText("0"); self.empty.show(); self.scroll.hide()
        self._reset_kpis()
        self.progress.setValue(0)
        self.status.setText(f"Loading models and processing {name} …")
        self.btn_upload.setEnabled(False); self.btn_stop.setEnabled(True); self.mode.setEnabled(False)

    def end_run(self, text: str):
        self.btn_upload.setEnabled(True); self.btn_stop.setEnabled(False); self.mode.setEnabled(True)
        self.status.setText(text)

    def show_frame(self, img, t: float, info: dict):
        self.video.show_image(img)
        self.k_students.set(info["persons"], "in view")
        self.k_flagged.set(info["flagged"], "confirmed episodes")
        self.k_clock.set(fmt_time(t)[:5], "of video")
        if info.get("total"):
            self.progress.setValue(int(1000 * min(1.0, info["idx"] / info["total"])))

    def add_alert(self, e: dict):
        if e["event_id"] in self._cards:
            self._cards[e["event_id"]].set_event(e)
            return
        card = AlertCard(e)
        card.review.connect(self.review); card.inspect.connect(self.inspect)
        self.cards.insertWidget(0, card)
        self._cards[e["event_id"]] = card
        self.empty.hide(); self.scroll.show()
        self.count.setText(str(len(self._cards)))
        self.k_alerts.set(len(self._cards), "since upload")
        card.flash()

    def refresh_cards(self, db):
        for eid, card in self._cards.items():
            card.set_event(db.get_event(eid))


# ------------------------------------------------------------------ incidents
class IncidentsPage(QWidget):
    inspect = Signal(int)
    review = Signal(int, str)
    COLS = ["EVIDENCE", "STUDENT", "BEHAVIOR", "SIGNAL", "VIDEO TIME", "DETECTED", "STATUS", ""]
    LIMIT = 200

    def __init__(self, db):
        super().__init__()
        self.db = db
        lay = _page_layout(self)
        lay.addLayout(_title("Incidents", "Every flag is a lead for a human reviewer, not a verdict. Open the evidence, then confirm or dismiss."))
        bar = QHBoxLayout(); bar.setSpacing(10)
        self.seg, self.grp = segmented(["All", "Needs review", "Confirmed", "False alarms"])
        self.grp.idClicked.connect(lambda _i: self.refresh())
        bar.addWidget(self.seg)
        self.beh = QComboBox(); self.beh.addItem("All behaviors", "")
        for k, v in BEHAVIOR_LABELS.items():
            self.beh.addItem(v, k)
        self.beh.currentIndexChanged.connect(lambda _i: self.refresh())
        bar.addWidget(self.beh)
        self.q = QLineEdit(); self.q.setPlaceholderText("Search student or session…"); self.q.setFixedWidth(240)
        self.q.textChanged.connect(lambda _t: self.refresh())
        bar.addWidget(self.q)
        bar.addStretch()
        self.note = QLabel(""); self.note.setObjectName("muted"); bar.addWidget(self.note)
        lay.addLayout(bar)

        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.verticalHeader().setDefaultSectionSize(76)
        hh = self.table.horizontalHeader()
        hh.setHighlightSections(False)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for i, w in enumerate((124, 100, 176, 126, 92, 130, 146)):
            self.table.setColumnWidth(i, w)
        hh.setSectionResizeMode(len(self.COLS) - 1, QHeaderView.ResizeMode.Stretch)
        self.table.cellDoubleClicked.connect(lambda r, _c: self._open_row(r))
        lay.addWidget(self.table, 1)
        self.empty = QLabel("No incidents match.\nProcess a video on the Monitor page and they will show up here.")
        self.empty.setObjectName("muted"); self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.empty)

    def _status(self) -> str:
        return ("", "pending", "confirmed", "dismissed")[self.grp.checkedId()]

    def _open_row(self, r: int):
        it = self.table.item(r, 1)
        if it:
            self.inspect.emit(it.data(Qt.ItemDataRole.UserRole))

    def refresh(self):
        status, beh, q = self._status(), self.beh.currentData(), self.q.text().strip().lower()
        rows = []
        for e in self.db.events(newest_first=True):
            if status and e["review_status"] != status:
                continue
            if beh and e["behavior"] != beh:
                continue
            if q and q not in f"{e['session']} student {e['track_id']} {label(e['behavior'])}".lower():
                continue
            rows.append(e)
        total = len(rows)
        rows = rows[: self.LIMIT]
        self.note.setText(f"Showing latest {self.LIMIT} of {total}" if total > self.LIMIT else f"{total} incident{'s' if total != 1 else ''}")
        self.empty.setVisible(not rows)
        self.table.setVisible(bool(rows))
        self.table.setUpdatesEnabled(False)
        self.table.clearContents()
        self.table.setRowCount(len(rows))
        for r, e in enumerate(rows):
            pic = QLabel(); pic.setPixmap(thumb(e["best_shot"] or e["onset_shot"], 104, 64))
            self.table.setCellWidget(r, 0, wrap(pic, (10, 0, 4, 0)))
            who = QTableWidgetItem(f"Student #{e['track_id']}")
            who.setData(Qt.ItemDataRole.UserRole, e["event_id"])
            f = who.font(); f.setBold(True); who.setFont(f)
            self.table.setItem(r, 1, who)
            self.table.setCellWidget(r, 2, wrap(behavior_chip(e["behavior"])))
            self.table.setCellWidget(r, 3, strength_cell(e["peak_conf"], colors(e["behavior"])[0]))
            self.table.setItem(r, 4, QTableWidgetItem(fmt_time(e["t_start"])))
            self.table.setItem(r, 5, QTableWidgetItem(fmt_when(e["created_at"])))
            self.table.setCellWidget(r, 6, wrap(status_chip(e["review_status"])))
            self.table.setCellWidget(r, 7, self._actions(e))
        self.table.setUpdatesEnabled(True)

    def _actions(self, e: dict) -> QWidget:
        box = QWidget()
        lay = QHBoxLayout(box); lay.setContentsMargins(8, 0, 12, 0); lay.setSpacing(6)
        lay.addStretch()
        eid = e["event_id"]
        b_view = QPushButton("Inspect"); b_view.setObjectName("mini")
        b_view.clicked.connect(lambda: self.inspect.emit(eid))
        lay.addWidget(b_view)
        if e["review_status"] == "pending":
            for text, tip, status in (("✓", "Confirm incident", "confirmed"), ("✕", "Dismiss as false alarm", "dismissed")):
                b = QPushButton(text); b.setObjectName("mini"); b.setToolTip(tip); b.setFixedWidth(32)
                b.clicked.connect(lambda _c=False, s=status: self.review.emit(eid, s))
                lay.addWidget(b)
        return box


# ------------------------------------------------------------------ evidence
class EvidenceDialog(QDialog):
    def __init__(self, db, event_id: int, bus, parent=None):
        super().__init__(parent)
        self.db, self.event_id, self.bus = db, event_id, bus
        self.setWindowTitle("Evidence")
        self.setMinimumSize(1060, 600)
        self.shot = "best"
        lay = QHBoxLayout(self); lay.setContentsMargins(24, 24, 24, 24); lay.setSpacing(24)
        left = QVBoxLayout(); left.setSpacing(12)
        self.seg, self.grp = segmented(["Peak frame", "Onset"])
        self.grp.idClicked.connect(self._pick)
        left.addWidget(self.seg, 0, Qt.AlignmentFlag.AlignLeft)
        self.img = QLabel(); self.img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.img.setStyleSheet("background:#14171A;border-radius:12px;color:#8B9096;")
        left.addWidget(self.img, 1)
        lay.addLayout(left, 1)

        right = QVBoxLayout(); right.setSpacing(10)
        self.title = QLabel(); self.title.setObjectName("h1")
        self.title.setWordWrap(True)
        right.addWidget(self.title)
        self.chip_row = QHBoxLayout(); right.addLayout(self.chip_row)
        self.form = QFormLayout(); self.form.setHorizontalSpacing(16); self.form.setVerticalSpacing(10)
        right.addLayout(self.form)
        right.addStretch()
        note = QLabel("Signal strength is a heuristic score, not a probability. Judge the frame, not the number.")
        note.setObjectName("muted"); note.setWordWrap(True)
        right.addWidget(note)
        self.btn_ok = QPushButton("Confirm incident"); self.btn_ok.setObjectName("primary")
        self.btn_no = QPushButton("Dismiss as false alarm"); self.btn_no.setObjectName("ghost")
        close = QPushButton("Close"); close.setObjectName("ghost")
        self.btn_ok.clicked.connect(lambda: self.bus.review_requested.emit(self.event_id, "confirmed"))
        self.btn_no.clicked.connect(lambda: self.bus.review_requested.emit(self.event_id, "dismissed"))
        close.clicked.connect(self.accept)
        for b in (self.btn_ok, self.btn_no, close):
            right.addWidget(b)
        side = QWidget(); side.setLayout(right); side.setFixedWidth(300)
        lay.addWidget(side)
        self.bus.changed.connect(self.reload)
        self.reload()

    def _pick(self, i: int):
        self.shot = ("best", "onset")[i]
        self._image()

    def _image(self):
        e = self.db.get_event(self.event_id)
        path = (e["best_shot"] if self.shot == "best" and e["best_shot"] else e["onset_shot"])
        pm = QPixmap(path) if path and Path(path).exists() else QPixmap()
        if pm.isNull():
            self.img.setText("No screenshot saved for this event.")
        else:
            self.img.setPixmap(pm.scaled(self.img.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._image()

    def showEvent(self, ev):
        super().showEvent(ev)
        self._image()

    def reload(self):
        e = self.db.get_event(self.event_id)
        self.title.setText(label(e["behavior"]))
        while self.chip_row.count():
            it = self.chip_row.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.chip_row.addWidget(status_chip(e["review_status"])); self.chip_row.addStretch()
        while self.form.rowCount():
            self.form.removeRow(0)
        cloud = ("Saved to Firebase" if e["cloud_synced"] else "Upload failed, will retry" if e["cloud_error"]
                 else "Waiting to upload" if (e["onset_cloud"] or e["best_cloud"]) else "Local only")
        for k, v in (("Student", f"#{e['track_id']} (tracker ID)"), ("Session", f"{e['session']} · {e['tag']}"),
                     ("Video time", f"{fmt_time(e['t_start'])} → {fmt_time(e['t_end'])}"),
                     ("Signal", "–" if e["peak_conf"] is None else f"{e['peak_conf']:.2f}"),
                     ("Detected", (e["created_at"] or "").replace("T", " ")), ("Cloud", cloud)):
            k_l = QLabel(k); k_l.setObjectName("muted")
            v_l = QLabel(v); v_l.setWordWrap(True)
            self.form.addRow(k_l, v_l)
        self.btn_ok.setEnabled(e["review_status"] != "confirmed"); self.btn_no.setEnabled(e["review_status"] != "dismissed")
        self._image()


# ------------------------------------------------------------------ settings
class SettingsPage(QWidget):
    save_cloud = Signal(object)
    sync_now = Signal()
    open_dashboard = Signal()

    def __init__(self):
        super().__init__()
        lay = _page_layout(self)
        lay.addLayout(_title("Settings", "Where evidence is stored, and how to reach the web dashboard."))

        fb = Card(); fl = QVBoxLayout(fb); fl.setContentsMargins(22, 18, 22, 20); fl.setSpacing(12)
        row = QHBoxLayout()
        t = QLabel("Firebase"); t.setObjectName("h2"); row.addWidget(t)
        self.state = chip("Off", "#555B5F", "#E9E5DA"); row.addWidget(self.state); row.addStretch()
        fl.addLayout(row)
        self.detail = QLabel(""); self.detail.setObjectName("muted"); self.detail.setWordWrap(True)
        fl.addWidget(self.detail)
        grid = QGridLayout(); grid.setHorizontalSpacing(14); grid.setVerticalSpacing(10)
        self.key = QLineEdit(); self.key.setPlaceholderText("serviceAccountKey.json")
        browse = QPushButton("Browse…"); browse.setObjectName("ghost"); browse.clicked.connect(self._browse)
        self.mode = QComboBox(); self.mode.addItem("Cloud Storage + Firestore", "storage"); self.mode.addItem("Firestore only (no Storage bucket)", "firestore_inline")
        self.bucket = QLineEdit(); self.bucket.setPlaceholderText("your-project-id.firebasestorage.app")
        self.coll = QLineEdit("incidents")
        for r, (name, w, extra) in enumerate((("Service account key", self.key, browse), ("Photos", self.mode, None),
                                              ("Storage bucket", self.bucket, None), ("Firestore collection", self.coll, None))):
            lab = QLabel(name); lab.setObjectName("muted")
            grid.addWidget(lab, r, 0); grid.addWidget(w, r, 1, 1, 1 if extra else 2)
            if extra:
                grid.addWidget(extra, r, 2)
        grid.setColumnStretch(1, 1)
        fl.addLayout(grid)
        self.mode.currentIndexChanged.connect(lambda _i: self.bucket.setEnabled(self.mode.currentData() == "storage"))
        btns = QHBoxLayout()
        save = QPushButton("Save and connect"); save.setObjectName("primary"); save.clicked.connect(self._save)
        sync = QPushButton("Upload pending now"); sync.setObjectName("ghost"); sync.clicked.connect(self.sync_now)
        btns.addWidget(save); btns.addWidget(sync); btns.addStretch()
        fl.addLayout(btns)
        hint = QLabel("Firebase console → Project settings → Service accounts → Generate new private key. "
                      "Keep that file out of git. Screenshots are exam evidence: leave the bucket private.")
        hint.setObjectName("muted"); hint.setWordWrap(True)
        fl.addWidget(hint)
        lay.addWidget(fb)

        dash = Card(); dl = QHBoxLayout(dash); dl.setContentsMargins(22, 18, 22, 18)
        col = QVBoxLayout()
        t2 = QLabel("Web dashboard"); t2.setObjectName("h2"); col.addWidget(t2)
        d2 = QLabel("Charts, review queue and evidence viewer in your browser. Served from this computer only."); d2.setObjectName("muted"); col.addWidget(d2)
        dl.addLayout(col, 1)
        b = QPushButton("Open dashboard"); b.setObjectName("ghost"); b.clicked.connect(self.open_dashboard)
        dl.addWidget(b)
        lay.addWidget(dash)
        lay.addStretch()
        self.bucket.setEnabled(True)

    def _browse(self):
        p, _ = QFileDialog.getOpenFileName(self, "Service account key", "", "JSON (*.json)")
        if p:
            self.key.setText(p)

    def _save(self):
        self.save_cloud.emit(CloudConfig(credentials=self.key.text().strip() or "serviceAccountKey.json",
                                         storage_bucket=self.bucket.text().strip(), mode=self.mode.currentData(),
                                         collection=self.coll.text().strip() or "incidents"))

    def load(self, cfg):
        if cfg:
            self.key.setText(cfg.credentials); self.bucket.setText(cfg.storage_bucket); self.coll.setText(cfg.collection)
            self.mode.setCurrentIndex(max(0, self.mode.findData(cfg.mode)))
            self.bucket.setEnabled(cfg.mode == "storage")

    def set_state(self, kind: str, text: str, detail: str = ""):
        colors_ = {"ok": ("#1F6B43", "#DFF0E6"), "error": ("#B5301B", "#F8E4DE"), "off": ("#555B5F", "#E9E5DA"), "busy": ("#8A5A00", "#F6EBD3")}
        fg, bg = colors_[kind]
        self.state.set(text, fg, bg)
        self.detail.setText(detail)
