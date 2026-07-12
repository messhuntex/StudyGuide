# StudyGuide Telegram Bot

Production-ready Telegram bot for students built with Python 3.12+, Aiogram 3.x, SQLite, and Telegram native file storage.

## Features

- Bengali-first student-friendly UI
- Study Groups, Classes, Practice Sets, Notes, PW Lectures, Support Team
- Full admin panel inside Telegram
- Broadcast messages to all users
- SQLite database (auto-creates tables)
- Telegram file_id based storage (no external file hosting)

## Files

- `bot.py` - Main bot file (single file, all-in-one)
- `requirements.txt` - Python dependencies
- `.env` - Environment variables
- `Dockerfile` - Container deployment
- `runtime.txt` - Render Python version

## Local Setup

1. Clone or download the files.
2. Create a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # Windows: venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Copy `.env.example` to `.env` and fill in:
   ```bash
   cp .env.example .env
   ```
5. Set your bot token from [@BotFather](https://t.me/BotFather).
6. Set your Telegram User ID as `ADMIN_USER_ID`. Get it from [@userinfobot](https://t.me/userinfobot).
7. Run:
   ```bash
   python bot.py
   ```

## Admin Access

Send `/admin` to the bot. Only the configured admin can access the panel.

## Deployment

### Render

1. Create a new Web Service.
2. Connect your GitHub repo or upload files manually.
3. Set environment variables in Render Dashboard.
4. For Python native deployment, include `runtime.txt`.
5. For webhook mode, set `WEBHOOK_URL` to your Render app URL.

### Koyeb

1. Create a new App.
2. Select Dockerfile deployment.
3. Add environment variables.
4. Set `WEBHOOK_URL` to your Koyeb app URL.
5. Expose port 8080.

### VPS / Oracle Cloud

1. Upload files.
2. Install dependencies.
3. Run with screen/tmux or systemd:
   ```bash
   python bot.py
   ```
4. Or use Docker:
   ```bash
   docker build -t studyguide-bot .
   docker run -d --env-file .env -p 8080:8080 --name studyguide studyguide-bot
   ```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| BOT_TOKEN | Yes | Telegram bot token |
| ADMIN_USER_ID | Yes* | Admin numeric user ID |
| ADMIN_USERNAME | Yes* | Admin Telegram username without @ |
| DB_PATH | No | SQLite file path (default: studyguide.db) |
| WEBHOOK_URL | No | Webhook URL for production |
| WEBHOOK_PORT | No | Webhook port (default: 8080) |
| WEBHOOK_PATH | No | Webhook path (default: /webhook) |

*At least one of ADMIN_USER_ID or ADMIN_USERNAME must be set.

## Notes

- Database file `studyguide.db` is created beside `bot.py` and persists across restarts.
- Files are stored only as Telegram file_ids. Never store actual files locally.