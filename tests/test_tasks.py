import unittest
import tempfile
import os
from datetime import date
import memory
import task_service as service

class TasksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.previous = memory.DATABASE
        memory.DATABASE = os.path.join(self.tmp.name, "test.db")
        memory.init_db()
        self.legacy = memory.save_task("Existing task")
        service.migrate()

    def tearDown(self):
        memory.DATABASE = self.previous
        self.tmp.cleanup()

    def test_migration_preserves_tasks_and_is_repeatable(self):
        service.migrate()
        self.assertEqual(service.list_tasks()[0]["title"], "Existing task")
        self.assertEqual(service.list_tasks()[0]["priority"], "medium")

    def test_deadline_ranking_completion_reopen_delete(self):
        urgent = service.create({"title": "Application", "due_date": "2026-10-30", "priority": "low"})
        tasks = service.list_tasks(date(2026, 10, 31))
        self.assertEqual(service.recommendation(tasks)["task_id"], urgent)
        self.assertTrue(tasks[0]["overdue"])
        service.update(urgent, {"completed": True})
        self.assertEqual(service.recommendation(service.list_tasks())["task_id"], self.legacy)
        service.update(urgent, {"completed": False})
        self.assertIsNone(next(t for t in service.list_tasks() if t["id"] == urgent)["completed_at"])
        self.assertTrue(service.delete(urgent))
        self.assertFalse(service.delete(urgent))

    def test_validation(self):
        for data in [{"title": ""}, {"title": "x", "due_date": "2026-02-30"},
                     {"title": "x", "priority": "unknown"}, {"title": "x", "estimated_minutes": True}]:
            with self.assertRaises(ValueError):
                service.create(data)

if __name__ == "__main__":
    unittest.main()
