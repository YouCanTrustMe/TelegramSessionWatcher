import json
import os
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from bot import bot, owner_filter
from config import LOGS_DIR, SCHEDULE_HOURS, BATCH_STATE_FILE, SCHEDULER_STATE_FILE


def _load_batch_state() -> dict:
    try:
        with open(BATCH_STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _load_scheduler_state() -> tuple:
    try:
        with open(SCHEDULER_STATE_FILE) as f:
            parts = f.read().strip().split("\n")
            return (
                parts[0] if len(parts) > 0 else "",
                parts[1] if len(parts) > 1 else "",
            )
    except FileNotFoundError:
        return ("", "")


@bot.on_message(filters.command("status") & owner_filter)
async def status_cmd(client: Client, message: Message):
    from watcher import get_batch_for_hour, _session_lock

    batch_state = _load_batch_state()
    scheduler_state = _load_scheduler_state()
    now = datetime.now()
    running = _session_lock.locked()

    lines = [f"**📊 Status** {'⏳ running' if running else ''}\n"]
    for hour in SCHEDULE_HOURS:
        batch = get_batch_for_hour(hour)
        last = batch_state.get(str(hour), "—")
        marker = "▶️" if hour == now.hour else "•"
        lines.append(f"{marker} `{hour:02d}:00` — {len(batch)} acc — {last}")

    sorted_hours = sorted(SCHEDULE_HOURS)
    future = [h for h in sorted_hours if h > now.hour]
    next_hour = future[0] if future else sorted_hours[0]
    lines.append(f"\n**Next:** `{next_hour:02d}:00`")

    last_backup = scheduler_state[1]
    if last_backup:
        lines.append(f"**Last backup:** `{last_backup}`")

    buttons = [
        InlineKeyboardButton(f"👁 {hour:02d}:00", callback_data=f"status_batch:{hour}")
        for hour in SCHEDULE_HOURS
    ]
    rows = [buttons[i:i+5] for i in range(0, len(buttons), 5)]
    markup = InlineKeyboardMarkup(rows)

    await message.reply("\n".join(lines), reply_markup=markup)


@bot.on_callback_query(filters.regex(r'^status_batch:') & owner_filter)
async def status_batch_callback(client: Client, callback: CallbackQuery):
    from watcher import get_batch_for_hour

    hour = int(callback.data.split(":")[1])
    batch = get_batch_for_hour(hour)
    await callback.answer()

    if not batch:
        await callback.message.reply(f"**{hour:02d}:00** — no accounts in this batch.")
        return

    names = "\n".join(f"• `{name}`" for name, _ in batch)
    await callback.message.reply(f"**{hour:02d}:00 — {len(batch)} accounts:**\n{names}")


@bot.on_message(filters.command("run") & owner_filter)
async def run_session_cmd(client: Client, message: Message):
    from watcher import run_session, _session_lock
    from config import SCHEDULE_HOURS

    if _session_lock.locked():
        await message.reply("⏳ Session check already in progress.")
        return

    parts = message.text.split()
    if len(parts) < 2:
        hours_str = ", ".join(str(h) for h in SCHEDULE_HOURS)
        await message.reply(f"Usage: `/run <hour>`\nAvailable hours: {hours_str}")
        return

    try:
        hour = int(parts[1].strip())
    except ValueError:
        await message.reply("❌ Invalid hour. Example: `/run 8`")
        return

    if hour not in SCHEDULE_HOURS:
        await message.reply(f"❌ Hour `{hour}` not in schedule: {SCHEDULE_HOURS}")
        return

    await message.reply(f"Starting session for hour {hour}...")
    await run_session(hour=hour)
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
