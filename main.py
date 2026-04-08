import asyncio
import signal
from datetime import datetime
from typing import Optional
from pyrogram import filters
from pyrogram.types import Message
from watcher import run_session
from bot import bot, owner_filter
from logger import get_logger
from config import SCHEDULE_HOURS, BACKUP_DAY, BACKUP_HOUR
import handlers

log = get_logger(__name__)

_shutdown = False


def _request_shutdown(sig_num, _frame=None):
    global _shutdown
    if not _shutdown:
        try:
            name = signal.Signals(sig_num).name
        except Exception:
            name = str(sig_num)
        log.info(f"Received {name}, shutting down gracefully...")
        _shutdown = True


signal.signal(signal.SIGINT, _request_shutdown)
signal.signal(signal.SIGTERM, _request_shutdown)


@bot.on_message(filters.command("exit") & owner_filter)
async def exit_cmd(client, message: Message):
    global _shutdown
    await message.reply("🛑 Shutting down...")
    log.info("Shutdown requested via /exit")
    _shutdown = True


async def scheduler():
    last_session_run: Optional[str] = None
    last_backup_run: Optional[str] = None

    while not _shutdown:
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

        for _ in range(30):
            if _shutdown:
                break
            await asyncio.sleep(1)


async def main():
    log.info("TelegramSessionWatcher started")
    await bot.start()
    me = await bot.get_me()
    log.info(f"Bot started: @{me.username}")
    try:
        await scheduler()
    finally:
        log.info("Stopping bot...")
        try:
            await bot.stop()
        except Exception as e:
            log.error(f"Error stopping bot: {e}")
        log.info("Shutdown complete")


if __name__ == "__main__":
    try:
        bot.run(main())
    except KeyboardInterrupt:
        pass