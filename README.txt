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
- `/start` shows language buttons first. After a language is selected, new users are asked to share their phone using a Telegram contact button.
- After the first successful share, the bot saves the phone, confirms receipt, and shows a separate button to open the Mini App.
- The website reads saved phone numbers securely from the bot service using the shared CONTACT_SYNC_SECRET.
- Returning users with a saved phone are not asked to share again; `/start` shows the Mini App button directly.
- No bot-name welcome banner is shown.
- The bot accepts only the user's own Telegram contact.
- The final Mini App button opens the same APP_URL.

IMPORTANT: Keep APP_URL set to the website root URL. The bot uses that site for contact sync and opening the Mini App. Test contact sharing inside Telegram.

In the website's api/config.php, set contact_api_url to this Render service's HTTPS URL and contact_sync_secret to the same CONTACT_SYNC_SECRET value. Do not share or commit this secret. Do not use the website admin panel's "Configure Telegram contact-first bot" action with this Render bot; Telegram supports one webhook per bot, and that action would replace the Render webhook.

SQLite uses /tmp on Render Free, so saved phone data can be lost after restart/redeploy. Use persistent storage or PostgreSQL for reliable long-term storage.
