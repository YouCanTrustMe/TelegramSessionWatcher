"""One-off migration helper.

Puts every session currently in data/sessions/ into a cooldown window so the
watcher skips them for a while — used right after moving the project to a new
server/IP, to let existing accounts "rest" before they connect from the new
location. Accounts added later via /add are NOT affected (they get no record).

Usage:
    python set_cooldown.py            # default 48 hours
    python set_cooldown.py 72         # custom hours
"""
import sys
from datetime import datetime, timedelta

from store import init_db, set_cooldown
from watcher import get_all_sessions


def main():
    hours = float(sys.argv[1]) if len(sys.argv) > 1 else 48.0
    until = datetime.now() + timedelta(hours=hours)

    init_db()
    sessions = get_all_sessions()
    if not sessions:
        print("No sessions in data/sessions/ — nothing to do.")
        return

    for name, _ in sessions:
        set_cooldown(name, until)
        print(f"  {name} -> {until.isoformat(timespec='seconds')}")

    print(f"\nDone: {len(sessions)} account(s) in cooldown until "
          f"{until.isoformat(timespec='seconds')} (~{hours:g}h).")


if __name__ == "__main__":
    main()
