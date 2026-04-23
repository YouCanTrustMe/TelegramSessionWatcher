import os
from pyrogram.types import Message
from converter import convert_to_tdata
from config import SESSIONS_DIR, ARCHIVE_DIR
from logger import get_logger
import store

log = get_logger(__name__)




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
    store.mark_converted(clean_name)
    log.info(f"tdata sent and removed: {clean_name}")