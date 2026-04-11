from pyrogram import Client, filters
from config import API_ID, API_HASH, BOT_TOKEN, OWNER_ID

bot = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
owner_filter = filters.user(OWNER_ID)

async def send_notification(text: str, silent: bool = False):
    try:
        await bot.send_message(OWNER_ID, text, disable_notification=silent)
    except Exception as e:
        from logger import get_logger
        get_logger(__name__).error(f"Failed to send notification: {e}")