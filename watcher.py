import asyncio
import os
import shutil
import random
from datetime import datetime
from pyrogram import Client
from pyrogram.errors import AuthKeyUnregistered, UserDeactivated, FloodWait, SessionRevoked
from pyrogram.raw.functions.account import UpdateStatus
from config import API_ID, API_HASH, SESSIONS_DIR, INVALID_DIR
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

async def check_account(name: str, session_path: str) -> bool:
    client = Client(session_path, api_id=API_ID, api_hash=API_HASH)
    has_unread = False

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

        async for dialog in client.get_dialogs():
            if (
                dialog.unread_messages_count > 0
                and dialog.chat.type.value not in ("channel", "supergroup", "group", "bot")
            ):
                chat_name = dialog.chat.first_name or dialog.chat.title or "Unknown"
                log.info(f"[{name}] Unread from: {chat_name}")
                await send_notification(f"📩 Account [{name}]\nNew message from: {chat_name}")
                has_unread = True

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
    except Exception as e:
        log.error(f"[{name}] Unknown error: {e}")
        await send_notification(f"⚠️ [{name}] Unknown error: {e}")
    finally:
        try:
            await client.invoke(UpdateStatus(offline=True))
        except Exception:
            pass
        await client.disconnect()
        log.info(f"[{name}] Disconnected")

    return has_unread

async def run_session():
    if _session_lock.locked():
        log.warning("run_session already in progress, skipping.")
        return

    async with _session_lock:
        sessions = get_all_sessions()

        if not sessions:
            log.warning("No .session files found in sessions/")
            return

        log.info(f"Starting session — accounts: {len(sessions)}")

        any_unread = False
        for name, path in sessions:
            has_unread = await check_account(name, path)
            if has_unread:
                any_unread = True
            await asyncio.sleep(random.uniform(2.0, 3.5))

        if not any_unread:
            now = datetime.now().strftime("%H:%M")
            await send_notification(f"✅ Session completed at {now} — no new messages", silent=True)

        log.info("Session completed")