# CRITICAL: RapidOCR must be imported before any PyQt6 modules to prevent Qt platform DLL conflicts
from core.ocr_engine import ScreenOcrWorker

import sys
import threading
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PyQt6.QtGui import QIcon, QPixmap, QColor, QPainter, QFont
from PyQt6.QtCore import Qt

from config import config
from ui.screen_overlay import ScreenOverlayWindow
from ui.zone_selector import ZoneSelectorWidget
from ui.settings_dialog import SettingsDialog
from windows.hooks import HotkeyWorker

def create_tray_icon():
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    # Background
    painter.setBrush(QColor(16, 185, 129))  # Emerald green for OCR
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(2, 2, 28, 28, 6, 6)
    # Text
    painter.setPen(QColor(255, 255, 255))
    font = QFont("Segoe UI", 12, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "OCR")
    painter.end()
    return QIcon(pixmap)

class ScreenOverlayApp:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)

        # UI Components
        self.screen_overlay = ScreenOverlayWindow()
        self.zone_selector = ZoneSelectorWidget()
        self.settings_dialog = None

        # OCR Worker
        self.ocr_worker = ScreenOcrWorker()
        self.ocr_worker.results_ready.connect(self.screen_overlay.update_blocks)

        # Zone Selector Connections
        self.zone_selector.zone_selected.connect(self.on_zone_selected)

        # Global Hotkeys Worker
        self.hotkey_worker = HotkeyWorker()
        self.hotkey_worker.scan_triggered.connect(self.trigger_scan)
        self.hotkey_worker.select_zone_triggered.connect(self.start_zone_selection)
        self.hotkey_worker.toggle_auto_triggered.connect(self.toggle_auto_scan)
        self.hotkey_worker.test_overlay_triggered.connect(self.show_test_pill)

        self.hook_thread = threading.Thread(target=self.hotkey_worker.start_hook, daemon=True)
        self.hook_thread.start()

        # System Tray
        self.tray = QSystemTrayIcon(create_tray_icon(), self.app)
        self.tray.setToolTip("Screen Overlay Translator (RapidOCR)")
        self.setup_tray_menu()
        self.tray.show()

        # Auto-scan enabled by default (real-time screen detection without manual screenshots)
        if config.get("ocr.auto_scan_enabled", True):
            interval = config.get("ocr.interval_ms", 300)
            self.ocr_worker.start_auto_scan(interval)

    def setup_tray_menu(self):
        menu = QMenu()

        self.auto_action = menu.addAction("Автосканирование экрана (Ctrl+Alt+O)")
        self.auto_action.setCheckable(True)
        self.auto_action.setChecked(config.get("ocr.auto_scan_enabled", True))
        self.auto_action.triggered.connect(self.toggle_auto_scan)

        self.scan_action = menu.addAction("Снимок экрана и перевод (Ctrl+Alt+S)")
        self.scan_action.triggered.connect(self.trigger_scan)

        self.zone_action = menu.addAction("Выбрать зону экрана (Ctrl+Alt+Z)")
        self.zone_action.triggered.connect(self.start_zone_selection)

        test_action = menu.addAction("Проверить оверлей (Ctrl+Alt+T)")
        test_action.triggered.connect(self.show_test_pill)

        menu.addSeparator()

        settings_action = menu.addAction("Настройки...")
        settings_action.triggered.connect(self.open_settings)

        menu.addSeparator()

        quit_action = menu.addAction("Выход")
        quit_action.triggered.connect(self.quit_app)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.trigger_scan()

    def trigger_scan(self):
        self.ocr_worker.scan_once(force=True)

    def start_zone_selection(self):
        self.zone_selector.start_selection()

    def on_zone_selected(self, zone):
        msg = f"Зона экрана сохранена: {zone[2]}x{zone[3]} at ({zone[0]}, {zone[1]})"
        self.tray.showMessage("Экранный переводчик", msg, QSystemTrayIcon.MessageIcon.Information, 1500)
        if self.settings_dialog and self.settings_dialog.isVisible():
            self.settings_dialog.update_zone_label()

    def toggle_auto_scan(self):
        is_running = self.ocr_worker.is_auto_scanning()
        new_state = not is_running
        config.set("ocr.auto_scan_enabled", new_state)
        interval = config.get("ocr.interval_ms", 300)

        if new_state:
            self.ocr_worker.start_auto_scan(interval)
        else:
            self.ocr_worker.stop_auto_scan()

        self.auto_action.setChecked(new_state)
        status = "Автосканирование экрана ВКЛЮЧЕНО (Ctrl+Alt+O)" if new_state else "Автосканирование экрана ВЫКЛЮЧЕНО"
        self.tray.showMessage("Экранный переводчик", status, QSystemTrayIcon.MessageIcon.Information, 1500)

    def open_settings(self):
        if self.settings_dialog is None:
            self.settings_dialog = SettingsDialog()
            self.settings_dialog.select_zone_requested.connect(self.start_zone_selection)
            self.settings_dialog.settings_changed.connect(self.on_settings_changed)
        self.settings_dialog.load_values()
        self.settings_dialog.show()
        self.settings_dialog.activateWindow()

    def on_settings_changed(self):
        auto_enabled = bool(config.get("ocr.auto_scan_enabled", False))
        interval = config.get("ocr.interval_ms", 300)
        self.auto_action.setChecked(auto_enabled)

        if auto_enabled:
            self.ocr_worker.start_auto_scan(interval)
        else:
            self.ocr_worker.stop_auto_scan()

    def show_test_pill(self, text: str = "Тестовый оверлей: Dobar dan -> Добрый день"):
        self.screen_overlay.show_test_pill(text)

    def quit_app(self):
        self.ocr_worker.stop_auto_scan()
        self.screen_overlay.close()
        self.zone_selector.close()
        self.hotkey_worker.stop_hook()
        self.app.quit()

    def run(self):
        src = config.get("source_lang", "auto").upper()
        tgt = config.get("target_lang", "ru").upper()
        self.tray.showMessage(
            "Экранный переводчик",
            f"Автосканирование активно: распознает {src} и переводит на {tgt} прямо поверх текста.",
            QSystemTrayIcon.MessageIcon.Information,
            2500
        )
        sys.exit(self.app.exec())

if __name__ == "__main__":
    app = ScreenOverlayApp()
    app.run()
