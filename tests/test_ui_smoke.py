import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from invigil.config import Config  # noqa: E402
from invigil.demo import seed  # noqa: E402
from invigil.ui.main_window import MainWindow  # noqa: E402
from invigil.ui.theme import QSS  # noqa: E402

SHOTS = os.environ.get("INVIGIL_SHOTS")  # set to a folder to also save screenshots


@pytest.fixture()
def win(tmp_path):
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(QSS)
    db = str(tmp_path / "ui.db")
    seed(db, str(tmp_path / "runs"), n=14)
    w = MainWindow(Config(), db, str(tmp_path / "runs"), str(tmp_path / "none.json"))
    w.show()
    app.processEvents()
    yield w, app
    w.sync = None
    w.close()


def snap(w, app, name):
    app.processEvents()
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        w.grab().save(os.path.join(SHOTS, name + ".png"))


def test_pages_render_and_filter(win):
    w, app = win
    snap(w, app, "monitor_empty")
    w._go(1)
    assert w.incidents.table.rowCount() == 14
    snap(w, app, "incidents")
    w.incidents.grp.button(1).click()  # Needs review
    pend = w.incidents.table.rowCount()
    assert 0 < pend < 14
    w.incidents.q.setText("student #99")
    assert w.incidents.table.rowCount() == 0 and not w.incidents.empty.isHidden()
    w.incidents.q.setText("")
    w._go(2)
    snap(w, app, "settings")


def test_review_updates_db_and_table(win):
    w, app = win
    w._go(1)
    w.incidents.grp.button(1).click()
    before = w.incidents.table.rowCount()
    eid = w.db.events(newest_first=True)[0]["event_id"]
    pending = [e for e in w.db.events() if e["review_status"] == "pending"][0]["event_id"]
    w.bus.review_requested.emit(pending, "confirmed")
    assert w.db.get_event(pending)["review_status"] == "confirmed"
    assert w.incidents.table.rowCount() == before - 1


def test_monitor_shows_frames_and_alerts(win, tmp_path):
    w, app = win
    ev = w.db.events(newest_first=True)
    img = QImage(os.path.join(os.path.dirname(ev[0]["best_shot"]), os.path.basename(ev[0]["best_shot"])))
    w.monitor.start_run("exam01.mp4")
    w.monitor.show_frame(img, 83.2, {"persons": 6, "flagged": 1, "total": 1000, "idx": 400})
    for e in ev[:3]:
        w.monitor.add_alert({**w.db.get_event(e["event_id"]), "kind": "open"})
    assert w.monitor.k_alerts.value.text() == "3" and w.monitor.k_students.value.text() == "6"
    assert not w.monitor.btn_upload.isEnabled() and w.monitor.btn_stop.isEnabled()
    snap(w, app, "monitor_running")
    w.monitor.end_run("Done.")
    assert w.monitor.btn_upload.isEnabled()


def test_evidence_dialog_opens_and_reviews(win):
    w, app = win
    from invigil.ui.pages import EvidenceDialog
    eid = w.db.events()[0]["event_id"]
    d = EvidenceDialog(w.db, eid, w.bus, w)
    d.show(); app.processEvents()
    if SHOTS:
        d.grab().save(os.path.join(SHOTS, "evidence.png"))
    d.btn_no.click()
    assert w.db.get_event(eid)["review_status"] == "dismissed" and not d.btn_no.isEnabled()
    d.close()
