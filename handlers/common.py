import os
import glob
from typing import Optional
import asyncio
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import SESSIONS_DIR, ARCHIVE_DIR

PAGE_SIZE = 10

pending_auth: dict = {}
_backup_task: Optional[asyncio.Task] = None

_cb_map: dict[str, str] = {}
_cb_seq: int = 0


def cb_encode(action: str, name: str) -> str:
    full = f"{action}:{name}"
    if len(full.encode("utf-8")) <= 64:
        return full
    global _cb_seq
    _cb_seq += 1
    key = str(_cb_seq)
    _cb_map[key] = name
    return f"{action}:#{key}"


def cb_decode(raw: str) -> str | None:
    if raw.startswith("#"):
        return _cb_map.get(raw[1:])
    return raw

CANCEL_MARKUP = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="auth:cancel")]])


def get_session_names(include_archived: bool = False) -> list:
    sessions = glob.glob(os.path.join(SESSIONS_DIR, "*.session"))
    names = sorted([os.path.basename(s).replace(".session", "") for s in sessions])
    if include_archived and os.path.isdir(ARCHIVE_DIR):
        archived = glob.glob(os.path.join(ARCHIVE_DIR, "*.session"))
        names += sorted([f"[archived] {os.path.basename(s).replace('.session', '')}" for s in archived])
    return names


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
            [InlineKeyboardButton(n, callback_data=cb_encode(action, n))]
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