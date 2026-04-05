from pyrogram import Client
from config import BOT_TOKEN, OWNER_ID

async def send_notification(text: str):
    async with Client("bot", bot_token=BOT_TOKEN) as b:
        await b.send_message(OWNER_ID, text)