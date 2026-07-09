"""A small custom-painted iOS-style sliding toggle switch (QAbstractButton
doesn't ship one, and QCheckBox's indicator can't be restyled into a
knob-on-a-track shape via QSS alone)."""
from PyQt6.QtCore import Qt, QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSize, pyqtProperty
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QAbstractButton


class ToggleSwitch(QAbstractButton):
    def __init__(self, parent=None, off_color="#33333d", on_color="#9fd2ff", knob_color="#ffffff"):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._off_color = QColor(off_color)
        self._on_color = QColor(on_color)
        self._knob_color = QColor(knob_color)
        self._knob_pos = 1.0 if self.isChecked() else 0.0

        self._anim = QPropertyAnimation(self, b"knobPos", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.toggled.connect(self._animate_to_state)

    def _animate_to_state(self, checked):
        self._anim.stop()
        self._anim.setStartValue(self._knob_pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def sizeHint(self):
        return QSize(40, 20)

    def _get_knob_pos(self):
        return self._knob_pos

    def _set_knob_pos(self, value):
        self._knob_pos = value
        self.update()

    knobPos = pyqtProperty(float, _get_knob_pos, _set_knob_pos)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        track_rect = QRectF(0, 0, self.width(), self.height())
        radius = track_rect.height() / 2

        t = self._knob_pos
        track_color = QColor(
            round(self._off_color.red() + (self._on_color.red() - self._off_color.red()) * t),
            round(self._off_color.green() + (self._on_color.green() - self._off_color.green()) * t),
            round(self._off_color.blue() + (self._on_color.blue() - self._off_color.blue()) * t),
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track_color)
        painter.drawRoundedRect(track_rect, radius, radius)

        knob_radius = radius - 2
        knob_x = knob_radius + 2 + t * (track_rect.width() - 2 * (knob_radius + 2))
        knob_y = track_rect.height() / 2
        painter.setBrush(self._knob_color)
        painter.drawEllipse(QPointF(knob_x, knob_y), knob_radius, knob_radius)
