import json
import os
import time
import uuid
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import fcntl


BASE_DIR = os.path.dirname(__file__)
DEFAULT_MESSAGES_FILE = os.path.join(BASE_DIR, "messages.json")


class MessageLogError(RuntimeError):
    pass


@dataclass(frozen=True)
class MessageEntry:
    id: str
    author: str
    content: str
    source: str  # "user" | "bot"
    timestamp: float
    channel_id: Optional[int] = None
    thread_id: Optional[int] = None
    delivered: Optional[bool] = None
    delivered_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "id": self.id,
            "author": self.author,
            "content": self.content,
            "source": self.source,
            "timestamp": self.timestamp,
        }
        if self.channel_id is not None:
            d["channel_id"] = self.channel_id
        if self.thread_id is not None:
            d["thread_id"] = self.thread_id
        if self.delivered is not None:
            d["delivered"] = self.delivered
        if self.delivered_at is not None:
            d["delivered_at"] = self.delivered_at
        return d


def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _read_messages_unlocked(f) -> List[Dict[str, Any]]:
    try:
        f.seek(0)
        raw = f.read()
    except Exception as e:
        raise MessageLogError(f"Failed reading messages log: {e}") from e

    if not raw.strip():
        return []

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # If the file is mid-write or corrupted, fail closed with empty list.
        return []

    if not isinstance(data, list):
        return []

    return [m for m in data if isinstance(m, dict)]


def _atomic_write_json(path: str, obj: Any) -> None:
    _ensure_parent_dir(path)
    fd, tmp_path = tempfile.mkstemp(prefix=".messages.", suffix=".tmp", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w") as tmp:
            json.dump(obj, tmp, indent=4)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_path, path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def load_messages(messages_file: str = DEFAULT_MESSAGES_FILE) -> List[Dict[str, Any]]:
    if not os.path.exists(messages_file):
        return []

    with open(messages_file, "r") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            return _read_messages_unlocked(f)
        finally:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass


def append_message(
    *,
    author: str,
    content: str,
    source: str,
    timestamp: Optional[float] = None,
    channel_id: Optional[int] = None,
    thread_id: Optional[int] = None,
    delivered: Optional[bool] = None,
    delivered_at: Optional[float] = None,
    messages_file: str = DEFAULT_MESSAGES_FILE,
) -> Dict[str, Any]:
    if source not in {"user", "bot"}:
        raise ValueError("source must be 'user' or 'bot'")

    entry = MessageEntry(
        id=str(uuid.uuid4()),
        author=str(author),
        content=str(content),
        source=source,
        timestamp=float(timestamp if timestamp is not None else time.time()),
        channel_id=channel_id,
        thread_id=thread_id,
        delivered=delivered,
        delivered_at=delivered_at,
    ).to_dict()

    _ensure_parent_dir(messages_file)
    if not os.path.exists(messages_file):
        _atomic_write_json(messages_file, [])

    with open(messages_file, "r+") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            messages = _read_messages_unlocked(f)
            messages.append(entry)
            _atomic_write_json(messages_file, messages)
        finally:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass

    return entry


def mark_delivered(
    message_id: str,
    *,
    delivered: bool = True,
    delivered_at: Optional[float] = None,
    messages_file: str = DEFAULT_MESSAGES_FILE,
) -> bool:
    if not os.path.exists(messages_file):
        return False

    delivered_at_value = float(delivered_at if delivered_at is not None else time.time())

    with open(messages_file, "r+") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            messages = _read_messages_unlocked(f)
            changed = False
            for msg in messages:
                if msg.get("id") == message_id:
                    msg["delivered"] = delivered
                    msg["delivered_at"] = delivered_at_value
                    changed = True
                    break
            if changed:
                _atomic_write_json(messages_file, messages)
            return changed
        finally:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass


def get_undelivered_bot_messages(messages_file: str = DEFAULT_MESSAGES_FILE) -> List[Dict[str, Any]]:
    messages = load_messages(messages_file)
    out = [
        m
        for m in messages
        if m.get("source") == "bot" and m.get("delivered") is False and (m.get("content") or "").strip()
    ]
    out.sort(key=lambda m: float(m.get("timestamp", 0)))
    return out

