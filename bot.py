#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
بات بازی جنگ جهانی - نسخه کامل
ساختار: python-telegram-bot v21.x + SQLite
فاز ۱: دیتابیس، ثبت‌نام، منوی اصلی
فاز ۲: کشور من (ساختمان‌سازی، ارتقا، تخصیص جمعیت، تولید منابع lazy، طول کشور)
فاز ۳: کارخونه‌های نظامی (تانک/جنگنده/کشتی/موشک)، نیروگاه اتمی، تولید واحد نظامی، مدل پایه بدون نقشه
فاز ۴: پدافند (۴ تیر، نرخ رهگیری، تعمیر، سقف ارتقا)
فاز ۵: حمله/جنگ عادی (سبد چندواحدی، محدودیت ۷۰٪ تفاوت قدرت، محاسبه دفاع، نتیجه و کاپ)
فاز ۶: اتحاد (ساخت، عضویت، ترک، اخراج توسط رهبر، گیفت با سقف ۵۰٪/کول‌داون ۱۲ساعته، گاوصندوق، اتحاد نامحدود ادمین + عضویت خودکار تازه‌وارد)
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

    try:
        cur.execute("ALTER TABLE resources ADD COLUMN electricity_industrial_cap INTEGER DEFAULT 1000")
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute("ALTER TABLE blueprints ADD COLUMN crew_required INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute("ALTER TABLE players ADD COLUMN alliance_cooldown_until TEXT")
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute("ALTER TABLE players ADD COLUMN last_gift_at TEXT")
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

    # ===== فاز ۳: کارخونه‌های نظامی =====
    # هزینه ساخت هر نوع کارخونه (پول + فلز)
    "factory_tank_build_gold": "1500",
    "factory_tank_build_metal": "300",
    "factory_jet_build_gold": "2500",
    "factory_jet_build_metal": "500",
    "factory_ship_build_gold": "3000",
    "factory_ship_build_metal": "600",
    "factory_missile_build_gold": "4000",
    "factory_missile_build_metal": "800",

    # هزینه ارتقای سطح کارخونه (تصاعدی، ضرب در سطح فعلی)
    "factory_upgrade_base_gold": "600",
    "factory_upgrade_base_metal": "150",

    # ظرفیت پایه انبار محصول هر کارخونه در سطح ۱ (هر سطح +۵۰٪)
    "factory_storage_base": "20",

    # نرخ تولید: هر کارگر در ساعت چند واحد از محصول کارخونه می‌سازه (ضرب در سطح کارخونه)
    "factory_production_rate_per_worker": "0.2",

    # مصرف فلز و برق صنعتی به ازای هر واحد تولیدشده
    "factory_metal_cost_per_unit": "30",
    "factory_electricity_cost_per_unit": "10",

    # نیروگاه اتمی (برق صنعتی، مخصوص کارخونه‌ها)
    "power_industrial_build_gold": "2000",
    "power_industrial_build_metal": "400",
    "power_industrial_output_per_hour": "15",

    # مدل پایه هر کارخونه (بدون نیاز به نقشه) - دمیج/خدمه/هزینه فلز
    "basic_tank_damage": "20",
    "basic_tank_crew": "2",
    "basic_jet_damage": "35",
    "basic_jet_crew": "3",
    "basic_ship_damage": "50",
    "basic_ship_crew": "4",
    "basic_missile_damage": "60",
    "basic_missile_crew": "1",

    # ===== فاز ۴: پدافند =====
    "defense_tier1_build_gold": "1000",
    "defense_tier1_build_metal": "200",
    "defense_tier2_build_gold": "2000",
    "defense_tier2_build_metal": "400",
    "defense_tier3_build_gold": "4000",
    "defense_tier3_build_metal": "800",
    "defense_tier4_build_gold": "8000",
    "defense_tier4_build_metal": "1500",

    "defense_upgrade_base_gold": "500",
    "defense_upgrade_base_metal": "100",

    "defense_repair_gold_per_tier": "300",

    # ===== فاز ۵: جنگ عادی =====
    "war_cap_reward_per_effective_damage": "0.2",   # هر ۵ واحد دمیج مؤثر = ۱ کاپ برای برنده
    "war_cap_consolation_defender": "0.1",          # اگه دفاع کامل موفق بود، مدافع از دمیج خام کاپ می‌گیره
    "war_max_targets_shown": "15",

    # ===== فاز ۶: اتحاد =====
    "alliance_create_gold_cost": "3000",
    "alliance_upgrade_members_gold_cost": "5000",
    "alliance_kick_cooldown_hours": "12",
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

    # فاز ۶: اگه اتحاد ادمین از قبل ساخته شده، تازه‌وارد خودکار ۲۴ ساعت عضوش می‌شه
    if not admin_flag:
        conn = get_db()
        admin_alliance = conn.execute("SELECT id FROM alliances WHERE is_admin_alliance=1 LIMIT 1").fetchone()
        conn.close()
        if admin_alliance:
            join_alliance(user_id, admin_alliance["id"], force=True)


# ============================================================
#  فاز ۲: موتور تولید (محاسبه lazy)
# ============================================================
BASIC_MODEL_CODES = {"tank": "TK-1", "jet": "JT-1", "ship": "SH-1", "missile": "MS-1"}


def get_factory_active_model(user_id: int, factory_row):
    """برمی‌گردونه (item_code, item_type, damage, crew) کارخونه - نقشه فعال یا مدل پایه"""
    if factory_row["blueprint_id"]:
        conn = get_db()
        bp = conn.execute("SELECT * FROM blueprints WHERE id=?", (factory_row["blueprint_id"],)).fetchone()
        conn.close()
        if bp:
            return bp["item_code"], bp["item_type"], bp["damage"], bp["crew_required"] or 1

    ftype = factory_row["type"]
    code = BASIC_MODEL_CODES.get(ftype, ftype.upper())
    damage = int(get_setting(f"basic_{ftype}_damage") or 20)
    crew = int(get_setting(f"basic_{ftype}_crew") or 1)
    return code, ftype, damage, crew


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

    # تولید برق صنعتی (نیروگاه اتمی - برای کارخونه‌ها)
    nuclear_plants = len(b_by_type.get("power_industrial", []))
    nuclear_output_rate = float(get_setting("power_industrial_output_per_hour") or 15)
    industrial_elec_produced = nuclear_plants * nuclear_output_rate * elapsed_hours
    elec_ind_cap = res["electricity_industrial_cap"] if res["electricity_industrial_cap"] else 1000
    new_electricity_industrial = min(res["electricity_industrial"] + industrial_elec_produced, elec_ind_cap)

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
        UPDATE resources SET fertilizer=?, oil=?, metal=?, food=?, electricity_civil=?,
                              electricity_industrial=?, last_production_check=?
        WHERE user_id=?
    """, (round(new_fertilizer, 1), round(new_oil, 1), round(new_metal, 1),
          round(new_food, 1), round(new_electricity, 1), round(new_electricity_industrial, 1),
          now_str(), user_id))

    # ---- تولید واحد نظامی در کارخونه‌ها (تقسیم مساوی کارگر کارخونه بین کارخونه‌های فعال) ----
    factories = conn.execute("SELECT * FROM factories WHERE user_id=?", (user_id,)).fetchall()
    if factories and pop["factory_workers"] > 0:
        workers_per_factory = pop["factory_workers"] / len(factories)
        production_rate = float(get_setting("factory_production_rate_per_worker") or 0.2)
        metal_cost_per_unit = float(get_setting("factory_metal_cost_per_unit") or 30)
        elec_cost_per_unit = float(get_setting("factory_electricity_cost_per_unit") or 10)

        available_metal = new_metal
        available_elec_ind = new_electricity_industrial

        for f in factories:
            item_code, item_type, damage, crew = get_factory_active_model(user_id, f)
            desired_units = workers_per_factory * production_rate * f["level"] * elapsed_hours

            # محدودیت با موجودی فلز/برق صنعتی
            max_by_metal = available_metal / metal_cost_per_unit if metal_cost_per_unit > 0 else desired_units
            max_by_elec = available_elec_ind / elec_cost_per_unit if elec_cost_per_unit > 0 else desired_units
            # محدودیت با ظرفیت انبار کارخونه
            free_storage = f["storage_cap"] - f["storage_used"]

            actual_units = min(desired_units, max_by_metal, max_by_elec, max(0, free_storage))
            if actual_units <= 0:
                continue

            available_metal -= actual_units * metal_cost_per_unit
            available_elec_ind -= actual_units * elec_cost_per_unit

            conn.execute("UPDATE factories SET storage_used = storage_used + ? WHERE id=?",
                         (actual_units, f["id"]))

            existing_unit = conn.execute(
                "SELECT * FROM military_units WHERE user_id=? AND item_code=?", (user_id, item_code)
            ).fetchone()
            if existing_unit:
                conn.execute("UPDATE military_units SET quantity = quantity + ? WHERE id=?",
                             (actual_units, existing_unit["id"]))
            else:
                conn.execute("""INSERT INTO military_units
                                 (user_id, item_code, item_type, quantity, crew_per_unit, damage_per_unit)
                                 VALUES (?, ?, ?, ?, ?, ?)""",
                             (user_id, item_code, item_type, actual_units, crew, damage))

        conn.execute("UPDATE resources SET metal=?, electricity_industrial=? WHERE user_id=?",
                     (round(available_metal, 1), round(available_elec_ind, 1), user_id))

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
        [InlineKeyboardButton("🏭 کارخونه‌های نظامی", callback_data="country_factories")],
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
    buttons.append([InlineKeyboardButton("☢️ ساخت نیروگاه اتمی", callback_data="build_power_industrial")])
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
#  فاز ۳: منوی کارخونه‌های نظامی
# ============================================================
FACTORY_TYPES = {
    "tank": ("🛡️ کارخونه تانک‌سازی", "🚜"),
    "jet": ("✈️ کارخونه جنگنده‌سازی", "✈️"),
    "ship": ("🚢 کارخونه کشتی‌سازی", "🚢"),
    "missile": ("🚀 کارخونه موشک‌سازی", "🚀"),
}


def factories_overview_text(user_id: int) -> str:
    conn = get_db()
    factories = conn.execute("SELECT * FROM factories WHERE user_id=?", (user_id,)).fetchall()
    units = conn.execute("SELECT * FROM military_units WHERE user_id=? AND quantity > 0", (user_id,)).fetchall()
    conn.close()

    text = "🏭 *کارخونه‌های نظامی*\n\n"
    if not factories:
        text += "هنوز هیچ کارخونه‌ای نساختی.\n\n"
    for f in factories:
        label = FACTORY_TYPES.get(f["type"], (f["type"], ""))[0]
        model_code, _, damage, crew = get_factory_active_model(user_id, f)
        text += (f"{label} — سطح {f['level']}\n"
                 f"  📦 انبار: {f['storage_used']:.0f}/{f['storage_cap']} | "
                 f"مدل فعال: {model_code} (دمیج {damage}، خدمه {crew})\n\n")

    if units:
        text += "📦 *انبار واحدهای آماده*\n"
        for u in units:
            text += f"  {u['item_code']} ({u['item_type']}): {u['quantity']:.0f} عدد\n"

    return text


def factories_menu_keyboard(user_id: int):
    conn = get_db()
    owned_types = {r["type"] for r in conn.execute(
        "SELECT type FROM factories WHERE user_id=?", (user_id,)).fetchall()}
    conn.close()

    buttons = []
    for ftype, (label, _) in FACTORY_TYPES.items():
        if ftype in owned_types:
            buttons.append([InlineKeyboardButton(f"⬆️ ارتقای {label}", callback_data=f"upgrade_factory_{ftype}")])
        else:
            buttons.append([InlineKeyboardButton(f"🏗️ ساخت {label}", callback_data=f"build_factory_{ftype}")])
    buttons.append([InlineKeyboardButton("🔄 بروزرسانی", callback_data="country_factories")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu_country")])
    return InlineKeyboardMarkup(buttons)


# ============================================================
#  فاز ۴: پدافند
# ============================================================
DEFENSE_TIER_NAMES = {1: "پدافند سبک (تیر ۱)", 2: "پدافند متوسط (تیر ۲)",
                       3: "پدافند سنگین (تیر ۳)", 4: "پدافند فوق‌سنگین (تیر ۴)"}


def check_and_complete_repairs(user_id: int):
    """اگه زمان تعمیر تموم شده، پدافند رو خودکار فعال می‌کنه (چک lazy)"""
    conn = get_db()
    defs = conn.execute("SELECT * FROM defenses WHERE user_id=? AND under_repair_until IS NOT NULL",
                         (user_id,)).fetchall()
    for d in defs:
        try:
            repair_done = datetime.fromisoformat(d["under_repair_until"])
        except (ValueError, TypeError):
            continue
        if datetime.utcnow() >= repair_done:
            conn.execute("UPDATE defenses SET hits_remaining=max_hits, under_repair_until=NULL WHERE id=?",
                         (d["id"],))
    conn.commit()
    conn.close()


def get_defense_effective_rate(tier: int, level: int) -> float:
    base_rate = float(get_setting(f"defense_tier{tier}_rate") or 10)
    cap_multiplier = 1.2 if tier == 4 else 1.5
    rate = base_rate * (1 + 0.1 * (level - 1))
    return min(rate, base_rate * cap_multiplier)


def get_defense_repair_hours(tier: int) -> float:
    base_hours = float(get_setting("defense_repair_base_hours") or 3)
    return base_hours * (1.2 ** (tier - 1))


def defenses_overview_text(user_id: int) -> str:
    check_and_complete_repairs(user_id)
    conn = get_db()
    defs = {d["tier"]: d for d in conn.execute("SELECT * FROM defenses WHERE user_id=?", (user_id,)).fetchall()}
    conn.close()

    text = "🛡️ *پدافند و دفاع*\n\n"
    for tier in range(1, 5):
        name = DEFENSE_TIER_NAMES[tier]
        d = defs.get(tier)
        if not d:
            text += f"❌ {name} — ساخته نشده\n\n"
            continue
        rate = get_defense_effective_rate(tier, d["level"])
        if d["under_repair_until"]:
            try:
                until = datetime.fromisoformat(d["under_repair_until"])
                remaining_min = max(0, int((until - datetime.utcnow()).total_seconds() / 60))
                status = f"🔧 در حال تعمیر ({remaining_min} دقیقه مونده)"
            except (ValueError, TypeError):
                status = "🔧 در حال تعمیر"
        else:
            status = f"ضربه باقی‌مانده: {d['hits_remaining']}/{d['max_hits']}"
        text += (f"✅ {name} — سطح {d['level']}\n"
                 f"  🎯 نرخ رهگیری: {rate:.0f}٪ | {status}\n\n")
    return text


def defenses_menu_keyboard(user_id: int):
    conn = get_db()
    defs = {d["tier"]: d for d in conn.execute("SELECT * FROM defenses WHERE user_id=?", (user_id,)).fetchall()}
    conn.close()

    buttons = []
    for tier in range(1, 5):
        d = defs.get(tier)
        name = DEFENSE_TIER_NAMES[tier].split(" (")[0]
        if not d:
            buttons.append([InlineKeyboardButton(f"🏗️ ساخت {name}", callback_data=f"build_defense_{tier}")])
        else:
            row = [InlineKeyboardButton(f"⬆️ ارتقای {name}", callback_data=f"upgrade_defense_{tier}")]
            if d["hits_remaining"] <= 0 and not d["under_repair_until"]:
                row.append(InlineKeyboardButton(f"🔧 تعمیر {name}", callback_data=f"repair_defense_{tier}"))
            buttons.append(row)
    buttons.append([InlineKeyboardButton("🔄 بروزرسانی", callback_data="menu_defense")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت به منو", callback_data="menu_main")])
    return InlineKeyboardMarkup(buttons)


def get_defense_repair_cost(tier: int) -> dict:
    per_tier = int(get_setting("defense_repair_gold_per_tier") or 300)
    return {"gold": per_tier * tier}


def repair_defense(user_id: int, tier: int) -> bool:
    conn = get_db()
    d = conn.execute("SELECT * FROM defenses WHERE user_id=? AND tier=?", (user_id, tier)).fetchone()
    if not d or d["hits_remaining"] > 0 or d["under_repair_until"]:
        conn.close()
        return False
    hours = get_defense_repair_hours(tier)
    until = (datetime.utcnow() + timedelta(hours=hours)).isoformat()
    conn.execute("UPDATE defenses SET under_repair_until=? WHERE id=?", (until, d["id"]))
    conn.commit()
    conn.close()
    return True


# ============================================================
#  فاز ۵: جنگ عادی (حمله)
# ============================================================
def get_country_power(user_id: int) -> float:
    """قدرت نظامی تقریبی یه کشور: مجموع (تعداد × دمیج) همه واحدهای نظامی"""
    conn = get_db()
    units = conn.execute("SELECT quantity, damage_per_unit FROM military_units WHERE user_id=?",
                          (user_id,)).fetchall()
    conn.close()
    return sum(u["quantity"] * u["damage_per_unit"] for u in units)


def power_gap_percent(power_a: float, power_b: float) -> float:
    higher = max(power_a, power_b, 1)
    return abs(power_a - power_b) / higher * 100


def get_owned_units(user_id: int):
    conn = get_db()
    units = conn.execute("SELECT * FROM military_units WHERE user_id=? AND quantity > 0", (user_id,)).fetchall()
    conn.close()
    return units


def get_attack_cart(user_id: int):
    pending = get_pending_action(user_id)
    if pending and pending["action"] == "attack_cart":
        return pending["data"].get("cart", [])
    return []


def save_attack_cart(user_id: int, cart: list):
    set_pending_action(user_id, "attack_cart", {"cart": cart})


def cart_total_damage(user_id: int, cart: list) -> float:
    conn = get_db()
    total = 0.0
    for item in cart:
        u = conn.execute("SELECT damage_per_unit FROM military_units WHERE user_id=? AND item_code=?",
                          (user_id, item["item_code"])).fetchone()
        if u:
            total += item["quantity"] * u["damage_per_unit"]
    conn.close()
    return total


def get_valid_targets(user_id: int):
    """لیست کشورهایی که تفاوت قدرتشون با بازیکن کمتر از حد مجازه (بدون نیاز به تایید ادمین)"""
    my_power = get_country_power(user_id)
    gap_limit = float(get_setting("war_power_gap_percent") or 70)
    max_shown = int(get_setting("war_max_targets_shown") or 15)

    conn = get_db()
    players = conn.execute("SELECT user_id, country_name, protection_until FROM players WHERE user_id != ?",
                            (user_id,)).fetchall()
    conn.close()

    now = datetime.utcnow()
    valid, needs_admin = [], []
    for p in players:
        try:
            protected = p["protection_until"] and datetime.fromisoformat(p["protection_until"]) > now
        except (ValueError, TypeError):
            protected = False
        if protected:
            continue
        their_power = get_country_power(p["user_id"])
        gap = power_gap_percent(my_power, their_power)
        entry = {"user_id": p["user_id"], "name": p["country_name"] or f"کشور #{p['user_id']}",
                 "power": their_power, "gap": gap}
        if gap <= gap_limit:
            valid.append(entry)
        else:
            needs_admin.append(entry)

    valid.sort(key=lambda x: x["gap"])
    return valid[:max_shown], needs_admin[:max_shown]


def submit_attack(attacker_id: int, defender_id: int, cart: list):
    """حمله رو نهایی می‌کنه: واحدها مصرف می‌شن، دمیج محاسبه و بعد از کسر پدافند، نتیجه فوری اعمال می‌شه.
    (توجه: تا فاز زمان‌بند/APScheduler اضافه بشه، نتیجه بلافاصله محاسبه می‌شه نه بعد از ۲ ساعت واقعی)"""
    conn = get_db()

    # کسر واحدهای مصرف‌شده و محاسبه دمیج خام
    raw_damage = 0.0
    for item in cart:
        u = conn.execute("SELECT * FROM military_units WHERE user_id=? AND item_code=?",
                          (attacker_id, item["item_code"])).fetchone()
        if not u or u["quantity"] < item["quantity"]:
            conn.close()
            return None  # موجودی کافی نیست، احتمالاً بین انتخاب و تایید چیزی تغییر کرده
        raw_damage += item["quantity"] * u["damage_per_unit"]
        conn.execute("UPDATE military_units SET quantity = quantity - ? WHERE id=?",
                     (item["quantity"], u["id"]))

    # محاسبه پدافند فعال مدافع (فقط تیرهایی که در حال تعمیر نیستن)
    defenses = conn.execute(
        "SELECT * FROM defenses WHERE user_id=? AND under_repair_until IS NULL", (defender_id,)
    ).fetchall()
    total_intercept_rate = 0.0
    active_defense_ids = []
    for d in defenses:
        if d["hits_remaining"] > 0:
            total_intercept_rate += get_defense_effective_rate(d["tier"], d["level"])
            active_defense_ids.append(d["id"])
    total_intercept_rate = min(total_intercept_rate, 100.0)

    blocked_damage = raw_damage * (total_intercept_rate / 100.0)
    effective_damage = max(0.0, raw_damage - blocked_damage)

    # هر پدافند فعال یه ضربه می‌خوره (مصرف hits_remaining)
    for d_id in active_defense_ids:
        conn.execute("UPDATE defenses SET hits_remaining = hits_remaining - 1 WHERE id=?", (d_id,))

    cap_per_dmg = float(get_setting("war_cap_reward_per_effective_damage") or 0.2)
    consolation_rate = float(get_setting("war_cap_consolation_defender") or 0.1)

    if effective_damage > 0:
        result = "attacker_win"
        cap_reward = round(effective_damage * cap_per_dmg)
        conn.execute("UPDATE players SET cap_points = cap_points + ? WHERE user_id=?",
                     (cap_reward, attacker_id))
    else:
        result = "defender_win"
        cap_reward = round(raw_damage * consolation_rate)
        conn.execute("UPDATE players SET cap_points = cap_points + ? WHERE user_id=?",
                     (cap_reward, defender_id))

    now = now_str()
    war_hours = float(get_setting("war_regular_duration_hours") or 2)
    end_time = (datetime.utcnow() + timedelta(hours=war_hours)).isoformat()
    cur = conn.execute("""
        INSERT INTO war_regular (attacker_id, defender_id, status, total_damage, defense_blocked,
                                  start_time, end_time, result)
        VALUES (?, ?, 'finished', ?, ?, ?, ?, ?)
    """, (attacker_id, defender_id, round(raw_damage, 1), round(blocked_damage, 1), now, end_time, result))
    war_id = cur.lastrowid

    conn.commit()
    conn.close()

    return {
        "war_id": war_id, "result": result, "raw_damage": round(raw_damage, 1),
        "blocked_damage": round(blocked_damage, 1), "effective_damage": round(effective_damage, 1),
        "intercept_rate": round(total_intercept_rate, 1), "cap_reward": cap_reward
    }


def attack_menu_text(user_id: int) -> str:
    cart = get_attack_cart(user_id)
    if not cart:
        return "⚔️ *حمله*\n\nهنوز واحدی برای حمله انتخاب نکردی."
    total = cart_total_damage(user_id, cart)
    lines = ["⚔️ *حمله* — سبد فعلی:\n"]
    for item in cart:
        lines.append(f"  🔹 {item['item_code']} × {item['quantity']}")
    lines.append(f"\n💥 مجموع دمیج: {total:.0f}")
    return "\n".join(lines)


def attack_menu_keyboard(user_id: int):
    cart = get_attack_cart(user_id)
    buttons = [[InlineKeyboardButton("➕ افزودن واحد", callback_data="attack_add_unit")]]
    if cart:
        buttons.append([InlineKeyboardButton("🎯 انتخاب هدف و ارسال", callback_data="attack_choose_target")])
        buttons.append([InlineKeyboardButton("🗑 خالی کردن سبد", callback_data="attack_clear_cart")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت به منو", callback_data="menu_main")])
    return InlineKeyboardMarkup(buttons)


def attack_unit_picker_keyboard(user_id: int):
    units = get_owned_units(user_id)
    if not units:
        return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="menu_attack")]])
    buttons = []
    for u in units:
        buttons.append([InlineKeyboardButton(
            f"{u['item_code']} (موجود: {u['quantity']:.0f})", callback_data=f"attack_pick_{u['item_code']}"
        )])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu_attack")])
    return InlineKeyboardMarkup(buttons)


def target_list_keyboard(user_id: int):
    valid, needs_admin = get_valid_targets(user_id)
    buttons = []
    for t in valid:
        buttons.append([InlineKeyboardButton(
            f"🎯 {t['name']} (قدرت: {t['power']:.0f})", callback_data=f"attack_target_{t['user_id']}"
        )])
    if not valid:
        buttons.append([InlineKeyboardButton("❌ هدف مناسبی پیدا نشد", callback_data="menu_attack")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu_attack")])
    return InlineKeyboardMarkup(buttons), len(needs_admin)


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


def quantity_prompt_keyboard(action_key: str, back_target: str = "country_build"):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔢 تعداد دلخواه (بنویس)", callback_data=f"qty_custom_{action_key}")],
        [InlineKeyboardButton("⬆️ حداکثر ممکن", callback_data=f"qty_max_{action_key}")],
        [InlineKeyboardButton("🔙 لغو", callback_data=back_target)],
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

    if action_key.startswith("upgrade_factory_"):
        ftype = action_key.replace("upgrade_factory_", "")
        conn = get_db()
        f = conn.execute("SELECT level FROM factories WHERE user_id=? AND type=?",
                          (user_id, ftype)).fetchone()
        conn.close()
        current_level = f["level"] if f else 1
        base_g = int(get_setting("factory_upgrade_base_gold") or 600)
        base_m = int(get_setting("factory_upgrade_base_metal") or 150)
        total_gold, total_metal = 0, 0
        for i in range(quantity):
            lvl = current_level + i
            total_gold += base_g * lvl
            total_metal += base_m * lvl
        return {"gold": total_gold, "metal": total_metal}

    if action_key.startswith("upgrade_defense_"):
        tier = int(action_key.replace("upgrade_defense_", ""))
        conn = get_db()
        d = conn.execute("SELECT level FROM defenses WHERE user_id=? AND tier=?",
                          (user_id, tier)).fetchone()
        conn.close()
        current_level = d["level"] if d else 1
        base_g = int(get_setting("defense_upgrade_base_gold") or 500)
        base_m = int(get_setting("defense_upgrade_base_metal") or 100)
        total_gold, total_metal = 0, 0
        for i in range(quantity):
            lvl = (current_level + i) * tier  # سطح‌بالاتر تیر = گرون‌تر
            total_gold += base_g * lvl
            total_metal += base_m * lvl
        return {"gold": total_gold, "metal": total_metal}

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

    if action_key == "build_power_industrial":
        g = int(get_setting("power_industrial_build_gold") or 2000)
        m = int(get_setting("power_industrial_build_metal") or 400)
        return {"gold": g * quantity, "metal": m * quantity}

    if action_key.startswith("build_factory_"):
        ftype = action_key.replace("build_factory_", "")
        g = int(get_setting(f"factory_{ftype}_build_gold") or 1500)
        m = int(get_setting(f"factory_{ftype}_build_metal") or 300)
        return {"gold": g * quantity, "metal": m * quantity}

    if action_key.startswith("build_defense_"):
        tier = int(action_key.replace("build_defense_", ""))
        g = int(get_setting(f"defense_tier{tier}_build_gold") or 1000)
        m = int(get_setting(f"defense_tier{tier}_build_metal") or 200)
        return {"gold": g * quantity, "metal": m * quantity}

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

    # هر کارخونه فقط یه بار قابل ساخته - بعدش فقط ارتقا داره
    if action_key.startswith("build_factory_"):
        max_q = min(max_q, 1)

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

    elif action_key.startswith("upgrade_factory_"):
        ftype = action_key.replace("upgrade_factory_", "")
        base_storage = int(get_setting("factory_storage_base") or 20)
        f = conn.execute("SELECT level FROM factories WHERE user_id=? AND type=?",
                          (user_id, ftype)).fetchone()
        new_level = (f["level"] if f else 1) + quantity
        new_cap = int(base_storage * (1 + 0.5 * (new_level - 1)))
        conn.execute("UPDATE factories SET level=?, storage_cap=? WHERE user_id=? AND type=?",
                      (new_level, new_cap, user_id, ftype))

    elif action_key.startswith("upgrade_defense_"):
        tier = int(action_key.replace("upgrade_defense_", ""))
        conn.execute("UPDATE defenses SET level = level + ? WHERE user_id=? AND tier=?",
                      (quantity, user_id, tier))

    elif action_key.startswith("upgrade_"):
        b_type = action_key.replace("upgrade_", "")
        conn.execute("UPDATE buildings SET level = level + ? WHERE user_id=? AND type=?",
                      (quantity, user_id, b_type))

    elif action_key == "land_upgrade":
        conn.execute("UPDATE players SET land_length = land_length + ? WHERE user_id=?",
                      (quantity * 10, user_id))

    elif action_key == "build_power_industrial":
        for _ in range(quantity):
            conn.execute("""INSERT INTO buildings (user_id, type, level, hp, built_at)
                             VALUES (?, 'power_industrial', 1, 0, ?)""", (user_id, now_str()))

    elif action_key.startswith("build_factory_"):
        ftype = action_key.replace("build_factory_", "")
        base_storage = int(get_setting("factory_storage_base") or 20)
        conn.execute("""INSERT INTO factories (user_id, type, level, storage_used, storage_cap, blueprint_id)
                         VALUES (?, ?, 1, 0, ?, NULL)""", (user_id, ftype, base_storage))

    elif action_key.startswith("build_defense_"):
        tier = int(action_key.replace("build_defense_", ""))
        max_hits = int(get_setting(f"defense_tier{tier}_max_hits") or 6)
        conn.execute("""INSERT INTO defenses (user_id, tier, level, hits_remaining, max_hits)
                         VALUES (?, ?, 1, ?, ?)""", (user_id, tier, max_hits, max_hits))

    conn.commit()
    conn.close()


def result_back_button(action_key: str):
    if "factory" in action_key:
        target, label = "country_factories", "🔙 بازگشت به کارخونه‌ها"
    elif "defense" in action_key:
        target, label = "menu_defense", "🔙 بازگشت به پدافند"
    else:
        target, label = "menu_country", "🔙 بازگشت به کشور من"
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=target)]])


ACTION_LABELS = {
    "build_house": "ساخت خونه",
    "build_power_civil": "ساخت نیروگاه عادی",
    "build_power_industrial": "ساخت نیروگاه اتمی",
    "build_mine_metal": "ساخت معدن فلز",
    "upgrade_farm": "ارتقای مزرعه",
    "upgrade_mine_fertilizer": "ارتقای معدن کود",
    "upgrade_mine_oil": "ارتقای معدن نفت",
    "upgrade_mine_metal": "ارتقای معدن فلز",
    "land_upgrade": "ارتقای طول کشور",
    "build_factory_tank": "ساخت کارخونه تانک‌سازی",
    "build_factory_jet": "ساخت کارخونه جنگنده‌سازی",
    "build_factory_ship": "ساخت کارخونه کشتی‌سازی",
    "build_factory_missile": "ساخت کارخونه موشک‌سازی",
    "upgrade_factory_tank": "ارتقای کارخونه تانک‌سازی",
    "upgrade_factory_jet": "ارتقای کارخونه جنگنده‌سازی",
    "upgrade_factory_ship": "ارتقای کارخونه کشتی‌سازی",
    "upgrade_factory_missile": "ارتقای کارخونه موشک‌سازی",
    "build_defense_1": "ساخت پدافند سبک (تیر ۱)",
    "build_defense_2": "ساخت پدافند متوسط (تیر ۲)",
    "build_defense_3": "ساخت پدافند سنگین (تیر ۳)",
    "build_defense_4": "ساخت پدافند فوق‌سنگین (تیر ۴)",
    "upgrade_defense_1": "ارتقای پدافند سبک (تیر ۱)",
    "upgrade_defense_2": "ارتقای پدافند متوسط (تیر ۲)",
    "upgrade_defense_3": "ارتقای پدافند سنگین (تیر ۳)",
    "upgrade_defense_4": "ارتقای پدافند فوق‌سنگین (تیر ۴)",
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

    if query.data == "menu_defense":
        await query.edit_message_text(
            defenses_overview_text(user_id),
            reply_markup=defenses_menu_keyboard(user_id),
            parse_mode="Markdown"
        )
        return

    if query.data == "menu_attack":
        await query.edit_message_text(
            attack_menu_text(user_id),
            reply_markup=attack_menu_keyboard(user_id),
            parse_mode="Markdown"
        )
        return

    if query.data == "menu_alliance":
        await query.edit_message_text(
            alliance_main_text(user_id),
            reply_markup=alliance_main_keyboard(user_id),
            parse_mode="Markdown"
        )
        return

    # سایر منوها در فازهای بعدی پیاده می‌شن
    placeholder_map = {
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

    if query.data == "country_factories":
        await query.edit_message_text(
            factories_overview_text(user_id),
            reply_markup=factories_menu_keyboard(user_id),
            parse_mode="Markdown"
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
        if "factory" in query.data:
            back_target = "country_factories"
        elif "defense" in query.data:
            back_target = "menu_defense"
        else:
            back_target = "country_build"
        text = f"🔧 {label}\n\nهزینه هر واحد: {cost_to_text(cost1)}\n\nچند تا می‌خوای انجام بدی؟"
        await query.edit_message_text(text, reply_markup=quantity_prompt_keyboard(query.data, back_target))
        return

    # ---- تعمیر پدافند (فوری، بدون نیاز به quantity) ----
    if query.data.startswith("repair_defense_"):
        tier = int(query.data.replace("repair_defense_", ""))
        cost = get_defense_repair_cost(tier)
        if not can_afford(user_id, cost):
            await safe_answer(query, f"پول کافی نداری. هزینه تعمیر: {cost_to_text(cost)}", show_alert=True)
            return
        success = repair_defense(user_id, tier)
        if success:
            deduct_cost(user_id, cost)
            hours = get_defense_repair_hours(tier)
            await query.edit_message_text(
                f"🔧 تعمیر پدافند تیر {tier} شروع شد. زمان تعمیر: {hours:.1f} ساعت\n"
                f"هزینه: {cost_to_text(cost)}",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 بازگشت", callback_data="menu_defense")]])
            )
        else:
            await safe_answer(query, "این پدافند الان نیازی به تعمیر نداره یا در حال تعمیره.", show_alert=True)
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
            reply_markup=result_back_button(action_key)
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

    # ---- ورودی‌های متنی غیرعددی (اسم اتحاد) ----
    if pending["action"] == "alliance_create_name":
        if len(text) < 2 or len(text) > 30:
            await update.message.reply_text("⚠️ اسم باید بین ۲ تا ۳۰ کاراکتر باشه.")
            return
        alliance_id, error = create_alliance(user_id, text)
        clear_pending_action(user_id)
        if alliance_id:
            await update.message.reply_text(
                f"✅ اتحاد «{text}» ساخته شد!",
                reply_markup=alliance_main_keyboard(user_id)
            )
        else:
            await update.message.reply_text(f"❌ {error}")
        return

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
            reply_markup=result_back_button(action_key)
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

    if pending["action"] == "attack_pick_quantity":
        item_code = pending["data"]["item_code"]
        conn = get_db()
        u = conn.execute("SELECT * FROM military_units WHERE user_id=? AND item_code=?",
                          (user_id, item_code)).fetchone()
        conn.close()
        if not u or u["quantity"] < quantity:
            max_available = u["quantity"] if u else 0
            await update.message.reply_text(f"❌ موجودی کافی نیست. حداکثر موجود: {max_available:.0f}")
            return
        cart = get_attack_cart(user_id)
        # اگه قبلاً این واحد تو سبد بود، جمعش کن
        found = False
        for item in cart:
            if item["item_code"] == item_code:
                item["quantity"] += quantity
                found = True
                break
        if not found:
            cart.append({"item_code": item_code, "quantity": quantity})
        save_attack_cart(user_id, cart)
        await update.message.reply_text(
            f"✅ {quantity} عدد {item_code} به سبد حمله اضافه شد.",
            reply_markup=attack_menu_keyboard(user_id)
        )
        return

    if pending["action"] == "gift_amount":
        receiver_id = pending["data"]["receiver_id"]
        resource_type = pending["data"]["resource_type"]
        clear_pending_action(user_id)
        success, error = send_gift(user_id, receiver_id, resource_type, quantity)
        if success:
            res_label = "پول" if resource_type == "gold" else "کاپ"
            await update.message.reply_text(
                f"✅ {quantity} {res_label} گیفت داده شد.",
                reply_markup=alliance_main_keyboard(user_id)
            )
            try:
                await context.bot.send_message(receiver_id, f"🎁 {quantity} {res_label} از هم‌اتحادیت گیفت گرفتی!")
            except Exception:
                pass
        else:
            await update.message.reply_text(f"❌ {error}")
        return

    if pending["action"] == "vault_contribute_amount":
        resource_type = pending["data"]["resource_type"]
        clear_pending_action(user_id)
        success, error = contribute_to_vault(user_id, resource_type, quantity)
        if success:
            res_label = "پول" if resource_type == "gold" else "کاپ"
            await update.message.reply_text(
                f"✅ {quantity} {res_label} به گاوصندوق اتحاد واریز شد.",
                reply_markup=alliance_main_keyboard(user_id)
            )
        else:
            await update.message.reply_text(f"❌ {error}")
        return


# ============================================================
#  فاز ۵: هندلر بخش «حمله»
# ============================================================
async def attack_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_answer(query)
    user_id = update.effective_user.id

    if query.data == "attack_add_unit":
        units = get_owned_units(user_id)
        if not units:
            await query.edit_message_text(
                "❌ هنوز هیچ واحد نظامی نساختی. اول از بخش «کارخونه‌های نظامی» چیزی بساز.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 بازگشت", callback_data="menu_attack")]])
            )
            return
        await query.edit_message_text(
            "کدوم واحد رو می‌خوای اضافه کنی؟",
            reply_markup=attack_unit_picker_keyboard(user_id)
        )
        return

    if query.data.startswith("attack_pick_"):
        item_code = query.data.replace("attack_pick_", "")
        set_pending_action(user_id, "attack_pick_quantity", {"item_code": item_code})
        conn = get_db()
        u = conn.execute("SELECT quantity FROM military_units WHERE user_id=? AND item_code=?",
                          (user_id, item_code)).fetchone()
        conn.close()
        await query.edit_message_text(
            f"چند تا {item_code} می‌خوای بفرستی؟ (موجود: {u['quantity']:.0f})\n"
            f"عدد رو تایپ کن."
        )
        return

    if query.data == "attack_clear_cart":
        clear_pending_action(user_id)
        await query.edit_message_text(
            attack_menu_text(user_id),
            reply_markup=attack_menu_keyboard(user_id),
            parse_mode="Markdown"
        )
        return

    if query.data == "attack_choose_target":
        cart = get_attack_cart(user_id)
        if not cart:
            await safe_answer(query, "سبد حمله خالیه", show_alert=True)
            return
        kb, admin_needed_count = target_list_keyboard(user_id)
        note = ""
        if admin_needed_count:
            note = (f"\n\nℹ️ {admin_needed_count} کشور دیگه هم هستن که تفاوت قدرتشون باهات بیشتر از حد مجازه؛ "
                    f"حمله بهشون نیاز به تایید دستی ادمین داره (این قابلیت در فاز پنل ادمین اضافه می‌شه).")
        await query.edit_message_text(
            f"🎯 یه هدف انتخاب کن:{note}",
            reply_markup=kb
        )
        return

    if query.data.startswith("attack_target_"):
        defender_id = int(query.data.replace("attack_target_", ""))
        cart = get_attack_cart(user_id)
        if not cart:
            await safe_answer(query, "سبد حمله خالیه", show_alert=True)
            return

        result = submit_attack(user_id, defender_id, cart)
        clear_pending_action(user_id)

        if result is None:
            await query.edit_message_text(
                "❌ موجودی واحدها تغییر کرده بود، حمله لغو شد. دوباره امتحان کن.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 بازگشت", callback_data="menu_attack")]])
            )
            return

        outcome_text = "🎉 پیروزی!" if result["result"] == "attacker_win" else "😔 دفاع حریف موفق بود"
        text = (
            f"⚔️ *نتیجه حمله*\n\n{outcome_text}\n\n"
            f"💥 دمیج خام: {result['raw_damage']}\n"
            f"🛡️ درصد دفع پدافند: {result['intercept_rate']}٪ (دمیج دفع‌شده: {result['blocked_damage']})\n"
            f"✅ دمیج مؤثر: {result['effective_damage']}\n"
            f"🏅 کاپ به‌دست‌اومده: {result['cap_reward']}\n"
        )
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 بازگشت به منو", callback_data="menu_main")]]),
            parse_mode="Markdown"
        )

        # اطلاع به مالک کشور مورد حمله
        try:
            await context.bot.send_message(
                defender_id,
                f"🚨 کشور شما مورد حمله قرار گرفت!\n"
                f"نتیجه: {'حمله موفق بود' if result['result']=='attacker_win' else 'دفاع شما موفق بود'}\n"
                f"دمیج مؤثر وارده: {result['effective_damage']}"
            )
        except Exception:
            pass
        return


# ============================================================
#  فاز ۶: اتحاد
# ============================================================
def get_alliance(alliance_id: int):
    conn = get_db()
    a = conn.execute("SELECT * FROM alliances WHERE id=?", (alliance_id,)).fetchone()
    conn.close()
    return a


def get_player_alliance(user_id: int):
    conn = get_db()
    p = conn.execute("SELECT alliance_id FROM players WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    if not p or not p["alliance_id"]:
        return None
    return get_alliance(p["alliance_id"])


def get_alliance_members(alliance_id: int):
    conn = get_db()
    members = conn.execute("SELECT user_id, country_name, alliance_join_date FROM players WHERE alliance_id=?",
                            (alliance_id,)).fetchall()
    conn.close()
    return members


def is_on_alliance_cooldown(user_id: int) -> bool:
    conn = get_db()
    p = conn.execute("SELECT alliance_cooldown_until FROM players WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    if not p or not p["alliance_cooldown_until"]:
        return False
    try:
        return datetime.fromisoformat(p["alliance_cooldown_until"]) > datetime.utcnow()
    except (ValueError, TypeError):
        return False


def create_alliance(user_id: int, name: str):
    conn = get_db()
    p = conn.execute("SELECT alliance_id, gold, is_admin FROM players WHERE user_id=?", (user_id,)).fetchone()
    if p["alliance_id"]:
        conn.close()
        return None, "قبلاً عضو یه اتحاد هستی."

    cost = int(get_setting("alliance_create_gold_cost") or 3000)
    if not p["is_admin"] and p["gold"] < cost:
        conn.close()
        return None, f"پول کافی نداری. هزینه ساخت اتحاد: {cost} پول."

    is_admin_alliance = 1 if p["is_admin"] else 0
    max_members = 999999 if is_admin_alliance else int(get_setting("alliance_default_max_members") or 5)

    if not p["is_admin"]:
        conn.execute("UPDATE players SET gold = gold - ? WHERE user_id=?", (cost, user_id))

    cur = conn.execute("""
        INSERT INTO alliances (name, leader_id, max_members, vault_gold, vault_cap, is_admin_alliance, created_at)
        VALUES (?, ?, ?, 0, 0, ?, ?)
    """, (name, user_id, max_members, is_admin_alliance, now_str()))
    alliance_id = cur.lastrowid

    conn.execute("UPDATE players SET alliance_id=?, alliance_join_date=? WHERE user_id=?",
                 (alliance_id, now_str(), user_id))
    conn.commit()
    conn.close()
    return alliance_id, None


def join_alliance(user_id: int, alliance_id: int, force: bool = False):
    conn = get_db()
    p = conn.execute("SELECT alliance_id FROM players WHERE user_id=?", (user_id,)).fetchone()
    if p["alliance_id"]:
        conn.close()
        return False, "قبلاً عضو یه اتحاد هستی."

    if not force and is_on_alliance_cooldown(user_id):
        conn.close()
        return False, "به‌خاطر ترک/اخراج اخیر، هنوز نمی‌تونی به اتحاد جدید بپیوندی."

    a = conn.execute("SELECT * FROM alliances WHERE id=?", (alliance_id,)).fetchone()
    if not a:
        conn.close()
        return False, "اتحاد پیدا نشد."

    if not a["is_admin_alliance"]:
        member_count = conn.execute("SELECT COUNT(*) as c FROM players WHERE alliance_id=?",
                                     (alliance_id,)).fetchone()["c"]
        if member_count >= a["max_members"]:
            conn.close()
            return False, "این اتحاد پره."

    conn.execute("UPDATE players SET alliance_id=?, alliance_join_date=?, alliance_cooldown_until=NULL WHERE user_id=?",
                 (alliance_id, now_str(), user_id))
    conn.commit()
    conn.close()
    return True, None


def leave_alliance(user_id: int):
    conn = get_db()
    p = conn.execute("SELECT alliance_id FROM players WHERE user_id=?", (user_id,)).fetchone()
    if not p["alliance_id"]:
        conn.close()
        return False, "تو هیچ اتحادی نیستی."

    a = conn.execute("SELECT * FROM alliances WHERE id=?", (p["alliance_id"],)).fetchone()
    if a and a["leader_id"] == user_id:
        member_count = conn.execute("SELECT COUNT(*) as c FROM players WHERE alliance_id=?",
                                     (a["id"],)).fetchone()["c"]
        if member_count > 1:
            conn.close()
            return False, "رهبر نمی‌تونه وقتی عضو دیگه‌ای هست اتحاد رو ترک کنه (باید همه رو اخراج کنی)."

    cooldown_hours = int(get_setting("alliance_leave_cooldown_hours") or 24)
    cooldown_until = (datetime.utcnow() + timedelta(hours=cooldown_hours)).isoformat()
    conn.execute("UPDATE players SET alliance_id=NULL, alliance_cooldown_until=? WHERE user_id=?",
                 (cooldown_until, user_id))

    # اگه رهبر بود و تنها عضو بود، اتحاد رو حذف کن (به جز اتحاد ادمین)
    if a and a["leader_id"] == user_id and not a["is_admin_alliance"]:
        conn.execute("DELETE FROM alliances WHERE id=?", (a["id"],))

    conn.commit()
    conn.close()
    return True, None


def kick_member(actor_id: int, target_id: int):
    conn = get_db()
    actor = conn.execute("SELECT alliance_id, is_admin FROM players WHERE user_id=?", (actor_id,)).fetchone()
    target = conn.execute("SELECT alliance_id FROM players WHERE user_id=?", (target_id,)).fetchone()

    if not target["alliance_id"]:
        conn.close()
        return False, "این بازیکن عضو هیچ اتحادی نیست."

    a = conn.execute("SELECT * FROM alliances WHERE id=?", (target["alliance_id"],)).fetchone()
    is_leader = a and a["leader_id"] == actor_id
    if not is_leader and not actor["is_admin"]:
        conn.close()
        return False, "فقط رهبر اتحاد یا ادمین می‌تونه عضو رو اخراج کنه."

    cooldown_hours = int(get_setting("alliance_kick_cooldown_hours") or 12)
    cooldown_until = (datetime.utcnow() + timedelta(hours=cooldown_hours)).isoformat()
    conn.execute("UPDATE players SET alliance_id=NULL, alliance_cooldown_until=? WHERE user_id=?",
                 (cooldown_until, target_id))
    conn.commit()
    conn.close()
    return True, None


def can_send_gift(user_id: int) -> bool:
    conn = get_db()
    p = conn.execute("SELECT last_gift_at FROM players WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    if not p or not p["last_gift_at"]:
        return True
    cooldown_hours = int(get_setting("alliance_gift_cooldown_hours") or 12)
    try:
        next_allowed = datetime.fromisoformat(p["last_gift_at"]) + timedelta(hours=cooldown_hours)
        return datetime.utcnow() >= next_allowed
    except (ValueError, TypeError):
        return True


def send_gift(sender_id: int, receiver_id: int, resource_type: str, amount: int):
    conn = get_db()
    sender = conn.execute("SELECT * FROM players WHERE user_id=?", (sender_id,)).fetchone()
    receiver = conn.execute("SELECT alliance_id FROM players WHERE user_id=?", (receiver_id,)).fetchone()

    if sender["alliance_id"] != receiver["alliance_id"] or sender["alliance_id"] is None:
        conn.close()
        return False, "فقط می‌تونی به هم‌اتحادی‌هات گیفت بدی."

    if not can_send_gift(sender_id):
        conn.close()
        return False, "هنوز کول‌داون گیفت قبلی‌ت تموم نشده (۱۲ ساعت)."

    current_amount = sender["gold"] if resource_type == "gold" else sender["cap_points"]
    max_percent = int(get_setting("alliance_gift_max_percent") or 50)
    max_allowed = current_amount * max_percent / 100

    if amount <= 0 or amount > max_allowed:
        conn.close()
        return False, f"حداکثر می‌تونی {max_allowed:.0f} واحد ({max_percent}٪ دارایی‌ت) گیفت بدی."

    field = "gold" if resource_type == "gold" else "cap_points"
    conn.execute(f"UPDATE players SET {field} = {field} - ? WHERE user_id=?", (amount, sender_id))
    conn.execute(f"UPDATE players SET {field} = {field} + ? WHERE user_id=?", (amount, receiver_id))
    conn.execute("UPDATE players SET last_gift_at=? WHERE user_id=?", (now_str(), sender_id))
    conn.execute("""INSERT INTO transactions (from_user, to_user, type, item, amount, timestamp)
                     VALUES (?, ?, 'gift', ?, ?, ?)""",
                 (sender_id, receiver_id, resource_type, amount, now_str()))
    conn.commit()
    conn.close()
    return True, None


def contribute_to_vault(user_id: int, resource_type: str, amount: int):
    conn = get_db()
    p = conn.execute("SELECT * FROM players WHERE user_id=?", (user_id,)).fetchone()
    if not p["alliance_id"]:
        conn.close()
        return False, "تو هیچ اتحادی نیستی."

    current_amount = p["gold"] if resource_type == "gold" else p["cap_points"]
    if amount <= 0 or amount > current_amount:
        conn.close()
        return False, "موجودی کافی نداری."

    field = "gold" if resource_type == "gold" else "cap_points"
    vault_field = "vault_gold" if resource_type == "gold" else "vault_cap"
    conn.execute(f"UPDATE players SET {field} = {field} - ? WHERE user_id=?", (amount, user_id))
    conn.execute(f"UPDATE alliances SET {vault_field} = {vault_field} + ? WHERE id=?", (amount, p["alliance_id"]))
    conn.commit()
    conn.close()
    return True, None


def alliance_main_text(user_id: int) -> str:
    a = get_player_alliance(user_id)
    if not a:
        return "🤝 *اتحاد*\n\nتو هنوز عضو هیچ اتحادی نیستی."

    members = get_alliance_members(a["id"])
    leader_name = "نامشخص"
    for m in members:
        if m["user_id"] == a["leader_id"]:
            leader_name = m["country_name"] or f"#{m['user_id']}"
            break

    text = (
        f"🤝 *اتحاد: {a['name']}*\n\n"
        f"👑 رهبر: {leader_name}\n"
        f"👥 اعضا: {len(members)}/{'نامحدود' if a['is_admin_alliance'] else a['max_members']}\n"
        f"💰 گاوصندوق پول: {a['vault_gold']}\n"
        f"🏅 گاوصندوق کاپ: {a['vault_cap']}\n\n"
        f"*لیست اعضا:*\n"
    )
    for m in members:
        tag = " 👑" if m["user_id"] == a["leader_id"] else ""
        member_label = m["country_name"] or f"#{m['user_id']}"
        text += f"  • {member_label}{tag}\n"
    return text


def alliance_main_keyboard(user_id: int):
    a = get_player_alliance(user_id)
    if not a:
        buttons = [
            [InlineKeyboardButton("🏗️ ساخت اتحاد جدید", callback_data="alliance_create")],
            [InlineKeyboardButton("📋 لیست اتحادهای قابل‌عضویت", callback_data="alliance_list")],
        ]
    else:
        buttons = [
            [InlineKeyboardButton("🎁 گیفت به عضو", callback_data="alliance_gift")],
            [InlineKeyboardButton("💰 واریز به گاوصندوق", callback_data="alliance_contribute")],
        ]
        if a["leader_id"] == user_id and not a["is_admin_alliance"]:
            buttons.append([InlineKeyboardButton("👢 اخراج عضو", callback_data="alliance_kick")])
        buttons.append([InlineKeyboardButton("🚪 ترک اتحاد", callback_data="alliance_leave")])
    buttons.append([InlineKeyboardButton("🔄 بروزرسانی", callback_data="menu_alliance")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت به منو", callback_data="menu_main")])
    return InlineKeyboardMarkup(buttons)


def alliance_join_list_keyboard():
    conn = get_db()
    alliances = conn.execute("SELECT * FROM alliances WHERE is_admin_alliance=0").fetchall()
    conn.close()
    buttons = []
    for a in alliances:
        member_count = len(get_alliance_members(a["id"]))
        if member_count < a["max_members"]:
            buttons.append([InlineKeyboardButton(
                f"{a['name']} ({member_count}/{a['max_members']})", callback_data=f"alliance_join_{a['id']}"
            )])
    if not buttons:
        buttons.append([InlineKeyboardButton("❌ اتحاد باز موجود نیست", callback_data="menu_alliance")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu_alliance")])
    return InlineKeyboardMarkup(buttons)


def alliance_member_picker_keyboard(user_id: int, prefix: str):
    a = get_player_alliance(user_id)
    if not a:
        return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="menu_alliance")]])
    members = get_alliance_members(a["id"])
    buttons = []
    for m in members:
        if m["user_id"] == user_id:
            continue
        buttons.append([InlineKeyboardButton(
            m["country_name"] or f"#{m['user_id']}", callback_data=f"{prefix}_{m['user_id']}"
        )])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu_alliance")])
    return InlineKeyboardMarkup(buttons)


async def alliance_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_answer(query)
    user_id = update.effective_user.id

    if query.data == "alliance_create":
        set_pending_action(user_id, "alliance_create_name", {})
        await query.edit_message_text("🏗️ اسم اتحادت رو بنویس و بفرست:")
        return

    if query.data == "alliance_list":
        await query.edit_message_text(
            "📋 اتحادهای قابل‌عضویت:",
            reply_markup=alliance_join_list_keyboard()
        )
        return

    if query.data.startswith("alliance_join_"):
        alliance_id = int(query.data.replace("alliance_join_", ""))
        success, error = join_alliance(user_id, alliance_id)
        if success:
            await query.edit_message_text(
                alliance_main_text(user_id),
                reply_markup=alliance_main_keyboard(user_id),
                parse_mode="Markdown"
            )
        else:
            await safe_answer(query, error, show_alert=True)
 if query.data == "alliance_leave":
        success, error = leave_alliance(user_id)
        if success:
            await query.edit_message_text(
                "✅ از اتحاد خارج شدی.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 بازگشت به منو", callback_data="menu_main")]])
            )
        else:
            await safe_answer(query, error, show_alert=True)
        return

    if query.data == "alliance_gift":
        await query.edit_message_text(
            "🎁 به کی می‌خوای گیفت بدی؟",
            reply_markup=alliance_member_picker_keyboard(user_id, "giftpick")
        )
        return

    if query.data.startswith("giftpick_"):
        receiver_id = int(query.data.replace("giftpick_", ""))
        set_pending_action(user_id, "gift_choose_resource", {"receiver_id": receiver_id})
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 پول", callback_data=f"giftres_gold_{receiver_id}")],
            [InlineKeyboardButton("🏅 کاپ", callback_data=f"giftres_cap_{receiver_id}")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="menu_alliance")],
        ])
        await query.edit_message_text("چی می‌خوای گیفت بدی؟", reply_markup=kb)
        return

    if query.data.startswith("giftres_"):
        _, res_type, receiver_id = query.data.split("_")
        set_pending_action(user_id, "gift_amount", {"receiver_id": int(receiver_id), "resource_type": res_type})
        await query.edit_message_text("چقدر می‌خوای گیفت بدی؟ عدد رو تایپ کن.")
        return

    if query.data == "alliance_contribute":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 پول", callback_data="contribres_gold")],
            [InlineKeyboardButton("🏅 کاپ", callback_data="contribres_cap")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="menu_alliance")],
        ])
        await query.edit_message_text("چی می‌خوای به گاوصندوق واریز کنی؟", reply_markup=kb)
        return

    if query.data.startswith("contribres_"):
        res_type = query.data.replace("contribres_", "")
        set_pending_action(user_id, "vault_contribute_amount", {"resource_type": res_type})
        await query.edit_message_text("چقدر می‌خوای واریز کنی؟ عدد رو تایپ کن.")
        return

    if query.data == "alliance_kick":
        await query.edit_message_text(
            "👢 کدوم عضو رو می‌خوای اخراج کنی؟",
            reply_markup=alliance_member_picker_keyboard(user_id, "kickpick")
        )
        return

    if query.data.startswith("kickpick_"):
        target_id = int(query.data.replace("kickpick_", ""))
        success, error = kick_member(user_id, target_id)
        if success:
            await query.edit_message_text(
                f"✅ عضو اخراج شد.",
                reply_markup=alliance_main_keyboard(user_id)
            )
            try:
                await context.bot.send_message(target_id, "🚨 از اتحاد اخراج شدی. تا ۱۲ ساعت نمی‌تونی به اتحاد جدید بپیوندی.")
            except Exception:
                pass
        else:
            await safe_answer(query, error, show_alert=True)
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
    country_patterns = "^(country_|build_|upgrade_|repair_defense_|land_upgrade|qty_custom_|qty_max_|assign_to_|popsrc_)"
    app.add_handler(CallbackQueryHandler(country_build_callback, pattern=country_patterns))

    # فاز ۵: حمله
    app.add_handler(CallbackQueryHandler(attack_callback, pattern="^attack_"))

    # فاز ۶: اتحاد
    alliance_patterns = "^(alliance_|giftpick_|giftres_|contribres_|kickpick_)"
    app.add_handler(CallbackQueryHandler(alliance_callback, pattern=alliance_patterns))

    # پیام‌های متنی (برای وارد کردن تعداد دلخواه) - باید بعد از کامندها ثبت بشه
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_input_handler))

    logger.info("بات در حال اجراست...")
    app.run_polling()


if __name__ == "__main__":
    main()
