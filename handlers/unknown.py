from pyrogram import Client, filters
from pyrogram.types import Message
from bot import bot, owner_filter

KNOWN_COMMANDS = {
    "add", "backup", "exit", "list", "restore", "status",
}


async def _is_unknown_command(_, __, message: Message) -> bool:
    text = message.text or ""
    if not text.startswith("/"):
        return False
    cmd = text.split(maxsplit=1)[0][1:].split("@", 1)[0].lower()
    return bool(cmd) and cmd not in KNOWN_COMMANDS


unknown_command_filter = filters.create(_is_unknown_command)


@bot.on_message(owner_filter & unknown_command_filter)
async def unknown_command(client: Client, message: Message):
    cmds = ", ".join(f"/{c}" for c in sorted(KNOWN_COMMANDS))
    await message.reply(f"❓ Unknown command.\n\nAvailable: {cmds}")
