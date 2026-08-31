import os
import asyncio
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from pyrogram.errors import UserNotParticipant

API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "ScreenEmpire")
DB_CHANNEL = int(os.environ.get("DB_CHANNEL", 0))
AUTO_DELETE_TIME = int(os.environ.get("AUTO_DELETE_TIME", 300))

app = Client(
    "ScreenEmpireBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

async def is_subscribed(client, user_id):
    try:
        await client.get_chat_member(CHANNEL_USERNAME, user_id)
        return True
    except UserNotParticipant:
        return False
    except Exception:
        return True

@app.on_message(filters.command("start"))
async def start_command(client, message: Message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "Buddy"
    
    # Force Subscribe Check
    if CHANNEL_USERNAME:
        not_joined = not await is_subscribed(client, user_id)
        if not_joined:
            btn = InlineKeyboardMarkup([
                [InlineKeyboardButton("📢 Join ScreenEmpire", url=f"https://t.me/{CHANNEL_USERNAME}")],
                [InlineKeyboardButton("🔄 Try Again", callback_data="check_sub")]
            ])
            await message.reply_text(
                f"Hey 👋 {user_name} 🤩\n\n"
                f"⚠️ **Access Restricted!**\n"
                f"To access the world's coolest movie database, you must join our official channel first.",
                reply_markup=btn
            )
            return

    # Deep-linking / File Forwarding Logic
    if len(message.command) > 1:
        try:
            file_id = int(message.command[1])
            msg = await client.get_messages(DB_CHANNEL, file_id)
            if msg:
                sent_msg = await msg.copy(
                    chat_id=message.chat.id,
                    caption=f"🎬 **Here is your file!**\n\n🍿 Powered by **ScreenEmpire**"
                )
                
                minutes = AUTO_DELETE_TIME // 60
                warning_text = await message.reply_text(
                    f"⏱️ **Auto-Delete Notice:**\n"
                    f"This file will auto-delete in **{minutes} minutes**. Please save or forward it immediately!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚡ Join Main Channel", url=f"https://t.me/{CHANNEL_USERNAME}")]])
                )
                
                async def delete_after_delay():
                    await asyncio.sleep(AUTO_DELETE_TIME)
                    try:
                        await sent_msg.delete()
                        await warning_text.delete()
                    except Exception:
                        pass
                
                asyncio.create_task(delete_after_delay())
                return
        except Exception:
            await message.reply_text("❌ **Error:** File not found or invalid link!")
            return

    # Professional Home Menu (Inspired by the reference image)
    home_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔎 SEARCH MOVIES OR SERIES 🔎", url=f"https://t.me/{CHANNEL_USERNAME}")],
        [InlineKeyboardButton("📤 SHARE NOW 📤", url=f"https://t.me/share/url?url=https://t.me/ScreenEmpireBot&text=Join%20ScreenEmpire%20for%20the%20latest%20Movies%20and%20Web%20Series!")]
    ])
    
    await message.reply_text(
        f"Hey 👋 **{user_name}** 🤩\n\n"
        f"🍿 **WELCOME TO THE WORLD'S COOLEST MOVIE HUB!**\n\n"
        f"Here You Can Request Movies & Web Series. Just click the links provided in our main channel to get your files instantly..!!",
        reply_markup=home_keyboard
    )

app.run()
