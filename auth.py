import asyncio
import os
from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded, PhoneCodeInvalid, PhoneCodeExpired
from config import API_ID, API_HASH, SESSIONS_DIR
from logger import get_logger

log = get_logger(__name__)

async def add_account():
    phone = input("Phone number (with country code, e.g. +380XXXXXXXXX): ").strip()

    session_path = os.path.join(SESSIONS_DIR, phone)

    client = Client(session_path, api_id=API_ID, api_hash=API_HASH)

    await client.connect()

    try:
        sent = await client.send_code(phone)
        log.info(f"[{phone}] Code sent")
    except Exception as e:
        log.error(f"[{phone}] Failed to send code: {e}")
        await client.disconnect()
        return

    code = input("Enter the code from Telegram: ").strip()

    try:
        await client.sign_in(phone, sent.phone_code_hash, code)
    except PhoneCodeInvalid:
        log.error("Invalid code")
        await client.disconnect()
        return
    except PhoneCodeExpired:
        log.error("Code expired")
        await client.disconnect()
        return
    except SessionPasswordNeeded:
        password = input("Enter 2FA password: ").strip()
        try:
            await client.check_password(password)
        except Exception as e:
            log.error(f"Invalid 2FA password: {e}")
            await client.disconnect()
            return

    me = await client.get_me()
    first = me.first_name or ""
    last = me.last_name or ""
    full_name = f"{first}{last}".strip()

    await client.disconnect()

    old_path = f"{session_path}.session"
    new_name = f"{phone}_{full_name}" if full_name else phone
    new_path = os.path.join(SESSIONS_DIR, f"{new_name}.session")
    os.rename(old_path, new_path)

    log.info(f"Account saved: {new_name}.session")
    print(f"\n✅ Account added: {new_name}")

if __name__ == "__main__":
    asyncio.run(add_account())