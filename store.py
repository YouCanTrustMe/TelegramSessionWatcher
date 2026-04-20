import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional
from config import DATA_DIR, SESSIONS_DIR, ARCHIVE_DIR

DB_PATH = os.path.join(DATA_DIR, "accounts.db")


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def init_db():
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                session_name   TEXT PRIMARY KEY,
                added_at       TEXT,
                notes          TEXT DEFAULT '',
                invalid_count  INTEGER DEFAULT 0,
                last_reauth    TEXT,
                last_unread    TEXT,
                last_converted TEXT
            )
        """)
        for col in ("last_converted TEXT", "invalid_reason TEXT"):
            try:
                conn.execute(f"ALTER TABLE accounts ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass
        existing = {row[0] for row in conn.execute("SELECT session_name FROM accounts")}

    new_rows = []
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
            new_rows.append((name, mtime))

    if new_rows:
        with _conn() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO accounts (session_name, added_at) VALUES (?, ?)",
                new_rows,
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
            """SELECT session_name, added_at, notes, invalid_count, last_reauth, last_unread, last_converted, invalid_reason
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
        "last_converted": row[6],
        "invalid_reason": row[7],
    }


def set_note(name: str, text: str):
    with _conn() as conn:
        conn.execute(
            "UPDATE accounts SET notes = ? WHERE session_name = ?",
            (text, name),
        )


def bump_invalid(name: str, reason: str = ""):
    with _conn() as conn:
        conn.execute(
            "UPDATE accounts SET invalid_count = invalid_count + 1, invalid_reason = ? WHERE session_name = ?",
            (reason, name),
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


def mark_converted(name: str):
    with _conn() as conn:
        conn.execute(
            "UPDATE accounts SET last_converted = ? WHERE session_name = ?",
            (_now(), name),
        )


def clear_converted(name: str):
    with _conn() as conn:
        conn.execute(
            "UPDATE accounts SET last_converted = NULL WHERE session_name = ?",
            (name,),
        )


def get_stale_accounts(days: int) -> list[dict]:
    cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    with _conn() as conn:
        rows = conn.execute(
            """SELECT session_name, added_at, last_converted
               FROM accounts
               WHERE last_converted IS NULL OR last_converted < ?
               ORDER BY COALESCE(last_converted, added_at) ASC""",
            (cutoff,),
        ).fetchall()
    return [
        {"session_name": r[0], "added_at": r[1], "last_converted": r[2]}
        for r in rows
    ]
