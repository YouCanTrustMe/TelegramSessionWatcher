import os
import zipfile
import shutil
import sqlite3
from typing import Optional
from telethon import TelegramClient
from opentele.td import TDesktop
from opentele.api import UseCurrentSession
from config import SESSIONS_DIR, API_ID, API_HASH, TDATA_DIR, TEMP_DIR

def pyrogram_to_telethon(pyrogram_path: str, telethon_path: str):
    conn = sqlite3.connect(f"{pyrogram_path}.session")
    cursor = conn.cursor()

    cursor.execute("SELECT dc_id, auth_key FROM sessions")
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise ValueError("No session data found")

    dc_id, auth_key = row

    telethon_conn = sqlite3.connect(f"{telethon_path}.session")
    telethon_cursor = telethon_conn.cursor()

    telethon_cursor.executescript("""
        CREATE TABLE IF NOT EXISTS version (version integer primary key);
        CREATE TABLE IF NOT EXISTS sessions (
            dc_id integer primary key,
            server_address text,
            port integer,
            auth_key blob,
            takeout_id integer
        );
        CREATE TABLE IF NOT EXISTS entities (
            id integer primary key,
            hash integer not null,
            username text,
            phone integer,
            name text,
            date integer
        );
        CREATE TABLE IF NOT EXISTS sent_files (
            md5_digest blob,
            file_size integer,
            type integer,
            id integer,
            hash integer,
            primary key(md5_digest, file_size, type)
        );
        CREATE TABLE IF NOT EXISTS update_state (
            id integer primary key,
            pts integer,
            qts integer,
            date integer,
            seq integer
        );
    """)

    dc_servers = {
        1: ("149.154.175.53", 443),
        2: ("149.154.167.51", 443),
        3: ("149.154.175.100", 443),
        4: ("149.154.167.91", 443),
        5: ("91.108.56.130", 443),
    }

    server, port = dc_servers.get(dc_id, ("149.154.167.51", 443))

    telethon_cursor.execute("INSERT OR REPLACE INTO version VALUES (7)")
    telethon_cursor.execute(
        "INSERT OR REPLACE INTO sessions VALUES (?, ?, ?, ?, ?)",
        (dc_id, server, port, auth_key, None)
    )

    telethon_conn.commit()
    telethon_conn.close()

async def convert_to_tdata(session_name: str, source_dir: str = None) -> Optional[str]:
    base_dir = source_dir if source_dir else SESSIONS_DIR
    session_path = os.path.join(base_dir, session_name)

    if not os.path.exists(f"{session_path}.session"):
        return None

    os.makedirs(TEMP_DIR, exist_ok=True)
    telethon_path = os.path.join(TEMP_DIR, session_name)

    if os.path.exists(f"{telethon_path}.session"):
        os.remove(f"{telethon_path}.session")

    pyrogram_to_telethon(session_path, telethon_path)

    output_path = os.path.join(TDATA_DIR, session_name)
    os.makedirs(output_path, exist_ok=True)

    client = TelegramClient(telethon_path, API_ID, API_HASH)
    await client.connect()

    try:
        tdesk = await TDesktop.FromTelethon(client, flag=UseCurrentSession)
        tdesk.SaveTData(output_path)
    finally:
        await client.disconnect()
        if os.path.exists(f"{telethon_path}.session"):
            os.remove(f"{telethon_path}.session")

    zip_path = f"{output_path}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(output_path):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.join("tdata", os.path.relpath(file_path, output_path))
                zf.write(file_path, arcname)

    shutil.rmtree(output_path)

    return zip_path