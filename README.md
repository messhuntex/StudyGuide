# StudyGuide Telegram Bot (Oracle Cloud Edition)

Production-ready Telegram bot for students built with Python 3.12+, Aiogram 3.x and SQLite.
Optimized to run 24/7 on **Oracle Cloud Always Free** VPS using **polling mode** and **systemd**.

## Features

- Bengali-first student-friendly UI
- Study Groups, Classes, Practice Sets, Notes, PW Lectures, Support Team
- Full admin panel inside Telegram (`/admin`)
- Broadcast (text / photo / document) with flood-limit protection
- SQLite database with WAL mode (crash-safe) + auto-backup script
- Telegram file_id storage only (no Cloudinary / AWS / local files)
- Auto-restart on crash and on server reboot

## Files

| File | Purpose |
|------|---------|
| `bot.py` | Main bot (single file, all-in-one) |
| `requirements.txt` | Python dependencies |
| `.env.example` | Environment variable template |
| `studyguide.service` | systemd unit for 24/7 running |
| `backup.sh` | Automatic DB backup script |

============================================================
## PART 1 — Get Your Telegram Credentials
============================================================

1. Open [@BotFather](https://t.me/BotFather) -> `/newbot` -> copy the **BOT_TOKEN**.
2. Open [@userinfobot](https://t.me/userinfobot) -> copy your numeric **ADMIN_USER_ID**.

============================================================
## PART 2 — Create Oracle Always Free VM
============================================================

1. Sign up at https://www.oracle.com/cloud/free/
   (A card is required for identity check — Always Free resources are never charged.)
2. Console -> Compute -> Instances -> **Create Instance**.
3. Image: **Canonical Ubuntu 22.04** (or 24.04).
4. Shape: pick an **Always Free** eligible shape:
   - `VM.Standard.A1.Flex` (Ampere ARM — up to 4 OCPU / 24 GB free), OR
   - `VM.Standard.E2.1.Micro` (x86 — always free).
5. Under "Add SSH keys" -> **Generate a key pair** -> download the **private key**.
6. Click **Create**. Wait until it is RUNNING, then copy the **Public IP address**.

### Open the network (so the VM can reach Telegram)
Outbound traffic is allowed by default, so polling works with no extra firewall rules.
(You do NOT need to open any inbound ports for polling mode.)

============================================================
## PART 3 — Connect to the Server (SSH)
============================================================

On your local computer terminal:

```bash
chmod 400 /path/to/your-private-key.key
ssh -i /path/to/your-private-key.key ubuntu@YOUR_PUBLIC_IP
```

(Windows users: use PowerShell, or PuTTY with the .ppk key.)

============================================================
## PART 4 — Install Everything
============================================================

Run these commands on the server:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git sqlite3

mkdir -p ~/studyguide && cd ~/studyguide
```

Now put the project files into `~/studyguide`. Two easy ways:

**Option A — create files manually**
```bash
nano bot.py            # paste bot.py content, Ctrl+O, Enter, Ctrl+X
nano requirements.txt  # paste, save
nano studyguide.service
nano backup.sh
```

**Option B — upload from your PC** (run on your PC, not the server)
```bash
scp -i your-key.key bot.py requirements.txt studyguide.service backup.sh \
    ubuntu@YOUR_PUBLIC_IP:~/studyguide/
```

Create the virtual environment and install dependencies:

```bash
cd ~/studyguide
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

============================================================
## PART 5 — Configure .env
============================================================

```bash
nano .env
```

Paste and edit:

```
BOT_TOKEN=123456:ABC-your-real-token
ADMIN_USER_ID=123456789
ADMIN_USERNAME=shreeakash
DB_PATH=/home/ubuntu/studyguide/studyguide.db
WEBHOOK_URL=
```

IMPORTANT: Keep `WEBHOOK_URL` empty. On Oracle the bot runs in **polling mode** automatically.
Save with Ctrl+O, Enter, Ctrl+X.

### Quick test (before making it a service)
```bash
source venv/bin/activate
python bot.py
```
Message your bot on Telegram — it should reply. Then press Ctrl+C to stop.

============================================================
## PART 6 — Run 24/7 with systemd
============================================================

The provided `studyguide.service` already uses the correct paths for user `ubuntu`.

```bash
sudo cp ~/studyguide/studyguide.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable studyguide     # start on every boot
sudo systemctl start studyguide      # start now
sudo systemctl status studyguide     # should show "active (running)"
```

The bot now:
- restarts automatically if it crashes,
- starts automatically when the server reboots,
- keeps `studyguide.db` on disk permanently.

### Everyday commands
```bash
sudo systemctl restart studyguide          # restart after editing files
sudo systemctl stop studyguide             # stop
sudo journalctl -u studyguide -f           # live logs
tail -f ~/studyguide/bot.log               # log file
```

============================================================
## PART 7 — Automatic Database Backups
============================================================

```bash
chmod +x ~/studyguide/backup.sh
~/studyguide/backup.sh          # test it once
crontab -e                      # choose nano if asked
```

Add this line at the bottom (backup every 6 hours):

```
0 */6 * * * /home/ubuntu/studyguide/backup.sh
```

Backups are stored (gzipped) in `~/studyguide/backups/` and rotated after 14 days.

### Download a backup to your PC
```bash
scp -i your-key.key ubuntu@YOUR_PUBLIC_IP:~/studyguide/backups/*.gz ./
```

============================================================
## PART 8 — Updating the Bot Later
============================================================

```bash
cd ~/studyguide
nano bot.py                       # make changes / paste new version
sudo systemctl restart studyguide
```

Because all content (messages, links, classes, subjects, practice sets) is stored in the
**database and edited from the in-bot admin panel**, you rarely need to touch the code.

============================================================
## Environment Variables Reference
============================================================

| Variable | Required | Description |
|----------|----------|-------------|
| BOT_TOKEN | Yes | Telegram bot token from BotFather |
| ADMIN_USER_ID | Yes* | Your numeric Telegram user ID |
| ADMIN_USERNAME | Yes* | Admin username without @ |
| DB_PATH | Recommended | Absolute path to SQLite file |
| WEBHOOK_URL | No | Leave EMPTY on Oracle (polling). Set only for Render/Koyeb |
| WEBHOOK_PORT | No | Webhook port (default 8080) |
| WEBHOOK_PATH | No | Webhook path (default /webhook) |

*At least one of ADMIN_USER_ID or ADMIN_USERNAME must be set.

============================================================
## Troubleshooting
============================================================

- **Bot not responding:** `sudo systemctl status studyguide` and `sudo journalctl -u studyguide -n 50`.
- **"TelegramConflictError":** another instance is polling. Stop duplicates / old webhook is auto-cleared on start.
- **Permission errors on DB:** ensure the folder is owned by ubuntu: `sudo chown -R ubuntu:ubuntu ~/studyguide`.
- **Changes not applied:** always run `sudo systemctl restart studyguide` after editing `bot.py` or `.env`.

## Notes

- WAL mode keeps the DB safe against crashes/power loss. You may see `studyguide.db-wal` / `-shm` files — that is normal.
- Files are stored only as Telegram file_ids. No files are ever written to disk.
- 100% free forever on Oracle Always Free — the database never resets.
