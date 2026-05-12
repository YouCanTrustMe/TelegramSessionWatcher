import os
import asyncio
import requests
from pyrogram import Client, filters
from config import API_ID, API_HASH, BOT_TOKEN, OWNER_ID, PIN_MSG_FILE

bot = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
owner_filter = filters.user(OWNER_ID)

async def send_notification(text: str, silent: bool = False):
    try:
        await bot.send_message(OWNER_ID, text, disable_notification=silent)
    except Exception as e:
        from logger import get_logger
        get_logger(__name__).error(f"Failed to send notification: {e}")


async def update_status_pin(text: str):
    from logger import get_logger
    log = get_logger(__name__)

    base = f"https://api.telegram.org/bot{BOT_TOKEN}"

    if os.path.exists(PIN_MSG_FILE):
        try:
            with open(PIN_MSG_FILE) as f:
                old_id = int(f.read().strip())
            resp = await asyncio.to_thread(
                lambda: requests.post(f"{base}/editMessageText",
                                      json={"chat_id": OWNER_ID, "message_id": old_id,
                                            "text": text, "parse_mode": "HTML"})
            )
            if resp.json().get("ok"):
                return
        except Exception:
            pass

    try:
        resp = await asyncio.to_thread(
            lambda: requests.post(f"{base}/sendMessage",
                                  json={"chat_id": OWNER_ID, "text": text,
                                        "parse_mode": "HTML", "disable_notification": True})
        )
        msg_id = resp.json()["result"]["message_id"]
        await asyncio.to_thread(
            lambda: requests.post(f"{base}/pinChatMessage",
                                  json={"chat_id": OWNER_ID, "message_id": msg_id,
                                        "disable_notification": True})
        )
        with open(PIN_MSG_FILE, "w") as f:
            f.write(str(msg_id))
    except Exception as e:
        log.error(f"Failed to update status pin: {e}")
