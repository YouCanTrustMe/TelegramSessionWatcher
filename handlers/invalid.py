import glob
import os
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery
from bot import bot, owner_filter
from config import API_ID, API_HASH, SESSIONS_DIR, INVALID_DIR, OWNER_ID
from logger import get_logger
from handlers.common import build_pagination, pending_auth, CANCEL_MARKUP

log = get_logger(__name__)


def get_invalid_names(include_done: bool = False) -> list:
    sessions = glob.glob(os.path.join(INVALID_DIR, "*.session"))
    names = []
    for s in sessions:
        name = os.path.basename(s).replace(".session", "")
        if include_done or not name.endswith("_done"):
            names.append(name)
    return sorted(names)


@bot.on_message(filters.command("invalid") & owner_filter)
async def invalid_cmd(client: Client, message: Message):
    names = get_invalid_names(include_done=True)
    if not names:
        await message.reply("No invalid sessions found.")
        return
    text, markup = build_pagination(names, 0, "list")
    await message.reply(text, reply_markup=markup)


@bot.on_message(filters.command("reauth") & owner_filter)
async def reauth_cmd(client: Client, message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) >= 2:
        await start_reauth(message, parts[1].strip())
        return

    names = get_invalid_names()
    if not names:
        await message.reply("No invalid sessions found.")
        return
    text, markup = build_pagination(names, 0, "reauth")
    await message.reply(text, reply_markup=markup)


@bot.on_callback_query(filters.regex(r'^reauth:'))
async def handle_reauth_callback(client: Client, callback: CallbackQuery):
    session_name = callback.data.split(":", 1)[1]
    await callback.answer()
    await start_reauth(callback.message, session_name)


async def start_reauth(message: Message, session_name: str):
    invalid_path = os.path.join(INVALID_DIR, session_name)
    if not os.path.exists(f"{invalid_path}.session"):
        await message.reply(f"Session `{session_name}` not found in invalid.")
        return

    phone_part = session_name.split("_")[0]
    phone = f"+{phone_part}" if not phone_part.startswith("+") else phone_part

    if OWNER_ID in pending_auth:
        from handlers.auth import cleanup_pending
        cleanup_pending(OWNER_ID)

    session_path = os.path.join(SESSIONS_DIR, phone)
    auth_client = Client(session_path, api_id=API_ID, api_hash=API_HASH)

    try:
        await auth_client.connect()
        sent = await auth_client.send_code(phone)
        pending_auth[OWNER_ID] = {
            "step": "code",
            "phone": phone,
            "hash": sent.phone_code_hash,
            "client": auth_client,
            "session_path": session_path,
            "reauth_source": invalid_path,
        }
        await message.reply(
            f"Re-auth for `{session_name}`\nCode sent to `{phone}`. Enter the code:",
            reply_markup=CANCEL_MARKUP
        )
    except Exception as e:
        await auth_client.disconnect()
        await message.reply(f"❌ Error sending code: {e}")
