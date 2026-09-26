import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest
import numpy as np
from core.ocr_engine import ScreenOcrEngine
from core.translator import matches_source_language, detect_language_heuristic, translate_and_detect_lang

class TestScreenOcr(unittest.TestCase):
    def test_serbian_detection_and_english_rejection(self):
        # Serbian Cyrillic must match
        self.assertTrue(matches_source_language("sr", "Добар дан како сте", "sr"))
        self.assertTrue(matches_source_language("sr", "пријатељу", "sr"))

        # Serbian Latin with diacritics must match
        self.assertTrue(matches_source_language("hr", "Dobar dan kako ste", "sr"))
        self.assertTrue(matches_source_language(None, "Kako si danas brate?", "sr"))

        # English gaming & common text MUST be REJECTED when 'sr' is selected!
        self.assertFalse(matches_source_language("en", "Attack speed +25 and armor +5", "sr"))
        self.assertFalse(matches_source_language("en", "Settings and Options", "sr"))
        self.assertFalse(matches_source_language("en", "Play Dota 2 Match", "sr"))
        self.assertFalse(matches_source_language("en", "Victory", "sr"))
        self.assertFalse(matches_source_language("en", "Inventory items", "sr"))

    def test_english_matching(self):
        self.assertTrue(matches_source_language("en", "Press Start to Continue", "en"))
        self.assertFalse(matches_source_language("sr", "Добар дан", "en"))
        self.assertFalse(matches_source_language("ru", "Привет мир", "en"))

    def test_heuristic_detection(self):
        self.assertEqual(detect_language_heuristic("Добар дан Ђорђе"), "sr")
        self.assertEqual(detect_language_heuristic("Kako si brate?"), "sr")
        self.assertEqual(detect_language_heuristic("Attack speed and health"), "en")

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
