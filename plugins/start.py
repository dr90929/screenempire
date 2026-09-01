import asyncio
import html
from datetime import date

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from pyrogram.errors import UserNotParticipant

from config import (
    AUTO_DELETE_TIME,
    CHANNEL_USERNAME,
    DB_CHANNEL,
    START_FSUB_PROMOTIONS,
)
from database import (
    track_user,
    get_file_from_message,
    get_file_name_from_message,
)

# ============================================================
# START FSub PROMOTION HELPERS
# ============================================================

def get_active_start_promotions():
    """
    Returns only currently active START promotions.

    A promotion is active when:
    - enabled = True
    - current date >= start_date
    - current date <= end_date

    After end_date, the promotion is automatically ignored.
    """

    active_promotions = []

    today = date.today()

    for promotion in START_FSUB_PROMOTIONS:

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
                f"Invalid START promotion configuration: {e}"
            )

    return active_promotions


async def is_channel_subscribed(
    client,
    channel,
    user_id
):
    """
    Checks whether the user is a member of one channel.
    """

    try:

        await client.get_chat_member(
            channel,
            user_id
        )

        return True

    except UserNotParticipant:

        return False

    except Exception as e:

        print(
            f"FSub check error for {channel}: {e}"
        )

        # Preserve the existing behavior:
        # temporary Telegram/API errors should not
        # unexpectedly block the user.
        return True


async def get_missing_start_channels(
    client,
    user_id
):
    """
    Checks:

    1. Permanent ScreenEmpire main channel.
    2. Currently active paid START promotions.

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
    # ACTIVE PAID START PROMOTIONS
    # --------------------------------------------------------

    for promotion in get_active_start_promotions():

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


def build_fsub_keyboard(
    missing_channels,
    callback_data="check_sub"
):
    """
    Builds Join buttons for all missing channels
    plus the existing Try Again button.
    """

    buttons = []

    for channel in missing_channels:

        channel_name = channel.get(
            "name",
            "Join Channel"
        )

        channel_url = channel.get(
            "url",
            ""
        )

        if not channel_url:
            continue

        buttons.append([
            InlineKeyboardButton(
                f"📢 Join {channel_name}",
                url=channel_url
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "🔄 Try Again",
            callback_data=callback_data
        )
    ])

    return InlineKeyboardMarkup(
        buttons
    )


# ============================================================
# FORCE SUBSCRIPTION
# ============================================================

async def is_subscribed(client, user_id):
    """
    Existing compatibility wrapper.

    For /start this checks:
    - Permanent ScreenEmpire channel
    - Active paid START promotions
    """

    missing_channels = await get_missing_start_channels(
        client,
        user_id
    )

    return not missing_channels


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
            parse_mode=ParseMode.HTML
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
            parse_mode=ParseMode.HTML,
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
# 2. START COMMAND
# ============================================================

@Client.on_message(
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
    # MULTI-CHANNEL START FSub
    #
    # Permanent:
    #   ScreenEmpire
    #
    # Temporary:
    #   Active START paid promotions
    # --------------------------------------------------------

    missing_channels = await get_missing_start_channels(
        client,
        user_id
    )

    if missing_channels:

        btn = build_fsub_keyboard(
            missing_channels,
            "check_sub"
        )

        if len(missing_channels) == 1:

            instruction = (
                "Please join the required channel below "
                "to continue."
            )

        else:

            instruction = (
                "Please join all required channels below "
                "to continue."
            )

        await message.reply_text(
            (
                f"Hey 👋 <b>{html.escape(user_name)}</b> 🤩\n\n"
                f"⚠️ <b>Access Restricted!</b>\n"
                f"To access the world's coolest movie "
                f"database, you must join the required "
                f"channel(s) first.\n\n"
                f"{instruction}"
            ),
            reply_markup=btn,
            parse_mode=ParseMode.HTML
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
                parse_mode=ParseMode.HTML
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
        parse_mode=ParseMode.HTML
    )


# ============================================================
# 3. TRY AGAIN BUTTON
# ============================================================

@Client.on_callback_query(
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

    missing_channels = await get_missing_start_channels(
        client,
        user_id
    )

    if missing_channels:

        btn = build_fsub_keyboard(
            missing_channels,
            "check_sub"
        )

        await callback_query.answer(
            "❌ You still need to join the required channel(s).",
            show_alert=True
        )

        try:

            await callback_query.message.edit_reply_markup(
                reply_markup=btn
            )

        except Exception:
            pass

        return

    await callback_query.answer(
        "✅ All required channels verified!",
        show_alert=True
    )

    await callback_query.message.edit_text(
        (
            "✅ <b>Verified successfully!</b>\n\n"
            "Now send me the movie or series name "
            "you want to search. 🍿"
        ),
        parse_mode=ParseMode.HTML
    )
