#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
بات بازی جنگ جهانی - نسخه کامل
ساختار: python-telegram-bot v21.x + SQLite
فاز ۱: دیتابیس، ثبت‌نام، منوی اصلی
"""

import os
import sqlite3
import logging
import json
import random
import string
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
from telegram.error import BadRequest

# ============================================================
#  تنظیمات پایه
# ============================================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))  # آیدی عددی ادمین اصلی (پایتخت)
ANNOUNCEMENT_CHANNEL_ID = os.environ.get("ANNOUNCEMENT_CHANNEL_ID", "")  # مثلاً @mychannel یا -100...

# مسیر مطلق دیتابیس برای سازگاری با Railway (با Volume ماندگار می‌مونه)
DB_DIR = os.environ.get("DB_DIR", "/app/data")
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "game.db")

PENDING_ACTIONS = {}  # user_id -> {"action": str, "data": dict}  (حافظه سریع، همراه با جدول دیتابیس برای پایداری)


# ============================================================
#  اتصال به دیتابیس
# ============================================================
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS players (
        user_id INTEGER PRIMARY KEY,
        country_name TEXT,
        is_admin INTEGER DEFAULT 0,
        referrer_id INTEGER,
        join_date TEXT,
        protection_until TEXT,
        alliance_id INTEGER,
        alliance_join_date TEXT,
        land_length INTEGER DEFAULT 10,
        gold INTEGER DEFAULT 500,
        cap_points INTEGER DEFAULT 0,
        channel_joined INTEGER DEFAULT 0,
        last_active TEXT
    );

    CREATE TABLE IF NOT EXISTS resources (
        user_id INTEGER PRIMARY KEY,
        fertilizer INTEGER DEFAULT 50,
        fertilizer_cap INTEGER DEFAULT 500,
        food INTEGER DEFAULT 50,
        food_cap INTEGER DEFAULT 500,
        oil INTEGER DEFAULT 30,
        oil_cap INTEGER DEFAULT 300,
        metal INTEGER DEFAULT 0,
        metal_cap INTEGER DEFAULT 300,
        electricity_civil INTEGER DEFAULT 10,
        electricity_industrial INTEGER DEFAULT 0,
        fertilizer_sellable INTEGER DEFAULT 1,
        oil_sellable INTEGER DEFAULT 0,
        metal_sellable INTEGER DEFAULT 0,
        FOREIGN KEY(user_id) REFERENCES players(user_id)
    );

    CREATE TABLE IF NOT EXISTS population (
        user_id INTEGER PRIMARY KEY,
        unemployed INTEGER DEFAULT 20,
        miners_fertilizer INTEGER DEFAULT 0,
        miners_oil INTEGER DEFAULT 0,
        miners_metal INTEGER DEFAULT 0,
        factory_workers INTEGER DEFAULT 0,
        military_crew INTEGER DEFAULT 0,
        housing_capacity INTEGER DEFAULT 20,
        last_growth_check TEXT,
        FOREIGN KEY(user_id) REFERENCES players(user_id)
    );

    CREATE TABLE IF NOT EXISTS buildings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        type TEXT,
        level INTEGER DEFAULT 1,
        hp INTEGER DEFAULT 0,
        built_at TEXT,
        FOREIGN KEY(user_id) REFERENCES players(user_id)
    );

    CREATE TABLE IF NOT EXISTS factories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        type TEXT,
        level INTEGER DEFAULT 1,
        storage_used INTEGER DEFAULT 0,
        storage_cap INTEGER DEFAULT 100,
        blueprint_id INTEGER,
        FOREIGN KEY(user_id) REFERENCES players(user_id)
    );

    CREATE TABLE IF NOT EXISTS blueprints (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        item_code TEXT,
        item_type TEXT,
        damage INTEGER,
        is_active INTEGER DEFAULT 0,
        FOREIGN KEY(user_id) REFERENCES players(user_id)
    );

    CREATE TABLE IF NOT EXISTS military_units (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        item_code TEXT,
        item_type TEXT,
        quantity INTEGER DEFAULT 0,
        crew_per_unit INTEGER DEFAULT 1,
        damage_per_unit INTEGER DEFAULT 10,
        FOREIGN KEY(user_id) REFERENCES players(user_id)
    );

    CREATE TABLE IF NOT EXISTS defenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        tier INTEGER,
        level INTEGER DEFAULT 1,
        hits_remaining INTEGER,
        max_hits INTEGER,
        under_repair_until TEXT,
        FOREIGN KEY(user_id) REFERENCES players(user_id)
    );

    CREATE TABLE IF NOT EXISTS research (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        research_type TEXT,
        level INTEGER DEFAULT 0,
        bonus_value REAL DEFAULT 0,
        FOREIGN KEY(user_id) REFERENCES players(user_id)
    );

    CREATE TABLE IF NOT EXISTS alliances (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        leader_id INTEGER,
        max_members INTEGER DEFAULT 5,
        vault_gold INTEGER DEFAULT 0,
        vault_cap INTEGER DEFAULT 0,
        is_admin_alliance INTEGER DEFAULT 0,
        created_at TEXT
    );

    CREATE TABLE IF NOT EXISTS alliance_storage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        alliance_id INTEGER,
        user_id INTEGER,
        item_code TEXT,
        quantity INTEGER,
        damage_per_unit INTEGER,
        FOREIGN KEY(alliance_id) REFERENCES alliances(id)
    );

    CREATE TABLE IF NOT EXISTS war_regular (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        attacker_id INTEGER,
        defender_id INTEGER,
        status TEXT DEFAULT 'pending_admin',
        total_damage INTEGER DEFAULT 0,
        defense_blocked INTEGER DEFAULT 0,
        start_time TEXT,
        end_time TEXT,
        result TEXT,
        admin_timeout_check TEXT
    );

    CREATE TABLE IF NOT EXISTS war_alliance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        attacker_alliance_id INTEGER,
        defender_alliance_id INTEGER,
        status TEXT DEFAULT 'scheduled',
        scheduled_by_admin_at TEXT,
        start_time TEXT,
        end_time TEXT,
        current_target_order TEXT,
        vault_reward_cap INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS war_alliance_targets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        war_id INTEGER,
        target_user_id INTEGER,
        max_hp INTEGER,
        current_hp INTEGER,
        destroyed INTEGER DEFAULT 0,
        wealth_lost_percent INTEGER DEFAULT 20,
        shield_until TEXT
    );

    CREATE TABLE IF NOT EXISTS war_alliance_contributions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        war_id INTEGER,
        user_id INTEGER,
        damage_dealt INTEGER DEFAULT 0,
        units_contributed INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS market_listings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        listing_code TEXT UNIQUE,
        seller_id INTEGER,
        item_category TEXT,
        item_code TEXT,
        quantity INTEGER,
        price_per_unit INTEGER,
        status TEXT DEFAULT 'active',
        created_at TEXT
    );

    CREATE TABLE IF NOT EXISTS admin_shop_settings (
        item_key TEXT PRIMARY KEY,
        price INTEGER,
        stock INTEGER,
        category TEXT
    );

    CREATE TABLE IF NOT EXISTS blueprint_shop (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_code TEXT,
        item_type TEXT,
        price INTEGER,
        stock INTEGER,
        damage_value INTEGER,
        crew_required INTEGER
    );

    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_user INTEGER,
        to_user INTEGER,
        type TEXT,
        item TEXT,
        amount INTEGER,
        timestamp TEXT
    );

    CREATE TABLE IF NOT EXISTS global_settings (
        setting_key TEXT PRIMARY KEY,
        setting_value TEXT
    );

    CREATE TABLE IF NOT EXISTS pending_actions (
        user_id INTEGER PRIMARY KEY,
        action_type TEXT,
        context_data TEXT
    );

    CREATE TABLE IF NOT EXISTS channel_announcements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT,
        related_id INTEGER,
        sent_at TEXT
    );
    """)

    conn.commit()
    conn.close()
    logger.info("دیتابیس با موفقیت مقداردهی اولیه شد.")


# ============================================================
#  تنظیمات پیش‌فرض سراسری (قابل تغییر توسط ادمین از پنل)
# ============================================================
DEFAULT_SETTINGS = {
    # اچ‌پی ساختمان‌ها (برای جنگ اتحادی)
    "house_hp": "50",
    "farm_hp": "80",

    # قیمت ارتقای طول کشور (هر واحد = ۱۰ جای مسکونی)
    "land_upgrade_gold": "2000",
    "land_upgrade_fertilizer": "500",
    "land_upgrade_electricity": "300",

    # زمان تعمیر پدافند (ساعت) - هر تیر بالاتر ۱.۲ برابر بیشتر
    "defense_repair_base_hours": "3",

    # حداکثر ضربه هر تیر پدافند قبل از نیاز به تعمیر
    "defense_tier1_max_hits": "6",
    "defense_tier2_max_hits": "5",
    "defense_tier3_max_hits": "4",
    "defense_tier4_max_hits": "2",

    # درصد رهگیری پایه هر تیر پدافند
    "defense_tier1_rate": "10",
    "defense_tier2_rate": "20",
    "defense_tier3_rate": "40",
    "defense_tier4_rate": "60",

    # محدودیت جنگ عادی
    "war_power_gap_percent": "70",   # اگه تفاوت قدرت بیشتر از این باشه رد می‌شه
    "war_admin_timeout_hours": "12",
    "war_regular_duration_hours": "2",

    # جنگ اتحادی
    "war_alliance_duration_hours": "24",
    "war_alliance_shield_hours": "12",
    "war_alliance_cap_per_destroyed": "100",

    # اتحاد
    "alliance_default_max_members": "5",
    "alliance_max_members_upgraded": "10",
    "alliance_gift_max_percent": "50",
    "alliance_gift_cooldown_hours": "12",
    "alliance_leave_cooldown_hours": "24",

    # تازه‌وارد / محافظت
    "newbie_admin_alliance_hours": "24",
    "newbie_protection_days": "7",

    # رفرال
    "referral_signup_bonus_cap": "10",
    "referral_daily_income_percent": "5",

    # فروش فوری
    "instant_sell_ratio": "4",  # یعنی ۱/۴ قیمت
}


def init_global_settings():
    conn = get_db()
    cur = conn.cursor()
    for key, value in DEFAULT_SETTINGS.items():
        cur.execute(
            "INSERT OR IGNORE INTO global_settings (setting_key, setting_value) VALUES (?, ?)",
            (key, value)
        )
    conn.commit()
    conn.close()


def get_setting(key: str):
    conn = get_db()
    row = conn.execute(
        "SELECT setting_value FROM global_settings WHERE setting_key = ?", (key,)
    ).fetchone()
    conn.close()
    if row is None:
        return DEFAULT_SETTINGS.get(key)
    return row["setting_value"]


def set_setting(key: str, value: str):
    conn = get_db()
    conn.execute(
        "INSERT INTO global_settings (setting_key, setting_value) VALUES (?, ?) "
        "ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value",
        (key, value)
    )
    conn.commit()
    conn.close()


# ============================================================
#  ابزارهای کمکی
# ============================================================
async def safe_answer(query, text=None, show_alert=False):
    """جلوگیری از خطای دوبار-پاسخ callback query"""
    try:
        await query.answer(text=text, show_alert=show_alert)
    except BadRequest:
        pass


def now_str():
    return datetime.utcnow().isoformat()


def generate_listing_code():
    """کد یکتای رندوم برای آگهی‌های بازار، مثل T2533"""
    while True:
        code = "T" + "".join(random.choices(string.digits, k=4))
        conn = get_db()
        exists = conn.execute(
            "SELECT 1 FROM market_listings WHERE listing_code = ? AND status = 'active'",
            (code,)
        ).fetchone()
        conn.close()
        if not exists:
            return code


def player_exists(user_id: int) -> bool:
    conn = get_db()
    row = conn.execute("SELECT 1 FROM players WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return row is not None


def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


# ============================================================
#  ثبت‌نام بازیکن جدید (سرمایه اولیه)
# ============================================================
def create_new_player(user_id: int, referrer_id: int = None):
    conn = get_db()
    cur = conn.cursor()
    join_date = now_str()
    protection_until = (datetime.utcnow() + timedelta(days=7)).isoformat()

    admin_flag = 1 if user_id == ADMIN_ID else 0
    country_name = "پایتخت" if admin_flag else None

    cur.execute("""
        INSERT INTO players (user_id, country_name, is_admin, referrer_id, join_date,
                              protection_until, land_length, gold, cap_points, last_active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, country_name, admin_flag, referrer_id, join_date,
          protection_until, 10, 500, 0, join_date))

    cur.execute("INSERT INTO resources (user_id) VALUES (?)", (user_id,))
    cur.execute("""INSERT INTO population (user_id, last_growth_check)
                    VALUES (?, ?)""", (user_id, join_date))

    # ساختمان‌های اولیه: ۲ خونه، ۱ مزرعه، ۱ معدن کود، ۱ معدن نفت، ۱ نیروگاه عادی
    house_hp = int(get_setting("house_hp") or 50)
    farm_hp = int(get_setting("farm_hp") or 80)

    starter_buildings = [
        ("house", house_hp), ("house", house_hp),
        ("farm", farm_hp),
        ("mine_fertilizer", 0),
        ("mine_oil", 0),
        ("power_civil", 0),
    ]
    for b_type, hp in starter_buildings:
        cur.execute("""INSERT INTO buildings (user_id, type, level, hp, built_at)
                        VALUES (?, ?, 1, ?, ?)""", (user_id, b_type, hp, join_date))

    # پدافند اولیه: تیر ۱ (ضعیف‌ترین)
    max_hits_t1 = int(get_setting("defense_tier1_max_hits") or 6)
    cur.execute("""INSERT INTO defenses (user_id, tier, level, hits_remaining, max_hits)
                    VALUES (?, 1, 1, ?, ?)""", (user_id, max_hits_t1, max_hits_t1))

    conn.commit()
    conn.close()


# ============================================================
#  منوی اصلی (دکمه‌های شیشه‌ای)
# ============================================================
def main_menu_keyboard(user_id: int):
    buttons = [
        [InlineKeyboardButton("🏙️ کشور من", callback_data="menu_country"),
         InlineKeyboardButton("⚔️ حمله", callback_data="menu_attack")],
        [InlineKeyboardButton("🛡️ پدافند و دفاع", callback_data="menu_defense"),
         InlineKeyboardButton("🤝 اتحاد", callback_data="menu_alliance")],
        [InlineKeyboardButton("🏪 شاپ‌ها", callback_data="menu_shops"),
         InlineKeyboardButton("🔬 آزمایشگاه", callback_data="menu_lab")],
        [InlineKeyboardButton("🏆 رنکینگ", callback_data="menu_ranking"),
         InlineKeyboardButton("📊 آمار من", callback_data="menu_stats")],
        [InlineKeyboardButton("📖 راهنما", callback_data="menu_help")],
    ]
    if is_admin(user_id):
        buttons.append([InlineKeyboardButton("👑 پنل ادمین", callback_data="menu_admin")])
    return InlineKeyboardMarkup(buttons)


def get_main_menu_text(user_id: int) -> str:
    conn = get_db()
    p = conn.execute("SELECT * FROM players WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    name = p["country_name"] or "بدون‌نام"
    return (
        f"🏳️ کشور: {name}\n"
        f"💰 پول: {p['gold']}\n"
        f"🏅 کاپ: {p['cap_points']}\n\n"
        f"یکی از گزینه‌های زیر را انتخاب کنید:"
    )


# ============================================================
#  هندلرها
# ============================================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not player_exists(user_id):
        referrer_id = None
        if context.args:
            try:
                potential_ref = int(context.args[0])
                if potential_ref != user_id and player_exists(potential_ref):
                    referrer_id = potential_ref
            except (ValueError, IndexError):
                pass

        create_new_player(user_id, referrer_id)

        # پاداش رفرال به دعوت‌کننده
        if referrer_id:
            bonus = int(get_setting("referral_signup_bonus_cap") or 10)
            conn = get_db()
            conn.execute(
                "UPDATE players SET cap_points = cap_points + ? WHERE user_id = ?",
                (bonus, referrer_id)
            )
            conn.execute("""INSERT INTO transactions (from_user, to_user, type, item, amount, timestamp)
                             VALUES (?, ?, 'referral_bonus', 'cap', ?, ?)""",
                          (user_id, referrer_id, bonus, now_str()))
            conn.commit()
            conn.close()
            try:
                await context.bot.send_message(
                    referrer_id,
                    f"🎉 یک بازیکن جدید با لینک دعوت شما وارد بازی شد!\n"
                    f"شما {bonus} کاپ جایزه گرفتید."
                )
            except Exception:
                pass

        welcome_text = (
            "🎮 به بازی «جنگ جهانی» خوش اومدی!\n\n"
            "کشور تازه‌ت ساخته شد و یه سری سرمایه اولیه گرفتی:\n"
            "💰 ۵۰۰ پول | 🏠 ۲ خونه | 🌾 ۱ مزرعه\n"
            "💩 ۱ معدن کود | 🛢️ ۱ معدن نفت | 🛡️ ۱ پدافند پایه\n\n"
            "برای شروع، از منوی زیر استفاده کن 👇"
        )
        await update.message.reply_text(welcome_text, reply_markup=main_menu_keyboard(user_id))
        return

    await update.message.reply_text(
        get_main_menu_text(user_id),
        reply_markup=main_menu_keyboard(user_id)
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 راهنمای بازی «جنگ جهانی»\n\n"
        "🏙️ *کشور من*: مدیریت ساختمان‌ها، منابع و جمعیت\n"
        "⚔️ *حمله*: انتخاب تجهیزات نظامی و کشور هدف برای جنگ\n"
        "🛡️ *پدافند*: مدیریت سیستم دفاعی برای مقابله با حملات\n"
        "🤝 *اتحاد*: عضویت/ساخت اتحاد، جنگ قبیله‌ای، گیفت\n"
        "🏪 *شاپ‌ها*: خرید از ادمین، نقشه‌ساخت، بازار بازیکنان\n"
        "🔬 *آزمایشگاه*: تحقیقات برای بونوس دائمی\n\n"
        "برای بازگشت به منو، دستور /start رو بزن."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_answer(query)
    user_id = update.effective_user.id

    if query.data == "menu_help":
        help_text = (
            "📖 راهنمای بازی «جنگ جهانی»\n\n"
            "🏙️ کشور من: مدیریت ساختمان‌ها، منابع و جمعیت\n"
            "⚔️ حمله: انتخاب تجهیزات و کشور هدف\n"
            "🛡️ پدافند: مدیریت دفاع\n"
            "🤝 اتحاد: عضویت/ساخت اتحاد، جنگ قبیله‌ای\n"
            "🏪 شاپ‌ها: خرید منابع، نقشه، بازار\n"
            "🔬 آزمایشگاه: تحقیقات\n"
        )
        back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")]])
        await query.edit_message_text(help_text, reply_markup=back_btn)
        return

    if query.data == "menu_main":
        await query.edit_message_text(
            get_main_menu_text(user_id),
            reply_markup=main_menu_keyboard(user_id)
        )
        return

    # سایر منوها در فازهای بعدی پیاده می‌شن
    placeholder_map = {
        "menu_country": "🏙️ بخش کشور من",
        "menu_attack": "⚔️ بخش حمله",
        "menu_defense": "🛡️ بخش پدافند",
        "menu_alliance": "🤝 بخش اتحاد",
        "menu_shops": "🏪 بخش شاپ‌ها",
        "menu_lab": "🔬 بخش آزمایشگاه",
        "menu_ranking": "🏆 بخش رنکینگ",
        "menu_stats": "📊 بخش آمار",
        "menu_admin": "👑 پنل ادمین",
    }
    if query.data in placeholder_map:
        back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")]])
        await query.edit_message_text(
            f"{placeholder_map[query.data]}\n\n(این بخش در فاز بعدی کدنویسی تکمیل می‌شه)",
            reply_markup=back_btn
        )


# ============================================================
#  اجرای اصلی
# ============================================================
def main():
    if not BOT_TOKEN:
        raise RuntimeError("لطفاً BOT_TOKEN رو در متغیرهای محیطی Railway تنظیم کن.")

    init_db()
    init_global_settings()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    # تلگرام اسم دستورات باید فقط حروف لاتین/عدد/آندرلاین باشه، پس «راهنما» به‌جای CommandHandler
    # با فیلتر متنی زیر پشتیبانی می‌شه (کاربر می‌تونه بنویسه «راهنما» و جواب بگیره)
    app.add_handler(MessageHandler(filters.Regex("^راهنما$"), help_command))
    app.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^menu_"))

    logger.info("بات در حال اجراست...")
    app.run_polling()


if __name__ == "__main__":
    main()
