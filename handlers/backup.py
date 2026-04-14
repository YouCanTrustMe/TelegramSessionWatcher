import os
import asyncio
import tempfile
import shutil
from datetime import datetime
import pyzipper
from pyrogram import Client, filters
from pyrogram.types import Message
from bot import bot, owner_filter
from config import OWNER_ID, BACKUP_PASSWORD, DATA_DIR, BASE_DIR
from logger import get_logger

log = get_logger(__name__)

GITIGNORE_PATHS = [DATA_DIR, ".env", "bot.session"]


def _collect_stats() -> tuple[list, list, int]:
    folder_stats = []
    file_list = []

    for path in GITIGNORE_PATHS:
        if not os.path.exists(path):
            continue
        if os.path.isfile(path):
            file_list.append(path)
        elif os.path.isdir(path):
            for entry in sorted(os.listdir(path)):
                full = os.path.join(path, entry)
                if os.path.isdir(full):
                    count = sum(len(fs) for _, _, fs in os.walk(full))
                    folder_stats.append((full, count))
                elif os.path.isfile(full):
                    file_list.append(full)

    total_files = sum(c for _, c in folder_stats) + len(file_list)
    return folder_stats, file_list, total_files


def _build_zip_sync(zip_path: str) -> tuple[list, list, int]:
    folder_stats, file_list, total_files = _collect_stats()

    if not BACKUP_PASSWORD:
        raise ValueError("BACKUP_PASSWORD is not set in .env")

    with pyzipper.AESZipFile(zip_path, "w", compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES) as zf:
        zf.setpassword(BACKUP_PASSWORD.encode())
        for path in GITIGNORE_PATHS:
            if not os.path.exists(path):
                continue
            if os.path.isfile(path):
                zf.write(path, path)
            elif os.path.isdir(path):
                for root, _, fs in os.walk(path):
                    for f in fs:
                        fp = os.path.join(root, f)
                        zf.write(fp, fp)

    return folder_stats, file_list, total_files


async def do_backup() -> None:
    date_str = datetime.now().strftime("%Y-%m-%d_%H-%M")
    zip_path = os.path.join(tempfile.gettempdir(), f"tsw_backup_{date_str}.zip")

    folder_stats, file_list, total_files = await asyncio.to_thread(_build_zip_sync, zip_path)

    lines = [f"**📦 `tsw_backup_{date_str}.zip`**"]
    if folder_stats:
        lines.append("\n📁 **Folders:**")
        for path, count in folder_stats:
            lines.append(f"• `{path}/` — `{count}`")
    if file_list:
        lines.append("\n📄 **Files:**")
        for path in file_list:
            lines.append(f"• `{path}`")
    lines.append(f"\n🗂 **Total:** `{total_files}` file(s)")
    caption = "\n".join(lines)

    try:
        await bot.send_document(OWNER_ID, zip_path, caption=caption)
        log.info("Backup created and sent")
        from state import write_backup_state
        write_backup_state(datetime.now().strftime("%Y-%m-%d %H:%M"))
    finally:
        if os.path.exists(zip_path):
            os.remove(zip_path)

    from handlers.misc import build_stale_report
    stale_report = build_stale_report()
    if stale_report:
        await bot.send_message(OWNER_ID, stale_report, disable_notification=True)


async def schedule_backup_after_add() -> None:
    await asyncio.sleep(180)
    log.info("Auto backup triggered after /add")
    try:
        await do_backup()
    except Exception as e:
        log.error(f"Auto backup after /add failed: {e}")
        try:
            await bot.send_message(OWNER_ID, f"❌ Auto backup failed: {e}")
        except Exception:
            pass


@bot.on_message(filters.command("backup") & owner_filter)
async def backup_cmd(client: Client, message: Message):
    await message.reply("Creating backup...")
    try:
        await do_backup()
    except Exception as e:
        await message.reply(f"❌ Backup failed: {e}")


@bot.on_message(filters.command("restore") & owner_filter)
async def restore_cmd(client: Client, message: Message):
    if not message.reply_to_message or not message.reply_to_message.document:
        await message.reply("Reply to a backup zip file with /restore")
        return

    await message.reply("Restoring backup...")

    zip_path = os.path.join(tempfile.gettempdir(), "tsw_restore.zip")
    try:
        await message.reply_to_message.download(zip_path)
    except Exception as e:
        await message.reply(f"❌ Failed to download file: {e}")
        return

    tmp_dir = os.path.join(tempfile.gettempdir(), "tsw_restore_tmp")
    if os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir)
    os.makedirs(tmp_dir)

    if not BACKUP_PASSWORD:
        await message.reply("❌ BACKUP_PASSWORD is not set in .env")
        if os.path.exists(zip_path):
            os.remove(zip_path)
        return

    try:
        with pyzipper.AESZipFile(zip_path, "r") as zf:
            zf.setpassword(BACKUP_PASSWORD.encode())
            for info in zf.infolist():
                if ".." in info.filename or info.filename.startswith("/"):
                    raise ValueError(f"Unsafe path in archive: {info.filename}")
            zf.extractall(tmp_dir)

        rollback = {}
        for item in os.listdir(tmp_dir):
            dst = os.path.join(BASE_DIR, item)
            if os.path.exists(dst):
                backup_copy = f"{dst}_rollback"
                if os.path.isdir(dst):
                    shutil.copytree(dst, backup_copy)
                else:
                    shutil.copy2(dst, backup_copy)
                rollback[dst] = backup_copy

        try:
            for item in os.listdir(tmp_dir):
                src = os.path.join(tmp_dir, item)
                dst = os.path.join(BASE_DIR, item)
                if os.path.isdir(src):
                    if os.path.exists(dst):
                        shutil.rmtree(dst)
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
        except Exception:
            for dst, backup_copy in rollback.items():
                if os.path.isdir(backup_copy):
                    if os.path.exists(dst):
                        shutil.rmtree(dst)
                    shutil.copytree(backup_copy, dst)
                else:
                    shutil.copy2(backup_copy, dst)
            raise

        for backup_copy in rollback.values():
            if os.path.isdir(backup_copy):
                shutil.rmtree(backup_copy)
            elif os.path.exists(backup_copy):
                os.remove(backup_copy)

        await message.reply("✅ Backup restored.")
        log.info("Backup restored")
    except Exception as e:
        await message.reply(f"❌ Restore failed: {e}")
        log.error(f"Restore failed: {e}")
    finally:
        if os.path.exists(zip_path):
            os.remove(zip_path)
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir)