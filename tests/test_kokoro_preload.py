"""Preloading must reuse the cached speech model and leave Flask startup safe."""

import unittest
from unittest.mock import patch

import tts_service


class KokoroPreloadTests(unittest.TestCase):
    def tearDown(self):
        tts_service.get_tts_model.cache_clear()

    def test_preload_reuses_model_for_later_responses(self):
        # A mocked model verifies one initialization without loading ONNX weights.
        tts_service.get_tts_model.cache_clear()
        with patch.object(tts_service, "Kokoro") as kokoro:
            self.assertTrue(tts_service.preload_tts_model())
            cached = tts_service.get_tts_model()
            self.assertIs(cached, kokoro.return_value)
            kokoro.assert_called_once()

    def test_preload_failure_does_not_abort_application_startup(self):
        tts_service.get_tts_model.cache_clear()
        with patch.object(tts_service, "Kokoro", side_effect=RuntimeError("test error")):
            self.assertFalse(tts_service.preload_tts_model())


if __name__ == "__main__":
    unittest.main()
