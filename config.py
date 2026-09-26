import os
import json
from pathlib import Path
from typing import Any, Dict

DEFAULT_CONFIG: Dict[str, Any] = {
    "source_lang": "sr",
    "target_lang": "ru",
    "ocr": {
        "auto_scan_enabled": True,
        "interval_ms": 1000,
        "zone": None,
        "font_size": 13,
        "opacity": 0.92,
        "filter_by_source_lang": True,
        "confidence_threshold": 0.35,
        "auto_clear_ms": 3000
    },
    "hotkeys": {
        "scan": "Ctrl+Alt+S",
        "select_zone": "Ctrl+Alt+Z",
        "toggle_auto": "Ctrl+Alt+O"
    }
}

class ConfigManager:
    """Manages persistent application configuration in user's home directory."""

    def __init__(self):
        self.config_dir = Path.home() / ".screen_overlay_translator"
        self.config_file = self.config_dir / "config.json"
        self._data: Dict[str, Any] = {}
        self.load()

    def load(self):
        if not self.config_file.exists():
            self._data = dict(DEFAULT_CONFIG)
            self.save()
            return

        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                self._data = self._deep_merge(dict(DEFAULT_CONFIG), loaded)
        except Exception:
            self._data = dict(DEFAULT_CONFIG)

    def save(self):
        self.config_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Config] Error saving config: {e}")

    def get(self, key_path: str, default: Any = None) -> Any:
        keys = key_path.split(".")
        val = self._data
        for k in keys:
            if isinstance(val, dict) and k in val:
                val = val[k]
            else:
                return default
        return val

    def set(self, key_path: str, value: Any):
        keys = key_path.split(".")
        val = self._data
        for k in keys[:-1]:
            if k not in val or not isinstance(val[k], dict):
                val[k] = {}
            val = val[k]
        val[keys[-1]] = value
        self.save()

    def _deep_merge(self, base: dict, update: dict) -> dict:
        for k, v in update.items():
            if isinstance(v, dict) and k in base and isinstance(base[k], dict):
                base[k] = self._deep_merge(base[k], v)
            else:
                base[k] = v
        return base

config = ConfigManager()
