import os
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from bot import bot, owner_filter
from config import LOGS_DIR


@bot.on_message(filters.command("run") & owner_filter)
async def run_session_cmd(client: Client, message: Message):
    from watcher import run_session
    await message.reply("Starting session manually...")
    await run_session()
    await message.reply("✅ Session completed.")


def _get_log_path() -> str:
    now = datetime.now()
    return os.path.join(LOGS_DIR, str(now.year), f"{now.month:02d}", f"{now.strftime('%Y-%m-%d')}.log")


@bot.on_message(filters.command("log") & owner_filter)
async def log_cmd(client: Client, message: Message):
    now = datetime.now()
    log_path = _get_log_path()

    if not os.path.exists(log_path):
        await message.reply("No log file found for today.")
        return

    with open(log_path, encoding="utf-8") as f:
        lines = f.readlines()

    tail = "".join(lines[-15:]).strip()
    if not tail:
        await message.reply("Log file is empty.")
        return

    header = f"📋 `{now.strftime('%Y-%m-%d')}` — last {min(15, len(lines))} lines:\n\n"
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("📎 Send full file", callback_data="log:file")]])
    await message.reply(header + f"```\n{tail}\n```", reply_markup=markup)


@bot.on_callback_query(filters.regex(r'^log:file$') & owner_filter)
async def log_file_callback(client: Client, callback: CallbackQuery):
    log_path = _get_log_path()
    if not os.path.exists(log_path):
        await callback.answer("No log file found for today.", show_alert=True)
        return
    await callback.answer()
    now = datetime.now()
    await callback.message.reply_document(log_path, caption=f"📋 Log for `{now.strftime('%Y-%m-%d')}`")
