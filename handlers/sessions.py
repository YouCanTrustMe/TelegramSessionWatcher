import os
import glob
import time
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.errors import AuthKeyUnregistered, UserDeactivated
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from bot import bot, owner_filter
from config import API_ID, API_HASH, SESSIONS_DIR, ARCHIVE_DIR
from logger import get_logger
from handlers.common import get_session_names, build_pagination

log = get_logger(__name__)


@bot.on_message(filters.command("list") & owner_filter)
async def list_accounts(client: Client, message: Message):
    names = get_session_names()
    if not names:
        await message.reply("No accounts found.")
        return
    text, markup = build_pagination(names, 0, "list")
    await message.reply(text, reply_markup=markup)


@bot.on_message(filters.command("archive") & owner_filter)
async def archive_account(client: Client, message: Message):
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

    size = os.path.getsize(session_path)
    modified = datetime.fromtimestamp(os.path.getmtime(session_path)).strftime("%Y-%m-%d %H:%M")
    file_status = "archived" if is_archived else "active"

    session_no_ext = os.path.join(base_dir, clean_name)
    client = Client(session_no_ext, api_id=API_ID, api_hash=API_HASH)

    try:
        await client.connect()
        me = await client.get_me()

        first = me.first_name or ""
        last = me.last_name or ""
        full_name = f"{first} {last}".strip() or "—"
        username = f"@{me.username}" if me.username else "—"
        phone = f"+{me.phone_number}" if me.phone_number else "—"
        account_status = "🟢 active"

        await client.disconnect()
    except (AuthKeyUnregistered, UserDeactivated) as e:
        if isinstance(e, AuthKeyUnregistered):
            account_status = "🔴 invalid session"
        else:
            account_status = "🔴 deactivated"
        full_name = username = phone = "—"
    except Exception as e:
        account_status = f"⚠️ error: {e}"
        full_name = username = phone = "—"

    await message.reply(
        f"**Account info:**\n"
        f"Name: `{clean_name}`\n"
        f"Full name: `{full_name}`\n"
        f"Username: `{username}`\n"
        f"Phone: `{phone}`\n"
        f"Account: {account_status}\n"
        f"File status: `{file_status}`\n"
        f"Size: `{size} bytes`\n"
        f"Last modified: `{modified}`"
    )


@bot.on_message(filters.command("unarchive") & owner_filter)
async def unarchive_account_cmd(client: Client, message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) >= 2:
        await do_unarchive(message, parts[1].strip())
        return

    if not os.path.isdir(ARCHIVE_DIR):
        await message.reply("Archive is empty.")
        return

    archived = glob.glob(os.path.join(ARCHIVE_DIR, "*.session"))
    names = sorted([os.path.basename(s).replace(".session", "") for s in archived])
    if not names:
        await message.reply("Archive is empty.")
        return

    text, markup = build_pagination(names, 0, "unarchive")
    await message.reply(text, reply_markup=markup)


@bot.on_callback_query(filters.regex(r'^unarchive:'))
async def handle_unarchive_callback(client: Client, callback: CallbackQuery):
    session_name = callback.data.split(":", 1)[1]
    await callback.answer()
    await do_unarchive(callback.message, session_name)


async def do_unarchive(message: Message, session_name: str):
    archive_path = os.path.join(ARCHIVE_DIR, f"{session_name}.session")

    if not os.path.exists(archive_path):
        await message.reply(f"Session `{session_name}` not found in archive.")
        return

    dest_path = os.path.join(SESSIONS_DIR, f"{session_name}.session")
    if os.path.exists(dest_path):
        dest_path = os.path.join(SESSIONS_DIR, f"{session_name}_{int(time.time())}.session")

    os.makedirs(SESSIONS_DIR, exist_ok=True)
    os.rename(archive_path, dest_path)

    restored_name = os.path.basename(dest_path).replace(".session", "")
    log.info(f"Session unarchived: {restored_name}")
    await message.reply(f"✅ Session `{restored_name}` moved back to active sessions.")


@bot.on_callback_query(filters.regex(r'^page:'))
async def handle_pagination(client: Client, callback: CallbackQuery):
    _, action, page = callback.data.split(":")
    page = int(page)

    if action == "unarchive":
        archived = glob.glob(os.path.join(ARCHIVE_DIR, "*.session")) if os.path.isdir(ARCHIVE_DIR) else []
        names = sorted([os.path.basename(s).replace(".session", "") for s in archived])
    else:
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