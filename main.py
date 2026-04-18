import os
import asyncio
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.error import TelegramError

# ─── LOGGING ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── CONFIG ──────────────────────────────────────────────────────────────────
# Environment variables ko safely load karna
BOT_TOKEN   = os.environ.get("BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
PORT        = int(os.environ.get("PORT", 8443))
PING_PORT   = 8080
PING_INTERVAL = 14 * 60 

def load_channels() -> list[dict]:
    raw = os.environ.get("CHANNELS", "")
    if not raw:
        logger.error("ERROR: CHANNELS environment variable missing hai!")
        return []
    
    channels = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split("|")
        if len(parts) != 3:
            logger.warning(f"Invalid format skipped: '{entry}' (Format '@id|link|name' hona chahiye)")
            continue
        username, link, name = [p.strip() for p in parts]
        channels.append({"username": username, "link": link, "name": name})
    
    return channels

CHANNELS = load_channels()

# ─── SELF PING (RENDER NO-SLEEP) ─────────────────────────────────────────────
class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is Active")

    def log_message(self, format, *args):
        pass 

def start_health_server():
    try:
        server = HTTPServer(("0.0.0.0", PING_PORT), PingHandler)
        logger.info(f"Health server started on port {PING_PORT}")
        server.serve_forever()
    except Exception as e:
        logger.error(f"Health server failed: {e}")

def self_ping_loop():
    # Render ko jagaaye rakhne ke liye external URL ping karna behtar hai
    url = WEBHOOK_URL if WEBHOOK_URL else f"http://localhost:{PING_PORT}"
    time.sleep(20) # Startup delay
    while True:
        try:
            r = requests.get(url, timeout=10)
            logger.info(f"Self-ping sent to {url} - Status: {r.status_code}")
        except Exception as e:
            logger.warning(f"Self-ping failed: {e}")
        time.sleep(PING_INTERVAL)

def start_pinger():
    threading.Thread(target=start_health_server, daemon=True).start()
    threading.Thread(target=self_ping_loop, daemon=True).start()

# ─── SUBSCRIPTION CHECK ──────────────────────────────────────────────────────
async def get_unjoined(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> list:
    unjoined = []
    for ch in CHANNELS:
        try:
            member = await context.bot.get_chat_member(ch["username"], user_id)
            if member.status not in ("member", "administrator", "creator"):
                unjoined.append(ch)
        except Exception as e:
            logger.error(f"Membership check failed for {ch['username']}: {e}")
            unjoined.append(ch)
    return unjoined

def join_keyboard(unjoined: list) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(f"📢 Join {ch['name']}", url=ch["link"])] for ch in unjoined]
    buttons.append([InlineKeyboardButton("✅ Verify Karo", callback_data="verify")])
    return InlineKeyboardMarkup(buttons)

async def gate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not CHANNELS:
        return True # Agar channel setup nahi hai toh bot chalne do
    
    unjoined = await get_unjoined(update.effective_user.id, context)
    if unjoined:
        ch_list = "\n".join([f"• {ch['name']}" for ch in unjoined])
        text = f"❌ **Access Denied!**\n\nAapne hamare channels join nahi kiye hain:\n{ch_list}\n\nNiche diye buttons se join karein aur Verify dabayein."
        if update.callback_query:
            await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=join_keyboard(unjoined))
        else:
            await update.effective_message.reply_text(text, parse_mode="Markdown", reply_markup=join_keyboard(unjoined))
        return False
    return True

# ─── HANDLERS ────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await gate(update, context):
        await update.message.reply_text(f"👋 Welcome {update.effective_user.first_name}!\n\nBot ab aapke liye active hai.")

async def verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if await gate(update, context):
        await query.edit_message_text("✅ Verification Successful! Ab aap bot use kar sakte hain.")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await gate(update, context):
        await update.message.reply_text(f"Aapne kaha: {update.message.text}")

# ─── MAIN ────────────────────────────────────────────────────────────────────
def main():
    if not BOT_TOKEN or not WEBHOOK_URL:
        logger.critical("FATAL ERROR: BOT_TOKEN ya WEBHOOK_URL missing hai!")
        return

    start_pinger()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(verify_callback, pattern="^verify$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    logger.info("Bot is starting...")
    
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=f"{WEBHOOK_URL}/webhook",
        url_path="webhook",
    )

if __name__ == "__main__":
    main()
