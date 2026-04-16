import os
import glob
import time
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.errors import AuthKeyUnregistered, UserDeactivated
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from bot import bot, owner_filter
from config import API_ID, API_HASH, SESSIONS_DIR, ARCHIVE_DIR, OWNER_ID
from logger import get_logger
from handlers.common import (
    get_session_names, build_pagination, cb_encode, cb_decode,
    move_session_files, pending_note, PAGE_SIZE, CANCEL_MARKUP,
)
from handlers.invalid import get_invalid_names
import store

log = get_logger(__name__)


MAX_SEARCH_RESULTS = 50


TAB_ACTIVE = "a"
TAB_ARCHIVE = "z"
TAB_INVALID = "i"
_TAB_LABELS = {TAB_ACTIVE: "Active", TAB_ARCHIVE: "Archive", TAB_INVALID: "Invalid"}
_TAB_ICONS = {TAB_ACTIVE: "🟢", TAB_ARCHIVE: "🗄", TAB_INVALID: "⚠️"}


def _tab_names(tab: str) -> list:
    if tab == TAB_ARCHIVE:
        archived = glob.glob(os.path.join(ARCHIVE_DIR, "*.session")) if os.path.isdir(ARCHIVE_DIR) else []
        return sorted([os.path.basename(s).replace(".session", "") for s in archived])
    if tab == TAB_INVALID:
        return get_invalid_names(include_done=True)
    return get_session_names()


def _tab_counts() -> dict:
    archived = glob.glob(os.path.join(ARCHIVE_DIR, "*.session")) if os.path.isdir(ARCHIVE_DIR) else []
    return {
        TAB_ACTIVE: len(get_session_names()),
        TAB_ARCHIVE: len(archived),
        TAB_INVALID: len(get_invalid_names(include_done=True)),
    }


def _build_list_view(tab: str, page: int):
    names = _tab_names(tab)
    counts = _tab_counts()
    total = len(names)
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    chunk = names[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]

    icon = _TAB_ICONS[tab]
    label = _TAB_LABELS[tab]
    if total == 0:
        text = f"**📒 {icon} {label}** — empty"
    elif tab == TAB_INVALID:
        active_count = sum(1 for n in names if not n.endswith("_done"))
        done_count = total - active_count
        text = f"**📒 {icon} {label}** — `{active_count}` active · `{done_count}` done · page {page + 1}/{pages}"
    else:
        text = f"**📒 {icon} {label}** — `{total}` · page {page + 1}/{pages}"

    rows = [[InlineKeyboardButton(n, callback_data=cb_encode(f"la_{tab}", n))] for n in chunk]

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"lt:{tab}:{page - 1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"lt:{tab}:{page + 1}"))
    if nav:
        rows.append(nav)

    tab_row = []
    for t in (TAB_ACTIVE, TAB_ARCHIVE, TAB_INVALID):
        mark = "• " if t == tab else ""
        tab_row.append(InlineKeyboardButton(
            f"{mark}{_TAB_ICONS[t]} {_TAB_LABELS[t]} ({counts[t]})",
            callback_data=f"lt:{t}:0",
        ))
    rows.append(tab_row)

    return text, InlineKeyboardMarkup(rows)


@bot.on_message(filters.command("list") & owner_filter)
async def list_accounts(client: Client, message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) >= 2:
        await _list_search(message, parts[1].strip())
        return
    text, markup = _build_list_view(TAB_ACTIVE, 0)
    await message.reply(text, reply_markup=markup)


@bot.on_callback_query(filters.regex(r'^lt:') & owner_filter)
async def handle_list_tab(client: Client, callback: CallbackQuery):
    _, tab, page = callback.data.split(":")
    text, markup = _build_list_view(tab, int(page))
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback.message.reply(text, reply_markup=markup)
    await callback.answer()


@bot.on_callback_query(filters.regex(r'^la_') & owner_filter)
async def handle_list_account(client: Client, callback: CallbackQuery):
    prefix, raw = callback.data.split(":", 1)
    tab = prefix[3:]
    name = cb_decode(raw)
    if name is None:
        await callback.answer("⚠️ Outdated button. Use /list again.", show_alert=True)
        return
    await callback.answer()

    buttons = []
    if tab == TAB_ACTIVE:
        buttons.append(InlineKeyboardButton("ℹ️ Info", callback_data=cb_encode(f"info_{tab}", name)))
        buttons.append(InlineKeyboardButton("🗄 Archive", callback_data=cb_encode("remove", name)))
        buttons.append(InlineKeyboardButton("↻ Convert", callback_data=cb_encode("convert", name)))
        buttons.append(InlineKeyboardButton("📝 Note", callback_data=cb_encode(f"list_note_{tab}", name)))
    elif tab == TAB_ARCHIVE:
        arch_name = f"[archived] {name}"
        buttons.append(InlineKeyboardButton("ℹ️ Info", callback_data=cb_encode(f"info_{tab}", arch_name)))
        buttons.append(InlineKeyboardButton("↩️ Unarchive", callback_data=cb_encode("unarchive", name)))
        buttons.append(InlineKeyboardButton("↻ Convert", callback_data=cb_encode("convert", arch_name)))
        buttons.append(InlineKeyboardButton("📝 Note", callback_data=cb_encode(f"list_note_{tab}", name)))
    elif tab == TAB_INVALID:
        base_name = name.removesuffix("_done").removesuffix("_invalid")
        if name.endswith("_invalid_done"):
            buttons.append(InlineKeyboardButton("🗑 Delete", callback_data=cb_encode("invalid_delete", name)))
        else:
            buttons.append(InlineKeyboardButton("🔑 Reauth", callback_data=cb_encode("reauth", name)))
        buttons.append(InlineKeyboardButton("📝 Note", callback_data=cb_encode(f"list_note_{tab}", base_name)))

    rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton("« Back to list", callback_data=f"lt:{tab}:0")])
    try:
        await callback.message.edit_text(
            f"**`{name}`**\nSelect action:",
            reply_markup=InlineKeyboardMarkup(rows),
        )
    except Exception:
        await callback.message.reply(
            f"**`{name}`**\nSelect action:",
            reply_markup=InlineKeyboardMarkup(rows),
        )


@bot.on_callback_query(filters.regex(r'^list_note_[azi]:') & owner_filter)
async def handle_list_note(client: Client, callback: CallbackQuery):
    prefix, raw = callback.data.split(":", 1)
    tab = prefix.split("_")[-1]
    name = cb_decode(raw)
    if name is None:
        await callback.answer("⚠️ Outdated button. Use /list again.", show_alert=True)
        return
    await callback.answer()
    pending_note[OWNER_ID] = {
        "session": name,
        "tab": tab,
        "msg_id": callback.message.id,
        "chat_id": callback.message.chat.id,
    }
    await callback.message.edit_text(
        f"📝 Enter note for `{name}`:\n_(empty message clears the note)_",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Cancel", callback_data=f"lt:{tab}:0"),
        ]]),
    )


@bot.on_message(owner_filter & filters.text & ~filters.regex(r'^/'))
async def handle_note_input(client: Client, message: Message):
    if OWNER_ID not in pending_note:
        return
    state = pending_note.pop(OWNER_ID)
    name = state["session"]
    tab = state.get("tab", TAB_ACTIVE)
    msg_id = state.get("msg_id")
    chat_id = state.get("chat_id")
    if store.get_account(name) is None:
        await message.reply(f"Account `{name}` not found in metadata store.")
        return
    text = message.text.strip()
    store.set_note(name, text)
    label = "saved" if text else "cleared"
    back_markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("« Back to list", callback_data=f"lt:{tab}:0"),
    ]])
    if msg_id and chat_id:
        try:
            await client.edit_message_text(chat_id, msg_id, f"✅ Note for `{name}` {label}.", reply_markup=back_markup)
            return
        except Exception:
            pass
    await message.reply(f"📝 Note for `{name}` {label}.")


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



async def do_info(session_name: str) -> str:
    clean_name = session_name.removeprefix("[archived] ")
    is_archived = session_name.startswith("[archived] ")
    base_dir = ARCHIVE_DIR if is_archived else SESSIONS_DIR
    session_path = os.path.join(base_dir, f"{clean_name}.session")

    if not os.path.exists(session_path):
        return f"Session `{clean_name}` not found."

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

    meta = store.get_account(clean_name)
    meta_block = ""
    if meta:
        meta_lines = []
        if meta["added_at"]:
            meta_lines.append(f"Added: `{meta['added_at']}`")
        if meta["invalid_count"]:
            reason_str = f" ({meta['invalid_reason']})" if meta.get("invalid_reason") else ""
            meta_lines.append(f"Invalid count: `{meta['invalid_count']}`{reason_str}")
        if meta["last_reauth"]:
            meta_lines.append(f"Last reauth: `{meta['last_reauth']}`")
        if meta["last_unread"]:
            meta_lines.append(f"Last unread: `{meta['last_unread']}`")
        if meta["notes"]:
            meta_lines.append(f"Notes: {meta['notes']}")
        if meta_lines:
            meta_block = "\n" + "\n".join(meta_lines)

    return (
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


@bot.on_callback_query(filters.regex(r'^info_[azi]:') & owner_filter)
async def handle_info_callback(client: Client, callback: CallbackQuery):
    prefix, raw = callback.data.split(":", 1)
    tab = prefix[5:]
    session_name = cb_decode(raw)
    if session_name is None:
        await callback.answer("⚠️ Outdated button. Use /list again.", show_alert=True)
        return
    await callback.answer()
    text = await do_info(session_name)
    display_name = session_name.removeprefix("[archived] ")
    back_data = cb_encode(f"la_{tab}", display_name)
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data=back_data)]])
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except Exception:
        await callback.message.reply(text, reply_markup=markup)