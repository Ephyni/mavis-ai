
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

