from dotenv import load_dotenv
import os

load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))

BACKUP_PASSWORD = os.getenv("BACKUP_PASSWORD")
BACKUP_DAY = int(os.getenv("BACKUP_DAY", "0"))
BACKUP_HOUR = int(os.getenv("BACKUP_HOUR", "9"))
SCHEDULE_HOURS = [7, 19]

DATA_DIR = "data"
SESSIONS_DIR = os.path.join(DATA_DIR, "sessions")
ARCHIVE_DIR = os.path.join(DATA_DIR, "archive")
LOGS_DIR = os.path.join(DATA_DIR, "logs")
TDATA_DIR = os.path.join(DATA_DIR, "tdata")
TEMP_DIR = os.path.join(DATA_DIR, "temp")

for _d in (SESSIONS_DIR, ARCHIVE_DIR, LOGS_DIR, TDATA_DIR, TEMP_DIR):
    os.makedirs(_d, exist_ok=True)