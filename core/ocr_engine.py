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
from rapidocr_onnxruntime.utils import OrtInferSession
from rapidocr_onnxruntime.ch_ppocr_v3_rec.text_recognize import TextRecognizer
import onnxruntime as ort
from PyQt6.QtCore import QObject, pyqtSignal, QTimer

from config import config
from core.translator import (
    translate_and_detect_lang,
    batch_translate_and_detect_lang,
    matches_source_language,
    is_definitely_english,
    is_potential_source_language
)

# Optimize ONNX Runtime to use max 2 worker threads so other CPU cores stay free for games/system
def _low_cpu_ort_init(self, config):
    sess_opt = ort.SessionOptions()
    sess_opt.log_severity_level = 4
    sess_opt.enable_cpu_mem_arena = False
    sess_opt.intra_op_num_threads = 2
    sess_opt.inter_op_num_threads = 1
    sess_opt.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    sess_opt.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    cpu_ep = 'CPUExecutionProvider'
    cpu_provider_options = {'arena_extend_strategy': 'kSameAsRequested'}
    self._verify_model(config['model_path'])
    self.session = ort.InferenceSession(config['model_path'], sess_options=sess_opt, providers=[(cpu_ep, cpu_provider_options)])

OrtInferSession.__init__ = _low_cpu_ort_init

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

            # Check if on the same horizontal line (within 50% of line height)
            if abs(block["y_center"] - line_y_center) < max(avg_h, block["h"]) * 0.5:
                min_x = min(b["x_min"] for b in line)
                max_x = max(b["x_max"] for b in line)
                # Distance to line bounding box
                gap = max(0, block["x_min"] - max_x, min_x - block["x_max"])
                # Word space threshold: ~1.2 of line height to keep phrases together without gluing buttons
                if gap < max(avg_h, block["h"]) * 1.2:
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
        # Set process priority to BELOW_NORMAL so games, browsers, and Windows DWM always get CPU priority
        try:
            import win32process
            import win32api
            win32process.SetPriorityClass(
                win32api.GetCurrentProcess(),
                win32process.BELOW_NORMAL_PRIORITY_CLASS
            )
        except Exception:
            pass

        # Disable angle classifier for screen text (text is always horizontal)
        self._ocr = RapidOCR(use_angle_cls=False)

        # Optimize detector resolution to 640 max dimension for ultra-fast DBNet detection (~100ms)
        try:
            if hasattr(self._ocr, "text_detector") and hasattr(self._ocr.text_detector, "preprocess_op"):
                for op in self._ocr.text_detector.preprocess_op:
                    if hasattr(op, "limit_type"):
                        op.limit_type = "max"
                        op.limit_side_len = 640
        except Exception as e:
            print(f"[OCR Engine] Warning: failed to configure detector resolution limit: {e}")

        self._models_dir = Path(__file__).resolve().parent.parent / "models"
        self._default_recognizer = self._ocr.text_recognizer
        self._recognizers: Dict[str, Any] = {"default": self._default_recognizer}

        self._last_thumb = None
        self._last_matched: List[Dict[str, Any]] = []
        self._cached_boxes: List[Dict[str, Any]] = []
        # Pre-load eslav recognizer by default so Russian and Latin are both recognized cleanly
        self._ocr.text_recognizer = self._get_recognizer_for_lang("auto")

    def _get_recognizer_for_lang(self, source_lang: str):
        """Loads and switches recognizer model dynamically based on source language."""
        # eslav model supports BOTH Russian Cyrillic and English Latin accurately
        target = "eslav"
        if source_lang in ("zh", "ja", "ko"):
            target = "default"

        if target in self._recognizers:
            return self._recognizers[target]

        model_path = self._models_dir / f"{target}_rec.onnx"
        dict_path = self._models_dir / f"{target}_dict.txt"
        if model_path.exists() and dict_path.exists():
            try:
                # rec_batch_num=1 processes boxes directly at minimum width, avoiding heavy padding overhead
                rec_cfg = {
                    'model_path': str(model_path),
                    'keys_path': str(dict_path),
                    'use_cuda': False,
                    'rec_img_shape': [3, 48, 320],
                    'rec_batch_num': 1
                }
                rec = TextRecognizer(rec_cfg)
                self._recognizers[target] = rec
                print(f"[OCR Engine] Loaded {target} recognition model ({target}_rec.onnx)")
                return rec
            except Exception as e:
                print(f"[OCR Engine] Failed to load {target} recognizer: {e}")

        return self._default_recognizer

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

    def has_screen_changed(self, img: np.ndarray, threshold: float = 2.0) -> bool:
        """
        Fast perceptual frame diff on small 64x36 thumbnail (<0.5 ms).
        Ignores minor pixel fluctuations (clocks, cursors, 3D world micro-jitter)
        so heavy OCR is NOT re-run when content hasn't changed.
        """
        try:
            # Subsample by step 16 to avoid converting all 6.5M pixels (0.4ms vs 27ms)
            sub = img[::16, ::16, 0]
            thumb = cv2.resize(sub, (64, 36), interpolation=cv2.INTER_NEAREST)

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
        source_lang: str = "auto",
        target_lang: str = "ru",
        confidence_threshold: float = 0.35,
        force: bool = False
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Differential Visual Fingerprint OCR & Smart Spatial Cache.
        Detects text boxes via DBNet (100ms), then reuses recognized texts for unchanged boxes (0ms),
        running recognizer and translation strictly on genuinely new text.
        """
        try:
            img, offset_x, offset_y = self.capture_image(zone)

            if not force and not self.has_screen_changed(img):
                # Screen unchanged: instantly reuse previous scan results, zero OCR load
                return self._last_matched

            self._ocr.text_recognizer = self._get_recognizer_for_lang(source_lang)

            t0 = time.time()
            dt_boxes, _ = self._ocr.text_detector(img)
            t_det = time.time() - t0

            if dt_boxes is None or len(dt_boxes) == 0:
                self._last_matched = []
                self._cached_boxes = []
                return []

            # Differential Visual Fingerprint Matching
            crops = self._ocr.get_crop_img_list(img, dt_boxes)
            uncached_indices = []
            uncached_crops = []
            box_results = [None] * len(dt_boxes)
            new_cached = []

            for i, (b, crop) in enumerate(zip(dt_boxes, crops)):
                pts = np.array(b, dtype=np.int32)
                cx = int(np.mean(pts[:, 0]))
                cy = int(np.mean(pts[:, 1]))
                fp = cv2.resize(crop[:, :, 0], (16, 8), interpolation=cv2.INTER_NEAREST)

                matched = None
                for c in self._cached_boxes:
                    if abs(c["cx"] - cx) <= 18 and abs(c["cy"] - cy) <= 14:
                        diff = float(np.mean(np.abs(fp.astype(np.int16) - c["fp"].astype(np.int16))))
                        if diff < 7.0:
                            matched = c
                            break

                if matched is not None:
                    box_results[i] = [b.tolist(), matched["text"], matched["score"]]
                    new_cached.append({"cx": cx, "cy": cy, "fp": fp, "text": matched["text"], "score": matched["score"]})
                else:
                    uncached_indices.append((i, cx, cy, fp, b))
                    uncached_crops.append(crop)

            t_rec0 = time.time()
            if uncached_crops:
                rec_res, _ = self._ocr.text_recognizer(uncached_crops)
                for (i, cx, cy, fp, b), (txt, score) in zip(uncached_indices, rec_res):
                    score_str = str(score)
                    box_results[i] = [b.tolist(), txt, score_str]
                    new_cached.append({"cx": cx, "cy": cy, "fp": fp, "text": txt, "score": score_str})
            t_rec = time.time() - t_rec0

            self._cached_boxes = new_cached
            ocr_results = [r for r in box_results if r is not None]

            # Group adjacent word fragments on the same line into coherent semantic lines
            merged_lines = group_and_merge_ocr_blocks(
                ocr_results,
                offset_x=offset_x,
                offset_y=offset_y,
                confidence_threshold=float(confidence_threshold)
            )

            candidate_blocks = []
            for line in merged_lines:
                text = line["text"]
                if config.get("ocr.filter_by_source_lang", True):
                    if not is_potential_source_language(text, source_lang, target_lang):
                        continue
                candidate_blocks.append(line)

            if not candidate_blocks:
                self._last_matched = []
                return []

            # Batch translate all candidate blocks in a single network request
            candidate_texts = [b["text"] for b in candidate_blocks]
            translations = batch_translate_and_detect_lang(
                candidate_texts,
                source_lang=source_lang,
                target_lang=target_lang
            )

            matched_blocks = []
            for line, (trans_text, detected_lang) in zip(candidate_blocks, translations):
                if not trans_text:
                    continue

                if config.get("ocr.filter_by_source_lang", True):
                    if not matches_source_language(detected_lang, line["text"], source_lang):
                        continue

                # Don't show overlay if translation is identical to source
                if trans_text.lower().strip() == line["text"].lower().strip():
                    continue

                matched_blocks.append({
                    "box": line["box"],
                    "src_text": line["text"],
                    "trans_text": trans_text,
                    "detected_lang": detected_lang,
                    "score": line["score"]
                })

                print(f"[OCR Match] '{line['text']}' -> '{trans_text}' (box: {line['box'][0]},{line['box'][1]},{line['box'][2]}x{line['box'][3]})")

            self._last_matched = matched_blocks

            reused_cnt = len(dt_boxes) - len(uncached_crops)
            total_time = time.time() - t0
            if matched_blocks:
                print(f"[OCR] Processed in {total_time*1000:.0f}ms (det:{t_det*1000:.0f}ms, rec:{t_rec*1000:.0f}ms, reused:{reused_cnt}/{len(dt_boxes)}) -> {len(matched_blocks)} block(s)")

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
                src = config.get("source_lang", "auto")
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

    def start_auto_scan(self, interval_ms: int = 300):
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
