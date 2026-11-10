import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import sqlite3
from urllib.parse import parse_qsl

import aiohttp
from aiohttp import web
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, WebAppInfo
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ContextTypes, filters
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
APP_URL = os.environ["APP_URL"].rstrip("/")
WEBHOOK_PATH = os.environ.get("WEBHOOK_PATH", "getachew2026").strip("/")
WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"]
CONTACT_SYNC_SECRET = os.environ["CONTACT_SYNC_SECRET"]
PORT = int(os.environ.get("PORT", "10000"))
RENDER_EXTERNAL_URL = os.environ["RENDER_EXTERNAL_URL"].rstrip("/")
DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "getachew_bot.sqlite3")
DB_PATH = os.environ.get("DB_PATH", DEFAULT_DB_PATH)

# Match the three language choices shown in the user's Telegram screenshots.
LANGUAGE_CHOICES = {
    "1 🇪🇹 Afaan Oromo": "om",
    "1 🇪🇹 አማርኛ": "am",
    "1 🇬🇧 English": "en",
}
LANGUAGE_LABELS = {
    "om": "1 🇪🇹 Afaan Oromo",
    "am": "1 🇪🇹 አማርኛ",
    "en": "1 🇬🇧 English",
}

WORDS = {
    "en": {
        "language_prompt": "Please select your language.",
        "phone_prompt": "Please share your phone number to continue.",
        "share_phone": "📱 Share Phone Number",
        "received": "✅ Your phone number was received successfully.",
        "open_prompt": "Tap the button below to open the app.",
        "open_app": "🚗 Getachew Fikadu app",
        "already_saved": "Your phone number is already saved. Tap below to open the app.",
        "wrong_contact": "Please share your own phone number using the button below.",
        "sync_error": "We couldn't save your phone number. Please try again.",
        "change_language": "🌐 Change language",
    },
    "am": {
        "language_prompt": "እባክዎ ቋንቋ ይምረጡ።",
        "phone_prompt": "ለመቀጠል እባክዎ የስልክ ቁጥርዎን ያጋሩ።",
        "share_phone": "📱 ስልክ ቁጥር ያጋሩ",
        "received": "✅ የስልክ ቁጥርዎ በተሳካ ሁኔታ ደርሶናል።",
        "open_prompt": "መተግበሪያውን ለመክፈት ከታች ያለውን ቁልፍ ይጫኑ።",
        "open_app": "🚗 Getachew Fikadu መተግበሪያ",
        "already_saved": "የስልክ ቁጥርዎ አስቀድሞ ተቀምጧል። መተግበሪያውን ለመክፈት ከታች ይጫኑ።",
        "wrong_contact": "እባክዎ ከታች ያለውን ቁልፍ በመጠቀም የራስዎን ስልክ ያጋሩ።",
        "sync_error": "የስልክ ቁጥርዎን ማስቀመጥ አልተቻለም። እባክዎ እንደገና ይሞክሩ።",
        "change_language": "🌐 ቋንቋ ይቀይሩ",
    },
    "om": {
        "language_prompt": "Maaloo afaan keessan filadhaa.",
        "phone_prompt": "Itti fufuuf maaloo lakkoofsa bilbilaa keessan qoodaa.",
        "share_phone": "📱 Lakkoofsa Bilbilaa Qoodaa",
        "received": "✅ Lakkoofsi bilbilaa keessan milkaa'inaan nu gaheera.",
        "open_prompt": "Appii banuuf buttonii armaan gadii tuqaa.",
        "open_app": "🚗 Getachew Fikadu app",
        "already_saved": "Lakkoofsi bilbilaa keessan duraan kuufameera. Appii banuuf armaan gadii tuqaa.",
        "wrong_contact": "Maaloo buttonii armaan gadii fayyadamuun lakkoofsa bilbilaa keessan qoodaa.",
        "sync_error": "Lakkoofsa bilbilaa keessan kuusuu hin dandeenye. Maaloo irra deebi'aa.",
        "change_language": "🌐 Afaan jijjiiraa",
    },
}


def get_db_conn():
    global DB_PATH
    try:
        return sqlite3.connect(DB_PATH)
    except Exception:
        fallback = "/tmp/getachew_bot.sqlite3"
        DB_PATH = fallback
        return sqlite3.connect(fallback)


def init_db():
    with get_db_conn() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY, language TEXT, phone TEXT
        )""")


def set_user(uid, lang=None, phone=None):
    with get_db_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO users(telegram_id) VALUES(?)", (uid,))
        if lang:
            conn.execute("UPDATE users SET language=? WHERE telegram_id=?", (lang, uid))
        if phone:
            conn.execute("UPDATE users SET phone=? WHERE telegram_id=?", (phone, uid))


def get_lang(uid):
    with get_db_conn() as conn:
        row = conn.execute("SELECT language FROM users WHERE telegram_id=?", (uid,)).fetchone()
    return (row and row[0]) or "en"


def get_phone(uid):
    with get_db_conn() as conn:
        row = conn.execute("SELECT phone FROM users WHERE telegram_id=?", (uid,)).fetchone()
    return (row and row[0]) or None


def language_keyboard():
    # Persistent keyboard: users can change language again at any time.
    return ReplyKeyboardMarkup(
        [[LANGUAGE_LABELS["om"]], [LANGUAGE_LABELS["am"]], [LANGUAGE_LABELS["en"]]],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def phone_keyboard(lang):
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(WORDS[lang]["share_phone"], request_contact=True)],
            [WORDS[lang]["change_language"]],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def app_keyboard(lang):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(WORDS[lang]["open_app"], web_app=WebAppInfo(url=APP_URL))],
        [InlineKeyboardButton(WORDS[lang]["change_language"], callback_data="show_languages")],
    ])


async def show_language_menu(message):
    # Title and language instructions appear in one message; the
    # three language buttons are attached directly underneath it.
    prompt = (
        "🚗 **Getachew Fikadu Jirata**\\n\\n"
        "Maaloo Afaan filadhaa.\\n"
        "━━━━━━━━━━━━━━\\n"
        "እባክዎ ቋንቋ ይምረጡ።\\n"
        "━━━━━━━━━━━━━━\\n"
        "Please select your language."
    )
    await message.reply_text(
        prompt,
        reply_markup=language_keyboard(),
        parse_mode="Markdown",
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
