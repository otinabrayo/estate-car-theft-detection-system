import sqlite3
from pathlib import Path


class EventLedger:

    def __init__(self, database_path):

        self.database_path = Path(database_path)

        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.connection = sqlite3.connect(
            str(self.database_path),
            timeout=30,
        )

        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS processed_events (
                event_id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL,
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        self.connection.commit()

    def is_processed(self, event_id):

        cursor = self.connection.execute(
            """
            SELECT 1
            FROM processed_events
            WHERE event_id = ?
            """,
            (str(event_id),),
        )

        return cursor.fetchone() is not None

    def mark_processed(self, event_id, idempotency_key):

        self.connection.execute(
            """
            INSERT OR IGNORE INTO processed_events (
                event_id,
                idempotency_key
            )
            VALUES (?, ?)
            """,
            (
                str(event_id),
                str(idempotency_key),
            ),
        )

        self.connection.commit()

    def close(self):
        self.connection.close()
