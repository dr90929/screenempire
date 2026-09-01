import asyncio
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import RESULTS_PER_PAGE
from database import search_sessions, format_file_size
from plugins.start import is_subscribed, track_user, send_requested_file


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
# 4. PAGINATION CALLBACK
# ============================================================

@Client.on_callback_query(
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

@Client.on_callback_query(
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


