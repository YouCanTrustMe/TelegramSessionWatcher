import os
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery
from bot import bot, owner_filter
from converter import convert_to_tdata
from config import SESSIONS_DIR, ARCHIVE_DIR
from logger import get_logger
from handlers.common import get_session_names, build_pagination

log = get_logger(__name__)


@bot.on_message(filters.command("convert") & owner_filter)
async def convert_account_cmd(client: Client, message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) >= 2:
        await do_convert(message, parts[1].strip())
        return

    names = get_session_names(include_archived=True)
    if not names:
        await message.reply("No accounts found.")
        return
    text, markup = build_pagination(names, 0, "convert")
    await message.reply(text, reply_markup=markup)


@bot.on_callback_query(filters.regex(r'^convert:'))
async def handle_convert_callback(client: Client, callback: CallbackQuery):
    session_name = callback.data.split(":", 1)[1]
    await callback.message.edit_text(f"Converting `{session_name}`...")
    await callback.answer()
    await do_convert(callback.message, session_name, notify=False)


async def do_convert(message: Message, session_name: str, notify: bool = True):
    clean_name = session_name.removeprefix("[archived] ")
    is_archived = session_name.startswith("[archived] ")
    source_dir = ARCHIVE_DIR if is_archived else SESSIONS_DIR

    if notify:
        await message.reply(f"Converting `{clean_name}`...")

    try:
        zip_path = await convert_to_tdata(clean_name, source_dir=source_dir)
    except Exception as e:
        log.error(f"Conversion failed for {clean_name}: {e}")
        await message.reply(f"❌ Failed to convert `{clean_name}`: {e}")
        return

    if zip_path is None:
        await message.reply(f"Session `{clean_name}` not found.")
        return
    await message.reply_document(zip_path, caption=f"tdata for `{clean_name}`")
    os.remove(zip_path)
    log.info(f"tdata sent and removed: {clean_name}")