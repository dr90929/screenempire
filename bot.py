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
    user_name = message.from_user.first_name or "Movie Lover"
    
    # Force Subscribe Check
    if CHANNEL_USERNAME:
        not_joined = not await is_subscribed(client, user_id)
        if not_joined:
            btn = InlineKeyboardMarkup([
                [InlineKeyboardButton("📢 Join ScreenEmpire Channel", url=f"https://t.me/{CHANNEL_USERNAME}")],
                [InlineKeyboardButton("🔄 I Have Joined (Try Again)", callback_data="check_sub")]
            ])
            await message.reply_text(
                f"👋 Hello **{user_name}**!\n\n"
                f"⚠️ **Access Denied!**\n"
                f"To use this bot and watch movies, you must join our official channel first.\n\n"
                f"*(Pehle hamara channel join karein, tabhi movies access milengi!)*",
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
                    caption=f"🎬 **Here is your file!**\n\n⚡ Powered by **ScreenEmpire**"
                )
                
                minutes = AUTO_DELETE_TIME // 60
                warning_text = await message.reply_text(
                    f"⏱️ **Auto-Delete Notice:**\n"
                    f"Yeh media agle **{minutes} minutes** mein apne aap delete ho jayegi. Kripya ise turant save ya forward kar lein!\n\n"
                    f"*(This file will auto-delete in {minutes} mins to avoid copyright issues.)*"
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
            await message.reply_text("❌ **Error:** Invalid link ya file nahi mili! Please correct link use karein.")
            return

    # Professional Home Menu
    home_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Join Main Channel", url=f"https://t.me/{CHANNEL_USERNAME}")],
        [InlineKeyboardButton("⚡ Request Movie", url=f"https://t.me/{CHANNEL_USERNAME}")]
    ])
    
    await message.reply_text(
        f"✨ **Welcome to ScreenEmpire, {user_name}!** ✨\n\n"
        f"Aapka apna ultimate destination movies aur web series ke liye. Yahan aapko sab kuch milega ek hi jagah par!\n\n"
        f"📌 **How to use:**\n"
        f"1. Channel par di gayi movie link par click karein.\n"
        f"2. Bot aapko yahan movie bhej dega.\n"
        f"3. Fast download karein kyunki files auto-delete hoti hain!\n\n"
        f"👇 Neeche diye gaye button se hamare main channel se jude rahein.",
        reply_markup=home_keyboard
    )

app.run()
