import asyncio
import hashlib
import hmac
import json
import logging
import os
import sqlite3
from urllib.parse import parse_qsl

import aiohttp
from aiohttp import web
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, ReplyKeyboardMarkup, WebAppInfo, MenuButtonCommands
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ContextTypes, filters
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Environment variables
BOT_TOKEN = os.environ["BOT_TOKEN"]
APP_URL = os.environ["APP_URL"].rstrip("/")
WEBHOOK_PATH = os.environ.get("WEBHOOK_PATH", "getachew2026").strip("/")
WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"]
CONTACT_SYNC_SECRET = os.environ["CONTACT_SYNC_SECRET"]
PORT = int(os.environ.get("PORT", "10000"))
RENDER_EXTERNAL_URL = os.environ["RENDER_EXTERNAL_URL"].rstrip("/")
DB_PATH = os.environ.get("DB_PATH", "/tmp/getachew_bot.sqlite3")

# Language texts matching screenshots exactly
WORDS = {
    "am": {
        "phone_prompt": "ለመቀጠል የስልክ ቁጥርዎን ያጋሩ። ከመልዕክት መጻፊያው አጠገብ ያለውን የኪቦርድ/ካሬ ምልክት በመጫን ኪቦርዱን ይክፈቱ፣ ከዚያ «2 📱 ስልክ ቁጥር አጋራ» ይጫኑ።",
        "share_phone": "2 📱 ስልክ ቁጥር አጋራ",
        "received": "የስልክ ቁጥር ተቀብለናል ✅",
        "open_prompt": "መተግበሪያውን ለመክፈት ከዚህ መልዕክት በታች ያለውን ቁልፍ ይጫኑ።",
        "open_app": "Getachew Fikadu app 🚗",
        "change_language": "ቋንቋ ቀይር",
        "wrong_contact": "እባክዎ የራስዎን ስልክ ቁጥር ብቻ ያጋሩ። የኪቦርድ/ካሬ ምልክቱን በመጫን «2 📱 ስልክ ቁጥር አጋራ» ይጫኑ።",
        "sync_error": "የስልክ ቁጥርዎን ማስቀመጥ አልተቻለም። እባክዎ እንደገና ይሞክሩ::",
    },
    "om": {
        "phone_prompt": "Itti fufuuf lakkoofsa bilbilaa keessan qoodaa. Mallattoo kiiboordii/iskuweerii cina sanduuqa ergaa tuqaa; kiiboordiin yoo baname, «2 📱 Lakkoofsa bilbilaa qoodaa» tuqaa.",
        "share_phone": "2 📱 Lakkoofsa bilbilaa qoodaa",
        "received": "Lakkoofsa bilbilaa fudhanneerra ✅",
        "open_prompt": "Appii banuuf qabduu armaan gadii tuqaa.",
        "open_app": "Getachew Fikadu app 🚗",
        "change_language": "Afaan jijjiiri",
        "wrong_contact": "Maaloo lakkoofsa bilbilaa keessan qofa qoodaa. Mallattoo kiiboordii/iskuweerii tuqaa, achiis «2 📱 Lakkoofsa bilbilaa qoodaa» tuqaa.",
        "sync_error": "Lakkoofsa bilbilaa keessan kuusuu hin dandeenye. Maaloo irra deebi'aa::",
    },
    "en": {
        "phone_prompt": "Please share your phone number to continue. Tap the small keyboard/squares icon beside the message box to show the keyboard, then tap “2 📱 Share phone number.”",
        "share_phone": "2 📱 Share phone number",
        "received": "Phone number received ✅",
        "open_prompt": "Tap the button below to open the app.",
        "open_app": "Getachew Fikadu app 🚗",
        "change_language": "Change language",
        "wrong_contact": "Please share your own phone number. Tap the small keyboard/squares icon beside the message box, then tap “2 📱 Share phone number.”",
        "sync_error": "We couldn't save your phone number. Please try again::",
    },
}

LANGUAGE_CHOICES = {
    "1 🇪🇹 Afaan Oromo": "om",
    "1 🇪🇹 አማርኛ": "am",
    "1 🇬🇧 English": "en",
}


# Database helpers
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS users (telegram_id INTEGER PRIMARY KEY, language TEXT, phone TEXT)")


def set_user(uid, lang=None, phone=None):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT OR IGNORE INTO users(telegram_id) VALUES(?)", (uid,))
        if lang:
            conn.execute("UPDATE users SET language=? WHERE telegram_id=?", (lang, uid))
        if phone:
            conn.execute("UPDATE users SET phone=? WHERE telegram_id=?", (phone, uid))


def get_lang(uid):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT language FROM users WHERE telegram_id=?", (uid,)).fetchone()
    return (row and row[0]) or "am"


def get_phone(uid):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT phone FROM users WHERE telegram_id=?", (uid,)).fetchone()
    return (row and row[0]) or None


# Keyboards
def language_inline_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1 🇪🇹 Afaan Oromo", callback_data="lang_om")],
        [InlineKeyboardButton("1 🇪🇹 አማርኛ", callback_data="lang_am")],
        [InlineKeyboardButton("1 🇬🇧 English", callback_data="lang_en")],
    ])


def phone_keyboard(lang):
    label = WORDS.get(lang, WORDS["am"])["share_phone"]
    return ReplyKeyboardMarkup(
        [[KeyboardButton(label, request_contact=True)]],
        resize_keyboard=True,
        is_persistent=True,
    )


def app_keyboard(lang):
    words = WORDS.get(lang, WORDS["am"])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(words["open_app"], web_app=WebAppInfo(url=APP_URL))],
        [InlineKeyboardButton(words["change_language"], callback_data="change_language")]
    ])


async def reset_chat_menu_button(bot, user_id):
    """Remove a previously configured per-chat Mini App shortcut before phone sharing."""
    try:
        await bot.set_chat_menu_button(chat_id=user_id, menu_button=MenuButtonCommands())
    except Exception:
        logger.exception("Could not reset the menu button for user %s", user_id)


# Bot Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message, user = update.effective_message, update.effective_user
    if not message or not user:
        return

    # Users who shared their phone number get the Mini App button in the reply keyboard.
    if await get_saved_phone(user.id):
        lang = get_lang(user.id)
        words = WORDS.get(lang, WORDS["am"])
        await message.reply_text(
            f"{words['received']}\n\n{words['open_prompt']}",
            reply_markup=app_keyboard(lang)
        )
        return

    await reset_chat_menu_button(context.bot, user.id)
    # New user: show language selection menu
    prompt = (
        "🚗 <b>Getachew Fikadu Jirata</b>\n\n"
        "Maaloo Afaan filadhaa.\n"
        "___________________\n"
        "እባክዎ ቋንቋ ይምረጡ።\n"
        "___________________\n"
        "Please select your language."
    )
    await message.reply_text(prompt, reply_markup=language_inline_keyboard(), parse_mode="HTML")


async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Allows users to explicitly change language anytime via /language without resetting phone."""
    message, user = update.effective_message, update.effective_user
    if not message:
        return
    if user and not await get_saved_phone(user.id):
        await reset_chat_menu_button(context.bot, user.id)
    prompt = (
        "🚗 <b>Getachew Fikadu Jirata</b>\n\n"
        "Maaloo Afaan filadhaa.\n"
        "___________________\n"
        "እባክዎ ቋንቋ ይምረጡ።\n"
        "___________________\n"
        "Please select your language."
    )
    await message.reply_text(prompt, reply_markup=language_inline_keyboard(), parse_mode="HTML")


async def send_phone_or_app(message, user_id, lang, bot):
    words = WORDS.get(lang, WORDS["am"])
    if await get_saved_phone(user_id):
        await message.reply_text(f"{words['received']}\n\n{words['open_prompt']}", reply_markup=app_keyboard(lang))
    else:
        await reset_chat_menu_button(bot, user_id)
        await message.reply_text(words["phone_prompt"], reply_markup=phone_keyboard(lang))


async def language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = (query.data or "").replace("lang_", "")
    user = update.effective_user
    if user and lang in WORDS:
        set_user(user.id, lang=lang)
        phone = get_phone(user.id)
        if phone:
            asyncio.create_task(sync_contact_to_website(user.id, phone))
        await send_phone_or_app(query.message, user.id, lang, context.bot)


async def change_language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "Please select your language / ቋንቋ ይምረጡ / Afaan filadhaa:",
        reply_markup=language_inline_keyboard()
    )


async def choose_language_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message, user = update.effective_message, update.effective_user
    if not message or not user or not message.text:
        return
    lang = LANGUAGE_CHOICES.get(message.text.strip())
    if lang:
        set_user(user.id, lang=lang)
        phone = get_phone(user.id)
        if phone:
            asyncio.create_task(sync_contact_to_website(user.id, phone))
        await send_phone_or_app(message, user.id, lang, context.bot)


async def sync_contact_to_website(telegram_id: int, phone: str):
    if not APP_URL or not CONTACT_SYNC_SECRET:
        logger.error("Contact sync is not configured; the website will not retain the shared phone number")
        return False
    sync_url = f"{APP_URL}/api/bot-contact.php"
    headers = {"X-Bot-Contact-Secret": CONTACT_SYNC_SECRET, "Content-Type": "application/json"}
    payload = {"telegram_id": str(telegram_id), "phone": str(phone), "language": get_lang(telegram_id)}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=6)) as session:
            async with session.post(sync_url, json=payload, headers=headers) as resp:
                if resp.status == 200:
                    logger.info("Synced contact for user %s to website", telegram_id)
                    return True
                else:
                    logger.warning("Contact sync returned HTTP %s", resp.status)
    except Exception as e:
        logger.warning("Website contact sync error: %s", e)
    return False


async def get_saved_phone(telegram_id: int):
    phone = get_phone(telegram_id)
    if phone:
        return phone
    if not APP_URL or not CONTACT_SYNC_SECRET:
        return None

    url = f"{APP_URL}/api/bot-contact.php"
    headers = {"X-Bot-Contact-Secret": CONTACT_SYNC_SECRET}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.get(url, params={"telegram_id": str(telegram_id)}, headers=headers) as response:
                if response.status != 200:
                    logger.warning("Website contact lookup returned HTTP %s", response.status)
                    return None
                result = await response.json()
    except Exception as error:
        logger.warning("Website contact lookup failed: %s", error)
        return None

    if not isinstance(result, dict) or not result.get("success"):
        logger.warning("Website contact lookup returned an unsuccessful response")
        return None
    language = result.get("language")
    if language in WORDS:
        set_user(telegram_id, lang=language)
    phone = result.get("phone")
    if isinstance(phone, str) and phone:
        set_user(telegram_id, phone=phone)
        return phone
    return None


async def got_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message, user = update.effective_message, update.effective_user
    contact = message.contact if message else None
    if not user or not contact or not contact.phone_number:
        return

    lang = get_lang(user.id)
    words = WORDS.get(lang, WORDS["am"])

    if contact.user_id is not None and contact.user_id != user.id:
        await message.reply_text(words["wrong_contact"], reply_markup=phone_keyboard(lang))
        return

    try:
        set_user(user.id, phone=contact.phone_number)
    except Exception:
        logger.exception("Failed to save contact for user %s", user.id)
        await message.reply_text(words["sync_error"], reply_markup=phone_keyboard(lang))
        return

    # Save the contact on the website before offering the Mini App button.
    await sync_contact_to_website(user.id, contact.phone_number)

    # Show the Mini App button after the website has saved the shared contact.
    await message.reply_text(f"{words['received']}\n\n{words['open_prompt']}", reply_markup=app_keyboard(lang))


# Web API Helpers
def telegram_webapp_user_id(init_data):
    if not init_data or len(init_data) > 10000:
        return None
    try:
        fields = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
        received_hash = fields.pop("hash", "")
        fields.pop("signature", None)
        if not received_hash:
            return None
        data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
        secret = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
        if not hmac.compare_digest(hmac.new(secret, data_check.encode("utf-8"), hashlib.sha256).hexdigest(), received_hash):
            return None
        user = json.loads(fields.get("user", "{}"))
        return user.get("id") if isinstance(user.get("id"), int) and user.get("id") > 0 else None
    except Exception:
        return None


def contact_api_response(request, payload, status=200):
    resp = web.json_response(payload, status=status)
    origin = request.headers.get("Origin", "")
    resp.headers["Access-Control-Allow-Origin"] = origin if origin else "*"
    if origin:
        resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Telegram-Init-Data, X-Bot-Contact-Secret, Authorization"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp


async def contact_lookup(request):
    if request.method == "OPTIONS":
        return contact_api_response(request, {"success": True})

    secret = request.headers.get("X-Bot-Contact-Secret") or request.query.get("secret")
    telegram_id = request.query.get("telegram_id")
    init_data = request.query.get("initData") or request.headers.get("X-Telegram-Init-Data")

    if request.method == "POST":
        try:
            body = await request.json()
        except Exception:
            body = {}
        secret = secret or body.get("secret")
        telegram_id = telegram_id or body.get("telegram_id")
        init_data = init_data or body.get("initData")

    # 1. Server-to-server secret authentication (e.g. from PHP backend)
    if secret and hmac.compare_digest(str(secret).strip(), CONTACT_SYNC_SECRET):
        if telegram_id and str(telegram_id).strip().isdigit():
            tid = int(telegram_id)
            phone = await get_saved_phone(tid)
            return contact_api_response(request, {"success": True, "phone": phone, "language": get_lang(tid)})
        return contact_api_response(request, {"success": False, "error": "Invalid telegram_id"}, 400)

    # 2. Telegram Mini App authentication using initData
    user_id = telegram_webapp_user_id(str(init_data).strip()) if init_data else None
    if user_id:
        phone = await get_saved_phone(user_id)
        return contact_api_response(request, {"success": True, "phone": phone, "language": get_lang(user_id), "user_id": user_id})

    return contact_api_response(request, {"success": False, "error": "Unauthorized contact lookup"}, 403)


# Webhook & Lifecycle
async def webhook(request):
    if request.match_info.get("secret") != WEBHOOK_SECRET:
        return web.Response(status=403)
    update = Update.de_json(await request.json(), application.bot)
    await application.process_update(update)
    return web.Response(text="OK")


async def startup(app):
    init_db()
    await application.initialize()
    await application.start()
    webhook_url = f"{RENDER_EXTERNAL_URL}/{WEBHOOK_PATH}/{WEBHOOK_SECRET}"
    await application.bot.set_webhook(webhook_url, allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)
    logger.info("Webhook configured for %s/%s/[hidden]", RENDER_EXTERNAL_URL, WEBHOOK_PATH)
    try:
        await application.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        logger.info("Default chat menu button reset; Mini App is available after phone sharing")
    except Exception as e:
        logger.warning("Could not reset default chat menu button: %s", e)


async def cleanup(app):
    await application.stop()
    await application.shutdown()


# Application Setup
application = Application.builder().token(BOT_TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("language", language_command))
application.add_handler(CallbackQueryHandler(language_callback, pattern=r"^lang_(om|am|en)$"))
application.add_handler(CallbackQueryHandler(change_language_callback, pattern=r"^change_language$"))
application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.CONTACT, got_contact))
application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, choose_language_text))

app = web.Application()
app.router.add_get("/health", lambda r: web.Response(text="OK"))
app.router.add_route("*", "/api/contact", contact_lookup)
app.router.add_post(f"/{WEBHOOK_PATH}/{{secret}}", webhook)
app.on_startup.append(startup)
app.on_cleanup.append(cleanup)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=PORT)
