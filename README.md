# TelegramSessionWatcher

A Telegram bot that monitors multiple user accounts for unread private messages and notifies the owner in real time.

## Features

- Monitors any number of Pyrogram `.session` accounts for unread DMs
- Batched, randomized schedule across the day to mimic natural activity
- Per-account metadata: notes, conversion status, invalid tracking
- Converts sessions to tdata format (for use in Telegram Desktop)
- AES-encrypted backups sent as Telegram documents
- Stale conversion reminders piggybacked on weekly backups
- Inline bot UI — account management entirely via buttons, no extra commands
- Invalid session auto-detection with 2-strike policy and reauth flow

## Requirements

- Python 3.12+
- macOS or Linux
- Telegram API credentials from [my.telegram.org](https://my.telegram.org)
- A bot token from [@BotFather](https://t.me/BotFather)

## Installation

```bash
git clone https://github.com/YouCanTrustMe/TelegramSessionWatcher.git
cd TelegramSessionWatcher

python3.12 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

## Configuration

Create a `.env` file in the project root:

```env
# Required
API_ID=12345678
API_HASH=your_api_hash_here
BOT_TOKEN=123456789:AAF...
OWNER_ID=123456789

# Optional
BACKUP_PASSWORD=yourpassword       # Password for encrypted backups
BACKUP_DAY=6                       # Weekday for weekly backup (0=Mon, 6=Sun)
BACKUP_HOUR=3                      # Hour (UTC) for weekly backup
SCHEDULE_HOURS=7,10,13,16,20,23,1,3,5,6  # Hours to run session checks
STALE_CONVERT_DAYS=60              # Days before flagging unconverted sessions
DAILY_KEEP_DAYS=90                 # Days to retain daily notification logs
```

## Running

```bash
source venv/bin/activate
python main.py
```

Keep it running with `tmux` or `screen`:

```bash
tmux new -s tsw
python main.py
# Ctrl+B, D to detach
```

## Adding your first account

1. Start the bot and open a chat with it
2. Send `/add`
3. Follow the prompts: phone number → confirmation code → 2FA password (if set)

Alternatively, add accounts from the command line (without the bot running):

```bash
python auth.py
```

## Bot commands

| Command | Description |
|---|---|
| `/status` | Overview of all batches with unread counts and last backup time |
| `/list` | Full account manager — browse Active / Archive / Invalid tabs, click any account to manage it |
| `/add` | Add a new monitored account (multi-step phone → code → 2FA) |
| `/backup` | Send an AES-encrypted zip of all sessions, logs, and config |
| `/restore` | Restore from a previously sent backup zip |
| `/exit` | Graceful shutdown |

## Project structure

```
main.py              # Entry point — starts bot, runs scheduler loop
bot.py               # Shared Pyrogram Client instance
watcher.py           # Session checker — connects accounts, reads dialogs
converter.py         # Pyrogram → Telethon → tdata conversion
config.py            # Env loading, directory creation, validation
logger.py            # Daily rotating log files
store.py             # SQLite metadata store (accounts.db)
state.py             # Scheduler state persistence (scheduler_state.txt)
auth.py              # Standalone CLI for adding accounts

handlers/
  auth.py            # /add and /reauth flow
  sessions.py        # /list — tabbed account manager
  backup.py          # /backup and /restore
  misc.py            # Today digest, stale report, log tail, manual run
  common.py          # Shared state and helpers
  unknown.py         # Unknown command handler

data/
  sessions/          # Active .session files
  archive/           # Archived sessions
  invalid/           # Invalid sessions (moved automatically)
  logs/              # Daily rotating logs (YYYY/MM/YYYY-MM-DD.log)
  tdata/             # Converted tdata output
  temp/              # Temporary conversion files
  accounts.db        # Per-account metadata
  scheduler_state.txt
  daily/             # Per-day notification logs (YYYY-MM-DD.jsonl)
```

## How scheduling works

`SCHEDULE_HOURS` defines which hours of the day trigger a session check. Each account is assigned to exactly one hour via a hash of its name (uniform distribution), forming "batches". Within a batch, accounts are checked sequentially with randomized delays (3–8s typical, 15–30s occasionally) to avoid triggering Telegram rate limits.

## Session validity

If a session returns `AuthKeyUnregistered` or `SessionRevoked`, the bot waits 60 seconds and retries once. Only on a confirmed second failure is the session moved to `data/invalid/` and the owner notified. Use the `/list` → Invalid tab → Reauth to re-login without re-adding the account.
