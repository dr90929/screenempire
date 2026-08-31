import os
import asyncio
import re

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

# --- DUMMY WEB SERVER FOR RENDER ---
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "ScreenEmpire Bot is Running Alive!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_web, daemon=True).start()
# ------------------------------------

# --- ENVIRONMENT VARIABLES ---
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "ScreenEmpire")
DB_CHANNEL = int(os.environ.get("DB_CHANNEL", 0))
AUTO_DELETE_TIME = int(os.environ.get("AUTO_DELETE_TIME", 60))
DATABASE_URI = os.environ.get("DATABASE_URI", "")

# --- MONGODB SETUP ---
db_client = AsyncIOMotorClient(DATABASE_URI)
db = db_client["ScreenEmpireDB"]
collection = db["movies"]

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

# 1. AUTO-SAVE FEATURE (Saves files forwarded to DB_CHANNEL)
@app.on_message(filters.chat(DB_CHANNEL) & (filters.document | filters.video))
async def auto_save(client, message: Message):
    file = message.document or message.video
    file_name = file.file_name if file.file_name else "Unknown_File"
    
    await collection.insert_one({
        "file_name": file_name,
        "message_id": message.id
    })
    print(f"Saved to Database: {file_name}")

@app.on_message(filters.command("start") & filters.private)
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
                time_label = f"{minutes} minute" if minutes > 0 else f"{AUTO_DELETE_TIME} seconds"
                warning_text = await message.reply_text(
                    f"⏱️ **Auto-Delete Notice:**\n"
                    f"This file will auto-delete in **{time_label}**. Please save or forward it immediately!",
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

    # Professional Home Menu 
    home_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔎 SEARCH MOVIES OR SERIES 🔎", url=f"https://t.me/{CHANNEL_USERNAME}")],
        [InlineKeyboardButton("📤 SHARE NOW 📤", url=f"https://t.me/share/url?url=https://t.me/ScreenEmpireBot&text=Join%20ScreenEmpire%20for%20the%20latest%20Movies%20and%20Web%20Series!")]
    ])
    
    await message.reply_text(
        f"Hey 👋 **{user_name}** 🤩\n\n"
        f"🍿 **WELCOME TO THE WORLD'S COOLEST MOVIE HUB!**\n\n"
        f"Here You Can Request Movies & Web Series. Just send the real Movie or Web Series name with proper English spelling to get your files instantly..!!",
        reply_markup=home_keyboard
    )

# 3. AUTO-FILTER TEXT SEARCH (Searches DB by movie name)
@app.on_message(filters.private & filters.text & ~filters.command("start"))
async def search_movie(client, message: Message):
    user_id = message.from_user.id
    
    # Force Subscribe Check for search
    if CHANNEL_USERNAME:
        if not await is_subscribed(client, user_id):
            await message.reply_text(f"⚠️ You must join @{CHANNEL_USERNAME} to search movies.")
            return

    query = message.text.strip()
    regex_query = re.compile(query, re.IGNORECASE) 
    
    # Database se match dhoondhna (Limit 3)
    cursor = collection.find({"file_name": regex_query}).limit(3)
    results = await cursor.to_list(length=3)
    
    if not results:
        await message.reply_text(f"❌ **No movies found for '{query}'!**\nPlease check the spelling and try again.")
        return
        
    for res in results:
        try:
            sent_msg = await client.copy_message(
                chat_id=message.chat.id,
                from_chat_id=DB_CHANNEL,
                message_id=res["message_id"],
                caption=f"🎬 **{res['file_name']}**\n\n🍿 Powered by **ScreenEmpire**"
            )
            
            minutes = AUTO_DELETE_TIME // 60
            time_label = f"{minutes} minute" if minutes > 0 else f"{AUTO_DELETE_TIME} seconds"
            warning_text = await message.reply_text(
                f"⏱️ **Auto-Delete Notice:**\nThis file will auto-delete in **{time_label}**. Save or forward it immediately!"
            )
            
            async def delete_after_delay(msg_to_del, warn_to_del):
                await asyncio.sleep(AUTO_DELETE_TIME)
                try:
                    await msg_to_del.delete()
                    await warn_to_del.delete()
                except: pass
                
            asyncio.create_task(delete_after_delay(sent_msg, warning_text))
        except Exception as e:
            print(f"File bhejte time error: {e}")

if __name__ == "__main__":
    app.run()
