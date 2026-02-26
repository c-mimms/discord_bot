import json
import time
import uuid
from typing import Any, Dict, List, Optional

from src.db.database import get_db


# ─────────────────────────────────────────────────────────────────────────────
# Messages
# ─────────────────────────────────────────────────────────────────────────────

def insert_message(
    author: str,
    content: str,
    source: str,
    timestamp: Optional[float] = None,
    channel_id: Optional[int] = None,
    thread_id: Optional[int] = None,
    delivered: Optional[bool] = None,
    delivered_at: Optional[float] = None,
    raw_discord_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Insert a raw message into the message log. Returns the stored dict."""
    if source not in {"user", "bot"}:
        raise ValueError("source must be 'user' or 'bot'")

    timestamp_val = float(timestamp if timestamp is not None else time.time())
    msg_id = str(uuid.uuid4())
    delivered_val = 1 if delivered else 0
    payload_json = json.dumps(raw_discord_payload) if raw_discord_payload else None

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO messages
                (id, author, content, source, timestamp,
                 channel_id, thread_id, delivered, delivered_at, raw_discord_payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (msg_id, str(author), str(content), source, timestamp_val,
             channel_id, thread_id, delivered_val, delivered_at, payload_json),
        )

    return {
        "id": msg_id,
        "author": str(author),
        "content": str(content),
        "source": source,
        "timestamp": timestamp_val,
        "channel_id": channel_id,
        "thread_id": thread_id,
        "delivered": bool(delivered_val),
        "delivered_at": delivered_at,
        "raw_discord_payload": raw_discord_payload,
    }


def get_undelivered_bot_messages() -> List[Dict[str, Any]]:
    """Return all undelivered bot messages with their origin channel/thread ids."""
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT *
            FROM messages
            WHERE source = 'bot' AND delivered = 0 AND trim(content) != ''
            ORDER BY timestamp ASC
            """
        )
        return [dict(row) for row in cursor.fetchall()]


def mark_delivered(
    message_id: str,
    delivered: bool = True,
    delivered_at: Optional[float] = None,
) -> bool:
    time_val = float(delivered_at if delivered_at is not None else time.time())
    with get_db() as conn:
        cursor = conn.execute(
            "UPDATE messages SET delivered = ?, delivered_at = ? WHERE id = ?",
            (1 if delivered else 0, time_val, message_id),
        )
        return cursor.rowcount > 0


# ─────────────────────────────────────────────────────────────────────────────
# Contexts
# ─────────────────────────────────────────────────────────────────────────────

def create_context(
    reply_channel_id: Optional[int] = None,
    reply_thread_id: Optional[int] = None,
) -> str:
    """Create a new conversation context, return its UUID id."""
    context_id = str(uuid.uuid4())
    now = time.time()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO contexts (id, reply_channel_id, reply_thread_id, status, created_at, updated_at)
            VALUES (?, ?, ?, 'idle', ?, ?)
            """,
            (context_id, reply_channel_id, reply_thread_id, now, now),
        )
    return context_id


def find_context_by_reply_thread(thread_id: int) -> Optional[str]:
    """Return the context_id that owns this reply thread, or None."""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT id FROM contexts WHERE reply_thread_id = ? ORDER BY updated_at DESC LIMIT 1",
            (thread_id,),
        )
        row = cursor.fetchone()
        return row["id"] if row else None


def set_context_reply_thread(context_id: str, thread_id: int) -> None:
    """Associate a Discord thread with a context (set after thread creation)."""
    with get_db() as conn:
        conn.execute(
            "UPDATE contexts SET reply_thread_id = ?, updated_at = ? WHERE id = ?",
            (thread_id, time.time(), context_id),
        )


def update_context_status(
    context_id: str,
    status: str,
    pid: Optional[int] = None,
) -> None:
    if status not in {"idle", "running"}:
        raise ValueError("status must be 'idle' or 'running'")
    with get_db() as conn:
        conn.execute(
            "UPDATE contexts SET status = ?, current_pid = ?, updated_at = ? WHERE id = ?",
            (status, pid, time.time(), context_id),
        )


def get_idle_contexts_with_pending_user_messages() -> List[str]:
    """
    Return context IDs that are idle but whose last linked message is from 'user'.
    """
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT c.id
            FROM contexts c
            WHERE c.status = 'idle'
              AND (
                  SELECT m.source
                  FROM context_messages cm
                  JOIN messages m ON cm.message_id = m.id
                  WHERE cm.context_id = c.id
                  ORDER BY m.timestamp DESC
                  LIMIT 1
              ) = 'user'
            """
        )
        return [row["id"] for row in cursor.fetchall()]


def get_context(context_id: str) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.execute("SELECT * FROM contexts WHERE id = ?", (context_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


# ─────────────────────────────────────────────────────────────────────────────
# Context ↔ Message linking
# ─────────────────────────────────────────────────────────────────────────────

def add_message_to_context(context_id: str, message_id: str) -> None:
    """Link a message to a context (idempotent)."""
    with get_db() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO context_messages (context_id, message_id, added_at)
            VALUES (?, ?, ?)
            """,
            (context_id, message_id, time.time()),
        )
        conn.execute(
            "UPDATE contexts SET updated_at = ? WHERE id = ?",
            (time.time(), context_id),
        )


def get_messages_for_context(
    context_id: str,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Return all messages linked to this context, ordered by timestamp."""
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT m.*
            FROM messages m
            JOIN context_messages cm ON cm.message_id = m.id
            WHERE cm.context_id = ?
            ORDER BY m.timestamp ASC
            LIMIT ?
            """,
            (context_id, limit),
        )
        return [dict(row) for row in cursor.fetchall()]


def get_latest_user_message_for_context(
    context_id: str,
) -> Optional[Dict[str, Any]]:
    """Return the most recent user message linked to this context."""
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT m.*
            FROM messages m
            JOIN context_messages cm ON cm.message_id = m.id
            WHERE cm.context_id = ? AND m.source = 'user'
            ORDER BY m.timestamp DESC
            LIMIT 1
            """,
            (context_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None
