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


def group_and_merge_ocr_blocks(
    ocr_results: List[Any],
    offset_x: int = 0,
    offset_y: int = 0,
    confidence_threshold: float = 0.35
) -> List[Dict[str, Any]]:
    """
    Groups adjacent OCR text fragments on the same line into coherent sentences/phrases.
    Merges their bounding boxes and combines text for natural, grammatical translation
    rather than fragmented word-by-word literal pieces.
    """
    if not ocr_results:
        return []

    parsed = []
    for dt_box, raw_text, score in ocr_results:
        try:
            score_val = float(score)
        except (ValueError, TypeError):
            score_val = 0.0

        if score_val < confidence_threshold:
            continue

        text = raw_text.strip()
        if not text or len(text) < 2:
            continue

        pts = np.array(dt_box, dtype=np.int32)
        x_min = int(np.min(pts[:, 0])) + offset_x
        y_min = int(np.min(pts[:, 1])) + offset_y
        x_max = int(np.max(pts[:, 0])) + offset_x
        y_max = int(np.max(pts[:, 1])) + offset_y
        width = max(1, x_max - x_min)
        height = max(1, y_max - y_min)

        parsed.append({
            "box": (x_min, y_min, width, height),
            "x_min": x_min,
            "y_min": y_min,
            "x_max": x_max,
            "y_max": y_max,
            "w": width,
            "h": height,
            "y_center": y_min + height / 2.0,
            "text": text,
            "score": score_val
        })

    if not parsed:
        return []

    # Sort parsed blocks top-to-bottom, left-to-right
    parsed.sort(key=lambda b: (b["y_min"], b["x_min"]))

    lines = []
    for block in parsed:
        matched_line = None
        for line in lines:
            line_y_center = sum(b["y_center"] for b in line) / len(line)
            avg_h = sum(b["h"] for b in line) / len(line)

            # Check if on the same horizontal line (within 60% of line height)
            if abs(block["y_center"] - line_y_center) < max(avg_h, block["h"]) * 0.6:
                min_x = min(b["x_min"] for b in line)
                max_x = max(b["x_max"] for b in line)
                # Distance to line bounding box
                gap = max(0, block["x_min"] - max_x, min_x - block["x_max"])
                if gap < max(avg_h, block["h"]) * 3.0:
                    matched_line = line
                    break

        if matched_line is not None:
            matched_line.append(block)
        else:
            lines.append([block])

    merged_blocks = []
    for line in lines:
        # Sort words in line strictly from left to right
        line.sort(key=lambda b: b["x_min"])

        merged_text = " ".join(b["text"] for b in line)
        min_x = min(b["x_min"] for b in line)
        min_y = min(b["y_min"] for b in line)
        max_x = max(b["x_max"] for b in line)
        max_y = max(b["y_max"] for b in line)
        merged_w = max_x - min_x
        merged_h = max_y - min_y
        avg_score = sum(b["score"] for b in line) / len(line)

        merged_blocks.append({
            "box": (min_x, min_y, merged_w, merged_h),
            "text": merged_text,
            "score": avg_score
        })

    return merged_blocks


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

        self._last_thumb = None
        self._last_matched: List[Dict[str, Any]] = []

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

    def has_screen_changed(self, img: np.ndarray, threshold: float = 0.8) -> bool:
        """
        Fast perceptual frame diff on small 64x36 thumbnail.
        Ignores minor pixel fluctuations (clocks, cursors) so heavy OCR is NOT re-run
        when the screen content hasn't really changed, eliminating CPU lag completely.
        """
        try:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            thumb = cv2.resize(gray, (64, 36), interpolation=cv2.INTER_AREA)

            if self._last_thumb is None:
                self._last_thumb = thumb
                return True

            diff = float(np.mean(np.abs(thumb.astype(np.int16) - self._last_thumb.astype(np.int16))))
            if diff < threshold:
                return False

            self._last_thumb = thumb
            return True
        except Exception:
            return True

    def process_screen(
        self,
        zone: Optional[Tuple[int, int, int, int]] = None,
        source_lang: str = "en",
        target_lang: str = "ru",
        confidence_threshold: float = 0.4,
        force: bool = False
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Captures screen/zone, runs OCR only when screen changed, and translates.
        """
        try:
            img, offset_x, offset_y = self.capture_image(zone)

            if not force and not self.has_screen_changed(img):
                # Screen unchanged: instantly reuse previous scan results, zero OCR load
                return self._last_matched

            t0 = time.time()
            ocr_results, _ = self._ocr(img)
            t_ocr = time.time() - t0

            if not ocr_results:
                self._last_matched = []
                return []

            # Group adjacent word fragments on the same line into coherent semantic lines
            merged_lines = group_and_merge_ocr_blocks(
                ocr_results,
                offset_x=offset_x,
                offset_y=offset_y,
                confidence_threshold=float(confidence_threshold)
            )

            matched_blocks = []
            checked_count = 0
            candidate_count = 0

            for line in merged_lines:
                text = line["text"]
                box = line["box"]
                score_val = line["score"]

                checked_count += 1

                # Ultra-fast local prefilter: rejects Russian, non-source, symbols in 0ms without HTTP requests
                if config.get("ocr.filter_by_source_lang", True):
                    if not is_potential_source_language(text, source_lang):
                        continue

                candidate_count += 1

                # Translate the full coherent sentence/line with complete contextual meaning
                trans_text, detected_lang = translate_and_detect_lang(
                    text,
                    source_lang=source_lang,
                    target_lang=target_lang
                )
                if not trans_text:
                    continue

                # Secondary strict verification
                if config.get("ocr.filter_by_source_lang", True):
                    if not matches_source_language(detected_lang, text, source_lang):
                        continue

                # Don't show overlay if translation is identical to source
                if trans_text.lower().strip() == text.lower().strip():
                    continue

                matched_blocks.append({
                    "box": box,
                    "src_text": text,
                    "trans_text": trans_text,
                    "detected_lang": detected_lang,
                    "score": score_val
                })

                print(f"[OCR Match] '{text}' -> '{trans_text}' (box: {box[0]},{box[1]},{box[2]}x{box[3]})")

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

    def start_auto_scan(self, interval_ms: int = 1000):
        """Starts periodic background scanning (1 second per tick)."""
        self._timer.setInterval(interval_ms)
        self._timer.start()

    def stop_auto_scan(self):
        """Stops periodic background scanning."""
        self._timer.stop()

    def is_auto_scanning(self) -> bool:
        return self._timer.isActive()

    def _on_auto_tick(self):
        self.scan_once(force=False)
