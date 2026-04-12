import asyncio
import hashlib
import json
import os
import shutil
import random
from datetime import datetime
from pyrogram import Client
from pyrogram.errors import AuthKeyUnregistered, UserDeactivated, FloodWait, SessionRevoked
from pyrogram.raw.functions.account import UpdateStatus
from config import API_ID, API_HASH, SESSIONS_DIR, INVALID_DIR, SCHEDULE_HOURS, BATCH_STATE_FILE
from bot import send_notification
from logger import get_logger

log = get_logger(__name__)
_session_lock = asyncio.Lock()

def move_to_invalid(name: str, session_path: str):
    dest = os.path.join(INVALID_DIR, f"{name}_invalid")
    for ext in (".session", ".session-journal"):
        src = f"{session_path}{ext}"
        if os.path.exists(src):
            shutil.move(src, f"{dest}{ext}")
    log.info(f"[{name}] Moved to invalid/")


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
    return [(name, path) for name, path in all_sessions
            if int(hashlib.md5(name.encode()).hexdigest(), 16) % len(SCHEDULE_HOURS) == idx]


def _random_delay() -> float:
    if random.random() < 0.2:
        return random.uniform(15.0, 30.0)
    return random.uniform(3.0, 8.0)


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


def _update_batch_state(hour: int):
    try:
        with open(BATCH_STATE_FILE) as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    state[str(hour)] = datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(BATCH_STATE_FILE, "w") as f:
        json.dump(state, f)

async def check_account(name: str, session_path: str, _retry: bool = True) -> bool:
    client = Client(session_path, api_id=API_ID, api_hash=API_HASH)
    has_unread = False
    disconnected = False

    try:
        await client.connect()
        log.info(f"[{name}] Connected")
    except Exception as e:
        log.error(f"[{name}] Connection error: {e}")
        await send_notification(f"⚠️ [{name}] Connection error: {e}")
        return False

    try:
        me = await client.get_me()
        log.info(f"[{name}] Account alive: {me.first_name}")

        await client.invoke(UpdateStatus(offline=False))

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
                chat_name = dialog.chat.first_name or dialog.chat.title or "Unknown"
                log.info(f"[{name}] Unread from: {chat_name}")
                preview = _format_preview(dialog.top_message)
                extra = dialog.unread_messages_count - 1
                block = f"From: {chat_name}\n{preview}"
                if extra > 0:
                    block += f"\n+ {extra} more unread"
                unread_blocks.append(block)

        if unread_blocks:
            header = f"📩 Account [{name}] — {len(unread_blocks)} chat(s)"
            await send_notification(header + "\n\n" + "\n\n".join(unread_blocks))
            has_unread = True

    except asyncio.TimeoutError:
        log.error(f"[{name}] get_dialogs timed out after 60s")
        await send_notification(f"⚠️ [{name}] Check timed out — Telegram not responding")
    except (AuthKeyUnregistered, SessionRevoked):
        log.error(f"[{name}] Session invalid")
        move_to_invalid(name, session_path)
        await send_notification(f"🚫 [{name}] Session invalid — moved to invalid. Use /reauth to re-login.")
    except UserDeactivated:
        log.error(f"[{name}] Account deactivated")
        move_to_invalid(name, session_path)
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

    return has_unread

async def run_session(hour: int = None):
    if _session_lock.locked():
        log.warning("run_session already in progress, skipping.")
        return

    async with _session_lock:
        sessions = get_batch_for_hour(hour) if hour is not None else get_all_sessions()

        if not sessions:
            log.warning("No sessions found for this batch.")
            return

        label = f"hour {hour}" if hour is not None else "all accounts"
        log.info(f"Starting session — {label}: {len(sessions)} accounts")

        any_unread = False
        checked = []
        for i, (name, path) in enumerate(sessions):
            check_time = datetime.now().strftime("%H:%M")
            has_unread = await check_account(name, path)
            checked.append((name, check_time))
            if has_unread:
                any_unread = True
            if i < len(sessions) - 1:
                delay = _random_delay()
                log.debug(f"Waiting {delay:.1f}s before next account")
                await asyncio.sleep(delay)

        if checked:
            start_time = checked[0][1]
            header = (
                f"✅ {start_time} — {len(checked)} checked, see messages above"
                if any_unread
                else f"✅ {start_time} — {len(checked)} checked, no new messages"
            )
            lines = [f"{header}\n"] + [f"{name} — {t}" for name, t in checked]
            await send_notification("\n".join(lines), silent=True)

        if hour is not None:
            _update_batch_state(hour)

        log.info("Session completed")