
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

    connection.commit()
    connection.close()

    print("MAVIS memory database initialized!")

    
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

def save_task(title):
    connection = sqlite3.connect(DATABASE)

    cursor = connection.execute(
        "INSERT INTO tasks (title) VALUES (?)",
        (title,)
    )

    connection.commit()
    task_id = cursor.lastrowid
    connection.close()

    return task_id

def get_tasks():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row

    cursor = connection.execute(
        "SELECT id, title, completed FROM tasks ORDER BY id DESC"
    )

    tasks = [dict(row) for row in cursor.fetchall()]
    connection.close()

    return tasks


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

        connection.commit()

        # Report whether SQLite modified a matching record.
        # Independent verification will check the persisted state.
        return cursor.rowcount > 0

    finally:
        # Release the database connection even if execution fails.
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
