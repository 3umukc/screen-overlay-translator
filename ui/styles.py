# Modern Dark Theme Stylesheet for Screen Overlay Translator (Zero emojis)

SETTINGS_STYLESHEET = """
QDialog {
    background-color: #0F172A;
    color: #F8FAFC;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 13px;
}

QGroupBox {
    border: 1px solid #1E293B;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 14px;
    font-weight: 600;
    color: #94A3B8;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 4px;
    background-color: #0F172A;
}

QLabel {
    color: #E2E8F0;
}

QComboBox, QSpinBox {
    background-color: #1E293B;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 6px 10px;
    color: #F8FAFC;
    selection-background-color: #3B82F6;
}

QComboBox:focus, QSpinBox:focus {
    border: 1px solid #3B82F6;
}

QComboBox QAbstractItemView {
    background-color: #1E293B;
    border: 1px solid #334155;
    color: #F8FAFC;
    selection-background-color: #2563EB;
}

QCheckBox {
    color: #E2E8F0;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #334155;
    border-radius: 4px;
    background-color: #1E293B;
}

QCheckBox::indicator:checked {
    background-color: #2563EB;
    border-color: #2563EB;
}

QPushButton {
    background-color: #2563EB;
    color: #FFFFFF;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #1D4ED8;
}

QPushButton:pressed {
    background-color: #1E40AF;
}

QPushButton#SecondaryBtn {
    background-color: #1E293B;
    color: #94A3B8;
    border: 1px solid #334155;
}

QPushButton#SecondaryBtn:hover {
    background-color: #334155;
    color: #F8FAFC;
}
"""
