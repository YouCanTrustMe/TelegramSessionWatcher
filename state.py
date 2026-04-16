import os
from typing import Optional
from config import SCHEDULER_STATE_FILE


def read_state() -> tuple[Optional[str], Optional[str]]:
    try:
        with open(SCHEDULER_STATE_FILE) as f:
            parts = f.read().strip().split("\n")
            return (
                parts[0] if len(parts) > 0 else None,
                parts[1] if len(parts) > 1 else None,
            )
    except FileNotFoundError:
        return None, None


def write_state(session_key: Optional[str], backup_key: Optional[str]):
    tmp = SCHEDULER_STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        f.write(f"{session_key or ''}\n{backup_key or ''}")
    os.replace(tmp, SCHEDULER_STATE_FILE)


def write_backup_state(backup_key: str):
    session_key, _ = read_state()
    write_state(session_key, backup_key)
