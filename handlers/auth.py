import os
import glob
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery
from pyrogram.errors import SessionPasswordNeeded, PhoneCodeInvalid, PhoneCodeExpired, PasswordHashInvalid
from bot import bot, owner_filter
from config import API_ID, API_HASH, SESSIONS_DIR, OWNER_ID
from logger import get_logger
from handlers.common import pending_auth, pending_note, CANCEL_MARKUP, set_backup_task
import store

log = get_logger(__name__)


async def cleanup_pending(user_id: int):
    state = pending_auth.pop(user_id, None)
    if not state:
        return
    client = state.get("client")
    if client:
        try:
            await client.disconnect()
        except Exception:
            pass
    session_path = state.get("session_path")
    if session_path:
        for ext in [".session", ".session-journal"]:
            path = f"{session_path}{ext}"
            if os.path.exists(path):
                os.remove(path)
                log.info(f"Removed incomplete session file: {path}")


async def start_code_request(
    message: Message,
    phone: str,
    success_text: str,
    error_suffix: str = "",
    extra_state: dict | None = None,
) -> bool:
    session_path = os.path.join(SESSIONS_DIR, phone)
    auth_client = Client(session_path, api_id=API_ID, api_hash=API_HASH)
    state = {"step": "phone", "client": auth_client, "session_path": session_path}
    if extra_state:
        state.update(extra_state)
    pending_auth[OWNER_ID] = state

    try:
        await auth_client.connect()
        sent = await auth_client.send_code(phone)
        pending_auth[OWNER_ID].update({
            "step": "code",
            "phone": phone,
            "hash": sent.phone_code_hash,
        })
        await message.reply(success_text, reply_markup=CANCEL_MARKUP)
        return True
    except Exception as e:
        await cleanup_pending(OWNER_ID)
        await message.reply(f"❌ Error sending code: {e}{error_suffix}")
        return False


@bot.on_message(filters.command("add") & owner_filter)
async def add_account_cmd(client: Client, message: Message):
    if OWNER_ID in pending_auth:
        await cleanup_pending(OWNER_ID)
    pending_note.pop(OWNER_ID, None)
    await message.reply("Send phone number (e.g. +380XXXXXXXXX):", reply_markup=CANCEL_MARKUP)
    pending_auth[OWNER_ID] = {"step": "phone"}


@bot.on_callback_query(filters.regex(r'^auth:cancel$'))
async def handle_auth_cancel(client: Client, callback: CallbackQuery):
    if OWNER_ID in pending_auth:
        await cleanup_pending(OWNER_ID)
        await callback.message.edit_text("❌ Cancelled. Incomplete session files removed.")
    elif OWNER_ID in pending_note:
        pending_note.pop(OWNER_ID, None)
        await callback.message.edit_text("❌ Note cancelled.")
    else:
        await callback.message.edit_text("Nothing to cancel.")
    await callback.answer()


@bot.on_message(owner_filter & filters.text & ~filters.regex(r'^/'))
async def handle_auth_input(client: Client, message: Message):
    if OWNER_ID not in pending_auth:
        from pyrogram import ContinuePropagation
        raise ContinuePropagation

    state = pending_auth[OWNER_ID]

    if state["step"] == "phone":
        phone = message.text.strip()
        phone_clean = phone.lstrip("+")
        existing = glob.glob(os.path.join(SESSIONS_DIR, f"{phone_clean}*.session"))
        if existing:
            name = os.path.basename(existing[0]).replace(".session", "")
            await message.reply(
                f"⚠️ Account with this number already exists: `{name}`\n\nArchive or delete it first.",
                reply_markup=CANCEL_MARKUP,
            )
            return
        await start_code_request(
            message,
            phone,
            success_text="Code sent. Enter the code from Telegram:",
            error_suffix="\n\nUse /add to try again.",
        )

    elif state["step"] == "code":
        code = message.text.strip()
        auth_client = state["client"]

        try:
            await auth_client.sign_in(state["phone"], state["hash"], code)
            await finish_auth(message, auth_client, state)
        except SessionPasswordNeeded:
            pending_auth[OWNER_ID]["step"] = "2fa"
            await message.reply("Enter 2FA password:", reply_markup=CANCEL_MARKUP)
        except (PhoneCodeInvalid, PhoneCodeExpired):
            await message.reply("❌ Invalid or expired code. Please enter the code again:", reply_markup=CANCEL_MARKUP)
        except Exception as e:
            await cleanup_pending(OWNER_ID)
            await message.reply(f"❌ Error: {e}\n\nUse /add to try again.")

    elif state["step"] == "2fa":
        password = message.text.strip()
        auth_client = state["client"]

        try:
            await auth_client.check_password(password)
            await finish_auth(message, auth_client, state)
        except PasswordHashInvalid:
            await message.reply("❌ Wrong password. Try again:", reply_markup=CANCEL_MARKUP)
        except Exception as e:
            await cleanup_pending(OWNER_ID)
            await message.reply(f"❌ Error: {e}\n\nUse /add to try again.")


async def finish_auth(message: Message, auth_client: Client, state: dict):
    from handlers.backup import schedule_backup_after_add
    me = await auth_client.get_me()
    first = me.first_name or ""
    last = me.last_name or ""
    full_name = f"{first}{last}".strip()

    await auth_client.disconnect()

    old_path = f"{state['session_path']}.session"
    phone = state["phone"]
    phone_clean = phone.lstrip("+")
    new_name = f"{phone_clean}_{full_name}" if full_name else phone_clean
    new_path = os.path.join(SESSIONS_DIR, f"{new_name}.session")
    os.rename(old_path, new_path)

    reauth_source = state.get("reauth_source")
    if reauth_source:
        for ext in (".session", ".session-journal"):
            src = f"{reauth_source}{ext}"
            if os.path.exists(src):
                os.rename(src, f"{reauth_source}_done{ext}")
        log.info(f"Reauth complete, marked as done: {reauth_source}")
        store.mark_reauth(new_name)
    else:
        store.add_account(new_name)

    del pending_auth[OWNER_ID]
    log.info(f"Account added via bot: {new_name}")
    await message.reply(f"✅ Account added: `{new_name}`\n⏳ Backup in 3 minutes...")

    set_backup_task(asyncio.create_task(schedule_backup_after_add()))