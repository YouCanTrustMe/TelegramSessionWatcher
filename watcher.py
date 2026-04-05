import asyncio
import os
import random
from pyrogram import Client
from pyrogram.errors import AuthKeyUnregistered, UserDeactivated, FloodWait
from config import API_ID, API_HASH, SESSIONS_DIR
from notifier import send_notification
from logger import get_logger

log = get_logger(__name__)

def get_all_sessions() -> list[str]:
    sessions = []
    for f in os.listdir(SESSIONS_DIR):
        if f.endswith(".session"):
            name = f.replace(".session", "")
            path = os.path.join(SESSIONS_DIR, name)
            sessions.append((name, path))
    return sessions

async def check_account(name: str, session_path: str):
    client = Client(session_path, api_id=API_ID, api_hash=API_HASH)

    try:
        await client.connect()
        log.info(f"[{name}] Connected")
    except Exception as e:
        log.error(f"[{name}] Connection error: {e}")
        await send_notification(f"⚠️ [{name}] Connection error: {e}")
        return

    try:
        me = await client.get_me()
        log.info(f"[{name}] Account alive: {me.first_name}")

        async for dialog in client.get_dialogs():
            if (
                dialog.unread_messages_count > 0
                and dialog.chat.type.value not in ("channel", "supergroup", "group", "bot")
            ):
                chat_name = dialog.chat.first_name or dialog.chat.title or "Unknown"
                log.info(f"[{name}] Unread from: {chat_name}")
                await send_notification(f"📩 Account [{name}]\nNew message from: {chat_name}")

    except AuthKeyUnregistered:
        log.error(f"[{name}] Session invalid")
        await send_notification(f"🚫 [{name}] Session invalid — re-authorization required")
    except UserDeactivated:
        log.error(f"[{name}] Account deactivated")
        await send_notification(f"❌ [{name}] Account deactivated by Telegram")
    except FloodWait as e:
        log.warning(f"[{name}] FloodWait: waiting {e.value}s")
        await asyncio.sleep(e.value)
    except Exception as e:
        log.error(f"[{name}] Unknown error: {e}")
        await send_notification(f"⚠️ [{name}] Unknown error: {e}")
    finally:
        await client.disconnect()
        log.info(f"[{name}] Disconnected")

async def run_session():
    sessions = get_all_sessions()

    if not sessions:
        log.warning("No .session files found in sessions/")
        return

    log.info(f"Starting session — accounts: {len(sessions)}")

    for name, path in sessions:
        await check_account(name, path)
        await asyncio.sleep(random.uniform(2.0, 3.5))

    log.info("Session completed")