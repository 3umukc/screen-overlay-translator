import ctypes
from typing import List, Dict, Any, Optional
from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import Qt, QRectF, QTimer, pyqtSlot
from PyQt6.QtGui import QPainter, QColor, QFont, QFontMetrics, QPen, QBrush

import win32gui
import win32con

from config import config

class ScreenOverlayWindow(QWidget):
    """
    Transparent, click-through overlay window that renders translated text
    directly over the recognized text bounding boxes on screen.
    Uses WS_EX_TRANSPARENT so it never captures mouse clicks or interferes with games.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._blocks: List[Dict[str, Any]] = []
        self._clear_timer = QTimer(self)
        self._clear_timer.setSingleShot(True)
        self._clear_timer.timeout.connect(self.clear_overlay)

        self.init_window_flags()

    def init_window_flags(self):
        # Frameless, transparent, always on top, tool window (hidden from taskbar/alt-tab)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        # Full virtual screen geometry (covers all connected monitors)
        screen_geo = QApplication.primaryScreen().virtualGeometry()
        self.setGeometry(screen_geo)

    def showEvent(self, event):
        super().showEvent(event)
        self._enable_click_through()

    def _enable_click_through(self):
        """Sets Win32 WS_EX_TRANSPARENT and WS_EX_LAYERED so all mouse events pass through."""
        try:
            hwnd = int(self.winId())
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            win32gui.SetWindowLong(
                hwnd,
                win32con.GWL_EXSTYLE,
                style | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_LAYERED
            )
        except Exception as e:
            print(f"[ScreenOverlay] Error enabling click-through: {e}")

    @pyqtSlot(list)
    def update_blocks(self, blocks: List[Dict[str, Any]], auto_clear_ms: int = 4000):
        """Updates the active translation blocks to render."""
        self._blocks = blocks
        self.update()

        if self._blocks:
            if not self.isVisible():
                self.show()
                self._enable_click_through()
            if auto_clear_ms > 0:
                self._clear_timer.start(auto_clear_ms)
        else:
            self.clear_overlay()

    def clear_overlay(self):
        """Clears all displayed translation blocks."""
        self._blocks = []
        self.update()
        self.hide()

    def paintEvent(self, event):
        if not self._blocks:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        font_size = config.get("ocr.font_size", 13)
        font = QFont("Segoe UI", font_size, QFont.Weight.DemiBold)
        painter.setFont(font)
        fm = QFontMetrics(font)

        bg_color = QColor(16, 20, 28, 230)
        border_pen = QPen(QColor(70, 85, 110, 210), 1.2)
        text_color = QColor(255, 255, 255, 250)

        for block in self._blocks:
            x, y, w, h = block["box"]
            trans_text = block.get("trans_text", "").strip()
            if not trans_text:
                continue

            # Calculate tight bounding rectangle for text
            text_rect = fm.boundingRect(int(x), int(y), max(int(w), 120), 0, Qt.TextFlag.TextWordWrap, trans_text)
            pad_x = 7
            pad_y = 4
            pill_rect = QRectF(
                text_rect.x() - pad_x,
                text_rect.y() - pad_y,
                text_rect.width() + pad_x * 2,
                text_rect.height() + pad_y * 2
            )

            # Draw rounded background pill
            painter.setPen(border_pen)
            painter.setBrush(QBrush(bg_color))
            painter.drawRoundedRect(pill_rect, 5.0, 5.0)

            # Draw translated text
            painter.setPen(text_color)
            painter.drawText(
                QRectF(text_rect.x(), text_rect.y(), text_rect.width(), text_rect.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap,
                trans_text
            )

        painter.end()
