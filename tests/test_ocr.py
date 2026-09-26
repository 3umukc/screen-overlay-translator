import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest
import numpy as np
from core.ocr_engine import is_text_in_source_lang, ScreenOcrEngine

class TestScreenOcr(unittest.TestCase):
    def test_language_detection_cyrillic(self):
        self.assertTrue(is_text_in_source_lang("Привет мир", "ru"))
        self.assertTrue(is_text_in_source_lang("Доброго вечора", "uk"))
        self.assertFalse(is_text_in_source_lang("Hello world", "ru"))

    def test_language_detection_latin(self):
        self.assertTrue(is_text_in_source_lang("Hello world", "en"))
        self.assertTrue(is_text_in_source_lang("Press Start to Continue", "en"))
        self.assertFalse(is_text_in_source_lang("Привет мир", "en"))

    def test_language_detection_cjk(self):
        self.assertTrue(is_text_in_source_lang("你好世界", "zh"))
        self.assertTrue(is_text_in_source_lang("こんにちは", "ja"))
        self.assertTrue(is_text_in_source_lang("안녕하세요", "ko"))
        self.assertFalse(is_text_in_source_lang("Hello world", "zh"))

    def test_language_detection_auto(self):
        self.assertTrue(is_text_in_source_lang("Any language string", "auto"))
        self.assertTrue(is_text_in_source_lang("Привет", "auto"))

    def test_image_hash_caching(self):
        engine = ScreenOcrEngine()
        img1 = np.zeros((100, 100, 3), dtype=np.uint8)
        img2 = np.zeros((100, 100, 3), dtype=np.uint8)
        img3 = np.ones((100, 100, 3), dtype=np.uint8) * 255

        hash1 = engine.compute_image_hash(img1)
        hash2 = engine.compute_image_hash(img2)
        hash3 = engine.compute_image_hash(img3)

        self.assertEqual(hash1, hash2)
        self.assertNotEqual(hash1, hash3)

if __name__ == "__main__":
    unittest.main()
