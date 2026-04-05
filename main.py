import asyncio
from datetime import datetime
from watcher import run_session
from logger import get_logger
from config import SCHEDULE_HOURS

log = get_logger(__name__)

async def scheduler():
    log.info("TelegramSessionWatcher started")

    while True:
        now = datetime.now()

        if now.hour in SCHEDULE_HOURS and now.minute == 0:
            log.info(f"Running session at {now.strftime('%H:%M')}")
            await run_session()
            await asyncio.sleep(60)
        else:
            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(scheduler())