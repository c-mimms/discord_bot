import sqlite3
import os
import contextlib
from typing import Generator

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
DB_PATH = os.environ.get("GEMINI_DB_PATH", os.path.join(PROJECT_ROOT, "gemini.db"))

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')
    return conn

@contextlib.contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with get_db() as conn:
        # ── contexts ──────────────────────────────────────────────────────────
        # UUID-keyed sessions. reply_thread_id is the Discord thread that owns
        # this context — used to route incoming thread messages here.
        conn.execute('''
            CREATE TABLE IF NOT EXISTS contexts (
                id               TEXT PRIMARY KEY,  -- uuid
                reply_channel_id INTEGER,           -- channel to reply to (before thread exists)
                reply_thread_id  INTEGER,           -- Discord thread owned by this context
                status           TEXT DEFAULT 'idle',
                current_pid      INTEGER,
                created_at       REAL,
                updated_at       REAL
            )
        ''')

        # ── messages ──────────────────────────────────────────────────────────
        # Append-only log of every Discord event. channel_id/thread_id are
        # informational only. Context membership is in context_messages.
        conn.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id                  TEXT PRIMARY KEY,  -- uuid
                author              TEXT NOT NULL,
                content             TEXT NOT NULL,
                source              TEXT NOT NULL,     -- 'user' | 'bot'
                timestamp           REAL NOT NULL,
                channel_id          INTEGER,           -- origin channel
                thread_id           INTEGER,           -- origin thread
                delivered           BOOLEAN DEFAULT 0,
                delivered_at        REAL,
                delivery_status     TEXT DEFAULT 'pending', -- 'pending' | 'sent' | 'failed'
                delivery_error      TEXT,
                raw_discord_payload TEXT               -- full Discord Message JSON
            )
        ''')

        # Best-effort schema sync for local/dev DBs created before these columns existed.
        msg_cols = {row["name"] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}
        if "delivery_status" not in msg_cols:
            conn.execute("ALTER TABLE messages ADD COLUMN delivery_status TEXT DEFAULT 'pending'")
        if "delivery_error" not in msg_cols:
            conn.execute("ALTER TABLE messages ADD COLUMN delivery_error TEXT")
        conn.execute(
            """
            UPDATE messages
            SET delivery_status = CASE WHEN delivered = 1 THEN 'sent' ELSE 'pending' END
            WHERE delivery_status IS NULL OR trim(delivery_status) = ''
            """
        )

        # ── context_messages ─────────────────────────────────────────────────
        # Many-to-many: any message can belong to any context.
        conn.execute('''
            CREATE TABLE IF NOT EXISTS context_messages (
                context_id  TEXT NOT NULL REFERENCES contexts(id) ON DELETE CASCADE,
                message_id  TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
                added_at    REAL NOT NULL,
                PRIMARY KEY (context_id, message_id)
            )
        ''')

        # ── indices ───────────────────────────────────────────────────────────
        conn.execute('CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_messages_undelivered ON messages(source, delivered) WHERE source = "bot" AND delivered = 0')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_delivery_status ON messages(source, delivery_status) WHERE source = 'bot'")
        conn.execute('CREATE INDEX IF NOT EXISTS idx_contexts_status ON contexts(status)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_contexts_reply_thread ON contexts(reply_thread_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_ctx_msg_context ON context_messages(context_id)')

# Initialize the db on import
init_db()
