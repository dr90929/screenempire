import asyncio
import html
import re
import uuid
from datetime import datetime, date

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import Message

from config import (
    CHANNEL_USERNAME,
    AUTO_DELETE_TIME,
    MAX_SEARCH_RESULTS,
    RESULTS_PER_PAGE,
    SEARCH_FSUB_PROMOTIONS,
)
from database import (
    collection,
    search_sessions,
    track_user,
    normalize_text,
    get_search_tokens,
)
from plugins.start import (
    is_channel_subscribed,
    build_fsub_keyboard,
)
from plugins.callbacks import build_results_keyboard


# ============================================================
# SEARCH FSub PROMOTION HELPERS
# ============================================================

def get_active_search_promotions():
    """
    Returns only currently active SEARCH promotions.

    A promotion is active when:
    - enabled = True
    - current date >= start_date
    - current date <= end_date

    After end_date, the promotion is automatically ignored.
    """

    active_promotions = []

    today = date.today()

    for promotion in SEARCH_FSUB_PROMOTIONS:

        try:

            if not promotion.get(
                "enabled",
                True
            ):
                continue

            start_date = date.fromisoformat(
                promotion["start_date"]
            )

            end_date = date.fromisoformat(
                promotion["end_date"]
            )

            if (
                start_date
                <= today
                <= end_date
            ):

                active_promotions.append(
                    promotion
                )

        except Exception as e:

            print(
                f"Invalid SEARCH promotion configuration: {e}"
            )

    return active_promotions


async def get_missing_search_channels(
    client,
    user_id
):
    """
    Checks:

    1. Permanent ScreenEmpire main channel.
    2. Currently active paid SEARCH promotions.

    Returns only channels that the user has not joined.
    """

    missing_channels = []

    # --------------------------------------------------------
    # PERMANENT MAIN SCREENEMPIRE CHANNEL
    # --------------------------------------------------------

    if CHANNEL_USERNAME:

        subscribed = await is_channel_subscribed(
            client,
            CHANNEL_USERNAME,
            user_id
        )

        if not subscribed:

            missing_channels.append({
                "name": "ScreenEmpire",
                "url": f"https://t.me/{CHANNEL_USERNAME}"
            })

    # --------------------------------------------------------
    # ACTIVE PAID SEARCH PROMOTIONS
    # --------------------------------------------------------

    for promotion in get_active_search_promotions():

        chat_id = promotion.get(
            "chat_id"
        )

        if not chat_id:
            continue

        subscribed = await is_channel_subscribed(
            client,
            chat_id,
            user_id
        )

        if not subscribed:

            missing_channels.append({
                "name": promotion.get(
                    "name",
                    "Required Channel"
                ),
                "url": promotion.get(
                    "url",
                    ""
                )
            })

    return missing_channels


# ============================================================
# 10. SMART MOVIE SEARCH
# ============================================================

@Client.on_message(
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
    # MULTI-CHANNEL SEARCH FSub
    #
    # Permanent:
    #   ScreenEmpire
    #
    # Temporary:
    #   Active SEARCH paid promotions
    # --------------------------------------------------------

    missing_channels = await get_missing_search_channels(
        client,
        user_id
    )

    if missing_channels:

        keyboard = build_fsub_keyboard(
            missing_channels,
            "check_search_sub"
        )

        if len(missing_channels) == 1:

            instruction = (
                "Please join the required channel below "
                "to search movies."
            )

        else:

            instruction = (
                "Please join all required channels below "
                "to search movies."
            )

        await message.reply_text(
            (
                f"⚠️ <b>Access Restricted!</b>\n\n"
                f"{instruction}"
            ),
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
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
            parse_mode=ParseMode.HTML
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
        parse_mode=ParseMode.HTML
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
# SEARCH FSub TRY AGAIN
# ============================================================

@Client.on_callback_query(
    filters.regex("^check_search_sub$")
)
async def check_search_subscription_callback(
    client,
    callback_query
):

    await track_user(
        callback_query.from_user
    )

    user_id = callback_query.from_user.id

    missing_channels = await get_missing_search_channels(
        client,
        user_id
    )

    if missing_channels:

        keyboard = build_fsub_keyboard(
            missing_channels,
            "check_search_sub"
        )

        await callback_query.answer(
            "❌ You still need to join the required channel(s).",
            show_alert=True
        )

        try:

            await callback_query.message.edit_reply_markup(
                reply_markup=keyboard
            )

        except Exception:
            pass

        return

    await callback_query.answer(
        "✅ All required channels verified!",
        show_alert=True
    )

    try:

        await callback_query.message.edit_text(
            (
                "✅ <b>Verified successfully!</b>\n\n"
                "Now send the movie or series name "
                "you want to search. 🍿"
            ),
            parse_mode=ParseMode.HTML
        )

    except Exception:
        pass
