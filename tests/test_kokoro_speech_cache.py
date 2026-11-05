"""Limited in-memory TTS cache never retains user-specific spoken content."""

import unittest
from unittest.mock import patch

import tts_service


class KokoroSpeechCacheTests(unittest.TestCase):
    def setUp(self):
        tts_service._cached_confirmation_speech.cache_clear()

    def tearDown(self):
        tts_service._cached_confirmation_speech.cache_clear()

    def test_fixed_confirmation_uses_cached_samples_on_second_request(self):
        samples = object()
        with patch.object(tts_service, "_synthesize_speech", return_value=(samples, 24000)) as synthesize:
            first = tts_service.generate_speech("Deleted and verified.")
            second = tts_service.generate_speech("Deleted and verified.")
        self.assertIs(first[0], samples)
        self.assertIs(second[0], samples)
        self.assertEqual(first[1], 24000)
        self.assertEqual(synthesize.call_count, 1)
        self.assertEqual(tts_service._cached_confirmation_speech.cache_info().hits, 1)

    def test_personalized_speech_is_never_cached(self):
        phrase = "Your private task is Review demo alpha."
        with patch.object(tts_service, "_synthesize_speech", return_value=("fresh", 24000)) as synthesize:
            tts_service.generate_speech(phrase)
            tts_service.generate_speech(phrase)
        self.assertEqual(synthesize.call_count, 2)
        self.assertEqual(tts_service._cached_confirmation_speech.cache_info().currsize, 0)

    def test_only_explicitly_approved_fixed_phrases_are_cached(self):
        expected = {
            "Task added and verified.",
            "Done. That task is completed and verified.",
            "Deleted and verified.",
            "Memory saved and verified.",
            "Memory deleted and verified.",
        }
        self.assertEqual(tts_service.CACHED_CONFIRMATIONS, expected)
        with patch.object(tts_service, "_synthesize_speech", return_value=("samples", 24000)) as synthesize:
            for phrase in expected:
                tts_service.generate_speech(phrase)
                tts_service.generate_speech(phrase)
        self.assertEqual(synthesize.call_count, len(expected))
        self.assertEqual(tts_service._cached_confirmation_speech.cache_info().currsize, len(expected))

    def test_invalid_input_is_rejected_before_caching(self):
        for value in ("", "   ", None, 17):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    tts_service.generate_speech(value)
        self.assertEqual(tts_service._cached_confirmation_speech.cache_info().currsize, 0)


if __name__ == "__main__":
    unittest.main()
