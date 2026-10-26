from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

from ..labels import STATUS_LABELS, colors, label
from .theme import P, STATUS_COLORS

_CACHE: dict = {}


def fmt_when(iso) -> str:
    from datetime import datetime
    try:
        return datetime.fromisoformat(iso).strftime("%b %d, %H:%M")
    except (TypeError, ValueError):
        return iso or "–"


def fmt_time(t) -> str:
    return "–" if t is None else f"{int(t // 60):02d}:{t % 60:04.1f}"


def thumb(path, w: int, h: int, radius: int = 8) -> QPixmap:
    """Cover-cropped, rounded, retina-sharp thumbnail (cached)."""
    key = (path, w, h)
    if key in _CACHE:
        return _CACHE[key]
    dpr = 2
    src = QPixmap(path) if path and Path(path).exists() else QPixmap()
    if src.isNull():
        src = QPixmap(w * dpr, h * dpr)
        src.fill(QColor(P["hover"]))
    else:
        src = src.scaled(w * dpr, h * dpr, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                         Qt.TransformationMode.SmoothTransformation)
        src = src.copy((src.width() - w * dpr) // 2, (src.height() - h * dpr) // 2, w * dpr, h * dpr)
    out = QPixmap(w * dpr, h * dpr)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0, 0, w * dpr, h * dpr), radius * dpr, radius * dpr)
    p.setClipPath(clip)
    p.drawPixmap(0, 0, src)
    p.end()
    out.setDevicePixelRatio(dpr)
    _CACHE[key] = out
    return out


class Chip(QWidget):
    """Pill label painted by hand: sizes itself from the font and always has round ends."""

    def __init__(self, text: str, fg: str, bg: str):
        super().__init__()
        f = self.font()
        f.setBold(True)
        f.setPixelSize(11)
        self.setFont(f)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.set(text, fg, bg)

    def set(self, text: str, fg: str, bg: str):
        self._text, self._fg, self._bg = text, QColor(fg), QColor(bg)
        fm = QFontMetrics(self.font())
        self.setFixedSize(fm.horizontalAdvance(text) + 30, fm.height() + 8)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._bg)
        p.drawRoundedRect(QRectF(self.rect()), self.height() / 2, self.height() / 2)
        p.setPen(self._fg)
        p.setFont(self.font())
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._text)


def chip(text: str, fg: str, bg: str) -> Chip:
    return Chip(text, fg, bg)


def behavior_chip(b: str) -> QLabel:
    strong, soft = colors(b)
    return chip(label(b), strong, soft)


def status_chip(s: str) -> QLabel:
    fg, bg = STATUS_COLORS.get(s, STATUS_COLORS["pending"])
    return chip(STATUS_LABELS.get(s, s), fg, bg)


def wrap(w: QWidget, margins=(8, 0, 8, 0)) -> QWidget:
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(*margins)
    lay.addWidget(w)
    lay.addStretch()
    return box


class Card(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")


class Kpi(Card):
    def __init__(self, title: str, accent: str):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(2)
        self._accent = accent
        t = QLabel(title.upper()); t.setObjectName("kpiLabel")
        self.value = QLabel("0"); self.value.setObjectName("kpiValue")
        self.sub = QLabel(""); self.sub.setObjectName("kpiSub")
        for w in (t, self.value, self.sub):
            lay.addWidget(w)

    def set(self, value, sub: str = ""):
        self.value.setText(str(value))
        self.sub.setText(sub)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self._accent))
        p.drawRoundedRect(QRectF(18, 0, self.width() - 36, 3), 1.5, 1.5)


class StrengthBar(QWidget):
    def __init__(self, value: float = 0.0, color: str = P["red"], w: int = 64):
        super().__init__()
        self.value, self.color = max(0.0, min(1.0, value or 0.0)), color
        self.setFixedSize(w, 6)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(P["hover"]))
        p.drawRoundedRect(QRectF(0, 0, self.width(), 6), 3, 3)
        p.setBrush(QColor(self.color))
        p.drawRoundedRect(QRectF(0, 0, self.width() * self.value, 6), 3, 3)


def strength_cell(value, color) -> QWidget:
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(8, 0, 8, 0)
    lay.setSpacing(8)
    lay.addWidget(StrengthBar(value, color))
    num = QLabel("–" if value is None else f"{value:.2f}")
    num.setObjectName("muted")
    lay.addWidget(num)
    lay.addStretch()
    return box


def segmented(labels: list) -> tuple:
    """-> (widget, QButtonGroup); button ids follow the order of labels."""
    wrap_ = QFrame()
    wrap_.setObjectName("segwrap")
    lay = QHBoxLayout(wrap_)
    lay.setContentsMargins(3, 3, 3, 3)
    lay.setSpacing(2)
    grp = QButtonGroup(wrap_)
    grp.setExclusive(True)
    for i, text in enumerate(labels):
        b = QPushButton(text)
        b.setObjectName("seg")
        b.setCheckable(True)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        grp.addButton(b, i)
        lay.addWidget(b)
    grp.button(0).setChecked(True)
    return wrap_, grp


class VideoView(QLabel):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(520, 320)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background:#14171A;border-radius:12px;color:#8B9096;font-size:14px;")
        self._img: QImage | None = None
        self.clear_view()

    def clear_view(self):
        self._img = None
        self.setPixmap(QPixmap())
        self.setText("Choose an exam video to begin.\nStudents get a green box; flagged moments turn red.")

    def show_image(self, img: QImage):
        self._img = img
        self._paint()

    def _paint(self):
        if self._img is not None:
            self.setPixmap(QPixmap.fromImage(self._img).scaled(
                self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._paint()


class AlertCard(Card):
    review = Signal(int, str)
    inspect = Signal(int)

    def __init__(self, e: dict):
        super().__init__()
        self.event_id = e["event_id"]
        self._outer = QHBoxLayout(self)
        self._outer.setContentsMargins(12, 12, 14, 12)
        self._outer.setSpacing(12)
        self.pic = QLabel()
        self.pic.setFixedSize(120, 76)
        self.pic.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pic.mousePressEvent = lambda ev: self.inspect.emit(self.event_id)
        self._outer.addWidget(self.pic)
        self.col = QVBoxLayout()
        self.col.setSpacing(5)
        self._outer.addLayout(self.col, 1)
        self.set_event(e)

    def _clear(self, lay):
        while lay.count():
            item = lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear(item.layout())

    def set_event(self, e: dict):
        self.pic.setPixmap(thumb(e.get("best_shot") or e.get("onset_shot"), 120, 76))
        self._clear(self.col)
        top = QHBoxLayout()
        top.addWidget(behavior_chip(e["behavior"]))
        top.addStretch()
        t = QLabel(fmt_time(e["t_start"])); t.setObjectName("muted")
        top.addWidget(t)
        self.col.addLayout(top)
        mid = QHBoxLayout(); mid.setSpacing(8)
        mid.addWidget(QLabel(f"<b>Student #{e['track_id']}</b>"))
        mid.addStretch()
        strong, _ = colors(e["behavior"])
        mid.addWidget(StrengthBar(e["peak_conf"], strong, 48))
        sc = QLabel("–" if e["peak_conf"] is None else f"{e['peak_conf']:.2f}"); sc.setObjectName("muted")
        mid.addWidget(sc)
        self.col.addLayout(mid)
        row = QHBoxLayout(); row.setSpacing(8)
        if e["review_status"] == "pending":
            ok, no = QPushButton("Confirm"), QPushButton("Dismiss")
            for b in (ok, no):
                b.setObjectName("mini"); b.setMinimumWidth(84)
            ok.clicked.connect(lambda: self.review.emit(self.event_id, "confirmed"))
            no.clicked.connect(lambda: self.review.emit(self.event_id, "dismissed"))
            row.addWidget(ok); row.addWidget(no); row.addStretch()
        else:
            row.addWidget(status_chip(e["review_status"])); row.addStretch()
        self.col.addLayout(row)

    def flash(self):
        self.setStyleSheet(f"QFrame#card{{border:2px solid {P['red']};}}")
        from PySide6.QtCore import QTimer
        QTimer.singleShot(1800, lambda: self.setStyleSheet(""))
