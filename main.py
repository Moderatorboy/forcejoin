"""
Telegram Bot - Force Subscribe + Self Ping (No Sleep)
======================================================
Bot khud apne aap ko har 14 minute mein ping karta hai
taaki Render free plan pe sleep na ho.

Render Environment Variables:
  BOT_TOKEN    = your_bot_token
  WEBHOOK_URL  = https://yourapp.onrender.com
  CHANNELS     = @ch1|https://t.me/ch1|Channel 1,@ch2|https://t.me/ch2|Channel 2
"""

import os
import asyncio
import logging
import threading
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

BOT_TOKEN   = os.environ["BOT_TOKEN"]
WEBHOOK_URL = os.environ["WEBHOOK_URL"]   # e.g. https://yourapp.onrender.com
PORT        = int(os.environ.get("PORT", 8443))
PING_PORT   = 8080   # Health check server ka port
PING_INTERVAL = 14 * 60  # 14 minutes (Render 15 min pe sleep karta hai)

def load_channels() -> list[dict]:
    raw = os.environ.get("CHANNELS", "")
    channels = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split("|")
        if len(parts) != 3:
            logger.warning(f"Invalid channel entry (skip): '{entry}'")
            continue
        username, link, name = [p.strip() for p in parts]
        channels.append({"username": username, "link": link, "name": name})
    if not channels:
        raise ValueError("CHANNELS env variable set nahi hai ya format galat hai.")
    logger.info(f"{len(channels)} channel(s) loaded: {[c['username'] for c in channels]}")
    return channels

CHANNELS = load_channels()

# ─── SELF PING ────────────────────────────────────────────────────────────────

class PingHandler(BaseHTTPRequestHandler):
    """Simple HTTP server — Render aur self-pinger dono ke liye."""
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass  # HTTP logs suppress karo

def start_health_server():
    """Background mein ek simple HTTP server chalao."""
    server = HTTPServer(("0.0.0.0", PING_PORT), PingHandler)
    logger.info(f"Health server port {PING_PORT} pe start hua")
    server.serve_forever()

def self_ping_loop():
    """Har 14 minute mein apne aap ko ping karo."""
    ping_url = f"http://localhost:{PING_PORT}"
    while True:
        try:
            r = requests.get(ping_url, timeout=10)
            logger.info(f"Self ping OK ({r.status_code})")
        except Exception as e:
            logger.warning(f"Self ping failed: {e}")
        import time
        time.sleep(PING_INTERVAL)

def start_pinger():
    """Health server + pinger dono alag threads mein chalao."""
    threading.Thread(target=start_health_server, daemon=True).start()
    threading.Thread(target=self_ping_loop,      daemon=True).start()

# ─── SUBSCRIPTION CHECK ──────────────────────────────────────────────────────

async def get_unjoined(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> list:
    unjoined = []
    for ch in CHANNELS:
        try:
            member = await context.bot.get_chat_member(ch["username"], user_id)
            if member.status not in ("member", "administrator", "creator"):
                unjoined.append(ch)
        except TelegramError as e:
            logger.warning(f"{ch['username']} check failed: {e}")
            unjoined.append(ch)
    return unjoined

def join_keyboard(unjoined: list) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(f"📢 {ch['name']} Join Karo", url=ch["link"])]
        for ch in unjoined
    ]
    buttons.append(
        [InlineKeyboardButton("✅ Sab join kar liya — Verify karo", callback_data="verify")]
    )
    return InlineKeyboardMarkup(buttons)

async def prompt(update: Update, unjoined: list) -> None:
    total     = len(CHANNELS)
    remaining = len(unjoined)
    joined    = total - remaining
    ch_list   = "\n".join(f"  ❌  {ch['name']}  ({ch['username']})" for ch in unjoined)
    await update.effective_message.reply_text(
        f"🔒 *Access Restricted*\n\n"
        f"Progress: *{joined}/{total}* channels joined\n\n"
        f"Abhi bhi yeh join karne baaki hain:\n{ch_list}\n\n"
        "Sab join karne ke baad *Verify* button dabao.",
        parse_mode="Markdown",
        reply_markup=join_keyboard(unjoined),
    )

async def gate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    unjoined = await get_unjoined(update.effective_user.id, context)
    if unjoined:
        await prompt(update, unjoined)
        return False
    return True

# ─── HANDLERS ────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await gate(update, context):
        return
    user = update.effective_user
    await update.message.reply_text(
        f"👋 Welcome, {user.first_name}!\n\n"
        f"Aapne saare {len(CHANNELS)} channels join kar liye hain.\n"
        "Ab bot ka full access hai!\n\n"
        "• /start — Yeh message\n"
        "• /help  — Help",
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await gate(update, context):
        return
    await update.message.reply_text(
        "🤖 *Help*\n\nApna bot logic yahan likho.",
        parse_mode="Markdown",
    )

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await gate(update, context):
        return
    # ── Apna bot logic yahan likho ───────────────────────────────────────────
    await update.message.reply_text(f"Aapne kaha: {update.message.text}")

async def verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    unjoined = await get_unjoined(query.from_user.id, context)

    if not unjoined:
        await query.edit_message_text(
            f"✅ *Verified!* Welcome, {query.from_user.first_name}!\n\n"
            f"Saare {len(CHANNELS)} channels join kar liye.\n"
            "/start dabao.",
            parse_mode="Markdown",
        )
        return

    remaining = len(unjoined)
    joined    = len(CHANNELS) - remaining
    ch_list   = "\n".join(f"  ❌  {ch['name']}  ({ch['username']})" for ch in unjoined)
    await query.edit_message_text(
        f"⚠️ Abhi bhi *{remaining} channel(s)* baaki hain:\n\n"
        f"Progress: *{joined}/{len(CHANNELS)}*\n\n"
        f"{ch_list}\n\n"
        "Sab join karo phir dobara Verify karo.",
        parse_mode="Markdown",
        reply_markup=join_keyboard(unjoined),
    )

# ─── MAIN ────────────────────────────────────────────────────────────────────

def main() -> None:
    # Pinger start karo (bot se pehle)
    start_pinger()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(verify_callback, pattern="^verify$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    logger.info(f"Bot start — {len(CHANNELS)} channel(s) — self-ping active (har {PING_INTERVAL//60} min)")
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=f"{WEBHOOK_URL}/webhook",
        url_path="/webhook",
    )

if __name__ == "__main__":
    main()
