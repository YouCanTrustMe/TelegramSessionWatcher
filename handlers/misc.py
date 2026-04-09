import os
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import Message
from bot import bot, owner_filter
from config import LOGS_DIR


@bot.on_message(filters.command("run") & owner_filter)
async def run_session_cmd(client: Client, message: Message):
    from watcher import run_session
    await message.reply("Starting session manually...")
    await run_session()
    await message.reply("✅ Session completed.")


@bot.on_message(filters.command("log") & owner_filter)
async def log_cmd(client: Client, message: Message):
    args = message.text.split()
    try:
        n = int(args[1]) if len(args) > 1 else 50
    except ValueError:
        n = 50

    now = datetime.now()
    log_path = os.path.join(LOGS_DIR, str(now.year), f"{now.month:02d}", f"{now.strftime('%Y-%m-%d')}.log")

    if not os.path.exists(log_path):
        await message.reply("No log file found for today.")
        return

    with open(log_path, encoding="utf-8") as f:
        lines = f.readlines()

    tail = "".join(lines[-n:]).strip()
    if not tail:
        await message.reply("Log file is empty.")
        return

    header = f"📋 `{now.strftime('%Y-%m-%d')}` — last {min(n, len(lines))} lines:\n\n"
    await message.reply(header + f"```\n{tail}\n```")