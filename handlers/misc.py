import asyncio
import json
import os
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from bot import bot, owner_filter
from config import LOGS_DIR, SCHEDULE_HOURS, BATCH_STATE_FILE, STALE_CONVERT_DAYS, DAILY_DIR
from state import read_state
from watcher import get_batch_for_hour, run_session, _session_lock
from handlers.invalid import get_invalid_names
import store


def _load_batch_state() -> dict:
    try:
        with open(BATCH_STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _load_scheduler_state() -> tuple:
    s, b = read_state()
    return (s or "", b or "")


@bot.on_message(filters.command("status") & owner_filter)
async def status_cmd(client: Client, message: Message):
    batch_state = _load_batch_state()
    scheduler_state = _load_scheduler_state()
    today = datetime.now().strftime("%Y-%m-%d")
    running = _session_lock.locked()

    lines = [f"**📊 Status** {'⏳ running' if running else ''}\n"]
    for hour in SCHEDULE_HOURS:
        batch = get_batch_for_hour(hour)
        last = batch_state.get(str(hour), "")
        if last.startswith(today):
            marker, suffix = "✅", ""
        elif last:
            try:
                dt = datetime.strptime(last[:10], "%Y-%m-%d")
                suffix = f" · {dt.strftime('%m-%d')}"
            except ValueError:
                suffix = ""
            marker = "•"
        else:
            marker, suffix = "•", " · never"
        lines.append(f"{marker} `{hour:02d}:00` — {len(batch)} acc{suffix}")

    invalid_count = len(get_invalid_names())
    if invalid_count:
        lines.append(f"\n⚠️ Invalid: `{invalid_count}` need reauth")

    last_backup = scheduler_state[1]
    if last_backup:
        lines.append(f"\n**💾 Last backup: {last_backup}**")

    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📬 Today", callback_data="status_today"),
            InlineKeyboardButton("⏰ Stale", callback_data="status_stale"),
            InlineKeyboardButton("▶️ Run", callback_data="status_run"),
        ],
        [InlineKeyboardButton("📋 Batches", callback_data="status_batches")],
    ])

    await message.reply("\n".join(lines), reply_markup=markup)


@bot.on_callback_query(filters.regex(r'^status_batches$') & owner_filter)
async def status_batches_callback(client: Client, callback: CallbackQuery):
    await callback.answer()
    buttons = [
        InlineKeyboardButton(f"{hour:02d}:00", callback_data=f"status_batch:{hour}")
        for hour in SCHEDULE_HOURS
    ]
    rows = [buttons[i:i+5] for i in range(0, len(buttons), 5)]
    rows.append([InlineKeyboardButton("❌ Close", callback_data="close_msg")])
    await callback.message.reply("Which hour to show?", reply_markup=InlineKeyboardMarkup(rows))


@bot.on_callback_query(filters.regex(r'^status_batch:') & owner_filter)
async def status_batch_callback(client: Client, callback: CallbackQuery):
    hour = int(callback.data.split(":")[1])
    batch = get_batch_for_hour(hour)
    await callback.answer()

    if not batch:
        await callback.message.reply(
            f"**{hour:02d}:00** — no accounts in this batch.",
            reply_markup=_CLOSE_MARKUP,
        )
        return

    names = "\n".join(f"• `{name}`" for name, _ in batch)
    await callback.message.reply(
        f"**{hour:02d}:00 — {len(batch)} accounts:**\n{names}",
        reply_markup=_CLOSE_MARKUP,
    )


async def start_run(chat_id: int, hour: int):
    if _session_lock.locked():
        await bot.send_message(chat_id, "⏳ Session check already in progress.")
        return
    if hour not in SCHEDULE_HOURS:
        await bot.send_message(chat_id, f"❌ Hour `{hour}` not in schedule: {SCHEDULE_HOURS}")
        return

    await bot.send_message(chat_id, f"Starting session for hour {hour}...")
    await run_session(hour=hour)
    await bot.send_message(chat_id, "✅ Session completed.")



@bot.on_callback_query(filters.regex(r'^status_run$') & owner_filter)
async def status_run_callback(client: Client, callback: CallbackQuery):
    await callback.answer()
    buttons = [
        InlineKeyboardButton(f"{hour:02d}:00", callback_data=f"status_run_hour:{hour}")
        for hour in SCHEDULE_HOURS
    ]
    rows = [buttons[i:i+5] for i in range(0, len(buttons), 5)]
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data="status_run_cancel")])
    await callback.message.reply("Which hour to run?", reply_markup=InlineKeyboardMarkup(rows))


@bot.on_callback_query(filters.regex(r'^status_run_cancel$') & owner_filter)
async def status_run_cancel_callback(client: Client, callback: CallbackQuery):
    await callback.answer()
    await callback.message.delete()


@bot.on_callback_query(filters.regex(r'^status_run_hour:') & owner_filter)
async def status_run_hour_callback(client: Client, callback: CallbackQuery):
    hour = int(callback.data.split(":")[1])
    await callback.answer()
    batch = get_batch_for_hour(hour)
    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirm", callback_data=f"run_confirm:{hour}"),
        InlineKeyboardButton("❌ Cancel", callback_data="close_msg"),
    ]])
    await callback.message.edit_text(
        f"▶️ Run `{hour:02d}:00`? — {len(batch)} account(s)",
        reply_markup=markup,
    )


@bot.on_callback_query(filters.regex(r'^run_confirm:') & owner_filter)
async def run_confirm_callback(client: Client, callback: CallbackQuery):
    hour = int(callback.data.split(":")[1])
    chat_id = callback.message.chat.id
    await callback.answer()
    await callback.message.delete()
    await start_run(chat_id, hour)


def _get_log_path() -> str:
    now = datetime.now()
    return os.path.join(LOGS_DIR, str(now.year), f"{now.month:02d}", f"{now.strftime('%Y-%m-%d')}.log")


async def send_log_tail(target: Message):
    now = datetime.now()
    log_path = _get_log_path()

    if not os.path.exists(log_path):
        await target.reply("No log file found for today.")
        return

    with open(log_path, encoding="utf-8") as f:
        lines = f.readlines()

    tail = "".join(lines[-15:]).strip()
    if not tail:
        await target.reply("Log file is empty.")
        return

    header = f"📋 `{now.strftime('%Y-%m-%d')}` — last {min(15, len(lines))} lines:\n\n"
    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("📎 Send full file", callback_data="log:file"),
        InlineKeyboardButton("❌ Close", callback_data="close_msg"),
    ]])
    await target.reply(header + f"```\n{tail}\n```", reply_markup=markup)



@bot.on_message(filters.command("log") & owner_filter)
async def log_cmd(client: Client, message: Message):
    await send_log_tail(message)


@bot.on_callback_query(filters.regex(r'^log:file$') & owner_filter)
async def log_file_callback(client: Client, callback: CallbackQuery):
    log_path = _get_log_path()
    if not os.path.exists(log_path):
        await callback.answer("No log file found for today.", show_alert=True)
        return
    await callback.answer()
    now = datetime.now()
    await callback.message.reply_document(log_path, caption=f"📋 Log for `{now.strftime('%Y-%m-%d')}`")


def build_stale_report(days: int = STALE_CONVERT_DAYS) -> str | None:
    stale = store.get_stale_accounts(days)
    if not stale:
        return None

    now = datetime.now()
    lines = [f"**⏰ Stale tdata** (no convert in {days}+ days) — `{len(stale)}`\n"]
    for entry in stale:
        ref = entry["last_converted"] or entry["added_at"]
        label = "converted" if entry["last_converted"] else "added"
        try:
            dt = datetime.fromisoformat(ref)
            age_days = (now - dt).days
            lines.append(f"• `{entry['session_name']}` — {label} {age_days}d ago")
        except (TypeError, ValueError):
            lines.append(f"• `{entry['session_name']}` — never {label}")
    return "\n".join(lines)


_CLOSE_MARKUP = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Close", callback_data="close_msg")]])


async def send_stale_report(target: Message):
    report = build_stale_report()
    if report is None:
        await target.reply(f"✅ No accounts stale beyond {STALE_CONVERT_DAYS} days.", reply_markup=_CLOSE_MARKUP)
        return
    await target.reply(report, reply_markup=_CLOSE_MARKUP)



@bot.on_callback_query(filters.regex(r'^status_stale$') & owner_filter)
async def status_stale_callback(client: Client, callback: CallbackQuery):
    await callback.answer()
    await send_stale_report(callback.message)


async def send_today_digest(target: Message):
    now = datetime.now()
    path = os.path.join(DAILY_DIR, f"{now.strftime('%Y-%m-%d')}.jsonl")
    if not os.path.exists(path):
        await target.reply("📭 No unread messages logged today.")
        return

    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not entries:
        await target.reply("📭 No unread messages logged today.")
        return

    total_chats = sum(e.get("chats", 0) for e in entries)
    header = (
        f"**📬 Today — {now.strftime('%Y-%m-%d')}**\n"
        f"`{len(entries)}` account notification(s), `{total_chats}` chat(s)\n"
    )

    current = header
    for e in entries:
        block = f"\n**{e['time']} — `{e['account']}`**\n{e['body']}\n"
        if len(current) + len(block) > 3800:
            await target.reply(current)
            current = block
        else:
            current += block
    if current.strip():
        await target.reply(current, reply_markup=_CLOSE_MARKUP)



@bot.on_callback_query(filters.regex(r'^status_today$') & owner_filter)
async def status_today_callback(client: Client, callback: CallbackQuery):
    await callback.answer()
    await send_today_digest(callback.message)


@bot.on_callback_query(filters.regex(r'^close_msg$') & owner_filter)
async def close_msg_callback(client: Client, callback: CallbackQuery):
    await callback.answer()
    await callback.message.delete()


@bot.on_message(filters.command("stats") & owner_filter)
async def stats_cmd(client: Client, message: Message):
    try:
        import server_stats
        report = await asyncio.to_thread(server_stats.format_report)
        await message.reply(f"```\n{report}\n```")
    except Exception as e:
        await message.reply(f"❌ {e}")


