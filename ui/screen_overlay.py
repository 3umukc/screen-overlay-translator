import time
from typing import List, Dict, Any, Optional
from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import Qt, QRectF, QTimer, pyqtSlot
from PyQt6.QtGui import QPainter, QColor, QFont, QFontMetrics, QPen, QBrush

import win32gui
import win32con

from config import config

class OverlayBlock:
    """Represents a stabilized translation block with lifespan to prevent flicker."""
    def __init__(self, box: tuple, src_text: str, trans_text: str, detected_lang: str = ""):
        self.box = list(box)  # [x, y, w, h]
        self.src_text = src_text
        self.trans_text = trans_text
        self.detected_lang = detected_lang
        self.last_seen = time.time()

    def update_box(self, new_box: tuple):
        # Position smoothing
        self.box[0] = int(0.7 * self.box[0] + 0.3 * new_box[0])
        self.box[1] = int(0.7 * self.box[1] + 0.3 * new_box[1])
        self.box[2] = int(0.7 * self.box[2] + 0.3 * new_box[2])
        self.box[3] = int(0.7 * self.box[3] + 0.3 * new_box[3])
        self.last_seen = time.time()

class ScreenOverlayWindow(QWidget):
    """
    Transparent, click-through, non-intrusive overlay window.
    Renders sleek floating translation pills with anti-flicker stabilization.
    Uses Win32 WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active_blocks: List[OverlayBlock] = []
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._purge_expired_blocks)
        self._refresh_timer.start(300)

        self.init_window_flags()

    def init_window_flags(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        screen_geo = QApplication.primaryScreen().virtualGeometry()
        self.setGeometry(screen_geo)

    def showEvent(self, event):
        super().showEvent(event)
        self._enable_click_through()

    def _enable_click_through(self):
        """Ensures the window never captures mouse input or steals keyboard focus."""
        try:
            hwnd = int(self.winId())
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            win32gui.SetWindowLong(
                hwnd,
                win32con.GWL_EXSTYLE,
                style | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_LAYERED | win32con.WS_EX_NOACTIVATE
            )
        except Exception as e:
            print(f"[ScreenOverlay] Error enabling click-through: {e}")

    @pyqtSlot(list)
    def update_blocks(self, raw_blocks: List[Dict[str, Any]]):
        """Receives new OCR blocks and stabilizes them with temporal smoothing."""
        now = time.time()

        for raw in raw_blocks:
            box = raw["box"]
            src = raw.get("src_text", "").strip()
            trans = raw.get("trans_text", "").strip()
            detected = raw.get("detected_lang", "")

            if not trans:
                continue

            # Look for existing matching block nearby
            found = False
            for existing in self._active_blocks:
                dist_x = abs(existing.box[0] - box[0])
                dist_y = abs(existing.box[1] - box[1])
                if dist_x < 35 and dist_y < 25:
                    existing.update_box(box)
                    existing.src_text = src
                    existing.trans_text = trans
                    existing.detected_lang = detected
                    found = True
                    break

            if not found:
                self._active_blocks.append(OverlayBlock(box, src, trans, detected))

        self._purge_expired_blocks()

    def _purge_expired_blocks(self):
        """Removes blocks that haven't been re-detected within the lifespan threshold."""
        now = time.time()
        lifespan = config.get("ocr.auto_clear_ms", 3000) / 1000.0

        alive = []
        for block in self._active_blocks:
            if (now - block.last_seen) < lifespan:
                alive.append(block)

        self._active_blocks = alive
        self.update()

        if self._active_blocks:
            if not self.isVisible():
                self.show()
                self._enable_click_through()
        else:
            if self.isVisible():
                self.hide()

    def clear_overlay(self):
        """Immediately clears all overlay blocks."""
        self._active_blocks.clear()
        self.update()
        self.hide()

    def show_test_pill(self, text: str = "Тестовый оверлей: Dobar dan -> Добрый день"):
        """Displays a test translation pill in the center of the primary monitor."""
        screen_geo = QApplication.primaryScreen().geometry()
        cx = screen_geo.x() + screen_geo.width() // 2 - 160
        cy = screen_geo.y() + screen_geo.height() // 2 - 20
        self.update_blocks([{
            "box": (cx, cy, 320, 36),
            "src_text": "Dobar dan",
            "trans_text": text,
            "detected_lang": "sr",
            "score": 0.99
        }])

    def paintEvent(self, event):
        if not self._active_blocks:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        screen_w = self.width()
        screen_h = self.height()

        opacity = config.get("ocr.opacity", 0.94)
        alpha = int(opacity * 255)
        # Google Lens style dark patch
        bg_brush = QBrush(QColor(18, 22, 30, alpha))
        border_pen = QPen(QColor(60, 70, 90, 140), 1.0)
        text_pen = QColor(255, 255, 255, 255)

        for block in self._active_blocks:
            bx, by, bw, bh = block.box
            trans_text = block.trans_text
            if not trans_text:
                continue

            # Fit font size to the detected text line height
            font_size = max(11, min(int(bh * 0.72), 24))
            font = QFont("Segoe UI", font_size, QFont.Weight.Medium)
            painter.setFont(font)
            fm = QFontMetrics(font)

            pad_x = 4
            pad_y = 2

            text_w = fm.horizontalAdvance(trans_text)
            text_h = fm.height()

            # Google Lens in-place patch directly covering the recognized text box
            patch_w = max(float(bw), float(text_w)) + pad_x * 2
            patch_h = max(float(bh), float(text_h)) + pad_y * 2

            patch_x = float(bx) - pad_x
            patch_y = float(by) - pad_y

            # Keep strictly within screen bounds
            if patch_x < 0:
                patch_x = 0
            elif patch_x + patch_w > screen_w:
                patch_x = max(0.0, screen_w - patch_w)

            if patch_y < 0:
                patch_y = 0
            elif patch_y + patch_h > screen_h:
                patch_y = max(0.0, screen_h - patch_h)

            patch_rect = QRectF(patch_x, patch_y, patch_w, patch_h)

            # Draw dark background patch masking original text
            painter.setPen(border_pen)
            painter.setBrush(bg_brush)
            painter.drawRoundedRect(patch_rect, 3.5, 3.5)

            # Draw white translated text centered vertically
            text_rect = QRectF(
                patch_x + pad_x,
                patch_y + pad_y,
                patch_w - pad_x * 2,
                patch_h - pad_y * 2
            )
            painter.setPen(text_pen)
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                trans_text
            )

        painter.end()
