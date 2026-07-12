#!/usr/bin/env python3
"""
StudyGuide Telegram Bot
Production-ready bot using Aiogram 3.x, SQLite, and Telegram native file storage.
"""

import os
import sys
import logging
import sqlite3
import asyncio
from datetime import datetime, date
from typing import Optional, List
from contextlib import contextmanager

from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError

from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class Config:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMIN_USER_ID: Optional[int] = None
    ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "shreeakash").lstrip("@")
    DB_PATH: str = os.getenv("DB_PATH", "studyguide.db")
    WEBHOOK_URL: Optional[str] = os.getenv("WEBHOOK_URL")
    WEBHOOK_PORT: int = int(os.getenv("WEBHOOK_PORT") or os.getenv("PORT") or "8080")
    WEBHOOK_PATH: str = os.getenv("WEBHOOK_PATH", "/webhook")

    def __init__(self):
        try:
            self.ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0")) or None
        except ValueError:
            self.ADMIN_USER_ID = None


config = Config()

if not config.BOT_TOKEN:
    logger.error("BOT_TOKEN is required. Please set it in .env file.")
    sys.exit(1)


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.init_db()

    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        # WAL mode = safer against crashes/power loss + better concurrency (ideal for VPS)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA busy_timeout=30000;")
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    joined_at TEXT
                );

                CREATE TABLE IF NOT EXISTS classes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE,
                    display_name TEXT,
                    sort_order INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS class_links (
                    class_id INTEGER PRIMARY KEY,
                    group_link TEXT DEFAULT '',
                    welcome_message TEXT DEFAULT '',
                    FOREIGN KEY (class_id) REFERENCES classes(id)
                );

                CREATE TABLE IF NOT EXISTS subjects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    class_id INTEGER,
                    name TEXT,
                    FOREIGN KEY (class_id) REFERENCES classes(id)
                );

                CREATE TABLE IF NOT EXISTS practice_sets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    class_id INTEGER,
                    subject_id INTEGER,
                    file_id TEXT,
                    file_type TEXT,
                    caption TEXT,
                    uploaded_at TEXT,
                    FOREIGN KEY (class_id) REFERENCES classes(id),
                    FOREIGN KEY (subject_id) REFERENCES subjects(id)
                );

                CREATE TABLE IF NOT EXISTS notes_links (
                    class_id INTEGER PRIMARY KEY,
                    group_link TEXT DEFAULT '',
                    FOREIGN KEY (class_id) REFERENCES classes(id)
                );

                CREATE TABLE IF NOT EXISTS messages (
                    key TEXT PRIMARY KEY,
                    text TEXT
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );

                CREATE TABLE IF NOT EXISTS broadcast_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_preview TEXT,
                    total_users INTEGER,
                    success INTEGER,
                    failed INTEGER,
                    sent_at TEXT
                );
            """)
            self._seed_defaults(cursor)

    def _seed_defaults(self, cursor):
        classes = [("9", "Class 9", 1), ("10", "Class 10", 2),
                   ("11", "Class 11", 3), ("12", "Class 12", 4)]
        for name, display, order in classes:
            cursor.execute(
                "INSERT OR IGNORE INTO classes (name, display_name, sort_order) VALUES (?, ?, ?)",
                (name, display, order),
            )
            cursor.execute(
                "INSERT OR IGNORE INTO class_links (class_id) SELECT id FROM classes WHERE name = ?",
                (name,),
            )
            cursor.execute(
                "INSERT OR IGNORE INTO notes_links (class_id) SELECT id FROM classes WHERE name = ?",
                (name,),
            )

        default_messages = {
            "welcome": """📚 StudyGuide Bot-এ তোমাকে স্বাগতম! 🎓

হ্যালো শিক্ষার্থী! 👋

আমি তোমার StudyGuide Bot 🤖

তোমার ক্লাস অনুযায়ী স্টাডি গ্রুপ, প্র্যাকটিস সেট, নোটস এবং গুরুত্বপূর্ণ স্টাডি রিসোর্স খুঁজে পেতে আমি সাহায্য করবো।

✨ নিচের মেনু থেকে প্রয়োজনীয় অপশন নির্বাচন করো।

📖 Study Materials
📝 Practice Sets
🎯 Official Study Groups
🎥 PW Lecture Support

🚀 Learn • Practice • Improve

📚 Powered By StudyGuide""",
            "about": """ℹ️ StudyGuide Bot

এই বটটি শিক্ষার্থীদের জন্য তৈরি।

এখানে তুমি পাবে:

📚 Study Groups
📝 Practice Sets
📖 Notes
🎥 Learning Resources

শুভকামনা রইলো। 🌟""",
            "study_group": """📢 Official Discussion Group

এটি আমাদের অফিসিয়াল স্টুডেন্ট ডিসকাশন গ্রুপ।

তুমি এখানে প্রশ্ন করতে, আলোচনা করতে এবং অন্যান্য শিক্ষার্থীদের সাথে যুক্ত হতে পারো।

👇👇👇

@PW_BANGLA_ZONE""",
            "pw_lectures": """🎥 PW Lectures সংক্রান্ত তথ্য

PW Lecture অথবা Course নিতে চাইলে নিচের ইউজারনেমে যোগাযোগ করো।

👤 @shreeakash

ধন্যবাদ। 😊""",
            "support_team": """🛠 Support Team

যেকোনো সমস্যা বা প্রশ্নের জন্য যোগাযোগ করো।

👤 @shreeakash

আমরা দ্রুত সাহায্য করার চেষ্টা করবো।""",
        }
        for key, text in default_messages.items():
            cursor.execute(
                "INSERT OR IGNORE INTO messages (key, text) VALUES (?, ?)",
                (key, text),
            )

        cursor.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            ("admin_username", "shreeakash"),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            ("study_group_link", "@PW_BANGLA_ZONE"),
        )

    def add_user(self, user_id: int, username: Optional[str], first_name: Optional[str],
                 last_name: Optional[str]):
        with self.get_connection() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO users (user_id, username, first_name, last_name, joined_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (user_id, username, first_name, last_name, datetime.now().isoformat()),
            )

    def get_total_users(self) -> int:
        with self.get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) FROM users").fetchone()
            return row[0] if row else 0

    def get_today_users(self) -> int:
        today = date.today().isoformat()
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM users WHERE joined_at LIKE ?", (f"{today}%",)
            ).fetchone()
            return row[0] if row else 0

    def get_all_user_ids(self) -> List[int]:
        with self.get_connection() as conn:
            rows = conn.execute("SELECT user_id FROM users").fetchall()
            return [row[0] for row in rows]

    def get_classes(self) -> List[sqlite3.Row]:
        with self.get_connection() as conn:
            return conn.execute(
                "SELECT * FROM classes ORDER BY sort_order"
            ).fetchall()

    def get_class(self, class_id: int) -> Optional[sqlite3.Row]:
        with self.get_connection() as conn:
            return conn.execute(
                "SELECT * FROM classes WHERE id = ?", (class_id,)
            ).fetchone()

    def add_class(self, name: str, display_name: str) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO classes (name, display_name, sort_order) VALUES (?, ?, ?)",
                (name, display_name, 99),
            )
            class_id = cursor.lastrowid
            cursor.execute(
                "INSERT OR IGNORE INTO class_links (class_id) VALUES (?)", (class_id,)
            )
            cursor.execute(
                "INSERT OR IGNORE INTO notes_links (class_id) VALUES (?)", (class_id,)
            )
            return class_id

    def delete_class(self, class_id: int):
        with self.get_connection() as conn:
            conn.execute("DELETE FROM practice_sets WHERE class_id = ?", (class_id,))
            conn.execute("DELETE FROM subjects WHERE class_id = ?", (class_id,))
            conn.execute("DELETE FROM class_links WHERE class_id = ?", (class_id,))
            conn.execute("DELETE FROM notes_links WHERE class_id = ?", (class_id,))
            conn.execute("DELETE FROM classes WHERE id = ?", (class_id,))

    def get_class_link(self, class_id: int) -> dict:
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM class_links WHERE class_id = ?", (class_id,)
            ).fetchone()
            if row:
                return {"group_link": row["group_link"], "welcome_message": row["welcome_message"]}
            return {"group_link": "", "welcome_message": ""}

    def update_class_link(self, class_id: int, group_link: str):
        with self.get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO class_links (class_id, group_link) VALUES (?, ?)",
                (class_id, group_link),
            )

    def update_class_welcome(self, class_id: int, welcome_message: str):
        with self.get_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO class_links (class_id, group_link, welcome_message)
                   VALUES (?, COALESCE((SELECT group_link FROM class_links WHERE class_id = ?), ''), ?)""",
                (class_id, class_id, welcome_message),
            )

    def get_subjects(self, class_id: int) -> List[sqlite3.Row]:
        with self.get_connection() as conn:
            return conn.execute(
                "SELECT * FROM subjects WHERE class_id = ? ORDER BY name", (class_id,)
            ).fetchall()

    def get_subject(self, subject_id: int) -> Optional[sqlite3.Row]:
        with self.get_connection() as conn:
            return conn.execute(
                "SELECT * FROM subjects WHERE id = ?", (subject_id,)
            ).fetchone()

    def add_subject(self, class_id: int, name: str) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO subjects (class_id, name) VALUES (?, ?)",
                (class_id, name),
            )
            return cursor.lastrowid

    def delete_subject(self, subject_id: int):
        with self.get_connection() as conn:
            conn.execute("DELETE FROM practice_sets WHERE subject_id = ?", (subject_id,))
            conn.execute("DELETE FROM subjects WHERE id = ?", (subject_id,))

    def rename_subject(self, subject_id: int, new_name: str):
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE subjects SET name = ? WHERE id = ?", (new_name, subject_id)
            )

    def add_practice_set(self, class_id: int, subject_id: int, file_id: str,
                         file_type: str, caption: str) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO practice_sets (class_id, subject_id, file_id, file_type, caption, uploaded_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (class_id, subject_id, file_id, file_type, caption, datetime.now().isoformat()),
            )
            return cursor.lastrowid

    def get_practice_sets(self, class_id: int, subject_id: int) -> List[sqlite3.Row]:
        with self.get_connection() as conn:
            return conn.execute(
                "SELECT * FROM practice_sets WHERE class_id = ? AND subject_id = ? ORDER BY id DESC",
                (class_id, subject_id),
            ).fetchall()

    def get_practice_set(self, paper_id: int) -> Optional[sqlite3.Row]:
        with self.get_connection() as conn:
            return conn.execute(
                "SELECT * FROM practice_sets WHERE id = ?", (paper_id,)
            ).fetchone()

    def update_practice_set_file(self, paper_id: int, file_id: str, file_type: str):
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE practice_sets SET file_id = ?, file_type = ? WHERE id = ?",
                (file_id, file_type, paper_id),
            )

    def update_practice_set_caption(self, paper_id: int, caption: str):
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE practice_sets SET caption = ? WHERE id = ?", (caption, paper_id)
            )

    def delete_practice_set(self, paper_id: int):
        with self.get_connection() as conn:
            conn.execute("DELETE FROM practice_sets WHERE id = ?", (paper_id,))

    def count_practice_sets(self) -> int:
        with self.get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) FROM practice_sets").fetchone()
            return row[0] if row else 0

    def get_notes_link(self, class_id: int) -> str:
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT group_link FROM notes_links WHERE class_id = ?", (class_id,)
            ).fetchone()
            return row["group_link"] if row else ""

    def set_notes_link(self, class_id: int, group_link: str):
        with self.get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO notes_links (class_id, group_link) VALUES (?, ?)",
                (class_id, group_link),
            )

    def delete_notes_link(self, class_id: int):
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE notes_links SET group_link = '' WHERE class_id = ?", (class_id,)
            )

    def get_message(self, key: str) -> str:
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT text FROM messages WHERE key = ?", (key,)
            ).fetchone()
            return row["text"] if row else ""

    def set_message(self, key: str, text: str):
        with self.get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO messages (key, text) VALUES (?, ?)",
                (key, text),
            )

    def get_setting(self, key: str, default: str = "") -> str:
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str):
        with self.get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )

    def log_broadcast(self, preview: str, total: int, success: int, failed: int):
        with self.get_connection() as conn:
            conn.execute(
                """INSERT INTO broadcast_logs (message_preview, total_users, success, failed, sent_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (preview, total, success, failed, datetime.now().isoformat()),
            )

    def get_total_broadcasts(self) -> int:
        with self.get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) FROM broadcast_logs").fetchone()
            return row[0] if row else 0


db = Database(config.DB_PATH)


class BroadcastState(StatesGroup):
    content = State()
    confirm = State()


class ClassManageState(StatesGroup):
    add = State()
    delete = State()
    edit_link = State()
    edit_welcome = State()


class SubjectManageState(StatesGroup):
    add = State()
    rename = State()


class PracticeSetState(StatesGroup):
    waiting_file_add = State()
    waiting_file_replace = State()
    waiting_caption = State()
    edit_caption = State()


class NotesState(StatesGroup):
    waiting_link = State()


class TextEditState(StatesGroup):
    waiting_text = State()


class SettingState(StatesGroup):
    waiting_value = State()


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Study Group", callback_data="study_group")],
        [InlineKeyboardButton(text="🏫 Classes", callback_data="classes")],
        [InlineKeyboardButton(text="📝 Practice Set Papers", callback_data="practice_sets")],
        [InlineKeyboardButton(text="📖 Notes", callback_data="notes")],
        [InlineKeyboardButton(text="🎥 PW Lectures", callback_data="pw_lectures")],
        [InlineKeyboardButton(text="🛠 Support Team", callback_data="support_team")],
        [InlineKeyboardButton(text="ℹ️ About", callback_data="about")],
    ])


def back_menu_kb(back_callback: str = "main_menu",
                 menu_callback: str = "main_menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Back", callback_data=back_callback),
         InlineKeyboardButton(text="🏠 Main Menu", callback_data=menu_callback)]
    ])


def admin_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Statistics", callback_data="admin_stats"),
         InlineKeyboardButton(text="📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="📢 Manage Groups", callback_data="admin_groups")],
        [InlineKeyboardButton(text="🏫 Manage Classes", callback_data="admin_classes")],
        [InlineKeyboardButton(text="📝 Manage Practice Sets", callback_data="admin_practice")],
        [InlineKeyboardButton(text="📖 Manage Notes", callback_data="admin_notes")],
        [InlineKeyboardButton(text="🎥 Manage PW Lectures", callback_data="admin_pw")],
        [InlineKeyboardButton(text="🛠 Manage Support Team", callback_data="admin_support")],
        [InlineKeyboardButton(text="💬 Manage Messages", callback_data="admin_messages")],
        [InlineKeyboardButton(text="⚙️ Settings", callback_data="admin_settings")],
        [InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu")],
    ])


def classes_kb(classes: List[sqlite3.Row], callback_prefix: str,
               back_callback: str = "main_menu") -> InlineKeyboardMarkup:
    buttons = []
    for cls in classes:
        buttons.append([InlineKeyboardButton(
            text=cls["display_name"],
            callback_data=f"{callback_prefix}:{cls['id']}"
        )])
    buttons.append([
        InlineKeyboardButton(text="⬅️ Back", callback_data=back_callback),
        InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def subjects_kb(subjects: List[sqlite3.Row], class_id: int,
                callback_prefix: str, back_callback: str = "practice_sets") -> InlineKeyboardMarkup:
    buttons = []
    for sub in subjects:
        buttons.append([InlineKeyboardButton(
            text=sub["name"],
            callback_data=f"{callback_prefix}:{class_id}:{sub['id']}"
        )])
    buttons.append([
        InlineKeyboardButton(text="⬅️ Back", callback_data=back_callback),
        InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def is_admin(user) -> bool:
    if config.ADMIN_USER_ID and user.id == config.ADMIN_USER_ID:
        return True
    username = (user.username or "").lower().lstrip("@")
    admin_username = config.ADMIN_USERNAME.lower().lstrip("@")
    if admin_username and username == admin_username:
        return True
    return False


async def safe_edit_text(callback: CallbackQuery, text: str, reply_markup=None,
                         parse_mode=ParseMode.HTML):
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception:
        await callback.message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)


bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


@dp.message(CommandStart())
async def cmd_start(message: Message):
    db.add_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        message.from_user.last_name,
    )
    welcome_text = db.get_message("welcome")
    await message.answer(welcome_text, reply_markup=main_menu_kb())


@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user):
        await message.answer("⛔ You are not authorized to access the admin panel.")
        return
    await message.answer("🔧 Admin Panel", reply_markup=admin_panel_kb())


@dp.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    welcome_text = db.get_message("welcome")
    await safe_edit_text(callback, welcome_text, reply_markup=main_menu_kb())
    await callback.answer()


@dp.callback_query(F.data == "study_group")
async def cb_study_group(callback: CallbackQuery):
    text = db.get_message("study_group")
    await safe_edit_text(callback, text, reply_markup=back_menu_kb("main_menu"))
    await callback.answer()


@dp.callback_query(F.data == "classes")
async def cb_classes(callback: CallbackQuery):
    classes = db.get_classes()
    await safe_edit_text(
        callback,
        "🏫 তোমার ক্লাস নির্বাচন করো:",
        reply_markup=classes_kb(classes, "class_detail", "main_menu")
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("class_detail:"))
async def cb_class_detail(callback: CallbackQuery):
    class_id = int(callback.data.split(":")[1])
    cls = db.get_class(class_id)
    if not cls:
        await callback.answer("Class not found.", show_alert=True)
        return
    link_data = db.get_class_link(class_id)
    link = link_data.get("group_link") or "Not set"
    welcome = link_data.get("welcome_message") or f"🔗 {cls['display_name']} Official Group"
    text = f"{welcome}\n\n{link}\n\n👆👆👆\n\nএটি তোমাদের অফিসিয়াল স্টাডি গ্রুপ।\n\nতোমাকে এই গ্রুপে স্বাগতম। 😊"
    await safe_edit_text(callback, text, reply_markup=back_menu_kb("classes", "main_menu"))
    await callback.answer()


@dp.callback_query(F.data == "practice_sets")
async def cb_practice_sets(callback: CallbackQuery):
    classes = db.get_classes()
    await safe_edit_text(
        callback,
        "📝 প্র্যাকটিস সেট পেপারের জন্য ক্লাস নির্বাচন করো:",
        reply_markup=classes_kb(classes, "practice_class", "main_menu")
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("practice_class:"))
async def cb_practice_class(callback: CallbackQuery):
    class_id = int(callback.data.split(":")[1])
    subjects = db.get_subjects(class_id)
    if not subjects:
        await safe_edit_text(
            callback,
            "এই ক্লাসের জন্য কোনো সাবজেক্ট যোগ করা হয়নি।",
            reply_markup=back_menu_kb("practice_sets", "main_menu")
        )
        await callback.answer()
        return
    await safe_edit_text(
        callback,
        "📚 সাবজেক্ট নির্বাচন করো:",
        reply_markup=subjects_kb(subjects, class_id, "practice_subject", "practice_sets")
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("practice_subject:"))
async def cb_practice_subject(callback: CallbackQuery):
    parts = callback.data.split(":")
    class_id = int(parts[1])
    subject_id = int(parts[2])
    papers = db.get_practice_sets(class_id, subject_id)
    if not papers:
        await safe_edit_text(
            callback,
            "এই সাবজেক্টের জন্য এখনো কোনো প্র্যাকটিস সেট আপলোড করা হয়নি।",
            reply_markup=back_menu_kb(f"practice_class:{class_id}", "main_menu")
        )
        await callback.answer()
        return

    await callback.answer("প্র্যাকটিস সেট পাঠানো হচ্ছে...")
    for paper in papers:
        caption = paper["caption"] or ""
        try:
            if paper["file_type"] == "photo":
                await callback.message.answer_photo(paper["file_id"], caption=caption)
            else:
                await callback.message.answer_document(paper["file_id"], caption=caption)
        except Exception as e:
            logger.error(f"Failed to send paper {paper['id']}: {e}")

    await callback.message.answer(
        "✅ উপরে প্র্যাকটিস সেট পাঠানো হয়েছে।",
        reply_markup=back_menu_kb(f"practice_class:{class_id}", "main_menu")
    )


@dp.callback_query(F.data == "notes")
async def cb_notes(callback: CallbackQuery):
    classes = [c for c in db.get_classes() if c["name"] in ("11", "12")]
    if not classes:
        classes = db.get_classes()
    await safe_edit_text(
        callback,
        "📖 নোটস পেতে ক্লাস নির্বাচন করো:",
        reply_markup=classes_kb(classes, "notes_class", "main_menu")
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("notes_class:"))
async def cb_notes_class(callback: CallbackQuery):
    class_id = int(callback.data.split(":")[1])
    link = db.get_notes_link(class_id)
    text = f"📖 Notes Group\n\n{link}\n\nনোটস পাওয়ার জন্য গ্রুপে যোগদান করো।"
    await safe_edit_text(callback, text, reply_markup=back_menu_kb("notes", "main_menu"))
    await callback.answer()


@dp.callback_query(F.data == "pw_lectures")
async def cb_pw_lectures(callback: CallbackQuery):
    text = db.get_message("pw_lectures")
    await safe_edit_text(callback, text, reply_markup=back_menu_kb("main_menu"))
    await callback.answer()


@dp.callback_query(F.data == "support_team")
async def cb_support_team(callback: CallbackQuery):
    text = db.get_message("support_team")
    await safe_edit_text(callback, text, reply_markup=back_menu_kb("main_menu"))
    await callback.answer()


@dp.callback_query(F.data == "about")
async def cb_about(callback: CallbackQuery):
    text = db.get_message("about")
    await safe_edit_text(callback, text, reply_markup=back_menu_kb("main_menu"))
    await callback.answer()


@dp.callback_query(F.data == "admin_stats")
async def cb_admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user):
        await callback.answer("⛔ Unauthorized", show_alert=True)
        return
    total_users = db.get_total_users()
    today_users = db.get_today_users()
    total_broadcasts = db.get_total_broadcasts()
    total_papers = db.count_practice_sets()
    text = f"""📊 Statistics

👥 Total Users: {total_users}
📅 Today's Users: {today_users}
📢 Total Broadcasts: {total_broadcasts}
📝 Total Practice Sets: {total_papers}"""
    await safe_edit_text(callback, text, reply_markup=back_menu_kb("admin_panel", "main_menu"))
    await callback.answer()


@dp.callback_query(F.data == "admin_broadcast")
async def cb_admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user):
        await callback.answer("⛔ Unauthorized", show_alert=True)
        return
    await state.set_state(BroadcastState.content)
    text = "📢 Broadcast করতে চাইলে এখন মেসেজ পাঠাও।\n\nসাপোর্টেড: Text, Photo, Document, Photo + Caption, Document + Caption"
    await safe_edit_text(callback, text, reply_markup=back_menu_kb("admin_panel", "main_menu"))
    await callback.answer()


@dp.message(BroadcastState.content)
async def broadcast_content(message: Message, state: FSMContext):
    if not is_admin(message.from_user):
        return
    content_type = None
    content_data = {}
    if message.text:
        content_type = "text"
        content_data["text"] = message.text
    elif message.photo:
        content_type = "photo"
        content_data["file_id"] = message.photo[-1].file_id
        content_data["caption"] = message.caption or ""
    elif message.document:
        content_type = "document"
        content_data["file_id"] = message.document.file_id
        content_data["caption"] = message.caption or ""
    else:
        await message.answer("❌ এই ধরনের কন্টেন্ট সাপোর্টেড নয়। আবার চেষ্টা করো।")
        return

    await state.update_data(content_type=content_type, content_data=content_data)
    await state.set_state(BroadcastState.confirm)

    preview = content_data.get("text") or content_data.get("caption") or "[Media]"
    await message.answer(
        f"📢 Broadcast Preview:\n\n{preview[:500]}\n\nপাঠাতে চাইলে '✅ Confirm' চাপো।",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Confirm Broadcast", callback_data="broadcast_confirm")],
            [InlineKeyboardButton(text="❌ Cancel", callback_data="admin_broadcast")],
        ])
    )


@dp.callback_query(F.data == "broadcast_confirm", BroadcastState.confirm)
async def cb_broadcast_confirm(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user):
        await callback.answer("⛔ Unauthorized", show_alert=True)
        return
    data = await state.get_data()
    content_type = data.get("content_type")
    content_data = data.get("content_data", {})
    user_ids = db.get_all_user_ids()
    success = 0
    failed = 0

    preview = content_data.get("text") or content_data.get("caption") or "[Media]"

    async def send_one(uid: int) -> bool:
        if content_type == "text":
            await bot.send_message(uid, content_data["text"])
        elif content_type == "photo":
            await bot.send_photo(uid, content_data["file_id"], caption=content_data.get("caption"))
        elif content_type == "document":
            await bot.send_document(uid, content_data["file_id"], caption=content_data.get("caption"))
        return True

    for uid in user_ids:
        try:
            await send_one(uid)
            success += 1
            # ~25 messages/sec is Telegram's safe broadcast limit
            await asyncio.sleep(0.04)
        except TelegramRetryAfter as e:
            # Hit flood limit: wait the required time, then retry once
            logger.warning(f"Flood limit, sleeping {e.retry_after}s")
            await asyncio.sleep(e.retry_after)
            try:
                await send_one(uid)
                success += 1
            except Exception as e2:
                logger.error(f"Broadcast retry failed to {uid}: {e2}")
                failed += 1
        except TelegramForbiddenError:
            # User blocked the bot / deactivated account
            failed += 1
        except Exception as e:
            logger.error(f"Broadcast failed to {uid}: {e}")
            failed += 1

    db.log_broadcast(preview[:200], len(user_ids), success, failed)
    await state.clear()
    await safe_edit_text(
        callback,
        f"✅ Broadcast Complete!\n\n✓ Success: {success}\n✗ Failed: {failed}",
        reply_markup=admin_panel_kb()
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_panel")
async def cb_admin_panel(callback: CallbackQuery):
    if not is_admin(callback.from_user):
        await callback.answer("⛔ Unauthorized", show_alert=True)
        return
    await safe_edit_text(callback, "🔧 Admin Panel", reply_markup=admin_panel_kb())
    await callback.answer()


@dp.callback_query(F.data == "admin_classes")
async def cb_admin_classes(callback: CallbackQuery):
    if not is_admin(callback.from_user):
        await callback.answer("⛔ Unauthorized", show_alert=True)
        return
    classes = db.get_classes()
    buttons = []
    for cls in classes:
        buttons.append([InlineKeyboardButton(
            text=f"✏️ {cls['display_name']}",
            callback_data=f"admin_class_edit:{cls['id']}"
        )])
    buttons.extend([
        [InlineKeyboardButton(text="➕ Add Class", callback_data="admin_class_add"),
         InlineKeyboardButton(text="🗑 Delete Class", callback_data="admin_class_delete")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="admin_panel"),
         InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu")],
    ])
    await safe_edit_text(callback, "🏫 Manage Classes", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@dp.callback_query(F.data == "admin_class_add")
async def cb_admin_class_add(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user):
        return
    await state.set_state(ClassManageState.add)
    await safe_edit_text(
        callback,
        "➕ নতুন ক্লাস যোগ করতে Format:\n\nClassName|Display Name\n\nExample: 11|Class 11",
        reply_markup=back_menu_kb("admin_classes", "main_menu")
    )
    await callback.answer()


@dp.message(ClassManageState.add)
async def add_class_message(message: Message, state: FSMContext):
    if not is_admin(message.from_user):
        return
    parts = message.text.split("|", 1)
    name = parts[0].strip()
    display = parts[1].strip() if len(parts) > 1 else name
    db.add_class(name, display)
    await state.clear()
    await message.answer(f"✅ ক্লাস '{display}' যোগ করা হয়েছে।", reply_markup=back_menu_kb("admin_classes", "main_menu"))


@dp.callback_query(F.data == "admin_class_delete")
async def cb_admin_class_delete(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user):
        return
    await state.set_state(ClassManageState.delete)
    classes = db.get_classes()
    buttons = []
    for cls in classes:
        buttons.append([InlineKeyboardButton(
            text=f"🗑 {cls['display_name']}",
            callback_data=f"admin_class_del:{cls['id']}"
        )])
    buttons.append([
        InlineKeyboardButton(text="⬅️ Back", callback_data="admin_classes"),
        InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu"),
    ])
    await safe_edit_text(callback, "🗑 মুছে ফেলতে ক্লাস নির্বাচন করো:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_class_del:"))
async def cb_admin_class_del(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user):
        return
    class_id = int(callback.data.split(":")[1])
    db.delete_class(class_id)
    await state.clear()
    await callback.answer("✅ ক্লাস মুছে ফেলা হয়েছে।", show_alert=True)
    await cb_admin_classes(callback)


@dp.callback_query(F.data.startswith("admin_class_edit:"))
async def cb_admin_class_edit(callback: CallbackQuery):
    if not is_admin(callback.from_user):
        return
    class_id = int(callback.data.split(":")[1])
    cls = db.get_class(class_id)
    link_data = db.get_class_link(class_id)
    text = f"🏫 {cls['display_name']}\n\n🔗 Group Link: {link_data['group_link']}\n📝 Welcome: {link_data['welcome_message'][:100]}"
    buttons = [
        [InlineKeyboardButton(text="✏️ Edit Group Link", callback_data=f"admin_class_link:{class_id}")],
        [InlineKeyboardButton(text="📝 Edit Welcome Message", callback_data=f"admin_class_welcome:{class_id}")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="admin_classes"),
         InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu")],
    ]
    await safe_edit_text(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_class_link:"))
async def cb_admin_class_link(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user):
        return
    class_id = int(callback.data.split(":")[1])
    await state.set_state(ClassManageState.edit_link)
    await state.update_data(edit_class_id=class_id)
    await safe_edit_text(
        callback,
        "🔗 নতুন গ্রুপ লিংক পাঠাও:",
        reply_markup=back_menu_kb(f"admin_class_edit:{class_id}", "main_menu")
    )
    await callback.answer()


@dp.message(ClassManageState.edit_link)
async def edit_class_link_message(message: Message, state: FSMContext):
    if not is_admin(message.from_user):
        return
    data = await state.get_data()
    class_id = data.get("edit_class_id")
    db.update_class_link(class_id, message.text.strip())
    await state.clear()
    await message.answer("✅ গ্রুপ লিংক আপডেট করা হয়েছে।", reply_markup=back_menu_kb("admin_classes", "main_menu"))


@dp.callback_query(F.data.startswith("admin_class_welcome:"))
async def cb_admin_class_welcome(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user):
        return
    class_id = int(callback.data.split(":")[1])
    await state.set_state(ClassManageState.edit_welcome)
    await state.update_data(edit_class_id=class_id)
    await safe_edit_text(
        callback,
        "📝 নতুন Welcome Message পাঠাও:",
        reply_markup=back_menu_kb(f"admin_class_edit:{class_id}", "main_menu")
    )
    await callback.answer()


@dp.message(ClassManageState.edit_welcome)
async def edit_class_welcome_message(message: Message, state: FSMContext):
    if not is_admin(message.from_user):
        return
    data = await state.get_data()
    class_id = data.get("edit_class_id")
    db.update_class_welcome(class_id, message.text.strip())
    await state.clear()
    await message.answer("✅ Welcome Message আপডেট করা হয়েছে।", reply_markup=back_menu_kb("admin_classes", "main_menu"))


@dp.callback_query(F.data == "admin_practice")
async def cb_admin_practice(callback: CallbackQuery):
    if not is_admin(callback.from_user):
        await callback.answer("⛔ Unauthorized", show_alert=True)
        return
    classes = db.get_classes()
    buttons = []
    for cls in classes:
        buttons.append([InlineKeyboardButton(
            text=f"📝 {cls['display_name']}",
            callback_data=f"admin_practice_class:{cls['id']}"
        )])
    buttons.append([
        InlineKeyboardButton(text="⬅️ Back", callback_data="admin_panel"),
        InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu"),
    ])
    await safe_edit_text(callback, "📝 Manage Practice Sets - ক্লাস নির্বাচন করো:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_practice_class:"))
async def cb_admin_practice_class(callback: CallbackQuery):
    if not is_admin(callback.from_user):
        return
    class_id = int(callback.data.split(":")[1])
    subjects = db.get_subjects(class_id)
    buttons = []
    for sub in subjects:
        buttons.append([InlineKeyboardButton(
            text=f"📂 {sub['name']}",
            callback_data=f"admin_practice_subject:{class_id}:{sub['id']}"
        )])
    buttons.extend([
        [InlineKeyboardButton(text="➕ Add Subject", callback_data=f"admin_subject_add:{class_id}"),
         InlineKeyboardButton(text="🗑 Delete Subject", callback_data=f"admin_subject_delete:{class_id}")],
        [InlineKeyboardButton(text="✏️ Rename Subject", callback_data=f"admin_subject_rename:{class_id}")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="admin_practice"),
         InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu")],
    ])
    await safe_edit_text(callback, "📝 সাবজেক্ট ম্যানেজ করো:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_subject_add:"))
async def cb_admin_subject_add(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user):
        return
    class_id = int(callback.data.split(":")[1])
    await state.set_state(SubjectManageState.add)
    await state.update_data(subject_class_id=class_id)
    await safe_edit_text(
        callback,
        "➕ সাবজেক্টের নাম পাঠাও:",
        reply_markup=back_menu_kb(f"admin_practice_class:{class_id}", "main_menu")
    )
    await callback.answer()


@dp.message(SubjectManageState.add)
async def add_subject_message(message: Message, state: FSMContext):
    if not is_admin(message.from_user):
        return
    data = await state.get_data()
    class_id = data.get("subject_class_id")
    db.add_subject(class_id, message.text.strip())
    await state.clear()
    await message.answer("✅ সাবজেক্ট যোগ করা হয়েছে।", reply_markup=back_menu_kb(f"admin_practice_class:{class_id}", "main_menu"))


@dp.callback_query(F.data.startswith("admin_subject_delete:"))
async def cb_admin_subject_delete(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user):
        return
    class_id = int(callback.data.split(":")[1])
    subjects = db.get_subjects(class_id)
    buttons = []
    for sub in subjects:
        buttons.append([InlineKeyboardButton(
            text=f"🗑 {sub['name']}",
            callback_data=f"admin_subject_del:{sub['id']}"
        )])
    buttons.append([
        InlineKeyboardButton(text="⬅️ Back", callback_data=f"admin_practice_class:{class_id}"),
        InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu"),
    ])
    await safe_edit_text(callback, "🗑 মুছে ফেলতে সাবজেক্ট নির্বাচন করো:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_subject_del:"))
async def cb_admin_subject_del(callback: CallbackQuery):
    if not is_admin(callback.from_user):
        return
    subject_id = int(callback.data.split(":")[1])
    db.delete_subject(subject_id)
    await callback.answer("✅ সাবজেক্ট মুছে ফেলা হয়েছে।", show_alert=True)
    await cb_admin_practice_class(callback)


@dp.callback_query(F.data.startswith("admin_subject_rename:"))
async def cb_admin_subject_rename(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user):
        return
    class_id = int(callback.data.split(":")[1])
    subjects = db.get_subjects(class_id)
    buttons = []
    for sub in subjects:
        buttons.append([InlineKeyboardButton(
            text=f"✏️ {sub['name']}",
            callback_data=f"admin_subject_ren:{sub['id']}"
        )])
    buttons.append([
        InlineKeyboardButton(text="⬅️ Back", callback_data=f"admin_practice_class:{class_id}"),
        InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu"),
    ])
    await safe_edit_text(callback, "✏️ রিনেম করতে সাবজেক্ট নির্বাচন করো:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_subject_ren:"))
async def cb_admin_subject_ren(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user):
        return
    subject_id = int(callback.data.split(":")[1])
    await state.set_state(SubjectManageState.rename)
    await state.update_data(rename_subject_id=subject_id)
    sub = db.get_subject(subject_id)
    await safe_edit_text(
        callback,
        f"✏️ '{sub['name']}'-এর নতুন নাম পাঠাও:",
        reply_markup=back_menu_kb(f"admin_practice_class:{sub['class_id']}", "main_menu")
    )
    await callback.answer()


@dp.message(SubjectManageState.rename)
async def rename_subject_message(message: Message, state: FSMContext):
    if not is_admin(message.from_user):
        return
    data = await state.get_data()
    subject_id = data.get("rename_subject_id")
    sub = db.get_subject(subject_id)
    db.rename_subject(subject_id, message.text.strip())
    await state.clear()
    await message.answer("✅ সাবজেক্ট রিনেম করা হয়েছে।", reply_markup=back_menu_kb(f"admin_practice_class:{sub['class_id']}", "main_menu"))


@dp.callback_query(F.data.startswith("admin_practice_subject:"))
async def cb_admin_practice_subject(callback: CallbackQuery):
    if not is_admin(callback.from_user):
        return
    parts = callback.data.split(":")
    class_id = int(parts[1])
    subject_id = int(parts[2])
    papers = db.get_practice_sets(class_id, subject_id)
    buttons = []
    for paper in papers:
        label = f"{'🖼' if paper['file_type']=='photo' else '📄'} Paper #{paper['id']}"
        buttons.append([InlineKeyboardButton(
            text=label,
            callback_data=f"admin_paper:{paper['id']}"
        )])
    buttons.extend([
        [InlineKeyboardButton(text="➕ Add Paper", callback_data=f"admin_paper_add:{class_id}:{subject_id}")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data=f"admin_practice_class:{class_id}"),
         InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu")],
    ])
    text = f"📝 Papers ({len(papers)} found)"
    await safe_edit_text(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_paper_add:"))
async def cb_admin_paper_add(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user):
        return
    parts = callback.data.split(":")
    class_id = int(parts[1])
    subject_id = int(parts[2])
    await state.set_state(PracticeSetState.waiting_file_add)
    await state.update_data(paper_class_id=class_id, paper_subject_id=subject_id)
    await safe_edit_text(
        callback,
        "📤 প্র্যাকটিস সেটের Photo অথবা PDF আপলোড করো:",
        reply_markup=back_menu_kb(f"admin_practice_subject:{class_id}:{subject_id}", "main_menu")
    )
    await callback.answer()


@dp.message(PracticeSetState.waiting_file_add)
async def add_paper_file(message: Message, state: FSMContext):
    if not is_admin(message.from_user):
        return
    file_id = None
    file_type = None
    if message.photo:
        file_id = message.photo[-1].file_id
        file_type = "photo"
    elif message.document:
        file_id = message.document.file_id
        file_type = "document"
    else:
        await message.answer("❌ অনুগ্রহ করে Photo অথবা PDF আপলোড করো।")
        return

    await state.update_data(file_id=file_id, file_type=file_type)
    await state.set_state(PracticeSetState.waiting_caption)
    await message.answer(
        "✅ ফাইল গ্রহণ করা হয়েছে। এখন Caption লিখো (যদি না চাও 'skip' লিখো):",
        reply_markup=back_menu_kb("admin_panel", "main_menu")
    )


@dp.message(PracticeSetState.waiting_caption)
async def add_paper_caption(message: Message, state: FSMContext):
    if not is_admin(message.from_user):
        return
    data = await state.get_data()
    class_id = data.get("paper_class_id")
    subject_id = data.get("paper_subject_id")
    file_id = data.get("file_id")
    file_type = data.get("file_type")
    caption = "" if message.text.lower().strip() == "skip" else message.text.strip()
    db.add_practice_set(class_id, subject_id, file_id, file_type, caption)
    await state.clear()
    await message.answer(
        "✅ প্র্যাকটিস সেট আপলোড করা হয়েছে।",
        reply_markup=back_menu_kb(f"admin_practice_subject:{class_id}:{subject_id}", "main_menu")
    )


@dp.callback_query(F.data.startswith("admin_paper:"))
async def cb_admin_paper(callback: CallbackQuery):
    if not is_admin(callback.from_user):
        return
    paper_id = int(callback.data.split(":")[1])
    paper = db.get_practice_set(paper_id)
    if not paper:
        await callback.answer("Paper not found.", show_alert=True)
        return
    text = f"📝 Paper #{paper['id']}\n\nType: {paper['file_type']}\nCaption: {paper['caption'][:200]}"
    buttons = [
        [InlineKeyboardButton(text="📝 Edit Caption", callback_data=f"admin_paper_cap:{paper_id}")],
        [InlineKeyboardButton(text="🔄 Replace File", callback_data=f"admin_paper_replace:{paper_id}")],
        [InlineKeyboardButton(text="🗑 Delete Paper", callback_data=f"admin_paper_del:{paper_id}")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data=f"admin_practice_subject:{paper['class_id']}:{paper['subject_id']}"),
         InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu")],
    ]
    await safe_edit_text(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_paper_cap:"))
async def cb_admin_paper_cap(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user):
        return
    paper_id = int(callback.data.split(":")[1])
    await state.set_state(PracticeSetState.edit_caption)
    await state.update_data(edit_paper_id=paper_id)
    await safe_edit_text(
        callback,
        "📝 নতুন Caption পাঠাও:",
        reply_markup=back_menu_kb(f"admin_paper:{paper_id}", "main_menu")
    )
    await callback.answer()


@dp.message(PracticeSetState.edit_caption)
async def edit_paper_caption(message: Message, state: FSMContext):
    if not is_admin(message.from_user):
        return
    data = await state.get_data()
    paper_id = data.get("edit_paper_id")
    db.update_practice_set_caption(paper_id, message.text.strip())
    await state.clear()
    await message.answer("✅ Caption আপডেট করা হয়েছে।", reply_markup=back_menu_kb("admin_practice", "main_menu"))


@dp.callback_query(F.data.startswith("admin_paper_replace:"))
async def cb_admin_paper_replace(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user):
        return
    paper_id = int(callback.data.split(":")[1])
    await state.set_state(PracticeSetState.waiting_file_replace)
    await state.update_data(replace_paper_id=paper_id)
    await safe_edit_text(
        callback,
        "🔄 নতুন Photo অথবা PDF আপলোড করো:",
        reply_markup=back_menu_kb(f"admin_paper:{paper_id}", "main_menu")
    )
    await callback.answer()


@dp.message(PracticeSetState.waiting_file_replace)
async def replace_paper_file(message: Message, state: FSMContext):
    if not is_admin(message.from_user):
        return
    data = await state.get_data()
    replace_id = data.get("replace_paper_id")
    file_id = None
    file_type = None
    if message.photo:
        file_id = message.photo[-1].file_id
        file_type = "photo"
    elif message.document:
        file_id = message.document.file_id
        file_type = "document"
    else:
        await message.answer("❌ অনুগ্রহ করে Photo অথবা PDF আপলোড করো।")
        return
    db.update_practice_set_file(replace_id, file_id, file_type)
    await state.clear()
    await message.answer("✅ ফাইল রিপ্লেস করা হয়েছে।", reply_markup=back_menu_kb("admin_practice", "main_menu"))


@dp.callback_query(F.data.startswith("admin_paper_del:"))
async def cb_admin_paper_del(callback: CallbackQuery):
    if not is_admin(callback.from_user):
        return
    paper_id = int(callback.data.split(":")[1])
    db.delete_practice_set(paper_id)
    await callback.answer("✅ Paper মুছে ফেলা হয়েছে।", show_alert=True)
    await cb_admin_practice_subject(callback)


@dp.callback_query(F.data == "admin_notes")
async def cb_admin_notes(callback: CallbackQuery):
    if not is_admin(callback.from_user):
        await callback.answer("⛔ Unauthorized", show_alert=True)
        return
    classes = [c for c in db.get_classes() if c["name"] in ("11", "12")]
    if not classes:
        classes = db.get_classes()
    buttons = []
    for cls in classes:
        buttons.append([InlineKeyboardButton(
            text=f"📖 {cls['display_name']}",
            callback_data=f"admin_notes_class:{cls['id']}"
        )])
    buttons.append([
        InlineKeyboardButton(text="⬅️ Back", callback_data="admin_panel"),
        InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu"),
    ])
    await safe_edit_text(callback, "📖 Manage Notes", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_notes_class:"))
async def cb_admin_notes_class(callback: CallbackQuery):
    if not is_admin(callback.from_user):
        return
    class_id = int(callback.data.split(":")[1])
    cls = db.get_class(class_id)
    link = db.get_notes_link(class_id)
    text = f"📖 {cls['display_name']} Notes\n\nCurrent Link: {link}"
    buttons = [
        [InlineKeyboardButton(text="✏️ Edit Link", callback_data=f"admin_notes_edit:{class_id}")],
        [InlineKeyboardButton(text="🗑 Delete Link", callback_data=f"admin_notes_del:{class_id}")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="admin_notes"),
         InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu")],
    ]
    await safe_edit_text(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_notes_edit:"))
async def cb_admin_notes_edit(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user):
        return
    class_id = int(callback.data.split(":")[1])
    await state.set_state(NotesState.waiting_link)
    await state.update_data(notes_class_id=class_id)
    await safe_edit_text(
        callback,
        "🔗 নতুন Notes Group Link পাঠাও:",
        reply_markup=back_menu_kb(f"admin_notes_class:{class_id}", "main_menu")
    )
    await callback.answer()


@dp.message(NotesState.waiting_link)
async def edit_notes_link(message: Message, state: FSMContext):
    if not is_admin(message.from_user):
        return
    data = await state.get_data()
    class_id = data.get("notes_class_id")
    db.set_notes_link(class_id, message.text.strip())
    await state.clear()
    await message.answer("✅ Notes Link আপডেট করা হয়েছে।", reply_markup=back_menu_kb("admin_notes", "main_menu"))


@dp.callback_query(F.data.startswith("admin_notes_del:"))
async def cb_admin_notes_del(callback: CallbackQuery):
    if not is_admin(callback.from_user):
        return
    class_id = int(callback.data.split(":")[1])
    db.delete_notes_link(class_id)
    await callback.answer("✅ Notes Link মুছে ফেলা হয়েছে।", show_alert=True)
    await cb_admin_notes(callback)


@dp.callback_query(F.data == "admin_pw")
async def cb_admin_pw(callback: CallbackQuery):
    if not is_admin(callback.from_user):
        await callback.answer("⛔ Unauthorized", show_alert=True)
        return
    text = db.get_message("pw_lectures")
    buttons = [
        [InlineKeyboardButton(text="✏️ Edit Text", callback_data="admin_pw_text")],
        [InlineKeyboardButton(text="👤 Edit Username", callback_data="admin_pw_user")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="admin_panel"),
         InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu")],
    ]
    await safe_edit_text(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@dp.callback_query(F.data == "admin_pw_text")
async def cb_admin_pw_text(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user):
        return
    await state.set_state(TextEditState.waiting_text)
    await state.update_data(message_key="pw_lectures")
    await safe_edit_text(
        callback,
        "✏️ নতুন PW Lectures টেক্সট পাঠাও:",
        reply_markup=back_menu_kb("admin_pw", "main_menu")
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_pw_user")
async def cb_admin_pw_user(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user):
        return
    await state.set_state(TextEditState.waiting_text)
    await state.update_data(pw_username=True)
    await safe_edit_text(
        callback,
        "👤 নতুন Username পাঠাও (@ ছাড়া):",
        reply_markup=back_menu_kb("admin_pw", "main_menu")
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_support")
async def cb_admin_support(callback: CallbackQuery):
    if not is_admin(callback.from_user):
        await callback.answer("⛔ Unauthorized", show_alert=True)
        return
    text = db.get_message("support_team")
    buttons = [
        [InlineKeyboardButton(text="✏️ Edit Text", callback_data="admin_support_text")],
        [InlineKeyboardButton(text="👤 Edit Username", callback_data="admin_support_user")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="admin_panel"),
         InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu")],
    ]
    await safe_edit_text(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@dp.callback_query(F.data == "admin_support_text")
async def cb_admin_support_text(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user):
        return
    await state.set_state(TextEditState.waiting_text)
    await state.update_data(message_key="support_team")
    await safe_edit_text(
        callback,
        "✏️ নতুন Support Team টেক্সট পাঠাও:",
        reply_markup=back_menu_kb("admin_support", "main_menu")
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_support_user")
async def cb_admin_support_user(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user):
        return
    await state.set_state(TextEditState.waiting_text)
    await state.update_data(support_username=True)
    await safe_edit_text(
        callback,
        "👤 নতুন Username পাঠাও (@ ছাড়া):",
        reply_markup=back_menu_kb("admin_support", "main_menu")
    )
    await callback.answer()


@dp.message(TextEditState.waiting_text)
async def edit_text_message(message: Message, state: FSMContext):
    if not is_admin(message.from_user):
        return
    data = await state.get_data()
    text = message.text.strip()
    if data.get("message_key"):
        db.set_message(data["message_key"], text)
        await message.answer("✅ Message আপডেট করা হয়েছে।", reply_markup=back_menu_kb("admin_panel", "main_menu"))
    elif data.get("pw_username"):
        username = text.lstrip("@")
        current = db.get_message("pw_lectures")
        new_text = current.replace("@shreeakash", f"@{username}")
        db.set_message("pw_lectures", new_text)
        await message.answer("✅ PW Lectures Username আপডেট করা হয়েছে।", reply_markup=back_menu_kb("admin_panel", "main_menu"))
    elif data.get("support_username"):
        username = text.lstrip("@")
        current = db.get_message("support_team")
        new_text = current.replace("@shreeakash", f"@{username}")
        db.set_message("support_team", new_text)
        await message.answer("✅ Support Team Username আপডেট করা হয়েছে।", reply_markup=back_menu_kb("admin_panel", "main_menu"))
    await state.clear()


@dp.callback_query(F.data == "admin_messages")
async def cb_admin_messages(callback: CallbackQuery):
    if not is_admin(callback.from_user):
        await callback.answer("⛔ Unauthorized", show_alert=True)
        return
    buttons = [
        [InlineKeyboardButton(text="✏️ Welcome Message", callback_data="edit_msg:welcome")],
        [InlineKeyboardButton(text="✏️ About Message", callback_data="edit_msg:about")],
        [InlineKeyboardButton(text="✏️ Study Group Message", callback_data="edit_msg:study_group")],
        [InlineKeyboardButton(text="✏️ PW Lectures Message", callback_data="edit_msg:pw_lectures")],
        [InlineKeyboardButton(text="✏️ Support Team Message", callback_data="edit_msg:support_team")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="admin_panel"),
         InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu")],
    ]
    await safe_edit_text(callback, "💬 Manage Messages", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@dp.callback_query(F.data.startswith("edit_msg:"))
async def cb_edit_msg(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user):
        return
    key = callback.data.split(":")[1]
    await state.set_state(TextEditState.waiting_text)
    await state.update_data(message_key=key)
    current = db.get_message(key)
    await safe_edit_text(
        callback,
        f"✏️ নতুন টেক্সট পাঠাও:\n\nCurrent:\n{current[:500]}",
        reply_markup=back_menu_kb("admin_messages", "main_menu")
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_groups")
async def cb_admin_groups(callback: CallbackQuery):
    if not is_admin(callback.from_user):
        await callback.answer("⛔ Unauthorized", show_alert=True)
        return
    text = "📢 Manage Groups\n\nStudy Group Link এবং Class Links এখান থেকে এডিট করা যাবে।"
    buttons = [
        [InlineKeyboardButton(text="✏️ Edit Study Group Message", callback_data="edit_msg:study_group")],
        [InlineKeyboardButton(text="🏫 Manage Class Links", callback_data="admin_classes")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="admin_panel"),
         InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu")],
    ]
    await safe_edit_text(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@dp.callback_query(F.data == "admin_settings")
async def cb_admin_settings(callback: CallbackQuery):
    if not is_admin(callback.from_user):
        await callback.answer("⛔ Unauthorized", show_alert=True)
        return
    admin_id = config.ADMIN_USER_ID or "Not set"
    admin_username = config.ADMIN_USERNAME
    text = f"""⚙️ Settings

Admin User ID: {admin_id}
Admin Username: @{admin_username}"""
    buttons = [
        [InlineKeyboardButton(text="🔑 Set Admin User ID", callback_data="admin_set_id")],
        [InlineKeyboardButton(text="👤 Set Admin Username", callback_data="admin_set_username")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="admin_panel"),
         InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu")],
    ]
    await safe_edit_text(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@dp.callback_query(F.data == "admin_set_id")
async def cb_admin_set_id(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user):
        return
    await state.set_state(SettingState.waiting_value)
    await state.update_data(setting_key="admin_user_id")
    await safe_edit_text(
        callback,
        "🔑 Admin User ID পাঠাও (শুধু সংখ্যা):",
        reply_markup=back_menu_kb("admin_settings", "main_menu")
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_set_username")
async def cb_admin_set_username(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user):
        return
    await state.set_state(SettingState.waiting_value)
    await state.update_data(setting_key="admin_username")
    await safe_edit_text(
        callback,
        "👤 Admin Username পাঠাও (@ ছাড়া):",
        reply_markup=back_menu_kb("admin_settings", "main_menu")
    )
    await callback.answer()


@dp.message(SettingState.waiting_value)
async def setting_value_message(message: Message, state: FSMContext):
    if not is_admin(message.from_user):
        return
    data = await state.get_data()
    key = data.get("setting_key")
    value = message.text.strip().lstrip("@")
    db.set_setting(key, value)
    if key == "admin_user_id":
        try:
            config.ADMIN_USER_ID = int(value) or None
        except ValueError:
            config.ADMIN_USER_ID = None
    elif key == "admin_username":
        config.ADMIN_USERNAME = value
    await state.clear()
    await message.answer(f"✅ Setting '{key}' আপডেট করা হয়েছে।", reply_markup=back_menu_kb("admin_settings", "main_menu"))


async def on_startup(bot: Bot):
    logger.info("StudyGuide Bot starting up...")
    try:
        me = await bot.get_me()
        logger.info(f"Logged in as @{me.username} (id={me.id})")
    except Exception as e:
        logger.warning(f"Could not fetch bot info: {e}")


async def on_shutdown(bot: Bot):
    logger.info("StudyGuide Bot shutting down...")
    await bot.session.close()


async def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    if config.WEBHOOK_URL:
        # ---- Webhook mode (optional - for PaaS like Render/Koyeb) ----
        logger.info(f"Starting in WEBHOOK mode: {config.WEBHOOK_URL}{config.WEBHOOK_PATH}")
        await bot.set_webhook(
            url=f"{config.WEBHOOK_URL}{config.WEBHOOK_PATH}",
            drop_pending_updates=True,
        )
        from aiohttp import web as _web  # local alias
        app = _web.Application()
        app.router.add_get("/", health_handler)
        webhook_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
        webhook_handler.register(app, path=config.WEBHOOK_PATH)
        setup_application(app, dp, bot=bot)
        runner = _web.AppRunner(app)
        await runner.setup()
        site = _web.TCPSite(runner, "0.0.0.0", config.WEBHOOK_PORT)
        await site.start()
        logger.info(f"Webhook server listening on 0.0.0.0:{config.WEBHOOK_PORT}")
        await asyncio.Event().wait()
    else:
        # ---- Polling mode (RECOMMENDED for Oracle Cloud / any VPS) ----
        # No domain or HTTPS needed. Delete any old webhook first to avoid conflicts.
        logger.info("Starting in POLLING mode (Oracle Cloud / VPS)...")
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")