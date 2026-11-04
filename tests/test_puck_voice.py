"""Puck voice selection uses the existing Kokoro engine and cache safeguards."""

import unittest
from unittest.mock import patch

import tts_service


class PuckVoiceTests(unittest.TestCase):
    def test_selected_voice_is_puck(self):
        self.assertEqual(tts_service.VOICE, "am_puck")

    def test_uncached_speech_uses_puck_at_existing_speed(self):
        with patch.object(tts_service, "get_tts_model") as mocked_model:
            mocked_model.return_value.create.return_value = ("samples", 24000)
            generated = tts_service.generate_speech("Hello from MAVIS.")
        self.assertEqual(generated, ("samples", 24000))
        mocked_model.return_value.create.assert_called_once_with(
            "Hello from MAVIS.", voice="am_puck", speed=1.15, lang="en-us"
        )

    def test_cached_confirmation_also_uses_puck(self):
        tts_service._cached_confirmation_speech.cache_clear()
        try:
            with patch.object(tts_service, "get_tts_model") as mocked_model:
                mocked_model.return_value.create.return_value = ("samples", 24000)
                first = tts_service.generate_speech("Deleted and verified.")
                second = tts_service.generate_speech("Deleted and verified.")
            self.assertEqual(first, second)
            mocked_model.return_value.create.assert_called_once_with(
                "Deleted and verified.", voice="am_puck", speed=1.15, lang="en-us"
            )
        finally:
            tts_service._cached_confirmation_speech.cache_clear()


if __name__ == "__main__":
    unittest.main()
