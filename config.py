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
SESSIONS_DIR = "sessions"
LOGS_DIR = "logs"