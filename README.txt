UPDATED BOT FILES

Upload bot.py and requirements.txt to your existing GitHub repository, replacing the old files.
Keep your existing Render environment variables and add:
BOT_TOKEN
WEBHOOK_PATH
WEBHOOK_SECRET
APP_URL
CONTACT_SYNC_SECRET (a private random value of at least 32 characters)

Render commands:
Build: pip install -r requirements.txt
Start: python bot.py

What changes:
- `/start` directly asks new users to share their phone using a Telegram contact button.
- After the first successful share, the bot saves the phone, syncs it to the website, confirms receipt, and shows a separate button to open the Mini App.
- Returning users with a saved phone are not asked to share again; `/start` shows the Mini App button directly.
- The bot does not show a welcome banner before opening the Mini App.
- The bot accepts only the user's own Telegram contact.
- The final Mini App button opens the same APP_URL.

IMPORTANT: Keep APP_URL set to the website root URL. The bot uses that site for contact sync and opening the Mini App. Test contact sharing inside Telegram.

Also add the same CONTACT_SYNC_SECRET value as contact_sync_secret in api/config.php. Do not share or commit this secret. Do not use the website admin panel's "Configure Telegram contact-first bot" action with this Render bot; Telegram supports one webhook per bot, and that action would replace the Render webhook.

SQLite uses /tmp on Render Free, so saved phone data can be lost after restart/redeploy. Use persistent storage or PostgreSQL for reliable long-term storage.
