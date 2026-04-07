import asyncio
import signal
from datetime import datetime
from watcher import run_session
from bot import bot
from logger import get_logger
from config import SCHEDULE_HOURS, BACKUP_DAY, BACKUP_HOUR
import handlers

log = get_logger(__name__)

_shutdown = False


async def scheduler():
    global _shutdown
    last_session_run: str | None = None
    last_backup_run: str | None = None

    while not _shutdown:
        now = datetime.now()

        if now.hour in SCHEDULE_HOURS:
            key = now.strftime("%Y-%m-%d %H")
            if key != last_session_run:
                last_session_run = key
                log.info(f"Running session at {now.strftime('%H:%M')}")
                await run_session()

        if now.weekday() == BACKUP_DAY and now.hour == BACKUP_HOUR:
            key = now.strftime("%Y-%m-%d %H")
            if key != last_backup_run:
                last_backup_run = key
                log.info("Running scheduled backup")
                await handlers.do_backup()

        await asyncio.sleep(30)


async def main():
    log.info("TelegramSessionWatcher started")
    await bot.start()
    log.info(f"Bot started: @{(await bot.get_me()).username}")

    loop = asyncio.get_running_loop()

    def handle_signal():
        global _shutdown
        log.info("Shutdown signal received, stopping...")
        _shutdown = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal)

    await scheduler()

    log.info("Stopping bot...")
    await bot.stop()
    log.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())