from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QGroupBox, QSpinBox, QCheckBox
)
from PyQt6.QtCore import pyqtSignal
from config import config
from ui.styles import SETTINGS_STYLESHEET

SUPPORTED_LANGUAGES = [
    ("Русский (ru)", "ru"),
    ("English (en)", "en"),
    ("Deutsch / Немецкий (de)", "de"),
    ("Français / Французский (fr)", "fr"),
    ("Español / Испанский (es)", "es"),
    ("Italiano / Итальянский (it)", "it"),
    ("Português / Португальский (pt)", "pt"),
    ("Nederlands / Нидерландский (nl)", "nl"),
    ("Polski / Польский (pl)", "pl"),
    ("Українська / Украинский (uk)", "uk"),
    ("Čeština / Чешский (cs)", "cs"),
    ("Slovenčina / Словацкий (sk)", "sk"),
    ("Български / Болгарский (bg)", "bg"),
    ("Српски / Сербский (sr)", "sr"),
    ("Hrvatski / Хорватский (hr)", "hr"),
    ("Svenska / Шведский (sv)", "sv"),
    ("Norsk / Норвежский (no)", "no"),
    ("Dansk / Датский (da)", "da"),
    ("Suomi / Финский (fi)", "fi"),
    ("Ελληνικά / Греческий (el)", "el"),
    ("Magyar / Венгерский (hu)", "hu"),
    ("Română / Румынский (ro)", "ro"),
    ("Lietuvių / Литовский (lt)", "lt"),
    ("Latviešu / Латышский (lv)", "lv"),
    ("Eesti / Эстонский (et)", "et"),
    ("Қазақша / Казахский (kk)", "kk"),
    ("Беларуская / Белорусский (be)", "be"),
    ("Հայերեն / Армянский (hy)", "hy"),
    ("ქართული / Грузинский (ka)", "ka"),
    ("Azərbaycan / Азербайджанский (az)", "az"),
    ("Oʻzbekcha / Узбекский (uz)", "uz"),
    ("Тоҷикӣ / Таджикский (tg)", "tg"),
    ("Кыргызча / Киргизский (ky)", "ky"),
    ("Türkçe / Турецкий (tr)", "tr"),
    ("中文 / Китайский (zh)", "zh"),
    ("日本語 / Японский (ja)", "ja"),
    ("한국어 / Корейский (ko)", "ko"),
    ("العربية / Арабский (ar)", "ar"),
    ("עברית / Иврит (he)", "he"),
    ("فارسی / Персидский (fa)", "fa"),
    ("हिन्दी / Хинди (hi)", "hi"),
    ("Tiếng Việt / Вьетнамский (vi)", "vi"),
    ("ไทย / Тайский (th)", "th"),
    ("Bahasa Indonesia / Индонезийский (id)", "id"),
    ("Bahasa Melayu / Малайский (ms)", "ms"),
    ("Tagalog / Филиппинский (tl)", "tl"),
]

SOURCE_LANGUAGES = [
    ("Автоопределение (auto)", "auto"),
] + SUPPORTED_LANGUAGES

class SettingsDialog(QDialog):
    select_zone_requested = pyqtSignal()
    settings_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки Screen Overlay Translator")
        self.setFixedSize(480, 520)
        self.setStyleSheet(SETTINGS_STYLESHEET)
        self.init_ui()
        self.load_values()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # 1. Languages Group
        lang_group = QGroupBox("Языки перевода")
        lang_layout = QVBoxLayout(lang_group)
        lang_layout.setSpacing(8)

        src_row = QHBoxLayout()
        src_row.addWidget(QLabel("Исходный язык (текст на экране):"))
        self.src_lang_combo = QComboBox()
        self.src_lang_combo.setMaxVisibleItems(15)
        for label, code in SOURCE_LANGUAGES:
            self.src_lang_combo.addItem(label, code)
        src_row.addWidget(self.src_lang_combo)
        lang_layout.addLayout(src_row)

        tgt_row = QHBoxLayout()
        tgt_row.addWidget(QLabel("Целевой язык (перевод в оверлее):"))
        self.tgt_lang_combo = QComboBox()
        self.tgt_lang_combo.setMaxVisibleItems(15)
        for label, code in SUPPORTED_LANGUAGES:
            self.tgt_lang_combo.addItem(label, code)
        tgt_row.addWidget(self.tgt_lang_combo)
        lang_layout.addLayout(tgt_row)

        self.filter_checkbox = QCheckBox("Фильтровать текст: переводить только выбранный исходный язык")
        lang_layout.addWidget(self.filter_checkbox)

        layout.addWidget(lang_group)

        # 2. Scanning & Overlay Group
        ocr_group = QGroupBox("Параметры сканирования и оверлея")
        ocr_layout = QVBoxLayout(ocr_group)
        ocr_layout.setSpacing(8)

        self.auto_scan_checkbox = QCheckBox("Автоматическое сканирование экрана в реальном времени")
        ocr_layout.addWidget(self.auto_scan_checkbox)

        interval_row = QHBoxLayout()
        interval_row.addWidget(QLabel("Интервал автосканирования (мс):"))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(300, 3000)
        self.interval_spin.setSingleStep(100)
        interval_row.addWidget(self.interval_spin)
        ocr_layout.addLayout(interval_row)

        font_row = QHBoxLayout()
        font_row.addWidget(QLabel("Размер шрифта плашек оверлея:"))
        self.font_spin = QSpinBox()
        self.font_spin.setRange(9, 26)
        self.font_spin.setSingleStep(1)
        font_row.addWidget(self.font_spin)
        ocr_layout.addLayout(font_row)

        zone_row = QHBoxLayout()
        self.zone_label = QLabel("Область: Весь экран")
        self.zone_label.setStyleSheet("color: #94A3B8; font-size: 11px;")
        zone_row.addWidget(self.zone_label)
        zone_row.addStretch()

        self.select_zone_btn = QPushButton("Выбрать зону")
        self.select_zone_btn.setObjectName("SecondaryBtn")
        self.select_zone_btn.clicked.connect(self._on_select_zone_click)
        zone_row.addWidget(self.select_zone_btn)

        self.reset_zone_btn = QPushButton("Сбросить")
        self.reset_zone_btn.setObjectName("SecondaryBtn")
        self.reset_zone_btn.clicked.connect(self._on_reset_zone_click)
        zone_row.addWidget(self.reset_zone_btn)

        ocr_layout.addLayout(zone_row)
        layout.addWidget(ocr_group)

        # 3. Hotkeys Reference
        info_label = QLabel(
            "Горячие клавиши:\n"
            "[Ctrl+Alt+S] Снимок экрана и перевод\n"
            "[Ctrl+Alt+Z] Выбрать прямоугольную зону экрана\n"
            "[Ctrl+Alt+O] Включить / выключить автосканирование"
        )
        info_label.setStyleSheet("color: #64748B; font-size: 11px; line-height: 1.4;")
        layout.addWidget(info_label)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Отмена")
        cancel_btn.setObjectName("SecondaryBtn")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        save_btn = QPushButton("Сохранить")
        save_btn.clicked.connect(self.save_values)
        btn_layout.addWidget(save_btn)

        layout.addLayout(btn_layout)

    def _on_select_zone_click(self):
        self.hide()
        self.select_zone_requested.emit()

    def _on_reset_zone_click(self):
        config.set("ocr.zone", None)
        self.update_zone_label()

    def update_zone_label(self):
        zone = config.get("ocr.zone", None)
        if zone:
            self.zone_label.setText(f"Область: {zone[2]}x{zone[3]} at ({zone[0]}, {zone[1]})")
        else:
            self.zone_label.setText("Область: Весь экран")

    def load_values(self):
        s_lang = config.get("source_lang", "en")
        s_idx = self.src_lang_combo.findData(s_lang)
        if s_idx >= 0:
            self.src_lang_combo.setCurrentIndex(s_idx)

        t_lang = config.get("target_lang", "ru")
        t_idx = self.tgt_lang_combo.findData(t_lang)
        if t_idx >= 0:
            self.tgt_lang_combo.setCurrentIndex(t_idx)

        self.filter_checkbox.setChecked(bool(config.get("ocr.filter_by_source_lang", True)))
        self.auto_scan_checkbox.setChecked(bool(config.get("ocr.auto_scan_enabled", False)))
        self.interval_spin.setValue(int(config.get("ocr.interval_ms", 700)))
        self.font_spin.setValue(int(config.get("ocr.font_size", 13)))
        self.update_zone_label()

    def save_values(self):
        config.set("source_lang", self.src_lang_combo.currentData())
        config.set("target_lang", self.tgt_lang_combo.currentData())
        config.set("ocr.filter_by_source_lang", self.filter_checkbox.isChecked())
        config.set("ocr.auto_scan_enabled", self.auto_scan_checkbox.isChecked())
        config.set("ocr.interval_ms", self.interval_spin.value())
        config.set("ocr.font_size", self.font_spin.value())

        self.settings_changed.emit()
        self.accept()
