import os
import asyncio
import re
import html
import uuid
from datetime import datetime, timedelta

# --- RENDER PYTHON ASYNCIO FIX (Yeh 2 lines error fix karengi) ---
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
# -----------------------------------------------------------------

import threading
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from pyrogram.errors import UserNotParticipant
from motor.motor_asyncio import AsyncIOMotorClient

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
# ENVIRONMENT VARIABLES
# ============================================================

API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

CHANNEL_USERNAME = os.environ.get(
    "CHANNEL_USERNAME",
    "ScreenEmpire"
).lstrip("@")

DB_CHANNEL = int(
    os.environ.get("DB_CHANNEL", 0)
)

AUTO_DELETE_TIME = int(
    os.environ.get("AUTO_DELETE_TIME", 60)
)

DATABASE_URI = os.environ.get(
    "DATABASE_URI",
    ""
)

# NEW:
# Add your Telegram numeric user ID in Render:
# ADMIN_ID = 123456789
ADMIN_ID = int(
    os.environ.get("ADMIN_ID", 0)
)

# ============================================================
# SEARCH SETTINGS
# ============================================================

RESULTS_PER_PAGE = 5

# Maximum number of matching files kept in one search session.
# This prevents unnecessarily large temporary sessions.
MAX_SEARCH_RESULTS = 100

# ============================================================
# MONGODB SETUP
# ============================================================

db_client = AsyncIOMotorClient(DATABASE_URI)

db = db_client["ScreenEmpireDB"]

collection = db["movies"]

users_collection = db["users"]

search_sessions = db["search_sessions"]

# Temporary in-memory state for admin broadcast.
# It is only used while the bot process is running.
broadcast_pending = set()

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
# TEXT / SEARCH HELPERS
# ============================================================

def normalize_text(text):
    """
    Removes separators and symbols for smart searching.

    Examples:

    Hanuman.Ansh
    Hanuman-Ansh
    Hanuman_Ansh
    Hanuman Ansh

    all become:

    hanumanansh
    """

    if not text:
        return ""

    return re.sub(
        r"[^a-zA-Z0-9]",
        "",
        text
    ).lower()


def get_search_tokens(text):
    """
    Splits a search query into words.

    Example:

    Hanuman Ansh
    ->
    ["hanuman", "ansh"]

    Hanuman-Ansh
    ->
    ["hanuman", "ansh"]
    """

    if not text:
        return []

    return re.findall(
        r"[a-zA-Z0-9]+",
        text.lower()
    )


def format_file_size(size):
    """
    Converts bytes into readable file size.
    """

    if not size:
        return "Unknown Size"

    size = float(size)

    units = [
        "B",
        "KB",
        "MB",
        "GB",
        "TB"
    ]

    index = 0

    while size >= 1024 and index < len(units) - 1:
        size /= 1024
        index += 1

    if index == 0:
        return f"{int(size)} {units[index]}"

    return f"{size:.2f} {units[index]}"


def get_file_from_message(message):
    """
    Returns document/video object.
    """

    return message.document or message.video


def get_file_name_from_message(message):
    """
    Safely gets filename.
    """

    file = get_file_from_message(message)

    if not file:
        return "Unknown_File"

    return file.file_name or "Unknown_File"


def get_file_size_from_message(message):
    """
    Safely gets file size.
    """

    file = get_file_from_message(message)

    if not file:
        return 0

    return file.file_size or 0


# ============================================================
# USER TRACKING
# ============================================================

async def track_user(user):
    """
    Automatically creates/updates user record.

    This is used by /stats and /broadcast.
    """

    if not user:
        return

    try:

        now = datetime.utcnow()

        await users_collection.update_one(
            {
                "user_id": user.id
            },
            {
                "$set": {
                    "first_name": user.first_name or "",
                    "last_name": user.last_name or "",
                    "username": user.username or "",
                    "last_seen": now
                },
                "$setOnInsert": {
                    "user_id": user.id,
                    "joined_at": now,
                    "blocked": False
                }
            },
            upsert=True
        )

    except Exception as e:

        print(
            f"User tracking error: {e}"
        )


# ============================================================
# FORCE SUBSCRIPTION
# ============================================================

async def is_subscribed(client, user_id):
    try:

        await client.get_chat_member(
            CHANNEL_USERNAME,
            user_id
        )

        return True

    except UserNotParticipant:

        return False

    except Exception:

        # Keeping original behavior so a temporary Telegram
        # API issue does not unexpectedly block all users.
        return True


# ============================================================
# SAVE / UPDATE FILE INDEX
# ============================================================

async def save_file_to_database(message):
    """
    MongoDB stores only file metadata/index.

    Actual file remains inside Telegram DB channel.
    """

    file_name = get_file_name_from_message(
        message
    )

    file_size = get_file_size_from_message(
        message
    )

    search_name = normalize_text(
        file_name
    )

    existing = await collection.find_one({
        "message_id": message.id
    })

    if existing:

        # Updates old records so /index can add the
        # new fields to already existing database entries.
        await collection.update_one(
            {
                "_id": existing["_id"]
            },
            {
                "$set": {
                    "file_name": file_name,
                    "file_size": file_size,
                    "search_name": search_name
                }
            }
        )

        return False

    await collection.insert_one({
        "file_name": file_name,
        "message_id": message.id,
        "file_size": file_size,
        "search_name": search_name
    })

    return True


# ============================================================
# 1. AUTO-SAVE FEATURE
# ============================================================

@app.on_message(
    filters.chat(DB_CHANNEL)
    & (filters.document | filters.video)
)
async def auto_save(client, message: Message):

    try:

        saved = await save_file_to_database(
            message
        )

        file_name = get_file_name_from_message(
            message
        )

        if saved:

            print(
                f"Saved to Database: {file_name}"
            )

        else:

            print(
                f"Updated/Already indexed: {file_name}"
            )

    except Exception as e:

        print(
            f"Database save error: {e}"
        )


# ============================================================
# AUTO DELETE HELPER
# ============================================================

async def delete_message_after_delay(
    message,
    delay
):

    await asyncio.sleep(
        delay
    )

    try:
        await message.delete()
    except Exception:
        pass


# ============================================================
# SEND REQUESTED FILE
# ============================================================

async def send_requested_file(
    client,
    user_chat_id,
    message_id
):

    try:

        original_message = await client.get_messages(
            DB_CHANNEL,
            message_id
        )

        if not original_message:

            return None, "❌ File not found."

        file = get_file_from_message(
            original_message
        )

        if not file:

            return None, "❌ This message does not contain a file."

        file_name = get_file_name_from_message(
            original_message
        )

        safe_file_name = html.escape(
            file_name
        )

        # ----------------------------------------------------
        # COPY FILE FROM PRIVATE DB CHANNEL
        # ----------------------------------------------------

        sent_msg = await client.copy_message(
            chat_id=user_chat_id,
            from_chat_id=DB_CHANNEL,
            message_id=message_id,
            caption=(
                f"🎬 <b>{safe_file_name}</b>\n\n"
                f"🍿 Powered by <b>ScreenEmpire</b>"
            ),
            parse_mode="html"
        )

        # ----------------------------------------------------
        # WARNING
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
            user_chat_id,
            (
                f"⏱️ <b>Auto-Delete Notice:</b>\n\n"
                f"This file will auto-delete in "
                f"<b>{time_label}</b>.\n\n"
                f"💾 Please save or forward it immediately!"
            ),
            parse_mode="html",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⚡ Join Main Channel",
                        url=f"https://t.me/{CHANNEL_USERNAME}"
                    )
                ]
            ])
        )

        # File timer starts when the file is actually requested.
        asyncio.create_task(
            delete_message_after_delay(
                sent_msg,
                AUTO_DELETE_TIME
            )
        )

        asyncio.create_task(
            delete_message_after_delay(
                warning_text,
                AUTO_DELETE_TIME
            )
        )

        return sent_msg, None

    except Exception as e:

        print(
            f"File sending error: {e}"
        )

        return None, (
            "❌ Unable to send this file right now."
        )


# ============================================================
# RESULT BUTTON KEYBOARD
# ============================================================

def build_results_keyboard(
    results,
    page,
    total_pages,
    session_id
):

    buttons = []

    start_index = (
        page * RESULTS_PER_PAGE
    )

    end_index = min(
        start_index + RESULTS_PER_PAGE,
        len(results)
    )

    # --------------------------------------------------------
    # FILE BUTTONS
    # --------------------------------------------------------

    for index in range(
        start_index,
        end_index
    ):

        result = results[index]

        file_name = result.get(
            "file_name",
            "Unknown File"
        )

        file_size = result.get(
            "file_size",
            0
        )

        size_text = format_file_size(
            file_size
        )

        # Keep filename readable inside Telegram button.
        max_name_length = 55

        if len(file_name) > max_name_length:

            button_file_name = (
                file_name[:max_name_length - 3]
                + "..."
            )

        else:

            button_file_name = file_name

        button_text = (
            f"{size_text} • {button_file_name}"
        )

        buttons.append([
            InlineKeyboardButton(
                button_text,
                callback_data=(
                    f"file:{session_id}:{index}"
                )
            )
        ])

    # --------------------------------------------------------
    # PAGINATION
    # --------------------------------------------------------

    navigation = []

    if page > 0:

        navigation.append(
            InlineKeyboardButton(
                "⏪ Previous",
                callback_data=(
                    f"page:{session_id}:{page - 1}"
                )
            )
        )

    navigation.append(
        InlineKeyboardButton(
            f"{page + 1}/{total_pages}",
            callback_data="page_current"
        )
    )

    if page < total_pages - 1:

        navigation.append(
            InlineKeyboardButton(
                "Next ⏩",
                callback_data=(
                    f"page:{session_id}:{page + 1}"
                )
            )
        )

    buttons.append(
        navigation
    )

    return InlineKeyboardMarkup(
        buttons
    )


# ============================================================
# 2. START COMMAND
# ============================================================

@app.on_message(
    filters.command("start")
    & filters.private
)
async def start_command(
    client,
    message: Message
):

    # Track user automatically.
    await track_user(
        message.from_user
    )

    user_id = message.from_user.id

    user_name = (
        message.from_user.first_name
        or "Buddy"
    )

    # --------------------------------------------------------
    # FORCE SUBSCRIBE CHECK
    # --------------------------------------------------------

    if CHANNEL_USERNAME:

        not_joined = not await is_subscribed(
            client,
            user_id
        )

        if not_joined:

            btn = InlineKeyboardMarkup([
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
            ])

            await message.reply_text(
                (
                    f"Hey 👋 <b>{html.escape(user_name)}</b> 🤩\n\n"
                    f"⚠️ <b>Access Restricted!</b>\n"
                    f"To access the world's coolest movie "
                    f"database, you must join our official "
                    f"channel first."
                ),
                reply_markup=btn,
                parse_mode="html"
            )

            return

    # --------------------------------------------------------
    # DEEP LINKING
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

            if msg:

                sent_msg, error = await send_requested_file(
                    client,
                    message.chat.id,
                    file_id
                )

                if error:

                    await message.reply_text(
                        error
                    )

                return

        except Exception:

            await message.reply_text(
                "❌ <b>Error:</b> File not found or invalid link!",
                parse_mode="html"
            )

            return

    # --------------------------------------------------------
    # PROFESSIONAL HOME MENU
    # --------------------------------------------------------

    home_keyboard = InlineKeyboardMarkup([
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
                    "&text=Join%20ScreenEmpire%20for%20the%20latest%20"
                    "Movies%20and%20Web%20Series!"
                )
            )
        ]
    ])

    await message.reply_text(
        (
            f"Hey 👋 <b>{html.escape(user_name)}</b> 🤩\n\n"
            f"🍿 <b>WELCOME TO THE WORLD'S COOLEST MOVIE HUB!</b>\n\n"
            f"Here You Can Request Movies & Web Series. "
            f"Just send the real Movie or Web Series name "
            f"with proper English spelling to get your files "
            f"instantly..!!"
        ),
        reply_markup=home_keyboard,
        parse_mode="html"
    )


# ============================================================
# 3. TRY AGAIN BUTTON
# ============================================================

@app.on_callback_query(
    filters.regex("^check_sub$")
)
async def check_subscription_callback(
    client,
    callback_query
):

    user_id = callback_query.from_user.id

    await track_user(
        callback_query.from_user
    )

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
            "✅ <b>Verified successfully!</b>\n\n"
            "Now send me the movie or series name "
            "you want to search. 🍿"
        ),
        parse_mode="html"
    )


# ============================================================
# 4. PAGINATION CALLBACK
# ============================================================

@app.on_callback_query(
    filters.regex(r"^page:")
)
async def pagination_callback(
    client,
    callback_query
):

    try:

        parts = callback_query.data.split(":")

        if len(parts) != 3:

            await callback_query.answer()
            return

        session_id = parts[1]

        page = int(
            parts[2]
        )

        session = await search_sessions.find_one({
            "_id": session_id
        })

        if not session:

            await callback_query.answer(
                "❌ This search has expired.",
                show_alert=True
            )

            return

        # Only owner can use this search session.
        if session.get(
            "user_id"
        ) != callback_query.from_user.id:

            await callback_query.answer(
                "❌ This search belongs to another user.",
                show_alert=True
            )

            return

        results = session.get(
            "results",
            []
        )

        if not results:

            await callback_query.answer(
                "❌ No results available.",
                show_alert=True
            )

            return

        total_pages = (
            len(results)
            + RESULTS_PER_PAGE
            - 1
        ) // RESULTS_PER_PAGE

        if page < 0 or page >= total_pages:

            await callback_query.answer()
            return

        keyboard = build_results_keyboard(
            results,
            page,
            total_pages,
            session_id
        )

        await callback_query.message.edit_reply_markup(
            reply_markup=keyboard
        )

        await callback_query.answer()

    except Exception as e:

        print(
            f"Pagination error: {e}"
        )

        await callback_query.answer(
            "❌ Unable to change page.",
            show_alert=True
        )


# ============================================================
# 5. FILE BUTTON CALLBACK
# ============================================================

@app.on_callback_query(
    filters.regex(r"^file:")
)
async def file_button_callback(
    client,
    callback_query
):

    try:

        parts = callback_query.data.split(":")

        if len(parts) != 3:

            await callback_query.answer(
                "❌ Invalid file button.",
                show_alert=True
            )

            return

        session_id = parts[1]

        result_index = int(
            parts[2]
        )

        session = await search_sessions.find_one({
            "_id": session_id
        })

        if not session:

            await callback_query.answer(
                "❌ This search has expired.",
                show_alert=True
            )

            return

        # Only owner can use this result list.
        if session.get(
            "user_id"
        ) != callback_query.from_user.id:

            await callback_query.answer(
                "❌ This search belongs to another user.",
                show_alert=True
            )

            return

        results = session.get(
            "results",
            []
        )

        if (
            result_index < 0
            or result_index >= len(results)
        ):

            await callback_query.answer(
                "❌ File not found.",
                show_alert=True
            )

            return

        result = results[
            result_index
        ]

        message_id = result.get(
            "message_id"
        )

        if not message_id:

            await callback_query.answer(
                "❌ Invalid file record.",
                show_alert=True
            )

            return

        await callback_query.answer(
            "📤 Sending your file..."
        )

        sent_msg, error = await send_requested_file(
            client,
            callback_query.message.chat.id,
            message_id
        )

        if error:

            await client.send_message(
                callback_query.message.chat.id,
                error
            )

    except Exception as e:

        print(
            f"File button error: {e}"
        )

        try:

            await callback_query.answer(
                "❌ Something went wrong.",
                show_alert=True
            )

        except Exception:
            pass


# ============================================================
# 6. ADMIN /INDEX COMMAND
# ============================================================

@app.on_message(
    filters.command("index")
    & filters.private
)
async def index_command(
    client,
    message: Message
):

    await track_user(
        message.from_user
    )

    # --------------------------------------------------------
    # ADMIN ONLY
    # --------------------------------------------------------

    if ADMIN_ID == 0:

        await message.reply_text(
            "❌ ADMIN_ID is not configured."
        )

        return

    if message.from_user.id != ADMIN_ID:

        await message.reply_text(
            "❌ You are not authorized to use this command."
        )

        return

    progress_message = await message.reply_text(
        "🔄 <b>Starting DB Channel indexing...</b>\n\n"
        "Please wait...",
        parse_mode="html"
    )

    scanned = 0
    saved = 0
    updated = 0
    skipped = 0
    errors = 0

    try:

        # ----------------------------------------------------
        # COMPLETE PRIVATE DB CHANNEL HISTORY
        # ----------------------------------------------------

        async for channel_message in client.get_chat_history(
            DB_CHANNEL
        ):

            scanned += 1

            try:

                if not (
                    channel_message.document
                    or channel_message.video
                ):

                    skipped += 1
                    continue

                existing = await collection.find_one({
                    "message_id": channel_message.id
                })

                was_saved = await save_file_to_database(
                    channel_message
                )

                if was_saved:

                    saved += 1

                elif existing:

                    updated += 1

                else:

                    skipped += 1

            except Exception as e:

                errors += 1

                print(
                    f"Index error at message "
                    f"{channel_message.id}: {e}"
                )

            # Progress every 500 messages.
            if scanned % 500 == 0:

                try:

                    await progress_message.edit_text(
                        (
                            f"🔄 <b>Indexing DB Channel...</b>\n\n"
                            f"📥 Scanned: <b>{scanned}</b>\n"
                            f"💾 New files: <b>{saved}</b>\n"
                            f"🔄 Updated: <b>{updated}</b>\n"
                            f"⏭️ Skipped: <b>{skipped}</b>\n"
                            f"❌ Errors: <b>{errors}</b>"
                        ),
                        parse_mode="html"
                    )

                except Exception:
                    pass

        # ----------------------------------------------------
        # COMPLETE
        # ----------------------------------------------------

        await progress_message.edit_text(
            (
                f"✅ <b>Indexing Completed!</b>\n\n"
                f"📥 Total messages scanned: <b>{scanned}</b>\n"
                f"💾 New files indexed: <b>{saved}</b>\n"
                f"🔄 Existing records updated: <b>{updated}</b>\n"
                f"⏭️ Non-file messages: <b>{skipped}</b>\n"
                f"❌ Errors: <b>{errors}</b>"
            ),
            parse_mode="html"
        )

    except Exception as e:

        print(
            f"Index command error: {e}"
        )

        try:

            await progress_message.edit_text(
                (
                    f"❌ <b>Indexing failed!</b>\n\n"
                    f"📥 Scanned: <b>{scanned}</b>\n"
                    f"💾 New files: <b>{saved}</b>\n"
                    f"🔄 Updated: <b>{updated}</b>\n"
                    f"❌ Errors: <b>{errors}</b>\n\n"
                    f"<code>{html.escape(str(e))}</code>"
                ),
                parse_mode="html"
            )

        except Exception:
            pass


# ============================================================
# 7. ADMIN /STATS COMMAND
# ============================================================

@app.on_message(
    filters.command("stats")
    & filters.private
)
async def stats_command(
    client,
    message: Message
):

    await track_user(
        message.from_user
    )

    # --------------------------------------------------------
    # ADMIN ONLY
    # --------------------------------------------------------

    if ADMIN_ID == 0:

        await message.reply_text(
            "❌ ADMIN_ID is not configured."
        )

        return

    if message.from_user.id != ADMIN_ID:

        await message.reply_text(
            "❌ You are not authorized to use this command."
        )

        return

    try:

        # ----------------------------------------------------
        # USER STATS
        # ----------------------------------------------------

        total_users = await users_collection.count_documents({})

        blocked_users = await users_collection.count_documents({
            "blocked": True
        })

        active_since = (
            datetime.utcnow()
            - timedelta(days=30)
        )

        active_users = await users_collection.count_documents({
            "last_seen": {
                "$gte": active_since
            }
        })

        # ----------------------------------------------------
        # FILE STATS
        # ----------------------------------------------------

        total_files = await collection.count_documents({})

        # ----------------------------------------------------
        # SEARCH SESSION STATS
        # ----------------------------------------------------

        total_search_sessions = await search_sessions.count_documents({})

        await message.reply_text(
            (
                "📊 <b>ScreenEmpire Bot Stats</b>\n\n"
                f"👥 <b>Total Users:</b> {total_users}\n"
                f"🟢 <b>Active Users (30 days):</b> {active_users}\n"
                f"🚫 <b>Blocked Users:</b> {blocked_users}\n\n"
                f"📁 <b>Total Indexed Files:</b> {total_files}\n"
                f"🔎 <b>Active Search Sessions:</b> {total_search_sessions}"
            ),
            parse_mode="html"
        )

    except Exception as e:

        print(
            f"Stats error: {e}"
        )

        await message.reply_text(
            "❌ Unable to load statistics."
        )


# ============================================================
# 8. ADMIN /BROADCAST COMMAND
# ============================================================

@app.on_message(
    filters.command("broadcast")
    & filters.private
)
async def broadcast_command(
    client,
    message: Message
):

    await track_user(
        message.from_user
    )

    # --------------------------------------------------------
    # ADMIN ONLY
    # --------------------------------------------------------

    if ADMIN_ID == 0:

        await message.reply_text(
            "❌ ADMIN_ID is not configured."
        )

        return

    if message.from_user.id != ADMIN_ID:

        await message.reply_text(
            "❌ You are not authorized to use this command."
        )

        return

    # --------------------------------------------------------
    # /broadcast <text>
    # --------------------------------------------------------

    command_text = message.text.split(
        maxsplit=1
    )

    if len(command_text) > 1:

        broadcast_text = command_text[1].strip()

        if not broadcast_text:

            await message.reply_text(
                "❌ Broadcast message cannot be empty."
            )

            return

        broadcast_message = await message.reply_text(
            "📢 <b>Broadcast started...</b>",
            parse_mode="html"
        )

        sent = 0
        failed = 0
        total = 0

        cursor = users_collection.find({
            "blocked": {
                "$ne": True
            }
        })

        async for user_record in cursor:

            total += 1

            target_user_id = user_record.get(
                "user_id"
            )

            if not target_user_id:
                continue

            try:

                await client.send_message(
                    target_user_id,
                    broadcast_text
                )

                sent += 1

                # Small delay to reduce the chance of
                # hitting Telegram rate limits.
                await asyncio.sleep(0.05)

            except Exception as e:

                failed += 1

                # If user has blocked the bot or cannot
                # receive messages, mark them.
                error_text = str(e).lower()

                if (
                    "blocked" in error_text
                    or "user is deactivated" in error_text
                    or "peer id invalid" in error_text
                ):

                    try:

                        await users_collection.update_one(
                            {
                                "user_id": target_user_id
                            },
                            {
                                "$set": {
                                    "blocked": True
                                }
                            }
                        )

                    except Exception:
                        pass

        try:

            await broadcast_message.edit_text(
                (
                    "📢 <b>Broadcast Completed!</b>\n\n"
                    f"👥 Total users: <b>{total}</b>\n"
                    f"✅ Sent: <b>{sent}</b>\n"
                    f"❌ Failed: <b>{failed}</b>"
                ),
                parse_mode="html"
            )

        except Exception:
            pass

        return

    # --------------------------------------------------------
    # INTERACTIVE BROADCAST MODE
    #
    # Admin can simply send:
    #
    # /broadcast
    #
    # Then send the message separately.
    # --------------------------------------------------------

    broadcast_pending.add(
        message.from_user.id
    )

    await message.reply_text(
        (
            "📢 <b>Broadcast Mode</b>\n\n"
            "Now send the message you want to broadcast.\n\n"
            "Send /cancel to cancel."
        ),
        parse_mode="html"
    )


# ============================================================
# 9. ADMIN BROADCAST MESSAGE CAPTURE
# ============================================================

@app.on_message(
    filters.private
)
async def broadcast_message_capture(
    client,
    message: Message
):

    # Only process users who explicitly entered
    # broadcast mode.
    if message.from_user.id not in broadcast_pending:
        return

    # Don't process the /broadcast command itself.
    if message.text and message.text.startswith("/broadcast"):
        return

    # --------------------------------------------------------
    # CANCEL
    # --------------------------------------------------------

    if (
        message.text
        and message.text.strip().lower() == "/cancel"
    ):

        broadcast_pending.discard(
            message.from_user.id
        )

        await message.reply_text(
            "❌ Broadcast cancelled."
        )

        return

    # --------------------------------------------------------
    # REMOVE PENDING STATE
    # --------------------------------------------------------

    broadcast_pending.discard(
        message.from_user.id
    )

    status_message = await message.reply_text(
        "📢 <b>Broadcast started...</b>",
        parse_mode="html"
    )

    sent = 0
    failed = 0
    total = 0

    cursor = users_collection.find({
        "blocked": {
            "$ne": True
        }
    })

    async for user_record in cursor:

        total += 1

        target_user_id = user_record.get(
            "user_id"
        )

        if not target_user_id:
            continue

        try:

            # copy_message allows text, photo, video,
            # document and other Telegram message types
            # to be broadcast without downloading files
            # through the bot.
            await client.copy_message(
                chat_id=target_user_id,
                from_chat_id=message.chat.id,
                message_id=message.id
            )

            sent += 1

            await asyncio.sleep(0.05)

        except Exception as e:

            failed += 1

            error_text = str(e).lower()

            if (
                "blocked" in error_text
                or "user is deactivated" in error_text
                or "peer id invalid" in error_text
            ):

                try:

                    await users_collection.update_one(
                        {
                            "user_id": target_user_id
                        },
                        {
                            "$set": {
                                "blocked": True
                            }
                        }
                    )

                except Exception:
                    pass

    try:

        await status_message.edit_text(
            (
                "📢 <b>Broadcast Completed!</b>\n\n"
                f"👥 Total users: <b>{total}</b>\n"
                f"✅ Sent: <b>{sent}</b>\n"
                f"❌ Failed: <b>{failed}</b>"
            ),
            parse_mode="html"
        )

    except Exception:
        pass


# ============================================================
# 10. SMART MOVIE SEARCH
# ============================================================

@app.on_message(
    filters.private
    & filters.text
    & ~filters.command("start")
    & ~filters.command("index")
    & ~filters.command("stats")
    & ~filters.command("broadcast")
    & ~filters.command("cancel")
)
async def search_movie(
    client,
    message: Message
):

    # Automatically save/update user.
    await track_user(
        message.from_user
    )

    user_id = message.from_user.id

    # --------------------------------------------------------
    # FORCE SUBSCRIBE CHECK
    # --------------------------------------------------------

    if CHANNEL_USERNAME:

        if not await is_subscribed(
            client,
            user_id
        ):

            await message.reply_text(
                (
                    f"⚠️ You must join "
                    f"@{html.escape(CHANNEL_USERNAME)} "
                    f"to search movies."
                ),
                parse_mode="html"
            )

            return

    # --------------------------------------------------------
    # QUERY
    # --------------------------------------------------------

    query = message.text.strip()

    if not query:
        return

    if len(query) < 2:

        await message.reply_text(
            "❌ Please enter at least 2 characters."
        )

        return

    normalized_query = normalize_text(
        query
    )

    tokens = get_search_tokens(
        query
    )

    if not normalized_query:

        await message.reply_text(
            "❌ Please enter a valid movie name."
        )

        return

    results = []

    # --------------------------------------------------------
    # SEARCH 1:
    # NORMALIZED search_name
    #
    # Hanuman Ansh
    # Hanuman-Ansh
    # Hanuman_Ansh
    # Hanuman.Ansh
    #
    # all become:
    #
    # hanumanansh
    # --------------------------------------------------------

    try:

        cursor = collection.find({
            "search_name": {
                "$regex": re.escape(
                    normalized_query
                ),
                "$options": "i"
            }
        }).limit(
            MAX_SEARCH_RESULTS
        )

        results = await cursor.to_list(
            length=MAX_SEARCH_RESULTS
        )

    except Exception as e:

        print(
            f"Normalized search error: {e}"
        )

    # --------------------------------------------------------
    # SEARCH 2:
    # TOKEN SEARCH
    #
    # Useful when words are separated by extra
    # filename information.
    #
    # Example:
    #
    # Hanuman 2025
    #
    # can match:
    #
    # Hanuman.Ansh.2025.1080p...
    # --------------------------------------------------------

    if not results and tokens:

        try:

            conditions = []

            for token in tokens:

                conditions.append({
                    "file_name": {
                        "$regex": re.escape(token),
                        "$options": "i"
                    }
                })

            cursor = collection.find({
                "$and": conditions
            }).limit(
                MAX_SEARCH_RESULTS
            )

            results = await cursor.to_list(
                length=MAX_SEARCH_RESULTS
            )

        except Exception as e:

            print(
                f"Token search error: {e}"
            )

    # --------------------------------------------------------
    # SEARCH 3:
    # OLD RECORD FALLBACK
    # --------------------------------------------------------

    if not results:

        try:

            cursor = collection.find({
                "file_name": {
                    "$regex": re.escape(
                        normalized_query
                    ),
                    "$options": "i"
                }
            }).limit(
                MAX_SEARCH_RESULTS
            )

            results = await cursor.to_list(
                length=MAX_SEARCH_RESULTS
            )

        except Exception as e:

            print(
                f"Fallback search error: {e}"
            )

    # --------------------------------------------------------
    # NO RESULTS
    # --------------------------------------------------------

    if not results:

        safe_query = html.escape(
            query
        )

        await message.reply_text(
            (
                f"❌ <b>No movies found for "
                f"'{safe_query}'!</b>\n\n"
                f"Please check the spelling and try again."
            ),
            parse_mode="html"
        )

        return

    # --------------------------------------------------------
    # REMOVE DUPLICATES
    # --------------------------------------------------------

    unique_results = []

    seen_message_ids = set()

    for result in results:

        message_id = result.get(
            "message_id"
        )

        if not message_id:
            continue

        if message_id in seen_message_ids:
            continue

        seen_message_ids.add(
            message_id
        )

        unique_results.append({
            "file_name": result.get(
                "file_name",
                "Unknown File"
            ),
            "message_id": message_id,
            "file_size": result.get(
                "file_size",
                0
            )
        })

    results = unique_results

    if not results:

        await message.reply_text(
            "❌ No valid files found."
        )

        return

    # --------------------------------------------------------
    # CREATE SEARCH SESSION
    # --------------------------------------------------------

    session_id = uuid.uuid4().hex[:12]

    await search_sessions.insert_one({
        "_id": session_id,
        "user_id": user_id,
        "query": query,
        "results": results,
        "created_at": datetime.utcnow()
    })

    # --------------------------------------------------------
    # PAGINATION
    # --------------------------------------------------------

    total_pages = (
        len(results)
        + RESULTS_PER_PAGE
        - 1
    ) // RESULTS_PER_PAGE

    keyboard = build_results_keyboard(
        results,
        0,
        total_pages,
        session_id
    )

    # --------------------------------------------------------
    # SEARCH RESULT MESSAGE
    # --------------------------------------------------------

    safe_user_name = html.escape(
        message.from_user.first_name
        or "Buddy"
    )

    safe_query = html.escape(
        query
    )

    result_text = (
        f"Hey {safe_user_name} 👋\n\n"
        f"⭕Rotate your 🔄 phone to see files' "
        f"full name...........................⭕\n\n"
        f"<i>Title : {safe_query}</i>\n\n"
        f"<i>Your Files is Ready Now</i>"
    )

    results_message = await message.reply_text(
        result_text,
        reply_markup=keyboard,
        parse_mode="html"
    )

    # --------------------------------------------------------
    # SEARCH RESULTS AUTO DELETE
    # --------------------------------------------------------

    async def delete_search_results():

        await asyncio.sleep(
            AUTO_DELETE_TIME
        )

        try:

            await results_message.delete()

        except Exception:
            pass

        try:

            await search_sessions.delete_one({
                "_id": session_id
            })

        except Exception:
            pass

    asyncio.create_task(
        delete_search_results()
    )


# ============================================================
# START BOT
# ============================================================

if __name__ == "__main__":
    app.run()
