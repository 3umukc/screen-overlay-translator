import time
import re
import hashlib
import threading
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
import mss
from rapidocr_onnxruntime import RapidOCR
from PyQt6.QtCore import QObject, pyqtSignal, QTimer

from config import config
from core.translator import translate_and_detect_lang, matches_source_language

def is_text_in_source_lang(text: str, source_lang: str) -> bool:
    """
    Checks if recognized text matches the target source language filter.
    Returns True if the text should be translated.
    """
    cleaned = text.strip()
    if not cleaned or len(cleaned) < 2:
        return False

    if source_lang == "auto":
        return True

    # Cyrillic languages (Russian, Ukrainian, Belarusian, etc.)
    if source_lang in ("ru", "uk", "be", "kk", "bg", "sr", "ky", "tg"):
        return bool(re.search(r"[\u0400-\u04FF]", cleaned))

    # CJK languages
    if source_lang == "zh":
        return bool(re.search(r"[\u4e00-\u9fff]", cleaned))
    if source_lang == "ja":
        return bool(re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", cleaned))
    if source_lang == "ko":
        return bool(re.search(r"[\uac00-\ud7af]", cleaned))

    # Semitic scripts
    if source_lang in ("ar", "fa"):
        return bool(re.search(r"[\u0600-\u06ff]", cleaned))
    if source_lang == "he":
        return bool(re.search(r"[\u0590-\u05ff]", cleaned))

    # English & Latin-based European languages
    if source_lang == "en":
        # Must contain Latin letters and not be primarily Cyrillic or CJK
        has_latin = bool(re.search(r"[a-zA-Z]", cleaned))
        has_cyrillic = bool(re.search(r"[\u0400-\u04FF]", cleaned))
        return has_latin and not has_cyrillic

    # Other European languages
    return bool(re.search(r"[a-zA-Z\u00C0-\u024F]", cleaned))


class ScreenOcrEngine:
    """Handles screen capture via mss and fast on-device text detection via RapidOCR."""

    def __init__(self):
        self._ocr = RapidOCR()
        self._sct = mss.mss()
        self._last_hash = ""

    def capture_image(self, zone: Optional[Tuple[int, int, int, int]] = None) -> Tuple[np.ndarray, int, int]:
        """
        Captures screen or specific zone.
        Returns: (image_bgr_numpy, offset_x, offset_y)
        """
        if zone:
            x, y, w, h = zone
            monitor = {"top": int(y), "left": int(x), "width": int(w), "height": int(h)}
            offset_x, offset_y = int(x), int(y)
        else:
            # Capture primary monitor
            mon = self._sct.monitors[1]
            monitor = {"top": mon["top"], "left": mon["left"], "width": mon["width"], "height": mon["height"]}
            offset_x, offset_y = mon["left"], mon["top"]

        sct_img = self._sct.grab(monitor)
        # Convert BGRA to BGR
        img = np.array(sct_img)[:, :, :3]
        return img, offset_x, offset_y

    def compute_image_hash(self, img: np.ndarray) -> str:
        """Computes a fast perceptual hash to detect unchanged frames."""
        # Downsample to 32x32 grayscale
        h, w = img.shape[:2]
        if h > 32 and w > 32:
            step_y = max(1, h // 32)
            step_x = max(1, w // 32)
            thumb = img[::step_y, ::step_x, 0]
        else:
            thumb = img[:, :, 0]
        return hashlib.md5(thumb.tobytes()).hexdigest()

    def process_screen(
        self,
        zone: Optional[Tuple[int, int, int, int]] = None,
        source_lang: str = "en",
        target_lang: str = "ru",
        confidence_threshold: float = 0.4,
        force: bool = False
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Captures screen/zone, runs OCR, filters by source_lang, and translates.
        Returns list of recognized and translated blocks:
        [
            {
                "box": (x, y, w, h),
                "polygon": [[x1, y1], [x2, y2], [x3, y3], [x4, y4]],
                "src_text": "...",
                "trans_text": "...",
                "score": 0.95
            },
            ...
        ]
        """
        try:
            img, offset_x, offset_y = self.capture_image(zone)
            img_hash = self.compute_image_hash(img)

            if not force and img_hash == self._last_hash:
                # Frame content is identical, skip OCR processing
                return None

            self._last_hash = img_hash

            # Run RapidOCR inference
            ocr_results, _ = self._ocr(img)
            if not ocr_results:
                return []

            matched_blocks = []
            for dt_box, raw_text, score in ocr_results:
                if score < confidence_threshold:
                    continue

                text = raw_text.strip()
                if not text or len(text) < 2:
                    continue

                # Translate and detect language
                trans_text, detected_lang = translate_and_detect_lang(text, source_lang=source_lang, target_lang=target_lang)
                if not trans_text:
                    continue

                # Filter by source language: if Serbian is chosen, English text is strictly rejected!
                if config.get("ocr.filter_by_source_lang", True):
                    if not matches_source_language(detected_lang, text, source_lang):
                        continue

                # Don't show overlay if translation is identical to source
                if trans_text.lower().strip() == text.lower().strip():
                    continue

                # Convert local coordinates to global screen coordinates
                pts = np.array(dt_box, dtype=np.int32)
                x_min = int(np.min(pts[:, 0])) + offset_x
                y_min = int(np.min(pts[:, 1])) + offset_y
                x_max = int(np.max(pts[:, 0])) + offset_x
                y_max = int(np.max(pts[:, 1])) + offset_y
                width = max(1, x_max - x_min)
                height = max(1, y_max - y_min)

                poly = [[int(pt[0]) + offset_x, int(pt[1]) + offset_y] for pt in dt_box]

                matched_blocks.append({
                    "box": (x_min, y_min, width, height),
                    "polygon": poly,
                    "src_text": text,
                    "trans_text": trans_text,
                    "detected_lang": detected_lang,
                    "score": float(score)
                })

            return matched_blocks
        except Exception as e:
            print(f"[OCR Engine] Error processing screen: {e}")
            return []


class ScreenOcrWorker(QObject):
    """Asynchronous worker that monitors screen text and emits translations."""

    results_ready = pyqtSignal(list)
    scan_started = pyqtSignal()
    scan_finished = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._engine: Optional[ScreenOcrEngine] = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_auto_tick)
        self._is_busy = False

    def _ensure_engine(self):
        if self._engine is None:
            self._engine = ScreenOcrEngine()

    def scan_once(self, force: bool = True):
        """Triggers a single screen OCR scan."""
        if self._is_busy:
            return
        self._is_busy = True
        self.scan_started.emit()

        def _run():
            try:
                self._ensure_engine()
                zone = config.get("ocr.zone", None)
                src = config.get("source_lang", "sr")
                tgt = config.get("target_lang", "ru")
                conf = config.get("ocr.confidence_threshold", 0.35)

                res = self._engine.process_screen(
                    zone=zone,
                    source_lang=src,
                    target_lang=tgt,
                    confidence_threshold=conf,
                    force=force
                )
                if res is not None:
                    self.results_ready.emit(res)
            finally:
                self._is_busy = False
                self.scan_finished.emit()

        # Run on a background daemon thread so GUI never lags or freezes
        threading.Thread(target=_run, daemon=True).start()

    def start_auto_scan(self, interval_ms: int = 700):
        """Starts periodic background scanning."""
        self._timer.setInterval(interval_ms)
        self._timer.start()

    def stop_auto_scan(self):
        """Stops periodic background scanning."""
        self._timer.stop()

    def is_auto_scanning(self) -> bool:
        return self._timer.isActive()

    def _on_auto_tick(self):
        self.scan_once(force=False)
