import asyncio
import html

from pyrogram import Client, filters, ContinuePropagation
from pyrogram.enums import ParseMode
from pyrogram.types import Message

from config import ADMIN_ID, DB_CHANNEL
from database import (
    collection,
    users_collection,
    search_sessions,
    save_file_to_database,
    track_user,
)

# Temporary in-memory state for admin broadcast.
# It is only used while the bot process is running.
broadcast_pending = set()


# ============================================================
# 6. ADMIN /INDEX COMMAND
# ============================================================

@Client.on_message(
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
        parse_mode=ParseMode.HTML
    )

    scanned = 0
    saved = 0
    updated = 0
    skipped = 0
    errors = 0
    deleted_from_db = 0

    try:

        # ----------------------------------------------------
        # BOT-COMPATIBLE INDEXING
        #
        # Telegram's getHistory method is user-only.
        # Therefore we first send a temporary message to
        # the DB channel to obtain its latest message ID.
        #
        # Then we fetch old messages directly by their IDs.
        # Pyrogram get_messages() supports bots and up to
        # 200 message IDs in one request.
        # ----------------------------------------------------

        try:

            await client.get_chat(
                DB_CHANNEL
            )

        except Exception as e:

            await progress_message.edit_text(
                (
                    "❌ <b>DB Channel access failed!</b>\n\n"
                    f"<code>{html.escape(str(e))}</code>\n\n"
                    "Please make sure the bot is an administrator "
                    "in the private DB channel and that DB_CHANNEL "
                    "is correct."
                ),
                parse_mode=ParseMode.HTML
            )

            return

        # ----------------------------------------------------
        # TEMPORARY MESSAGE
        # ----------------------------------------------------

        temp_msg = await client.send_message(
            DB_CHANNEL,
            "⏳ Indexing started..."
        )

        highest_id = temp_msg.id

        # Delete temporary message immediately.
        try:

            await temp_msg.delete()

        except Exception:
            pass

        # ----------------------------------------------------
        # FETCH OLD MESSAGES BY ID
        # ----------------------------------------------------

        batch_size = 200

        # Start below the temporary message because that
        # message is not part of the actual movie database.
        current_id = highest_id - 1

        while current_id > 0:

            start_id = current_id

            end_id = max(
                1,
                start_id - batch_size + 1
            )

            message_ids = list(
                range(
                    start_id,
                    end_id - 1,
                    -1
                )
            )

            try:

                channel_messages = await client.get_messages(
                    DB_CHANNEL,
                    message_ids
                )

            except Exception as e:

                errors += len(
                    message_ids
                )

                print(
                    f"Error fetching ID batch "
                    f"{start_id}-{end_id}: {e}"
                )

                # Move to the next batch.
                current_id = end_id - 1

                await asyncio.sleep(1)

                continue

            # ------------------------------------------------
            # PROCESS BATCH + GHOST FILE CLEANUP
            # ------------------------------------------------

            for channel_message in channel_messages:

                scanned += 1

                try:

                    # Deleted/non-existing message IDs can
                    # return empty message objects.
                    if (
                        not channel_message
                        or getattr(
                            channel_message,
                            "empty",
                            False
                        )
                    ):

                        skipped += 1
                        continue

                    message_id = getattr(
                        channel_message,
                        "id",
                        None
                    )

                    if not message_id:
                        skipped += 1
                        continue

                    # If the Telegram message still exists but
                    # is no longer a file, remove any stale
                    # database record for that message.
                    if not (
                        channel_message.document
                        or channel_message.video
                    ):

                        cleanup_result = await collection.delete_one({
                            "message_id": message_id
                        })

                        if cleanup_result.deleted_count > 0:
                            deleted_from_db += 1
                        else:
                            skipped += 1

                        continue

                    existing = await collection.find_one({
                        "message_id": message_id
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
                        f"{getattr(channel_message, 'id', 'unknown')}: {e}"
                    )

            # ------------------------------------------------
            # CLEANUP DELETED/GAP MESSAGE IDS
            #
            # Any requested ID that was not returned as a
            # non-empty Telegram message no longer exists in
            # the channel. Remove its stale MongoDB index.
            # ------------------------------------------------

            returned_ids = {
                getattr(
                    channel_message,
                    "id",
                    None
                )
                for channel_message in channel_messages
                if (
                    channel_message
                    and not getattr(
                        channel_message,
                        "empty",
                        False
                    )
                    and getattr(
                        channel_message,
                        "id",
                        None
                    )
                )
            }

            missing_ids = set(
                message_ids
            ) - returned_ids

            if missing_ids:

                try:

                    cleanup_result = await collection.delete_many({
                        "message_id": {
                            "$in": list(missing_ids)
                        }
                    })

                    deleted_from_db += (
                        cleanup_result.deleted_count
                    )

                except Exception as e:

                    errors += 1

                    print(
                        f"Ghost cleanup error for batch "
                        f"{start_id}-{end_id}: {e}"
                    )

            # ------------------------------------------------
            # PROGRESS
            # ------------------------------------------------

            try:

                await progress_message.edit_text(
                    (
                        f"🔄 <b>Indexing DB Channel...</b>\n\n"
                        f"📥 Scanned: <b>{scanned}</b>\n"
                        f"💾 New files: <b>{saved}</b>\n"
                        f"🔄 Updated: <b>{updated}</b>\n"
                        f"🗑️ Cleaned from DB: <b>{deleted_from_db}</b>\n"
                        f"⏭️ Skipped/Empty: <b>{skipped}</b>\n"
                        f"❌ Errors: <b>{errors}</b>"
                    ),
                    parse_mode=ParseMode.HTML
                )

            except Exception:
                pass

            # Move to next older batch.
            current_id = end_id - 1

            # Small delay to reduce Telegram rate-limit risk.
            await asyncio.sleep(1)

        # ----------------------------------------------------
        # COMPLETE
        # ----------------------------------------------------

        await progress_message.edit_text(
            (
                f"✅ <b>Indexing Completed!</b>\n\n"
                f"📥 Total IDs scanned: <b>{scanned}</b>\n"
                f"💾 New files indexed: <b>{saved}</b>\n"
                f"🔄 Existing records updated: <b>{updated}</b>\n"
                f"🗑️ Cleaned from DB: <b>{deleted_from_db}</b>\n"
                f"⏭️ Non-file/empty messages: <b>{skipped}</b>\n"
                f"❌ Errors: <b>{errors}</b>"
            ),
            parse_mode=ParseMode.HTML
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
                parse_mode=ParseMode.HTML
            )

        except Exception:
            pass



# ============================================================
# 7. ADMIN /STATS COMMAND
# ============================================================

@Client.on_message(
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
            parse_mode=ParseMode.HTML
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

@Client.on_message(
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
            parse_mode=ParseMode.HTML
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
                parse_mode=ParseMode.HTML
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
        parse_mode=ParseMode.HTML
    )



# ============================================================
# 9. ADMIN BROADCAST MESSAGE CAPTURE
# ============================================================

@Client.on_message(
    filters.private
)
async def broadcast_message_capture(
    client,
    message: Message
):

    # Only process users who explicitly entered
    # broadcast mode.
    if message.from_user.id not in broadcast_pending:
        raise ContinuePropagation

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
        parse_mode=ParseMode.HTML
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
            parse_mode=ParseMode.HTML
        )

    except Exception:
        pass

