
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
