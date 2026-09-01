import re
from datetime import datetime

from motor.motor_asyncio import AsyncIOMotorClient

from config import DATABASE_URI


# ============================================================
# MONGODB SETUP
# ============================================================

db_client = AsyncIOMotorClient(DATABASE_URI)

db = db_client["ScreenEmpireDB"]

collection = db["movies"]

users_collection = db["users"]

search_sessions = db["search_sessions"]


# ============================================================
# TEXT / FILE HELPERS
# ============================================================

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
