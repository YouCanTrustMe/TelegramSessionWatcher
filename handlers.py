import os
import glob
import time
import sqlite3
import asyncio
import pyzipper
import tempfile
import shutil
from datetime import datetime
from typing import Optional
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from bot import bot, owner_filter
from converter import convert_to_tdata
from config import API_ID, API_HASH, SESSIONS_DIR, OWNER_ID, BACKUP_PASSWORD
from logger import get_logger

GITIGNORE_PATHS = ["sessions", "sessions_archive", ".env", "logs", "bot.session"]
ARCHIVE_DIR = "sessions_archive"

log = get_logger(__name__)

pending_auth = {}
PAGE_SIZE = 10
_backup_task: Optional[asyncio.Task] = None

CANCEL_MARKUP = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="auth:cancel")]])


def get_session_names(include_archived: bool = False) -> list:
    sessions = glob.glob(os.path.join(SESSIONS_DIR, "*.session"))
    names = sorted([os.path.basename(s).replace(".session", "") for s in sessions])
    if include_archived and os.path.isdir(ARCHIVE_DIR):
        archived = glob.glob(os.path.join(ARCHIVE_DIR, "*.session"))
        names += sorted([f"[archived] {os.path.basename(s).replace('.session', '')}" for s in archived])
    return names


def cleanup_pending(user_id: int):
    state = pending_auth.pop(user_id, None)
    if not state:
        return
    client = state.get("client")
    if client:
        try:
            asyncio.create_task(client.disconnect())
        except Exception:
            pass
    session_path = state.get("session_path")
    if session_path:
        for ext in ["", ".session", ".session-journal"]:
            path = f"{session_path}{ext}"
            if os.path.exists(path):
                os.remove(path)
                log.info(f"Removed incomplete session file: {path}")


def build_pagination(names: list, page: int, action: str) -> tuple:
    total = len(names)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))

    start = page * PAGE_SIZE
    chunk = names[start:start + PAGE_SIZE]

    if action == "list":
        text = "\n".join(f"• `{n}`" for n in chunk)
        text = f"**Accounts ({total}) — Page {page + 1}/{total_pages}:**\n{text}"
        buttons = []
    else:
        text = f"**Select account ({action}) — Page {page + 1}/{total_pages}:**"
        buttons = [
            [InlineKeyboardButton(n, callback_data=f"{action}:{n}")]
            for n in chunk
        ]

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("« Prev", callback_data=f"page:{action}:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next »", callback_data=f"page:{action}:{page + 1}"))
    if nav:
        buttons.append(nav)

    markup = InlineKeyboardMarkup(buttons) if buttons else None
    return text, markup


def _build_zip_sync(zip_path: str) -> tuple[list, list, int]:
    dir_stats = []
    file_list = []
    total_files = 0

    for path in GITIGNORE_PATHS:
        if not os.path.exists(path):
            continue
        if os.path.isdir(path):
            count = sum(len(fs) for _, _, fs in os.walk(path))
            dir_stats.append((path, count))
            total_files += count
        elif os.path.isfile(path):
            file_list.append(path)
            total_files += 1

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

    return dir_stats, file_list, total_files


async def do_backup() -> None:
    date_str = datetime.now().strftime("%Y-%m-%d_%H-%M")
    zip_path = os.path.join(tempfile.gettempdir(), f"tsw_backup_{date_str}.zip")

    dir_stats, file_list, total_files = await asyncio.to_thread(_build_zip_sync, zip_path)

    lines = [f"**📦 `tsw_backup_{date_str}.zip`**\n"]
    for path, count in dir_stats:
        lines.append(f"📁 __{path}/__ — `{count}` file(s)")
    for path in file_list:
        lines.append(f"📄 `{path}`")
    lines.append(f"\n> 🗂 Total: **{total_files}** file(s)")
    caption = "\n".join(lines)

    await bot.send_document(OWNER_ID, zip_path, caption=caption)
    os.remove(zip_path)
    log.info("Backup created and sent")


async def schedule_backup_after_add() -> None:
    await asyncio.sleep(180)
    log.info("Auto backup triggered after /add")
    await do_backup()


@bot.on_message(filters.command("list") & owner_filter)
async def list_accounts(client: Client, message: Message):
    names = get_session_names()
    if not names:
        await message.reply("No accounts found.")
        return
    text, markup = build_pagination(names, 0, "list")
    await message.reply(text, reply_markup=markup)


@bot.on_message(filters.command("cancel") & owner_filter)
async def cancel_cmd(client: Client, message: Message):
    if OWNER_ID in pending_auth:
        cleanup_pending(OWNER_ID)
        await message.reply("❌ Cancelled. Incomplete session files removed.")
    else:
        await message.reply("Nothing to cancel.")


@bot.on_callback_query(filters.regex(r'^auth:cancel$'))
async def handle_auth_cancel(client: Client, callback: CallbackQuery):
    if OWNER_ID in pending_auth:
        cleanup_pending(OWNER_ID)
        await callback.message.edit_text("❌ Cancelled. Incomplete session files removed.")
    else:
        await callback.message.edit_text("Nothing to cancel.")
    await callback.answer()


@bot.on_message(filters.command("remove") & owner_filter)
async def remove_account(client: Client, message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) >= 2:
        await ask_remove_confirm(message, parts[1].strip())
        return

    names = get_session_names()
    if not names:
        await message.reply("No accounts found.")
        return
    text, markup = build_pagination(names, 0, "remove")
    await message.reply(text, reply_markup=markup)


async def ask_remove_confirm(message: Message, session_name: str):
    session_path = os.path.join(SESSIONS_DIR, f"{session_name}.session")
    if not os.path.exists(session_path):
        await message.reply(f"Session `{session_name}` not found.")
        return
    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes, archive", callback_data=f"confirm_remove:{session_name}"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_remove"),
        ]
    ])
    await message.reply(
        f"⚠️ Archive `{session_name}`?\n_Session will be moved to `{ARCHIVE_DIR}/`, not deleted._",
        reply_markup=markup
    )


@bot.on_callback_query(filters.regex(r'^confirm_remove:'))
async def handle_confirm_remove(client: Client, callback: CallbackQuery):
    session_name = callback.data.split(":", 1)[1]
    session_path = os.path.join(SESSIONS_DIR, f"{session_name}.session")

    if not os.path.exists(session_path):
        await callback.answer("Not found.", show_alert=True)
        return

    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    archive_path = os.path.join(ARCHIVE_DIR, f"{session_name}.session")
    if os.path.exists(archive_path):
        archive_path = os.path.join(ARCHIVE_DIR, f"{session_name}_{int(time.time())}.session")

    os.rename(session_path, archive_path)
    log.info(f"Account archived: {session_name}")
    await callback.message.edit_text(f"📦 Account `{session_name}` moved to archive.")
    await callback.answer()


@bot.on_callback_query(filters.regex(r'^cancel_remove$'))
async def handle_cancel_remove(client: Client, callback: CallbackQuery):
    await callback.message.edit_text("❌ Removal cancelled.")
    await callback.answer()


@bot.on_message(filters.command("convert") & owner_filter)
async def convert_account_cmd(client: Client, message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) >= 2:
        await do_convert(message, parts[1].strip())
        return

    names = get_session_names(include_archived=True)
    if not names:
        await message.reply("No accounts found.")
        return
    text, markup = build_pagination(names, 0, "convert")
    await message.reply(text, reply_markup=markup)


@bot.on_message(filters.command("info") & owner_filter)
async def info_account_cmd(client: Client, message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) >= 2:
        await do_info(message, parts[1].strip())
        return

    names = get_session_names(include_archived=True)
    if not names:
        await message.reply("No accounts found.")
        return
    text, markup = build_pagination(names, 0, "info")
    await message.reply(text, reply_markup=markup)


async def do_info(message: Message, session_name: str):
    clean_name = session_name.removeprefix("[archived] ")
    is_archived = session_name.startswith("[archived] ")
    base_dir = ARCHIVE_DIR if is_archived else SESSIONS_DIR
    session_path = os.path.join(base_dir, f"{clean_name}.session")

    if not os.path.exists(session_path):
        await message.reply(f"Session `{clean_name}` not found.")
        return

    try:
        conn = sqlite3.connect(session_path)
        cursor = conn.cursor()
        cursor.execute("SELECT dc_id, user_id FROM sessions")
        row = cursor.fetchone()
    finally:
        conn.close()

    if not row:
        await message.reply("No data found in session.")
        return

    dc_id, user_id = row
    size = os.path.getsize(session_path)
    modified = datetime.fromtimestamp(os.path.getmtime(session_path)).strftime("%Y-%m-%d %H:%M")
    status = "archived" if is_archived else "active"

    await message.reply(
        f"**Account info:**\n"
        f"Name: `{clean_name}`\n"
        f"Status: `{status}`\n"
        f"User ID: `{user_id}`\n"
        f"DC: `{dc_id}`\n"
        f"Size: `{size} bytes`\n"
        f"Last modified: `{modified}`"
    )


@bot.on_message(filters.command("log") & owner_filter)
async def log_cmd(client: Client, message: Message):
    now = datetime.now()
    log_path = os.path.join("logs", str(now.year), f"{now.month:02d}", f"{now.strftime('%Y-%m-%d')}.log")

    if not os.path.exists(log_path):
        await message.reply("No log file found for today.")
        return

    await message.reply_document(log_path, caption=f"📋 Log for `{now.strftime('%Y-%m-%d')}`")


@bot.on_callback_query(filters.regex(r'^page:'))
async def handle_pagination(client: Client, callback: CallbackQuery):
    _, action, page = callback.data.split(":")
    page = int(page)
    include_archived = action in ("info", "convert")
    names = get_session_names(include_archived=include_archived)
    text, markup = build_pagination(names, page, action)
    await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer()


@bot.on_callback_query(filters.regex(r'^remove:'))
async def handle_remove_callback(client: Client, callback: CallbackQuery):
    session_name = callback.data.split(":", 1)[1]
    await ask_remove_confirm(callback.message, session_name)
    await callback.answer()


@bot.on_callback_query(filters.regex(r'^info:'))
async def handle_info_callback(client: Client, callback: CallbackQuery):
    session_name = callback.data.split(":", 1)[1]
    await callback.answer()
    await do_info(callback.message, session_name)


@bot.on_callback_query(filters.regex(r'^convert:'))
async def handle_convert_callback(client: Client, callback: CallbackQuery):
    session_name = callback.data.split(":", 1)[1]
    await callback.message.edit_text(f"Converting `{session_name}`...")
    await callback.answer()
    await do_convert(callback.message, session_name)


async def do_convert(message: Message, session_name: str):
    clean_name = session_name.removeprefix("[archived] ")
    await message.reply(f"Converting `{clean_name}`...")
    zip_path = await convert_to_tdata(clean_name)
    if zip_path is None:
        await message.reply(f"Session `{clean_name}` not found.")
        return
    await message.reply_document(zip_path, caption=f"tdata for `{clean_name}`")
    os.remove(zip_path)
    log.info(f"tdata sent and removed: {clean_name}")


@bot.on_message(filters.command("run") & owner_filter)
async def run_session_cmd(client: Client, message: Message):
    from watcher import run_session
    await message.reply("Starting session manually...")
    await run_session()
    await message.reply("✅ Session completed.")


@bot.on_message(filters.command("add") & owner_filter)
async def add_account_cmd(client: Client, message: Message):
    if OWNER_ID in pending_auth:
        cleanup_pending(OWNER_ID)
    await message.reply("Send phone number (e.g. +380XXXXXXXXX):", reply_markup=CANCEL_MARKUP)
    pending_auth[OWNER_ID] = {"step": "phone"}


@bot.on_message(owner_filter & filters.text & ~filters.regex(r'^/'))
async def handle_auth_input(client: Client, message: Message):
    if OWNER_ID not in pending_auth:
        return

    state = pending_auth[OWNER_ID]

    if state["step"] == "phone":
        phone = message.text.strip()
        session_path = os.path.join(SESSIONS_DIR, phone)
        auth_client = Client(session_path, api_id=API_ID, api_hash=API_HASH)
        await auth_client.connect()

        try:
            sent = await auth_client.send_code(phone)
            pending_auth[OWNER_ID] = {
                "step": "code",
                "phone": phone,
                "hash": sent.phone_code_hash,
                "client": auth_client,
                "session_path": session_path
            }
            await message.reply("Code sent. Enter the code from Telegram:", reply_markup=CANCEL_MARKUP)
        except Exception as e:
            await auth_client.disconnect()
            del pending_auth[OWNER_ID]
            await message.reply(f"❌ Error sending code: {e}\n\nUse /add to try again.")

    elif state["step"] == "code":
        code = message.text.strip()
        auth_client = state["client"]

        try:
            await auth_client.sign_in(state["phone"], state["hash"], code)
            await finish_auth(message, auth_client, state)
        except Exception as e:
            err = str(e).lower()
            if "session_password_needed" in err or "password" in err or "2fa" in err:
                pending_auth[OWNER_ID]["step"] = "2fa"
                await message.reply("Enter 2FA password:", reply_markup=CANCEL_MARKUP)
            elif "phone_code_invalid" in err or "phone_code_expired" in err:
                await message.reply("❌ Invalid or expired code. Please enter the code again:", reply_markup=CANCEL_MARKUP)
            else:
                cleanup_pending(OWNER_ID)
                await message.reply(f"❌ Error: {e}\n\nUse /add to try again.")

    elif state["step"] == "2fa":
        password = message.text.strip()
        auth_client = state["client"]

        try:
            await auth_client.check_password(password)
            await finish_auth(message, auth_client, state)
        except Exception as e:
            err = str(e).lower()
            if "password_hash_invalid" in err:
                await message.reply("❌ Wrong password. Try again:", reply_markup=CANCEL_MARKUP)
            else:
                cleanup_pending(OWNER_ID)
                await message.reply(f"❌ Error: {e}\n\nUse /add to try again.")


async def finish_auth(message: Message, auth_client: Client, state: dict):
    global _backup_task

    me = await auth_client.get_me()
    first = me.first_name or ""
    last = me.last_name or ""
    full_name = f"{first}{last}".strip()

    await auth_client.disconnect()

    old_path = f"{state['session_path']}.session"
    phone = state["phone"]
    new_name = f"{phone}_{full_name}" if full_name else phone
    new_path = os.path.join(SESSIONS_DIR, f"{new_name}.session")
    os.rename(old_path, new_path)

    del pending_auth[OWNER_ID]
    log.info(f"Account added via bot: {new_name}")
    await message.reply(f"✅ Account added: `{new_name}`\n⏳ Backup in 3 minutes...")

    if _backup_task and not _backup_task.done():
        _backup_task.cancel()
    _backup_task = asyncio.create_task(schedule_backup_after_add())


@bot.on_message(filters.command("backup") & owner_filter)
async def backup_cmd(client: Client, message: Message):
    await message.reply("Creating backup...")
    await do_backup()


@bot.on_message(filters.command("restore") & owner_filter)
async def restore_cmd(client: Client, message: Message):
    if not message.reply_to_message or not message.reply_to_message.document:
        await message.reply("Reply to a backup zip file with /restore")
        return

    await message.reply("Restoring backup...")

    zip_path = os.path.join(tempfile.gettempdir(), "tsw_restore.zip")
    await message.reply_to_message.download(zip_path)

    tmp_dir = os.path.join(tempfile.gettempdir(), "tsw_restore_tmp")
    if os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir)
    os.makedirs(tmp_dir)

    try:
        with pyzipper.AESZipFile(zip_path, "r") as zf:
            zf.setpassword(BACKUP_PASSWORD.encode())
            zf.extractall(tmp_dir)

        for item in os.listdir(tmp_dir):
            src = os.path.join(tmp_dir, item)
            dst = item
            if os.path.isdir(src):
                if os.path.exists(dst):
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)

        await message.reply("✅ Backup restored.")
        log.info("Backup restored")
    except Exception as e:
        await message.reply(f"❌ Restore failed: {e}")
        log.error(f"Restore failed: {e}")
    finally:
        os.remove(zip_path)
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir)