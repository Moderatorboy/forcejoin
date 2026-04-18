import os
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

# ─── LOGGING ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── CONFIG ──────────────────────────────────────────────────────────────────
BOT_TOKEN   = os.environ.get("BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
OWNER_ID    = os.environ.get("OWNER_ID") # Render pe aapki ID
PORT        = int(os.environ.get("PORT", 8443))
PING_PORT   = 8080
PING_INTERVAL = 14 * 60 

def load_channels() -> list[dict]:
    raw = os.environ.get("CHANNELS", "")
    channels = []
    if not raw:
        return channels
    
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry: continue
        parts = entry.split("|")
        if len(parts) == 3:
            channels.append({
                "username": parts[0].strip(),
                "link": parts[1].strip(),
                "name": parts[2].strip()
            })
    return channels

CHANNELS = load_channels()

# ─── SELF PING (RENDER NO-SLEEP) ─────────────────────────────────────────────
class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is Live")
    def log_message(self, format, *args): pass

def start_health_server():
    server = HTTPServer(("0.0.0.0", PING_PORT), PingHandler)
    server.serve_forever()

def self_ping_loop():
    time.sleep(20)
    while True:
        try:
            requests.get(WEBHOOK_URL, timeout=10)
        except: pass
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
        except:
            unjoined.append(ch)
    return unjoined

async def gate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    unjoined = await get_unjoined(update.effective_user.id, context)
    if unjoined:
        buttons = [[InlineKeyboardButton(f"📢 Join {ch['name']}", url=ch["link"])] for ch in unjoined]
        buttons.append([InlineKeyboardButton("✅ Verify Karo", callback_data="verify")])
        text = "❌ **Access Denied!**\n\nBot use karne ke liye hamare channels join karein."
        
        if update.callback_query:
            await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await update.effective_message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))
        return False
    return True

# ─── HANDLERS ────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await gate(update, context):
        await update.message.reply_text(f"👋 Welcome {update.effective_user.first_name}!\nAap bot ko message bhej sakte hain.")

async def verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if await gate(update, context):
        await query.edit_message_text("✅ Verification Successful! Ab aap message bhej sakte hain.")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await gate(update, context):
        # Forward message to Owner
        if OWNER_ID:
            try:
                await update.message.forward(chat_id=OWNER_ID)
                await update.message.reply_text("✅ Aapka message owner ko forward kar diya gaya hai.")
            except Exception as e:
                logger.error(f"Forward error: {e}")
                await update.message.reply_text("❌ Message bhejte waqt kuch galti hui.")

# ─── MAIN ────────────────────────────────────────────────────────────────────
def main():
    start_pinger()
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(verify_callback, pattern="^verify$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    app.run_webhook(
        listen="0.0.0.0", port=PORT,
        webhook_url=f"{WEBHOOK_URL}/webhook", url_path="webhook"
    )

if __name__ == "__main__":
    main()
