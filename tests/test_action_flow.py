"""Pure regression checks for MAVIS's single pending-action state."""

import unittest
from action_flow import clear_pending, set_pending, confirmation_answer


class PendingActionTest(unittest.TestCase):
    def test_replace_and_clear_all_previous_state(self):
        state = {"pending_delete_task_id": 9}
        set_pending(state, "delete_task", "confirm", target_id=9)
        self.assertNotIn("pending_delete_task_id", state)
        set_pending(state, "save_memory", "confirm", target_id=4)
        self.assertEqual(state["pending_action"]["kind"], "save_memory")
        self.assertEqual(state["pending_action"]["target_id"], 4)
        clear_pending(state)
        self.assertNotIn("pending_action", state)

    def test_selection_cannot_execute_without_selection(self):
        state = {}
        with self.assertRaises(ValueError):
            set_pending(state, "delete_memory", "confirm")
        set_pending(state, "delete_memory", "select", option_ids=[5, 4, 3, 2, 1])
        self.assertEqual(state["pending_action"]["option_ids"], [5, 4, 3, 2])

    def test_approval_and_cancellation_words(self):
        for phrase in ("Yes.", "Yes, please.", "Yes, delete it.", "MAVIS, yes", "Yep"):
            with self.subTest(phrase=phrase):
                self.assertEqual(confirmation_answer(phrase), "yes")
        for phrase in ("No", "Cancel.", "No, don't delete it.", "Never mind"):
            with self.subTest(phrase=phrase):
                self.assertEqual(confirmation_answer(phrase), "no")
        for phrase in (
            "Mavis forget sapphire", "Complete my demo task",
            "I guess yes, if you are sure", "The first one", "My other memory",
        ):
            with self.subTest(phrase=phrase):
                self.assertIsNone(confirmation_answer(phrase))


if __name__ == "__main__":
    unittest.main()
