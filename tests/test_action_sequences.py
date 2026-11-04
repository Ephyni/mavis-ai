"""Regression tests for consecutive actions using a temporary SQLite database.

The tests never connect to the Muse API or change the user's mavis.db.
"""

import importlib
import os
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import memory


class ConsecutiveActionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.original_database = memory.DATABASE
        memory.DATABASE = os.path.join(cls.temporary.name, "isolated.db")
        cls.environment = patch.dict(os.environ, {
            "FLASK_SECRET_KEY": "test-only-session-secret",
            "MODEL_API_KEY": "test-only-no-remote-calls",
        })
        cls.environment.start()
        cls.module = importlib.import_module("app")
        cls.module.app.config.update(TESTING=True)

    @classmethod
    def tearDownClass(cls):
        memory.DATABASE = cls.original_database
        cls.environment.stop()
        cls.temporary.cleanup()

    def setUp(self):
        self.client = self.module.app.test_client()
        with sqlite3.connect(memory.DATABASE) as connection:
            for table in ("tasks", "memories", "memory_proposals", "task_activity"):
                connection.execute(f"DELETE FROM {table}")

    def chat(self, content):
        response = self.client.post("/api/chat", json={"message": content})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def test_two_completions_and_repeated_completion(self):
        alpha_id = memory.save_task("Review demo alpha")
        beta_id = memory.save_task("Review demo beta")
        first = self.chat("MAVIS, complete review demo alpha.")
        self.assertEqual(first["verification"]["status"], "verified")
        repeated = self.chat("MAVIS, complete review demo alpha.")
        self.assertIn("already completed", repeated["reply"])
        # Repeating the alpha request must not silently complete beta.
        status = {task["id"]: task["completed"] for task in memory.get_tasks()}
        self.assertEqual(status[alpha_id], 1)
        self.assertEqual(status[beta_id], 0)
        second = self.chat("MAVIS, complete review demo beta.")
        self.assertEqual(second["verification"]["status"], "verified")
        self.assertEqual(second["task_id"], beta_id)

    def test_consecutive_task_deletions_and_repeat(self):
        memory.save_task("Clear demo cache")
        memory.save_task("Archive demo notes")
        self.assertTrue(self.chat("MAVIS, delete clear demo cache.")["confirmation_required"])
        self.assertTrue(self.chat("Yes, delete it")["verified"])
        repeated = self.chat("MAVIS, delete clear demo cache.")
        self.assertIn("already deleted", repeated["reply"])
        self.assertTrue(self.chat("MAVIS, delete archive demo notes.")["confirmation_required"])
        self.assertTrue(self.chat("Yes")["verified"])
        self.assertEqual(memory.get_tasks(), [])

    def test_repeated_deletion_never_targets_similarly_named_task(self):
        alpha_id = memory.save_task("Archive demo alpha")
        beta_id = memory.save_task("Archive demo beta")
        self.assertTrue(self.chat("MAVIS, delete archive demo alpha.")["confirmation_required"])
        deleted = self.chat("Yes, delete it")
        self.assertTrue(deleted["verified"])
        self.assertEqual(deleted["task_id"], alpha_id)
        # A second alpha request must not queue beta for permanent deletion.
        repeated = self.chat("MAVIS, delete archive demo alpha.")
        self.assertIn("already deleted", repeated["reply"])
        remaining = memory.get_tasks()
        self.assertEqual([task["id"] for task in remaining], [beta_id])

    def test_full_task_list_with_concise_spoken_summary(self):
        memory.save_task("Review presentation notes")
        memory.save_task("Practice speaking to the judges")
        result = self.chat("MAVIS, show me my tasks")
        self.assertIn("Review presentation notes", result["reply"])
        self.assertIn("Practice speaking to the judges", result["reply"])
        self.assertEqual(len(result["tasks"]), 2)
        self.assertIn("2 tasks", result["spoken_reply"])
        self.assertNotIn("presentation notes", result["spoken_reply"])

    def test_verified_actions_speak_concisely_without_hiding_details(self):
        task_id = memory.save_task("Prepare presentation for the hackathon")
        completed = self.chat("MAVIS, complete prepare presentation for the hackathon")
        self.assertEqual(completed["verification"]["status"], "verified")
        self.assertIn("Prepare presentation for the hackathon", completed["reply"])
        self.assertLess(len(completed["spoken_reply"]), len(completed["reply"]))
        self.assertIn("verified", completed["spoken_reply"])

        task_id = memory.save_task("Erase temporary demo cache")
        confirmation = self.chat("MAVIS, delete erase temporary demo cache")
        self.assertTrue(confirmation["confirmation_required"])
        self.assertNotIn("spoken_reply", confirmation)
        deleted = self.chat("Yes, delete it")
        self.assertTrue(deleted["verified"])
        self.assertIn("Erase temporary demo cache", deleted["reply"])
        self.assertEqual(deleted["spoken_reply"], "Deleted and verified.")

    def test_verified_memory_speech_keeps_full_written_fact(self):
        requested = self.chat("MAVIS, remember that my secret demo word is pomegranate.")
        self.assertTrue(requested["pending_approval"])
        self.assertNotIn("spoken_reply", requested)
        saved = self.chat("Yes please")
        self.assertTrue(saved["verified"])
        self.assertIn("pomegranate", saved["reply"])
        self.assertEqual(saved["spoken_reply"], "Memory saved and verified.")

        requested = self.chat("MAVIS, forget my secret demo word is pomegranate.")
        self.assertTrue(requested["confirmation_required"])
        forgotten = self.chat("Yes please")
        self.assertTrue(forgotten["verified"])
        self.assertEqual(forgotten["spoken_reply"], "Memory deleted and verified.")

    def test_two_memory_deletions_and_repeated_name(self):
        memory.save_memory("Sapphire demo phrase")
        memory.save_memory("Turquoise demo phrase")
        self.assertTrue(self.chat("MAVIS, forget sapphire demo phrase.")["confirmation_required"])
        self.assertTrue(self.chat("Yes")["verified"])
        again = self.chat("MAVIS, forget sapphire demo phrase.")
        self.assertIn("already deleted", again["reply"])
        self.assertTrue(self.chat("MAVIS, forget turquoise demo phrase.")["confirmation_required"])
        self.assertTrue(self.chat("Yes")["verified"])
        self.assertEqual(memory.get_memories(), [])

    def test_unmatched_memory_requires_name_then_confirmation(self):
        memory.save_memory("Silver lantern stage cue")
        no_match = self.chat("MAVIS, forget my memory about moonlight.")
        self.assertEqual(no_match["intent"], "delete_memory")
        self.assertFalse(no_match["confirmation_required"])
        not_a_confirmation = self.chat("Yes")
        self.assertEqual(not_a_confirmation["intent"], "delete_memory")
        self.assertEqual(len(memory.get_memories()), 1)
        selected = self.chat("Silver lantern stage cue")
        self.assertTrue(selected["confirmation_required"])
        cancelled = self.chat("No")
        self.assertTrue(cancelled["cancelled"])
        self.assertEqual(len(memory.get_memories()), 1)

    def test_hey_mavis_create_cancels_unmatched_delete_selection(self):
        gum_id = memory.save_task("Buy gum")
        unmatched = self.chat("Hey Mavis, delete by gum from the active tasks.")
        self.assertEqual(unmatched["intent"], "delete_task")
        self.assertFalse(unmatched["confirmation_required"])

        stages = []
        def fake_model_response(_client, stage, **_kwargs):
            stages.append(stage)
            self.assertEqual(stage, "task title extraction")
            return SimpleNamespace(output_text="Buy soda")

        with patch.object(self.module, "_timed_model_response",
                          side_effect=fake_model_response):
            created = self.chat("Hey Mavis, create a task to buy soda.")
        self.assertEqual(created["intent"], "add_task")
        self.assertIn("Buy soda", created["reply"])
        self.assertEqual(stages, ["task title extraction"])
        saved = {task["id"]: task["title"] for task in memory.get_tasks()}
        self.assertEqual(saved[gum_id], "Buy gum")
        self.assertIn("Buy soda", saved.values())
        with self.client.session_transaction() as session:
            self.assertNotIn("pending_task_selection", session)
            self.assertNotIn("pending_delete_task_id", session)

    def test_new_creation_replaces_selected_delete_confirmation(self):
        gum_id = memory.save_task("Buy gum")
        selected = self.chat("MAVIS, delete buy gum.")
        self.assertTrue(selected["confirmation_required"])

        with patch.object(
            self.module,
            "_timed_model_response",
            return_value=SimpleNamespace(output_text="Buy soda"),
        ):
            created = self.chat("Hey MAVIS, actually create a task to buy soda.")
        self.assertEqual(created["intent"], "add_task")
        self.assertIn("Buy soda", created["reply"])
        saved = {task["id"]: task["title"] for task in memory.get_tasks()}
        self.assertEqual(saved[gum_id], "Buy gum")
        self.assertIn("Buy soda", saved.values())
        with self.client.session_transaction() as session:
            self.assertNotIn("pending_delete_task_id", session)
            self.assertNotIn("pending_task_selection", session)

    def test_new_memory_command_replaces_stale_task_confirmation(self):
        task_id = memory.save_task("Prepare demo clips")
        self.assertTrue(self.chat("Delete prepare demo clips")["confirmation_required"])
        requested = self.chat("MAVIS, remember that my demo code is glacier.")
        self.assertTrue(requested["pending_approval"])
        self.assertTrue(self.chat("Yes, please")["verified"])
        self.assertTrue(any(item["id"] == task_id for item in memory.get_tasks()))
        self.assertEqual(len(memory.get_memories()), 1)

    def test_ambiguous_memory_requires_selection(self):
        memory.save_memory("Demo phrase sapphire alpha")
        memory.save_memory("Demo phrase sapphire beta")
        response = self.chat("Forget demo phrase sapphire.")
        self.assertFalse(response["confirmation_required"])
        self.assertEqual(len(memory.get_memories()), 2)
        self.assertFalse(self.chat("Yes")["confirmation_required"])
        self.assertEqual(len(memory.get_memories()), 2)
        self.assertTrue(self.chat("The first one")["confirmation_required"])
        self.assertTrue(self.chat("Yes")["verified"])
        self.assertEqual(len(memory.get_memories()), 1)

    def test_delete_it_confirms_only_a_selected_task(self):
        memory.save_task("Remove temporary cache")
        request = self.chat("MAVIS, delete remove temporary cache.")
        self.assertTrue(request["confirmation_required"])
        self.assertTrue(self.chat("Delete it.")["verified"])
        self.assertEqual(memory.get_tasks(), [])

    def test_forget_it_cancels_approved_delete_request(self):
        memory.save_task("Keep flight notes")
        self.assertTrue(self.chat("MAVIS, delete keep flight notes.")["confirmation_required"])
        self.assertTrue(self.chat("Forget it.")["cancelled"])
        self.assertEqual(len(memory.get_tasks()), 1)

    def test_save_it_does_not_approve_task_deletion(self):
        memory.save_task("Retain test record")
        self.assertTrue(self.chat("MAVIS, delete retain test record.")["confirmation_required"])
        answer = self.chat("Save it.")
        self.assertTrue(answer["confirmation_required"])
        self.assertEqual(len(memory.get_tasks()), 1)


if __name__ == "__main__":
    unittest.main()
