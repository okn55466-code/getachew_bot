import asyncio, logging, os, sqlite3
from aiohttp import ClientError, ClientSession, ClientTimeout, web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

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

def init_db():
    with sqlite3.connect(DB_PATH) as c:
        c.execute("CREATE TABLE IF NOT EXISTS users (telegram_id INTEGER PRIMARY KEY, language TEXT, phone TEXT)")
def set_user(uid, phone=None):
    with sqlite3.connect(DB_PATH) as c:
        c.execute("INSERT OR IGNORE INTO users(telegram_id) VALUES(?)",(uid,))
        if phone: c.execute("UPDATE users SET phone=? WHERE telegram_id=?",(phone,uid))

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

async def sync_contact(uid, phone):
    async with ClientSession(timeout=ClientTimeout(total=15)) as session:
        async with session.post(
            APP_URL + "/api/bot-contact.php",
            json={"telegram_id": str(uid), "phone": phone},
            headers={"X-Bot-Contact-Secret": CONTACT_SYNC_SECRET}
        ) as response:
            result=await response.json()
            if response.status != 200 or not isinstance(result,dict) or not result.get("success"):
                raise ValueError("Contact sync endpoint rejected the phone number.")

async def start(update:Update, context:ContextTypes.DEFAULT_TYPE):
    user=update.effective_user
    phone=get_phone(user.id)
    if phone:
        try:
            await sync_contact(user.id,phone)
        except (ClientError, asyncio.TimeoutError, ValueError):
            logging.exception("Could not sync saved Telegram contact to the Mini App server")
            await update.message.reply_text("We couldn't load your saved phone number into the app. Please try /start again later.")
            return
        await update.message.reply_text(
            "Your phone number is already saved. Press below to open the app.",
            reply_markup=app_keyboard()
        )
        return

    await update.message.reply_text(
        "Please share your phone number to continue.",
        reply_markup=phone_keyboard()
    )

async def got_contact(update:Update, context:ContextTypes.DEFAULT_TYPE):
    contact=update.message.contact
    user=update.effective_user
    if not contact or contact.user_id != user.id:
        await update.message.reply_text(
            "Please share your own phone number using the button below.",
            reply_markup=phone_keyboard()
        )
        return
    try:
        await sync_contact(user.id,contact.phone_number)
    except (ClientError, asyncio.TimeoutError, ValueError):
        logging.exception("Could not sync Telegram contact to the Mini App server")
        await update.message.reply_text(
            "We couldn't save your phone number. Please try sharing it again.",
            reply_markup=phone_keyboard()
        )
        return
    set_user(user.id,phone=contact.phone_number)
    await update.message.reply_text(
        "We received your phone number. Press the button below to open the app.",
        reply_markup=app_keyboard()
    )

async def health(request):
    return web.Response(text="OK")

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
application.add_handler(MessageHandler(filters.CONTACT,got_contact))
app=web.Application()
app.router.add_get("/health",health)
app.router.add_post(f"/{WEBHOOK_PATH}/{{secret}}",webhook)
app.on_startup.append(startup)
app.on_cleanup.append(cleanup)

if __name__=="__main__":
    web.run_app(app,host="0.0.0.0",port=PORT)
