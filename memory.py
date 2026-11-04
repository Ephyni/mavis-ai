
import sqlite3

DATABASE = "mavis.db"

def init_db():
    connection = sqlite3.connect(DATABASE)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            category TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS memory_proposals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            category TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            completed INTEGER NOT NULL DEFAULT 0
        )
    """)

    # Events remain available even after a task itself is deleted.
    # The increasing event ID defines a stable newest-first activity order.
    connection.execute("""
        CREATE TABLE IF NOT EXISTS task_activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            action TEXT NOT NULL CHECK (
                action IN ('created', 'completed', 'deleted', 'reopened')
            ),
            happened_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Include memory deletions in the same chronological event stream.
    activity_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(task_activity)")
    }
    if "entity_type" not in activity_columns:
        connection.execute(
            "ALTER TABLE task_activity "
            "ADD COLUMN entity_type TEXT NOT NULL DEFAULT 'task'"
        )

    # Persist reminders so they survive application restarts.
    connection.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message TEXT NOT NULL,
            due_at TEXT NOT NULL,
            notified INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    connection.commit()
    connection.close()

    print("MAVIS memory database initialized!")


def save_reminder(message, due_at):
    """Persist a reminder with a UTC due time."""
    from datetime import datetime, timezone

    if not isinstance(message, str) or not message.strip():
        raise ValueError("Reminder message is required.")

    if not isinstance(due_at, str):
        raise ValueError("A UTC due time is required.")

    due = datetime.fromisoformat(due_at.replace("Z", "+00:00"))

    if due.tzinfo is None:
        raise ValueError("Reminder due time must include a timezone.")

    due_utc = due.astimezone(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    connection = sqlite3.connect(DATABASE)

    try:
        cursor = connection.execute(
            "INSERT INTO reminders (message, due_at) VALUES (?, ?)",
            (message.strip(), due_utc)
        )
        connection.commit()
        return cursor.lastrowid
    finally:
        connection.close()

def verify_reminder_saved(reminder_id, expected_message, expected_due_at):
    """Independently verify a reminder's persisted SQLite values."""
    from datetime import datetime, timezone

    if not isinstance(expected_message, str) or not isinstance(expected_due_at, str):
        return False

    try:
        due = datetime.fromisoformat(
            expected_due_at.replace("Z", "+00:00")
        )
        if due.tzinfo is None:
            return False

        expected_utc = due.astimezone(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    except ValueError:
        return False

    connection = sqlite3.connect(DATABASE)

    try:
        record = connection.execute(
            "SELECT message, due_at FROM reminders WHERE id = ?",
            (reminder_id,)
        ).fetchone()

        return (
            record is not None
            and record[0] == expected_message.strip()
            and record[1] == expected_utc
        )
    finally:
        connection.close()

def get_reminders():
    """Retrieve saved reminders for conversational recall."""
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row

    try:
        cursor = connection.execute(
            """
            SELECT id, message, due_at, notified
            FROM reminders
            ORDER BY id DESC
            """
        )

        return [dict(row) for row in cursor.fetchall()]
    finally:
        connection.close()

def get_due_reminders(cutoff_utc=None):
    """Retrieve unnotified reminders due by the specified UTC time."""
    from datetime import datetime, timezone

    if cutoff_utc is None:
        cutoff_utc = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row

    try:
        cursor = connection.execute(
            """
            SELECT id, message, due_at
            FROM reminders
            WHERE notified = 0
              AND due_at <= ?
            ORDER BY due_at ASC
            """,
            (cutoff_utc,),
        )

        return [dict(row) for row in cursor.fetchall()]
    finally:
        connection.close()

def mark_reminder_notified(reminder_id):
    """Acknowledge a due reminder once after notification delivery."""
    from datetime import datetime, timezone

    now_utc = datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    connection = sqlite3.connect(DATABASE)

    try:
        cursor = connection.execute(
            """
            UPDATE reminders
            SET notified = 1
            WHERE id = ?
              AND notified = 0
              AND due_at <= ?
            """,
            (reminder_id, now_utc),
        )

        connection.commit()
        return cursor.rowcount == 1
    finally:
        connection.close()

    
def save_memory(content, category="general"):
    connection = sqlite3.connect(DATABASE)

    cursor = connection.execute(
        """
        INSERT INTO memories (content, category)
        VALUES (?, ?)
        """,
        (content, category)
    )

    connection.commit()
    memory_id = cursor.lastrowid
    connection.close()

    return memory_id


def get_memories():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row

    cursor = connection.execute(
        "SELECT * FROM memories ORDER BY id DESC"
    )

    memories = [dict(row) for row in cursor.fetchall()]

    connection.close()

    return memories


def delete_memory(memory_id):
    """Delete a saved memory and approved proposal copy, without logging its text."""
    if type(memory_id) is not int or memory_id <= 0:
        return False
    connection = sqlite3.connect(DATABASE)
    try:
        connection.execute("BEGIN IMMEDIATE")
        stored = connection.execute(
            "SELECT content, category FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
        if stored is None:
            connection.rollback()
            return False
        removed = connection.execute(
            "DELETE FROM memories WHERE id = ?", (memory_id,)
        ).rowcount
        if removed != 1:
            connection.rollback()
            return False

        # Approved proposals retain a copy of the memory's original text.
        connection.execute(
            """
            DELETE FROM memory_proposals
            WHERE status = 'approved' AND content = ? AND category = ?
            """,
            (stored[0], stored[1]),
        )
        # Do not write forgotten content to history: only log the event.
        connection.execute(
            """
            INSERT INTO task_activity (task_id, title, action, entity_type)
            VALUES (?, 'A saved memory was removed', 'deleted', 'memory')
            """,
            (memory_id,),
        )
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def verify_memory_deleted(memory_id):
    """Independently verify that this ID no longer exists in saved memories."""
    if type(memory_id) is not int or memory_id <= 0:
        return False
    connection = sqlite3.connect(DATABASE)
    try:
        return connection.execute(
            "SELECT 1 FROM memories WHERE id = ?", (memory_id,)
        ).fetchone() is None
    finally:
        connection.close()


def propose_memory(content, category="general"):
    connection = sqlite3.connect(DATABASE)

    cursor = connection.execute(
        """
        INSERT INTO memory_proposals (content, category)
        VALUES (?, ?)
        """,
        (content, category)
    )

    connection.commit()
    proposal_id = cursor.lastrowid
    connection.close()

    return proposal_id


def get_proposals():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row

    cursor = connection.execute(
        """
        SELECT * FROM memory_proposals
        WHERE status = 'pending'
        ORDER BY id DESC
        """
    )

    proposals = [dict(row) for row in cursor.fetchall()]

    connection.close()

    return proposals


def approve_memory(proposal_id):
    connection = sqlite3.connect(DATABASE)

    try:
        connection.execute("BEGIN IMMEDIATE")

        cursor = connection.execute(
            """
            SELECT content, category
            FROM memory_proposals
            WHERE id = ? AND status = 'pending'
            """,
            (proposal_id,)
        )

        proposal = cursor.fetchone()

        if proposal is None:
            connection.rollback()
            return None

        cursor = connection.execute(
            """
            INSERT INTO memories (content, category)
            VALUES (?, ?)
            """,
            proposal
        )

        memory_id = cursor.lastrowid

        connection.execute(
            """
            UPDATE memory_proposals
            SET status = 'approved'
            WHERE id = ?
            """,
            (proposal_id,)
        )

        connection.commit()
        return memory_id

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def reject_memory(proposal_id):
    connection = sqlite3.connect(DATABASE)

    try:
        cursor = connection.execute(
            """
            UPDATE memory_proposals
            SET status = 'rejected'
            WHERE id = ? AND status = 'pending'
            """,
            (proposal_id,)
        )

        connection.commit()
        return cursor.rowcount > 0

    finally:
        connection.close()

def log_task_activity(connection, task_id, title, action):
    """Append a real task event within the caller's SQLite transaction."""
    if action not in {"created", "completed", "deleted", "reopened"}:
        raise ValueError("Unsupported task activity action.")
    connection.execute(
        "INSERT INTO task_activity (task_id, title, action) VALUES (?, ?, ?)",
        (task_id, title, action),
    )


def get_task_activity(limit=2):
    """Return the latest persisted task actions, newest event first."""
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("Activity limit must be between 1 and 20.")

    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT id, task_id, title, action, happened_at, entity_type
            FROM task_activity
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def save_task(title):
    connection = sqlite3.connect(DATABASE)
    try:
        cursor = connection.execute(
            "INSERT INTO tasks (title) VALUES (?)",
            (title,)
        )
        task_id = cursor.lastrowid
        log_task_activity(connection, task_id, title, "created")
        connection.commit()
        return task_id
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_tasks(completed=None):
    """Retrieve tasks, optionally filtered by completion status."""
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row

    try:
        if completed is None:
            cursor = connection.execute(
                "SELECT id, title, completed FROM tasks ORDER BY id DESC"
            )
        else:
            cursor = connection.execute(
                """
                SELECT id, title, completed
                FROM tasks
                WHERE completed = ?
                ORDER BY id DESC
                """,
                (int(completed),),
            )

        return [dict(row) for row in cursor.fetchall()]
    finally:
        connection.close()


def verify_task_created(task_id, expected_title):
    """Confirm that a newly created task was persisted in SQLite."""
    return any(
        task["id"] == task_id and task["title"] == expected_title
        for task in get_tasks()
    )


def complete_task(task_id):
    """
    Mark an existing task as completed in SQLite.

    This operation supports MAVIS's agentic task execution
    workflow. The task is identified by its database ID,
    ensuring that updates target a specific record.

    Returns:
        bool: True if a task was updated, otherwise False.
    """

    connection = sqlite3.connect(DATABASE)

    try:
        # Restrict updates to the requested task ID and prevent
        # unnecessary modifications to already completed tasks.
        cursor = connection.execute(
            """
            UPDATE tasks
            SET completed = 1
            WHERE id = ? AND completed = 0
            """,
            (task_id,)
        )

        if cursor.rowcount > 0:
            row = connection.execute(
                "SELECT title FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            log_task_activity(connection, task_id, row[0], "completed")
        connection.commit()

        # Report whether SQLite modified a matching record.
        # Independent verification will check the persisted state.
        return cursor.rowcount > 0

    finally:
        # Release the database connection even if execution fails.
        connection.close()


def delete_task(task_id):
    """Permanently delete a task and verify its removal from SQLite."""
    if type(task_id) is not int or task_id <= 0:
        return False

    connection = sqlite3.connect(DATABASE)

    try:
        # Preserve the title before removing the record permanently.
        prior = connection.execute(
            "SELECT title FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if prior is None:
            return False

        # Target exactly one task using its unique database ID.
        cursor = connection.execute(
            "DELETE FROM tasks WHERE id = ?",
            (task_id,)
        )

        if cursor.rowcount != 1:
            connection.rollback()
            return False

        # Confirm the record is absent before committing the deletion.
        remaining = connection.execute(
            "SELECT 1 FROM tasks WHERE id = ?",
            (task_id,)
        ).fetchone()

        if remaining is not None:
            connection.rollback()
            return False

        log_task_activity(connection, task_id, prior[0], "deleted")
        connection.commit()
        return True

    except sqlite3.Error:
        connection.rollback()
        raise

    finally:
        connection.close()

def verify_task_deleted(task_id):
    """Independently verify that a task is absent from persisted SQLite data."""
    if type(task_id) is not int or task_id <= 0:
        return False

    connection = sqlite3.connect(DATABASE)

    try:
        # Query committed database state independently of the deletion operation.
        remaining = connection.execute(
            "SELECT 1 FROM tasks WHERE id = ?",
            (task_id,)
        ).fetchone()

        return remaining is None

    finally:
        connection.close()


def verify_task_completed(task_id):
    """
    Independently verify that a task is marked complete in SQLite.

    This verifier reads the persisted database state rather than
    trusting the Builder's reported execution result. It prevents
    MAVIS from confirming task completion without supporting evidence.

    Returns:
        bool: True when the task exists and is complete;
        otherwise False.
    """

    connection = sqlite3.connect(DATABASE)

    try:
        # Read the persisted state using the specific task ID.
        cursor = connection.execute(
            "SELECT completed FROM tasks WHERE id = ?",
            (task_id,)
        )

        task = cursor.fetchone()

        # Reject missing records and incomplete tasks to prevent
        # unsupported success confirmations.
        return task is not None and task[0] == 1

    finally:
        # Ensure database resources are released after verification.
        connection.close()


def run_verification(action, task_id):
    """
    Route task verification requests to the appropriate
    deterministic database check.

    This provides a centralized verification entry point
    for MAVIS's Builder–Verifier architecture. Unsupported
    actions are rejected rather than assumed successful.
    """

    if action == "complete_task":
        return verify_task_completed(task_id)

    return False


def execute_verified_task_completion(task_id):
    """
    Coordinate task completion and independent verification.

    The Builder updates the task in SQLite, while the Verifier
    checks the persisted result. Structured execution events
    provide traceable outcomes for MAVIS's productivity panel.

    A successful response requires both execution and
    verification to pass.
    """

    events = []

    # Validate the task identifier before attempting a database update.
    if type(task_id) is not int or task_id <= 0:
        return {
            "status": "failed",
            "events": [{"stage": "validation", "status": "failed"}]
        }

    events.append({"stage": "validation", "status": "passed"})

    try:
        # Execute the Builder's database operation.
        updated = complete_task(task_id)

        if not updated:
            events.append({"stage": "execution", "status": "failed"})
            return {"status": "failed", "events": events}

        events.append({"stage": "execution", "status": "passed"})

        # Independently verify the persisted database state.
        verified = run_verification("complete_task", task_id)

        events.append({
            "stage": "verification",
            "status": "passed" if verified else "failed"
        })

        return {
            "status": "verified" if verified else "failed",
            "events": events
        }

    except Exception:
        # Never report success when execution or verification fails.
        events.append({"stage": "operation", "status": "failed"})
        return {"status": "failed", "events": events}
