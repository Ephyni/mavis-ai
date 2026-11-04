"""Regression checks for deterministic spoken commands, without API calls."""
import ast
import re
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "app.py"
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))
NAMES = {"_explicit_task_intent", "_task_words", "_task_matches",
         "_memory_deletion_subject", "_saved_memory_matches"}
CONSTANTS = {"_TASK_COMMAND_WORDS", "_TASK_TITLE_FILLERS", "_MEMORY_FILLERS"}
nodes = []
for node in TREE.body:
    if isinstance(node, ast.FunctionDef) and node.name in NAMES:
        nodes.append(node)
    elif isinstance(node, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id in CONSTANTS for t in node.targets
    ):
        nodes.append(node)
helpers = {"re": re}
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), helpers)


class CommandRoutingTests(unittest.TestCase):
    def test_complete_phrases(self):
        for phrase in ("MAVIS complete my Python task", "I finished my Python task",
                       "I'm done with my Python task", "I just did my Python task",
                       "Cross off my Python task"):
            with self.subTest(phrase=phrase):
                self.assertEqual(helpers["_explicit_task_intent"](phrase), "complete_task")

    def test_delete_phrases(self):
        for phrase in ("MAVIS delete my Python task", "Get rid of my Python task",
                       "Please remove the Python task"):
            with self.subTest(phrase=phrase):
                self.assertEqual(helpers["_explicit_task_intent"](phrase), "delete_task")

    def test_questions_and_negations_not_actions(self):
        for phrase in ("How do I delete a task?", "Don't delete my task",
                       "Remind me to finish my task"):
            with self.subTest(phrase=phrase):
                self.assertIsNone(helpers["_explicit_task_intent"](phrase))

    def test_matching_and_duplicate_safety(self):
        tasks = [{"id": 1, "title": "buy bananas", "completed": 0},
                 {"id": 2, "title": "Python assignment", "completed": 0}]
        selected, _ = helpers["_task_matches"]("I finished buying bananas", tasks)
        self.assertEqual(selected["id"], 1)
        selected, _ = helpers["_task_matches"]("I'm done with my Python assignment", tasks)
        self.assertEqual(selected["id"], 2)
        selected, matches = helpers["_task_matches"](
            "Complete my Python assignment", tasks + [dict(tasks[1], id=3)])
        self.assertIsNone(selected)
        self.assertEqual(len(matches), 2)

    def test_distinguishing_task_words_are_mandatory(self):
        tasks = [
            {"id": 10, "title": "Review demo alpha", "completed": 0},
            {"id": 11, "title": "Review demo beta", "completed": 0},
        ]
        selected, matches = helpers["_task_matches"](
            "MAVIS complete review demo alpha", [tasks[1]]
        )
        self.assertIsNone(selected)
        self.assertEqual(matches, [])
        selected, matches = helpers["_task_matches"](
            "MAVIS complete review demo", tasks
        )
        self.assertIsNone(selected)
        self.assertEqual(len(matches), 2)
        # A unique short name remains a supported natural-language request.
        selected, matches = helpers["_task_matches"](
            "MAVIS complete beta", tasks
        )
        self.assertEqual(selected["id"], 11)
        self.assertEqual(len(matches), 1)

    def test_forgetting_phrases(self):
        for phrase in ("Mavis forget my next demo test word is sapphire",
                       "Can you forget my next demo test word is sapphire",
                       "I want you to forget my next demo test word is sapphire",
                       "Remove the saved memory about sapphire",
                       "Get rid of my memory about sapphire",
                       "Delete the memories about sapphire",
                       "Erase my stored memory about pineapple"):
            with self.subTest(phrase=phrase):
                self.assertIsNotNone(helpers["_memory_deletion_subject"](phrase))
        self.assertIsNone(helpers["_memory_deletion_subject"](
            "MAVIS don't forget my demo test word"))

    def test_memory_match_and_duplicates(self):
        saved = [{"id": 4, "content": "my next demo test word is sapphire"},
                 {"id": 5, "content": "my favorite fruit is pineapple"}]
        subject = helpers["_memory_deletion_subject"](
            "Mavis forget my next demo test word is sapphire")
        selected, _ = helpers["_saved_memory_matches"](subject, saved)
        self.assertEqual(selected["id"], 4)
        selected, matches = helpers["_saved_memory_matches"](
            "sapphire", saved + [dict(saved[0], id=6)])
        self.assertIsNone(selected)
        self.assertEqual(len(matches), 2)


if __name__ == "__main__":
    unittest.main()
