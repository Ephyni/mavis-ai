"""Persistent tasks and explainable deadline-based recommendations."""
from datetime import datetime, date
import sqlite3
from contextlib import contextmanager
import memory

PRIORITIES = {"low": 1, "medium": 2, "high": 3, "critical": 4}

@contextmanager
def connect():
    db = sqlite3.connect(memory.DATABASE)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()

def migrate():
    with connect() as db:
        columns = {r["name"] for r in db.execute("PRAGMA table_info(tasks)")}
        for name, kind in [("due_date", "TEXT"), ("priority", "TEXT DEFAULT 'medium'"),
                           ("estimated_minutes", "INTEGER DEFAULT 30"), ("completed_at", "TEXT")]:
            if name not in columns:
                db.execute(f"ALTER TABLE tasks ADD COLUMN {name} {kind}")

def validate(data):
    title = data.get("title")
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 500:
        raise ValueError("Enter a task title between 1 and 500 characters.")
    priority = data.get("priority", "medium")
    if not isinstance(priority, str) or priority not in PRIORITIES:
        raise ValueError("Choose a valid priority.")
    due = data.get("due_date") or None
    if due is not None:
        if not isinstance(due, str):
            raise ValueError("Use a date in YYYY-MM-DD format.")
        try:
            due = date.fromisoformat(due).isoformat()
        except ValueError:
            raise ValueError("Use a valid date in YYYY-MM-DD format.")
    minutes = data.get("estimated_minutes", 30)
    if type(minutes) is not int or not 1 <= minutes <= 10080:
        raise ValueError("Estimated time must be 1–10080 minutes.")
    return title.strip(), due, priority, minutes

def list_tasks(today=None):
    today = today or date.today()
    with connect() as db:
        tasks = [dict(r) for r in db.execute("SELECT * FROM tasks")]
    for task in tasks:
        days = (date.fromisoformat(task["due_date"]) - today).days if task["due_date"] else None
        task["overdue"] = days is not None and days < 0 and not task["completed"]
        task["due_today"] = days == 0
        task["urgency"] = ("critical" if days is not None and days <= 0 else
                           "high" if days is not None and days <= 2 else task["priority"])
        task["rank"] = max(PRIORITIES[task["priority"]], PRIORITIES[task["urgency"]])
        task["urgency"] = next(name for name, rank in PRIORITIES.items() if rank == task["rank"])
    tasks.sort(key=lambda t: (t["completed"], -t["rank"], t["due_date"] or "9999-12-31", t["id"]))
    return tasks

def recommendation(tasks):
    task = next((t for t in tasks if not t["completed"]), None)
    if not task:
        return None
    reason = ("It is overdue." if task["overdue"] else "It is due today." if task["due_today"]
              else f"It is due on {task['due_date']}." if task["due_date"]
              else "It has the highest priority among your open tasks.")
    return {"task_id": task["id"], "title": task["title"],
            "reason": reason + f" Priority: {task['priority']}. Allow about {task['estimated_minutes']} minutes."}

def create(data):
    values = validate(data)
    with connect() as db:
        return db.execute("INSERT INTO tasks (title, due_date, priority, estimated_minutes) VALUES (?, ?, ?, ?)", values).lastrowid

def update(task_id, data):
    with connect() as db:
        row = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            return False
        merged = dict(row)
        merged.update(data)
        values = validate(merged)
        completed = merged["completed"]
        if type(completed) not in (int, bool) or completed not in (0, 1):
            raise ValueError("Completed must be true or false.")
        completed_at = (row["completed_at"] or datetime.now().isoformat()) if completed else None
        db.execute("UPDATE tasks SET title=?, due_date=?, priority=?, estimated_minutes=?, completed=?, completed_at=? WHERE id=?",
                   (*values, int(completed), completed_at, task_id))
        return True

def delete(task_id):
    with connect() as db:
        return db.execute("DELETE FROM tasks WHERE id=?", (task_id,)).rowcount > 0
