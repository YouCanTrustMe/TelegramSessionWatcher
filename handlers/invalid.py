import glob
import os
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from bot import bot, owner_filter
from config import INVALID_DIR, OWNER_ID
from handlers.common import build_pagination, pending_auth, cb_decode, move_session_files


def get_invalid_names(include_done: bool = False) -> list:
    sessions = glob.glob(os.path.join(INVALID_DIR, "*.session"))
    names = []
    for s in sessions:
        name = os.path.basename(s).replace(".session", "")
        if include_done or not name.endswith("_done"):
            names.append(name)
    return sorted(names)



@bot.on_callback_query(filters.regex(r'^invalid_delete:') & owner_filter)
async def handle_invalid_delete_callback(client: Client, callback: CallbackQuery):
    name = cb_decode(callback.data.split(":", 1)[1])
    if name is None:
        await callback.answer("⚠️ Outdated button. Use /list again.", show_alert=True)
        return
    await callback.answer()
    for ext in (".session", ".session-journal"):
        path = os.path.join(INVALID_DIR, f"{name}{ext}")
        if os.path.exists(path):
            os.remove(path)
    await callback.message.edit_text(f"🗑 `{name}` deleted.")


@bot.on_callback_query(filters.regex(r'^reauth:'))
async def handle_reauth_callback(client: Client, callback: CallbackQuery):
    session_name = cb_decode(callback.data.split(":", 1)[1])
    if session_name is None:
        await callback.answer("⚠️ Outdated button. Use /reauth again.", show_alert=True)
        return
    await callback.answer()
    await start_reauth(callback.message, session_name)


async def start_reauth(message: Message, session_name: str):
    from handlers.auth import cleanup_pending, start_code_request

    invalid_path = os.path.join(INVALID_DIR, session_name)
    if not os.path.exists(f"{invalid_path}.session"):
        await message.reply(f"Session `{session_name}` not found in invalid.")
        return

    phone_part = session_name.split("_")[0]
    phone = f"+{phone_part}" if not phone_part.startswith("+") else phone_part

    if OWNER_ID in pending_auth:
        await cleanup_pending(OWNER_ID)

    await start_code_request(
        message,
        phone,
        success_text=f"Re-auth for `{session_name}`\nCode sent to `{phone}`. Enter the code:",
        extra_state={"reauth_source": invalid_path},
    )
