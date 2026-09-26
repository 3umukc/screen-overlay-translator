import time
import re
import hashlib
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import cv2
import numpy as np
import mss
from rapidocr_onnxruntime import RapidOCR
from rapidocr_onnxruntime.ch_ppocr_v3_rec.text_recognize import TextRecognizer
from PyQt6.QtCore import QObject, pyqtSignal, QTimer

from config import config
from core.translator import (
    translate_and_detect_lang,
    matches_source_language,
    is_definitely_english,
    is_potential_source_language
)

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
        
        # Load specialized Slavic recognition model (supports Cyrillic + Latin with high accuracy)
        models_dir = Path(__file__).resolve().parent.parent / "models"
        eslav_model = models_dir / "eslav_rec.onnx"
        eslav_dict = models_dir / "eslav_dict.txt"

        if eslav_model.exists() and eslav_dict.exists():
            try:
                rec_cfg = {
                    'model_path': str(eslav_model),
                    'keys_path': str(eslav_dict),
                    'use_cuda': False,
                    'rec_img_shape': [3, 48, 320],
                    'rec_batch_num': 6
                }
                self._ocr.text_recognizer = TextRecognizer(rec_cfg)
                print("[OCR Engine] Successfully loaded Slavic recognition model (eslav_rec.onnx)")
            except Exception as e:
                print(f"[OCR Engine] Warning: failed to load eslav model: {e}")

        self._last_hash = ""

    def capture_image(self, zone: Optional[Tuple[int, int, int, int]] = None) -> Tuple[np.ndarray, int, int]:
        """
        Captures screen or specific zone safely within the calling thread.
        Covers all monitors (virtual desktop) by default so any window is caught.
        Returns: (image_bgr_numpy, offset_x, offset_y)
        """
        with mss.mss() as sct:
            if zone:
                x, y, w, h = zone
                monitor = {"top": int(y), "left": int(x), "width": int(w), "height": int(h)}
                offset_x, offset_y = int(x), int(y)
            else:
                # Capture full virtual desktop (monitors[0]) to support multi-monitor setups
                mon = sct.monitors[0]
                monitor = {"top": mon["top"], "left": mon["left"], "width": mon["width"], "height": mon["height"]}
                offset_x, offset_y = mon["left"], mon["top"]

            sct_img = sct.grab(monitor)
            img = np.array(sct_img)[:, :, :3]
            return img, offset_x, offset_y

    def compute_image_hash(self, img: np.ndarray) -> str:
        """Computes a fast perceptual hash to detect unchanged frames."""
        try:
            thumb = cv2.resize(img, (160, 90), interpolation=cv2.INTER_AREA)
            return hashlib.md5(thumb.tobytes()).hexdigest()
        except Exception:
            return ""

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
        """
        try:
            img, offset_x, offset_y = self.capture_image(zone)
            img_hash = self.compute_image_hash(img)

            if not force and img_hash == self._last_hash:
                # If frame is identical and we had active blocks, refresh them so they don't disappear
                if getattr(self, "_last_matched", None):
                    return self._last_matched
                return None

            self._last_hash = img_hash

            t0 = time.time()
            ocr_results, _ = self._ocr(img)
            t_ocr = time.time() - t0

            if not ocr_results:
                self._last_matched = []
                return []

            matched_blocks = []
            checked_count = 0
            candidate_count = 0

            for dt_box, raw_text, score in ocr_results:
                try:
                    score_val = float(score)
                except (ValueError, TypeError):
                    score_val = 0.0

                if score_val < float(confidence_threshold):
                    continue

                text = raw_text.strip()
                if not text or len(text) < 2:
                    continue

                checked_count += 1

                # Ultra-fast local prefilter: rejects Russian, English, symbols in 0ms without HTTP requests
                if config.get("ocr.filter_by_source_lang", True):
                    if not is_potential_source_language(text, source_lang):
                        continue

                candidate_count += 1

                # Translate and detect language
                trans_text, detected_lang = translate_and_detect_lang(text, source_lang=source_lang, target_lang=target_lang)
                if not trans_text:
                    continue

                # Secondary strict verification
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
                    "score": score_val
                })

                print(f"[OCR Match] '{text}' -> '{trans_text}' (box: {x_min},{y_min},{width}x{height})")

            self._last_matched = matched_blocks

            if matched_blocks:
                print(f"[OCR] Found {len(matched_blocks)} translated block(s) in {t_ocr:.2f}s (candidates: {candidate_count}/{checked_count})")
            elif candidate_count > 0:
                print(f"[OCR] Checked {candidate_count} candidates, 0 translated blocks.")

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
        self._scan_counter = 0

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
                self._scan_counter += 1
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
