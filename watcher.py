import asyncio
import html
import json
import os
import shutil
import random
from datetime import datetime
from pyrogram import Client
from pyrogram.errors import AuthKeyUnregistered, UserDeactivated, FloodWait, SessionRevoked
from pyrogram.raw.functions.account import UpdateStatus
from pyrogram.raw.functions.updates import GetState
from pyrogram.raw.functions.contacts import GetStatuses, GetContacts
from pyrogram.raw.functions.messages import GetPinnedDialogs
from config import API_ID, API_HASH, SESSIONS_DIR, INVALID_DIR, SCHEDULE_HOURS, BATCH_STATE_FILE, DAILY_DIR
from bot import send_notification, send_html_notification, update_status_pin
from logger import get_logger
import store

log = get_logger(__name__)
_session_lock = asyncio.Lock()

def move_to_invalid(name: str, session_path: str, reason: str = ""):
    dest = os.path.join(INVALID_DIR, f"{name}_invalid")
    for ext in (".session", ".session-journal"):
        src = f"{session_path}{ext}"
        if os.path.exists(src):
            shutil.move(src, f"{dest}{ext}")
    store.bump_invalid(name, reason=reason)
    log.info(f"[{name}] Moved to invalid/ reason={reason!r}")


def get_all_sessions() -> list:
    sessions = []
    for f in os.listdir(SESSIONS_DIR):
        if f.endswith(".session"):
            name = f.replace(".session", "")
            path = os.path.join(SESSIONS_DIR, name)
            sessions.append((name, path))
    return sessions


def get_batch_for_hour(hour: int) -> list:
    all_sessions = get_all_sessions()
    if hour not in SCHEDULE_HOURS or not SCHEDULE_HOURS:
        return all_sessions
    idx = SCHEDULE_HOURS.index(hour)
    n = len(SCHEDULE_HOURS)
    day_offset = datetime.now().timetuple().tm_yday
    sorted_sessions = sorted(all_sessions, key=lambda x: x[0])
    return [s for i, s in enumerate(sorted_sessions) if (i + day_offset) % n == idx]


def _next_schedule_hour(current_hour: int) -> str:
    future = [h for h in SCHEDULE_HOURS if h > current_hour]
    nxt = min(future) if future else min(SCHEDULE_HOURS)
    return f"{nxt:02d}:00"


def _random_delay() -> float:
    if random.random() < 0.2:
        return random.uniform(15.0, 30.0)
    return random.uniform(3.0, 8.0)


def _format_account_header(name: str) -> str:
    if "_" in name:
        phone, display = name.split("_", 1)
        return f"📩 {html.escape(display)} (+{phone})"
    return f"📩 +{name}"


def _format_preview(msg) -> str:
    if msg is None:
        return "[no preview]"
    if msg.text:
        return msg.text if len(msg.text) <= 200 else msg.text[:200] + "..."
    if msg.caption:
        cap = msg.caption if len(msg.caption) <= 200 else msg.caption[:200] + "..."
        return f"[media] {cap}"
    if msg.photo:
        return "[photo]"
    if msg.voice:
        return "[voice]"
    if msg.video_note:
        return "[video note]"
    if msg.video:
        return "[video]"
    if msg.animation:
        return "[gif]"
    if msg.sticker:
        return f"[sticker {msg.sticker.emoji or ''}]".strip()
    if msg.audio:
        return "[audio]"
    if msg.document:
        return "[file]"
    if msg.location:
        return "[location]"
    if msg.contact:
        return "[contact]"
    return "[message]"


def _append_daily_entry(name: str, blocks: list[str]):
    now = datetime.now()
    path = os.path.join(DAILY_DIR, f"{now.strftime('%Y-%m-%d')}.jsonl")
    entry = {
        "time": now.strftime("%H:%M"),
        "account": name,
        "chats": len(blocks),
        "blocks": blocks,
        "body": "\n\n".join(blocks),
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _update_batch_state(hour: int):
    try:
        with open(BATCH_STATE_FILE) as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    state[str(hour)] = datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(BATCH_STATE_FILE, "w") as f:
        json.dump(state, f)

async def check_account(name: str, session_path: str, _retry: bool = True) -> list[str]:
    client = Client(session_path, api_id=API_ID, api_hash=API_HASH)
    unread_blocks: list[str] = []
    disconnected = False

    try:
        await client.connect()
        log.info(f"[{name}] Connected")
    except Exception as e:
        log.error(f"[{name}] Connection error: {e}")
        await send_notification(f"⚠️ [{name}] Connection error: {e}")
        return []

    try:
        try:
            await client.invoke(UpdateStatus(offline=False))
            await asyncio.sleep(5)
            await client.invoke(GetState())
            await client.invoke(GetStatuses())
            await client.invoke(GetContacts(hash=0))
            await client.invoke(GetPinnedDialogs(folder_id=0))
        except Exception:
            pass

        me = await client.get_me()
        log.info(f"[{name}] Account alive: {me.first_name}")

        async def _collect_dialogs():
            result = []
            async for dialog in client.get_dialogs():
                result.append(dialog)
            return result

        dialogs = await asyncio.wait_for(_collect_dialogs(), timeout=60)
        unread_blocks = []
        for dialog in dialogs:
            if (
                dialog.unread_messages_count > 0
                and dialog.chat.type.value not in ("channel", "supergroup", "group", "bot")
            ):
                first = dialog.chat.first_name or ""
                last = dialog.chat.last_name or ""
                chat_name = f"{first} {last}".strip() or dialog.chat.title or "Unknown"
                log.info(f"[{name}] Unread from: {chat_name}")
                preview = _format_preview(dialog.top_message)
                extra = dialog.unread_messages_count - 1
                ts = dialog.top_message.date.strftime("%d.%m %H:%M") if dialog.top_message and dialog.top_message.date else ""
                line1 = f"{chat_name}, {ts}" if ts else chat_name
                block = f"{line1}\n\"{preview}\""
                if extra > 0:
                    block += f"  · +{extra} more"
                unread_blocks.append(block)

        if unread_blocks:
            _append_daily_entry(name, unread_blocks)
            store.mark_unread(name)

    except asyncio.TimeoutError:
        log.error(f"[{name}] get_dialogs timed out after 60s")
        await send_notification(f"⚠️ [{name}] Check timed out — Telegram not responding")
    except (AuthKeyUnregistered, SessionRevoked) as e:
        if _retry:
            log.warning(f"[{name}] Session appears invalid, retrying in 60s")
            await client.disconnect()
            disconnected = True
            await asyncio.sleep(60)
            return await check_account(name, session_path, _retry=False)
        reason = type(e).__name__
        log.error(f"[{name}] Session invalid ({reason}), confirmed on retry")
        move_to_invalid(name, session_path, reason=reason)
        await send_notification(f"🚫 [{name}] Session invalid — moved to invalid. Use /reauth to re-login.")
    except UserDeactivated:
        log.error(f"[{name}] Account deactivated")
        move_to_invalid(name, session_path, reason="UserDeactivated")
        await send_notification(f"❌ [{name}] Account deactivated by Telegram — moved to invalid.")
    except FloodWait as e:
        log.warning(f"[{name}] FloodWait: waiting {e.value}s")
        await asyncio.sleep(e.value)
        await client.disconnect()
        disconnected = True
        if _retry:
            log.info(f"[{name}] Retrying after FloodWait")
            return await check_account(name, session_path, _retry=False)
    except Exception as e:
        log.error(f"[{name}] Unknown error: {e}")
        await send_notification(f"⚠️ [{name}] Unknown error: {e}")
    finally:
        if not disconnected:
            try:
                await client.invoke(UpdateStatus(offline=True))
            except Exception:
                pass
            await client.disconnect()
        log.info(f"[{name}] Disconnected")

    return unread_blocks

async def run_session(hour: int = None):
    if _session_lock.locked():
        log.warning("run_session already in progress, skipping.")
        return

    async with _session_lock:
        sessions = get_batch_for_hour(hour) if hour is not None else get_all_sessions()

        active = [(n, p) for n, p in sessions if not store.is_in_cooldown(n)]
        skipped = len(sessions) - len(active)
        if skipped:
            log.info(f"Skipping {skipped} account(s) in cooldown")
        sessions = active

        if not sessions:
            log.warning("No sessions found for this batch.")
            return

        label = f"hour {hour}" if hour is not None else "all accounts"
        log.info(f"Starting session — {label}: {len(sessions)} accounts")

        start_time = datetime.now().strftime("%d.%m %H:%M")
        all_unread: list[tuple[str, list[str]]] = []
        checked = []
        for i, (name, path) in enumerate(sessions):
            check_time = datetime.now().strftime("%H:%M")
            unread_blocks = await check_account(name, path)
            checked.append((name, check_time))
            if unread_blocks:
                all_unread.append((name, unread_blocks))
            if i < len(sessions) - 1:
                delay = _random_delay()
                log.debug(f"Waiting {delay:.1f}s before next account")
                await asyncio.sleep(delay)

        if all_unread:
            parts = []
            for acc_name, blocks in all_unread:
                quoted = "\n".join(
                    f"<blockquote>{html.escape(b)}</blockquote>" for b in blocks
                )
                parts.append(_format_account_header(acc_name) + "\n\n" + quoted)
            combined = "\n\n\n".join(parts)
            chunk_limit = 4000
            if len(combined) <= chunk_limit:
                await send_html_notification(combined)
            else:
                chunk, silent = "", False
                for part in parts:
                    if chunk and len(chunk) + len(part) + 3 > chunk_limit:
                        await send_html_notification(chunk, silent=silent)
                        chunk, silent = "", True
                    chunk = (chunk + "\n\n\n" + part).lstrip()
                if chunk:
                    await send_html_notification(chunk, silent=silent)

        if checked:
            status = "📩 new messages" if all_unread else "✅ no new messages"
            header = f"📊 {start_time} · {len(checked)} checked · {status}"
            next_hour = _next_schedule_hour(hour if hour is not None else datetime.now().hour)
            accounts_block = "\n".join(f"{name} — {t}" for name, t in checked)
            pin_text = f"{header}\nNext: {next_hour}\n\n<blockquote expandable>{accounts_block}</blockquote>"
            await update_status_pin(pin_text)

        if hour is not None:
            _update_batch_state(hour)

        log.info("Session completed")