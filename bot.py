import hmac, logging, os, re, sqlite3
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, WebAppInfo
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO)
BOT_TOKEN=os.environ["BOT_TOKEN"]
APP_URL=os.environ["APP_URL"].rstrip("/")
WEBHOOK_PATH=os.environ.get("WEBHOOK_PATH","getachew2026").strip("/")
WEBHOOK_SECRET=os.environ["WEBHOOK_SECRET"]
CONTACT_SYNC_SECRET=os.environ["CONTACT_SYNC_SECRET"]
PORT=int(os.environ.get("PORT","10000"))
RENDER_EXTERNAL_URL=os.environ["RENDER_EXTERNAL_URL"].rstrip("/")
DB_PATH=os.environ.get("DB_PATH","/tmp/getachew_bot.sqlite3")

PHONE_BUTTON="📱 Share Phone Number"
APP_BUTTON="🚗 Open Mini App"
WORDS={
    "en": {
        "language_prompt": "Please select your language.",
        "phone_prompt": "Please share your phone number to continue.",
        "received": "We received your phone number. Press the button below to open the app.",
        "open_prompt": "Press the button below to open the Mini App.",
        "already_saved": "Your phone number is already saved. Press below to open the app.",
        "wrong_contact": "Please share your own phone number using the button below.",
        "sync_error": "We couldn't save your phone number. Please try sharing it again."
    },
    "am": {
        "language_prompt": "እባክዎ ቋንቋ ይምረጡ።",
        "phone_prompt": "ለመቀጠል እባክዎ የስልክ ቁጥርዎን ያጋሩ።",
        "received": "የስልክ ቁጥርዎ ደርሶናል። መተግበሪያውን ለመክፈት ከታች ያለውን ቁልፍ ይጫኑ።",
        "open_prompt": "Mini App-ን ለመክፈት ከታች ያለውን ቁልፍ ይጫኑ።",
        "already_saved": "የስልክ ቁጥርዎ አስቀድሞ ተቀምጧል። መተግበሪያውን ለመክፈት ከታች ይጫኑ።",
        "wrong_contact": "እባክዎ ከታች ያለውን ቁልፍ በመጠቀም የራስዎን ስልክ ያጋሩ።",
        "sync_error": "የስልክ ቁጥርዎን ማስቀመጥ አልተቻለም። እባክዎ እንደገና ያጋሩ።"
    },
    "om": {
        "language_prompt": "Maaloo afaan keessan filadhaa.",
        "phone_prompt": "Itti fufuuf maaloo lakkoofsa bilbilaa keessan qoodaa.",
        "received": "Lakkoofsa bilbilaa keessan arganneerra. Appii banuuf buttonii armaan gadii tuqaa.",
        "open_prompt": "Mini App banuuf buttonii armaan gadii tuqaa.",
        "already_saved": "Lakkoofsi bilbilaa keessan duraan kuufameera. Appii banuuf armaan gadii tuqaa.",
        "wrong_contact": "Maaloo buttonii armaan gadii fayyadamuun lakkoofsa bilbilaa keessan qoodaa.",
        "sync_error": "Lakkoofsa bilbilaa keessan kuusuu hin dandeenye. Maaloo irra deebi'aa."
    }
}

def init_db():
    with sqlite3.connect(DB_PATH) as c:
        c.execute("CREATE TABLE IF NOT EXISTS users (telegram_id INTEGER PRIMARY KEY, language TEXT, phone TEXT)")
def set_user(uid, lang=None, phone=None):
    with sqlite3.connect(DB_PATH) as c:
        c.execute("INSERT OR IGNORE INTO users(telegram_id) VALUES(?)",(uid,))
        if lang: c.execute("UPDATE users SET language=? WHERE telegram_id=?",(lang,uid))
        if phone: c.execute("UPDATE users SET phone=? WHERE telegram_id=?",(phone,uid))

def get_lang(uid):
    with sqlite3.connect(DB_PATH) as c:
        r=c.execute("SELECT language FROM users WHERE telegram_id=?",(uid,)).fetchone()
    return (r and r[0]) or "en"

def get_phone(uid):
    with sqlite3.connect(DB_PATH) as c:
        r=c.execute("SELECT phone FROM users WHERE telegram_id=?",(uid,)).fetchone()
    return (r and r[0]) or None

def phone_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton(PHONE_BUTTON, request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

def app_keyboard():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(APP_BUTTON, web_app=WebAppInfo(url=APP_URL))]]
    )

async def start(update:Update, context:ContextTypes.DEFAULT_TYPE):
    text=WORDS["en"]["language_prompt"] + "\n" + WORDS["am"]["language_prompt"] + "\n" + WORDS["om"]["language_prompt"]
    keys=[
        [InlineKeyboardButton("🇬🇧 English", callback_data="lang:en")],
        [InlineKeyboardButton("🇪🇹 አማርኛ", callback_data="lang:am")],
        [InlineKeyboardButton("🇪🇹 Afaan Oromo", callback_data="lang:om")]
    ]
    await update.message.reply_text(text,reply_markup=InlineKeyboardMarkup(keys))

async def choose_language(update:Update, context:ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    user=query.from_user
    lang=query.data.split(":",1)[1]
    set_user(user.id,lang=lang)
    words=WORDS[lang]
    phone=get_phone(user.id)
    if phone:
        await query.message.reply_text(
            words["already_saved"],
            reply_markup=app_keyboard()
        )
        return

    await query.message.reply_text(
        words["phone_prompt"],
        reply_markup=phone_keyboard()
    )

async def got_contact(update:Update, context:ContextTypes.DEFAULT_TYPE):
    contact=update.message.contact
    user=update.effective_user
    if not contact or contact.user_id != user.id:
        words=WORDS.get(get_lang(user.id),WORDS["en"])
        await update.message.reply_text(
            words["wrong_contact"],
            reply_markup=phone_keyboard()
        )
        return
    set_user(user.id,phone=contact.phone_number)
    words=WORDS.get(get_lang(user.id),WORDS["en"])
    await update.message.reply_text(
        words["received"],
        reply_markup=ReplyKeyboardRemove()
    )
    await update.message.reply_text(
        words["open_prompt"],
        reply_markup=app_keyboard()
    )

async def health(request):
    return web.Response(text="OK")

async def contact_lookup(request):
    received_secret=request.headers.get("X-Bot-Contact-Secret","")
    if not hmac.compare_digest(received_secret,CONTACT_SYNC_SECRET):
        return web.json_response({"success":False,"error":"Authentication failed."},status=403)
    telegram_id=request.query.get("telegram_id","")
    if not re.fullmatch(r"[1-9][0-9]{0,19}",telegram_id):
        return web.json_response({"success":False,"error":"Invalid Telegram user ID."},status=400)
    phone=get_phone(int(telegram_id))
    return web.json_response({"success":True,"phone":phone})

async def webhook(request):
    if request.match_info["secret"] != WEBHOOK_SECRET: return web.Response(status=403)
    upd=Update.de_json(await request.json(),application.bot)
    await application.process_update(upd)
    return web.Response(text="OK")

async def startup(app):
    init_db()
    await application.initialize()
    await application.start()
    await application.bot.set_webhook(
      f"{RENDER_EXTERNAL_URL}/{WEBHOOK_PATH}/{WEBHOOK_SECRET}",
      allowed_updates=Update.ALL_TYPES,drop_pending_updates=True)

async def cleanup(app):
    await application.bot.delete_webhook()
    await application.stop()
    await application.shutdown()

application=Application.builder().token(BOT_TOKEN).build()
application.add_handler(CommandHandler("start",start))
application.add_handler(CallbackQueryHandler(choose_language,pattern=r"^lang:(en|am|om)$"))
application.add_handler(MessageHandler(filters.CONTACT,got_contact))
app=web.Application()
app.router.add_get("/health",health)
app.router.add_get("/api/contact",contact_lookup)
app.router.add_post(f"/{WEBHOOK_PATH}/{{secret}}",webhook)
app.on_startup.append(startup)
app.on_cleanup.append(cleanup)

if __name__=="__main__":
    web.run_app(app,host="0.0.0.0",port=PORT)
