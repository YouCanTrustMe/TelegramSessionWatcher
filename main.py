import asyncio
from datetime import datetime
from watcher import run_session
from bot import bot
from logger import get_logger
from config import SCHEDULE_HOURS, BACKUP_DAY, BACKUP_HOUR
import handlers

log = get_logger(__name__)

async def do_backup():
    from handlers import backup_cmd
    import pyzipper
    import tempfile
    import os
    from config import BACKUP_PASSWORD, OWNER_ID
    from handlers import GITIGNORE_PATHS

    date_str = datetime.now().strftime("%Y-%m-%d_%H-%M")
    zip_path = os.path.join(tempfile.gettempdir(), f"tsw_backup_{date_str}.zip")

    with pyzipper.AESZipFile(zip_path, "w", compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES) as zf:
        zf.setpassword(BACKUP_PASSWORD.encode())
        for path in GITIGNORE_PATHS:
            if not os.path.exists(path):
                continue
            if os.path.isfile(path):
                zf.write(path, path)
            elif os.path.isdir(path):
                for root, dirs, files in os.walk(path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        zf.write(file_path, file_path)

    await bot.send_document(OWNER_ID, zip_path, caption=f"🔐 Auto backup {date_str}")
    os.remove(zip_path)
    log.info(f"Auto backup sent: {date_str}")

async def scheduler():
    while True:
        now = datetime.now()

        if now.hour in SCHEDULE_HOURS and now.minute == 0:
            log.info(f"Running session at {now.strftime('%H:%M')}")
            await run_session()
            await asyncio.sleep(60)

        if now.weekday() == BACKUP_DAY and now.hour == BACKUP_HOUR and now.minute == 0:
            log.info("Running auto backup")
            await do_backup()
            await asyncio.sleep(60)

        await asyncio.sleep(30)

async def main():
    log.info("TelegramSessionWatcher started")
    await bot.start()
    log.info(f"Bot started: @{(await bot.get_me()).username}")
    await scheduler()

if __name__ == "__main__":
    bot.run(main())