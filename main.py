import asyncio
from datetime import datetime
from typing import Optional
from watcher import run_session
from bot import bot
from logger import get_logger
from config import SCHEDULE_HOURS, BACKUP_DAY, BACKUP_HOUR
import handlers

log = get_logger(__name__)


async def scheduler():
    last_session_run: Optional[str] = None
    last_backup_run: Optional[str] = None

    while True:
        now = datetime.now()

        if now.hour in SCHEDULE_HOURS:
            key = now.strftime("%Y-%m-%d %H")
            if key != last_session_run:
                last_session_run = key
                log.info(f"Running session at {now.strftime('%H:%M')}")
                try:
                    await run_session()
                except Exception as e:
                    log.error(f"run_session failed: {e}")

        if now.weekday() == BACKUP_DAY and now.hour == BACKUP_HOUR:
            key = now.strftime("%Y-%m-%d %H")
            if key != last_backup_run:
                last_backup_run = key
                log.info("Running scheduled backup")
                try:
                    await handlers.do_backup()
                except Exception as e:
                    log.error(f"do_backup failed: {e}")

        await asyncio.sleep(30)


async def main():
    log.info("TelegramSessionWatcher started")
    await bot.start()
    me = await bot.get_me()
    log.info(f"Bot started: @{me.username}")
    try:
        await scheduler()
    finally:
        await bot.stop()


if __name__ == "__main__":
    bot.run(main())