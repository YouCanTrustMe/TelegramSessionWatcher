from dotenv import load_dotenv
import os

load_dotenv()

_missing = [k for k in ("API_ID", "API_HASH", "BOT_TOKEN", "OWNER_ID") if not os.getenv(k)]
if _missing:
    raise EnvironmentError(f"Missing required .env variables: {', '.join(_missing)}")

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))

BACKUP_PASSWORD = os.getenv("BACKUP_PASSWORD")
BACKUP_DAY = max(0, min(6, int(os.getenv("BACKUP_DAY", "0"))))
BACKUP_HOUR = max(0, min(23, int(os.getenv("BACKUP_HOUR", "9"))))

def _parse_schedule_hours(raw: str) -> list[int]:
    result = []
    for h in raw.split(","):
        try:
            n = int(h.strip())
            if 0 <= n <= 23:
                result.append(n)
        except ValueError:
            pass
    return result or [7, 10, 13, 16, 20, 23, 1, 3, 5, 6]

SCHEDULE_HOURS = _parse_schedule_hours(os.getenv("SCHEDULE_HOURS", "7,10,13,16,20,23,1,3,5,6"))
STALE_CONVERT_DAYS = int(os.getenv("STALE_CONVERT_DAYS", "60"))
DAILY_KEEP_DAYS = int(os.getenv("DAILY_KEEP_DAYS", "90"))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = "data"
SESSIONS_DIR = os.path.join(DATA_DIR, "sessions")
ARCHIVE_DIR = os.path.join(DATA_DIR, "archive")
INVALID_DIR = os.path.join(DATA_DIR, "invalid")
LOGS_DIR = os.path.join(DATA_DIR, "logs")
TDATA_DIR = os.path.join(DATA_DIR, "tdata")
TEMP_DIR = os.path.join(DATA_DIR, "temp")
DAILY_DIR = os.path.join(DATA_DIR, "daily")

SCHEDULER_STATE_FILE = os.path.join(DATA_DIR, "scheduler_state.txt")
BATCH_STATE_FILE = os.path.join(DATA_DIR, "batch_state.json")
BACKUP_COUNTS_FILE = os.path.join(DATA_DIR, "backup_counts.json")

for _d in (SESSIONS_DIR, ARCHIVE_DIR, INVALID_DIR, LOGS_DIR, TDATA_DIR, TEMP_DIR, DAILY_DIR):
    os.makedirs(_d, exist_ok=True)