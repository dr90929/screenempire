```python
import os
import asyncio
import re
import threading
import logging

from flask import Flask

from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message
)
from pyrogram.errors import UserNotParticipant

from motor.motor_asyncio import AsyncIOMotorClient


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("ScreenEmpireBot")


# ============================================================
# RENDER WEB SERVER
# ============================================================

web_app = Flask(__name__)


@web_app.route("/")
def home():
    return "ScreenEmpire Bot is Running Alive!"


def run_web():
    port = int(os.environ.get("PORT", 8080))

    web_app.run(
        host="0.0.0.0",
        port=port
    )


threading.Thread(
    target=run_web,
    daemon=True
).start()


# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

API_ID = int(os.environ.get("API_ID", "0"))

API_HASH = os.environ.get(
    "API_HASH",
    ""
)

BOT_TOKEN = os.environ.get(
    "BOT_TOKEN",
    ""
)

CHANNEL_USERNAME = os.environ.get(
    "CHANNEL_USERNAME",
    "ScreenEmpire"
).lstrip("@")

DB_CHANNEL = int(
    os.environ.get(
        "DB_CHANNEL",
        "0"
    )
)

AUTO_DELETE_TIME = int(
    os.environ.get(
        "AUTO_DELETE_TIME",
        "60"
    )
)

DATABASE_URI = os.environ.get(
    "DATABASE_URI",
    ""
)


# Maximum search results
MAX_RESULTS = int(
    os.environ.get(
        "MAX_RESULTS",
        "5"
    )
)


# ============================================================
# MONGODB
# ============================================================

db_client = AsyncIOMotorClient(
    DATABASE_URI,
    serverSelectionTimeoutMS=5000
)

db = db_client["ScreenEmpireDB"]

collection = db["movies"]


# ============================================================
# PYROGRAM
# ============================================================

app = Client(
    "ScreenEmpireBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)


# ============================================================
# SEARCH NORMALIZATION
# ============================================================

def normalize_filename(text: str) -> str:
    """
    Converts filename into a search-friendly format.

    Example:

    Hanuman.Ansh_2025-1080p.mkv

    becomes:

    hanumanansh20251080pmkv
    """

    if not text:
        return ""

    text = text.lower().strip()

    # Keep only letters and numbers.
    # This removes:
    # .
    # _
    # -
    # spaces
    # brackets
    # etc.

    return re.sub(
        r"[^a-z0-9]+",
        "",
        text
    )


def extract_search_tokens(text: str):
    """
    Break user query into meaningful words.

    Examples:

    Hanuman Ansh
    ->
    ["hanuman", "ansh"]

    Hanuman-Ansh
    ->
    ["hanuman", "ansh"]

    Hanuman.Ansh
    ->
    ["hanuman", "ansh"]
    """

    if not text:
        return []

    text = text.lower().strip()

    tokens = re.findall(
        r"[a-z0-9]+",
        text
    )

    return list(
        dict.fromkeys(tokens)
    )


# ============================================================
# DATABASE INDEX SETUP
# ============================================================

async def setup_database():
    """
    Creates MongoDB indexes.

    This improves search and duplicate detection.
    """

    try:
        await collection.create_index(
            "message_id",
            unique=True
        )

        await collection.create_index(
            "search_name"
        )

        await collection.create_index(
            "file_name"
        )

        logger.info(
            "MongoDB indexes are ready."
        )

    except Exception as e:
        logger.error(
            f"Database index error: {e}"
        )


# ============================================================
# FORCE SUBSCRIPTION
# ============================================================

async def is_subscribed(
    client,
    user_id
):
    """
    Checks whether user joined the channel.

    IMPORTANT:
    Unexpected Telegram errors are NOT automatically
    treated as subscribed anymore.
    """

    try:

        member = await client.get_chat_member(
            CHANNEL_USERNAME,
            user_id
        )

        status = str(
            member.status
        ).lower()

        # These statuses mean the user is actually inside.
        if status in {
            "member",
            "administrator",
            "owner"
        }:
            return True

        return False

    except UserNotParticipant:
        return False

    except Exception as e:

        logger.error(
            f"Subscription check error: {e}"
        )

        # Safer behavior:
        # if Telegram check fails, deny access
        return False


# ============================================================
# AUTO SAVE FILES
# ============================================================

@app.on_message(
    filters.chat(DB_CHANNEL)
    & (filters.document | filters.video)
)
async def auto_save(
    client,
    message: Message
):

    try:

        file = (
            message.document
            or message.video
        )

        if not file:
            return

        file_name = (
            file.file_name
            if file.file_name
            else "Unknown_File"
        )

        search_name = normalize_filename(
            file_name
        )

        # ----------------------------------------------------
        # DUPLICATE PROTECTION
        # ----------------------------------------------------

        existing = await collection.find_one(
            {
                "message_id": message.id
            }
        )

        if existing:

            logger.info(
                f"Already saved: {file_name}"
            )

            return

        # ----------------------------------------------------
        # SAVE
        # ----------------------------------------------------

        await collection.insert_one(
            {
                "file_name": file_name,
                "search_name": search_name,
                "message_id": message.id
            }
        )

        logger.info(
            f"Saved to database: {file_name}"
        )

    except Exception as e:

        logger.error(
            f"Auto-save error: {e}"
        )


# ============================================================
# SEND FILE HELPER
# ============================================================

async def send_file_with_auto_delete(
    client,
    chat_id,
    message_id,
    file_name=None
):

    try:

        sent_msg = await client.copy_message(
            chat_id=chat_id,
            from_chat_id=DB_CHANNEL,
            message_id=message_id,
            caption=(
                f"🎬 **{file_name or 'Here is your file!'}**\n\n"
                f"🍿 Powered by **ScreenEmpire**"
            )
        )

        # ----------------------------------------------------
        # TIME LABEL
        # ----------------------------------------------------

        if AUTO_DELETE_TIME >= 60:

            minutes = AUTO_DELETE_TIME // 60

            time_label = (
                f"{minutes} minute"
                if minutes == 1
                else f"{minutes} minutes"
            )

        else:

            time_label = (
                f"{AUTO_DELETE_TIME} seconds"
            )

        warning_text = await client.send_message(
            chat_id,
            (
                f"⏱️ **Auto-Delete Notice**\n\n"
                f"This file will auto-delete in "
                f"**{time_label}**.\n\n"
                f"💾 Please save or forward it immediately!"
            ),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "📢 Join Main Channel",
                            url=f"https://t.me/{CHANNEL_USERNAME}"
                        )
                    ]
                ]
            )
        )

        # ----------------------------------------------------
        # AUTO DELETE TASK
        # ----------------------------------------------------

        async def delete_after_delay():

            await asyncio.sleep(
                AUTO_DELETE_TIME
            )

            try:
                await sent_msg.delete()

            except Exception:
                pass

            try:
                await warning_text.delete()

            except Exception:
                pass

        asyncio.create_task(
            delete_after_delay()
        )

        return sent_msg

    except Exception as e:

        logger.error(
            f"File sending error: {e}"
        )

        return None


# ============================================================
# START COMMAND
# ============================================================

@app.on_message(
    filters.command("start")
    & filters.private
)
async def start_command(
    client,
    message: Message
):

    user_id = message.from_user.id

    user_name = (
        message.from_user.first_name
        or "Buddy"
    )

    # --------------------------------------------------------
    # FORCE SUBSCRIBE
    # --------------------------------------------------------

    if CHANNEL_USERNAME:

        subscribed = await is_subscribed(
            client,
            user_id
        )

        if not subscribed:

            btn = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "📢 Join ScreenEmpire",
                            url=f"https://t.me/{CHANNEL_USERNAME}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "🔄 Try Again",
                            callback_data="check_sub"
                        )
                    ]
                ]
            )

            await message.reply_text(
                (
                    f"Hey 👋 **{user_name}** 🤩\n\n"
                    f"⚠️ **Access Restricted!**\n\n"
                    f"To access the world's coolest movie "
                    f"database, you must join our official "
                    f"channel first."
                ),
                reply_markup=btn
            )

            return

    # --------------------------------------------------------
    # DEEP LINK
    # --------------------------------------------------------

    if len(message.command) > 1:

        try:

            file_id = int(
                message.command[1]
            )

            msg = await client.get_messages(
                DB_CHANNEL,
                file_id
            )

            if not msg:

                await message.reply_text(
                    "❌ **File not found!**"
                )

                return

            await send_file_with_auto_delete(
                client,
                message.chat.id,
                file_id
            )

            return

        except Exception as e:

            logger.error(
                f"Deep-link error: {e}"
            )

            await message.reply_text(
                (
                    "❌ **Error:** File not found "
                    "or invalid link!"
                )
            )

            return

    # --------------------------------------------------------
    # HOME MENU
    # --------------------------------------------------------

    home_keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔎 SEARCH MOVIES OR SERIES 🔎",
                    url=f"https://t.me/{CHANNEL_USERNAME}"
                )
            ],
            [
                InlineKeyboardButton(
                    "📤 SHARE NOW 📤",
                    url=(
                        "https://t.me/share/url?"
                        "url=https://t.me/ScreenEmpireBot"
                        "&text=Join%20ScreenEmpire%20for%20"
                        "the%20latest%20Movies%20and%20Web%20Series!"
                    )
                )
            ]
        ]
    )

    await message.reply_text(
        (
            f"Hey 👋 **{user_name}** 🤩\n\n"
            f"🍿 **WELCOME TO THE WORLD'S COOLEST MOVIE HUB!**\n\n"
            f"Send me the real Movie or Web Series "
            f"name with proper English spelling and "
            f"I'll find your files instantly..!!"
        ),
        reply_markup=home_keyboard
    )


# ============================================================
# TRY AGAIN BUTTON
# ============================================================

@app.on_callback_query(
    filters.regex("^check_sub$")
)
async def check_subscription_callback(
    client,
    callback_query
):

    user_id = callback_query.from_user.id

    subscribed = await is_subscribed(
        client,
        user_id
    )

    if not subscribed:

        await callback_query.answer(
            "❌ You haven't joined the channel yet.",
            show_alert=True
        )

        return

    await callback_query.answer(
        "✅ Subscription verified!",
        show_alert=True
    )

    await callback_query.message.edit_text(
        (
            "✅ **Verified successfully!**\n\n"
            "Now send me the movie or series name "
            "you want to search. 🍿"
        )
    )


# ============================================================
# SMART MOVIE SEARCH
# ============================================================

@app.on_message(
    filters.private
    & filters.text
    & ~filters.command("start")
)
async def search_movie(
    client,
    message: Message
):

    user_id = message.from_user.id

    # --------------------------------------------------------
    # FORCE SUBSCRIBE
    # --------------------------------------------------------

    if CHANNEL_USERNAME:

        subscribed = await is_subscribed(
            client,
            user_id
        )

        if not subscribed:

            await message.reply_text(
                (
                    f"⚠️ You must join "
                    f"@{CHANNEL_USERNAME} "
                    f"to search movies."
                )
            )

            return

    # --------------------------------------------------------
    # USER QUERY
    # --------------------------------------------------------

    query = message.text.strip()

    if not query:

        return

    # Ignore extremely tiny queries
    if len(query) < 2:

        await message.reply_text(
            "🔎 Please enter at least 2 characters."
        )

        return

    # --------------------------------------------------------
    # NORMALIZED QUERY
    # --------------------------------------------------------

    normalized_query = normalize_filename(
        query
    )

    tokens = extract_search_tokens(
        query
    )

    if not normalized_query:

        await message.reply_text(
            "❌ Please enter a valid movie name."
        )

        return

    # --------------------------------------------------------
    # SMART MONGODB SEARCH
    # --------------------------------------------------------

    # First try normalized search.
    #
    # Example:
    #
    # User:
    # Hanuman Ansh
    #
    # normalized:
    # hanumanansh
    #
    # Database:
    # hanumanansh20251080p...
    #
    # MATCH ✅

    results = []

    try:

        cursor = collection.find(
            {
                "search_name": {
                    "$regex": re.escape(
                        normalized_query
                    ),
                    "$options": "i"
                }
            }
        ).limit(
            MAX_RESULTS
        )

        results = await cursor.to_list(
            length=MAX_RESULTS
        )

    except Exception as e:

        logger.error(
            f"Normalized search error: {e}"
        )

    # --------------------------------------------------------
    # TOKEN SEARCH FALLBACK
    # --------------------------------------------------------

    # This is VERY important.
    #
    # Example:
    #
    # File:
    # Hanuman.Ansh.2025.mkv
    #
    # User:
    # Hanuman 2025
    #
    # Normalized:
    # hanuman2025
    #
    # Direct contiguous search may fail because
    # "ansh" exists between them.
    #
    # Token search solves this.

    if not results and tokens:

        try:

            and_conditions = []

            for token in tokens:

                safe_token = re.escape(
                    token
                )

                and_conditions.append(
                    {
                        "file_name": {
                            "$regex": safe_token,
                            "$options": "i"
                        }
                    }
                )

            cursor = collection.find(
                {
                    "$and": and_conditions
                }
            ).limit(
                MAX_RESULTS
            )

            results = await cursor.to_list(
                length=MAX_RESULTS
            )

        except Exception as e:

            logger.error(
                f"Token search error: {e}"
            )

    # --------------------------------------------------------
    # NO RESULTS
    # --------------------------------------------------------

    if not results:

        await message.reply_text(
            (
                f"❌ **No movies found for "
                f"'{query}'!**\n\n"
                f"💡 Try:\n"
                f"• Different spelling\n"
                f"• Movie name only\n"
                f"• Series name only"
            )
        )

        return

    # --------------------------------------------------------
    # SEND RESULTS
    # --------------------------------------------------------

    sent_count = 0

    for res in results:

        try:

            message_id = res.get(
                "message_id"
            )

            file_name = res.get(
                "file_name",
                "Unknown File"
            )

            if not message_id:

                continue

            sent_msg = await send_file_with_auto_delete(
                client,
                message.chat.id,
                message_id,
                file_name
            )

            if sent_msg:

                sent_count += 1

        except Exception as e:

            logger.error(
                f"Search result error: {e}"
            )

    # --------------------------------------------------------
    # OPTIONAL SEARCH SUMMARY
    # --------------------------------------------------------

    if sent_count == 0:

        await message.reply_text(
            "❌ Unable to send the matching files."
        )


# ============================================================
# STARTUP
# ============================================================

async def startup():

    await setup_database()

    logger.info(
        "ScreenEmpire Bot database initialized."
    )


if __name__ == "__main__":

    # Run database setup before bot starts
    asyncio.get_event_loop().run_until_complete(
        startup()
    )

    logger.info(
        "Starting ScreenEmpire Bot..."
    )

    app.run()
```
