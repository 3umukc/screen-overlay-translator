from typing import Optional, Tuple
from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import Qt, QRect, QPoint, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QFont

from config import config

class ZoneSelectorWidget(QWidget):
    """
    Snipping-Tool style fullscreen transparent canvas for selecting a screen zone
    to monitor and translate.
    """

    zone_selected = pyqtSignal(tuple)  # (x, y, w, h)
    selection_cancelled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._start_pos: Optional[QPoint] = None
        self._current_pos: Optional[QPoint] = None
        self._is_selecting = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def start_selection(self):
        """Displays the fullscreen canvas over all virtual monitors."""
        screen_geo = QApplication.primaryScreen().virtualGeometry()
        self.setGeometry(screen_geo)
        self._start_pos = None
        self._current_pos = None
        self._is_selecting = False
        self.show()
        self.activateWindow()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._start_pos = event.globalPosition().toPoint()
            self._current_pos = self._start_pos
            self._is_selecting = True
            self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            self.cancel_selection()

    def mouseMoveEvent(self, event):
        if self._is_selecting:
            self._current_pos = event.globalPosition().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._is_selecting:
            self._is_selecting = False
            self._current_pos = event.globalPosition().toPoint()
            self.finish_selection()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancel_selection()
        else:
            super().keyPressEvent(event)

    def cancel_selection(self):
        self.hide()
        self.selection_cancelled.emit()

    def finish_selection(self):
        self.hide()
        if self._start_pos and self._current_pos:
            x1 = min(self._start_pos.x(), self._current_pos.x())
            y1 = min(self._start_pos.y(), self._current_pos.y())
            x2 = max(self._start_pos.x(), self._current_pos.x())
            y2 = max(self._start_pos.y(), self._current_pos.y())
            w = x2 - x1
            h = y2 - y1

            if w >= 20 and h >= 20:
                zone = (x1, y1, w, h)
                config.set("ocr.zone", list(zone))
                self.zone_selected.emit(zone)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 1. Dark semi-transparent background over entire screen
        painter.fillRect(self.rect(), QColor(0, 0, 0, 110))

        # 2. Draw selection rectangle cut-out and border
        if self._start_pos and self._current_pos:
            x = min(self._start_pos.x(), self._current_pos.x()) - self.geometry().x()
            y = min(self._start_pos.y(), self._current_pos.y()) - self.geometry().y()
            w = abs(self._current_pos.x() - self._start_pos.x())
            h = abs(self._current_pos.y() - self._start_pos.y())
            sel_rect = QRect(x, y, w, h)

            # Clear dark tint inside the selected area so user sees the screen clearly
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(sel_rect, Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

            # Bright blue border and dimensions label
            pen = QPen(QColor(59, 130, 246), 2, Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(sel_rect)

            dim_text = f"{w} x {h}"
            painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(x + 5, y - 6 if y > 20 else y + 16, dim_text)

        # 3. Top instruction hint
        hint_text = "Выделите область экрана для перевода | Escape для отмены"
        painter.setFont(QFont("Segoe UI", 12, QFont.Weight.Medium))
        fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(hint_text)
        screen_center_x = self.rect().width() // 2
        hint_rect = QRect(screen_center_x - (tw // 2) - 15, 30, tw + 30, 36)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(20, 24, 33, 220))
        painter.drawRoundedRect(hint_rect, 6.0, 6.0)

        painter.setPen(QColor(255, 255, 255))
        painter.drawText(hint_rect, Qt.AlignmentFlag.AlignCenter, hint_text)

        painter.end()
