#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
بات بازی جنگ جهانی - نسخه کامل
ساختار: python-telegram-bot v21.x + SQLite
فاز ۱: دیتابیس، ثبت‌نام، منوی اصلی
فاز ۲: کشور من (ساختمان‌سازی، ارتقا، تخصیص جمعیت، تولید منابع lazy، طول کشور)
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

    # مایگریشن: ستون تاریخ آخرین محاسبه تولید (برای محاسبه lazy)
    try:
        cur.execute("ALTER TABLE resources ADD COLUMN last_production_check TEXT")
    except sqlite3.OperationalError:
        pass  # ستون از قبل وجود داره

    try:
        cur.execute("ALTER TABLE resources ADD COLUMN electricity_civil_cap INTEGER DEFAULT 1000")
    except sqlite3.OperationalError:
        pass

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

    # ===== فاز ۲: تولید و ساخت‌وساز =====
    # نرخ تولید هر کارگر معدن در ساعت (پایه، سطح ساختمان ۱۰٪ اضافه می‌کنه هر سطح)
    "mine_fertilizer_rate_per_worker": "5",
    "mine_oil_rate_per_worker": "3",
    "mine_metal_rate_per_worker": "3",

    # مزرعه: تولید غذا و مصرف کود به ازای هر سطح، در ساعت
    "farm_food_rate_per_level": "10",
    "farm_fertilizer_consumption_per_level": "5",

    # مصرف غذای هر نفر جمعیت در ساعت
    "population_food_consumption_per_hour": "0.5",

    # هزینه ساخت هر خونه
    "house_build_gold": "300",
    "house_build_metal": "50",

    # هزینه ساخت هر نیروگاه عادی (هر واحد پوشش ۱۰ خونه می‌ده)
    "power_civil_build_gold": "400",
    "power_civil_build_metal": "30",
    "power_civil_houses_covered": "10",

    # هزینه پایه ارتقای سطح مزرعه/معادن (ضرب در سطح فعلی، تصاعدی)
    "farm_upgrade_base_gold": "300",
    "farm_upgrade_base_fertilizer": "100",
    "mine_upgrade_base_gold": "250",
    "mine_upgrade_base_metal": "40",

    # هزینه ساخت معدن فلز (چون از اول داده نمی‌شه)
    "mine_metal_build_gold": "600",
    "mine_metal_build_fertilizer": "100",

    # ظرفیت پایه کارگر هر معدن/مزرعه در سطح ۱ (سقف تعداد کارگر قابل‌تخصیص)
    "mine_worker_capacity_per_level": "5",

    # تولید برق عادی توسط هر نیروگاه در ساعت (بدون نیاز به کارگر)
    "power_civil_output_per_hour": "8",
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

    cur.execute("INSERT INTO resources (user_id, last_production_check) VALUES (?, ?)",
                (user_id, join_date))
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
#  فاز ۲: موتور تولید (محاسبه lazy)
# ============================================================
def calculate_and_apply_production(user_id: int):
    """
    هر بار که کاربر وارد بخش «کشور من» می‌شه، این تابع صدا زده می‌شه.
    بر اساس زمان سپری‌شده از آخرین چک، تولید منابع و مصرف غذا رو محاسبه و اعمال می‌کنه.
    """
    conn = get_db()
    res = conn.execute("SELECT * FROM resources WHERE user_id = ?", (user_id,)).fetchone()
    pop = conn.execute("SELECT * FROM population WHERE user_id = ?", (user_id,)).fetchone()
    buildings = conn.execute("SELECT * FROM buildings WHERE user_id = ?", (user_id,)).fetchall()

    if res is None or pop is None:
        conn.close()
        return

    last_check = res["last_production_check"] or now_str()
    try:
        last_dt = datetime.fromisoformat(last_check)
    except ValueError:
        last_dt = datetime.utcnow()

    elapsed_hours = (datetime.utcnow() - last_dt).total_seconds() / 3600.0
    elapsed_hours = max(0.0, min(elapsed_hours, 72.0))  # سقف ۷۲ ساعت برای جلوگیری از اعداد نجومی

    if elapsed_hours <= 0:
        conn.close()
        return

    b_by_type = {}
    for b in buildings:
        b_by_type.setdefault(b["type"], []).append(b)

    def level_of(b_type):
        rows = b_by_type.get(b_type, [])
        return rows[0]["level"] if rows else 0

    fert_rate = float(get_setting("mine_fertilizer_rate_per_worker") or 5)
    oil_rate = float(get_setting("mine_oil_rate_per_worker") or 3)
    metal_rate = float(get_setting("mine_metal_rate_per_worker") or 3)
    farm_food_rate = float(get_setting("farm_food_rate_per_level") or 10)
    farm_fert_consumption = float(get_setting("farm_fertilizer_consumption_per_level") or 5)
    food_consumption_per_hour = float(get_setting("population_food_consumption_per_hour") or 0.5)

    fert_level = level_of("mine_fertilizer")
    oil_level = level_of("mine_oil")
    metal_level = level_of("mine_metal")
    farm_level = level_of("farm")

    # تولید مواد خام (هر سطح ساختمان ۱۰٪ بونوس تولید می‌ده)
    fert_produced = pop["miners_fertilizer"] * fert_rate * (1 + 0.1 * max(0, fert_level - 1)) * elapsed_hours
    oil_produced = pop["miners_oil"] * oil_rate * (1 + 0.1 * max(0, oil_level - 1)) * elapsed_hours
    metal_produced = pop["miners_metal"] * metal_rate * (1 + 0.1 * max(0, metal_level - 1)) * elapsed_hours

    new_fertilizer = min(res["fertilizer"] + fert_produced, res["fertilizer_cap"])
    new_oil = min(res["oil"] + oil_produced, res["oil_cap"])
    new_metal = min(res["metal"] + metal_produced, res["metal_cap"])

    # تولید برق عادی (بدون نیاز به کارگر، فقط با تعداد نیروگاه)
    power_plants = len(b_by_type.get("power_civil", []))
    power_output_rate = float(get_setting("power_civil_output_per_hour") or 8)
    electricity_produced = power_plants * power_output_rate * elapsed_hours
    elec_cap = res["electricity_civil_cap"] if res["electricity_civil_cap"] else 1000
    new_electricity = min(res["electricity_civil"] + electricity_produced, elec_cap)

    # تولید غذا (مصرف کود می‌کنه؛ اگه کود کافی نباشه تولید غذا متناسب کم می‌شه)
    fert_needed_for_farm = farm_level * farm_fert_consumption * elapsed_hours
    fert_available_for_farm = min(fert_needed_for_farm, new_fertilizer)
    farm_efficiency = (fert_available_for_farm / fert_needed_for_farm) if fert_needed_for_farm > 0 else 0
    food_produced = farm_level * farm_food_rate * elapsed_hours * farm_efficiency
    new_fertilizer -= fert_available_for_farm

    new_food = min(res["food"] + food_produced, res["food_cap"])

    # مصرف غذای جمعیت
    total_population = (pop["unemployed"] + pop["miners_fertilizer"] + pop["miners_oil"] +
                         pop["miners_metal"] + pop["factory_workers"] + pop["military_crew"])
    food_consumed = total_population * food_consumption_per_hour * elapsed_hours
    new_food = max(0, new_food - food_consumed)

    conn.execute("""
        UPDATE resources SET fertilizer=?, oil=?, metal=?, food=?, electricity_civil=?, last_production_check=?
        WHERE user_id=?
    """, (round(new_fertilizer, 1), round(new_oil, 1), round(new_metal, 1),
          round(new_food, 1), round(new_electricity, 1), now_str(), user_id))
    conn.commit()
    conn.close()


def get_buildings_summary(user_id: int):
    conn = get_db()
    rows = conn.execute("SELECT type, level, COUNT(*) as cnt FROM buildings WHERE user_id=? GROUP BY type, level",
                         (user_id,)).fetchall()
    conn.close()
    summary = {}
    for r in rows:
        summary.setdefault(r["type"], []).append((r["level"], r["cnt"]))
    return summary


def count_houses(user_id: int) -> int:
    conn = get_db()
    n = conn.execute("SELECT COUNT(*) as c FROM buildings WHERE user_id=? AND type='house'",
                      (user_id,)).fetchone()["c"]
    conn.close()
    return n


def count_power_civil(user_id: int) -> int:
    conn = get_db()
    n = conn.execute("SELECT COUNT(*) as c FROM buildings WHERE user_id=? AND type='power_civil'",
                      (user_id,)).fetchone()["c"]
    conn.close()
    return n


# ============================================================
#  فاز ۲: منوی «کشور من»
# ============================================================
def country_overview_text(user_id: int) -> str:
    calculate_and_apply_production(user_id)
    conn = get_db()
    res = conn.execute("SELECT * FROM resources WHERE user_id=?", (user_id,)).fetchone()
    pop = conn.execute("SELECT * FROM population WHERE user_id=?", (user_id,)).fetchone()
    player = conn.execute("SELECT * FROM players WHERE user_id=?", (user_id,)).fetchone()
    conn.close()

    houses = count_houses(user_id)
    power_plants = count_power_civil(user_id)
    power_cap = power_plants * int(get_setting("power_civil_houses_covered") or 10)

    total_pop = (pop["unemployed"] + pop["miners_fertilizer"] + pop["miners_oil"] +
                 pop["miners_metal"] + pop["factory_workers"] + pop["military_crew"])

    power_status = "✅ کافی" if power_cap >= houses else f"⚠️ کمبود برق ({power_cap}/{houses} خونه پوشش داره)"

    return (
        f"🏙️ *کشور: {player['country_name'] or 'بدون‌نام'}*\n\n"
        f"📏 طول کشور: {player['land_length']} (ظرفیت خونه: {player['land_length']})\n"
        f"🏠 خونه‌ها: {houses}/{player['land_length']} | ⚡ نیروگاه عادی: {power_plants} — {power_status}\n\n"
        f"👥 *جمعیت* (کل: {total_pop} | ظرفیت مسکن: {pop['housing_capacity']})\n"
        f"  🔸 بیکار: {pop['unemployed']}\n"
        f"  🔸 کارگر کود: {pop['miners_fertilizer']} | کارگر نفت: {pop['miners_oil']} | کارگر فلز: {pop['miners_metal']}\n"
        f"  🔸 کارگر کارخونه: {pop['factory_workers']} | خدمه نظامی: {pop['military_crew']}\n\n"
        f"📦 *منابع*\n"
        f"  💰 پول: {player['gold']}\n"
        f"  💩 کود: {res['fertilizer']:.0f}/{res['fertilizer_cap']}\n"
        f"  🛢️ نفت: {res['oil']:.0f}/{res['oil_cap']}\n"
        f"  ⚙️ فلز: {res['metal']:.0f}/{res['metal_cap']}\n"
        f"  ⚡ برق عادی: {res['electricity_civil']:.0f}/{res['electricity_civil_cap']}\n"
        f"  🌾 غذا: {res['food']:.0f}/{res['food_cap']}\n"
    )


def country_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏗️ ساختمان‌سازی و ارتقا", callback_data="country_build")],
        [InlineKeyboardButton("👥 تخصیص جمعیت", callback_data="country_population")],
        [InlineKeyboardButton("📏 ارتقای طول کشور", callback_data="country_land")],
        [InlineKeyboardButton("🔄 بروزرسانی", callback_data="menu_country")],
        [InlineKeyboardButton("🔙 بازگشت به منو", callback_data="menu_main")],
    ])


def build_menu_keyboard(user_id: int):
    houses = count_houses(user_id)
    conn = get_db()
    player = conn.execute("SELECT land_length FROM players WHERE user_id=?", (user_id,)).fetchone()
    has_metal_mine = conn.execute(
        "SELECT 1 FROM buildings WHERE user_id=? AND type='mine_metal'", (user_id,)
    ).fetchone()
    conn.close()

    buttons = []
    if houses < player["land_length"]:
        buttons.append([InlineKeyboardButton("🏠 ساخت خونه", callback_data="build_house")])
    buttons.append([InlineKeyboardButton("⚡ ساخت نیروگاه عادی", callback_data="build_power_civil")])
    buttons.append([InlineKeyboardButton("🌾 ارتقای مزرعه", callback_data="upgrade_farm")])
    buttons.append([InlineKeyboardButton("💩 ارتقای معدن کود", callback_data="upgrade_mine_fertilizer")])
    buttons.append([InlineKeyboardButton("🛢️ ارتقای معدن نفت", callback_data="upgrade_mine_oil")])
    if has_metal_mine:
        buttons.append([InlineKeyboardButton("⚙️ ارتقای معدن فلز", callback_data="upgrade_mine_metal")])
    else:
        buttons.append([InlineKeyboardButton("⚙️ ساخت معدن فلز", callback_data="build_mine_metal")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu_country")])
    return InlineKeyboardMarkup(buttons)


# ============================================================
#  فاز ۲: سیستم تعداد دلخواه / حداکثر (بدون کلیک تکراری)
# ============================================================
def set_pending_action(user_id: int, action_type: str, data: dict):
    PENDING_ACTIONS[user_id] = {"action": action_type, "data": data}
    conn = get_db()
    conn.execute("""
        INSERT INTO pending_actions (user_id, action_type, context_data)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET action_type=excluded.action_type, context_data=excluded.context_data
    """, (user_id, action_type, json.dumps(data)))
    conn.commit()
    conn.close()


def clear_pending_action(user_id: int):
    PENDING_ACTIONS.pop(user_id, None)
    conn = get_db()
    conn.execute("DELETE FROM pending_actions WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


def get_pending_action(user_id: int):
    if user_id in PENDING_ACTIONS:
        return PENDING_ACTIONS[user_id]
    conn = get_db()
    row = conn.execute("SELECT action_type, context_data FROM pending_actions WHERE user_id=?",
                        (user_id,)).fetchone()
    conn.close()
    if row:
        data = {"action": row["action_type"], "data": json.loads(row["context_data"])}
        PENDING_ACTIONS[user_id] = data
        return data
    return None


def quantity_prompt_keyboard(action_key: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔢 تعداد دلخواه (بنویس)", callback_data=f"qty_custom_{action_key}")],
        [InlineKeyboardButton("⬆️ حداکثر ممکن", callback_data=f"qty_max_{action_key}")],
        [InlineKeyboardButton("🔙 لغو", callback_data="country_build")],
    ])


# ---- محاسبه هزینه هر عمل (برای هر کدوم قابلیت quantity داره) ----
def get_action_cost(user_id: int, action_key: str, quantity: int):
    """برمی‌گردونه dict هزینه‌ها برای quantity واحد/سطح از این عمل."""
    conn = get_db()
    player = conn.execute("SELECT * FROM players WHERE user_id=?", (user_id,)).fetchone()
    conn.close()

    if action_key == "build_house":
        g = int(get_setting("house_build_gold") or 300)
        m = int(get_setting("house_build_metal") or 50)
        return {"gold": g * quantity, "metal": m * quantity}

    if action_key == "build_power_civil":
        g = int(get_setting("power_civil_build_gold") or 400)
        m = int(get_setting("power_civil_build_metal") or 30)
        return {"gold": g * quantity, "metal": m * quantity}

    if action_key == "build_mine_metal":
        g = int(get_setting("mine_metal_build_gold") or 600)
        f = int(get_setting("mine_metal_build_fertilizer") or 100)
        return {"gold": g * quantity, "fertilizer": f * quantity}

    if action_key.startswith("upgrade_"):
        b_type = action_key.replace("upgrade_", "")
        conn = get_db()
        b = conn.execute("SELECT level FROM buildings WHERE user_id=? AND type=?",
                          (user_id, b_type)).fetchone()
        conn.close()
        current_level = b["level"] if b else 1

        if b_type == "farm":
            base_g = int(get_setting("farm_upgrade_base_gold") or 300)
            base_f = int(get_setting("farm_upgrade_base_fertilizer") or 100)
        else:
            base_g = int(get_setting("mine_upgrade_base_gold") or 250)
            base_f = int(get_setting("mine_upgrade_base_metal") or 40)

        total_gold, total_res = 0, 0
        for i in range(quantity):
            lvl = current_level + i
            total_gold += base_g * lvl
            total_res += base_f * lvl

        if b_type == "farm":
            return {"gold": total_gold, "fertilizer": total_res}
        else:
            return {"gold": total_gold, "metal": total_res}

    if action_key == "land_upgrade":
        g = int(get_setting("land_upgrade_gold") or 2000)
        f = int(get_setting("land_upgrade_fertilizer") or 500)
        e = int(get_setting("land_upgrade_electricity") or 300)
        return {"gold": g * quantity, "fertilizer": f * quantity, "electricity": e * quantity}

    return {}


def can_afford(user_id: int, cost: dict) -> bool:
    conn = get_db()
    player = conn.execute("SELECT gold FROM players WHERE user_id=?", (user_id,)).fetchone()
    res = conn.execute("SELECT * FROM resources WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    if cost.get("gold", 0) > player["gold"]:
        return False
    if cost.get("metal", 0) > res["metal"]:
        return False
    if cost.get("fertilizer", 0) > res["fertilizer"]:
        return False
    if cost.get("electricity", 0) > res["electricity_civil"]:
        return False
    return True


def deduct_cost(user_id: int, cost: dict):
    conn = get_db()
    if "gold" in cost:
        conn.execute("UPDATE players SET gold = gold - ? WHERE user_id=?", (cost["gold"], user_id))
    if "metal" in cost:
        conn.execute("UPDATE resources SET metal = metal - ? WHERE user_id=?", (cost["metal"], user_id))
    if "fertilizer" in cost:
        conn.execute("UPDATE resources SET fertilizer = fertilizer - ? WHERE user_id=?",
                      (cost["fertilizer"], user_id))
    if "electricity" in cost:
        conn.execute("UPDATE resources SET electricity_civil = electricity_civil - ? WHERE user_id=?",
                      (cost["electricity"], user_id))
    conn.commit()
    conn.close()


def compute_max_quantity(user_id: int, action_key: str) -> int:
    """بیشترین quantity ممکنی که بازیکن الان استطاعتشو داره (حداکثر ۵۰ برای جلوگیری از حلقه بی‌نهایت)."""
    max_q = 0
    for q in range(1, 51):
        cost = get_action_cost(user_id, action_key, q)
        if not can_afford(user_id, cost):
            break
        max_q = q

    # محدودیت اضافه برای ساخت خونه: نمی‌تونه بیشتر از جای خالی طول کشور بسازه
    if action_key == "build_house":
        conn = get_db()
        player = conn.execute("SELECT land_length FROM players WHERE user_id=?", (user_id,)).fetchone()
        conn.close()
        free_slots = player["land_length"] - count_houses(user_id)
        max_q = min(max_q, max(0, free_slots))

    return max_q


def apply_action(user_id: int, action_key: str, quantity: int):
    """عملیات رو بعد از کسر هزینه واقعاً انجام می‌ده."""
    conn = get_db()

    if action_key == "build_house":
        house_hp = int(get_setting("house_hp") or 50)
        for _ in range(quantity):
            conn.execute("""INSERT INTO buildings (user_id, type, level, hp, built_at)
                             VALUES (?, 'house', 1, ?, ?)""", (user_id, house_hp, now_str()))
        conn.execute("UPDATE population SET housing_capacity = housing_capacity + ? WHERE user_id=?",
                      (quantity * 10, user_id))

    elif action_key == "build_power_civil":
        for _ in range(quantity):
            conn.execute("""INSERT INTO buildings (user_id, type, level, hp, built_at)
                             VALUES (?, 'power_civil', 1, 0, ?)""", (user_id, now_str()))

    elif action_key == "build_mine_metal":
        conn.execute("""INSERT INTO buildings (user_id, type, level, hp, built_at)
                         VALUES (?, 'mine_metal', 1, 0, ?)""", (user_id, now_str()))

    elif action_key.startswith("upgrade_"):
        b_type = action_key.replace("upgrade_", "")
        conn.execute("UPDATE buildings SET level = level + ? WHERE user_id=? AND type=?",
                      (quantity, user_id, b_type))

    elif action_key == "land_upgrade":
        conn.execute("UPDATE players SET land_length = land_length + ? WHERE user_id=?",
                      (quantity * 10, user_id))

    conn.commit()
    conn.close()


ACTION_LABELS = {
    "build_house": "ساخت خونه",
    "build_power_civil": "ساخت نیروگاه عادی",
    "build_mine_metal": "ساخت معدن فلز",
    "upgrade_farm": "ارتقای مزرعه",
    "upgrade_mine_fertilizer": "ارتقای معدن کود",
    "upgrade_mine_oil": "ارتقای معدن نفت",
    "upgrade_mine_metal": "ارتقای معدن فلز",
    "land_upgrade": "ارتقای طول کشور",
}


def cost_to_text(cost: dict) -> str:
    parts = []
    if cost.get("gold"):
        parts.append(f"💰 {cost['gold']} پول")
    if cost.get("metal"):
        parts.append(f"⚙️ {cost['metal']} فلز")
    if cost.get("fertilizer"):
        parts.append(f"💩 {cost['fertilizer']} کود")
    if cost.get("electricity"):
        parts.append(f"⚡ {cost['electricity']} برق")
    return " + ".join(parts) if parts else "رایگان"


# ============================================================
#  فاز ۲: تخصیص جمعیت
# ============================================================
POP_BUCKETS = {
    "unemployed": "بیکار",
    "miners_fertilizer": "کارگر معدن کود",
    "miners_oil": "کارگر معدن نفت",
    "miners_metal": "کارگر معدن فلز",
    "factory_workers": "کارگر کارخونه",
}


def population_menu_keyboard():
    buttons = []
    for key, label in POP_BUCKETS.items():
        if key == "unemployed":
            continue
        buttons.append([InlineKeyboardButton(
            f"➡️ انتقال به {label}", callback_data=f"assign_to_{key}"
        )])
    buttons.append([InlineKeyboardButton("↩️ بازگردوندن به بیکار", callback_data="assign_to_unemployed")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu_country")])
    return InlineKeyboardMarkup(buttons)


def population_source_keyboard(target_key: str):
    """از کدوم بخش می‌خوای جمعیت کم کنی و بفرستی به target_key"""
    buttons = []
    for key, label in POP_BUCKETS.items():
        if key == target_key:
            continue
        buttons.append([InlineKeyboardButton(f"از «{label}»", callback_data=f"popsrc_{key}_{target_key}")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="country_population")])
    return InlineKeyboardMarkup(buttons)


def move_population(user_id: int, from_bucket: str, to_bucket: str, quantity: int) -> bool:
    conn = get_db()
    pop = conn.execute("SELECT * FROM population WHERE user_id=?", (user_id,)).fetchone()
    if pop[from_bucket] < quantity:
        conn.close()
        return False

    # اگه مقصد کارگر معدنه، سقف ظرفیت کارگر معدن رو چک کن
    if to_bucket in ("miners_fertilizer", "miners_oil", "miners_metal"):
        b_type_map = {"miners_fertilizer": "mine_fertilizer", "miners_oil": "mine_oil",
                      "miners_metal": "mine_metal"}
        b = conn.execute("SELECT level FROM buildings WHERE user_id=? AND type=?",
                          (user_id, b_type_map[to_bucket])).fetchone()
        level = b["level"] if b else 0
        cap_per_level = int(get_setting("mine_worker_capacity_per_level") or 5)
        capacity = level * cap_per_level
        current = pop[to_bucket]
        if current + quantity > capacity:
            conn.close()
            return False

    conn.execute(f"UPDATE population SET {from_bucket} = {from_bucket} - ? WHERE user_id=?",
                 (quantity, user_id))
    conn.execute(f"UPDATE population SET {to_bucket} = {to_bucket} + ? WHERE user_id=?",
                 (quantity, user_id))
    conn.commit()
    conn.close()
    return True


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

    if query.data == "menu_country":
        await query.edit_message_text(
            country_overview_text(user_id),
            reply_markup=country_menu_keyboard(),
            parse_mode="Markdown"
        )
        return

    # سایر منوها در فازهای بعدی پیاده می‌شن
    placeholder_map = {
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
#  فاز ۲: هندلر بخش «کشور من» - ساختمان‌سازی/ارتقا/طول کشور/جمعیت
# ============================================================
async def country_build_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_answer(query)
    user_id = update.effective_user.id

    if query.data == "country_build":
        await query.edit_message_text(
            "🏗️ ساختمان‌سازی و ارتقا\n\nچی می‌خوای بسازی یا ارتقا بدی؟",
            reply_markup=build_menu_keyboard(user_id)
        )
        return

    if query.data == "country_population":
        await query.edit_message_text(
            "👥 تخصیص جمعیت\n\nمی‌خوای جمعیت رو به کدوم بخش منتقل کنی؟",
            reply_markup=population_menu_keyboard()
        )
        return

    if query.data == "country_land":
        cost1 = get_action_cost(user_id, "land_upgrade", 1)
        text = (
            f"📏 ارتقای طول کشور\n\n"
            f"هر ارتقا: +۱۰ جای ساخت خونه اضافه می‌کنه\n"
            f"هزینه هر واحد ارتقا: {cost_to_text(cost1)}\n\n"
            f"چند واحد می‌خوای ارتقا بدی؟"
        )
        await query.edit_message_text(text, reply_markup=quantity_prompt_keyboard("land_upgrade"))
        return

    # ---- درخواست شروع یه اکشن با quantity (ساخت/ارتقا) ----
    if query.data in ACTION_LABELS and query.data != "land_upgrade":
        cost1 = get_action_cost(user_id, query.data, 1)
        label = ACTION_LABELS[query.data]
        text = f"🔧 {label}\n\nهزینه هر واحد: {cost_to_text(cost1)}\n\nچند تا می‌خوای انجام بدی؟"
        await query.edit_message_text(text, reply_markup=quantity_prompt_keyboard(query.data))
        return

    # ---- انتخاب «تعداد دلخواه» -> منتظر پیام متنی می‌مونیم ----
    if query.data.startswith("qty_custom_"):
        action_key = query.data.replace("qty_custom_", "")
        set_pending_action(user_id, "enter_quantity", {"action_key": action_key})
        await query.edit_message_text(
            "🔢 لطفاً عدد مورد نظرت رو به‌صورت پیام متنی بفرست (مثلاً بنویس: 5)"
        )
        return

    # ---- انتخاب «حداکثر ممکن» -> فوری اجرا می‌شه ----
    if query.data.startswith("qty_max_"):
        action_key = query.data.replace("qty_max_", "")
        max_q = compute_max_quantity(user_id, action_key)
        if max_q <= 0:
            await query.edit_message_text(
                "❌ در حال حاضر منابع/جای کافی برای حتی یک واحد نداری.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 بازگشت", callback_data="country_build")]])
            )
            return
        cost = get_action_cost(user_id, action_key, max_q)
        deduct_cost(user_id, cost)
        apply_action(user_id, action_key, max_q)
        label = ACTION_LABELS.get(action_key, action_key)
        await query.edit_message_text(
            f"✅ {label} با موفقیت انجام شد!\nتعداد: {max_q}\nهزینه پرداختی: {cost_to_text(cost)}",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 بازگشت به کشور من", callback_data="menu_country")]])
        )
        return

    # ---- تخصیص جمعیت: انتخاب مقصد ----
    if query.data.startswith("assign_to_"):
        target_key = query.data.replace("assign_to_", "")
        await query.edit_message_text(
            f"➡️ انتقال جمعیت به «{POP_BUCKETS[target_key]}»\n\nاز کدوم بخش می‌خوای کم کنی؟",
            reply_markup=population_source_keyboard(target_key)
        )
        return

    # ---- تخصیص جمعیت: انتخاب مبدا -> منتظر تعداد ----
    if query.data.startswith("popsrc_"):
        remainder = query.data.replace("popsrc_", "")
        matched_from = None
        matched_to = None
        for key in POP_BUCKETS:
            if remainder.startswith(key + "_"):
                matched_from = key
                matched_to = remainder[len(key) + 1:]
                break
        if not matched_from:
            await safe_answer(query, "خطا در پردازش", show_alert=True)
            return

        set_pending_action(user_id, "enter_pop_quantity", {"from": matched_from, "to": matched_to})
        conn = get_db()
        pop = conn.execute("SELECT * FROM population WHERE user_id=?", (user_id,)).fetchone()
        conn.close()
        available = pop[matched_from]
        await query.edit_message_text(
            f"از «{POP_BUCKETS[matched_from]}» ({available} نفر موجود) به «{POP_BUCKETS[matched_to]}»\n\n"
            f"چند نفر می‌خوای منتقل کنی؟ (عدد رو تایپ کن)"
        )
        return


# ============================================================
#  فاز ۲: دریافت ورودی متنی (تعداد دلخواه ساخت/ارتقا/تخصیص جمعیت)
# ============================================================
async def text_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pending = get_pending_action(user_id)
    if not pending:
        return  # هیچ اکشن در انتظاری نیست، پیام رو نادیده بگیر

    text = update.message.text.strip()
    if not text.isdigit() or int(text) <= 0:
        await update.message.reply_text("⚠️ لطفاً فقط یه عدد صحیح مثبت بفرست (مثلاً 5)")
        return

    quantity = int(text)

    if pending["action"] == "enter_quantity":
        action_key = pending["data"]["action_key"]
        max_q = compute_max_quantity(user_id, action_key)
        if quantity > max_q:
            await update.message.reply_text(
                f"❌ استطاعت این تعداد رو نداری. حداکثر ممکن الان: {max_q}\n"
                f"یه عدد کمتر یا مساوی {max_q} بفرست."
            )
            return
        cost = get_action_cost(user_id, action_key, quantity)
        deduct_cost(user_id, cost)
        apply_action(user_id, action_key, quantity)
        clear_pending_action(user_id)
        label = ACTION_LABELS.get(action_key, action_key)
        await update.message.reply_text(
            f"✅ {label} با موفقیت انجام شد!\nتعداد: {quantity}\nهزینه پرداختی: {cost_to_text(cost)}",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 بازگشت به کشور من", callback_data="menu_country")]])
        )
        return

    if pending["action"] == "enter_pop_quantity":
        from_key = pending["data"]["from"]
        to_key = pending["data"]["to"]
        success = move_population(user_id, from_key, to_key, quantity)
        clear_pending_action(user_id)
        if success:
            await update.message.reply_text(
                f"✅ {quantity} نفر از «{POP_BUCKETS[from_key]}» به «{POP_BUCKETS[to_key]}» منتقل شدن.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 بازگشت به کشور من", callback_data="menu_country")]])
            )
        else:
            await update.message.reply_text(
                "❌ این تعداد امکان‌پذیر نیست (یا جمعیت کافی نداری، یا ظرفیت مقصد پره — "
                "برای افزایش ظرفیت معدن، سطحش رو ارتقا بده)."
            )
        return


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

    # فاز ۲: ساختمان‌سازی، ارتقا، طول کشور، تخصیص جمعیت، تعداد دلخواه/حداکثر
    country_patterns = "^(country_|build_|upgrade_|land_upgrade|qty_custom_|qty_max_|assign_to_|popsrc_)"
    app.add_handler(CallbackQueryHandler(country_build_callback, pattern=country_patterns))

    # پیام‌های متنی (برای وارد کردن تعداد دلخواه) - باید بعد از کامندها ثبت بشه
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_input_handler))

    logger.info("بات در حال اجراست...")
    app.run_polling()


if __name__ == "__main__":
    main()
