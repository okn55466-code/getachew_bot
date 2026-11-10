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
        [[KeyboardButton(WORDS[lang]["share_phone"], request_contact=True)]],
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
        "\\n"
        "እባክዎ ቋንቋ ይምረጡ።\\n"
        "\\n"
        "Please select your language."
    )
    await message.reply_text(
        prompt,
        reply_markup=language_keyboard(),
        parse_mode="Markdown",
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_message:
        await show_language_menu(update.effective_message)


async def send_phone_or_app(message, user_id, lang):
    words = WORDS[lang]
    if get_phone(user_id):
        await message.reply_text(
            words["already_saved"],
            reply_markup=app_keyboard(lang),
        )
    else:
        await message.reply_text(
            words["phone_prompt"],
            reply_markup=phone_keyboard(lang),
        )


async def apply_language(message, user, lang):
    set_user(user.id, lang=lang)
    await send_phone_or_app(message, user.id, lang)


async def choose_language_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not message.text:
        return
    if message.text.strip() in {words["change_language"] for words in WORDS.values()}:
        await show_language_menu(message)
        return
    lang = LANGUAGE_CHOICES.get(message.text.strip())
    if lang:
        await apply_language(message, user, lang)


async def show_languages_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await show_language_menu(query.message)


async def sync_contact_to_website(telegram_id: int, phone: str):
    if not APP_URL or not CONTACT_SYNC_SECRET:
        return
    sync_url = f"{APP_URL}/api/bot-contact.php"
    try:
        headers = {
            "X-Bot-Contact-Secret": CONTACT_SYNC_SECRET,
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; TelegramBotContactSync/1.0)",
        }
        payload = {"telegram_id": str(telegram_id), "phone": str(phone)}
        timeout = aiohttp.ClientTimeout(total=6)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(sync_url, json=payload, headers=headers) as resp:
                if resp.status == 200:
                    logger.info("Successfully synced contact for user %s to website %s", telegram_id, sync_url)
                else:
                    text = await resp.text()
                    logger.warning("Website contact sync returned HTTP %s: %s", resp.status, text[:200])
    except Exception as e:
        logger.warning("Website contact sync error: %s", e)


async def got_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user = update.effective_user
    contact = message.contact if message else None
    if not user or not contact or not contact.phone_number:
        return

    # Telegram Contact.user_id is optional; only reject if it explicitly
    # identifies a different Telegram account.
    if contact.user_id is not None and contact.user_id != user.id:
        lang = get_lang(user.id)
        await message.reply_text(
            WORDS[lang]["wrong_contact"],
            reply_markup=phone_keyboard(lang),
        )
        return

    try:
        set_user(user.id, phone=contact.phone_number)
    except Exception:
        logger.exception("Failed to save contact for Telegram user %s", user.id)
        lang = get_lang(user.id)
        await message.reply_text(
            WORDS[lang]["sync_error"],
            reply_markup=phone_keyboard(lang),
        )
        return

    # Sync to PHP website in background
    asyncio.create_task(sync_contact_to_website(user.id, contact.phone_number))

    lang = get_lang(user.id)
    await message.reply_text(WORDS[lang]["received"], reply_markup=ReplyKeyboardRemove())
    await message.reply_text(
        WORDS[lang]["open_prompt"],
        reply_markup=app_keyboard(lang),
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Unhandled Telegram update error", exc_info=context.error)


async def health(request):
    return web.Response(text="OK")


def telegram_webapp_user_id(init_data):
    """Validate Telegram Mini App initData and return the authenticated user ID."""
    if not init_data or len(init_data) > 10000:
        return None
    try:
        fields = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
        received_hash = fields.pop("hash", "")
        if not received_hash:
            return None
        data_check_string = "\n".join(
            f"{key}={value}" for key, value in sorted(fields.items())
        )
        secret_key = hmac.new(
            b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256
        ).digest()
        calculated_hash = hmac.new(
            secret_key, data_check_string.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(calculated_hash, received_hash):
            return None
        user_data = json.loads(fields.get("user", "{}"))
        user_id = user_data.get("id")
        if not isinstance(user_id, int) or user_id <= 0:
            return None
        return user_id
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def contact_api_response(request, payload, status=200):
    response = web.json_response(payload, status=status)
    origin = request.headers.get("Origin", "")
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
    else:
        response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = (
        "Content-Type, X-Telegram-Init-Data, X-Bot-Contact-Secret, Authorization"
    )
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Max-Age"] = "86400"
    return response


async def contact_lookup(request):
    if request.method == "OPTIONS":
        return contact_api_response(request, {"success": True})

    # 1. Server-to-server secret authentication (e.g. from PHP backend)
    secret_header = request.headers.get("X-Bot-Contact-Secret", "").strip()
    secret_param = request.query.get("secret", "").strip()
    secret_matched = False
    if secret_header and hmac.compare_digest(secret_header, CONTACT_SYNC_SECRET):
        secret_matched = True
    elif secret_param and hmac.compare_digest(secret_param, CONTACT_SYNC_SECRET):
        secret_matched = True

    if request.method == "GET":
        if secret_matched:
            telegram_id_str = str(request.query.get("telegram_id", "")).strip()
            if telegram_id_str.isdigit():
                phone = get_phone(int(telegram_id_str))
                return contact_api_response(request, {"success": True, "phone": phone})
            return contact_api_response(request, {"success": False, "error": "Invalid telegram_id."}, 400)

        # Telegram Mini App client-side GET with initData query param
        init_data = request.query.get("initData", "").strip()
        if init_data:
            user_id = telegram_webapp_user_id(init_data)
            if user_id:
                phone = get_phone(user_id)
                return contact_api_response(request, {"success": True, "phone": phone, "user_id": user_id})
            return contact_api_response(request, {"success": False, "error": "Telegram verification failed."}, 403)

        return contact_api_response(request, {"success": False, "error": "Unauthorized contact lookup."}, 403)

    if request.method == "POST":
        body = {}
        try:
            body = await request.json()
        except Exception:
            try:
                body = dict(await request.post())
            except Exception:
                body = {}

        # Server-to-server POST with secret in body
        body_secret = str(body.get("secret", "")).strip()
        if (not secret_matched) and body_secret and hmac.compare_digest(body_secret, CONTACT_SYNC_SECRET):
            secret_matched = True

        if secret_matched:
            telegram_id_str = str(body.get("telegram_id", "") or request.query.get("telegram_id", "")).strip()
            if telegram_id_str.isdigit():
                phone = get_phone(int(telegram_id_str))
                return contact_api_response(request, {"success": True, "phone": phone})
            return contact_api_response(request, {"success": False, "error": "Invalid telegram_id."}, 400)

        # Telegram Mini App client-side POST with initData in body or header
        init_data = (body.get("initData") or request.headers.get("X-Telegram-Init-Data", "")).strip()
        user_id = telegram_webapp_user_id(init_data)
        if not user_id:
            return contact_api_response(request, {"success": False, "error": "Telegram verification failed. Open this page inside Telegram."}, 403)
        phone = get_phone(user_id)
        return contact_api_response(request, {"success": True, "phone": phone, "user_id": user_id})

    return contact_api_response(request, {"success": False, "error": "Method not allowed."}, 405)


async def webhook(request):
    if request.match_info["secret"] != WEBHOOK_SECRET:
        return web.Response(status=403)
    update = Update.de_json(await request.json(), application.bot)
    await application.process_update(update)
    return web.Response(text="OK")


async def startup(app):
    init_db()
    await application.initialize()
    await application.start()
    webhook_url = f"{RENDER_EXTERNAL_URL}/{WEBHOOK_PATH}/{WEBHOOK_SECRET}"
    await application.bot.set_webhook(
        webhook_url,
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )
    logger.info("Telegram webhook configured successfully for %s/%s/[hidden]",
                RENDER_EXTERNAL_URL, WEBHOOK_PATH)


async def cleanup(app):
    # Do not delete the Telegram webhook on ordinary Render shutdown/restart.
    await application.stop()
    await application.shutdown()


application = Application.builder().token(BOT_TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(CallbackQueryHandler(show_languages_callback, pattern=r"^show_languages$"))
application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.CONTACT, got_contact))
application.add_handler(MessageHandler(
    filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
    choose_language_text
))
application.add_error_handler(error_handler)

app = web.Application()
app.router.add_get("/health", health)
app.router.add_route("*", "/api/contact", contact_lookup)
app.router.add_post(f"/{WEBHOOK_PATH}/{{secret}}", webhook)
app.on_startup.append(startup)
app.on_cleanup.append(cleanup)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=PORT)
