import asyncio
import os
import signal
from datetime import datetime, timedelta
from pyrogram import filters
from pyrogram.types import Message
from watcher import run_session
from bot import bot, owner_filter
from logger import get_logger
from config import SCHEDULE_HOURS, BACKUP_DAY, BACKUP_HOUR, DAILY_DIR, DAILY_KEEP_DAYS
from state import read_state, write_state
from store import init_db
import handlers
from handlers.backup import do_backup

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
    last_session_run, last_backup_run = read_state()

    while not _shutdown:
        now = datetime.now()

        if now.hour in SCHEDULE_HOURS:
            key = now.strftime("%Y-%m-%d %H:%M")
            if key[:13] != (last_session_run or "")[:13]:
                log.info(f"Running session at {now.strftime('%H:%M')}")
                try:
                    await run_session(hour=now.hour)
                except Exception as e:
                    log.error(f"run_session failed: {e}")
                last_session_run = key
                write_state(last_session_run, last_backup_run)

        if now.weekday() == BACKUP_DAY and now.hour == BACKUP_HOUR:
            key = now.strftime("%Y-%m-%d %H:%M")
            if key[:13] != (last_backup_run or "")[:13]:
                log.info("Running scheduled backup")
                try:
                    await do_backup()
                except Exception as e:
                    log.error(f"do_backup failed: {e}")
                last_backup_run = key
                write_state(last_session_run, last_backup_run)

        for _ in range(30):
            if _shutdown:
                break
            await asyncio.sleep(1)


def _cleanup_daily_logs():
    cutoff = datetime.now() - timedelta(days=DAILY_KEEP_DAYS)
    removed = 0
    for fname in os.listdir(DAILY_DIR):
        if not fname.endswith(".jsonl"):
            continue
        try:
            dt = datetime.strptime(fname[:10], "%Y-%m-%d")
        except ValueError:
            continue
        if dt < cutoff:
            os.remove(os.path.join(DAILY_DIR, fname))
            removed += 1
    if removed:
        log.info(f"Removed {removed} old daily log(s) (>{DAILY_KEEP_DAYS} days)")


async def main():
    log.info("TelegramSessionWatcher started")
    init_db()
    _cleanup_daily_logs()
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