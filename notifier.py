import os
import glob
from pyrogram import Client, filters
from pyrogram.types import Message
from config import API_ID, API_HASH, BOT_TOKEN, OWNER_ID, SESSIONS_DIR
from converter import convert_to_tdata
from logger import get_logger

log = get_logger(__name__)

bot = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

owner_filter = filters.user(OWNER_ID)

async def send_notification(text: str):
    await bot.send_message(OWNER_ID, text)

@bot.on_message(filters.command("list") & owner_filter)
async def list_accounts(client: Client, message: Message):
    sessions = glob.glob(os.path.join(SESSIONS_DIR, "*.session"))
    if not sessions:
        await message.reply("No accounts found.")
        return
    names = [os.path.basename(s).replace(".session", "") for s in sessions]
    text = "\n".join(f"• `{n}`" for n in names)
    await message.reply(f"**Accounts ({len(names)}):**\n{text}")

@bot.on_message(filters.command("convert") & owner_filter)
async def convert_account(client: Client, message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("Usage: /convert <session_name>")
        return

    session_name = parts[1].strip()
    await message.reply(f"Converting `{session_name}`...")

    zip_path = await convert_to_tdata(session_name)

    if zip_path is None:
        await message.reply(f"Session `{session_name}` not found.")
        return

    await message.reply_document(zip_path, caption=f"tdata for `{session_name}`")

    os.remove(zip_path)
    log.info(f"tdata sent and removed: {session_name}")