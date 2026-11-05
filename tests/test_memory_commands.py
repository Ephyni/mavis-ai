"""Pure unit tests for natural memory commands; no model API required."""

import unittest

from memory_commands import extract_memory_fact, makes_unverified_memory_claim


class MemoryCommandsTest(unittest.TestCase):
    def test_explicit_memory_commands(self):
        cases = {
            "MAVIS, remember that my presentation is on Friday.":
                "my presentation is on Friday",
            "Hey MAVIS, please remember my demo is tomorrow.":
                "my demo is tomorrow",
            "Can you remember that I prefer blue backgrounds?":
                "I prefer blue backgrounds",
            "Remember this: My test fruit is pineapple.":
                "My test fruit is pineapple",
            "MAVIS, save this for later: My code word is sunshine.":
                "My code word is sunshine",
            "Please save that my presentation is on Friday.":
                "my presentation is on Friday",
            "MAVIS, don't forget that my demo is tomorrow.":
                "my demo is tomorrow",
            "Make a note of this: My test number is 42.":
                "My test number is 42",
            "Keep in mind that I prefer short replies.":
                "I prefer short replies",
            "I want you to remember that my favorite color is teal.":
                "my favorite color is teal",
        }
        for message, expected in cases.items():
            with self.subTest(message=message):
                self.assertEqual(extract_memory_fact(message), expected)

    def test_missing_fact_asks_for_details(self):
        for message in ["MAVIS, remember this.", "Save this for later.",
                        "Remember that.", "Please make a note."]:
            with self.subTest(message=message):
                self.assertEqual(extract_memory_fact(message), "")

    def test_other_intents_not_changed(self):
        for message in [
            "My favorite fruit is pineapple.",
            "Do you remember my favorite fruit?",
            "Remember to buy apples tomorrow.",
            "Don't forget to call mom.",
            "Don't remember my secret.",
            "Please save my task to buy bananas.",
            "MAVIS, delete the memory about Friday.",
            "MAVIS, complete my Python task.",
            "Set a reminder for tomorrow.",
        ]:
            with self.subTest(message=message):
                self.assertIsNone(extract_memory_fact(message))

    def test_unverified_memory_promises(self):
        for reply in [
            "Got it! I'll remember sunshine as your test word.",
            "I've saved that to memory.",
            "I will remember it.",
            "I'll keep that in mind.",
            "Consider it saved.",
            "I’ll remember that for next time.",
        ]:
            with self.subTest(reply=reply):
                self.assertTrue(makes_unverified_memory_claim(reply))

    def test_normal_chat_responses(self):
        for reply in [
            "I can save that if you'd like.",
            "I remember that you mentioned a presentation before.",
            "I haven't saved that information.",
            "Would you like me to remember that?",
        ]:
            with self.subTest(reply=reply):
                self.assertFalse(makes_unverified_memory_claim(reply))


if __name__ == "__main__":
    unittest.main()
