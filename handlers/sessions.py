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
from handlers.common import get_session_names, build_pagination, cb_encode, cb_decode, move_session_files

log = get_logger(__name__)


MAX_SEARCH_RESULTS = 50


@bot.on_message(filters.command("list") & owner_filter)
async def list_accounts(client: Client, message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) >= 2:
        await _list_search(message, parts[1].strip())
        return

    names = get_session_names()
    if not names:
        await message.reply("No accounts found.")
        return
    text, markup = build_pagination(names, 0, "list")
    await message.reply(text, reply_markup=markup)


async def _list_search(message: Message, query: str):
    q = query.lower()
    active = get_session_names()
    archived = get_session_names(include_archived=True)[len(active):]

    hits = [(n, False) for n in active if q in n.lower()]
    hits += [(n.removeprefix("[archived] "), True) for n in archived if q in n.lower()]

    if not hits:
        await message.reply(f"No accounts matching `{query}`.")
        return

    shown = hits[:MAX_SEARCH_RESULTS]
    lines = [f"**🔎 Matches for** `{query}` — `{len(hits)}`\n"]
    for name, is_arch in shown:
        suffix = " _[archived]_" if is_arch else ""
        lines.append(f"• `{name}`{suffix}")
    if len(hits) > MAX_SEARCH_RESULTS:
        lines.append(f"\n_…and {len(hits) - MAX_SEARCH_RESULTS} more. Refine the query._")
    await message.reply("\n".join(lines))


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
            InlineKeyboardButton("✅ Yes, archive", callback_data=cb_encode("confirm_remove", session_name)),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_remove"),
        ]
    ])
    await message.reply(
        f"⚠️ Archive `{session_name}`?\n_Session will be moved to `{ARCHIVE_DIR}/`, not deleted._",
        reply_markup=markup
    )


@bot.on_callback_query(filters.regex(r'^confirm_remove:'))
async def handle_confirm_remove(client: Client, callback: CallbackQuery):
    session_name = cb_decode(callback.data.split(":", 1)[1])
    if session_name is None:
        await callback.answer("⚠️ Outdated button. Use /archive again.", show_alert=True)
        return
    session_path = os.path.join(SESSIONS_DIR, f"{session_name}.session")

    if not os.path.exists(session_path):
        await callback.answer("Not found.", show_alert=True)
        return

    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    dst_name = session_name
    if os.path.exists(os.path.join(ARCHIVE_DIR, f"{dst_name}.session")):
        dst_name = f"{session_name}_{int(time.time())}"

    move_session_files(
        os.path.join(SESSIONS_DIR, session_name),
        os.path.join(ARCHIVE_DIR, dst_name),
    )
    log.info(f"Account archived: {dst_name}")
    await callback.message.edit_text(f"📦 Account `{dst_name}` moved to archive.")
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

    full_name = username = phone = "—"
    account_status = "⚠️ unknown"

    try:
        await client.connect()
        me = await client.get_me()
        first = me.first_name or ""
        last = me.last_name or ""
        full_name = f"{first} {last}".strip() or "—"
        username = f"@{me.username}" if me.username else "—"
        phone = f"+{me.phone_number}" if me.phone_number else "—"
        account_status = "🟢 active"
    except (AuthKeyUnregistered, UserDeactivated) as e:
        account_status = "🔴 invalid session" if isinstance(e, AuthKeyUnregistered) else "🔴 deactivated"
    except Exception as e:
        account_status = f"⚠️ error: {e}"
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

    import store
    meta = store.get_account(clean_name)
    meta_block = ""
    if meta:
        meta_lines = []
        if meta["added_at"]:
            meta_lines.append(f"Added: `{meta['added_at']}`")
        if meta["invalid_count"]:
            meta_lines.append(f"Invalid count: `{meta['invalid_count']}`")
        if meta["last_reauth"]:
            meta_lines.append(f"Last reauth: `{meta['last_reauth']}`")
        if meta["last_unread"]:
            meta_lines.append(f"Last unread: `{meta['last_unread']}`")
        if meta["notes"]:
            meta_lines.append(f"Notes: {meta['notes']}")
        if meta_lines:
            meta_block = "\n" + "\n".join(meta_lines)

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
        f"{meta_block}"
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
    session_name = cb_decode(callback.data.split(":", 1)[1])
    if session_name is None:
        await callback.answer("⚠️ Outdated button. Use /unarchive again.", show_alert=True)
        return
    await callback.answer()
    await do_unarchive(callback.message, session_name)


async def do_unarchive(message: Message, session_name: str):
    if not os.path.exists(os.path.join(ARCHIVE_DIR, f"{session_name}.session")):
        await message.reply(f"Session `{session_name}` not found in archive.")
        return

    restored_name = session_name
    if os.path.exists(os.path.join(SESSIONS_DIR, f"{restored_name}.session")):
        restored_name = f"{session_name}_{int(time.time())}"

    os.makedirs(SESSIONS_DIR, exist_ok=True)
    move_session_files(
        os.path.join(ARCHIVE_DIR, session_name),
        os.path.join(SESSIONS_DIR, restored_name),
    )
    log.info(f"Session unarchived: {restored_name}")
    await message.reply(f"✅ Session `{restored_name}` moved back to active sessions.")


@bot.on_callback_query(filters.regex(r'^page:'))
async def handle_pagination(client: Client, callback: CallbackQuery):
    _, action, page = callback.data.split(":")
    page = int(page)

    if action == "unarchive":
        archived = glob.glob(os.path.join(ARCHIVE_DIR, "*.session")) if os.path.isdir(ARCHIVE_DIR) else []
        names = sorted([os.path.basename(s).replace(".session", "") for s in archived])
    elif action == "reauth":
        from handlers.invalid import get_invalid_names
        names = get_invalid_names()
    elif action == "invalid":
        from handlers.invalid import get_invalid_names
        names = get_invalid_names(include_done=True)
    else:
        include_archived = action in ("info", "convert")
        names = get_session_names(include_archived=include_archived)

    text, markup = build_pagination(names, page, action)
    await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer()


@bot.on_callback_query(filters.regex(r'^remove:'))
async def handle_remove_callback(client: Client, callback: CallbackQuery):
    session_name = cb_decode(callback.data.split(":", 1)[1])
    if session_name is None:
        await callback.answer("⚠️ Outdated button. Use /archive again.", show_alert=True)
        return
    await ask_remove_confirm(callback.message, session_name)
    await callback.answer()


@bot.on_callback_query(filters.regex(r'^info:'))
async def handle_info_callback(client: Client, callback: CallbackQuery):
    session_name = cb_decode(callback.data.split(":", 1)[1])
    if session_name is None:
        await callback.answer("⚠️ Outdated button. Use /info again.", show_alert=True)
        return
    await callback.answer()
    await do_info(callback.message, session_name)