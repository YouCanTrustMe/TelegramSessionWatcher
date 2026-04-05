import asyncio
from datetime import datetime
from watcher import run_session
from bot import bot
import handlers
from logger import get_logger
from config import SCHEDULE_HOURS

log = get_logger(__name__)

async def scheduler():
    while True:
        now = datetime.now()
        if now.hour in SCHEDULE_HOURS and now.minute == 0:
            log.info(f"Running session at {now.strftime('%H:%M')}")
            await run_session()
            await asyncio.sleep(60)
        else:
            await asyncio.sleep(30)

async def main():
    log.info("TelegramSessionWatcher started")
    await bot.start()
    log.info(f"Bot started: @{(await bot.get_me()).username}")
    await scheduler()

if __name__ == "__main__":
    bot.run(main())