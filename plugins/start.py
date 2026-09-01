import asyncio
import html

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from pyrogram.errors import UserNotParticipant

from config import AUTO_DELETE_TIME, CHANNEL_USERNAME, DB_CHANNEL
from database import track_user, get_file_from_message

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
        parse_mode=ParseMode.HTML
    )


