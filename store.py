import os
import sqlite3
from datetime import datetime
from typing import Optional
from config import DATA_DIR, SESSIONS_DIR, ARCHIVE_DIR

DB_PATH = os.path.join(DATA_DIR, "accounts.db")


def _conn():
    return sqlite3.connect(DB_PATH)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def init_db():
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                session_name  TEXT PRIMARY KEY,
                added_at      TEXT,
                notes         TEXT DEFAULT '',
                invalid_count INTEGER DEFAULT 0,
                last_reauth   TEXT,
                last_unread   TEXT
            )
        """)
        existing = {row[0] for row in conn.execute("SELECT session_name FROM accounts")}

    for base in (SESSIONS_DIR, ARCHIVE_DIR):
        if not os.path.isdir(base):
            continue
        for f in os.listdir(base):
            if not f.endswith(".session"):
                continue
            name = f[:-len(".session")]
            if name in existing:
                continue
            mtime = datetime.fromtimestamp(
                os.path.getmtime(os.path.join(base, f))
            ).isoformat(timespec="seconds")
            with _conn() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO accounts (session_name, added_at) VALUES (?, ?)",
                    (name, mtime),
                )


def add_account(name: str):
    with _conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO accounts (session_name, added_at) VALUES (?, ?)",
            (name, _now()),
        )


def get_account(name: str) -> Optional[dict]:
    with _conn() as conn:
        row = conn.execute(
            """SELECT session_name, added_at, notes, invalid_count, last_reauth, last_unread
               FROM accounts WHERE session_name = ?""",
            (name,),
        ).fetchone()
    if not row:
        return None
    return {
        "session_name": row[0],
        "added_at": row[1],
        "notes": row[2] or "",
        "invalid_count": row[3] or 0,
        "last_reauth": row[4],
        "last_unread": row[5],
    }


def set_note(name: str, text: str):
    with _conn() as conn:
        conn.execute(
            "UPDATE accounts SET notes = ? WHERE session_name = ?",
            (text, name),
        )


def bump_invalid(name: str):
    with _conn() as conn:
        conn.execute(
            "UPDATE accounts SET invalid_count = invalid_count + 1 WHERE session_name = ?",
            (name,),
        )


def mark_reauth(name: str):
    add_account(name)
    with _conn() as conn:
        conn.execute(
            "UPDATE accounts SET last_reauth = ? WHERE session_name = ?",
            (_now(), name),
        )


def mark_unread(name: str):
    with _conn() as conn:
        conn.execute(
            "UPDATE accounts SET last_unread = ? WHERE session_name = ?",
            (_now(), name),
        )
