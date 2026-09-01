import os
import asyncio

# --- RENDER PYTHON ASYNCIO FIX (Sabse upar hona zaroori hai!) ---
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
# -----------------------------------------------------------------

import threading
from flask import Flask
from pyrogram import Client

from config import API_ID, API_HASH, BOT_TOKEN


# ============================================================
# DUMMY WEB SERVER FOR RENDER
# ============================================================

web_app = Flask(__name__)


@web_app.route('/')
def home():
    return "ScreenEmpire Bot is Running Alive!"


def run_web():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host="0.0.0.0", port=port)


threading.Thread(target=run_web, daemon=True).start()


# ============================================================
# PYROGRAM
# ============================================================

app = Client(
    "ScreenEmpireBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    plugins={"root": "plugins"}
)


# ============================================================
# START BOT
# ============================================================

if __name__ == "__main__":
    app.run()
