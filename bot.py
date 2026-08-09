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
فاز ۷: جنگ اتحادی/قبیله‌ای (اهدای تجهیزات، رأی‌گیری، توالی حمله بر اساس اچ‌پی، پدافند، ۲۰٪ غارت ثروت، جایزه کاپ)
فاز ۸: شاپ‌ها (شاپ ادمین منابع، شاپ کاپ، شاپ نقشه‌ساخت + نصب، بازار بازیکنان با کد یکتا، فروش فوری ۱/۴ قیمت)
فاز ۹: آزمایشگاه/تحقیقات (زره، پالایش نفت، فرآوری فلز، کشاورزی — با اثر واقعی رو دفاع و تولید)
فاز ۱۰: رنکینگ (بر اساس قدرت نظامی)، آمار من (رکورد جنگی، اتحاد، جمعیت)، برداشت روزانه درآمد رفرال (۵٪ از دارایی زیرمجموعه مستقیم، کول‌داون ۲۴ساعته)
فاز ۱۱: کانال اعلامیه (عضویت اجباری با fail-open در خطا، اعلامیه خودکار جنگ/جنگ‌اتحادی، پیام رهبر یا اعضا به نام اتحاد یا کشور خودشون)
فاز ۱۲: پنل ادمین کامل (ویرایشگر قیمت‌ها به تفکیک دسته، تایید/رد حمله‌های خارج از محدوده قدرت، مدیریت/اخراج اجباری اتحادها، آمار روزانه)
فاز ۱۳: زمان‌بند خودکار (جنگ عادی واقعاً ۲ ساعت طول می‌کشه، جنگ اتحادی ۲۴ ساعت، تعمیر پدافند خودکار با اطلاع‌رسانی، تایم‌اوت ۱۲ساعته تایید ادمین، اعمال سپر بعد جنگ اتحادی، رشد جمعیت ۲۴ساعته)
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

    CREATE TABLE IF NOT EXISTS war_alliance_votes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        war_id INTEGER,
        user_id INTEGER,
        vote INTEGER,
        UNIQUE(war_id, user_id)
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

    try:
        cur.execute("ALTER TABLE players ADD COLUMN last_referral_claim TEXT")
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute("ALTER TABLE war_regular ADD COLUMN pending_cart_json TEXT")
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

    # ===== فاز ۷: جنگ اتحادی (قبیله‌ای) =====
    "alliance_war_min_members": "5",
    "alliance_war_vote_threshold_percent": "50",

    # ===== فاز ۸: شاپ‌ها =====
    # شاپ ادمین: قیمت خرید هر واحد منبع (با پول)
    "admin_shop_oil_price": "10",
    "admin_shop_metal_price": "15",
    "admin_shop_fertilizer_price": "5",
    "admin_shop_electricity_price": "8",

    # شاپ کاپ: قیمت هر واحد فلز با کاپ + مقدار گردش آیتم ویژه
    "cap_shop_metal_price": "5",
    "cap_shop_special_item_cap_cost": "200",
    "cap_shop_special_item_gold_reward": "5000",

    # فروش فوری: ارزش پایه هر واحد نظامی (قبل از تقسیم بر نسبت فروش فوری)
    "instant_sell_unit_value_tank": "50",
    "instant_sell_unit_value_jet": "80",
    "instant_sell_unit_value_ship": "120",
    "instant_sell_unit_value_missile": "150",

    # ===== فاز ۹: آزمایشگاه/تحقیقات =====
    "research_armor_bonus_per_level": "3",         # درصد افزایش نرخ پدافند به‌ازای هر سطح
    "research_oil_refine_bonus_per_level": "8",    # درصد افزایش تولید نفت به‌ازای هر سطح
    "research_metal_bonus_per_level": "8",         # درصد افزایش تولید فلز به‌ازای هر سطح
    "research_food_bonus_per_level": "8",          # درصد افزایش تولید غذا به‌ازای هر سطح
    "research_upgrade_base_gold": "800",
    "research_max_level": "10",

    # ===== فاز ۱۰: رفرال و رنکینگ =====
    "referral_claim_cooldown_hours": "24",
    "leaderboard_size": "10",

    # ===== فاز ۱۱: کانال و عضویت اجباری =====
    "force_channel_membership": "1",   # 1=فعال, 0=غیرفعال
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


DEFAULT_BLUEPRINTS = [
    # (item_code, item_type, price, stock, damage_value, crew_required)
    ("TK-2", "tank", 5000, 20, 35, 3),
    ("JT-2", "jet", 8000, 15, 55, 4),
    ("SH-2", "ship", 10000, 10, 75, 5),
    ("MS-2", "missile", 12000, 10, 90, 2),
]


def init_blueprint_shop():
    conn = get_db()
    existing = conn.execute("SELECT COUNT(*) as c FROM blueprint_shop").fetchone()["c"]
    if existing == 0:
        for item_code, item_type, price, stock, damage, crew in DEFAULT_BLUEPRINTS:
            conn.execute("""INSERT INTO blueprint_shop (item_code, item_type, price, stock, damage_value, crew_required)
                             VALUES (?, ?, ?, ?, ?, ?)""", (item_code, item_type, price, stock, damage, crew))
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

    # بونوس تحقیقات آزمایشگاه (فاز ۹)
    oil_research_bonus = 1 + get_research_bonus_percent(user_id, "oil_refine") / 100
    metal_research_bonus = 1 + get_research_bonus_percent(user_id, "metal") / 100
    food_research_bonus = 1 + get_research_bonus_percent(user_id, "food") / 100

    # تولید مواد خام (هر سطح ساختمان ۱۰٪ بونوس تولید می‌ده، به‌علاوه بونوس تحقیقات)
    fert_produced = pop["miners_fertilizer"] * fert_rate * (1 + 0.1 * max(0, fert_level - 1)) * elapsed_hours
    oil_produced = (pop["miners_oil"] * oil_rate * (1 + 0.1 * max(0, oil_level - 1))
                     * elapsed_hours * oil_research_bonus)
    metal_produced = (pop["miners_metal"] * metal_rate * (1 + 0.1 * max(0, metal_level - 1))
                       * elapsed_hours * metal_research_bonus)

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
    food_produced = farm_level * farm_food_rate * elapsed_hours * farm_efficiency * food_research_bonus
    new_fertilizer -= fert_available_for_farm

    new_food = min(res["food"] + food_produced, res["food_cap"])

    # مصرف غذای جمعیت
    total_population = (pop["unemployed"] + pop["miners_fertilizer"] + pop["miners_oil"] +
                         pop["miners_metal"] + pop["factory_workers"] + pop["military_crew"])
    food_consumed = total_population * food_consumption_per_hour * elapsed_hours
    new_food = max(0, new_food - food_consumed)

    # ---- رشد جمعیت (فاز ۹/۱۳): هر خونه ۲۴ ساعت بعد از آخرین چک، اگه غذا کافی بود پر می‌شه ----
    last_growth = pop["last_growth_check"] or now_str()
    try:
        last_growth_dt = datetime.fromisoformat(last_growth)
    except (ValueError, TypeError):
        last_growth_dt = datetime.utcnow()
    growth_elapsed_hours = (datetime.utcnow() - last_growth_dt).total_seconds() / 3600.0

    new_unemployed = pop["unemployed"]
    new_last_growth_check = pop["last_growth_check"]
    if growth_elapsed_hours >= 24:
        if new_food > 0:
            current_total_pop = total_population
            if current_total_pop < pop["housing_capacity"]:
                new_unemployed += (pop["housing_capacity"] - current_total_pop)
        new_last_growth_check = now_str()
        conn.execute("UPDATE population SET unemployed=?, last_growth_check=? WHERE user_id=?",
                     (new_unemployed, new_last_growth_check, user_id))

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


def get_defense_effective_rate(tier: int, level: int, armor_bonus_percent: float = 0) -> float:
    base_rate = float(get_setting(f"defense_tier{tier}_rate") or 10)
    cap_multiplier = 1.2 if tier == 4 else 1.5
    rate = base_rate * (1 + 0.1 * (level - 1)) * (1 + armor_bonus_percent / 100)
    return min(rate, base_rate * cap_multiplier * (1 + armor_bonus_percent / 100))


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


def has_active_shield(user_id: int) -> bool:
    """چک می‌کنه آیا کشور تازه تو جنگ اتحادی نابود شده و هنوز تو دوره سپره"""
    conn = get_db()
    row = conn.execute(
        "SELECT shield_until FROM war_alliance_targets WHERE target_user_id=? AND shield_until IS NOT NULL "
        "ORDER BY id DESC LIMIT 1", (user_id,)
    ).fetchone()
    conn.close()
    if not row or not row["shield_until"]:
        return False
    try:
        return datetime.fromisoformat(row["shield_until"]) > datetime.utcnow()
    except (ValueError, TypeError):
        return False


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
        if protected or has_active_shield(p["user_id"]):
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


def create_ongoing_attack(attacker_id: int, defender_id: int, cart: list, existing_war_id: int = None):
    """حمله رو ثبت می‌کنه: واحدها بلافاصله مصرف می‌شن و دمیج خام قفل می‌شه، ولی نتیجه (با محاسبه پدافند
    در لحظه پایان) بعد از گذشت war_regular_duration_hours توسط زمان‌بند محاسبه می‌شه، نه فوری.
    اگه existing_war_id داده بشه (حمله‌ای که تایید ادمین بود)، همون ردیف رو آپدیت می‌کنه."""
    conn = get_db()

    raw_damage = 0.0
    for item in cart:
        u = conn.execute("SELECT * FROM military_units WHERE user_id=? AND item_code=?",
                          (attacker_id, item["item_code"])).fetchone()
        if not u or u["quantity"] < item["quantity"]:
            conn.close()
            return None
        raw_damage += item["quantity"] * u["damage_per_unit"]
        conn.execute("UPDATE military_units SET quantity = quantity - ? WHERE id=?",
                     (item["quantity"], u["id"]))

    now = now_str()
    war_hours = float(get_setting("war_regular_duration_hours") or 2)
    end_time = (datetime.utcnow() + timedelta(hours=war_hours)).isoformat()

    if existing_war_id:
        conn.execute("""
            UPDATE war_regular SET status='ongoing', total_damage=?, start_time=?, end_time=?
            WHERE id=?
        """, (round(raw_damage, 1), now, end_time, existing_war_id))
        war_id = existing_war_id
    else:
        cur = conn.execute("""
            INSERT INTO war_regular (attacker_id, defender_id, status, total_damage, start_time, end_time)
            VALUES (?, ?, 'ongoing', ?, ?, ?)
        """, (attacker_id, defender_id, round(raw_damage, 1), now, end_time))
        war_id = cur.lastrowid

    conn.commit()
    conn.close()
    return {"war_id": war_id, "raw_damage": round(raw_damage, 1), "end_time": end_time}


def resolve_regular_war(war_id: int):
    """محاسبه واقعی نتیجه جنگ - با پدافند و تحقیقات مدافع در لحظه پایان، نه لحظه ارسال حمله."""
    conn = get_db()
    war = conn.execute("SELECT * FROM war_regular WHERE id=?", (war_id,)).fetchone()
    if not war or war["status"] != "ongoing":
        conn.close()
        return None

    attacker_id, defender_id = war["attacker_id"], war["defender_id"]
    raw_damage = war["total_damage"]

    defenses = conn.execute(
        "SELECT * FROM defenses WHERE user_id=? AND under_repair_until IS NULL", (defender_id,)
    ).fetchall()
    defender_armor_bonus = get_research_bonus_percent(defender_id, "armor")
    total_intercept_rate = 0.0
    active_defense_ids = []
    for d in defenses:
        if d["hits_remaining"] > 0:
            total_intercept_rate += get_defense_effective_rate(d["tier"], d["level"], defender_armor_bonus)
            active_defense_ids.append(d["id"])
    total_intercept_rate = min(total_intercept_rate, 100.0)

    blocked_damage = raw_damage * (total_intercept_rate / 100.0)
    effective_damage = max(0.0, raw_damage - blocked_damage)

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

    conn.execute("""UPDATE war_regular SET status='finished', defense_blocked=?, result=? WHERE id=?""",
                 (round(blocked_damage, 1), result, war_id))
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
    for t in needs_admin[:5]:
        buttons.append([InlineKeyboardButton(
            f"⚠️ {t['name']} (نیاز به تایید ادمین)", callback_data=f"attack_reqadmin_{t['user_id']}"
        )])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu_attack")])
    return InlineKeyboardMarkup(buttons), len(needs_admin)


def request_admin_attack_approval(attacker_id: int, defender_id: int, cart: list):
    """حمله به کشور خارج از محدوده مجاز قدرت - می‌ره پیش ادمین برای تایید دستی"""
    conn = get_db()
    # چک موجودی (بدون کسر کردن، چون هنوز تایید نشده)
    for item in cart:
        u = conn.execute("SELECT * FROM military_units WHERE user_id=? AND item_code=?",
                          (attacker_id, item["item_code"])).fetchone()
        if not u or u["quantity"] < item["quantity"]:
            conn.close()
            return None, "موجودی کافی نداری."

    timeout_hours = float(get_setting("war_admin_timeout_hours") or 12)
    timeout_at = (datetime.utcnow() + timedelta(hours=timeout_hours)).isoformat()
    cur = conn.execute("""
        INSERT INTO war_regular (attacker_id, defender_id, status, admin_timeout_check, pending_cart_json)
        VALUES (?, ?, 'pending_admin', ?, ?)
    """, (attacker_id, defender_id, timeout_at, json.dumps(cart)))
    war_id = cur.lastrowid
    conn.commit()
    conn.close()
    return war_id, None


def get_pending_admin_attacks():
    conn = get_db()
    rows = conn.execute("SELECT * FROM war_regular WHERE status='pending_admin'").fetchall()
    conn.close()
    return rows


def approve_pending_attack(war_id: int):
    conn = get_db()
    war = conn.execute("SELECT * FROM war_regular WHERE id=?", (war_id,)).fetchone()
    conn.close()
    if not war or war["status"] != "pending_admin":
        return None, "این درخواست دیگه فعال نیست."
    cart = json.loads(war["pending_cart_json"])
    result = create_ongoing_attack(war["attacker_id"], war["defender_id"], cart, existing_war_id=war_id)
    if result is None:
        conn = get_db()
        conn.execute("UPDATE war_regular SET status='rejected' WHERE id=?", (war_id,))
        conn.commit()
        conn.close()
        return None, "موجودی حمله‌کننده کافی نبود، درخواست لغو شد."
    return result, None


def reject_pending_attack(war_id: int):
    conn = get_db()
    conn.execute("UPDATE war_regular SET status='rejected' WHERE id=?", (war_id,))
    conn.commit()
    conn.close()


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

    if action_key.startswith("research_"):
        rtype = action_key.replace("research_", "")
        current_level = get_research_level(user_id, rtype)
        max_level = int(get_setting("research_max_level") or 10)
        base_g = int(get_setting("research_upgrade_base_gold") or 800)
        total_gold = 0
        for i in range(quantity):
            lvl = current_level + i + 1
            if lvl > max_level:
                break
            total_gold += base_g * lvl
        return {"gold": total_gold}

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

    # تحقیقات نمی‌تونه از سقف سطح بره بالاتر
    if action_key.startswith("research_"):
        rtype = action_key.replace("research_", "")
        max_level = int(get_setting("research_max_level") or 10)
        current_level = get_research_level(user_id, rtype)
        max_q = min(max_q, max(0, max_level - current_level))

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

    elif action_key.startswith("research_"):
        rtype = action_key.replace("research_", "")
        max_level = int(get_setting("research_max_level") or 10)
        current_level = get_research_level(user_id, rtype)
        new_level = min(current_level + quantity, max_level)
        existing = conn.execute("SELECT id FROM research WHERE user_id=? AND research_type=?",
                                (user_id, rtype)).fetchone()
        if existing:
            conn.execute("UPDATE research SET level=? WHERE id=?", (new_level, existing["id"]))
        else:
            conn.execute("""INSERT INTO research (user_id, research_type, level, bonus_value)
                             VALUES (?, ?, ?, 0)""", (user_id, rtype, new_level))

    conn.commit()
    conn.close()


def result_back_button(action_key: str):
    if "factory" in action_key:
        target, label = "country_factories", "🔙 بازگشت به کارخونه‌ها"
    elif "defense" in action_key:
        target, label = "menu_defense", "🔙 بازگشت به پدافند"
    elif action_key.startswith("research_"):
        target, label = "menu_lab", "🔙 بازگشت به آزمایشگاه"
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
    "research_armor": "ارتقای تحقیق زره",
    "research_oil_refine": "ارتقای تحقیق پالایش نفت",
    "research_metal": "ارتقای تحقیق فرآوری فلز",
    "research_food": "ارتقای تحقیق کشاورزی",
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

    if not await require_membership(update, context):
        return

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

    if not await require_membership(update, context):
        return

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

    if query.data == "menu_shops":
        await query.edit_message_text(
            "🏪 *شاپ‌ها*\n\nکدوم شاپ رو می‌خوای؟",
            reply_markup=shops_menu_keyboard(),
            parse_mode="Markdown"
        )
        return

    if query.data == "menu_alliance_war":
        my_alliance = get_player_alliance(user_id)
        text = alliance_war_status_text(my_alliance["id"]) if my_alliance else "⚔️ تو عضو هیچ اتحادی نیستی."
        await query.edit_message_text(
            text,
            reply_markup=alliance_war_menu_keyboard(user_id),
            parse_mode="Markdown"
        )
        return

    if query.data == "menu_lab":
        await query.edit_message_text(
            lab_overview_text(user_id),
            reply_markup=lab_menu_keyboard(),
            parse_mode="Markdown"
        )
        return

    if query.data == "menu_ranking":
        await query.edit_message_text(
            ranking_text(),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")]]),
            parse_mode="Markdown"
        )
        return

    if query.data == "menu_stats":
        await query.edit_message_text(
            my_stats_text(user_id),
            reply_markup=my_stats_keyboard(user_id),
            parse_mode="Markdown"
        )
        return

    if query.data == "menu_admin":
        if not is_admin(user_id):
            return
        await query.edit_message_text("👑 *پنل ادمین*", reply_markup=admin_main_keyboard(), parse_mode="Markdown")
        return


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

    if pending["action"] == "announce_text":
        mode = pending["data"]["mode"]
        clear_pending_action(user_id)

        if not ANNOUNCEMENT_CHANNEL_ID:
            await update.message.reply_text("❌ کانال اعلامیه هنوز تنظیم نشده.")
            return

        conn = get_db()
        p = conn.execute("SELECT country_name FROM players WHERE user_id=?", (user_id,)).fetchone()
        conn.close()

        if mode == "alliance":
            a = get_player_alliance(user_id)
            sender_label = f"🤝 اتحاد «{a['name']}»" if a else "🤝 اتحاد"
        else:
            sender_label = f"🏳️ {p['country_name'] or 'کشور ناشناس'}"

        announce_text = f"📢 *اعلامیه از طرف {sender_label}*\n\n{text}"
        try:
            await context.bot.send_message(ANNOUNCEMENT_CHANNEL_ID, announce_text, parse_mode="Markdown")
            await update.message.reply_text("✅ پیام تو کانال منتشر شد.", reply_markup=alliance_main_keyboard(user_id))
        except Exception:
            await update.message.reply_text("❌ ارسال پیام به کانال ناموفق بود.")
        return

    if pending["action"] == "admin_set_setting":
        if not is_admin(user_id):
            clear_pending_action(user_id)
            return
        setting_key = pending["data"]["key"]
        try:
            float(text)  # فقط برای اعتبارسنجی که عدد باشه (اعشاری هم مجازه)
        except ValueError:
            await update.message.reply_text("⚠️ فقط عدد بفرست (اعشار هم مجازه، مثلاً 12.5)")
            return
        clear_pending_action(user_id)
        set_setting(setting_key, text)
        await update.message.reply_text(
            f"✅ مقدار «{setting_key}» به {text} تغییر کرد.",
            reply_markup=admin_main_keyboard()
        )
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

    if pending["action"] == "donate_amount":
        item_code = pending["data"]["item_code"]
        clear_pending_action(user_id)
        success, error = donate_to_alliance(user_id, item_code, quantity)
        if success:
            await update.message.reply_text(
                f"✅ {quantity} عدد {item_code} به انبار اتحاد اهدا شد.",
                reply_markup=alliance_war_menu_keyboard(user_id)
            )
        else:
            await update.message.reply_text(f"❌ {error}")
        return

    if pending["action"] == "buy_admin_resource":
        resource_type = pending["data"]["resource_type"]
        clear_pending_action(user_id)
        success, error = buy_admin_resource(user_id, resource_type, quantity)
        if success:
            await update.message.reply_text(
                f"✅ {quantity} {RESOURCE_LABELS[resource_type]} خریداری شد.",
                reply_markup=shops_menu_keyboard()
            )
        else:
            await update.message.reply_text(f"❌ {error}")
        return

    if pending["action"] == "buy_cap_metal":
        clear_pending_action(user_id)
        success, error = buy_cap_metal(user_id, quantity)
        if success:
            await update.message.reply_text(f"✅ {quantity} فلز خریداری شد.", reply_markup=shops_menu_keyboard())
        else:
            await update.message.reply_text(f"❌ {error}")
        return

    if pending["action"] == "market_sell_quantity":
        category = pending["data"]["category"]
        item_code = pending["data"]["item_code"]
        set_pending_action(user_id, "market_sell_price",
                            {"category": category, "item_code": item_code, "quantity": quantity})
        await update.message.reply_text("قیمت هر واحد رو (به پول) بنویس:")
        return

    if pending["action"] == "market_sell_price":
        category = pending["data"]["category"]
        item_code = pending["data"]["item_code"]
        sell_quantity = pending["data"]["quantity"]
        clear_pending_action(user_id)
        code, error = create_market_listing(user_id, category, item_code, sell_quantity, quantity)
        if code:
            await update.message.reply_text(
                f"✅ آگهی ثبت شد!\nکد: `{code}`\n{sell_quantity} × {quantity} پول",
                reply_markup=shops_menu_keyboard(),
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(f"❌ {error}")
        return

    if pending["action"] == "instant_sell_quantity":
        category = pending["data"]["category"]
        item_code = pending["data"]["item_code"]
        clear_pending_action(user_id)
        success, result = instant_sell(user_id, category, item_code, quantity)
        if success:
            await update.message.reply_text(
                f"✅ فروخته شد! {result} پول گرفتی.",
                reply_markup=shops_menu_keyboard()
            )
        else:
            await update.message.reply_text(f"❌ {result}")
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

        result = create_ongoing_attack(user_id, defender_id, cart)
        clear_pending_action(user_id)

        if result is None:
            await query.edit_message_text(
                "❌ موجودی واحدها تغییر کرده بود، حمله لغو شد. دوباره امتحان کن.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 بازگشت", callback_data="menu_attack")]])
            )
            return

        war_hours = get_setting("war_regular_duration_hours")
        text = (
            f"⚔️ *حمله ارسال شد!*\n\n"
            f"💥 دمیج خام: {result['raw_damage']}\n"
            f"⏳ نتیجه بعد از {war_hours} ساعت اعلام می‌شه.\n"
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
                f"🚨 کشور شما مورد حمله قرار گرفت! نتیجه بعد از {war_hours} ساعت مشخص می‌شه."
            )
        except Exception:
            pass
        return

    if query.data.startswith("attack_reqadmin_"):
        defender_id = int(query.data.replace("attack_reqadmin_", ""))
        cart = get_attack_cart(user_id)
        if not cart:
            await safe_answer(query, "سبد حمله خالیه", show_alert=True)
            return
        war_id, error = request_admin_attack_approval(user_id, defender_id, cart)
        clear_pending_action(user_id)
        if war_id:
            await query.edit_message_text(
                "✅ درخواستت برای ادمین ارسال شد. تا ۱۲ ساعت دیگه بررسی می‌شه.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 بازگشت به منو", callback_data="menu_main")]])
            )
            if ADMIN_ID:
                try:
                    await context.bot.send_message(
                        ADMIN_ID,
                        f"⚠️ درخواست حمله خارج از محدوده قدرت:\n"
                        f"حمله‌کننده: {user_id} → مدافع: {defender_id}\n"
                        f"برای بررسی، پنل ادمین رو باز کن."
                    )
                except Exception:
                    pass
        else:
            await safe_answer(query, error, show_alert=True)
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

    if not target or not target["alliance_id"]:
        conn.close()
        return False, "این بازیکن عضو هیچ اتحادی نیست."

    a = conn.execute("SELECT * FROM alliances WHERE id=?", (target["alliance_id"],)).fetchone()
    is_leader = a and a["leader_id"] == actor_id
    actor_is_admin = is_admin(actor_id) or (actor and actor["is_admin"])
    if not is_leader and not actor_is_admin:
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
            [InlineKeyboardButton("⚔️ جنگ اتحادی", callback_data="menu_alliance_war")],
        ]
        buttons.append([InlineKeyboardButton("📢 اعلامیه به کانال", callback_data="alliance_announce_start")])
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
        return

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

    # فاز ۱۱: اعلامیه رهبر اتحاد به کانال
    if query.data == "alliance_announce_start":
        a = get_player_alliance(user_id)
        if not a:
            await safe_answer(query, "تو عضو هیچ اتحادی نیستی.", show_alert=True)
            return
        if a["leader_id"] == user_id:
            await query.edit_message_text("می‌خوای به چه عنوانی پیام بفرستی؟", reply_markup=announce_mode_keyboard())
        else:
            set_pending_action(user_id, "announce_text", {"mode": "self"})
            await query.edit_message_text("متن پیامت رو بنویس (به نام کشور خودت منتشر می‌شه):")
        return

    if query.data.startswith("announce_mode_"):
        mode = query.data.replace("announce_mode_", "")
        set_pending_action(user_id, "announce_text", {"mode": mode})
        await query.edit_message_text("متن پیامت رو بنویس:")
        return


# ============================================================
#  فاز ۷: جنگ اتحادی (قبیله‌ای)
# ============================================================
def get_country_hp(user_id: int) -> int:
    """اچ‌پی کل کشور = مجموع hp خونه‌ها و مزرعه‌ها"""
    conn = get_db()
    total = conn.execute(
        "SELECT COALESCE(SUM(hp), 0) as total FROM buildings WHERE user_id=? AND type IN ('house','farm')",
        (user_id,)
    ).fetchone()["total"]
    conn.close()
    return total


def get_alliance_storage_items(alliance_id: int):
    conn = get_db()
    items = conn.execute("SELECT * FROM alliance_storage WHERE alliance_id=? AND quantity > 0",
                          (alliance_id,)).fetchall()
    conn.close()
    return items


def donate_to_alliance(user_id: int, item_code: str, quantity: int):
    conn = get_db()
    p = conn.execute("SELECT alliance_id FROM players WHERE user_id=?", (user_id,)).fetchone()
    if not p["alliance_id"]:
        conn.close()
        return False, "تو هیچ اتحادی نیستی."

    u = conn.execute("SELECT * FROM military_units WHERE user_id=? AND item_code=?",
                      (user_id, item_code)).fetchone()
    if not u or u["quantity"] < quantity:
        conn.close()
        return False, "موجودی کافی نداری."

    conn.execute("UPDATE military_units SET quantity = quantity - ? WHERE id=?", (quantity, u["id"]))

    existing = conn.execute(
        "SELECT * FROM alliance_storage WHERE alliance_id=? AND user_id=? AND item_code=?",
        (p["alliance_id"], user_id, item_code)
    ).fetchone()
    if existing:
        conn.execute("UPDATE alliance_storage SET quantity = quantity + ? WHERE id=?",
                     (quantity, existing["id"]))
    else:
        conn.execute("""INSERT INTO alliance_storage (alliance_id, user_id, item_code, quantity, damage_per_unit)
                         VALUES (?, ?, ?, ?, ?)""",
                     (p["alliance_id"], user_id, item_code, quantity, u["damage_per_unit"]))
    conn.commit()
    conn.close()
    return True, None


def initiate_alliance_war(leader_id: int, defender_alliance_id: int):
    conn = get_db()
    p = conn.execute("SELECT alliance_id FROM players WHERE user_id=?", (leader_id,)).fetchone()
    a = conn.execute("SELECT * FROM alliances WHERE id=?", (p["alliance_id"],)).fetchone()

    if not a or a["leader_id"] != leader_id:
        conn.close()
        return None, "فقط رهبر اتحاد می‌تونه اعلام جنگ کنه."

    min_members = int(get_setting("alliance_war_min_members") or 5)
    member_count = conn.execute("SELECT COUNT(*) as c FROM players WHERE alliance_id=?",
                                 (a["id"],)).fetchone()["c"]
    if member_count < min_members:
        conn.close()
        return None, f"اتحادت حداقل باید {min_members} عضو داشته باشه."

    existing_war = conn.execute(
        "SELECT id FROM war_alliance WHERE attacker_alliance_id=? AND status IN ('voting','scheduled','ongoing')",
        (a["id"],)
    ).fetchone()
    if existing_war:
        conn.close()
        return None, "یه جنگ اتحادی دیگه در جریانه، اول اون تموم بشه."

    defenders = conn.execute("SELECT user_id FROM players WHERE alliance_id=?",
                              (defender_alliance_id,)).fetchall()
    if not defenders:
        conn.close()
        return None, "اتحاد مقصد عضو نداره."

    # ترتیب اهداف: ضعیف‌ترین (کمترین اچ‌پی) اول، بدون کشورهایی که سپر فعال دارن
    eligible_defenders = [d["user_id"] for d in defenders if not has_active_shield(d["user_id"])]
    if not eligible_defenders:
        conn.close()
        return None, "همه اعضای اتحاد مقصد الان سپر دارن، نمی‌شه بهشون حمله کرد."
    order = sorted(eligible_defenders, key=lambda uid: get_country_hp(uid))

    cur = conn.execute("""
        INSERT INTO war_alliance (attacker_alliance_id, defender_alliance_id, status,
                                   current_target_order, vault_reward_cap)
        VALUES (?, ?, 'voting', ?, 0)
    """, (a["id"], defender_alliance_id, json.dumps(order)))
    war_id = cur.lastrowid

    # رأی رهبر خودکار موافقه
    conn.execute("INSERT OR REPLACE INTO war_alliance_votes (war_id, user_id, vote) VALUES (?, ?, 1)",
                 (war_id, leader_id))
    conn.commit()
    conn.close()
    return war_id, None


def cast_alliance_war_vote(war_id: int, user_id: int, approve: bool):
    conn = get_db()
    war = conn.execute("SELECT * FROM war_alliance WHERE id=?", (war_id,)).fetchone()
    if not war or war["status"] != "voting":
        conn.close()
        return False, "این رأی‌گیری دیگه فعال نیست."

    p = conn.execute("SELECT alliance_id FROM players WHERE user_id=?", (user_id,)).fetchone()
    if p["alliance_id"] != war["attacker_alliance_id"]:
        conn.close()
        return False, "فقط اعضای اتحاد حمله‌کننده می‌تونن رأی بدن."

    conn.execute("INSERT OR REPLACE INTO war_alliance_votes (war_id, user_id, vote) VALUES (?, ?, ?)",
                 (war_id, user_id, 1 if approve else 0))
    conn.commit()

    member_count = conn.execute("SELECT COUNT(*) as c FROM players WHERE alliance_id=?",
                                 (war["attacker_alliance_id"],)).fetchone()["c"]
    yes_votes = conn.execute("SELECT COUNT(*) as c FROM war_alliance_votes WHERE war_id=? AND vote=1",
                              (war_id,)).fetchone()["c"]
    threshold = float(get_setting("alliance_war_vote_threshold_percent") or 50)

    approved = (yes_votes / member_count * 100) >= threshold if member_count else False
    if approved:
        conn.execute("UPDATE war_alliance SET status='scheduled' WHERE id=?", (war_id,))
    conn.commit()
    conn.close()
    return True, ("approved" if approved else "recorded")


def start_alliance_war(war_id: int):
    """جنگ رو رسماً شروع می‌کنه؛ نتیجه‌گیری واقعی بعد از war_alliance_duration_hours توسط
    زمان‌بند خودکار (فاز ۱۳) انجام می‌شه، نه فوری."""
    conn = get_db()
    war = conn.execute("SELECT * FROM war_alliance WHERE id=?", (war_id,)).fetchone()
    if not war or war["status"] != "scheduled":
        conn.close()
        return False, "این جنگ آماده شروع نیست."

    targets = json.loads(war["current_target_order"])
    now = now_str()
    duration_hours = float(get_setting("war_alliance_duration_hours") or 24)
    end_time = (datetime.utcnow() + timedelta(hours=duration_hours)).isoformat()

    for target_id in targets:
        max_hp = get_country_hp(target_id)
        conn.execute("""INSERT INTO war_alliance_targets
                         (war_id, target_user_id, max_hp, current_hp, destroyed, wealth_lost_percent)
                         VALUES (?, ?, ?, ?, 0, 20)""", (war_id, target_id, max_hp, max_hp))

    conn.execute("UPDATE war_alliance SET status='ongoing', scheduled_by_admin_at=?, start_time=?, end_time=? WHERE id=?",
                 (now, now, end_time, war_id))
    conn.commit()
    conn.close()
    return True, None


def resolve_alliance_war(war_id: int):
    conn = get_db()
    war = conn.execute("SELECT * FROM war_alliance WHERE id=?", (war_id,)).fetchone()
    attacker_alliance_id = war["attacker_alliance_id"]

    storage_items = conn.execute("SELECT * FROM alliance_storage WHERE alliance_id=? AND quantity > 0",
                                  (attacker_alliance_id,)).fetchall()

    # مجموع دمیج در دسترس و سهم هر بازیکن (برای جایزه)
    contributions = {}
    remaining_damage = 0.0
    for item in storage_items:
        dmg = item["quantity"] * item["damage_per_unit"]
        remaining_damage += dmg
        contributions[item["user_id"]] = contributions.get(item["user_id"], 0) + dmg

    targets = conn.execute("SELECT * FROM war_alliance_targets WHERE war_id=? ORDER BY id",
                            (war_id,)).fetchall()

    destroyed_count = 0
    cap_per_destroyed = int(get_setting("war_alliance_cap_per_destroyed") or 100)
    shield_hours = float(get_setting("war_alliance_shield_hours") or 12)

    for t in targets:
        if remaining_damage <= 0:
            break

        defenses = conn.execute(
            "SELECT * FROM defenses WHERE user_id=? AND under_repair_until IS NULL AND hits_remaining > 0",
            (t["target_user_id"],)
        ).fetchall()
        defender_armor_bonus = get_research_bonus_percent(t["target_user_id"], "armor")
        total_intercept = min(sum(get_defense_effective_rate(d["tier"], d["level"], defender_armor_bonus)
                                   for d in defenses), 100.0)

        current_hp = t["current_hp"]
        while current_hp > 0 and remaining_damage > 0:
            chunk = min(remaining_damage, current_hp / max(1 - total_intercept / 100, 0.01))
            effective = chunk * (1 - total_intercept / 100)
            current_hp -= effective
            remaining_damage -= chunk

        destroyed = current_hp <= 0
        if destroyed:
            destroyed_count += 1
            wealth_pct = t["wealth_lost_percent"]
            shield_until = (datetime.utcnow() + timedelta(hours=shield_hours)).isoformat()
            conn.execute("""UPDATE war_alliance_targets SET current_hp=0, destroyed=1, shield_until=?
                             WHERE id=?""", (shield_until, t["id"]))
            defender = conn.execute("SELECT gold, cap_points FROM players WHERE user_id=?",
                                     (t["target_user_id"],)).fetchone()
            gold_loss = int(defender["gold"] * wealth_pct / 100)
            cap_loss = int(defender["cap_points"] * wealth_pct / 100)
            conn.execute("UPDATE players SET gold = gold - ?, cap_points = cap_points - ? WHERE user_id=?",
                         (gold_loss, cap_loss, t["target_user_id"]))
            conn.execute("UPDATE alliances SET vault_cap = vault_cap + ? WHERE id=?",
                         (cap_per_destroyed, attacker_alliance_id))
        else:
            conn.execute("UPDATE war_alliance_targets SET current_hp=? WHERE id=?",
                         (max(0, current_hp), t["id"]))

        for d in defenses:
            conn.execute("UPDATE defenses SET hits_remaining = hits_remaining - 1 WHERE id=?", (d["id"],))

    # تجهیزات مصرف‌شده رو از انبار اتحاد پاک کن (همه یا هرچی مصرف شد، تناسبی خالی می‌کنیم)
    total_available = sum(item["quantity"] * item["damage_per_unit"] for item in storage_items)
    consumed_ratio = 1.0 if total_available <= 0 else min(1.0, (total_available - max(0, remaining_damage)) / total_available)
    for item in storage_items:
        consumed_qty = int(item["quantity"] * consumed_ratio)
        conn.execute("UPDATE alliance_storage SET quantity = quantity - ? WHERE id=?",
                     (consumed_qty, item["id"]))

    # ثبت سهم مشارکت هر عضو
    for uid, dmg in contributions.items():
        conn.execute("""INSERT INTO war_alliance_contributions (war_id, user_id, damage_dealt, units_contributed)
                         VALUES (?, ?, ?, ?)""", (war_id, uid, dmg, 0))

    conn.execute("UPDATE war_alliance SET status='finished', vault_reward_cap=? WHERE id=?",
                 (destroyed_count * cap_per_destroyed, war_id))
    conn.commit()
    conn.close()

    return {"destroyed_count": destroyed_count, "cap_earned": destroyed_count * cap_per_destroyed}


def alliance_war_status_text(alliance_id: int) -> str:
    conn = get_db()
    war = conn.execute(
        "SELECT * FROM war_alliance WHERE attacker_alliance_id=? AND status IN ('voting','scheduled','ongoing') "
        "ORDER BY id DESC LIMIT 1", (alliance_id,)
    ).fetchone()
    conn.close()
    if not war:
        return "⚔️ *جنگ اتحادی*\n\nهیچ جنگ فعالی در جریان نیست."

    defender_alliance = get_alliance(war["defender_alliance_id"])
    status_map = {"voting": "🗳 در حال رأی‌گیری", "scheduled": "⏳ منتظر تایید/شروع ادمین", "ongoing": "🔥 در حال جنگ"}
    return (f"⚔️ *جنگ اتحادی*\n\n"
            f"🎯 حریف: {defender_alliance['name'] if defender_alliance else 'نامشخص'}\n"
            f"📊 وضعیت: {status_map.get(war['status'], war['status'])}\n")


def alliance_war_menu_keyboard(user_id: int):
    a = get_player_alliance(user_id)
    buttons = []
    if a:
        conn = get_db()
        active_war = conn.execute(
            "SELECT id, status FROM war_alliance WHERE attacker_alliance_id=? AND status IN ('voting','scheduled','ongoing')",
            (a["id"],)
        ).fetchone()
        conn.close()

        buttons.append([InlineKeyboardButton("🎒 اهدای تجهیزات به اتحاد", callback_data="warall_donate")])
        if active_war and active_war["status"] == "voting":
            buttons.append([InlineKeyboardButton("✅ رأی موافق", callback_data=f"warall_vote_yes_{active_war['id']}")])
            buttons.append([InlineKeyboardButton("❌ رأی مخالف", callback_data=f"warall_vote_no_{active_war['id']}")])
        elif a["leader_id"] == user_id and not active_war:
            buttons.append([InlineKeyboardButton("🎯 اعلام جنگ به اتحاد دیگه", callback_data="warall_declare")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu_alliance")])
    return InlineKeyboardMarkup(buttons)


def other_alliances_keyboard():
    conn = get_db()
    alliances = conn.execute("SELECT * FROM alliances WHERE is_admin_alliance=0").fetchall()
    conn.close()
    buttons = []
    for a in alliances:
        buttons.append([InlineKeyboardButton(a["name"], callback_data=f"warall_target_{a['id']}")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu_alliance")])
    return InlineKeyboardMarkup(buttons)


async def start_alliance_war_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور موقت ادمین برای شروع جنگ اتحادی تایید‌شده - تا فاز پنل ادمین یه دکمه واقعی جایگزینش می‌شه"""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return

    conn = get_db()
    scheduled_wars = conn.execute("SELECT * FROM war_alliance WHERE status='scheduled'").fetchall()
    conn.close()

    if not context.args:
        if not scheduled_wars:
            await update.message.reply_text("هیچ جنگ اتحادی آماده شروع نیست.")
            return
        lines = ["جنگ‌های آماده شروع:\n"]
        for w in scheduled_wars:
            att = get_alliance(w["attacker_alliance_id"])
            defn = get_alliance(w["defender_alliance_id"])
            lines.append(f"شماره {w['id']}: {att['name']} ⚔️ {defn['name']}")
        lines.append("\nبرای شروع: /start_alliance_war شماره_جنگ")
        await update.message.reply_text("\n".join(lines))
        return

    try:
        war_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("شماره جنگ نامعتبره.")
        return

    success, error = start_alliance_war(war_id)
    if not success:
        await update.message.reply_text(f"❌ {error}")
        return

    war_hours = get_setting("war_alliance_duration_hours")
    await update.message.reply_text(
        f"✅ جنگ اتحادی رسماً شروع شد!\nنتیجه بعد از {war_hours} ساعت خودکار اعلام می‌شه."
    )
    await post_alliance_war_announcement(context.bot, war_id, "started")


async def alliance_war_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_answer(query)
    user_id = update.effective_user.id

    if query.data == "menu_alliance_war":
        my_alliance = get_player_alliance(user_id)
        text = alliance_war_status_text(my_alliance["id"]) if my_alliance else "⚔️ تو عضو هیچ اتحادی نیستی."
        await query.edit_message_text(
            text,
            reply_markup=alliance_war_menu_keyboard(user_id),
            parse_mode="Markdown"
        )
        return

    if query.data == "warall_declare":
        await query.edit_message_text(
            "🎯 کدوم اتحاد رو هدف قرار می‌دی؟",
            reply_markup=other_alliances_keyboard()
        )
        return

    if query.data.startswith("warall_target_"):
        defender_alliance_id = int(query.data.replace("warall_target_", ""))
        war_id, error = initiate_alliance_war(user_id, defender_alliance_id)
        if war_id:
            await query.edit_message_text(
                "✅ جنگ اعلام شد و رأی‌گیری شروع شد! اعضا باید رأی بدن.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 بازگشت", callback_data="menu_alliance")]])
            )
            await post_alliance_war_announcement(context.bot, war_id, "declared")
        else:
            await safe_answer(query, error, show_alert=True)
        return

    if query.data.startswith("warall_vote_"):
        parts = query.data.replace("warall_vote_", "").rsplit("_", 1)
        approve_str, war_id = parts[0], int(parts[1])
        approve = approve_str == "yes"
        success, result = cast_alliance_war_vote(war_id, user_id, approve)
        if success:
            msg = "✅ رأیت ثبت شد."
            if result == "approved":
                msg += "\n🎉 اکثریت موافقت کردن! منتظر شروع ادمین باش."
            await query.edit_message_text(msg, reply_markup=alliance_war_menu_keyboard(user_id))
        else:
            await safe_answer(query, result, show_alert=True)
        return

    if query.data == "warall_donate":
        units = get_owned_units(user_id)
        if not units:
            await safe_answer(query, "هیچ واحد نظامی نداری.", show_alert=True)
            return
        buttons = [[InlineKeyboardButton(f"{u['item_code']} ({u['quantity']:.0f})",
                                          callback_data=f"warall_donate_pick_{u['item_code']}")] for u in units]
        buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu_alliance")])
        await query.edit_message_text("کدوم واحد رو اهدا می‌کنی؟", reply_markup=InlineKeyboardMarkup(buttons))
        return

    if query.data.startswith("warall_donate_pick_"):
        item_code = query.data.replace("warall_donate_pick_", "")
        set_pending_action(user_id, "donate_amount", {"item_code": item_code})
        await query.edit_message_text("چند تا می‌خوای اهدا کنی؟ عدد رو تایپ کن.")
        return


# ============================================================
#  فاز ۹: آزمایشگاه/تحقیقات
# ============================================================
RESEARCH_TYPES = {
    "armor": ("🛡️ زره (تقویت پدافند)", "armor"),
    "oil_refine": ("🛢️ پالایش نفت", "oil_refine"),
    "metal": ("⚙️ فرآوری فلز", "metal"),
    "food": ("🌾 بهبود کشاورزی", "food"),
}


def get_research_level(user_id: int, research_type: str) -> int:
    conn = get_db()
    r = conn.execute("SELECT level FROM research WHERE user_id=? AND research_type=?",
                      (user_id, research_type)).fetchone()
    conn.close()
    return r["level"] if r else 0


def get_research_bonus_percent(user_id: int, research_type: str) -> float:
    level = get_research_level(user_id, research_type)
    per_level = float(get_setting(f"research_{research_type}_bonus_per_level") or 5)
    return level * per_level


def lab_overview_text(user_id: int) -> str:
    text = "🔬 *آزمایشگاه*\n\n"
    for rtype, (label, _) in RESEARCH_TYPES.items():
        level = get_research_level(user_id, rtype)
        bonus = get_research_bonus_percent(user_id, rtype)
        text += f"{label} — سطح {level} (بونوس فعلی: +{bonus:.0f}٪)\n"
    return text


def lab_menu_keyboard():
    buttons = [[InlineKeyboardButton(f"⬆️ ارتقای {label}", callback_data=f"research_{key}")]
               for key, (label, _) in RESEARCH_TYPES.items()]
    buttons.append([InlineKeyboardButton("🔙 بازگشت به منو", callback_data="menu_main")])
    return InlineKeyboardMarkup(buttons)


async def research_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نقطه ورود ارتقای تحقیقات - جریان تعداد دلخواه/حداکثر رو با هندلر کشور مشترکه"""
    query = update.callback_query
    await safe_answer(query)
    user_id = update.effective_user.id
    action_key = query.data  # مثل research_armor

    if action_key not in ACTION_LABELS:
        return

    max_level = int(get_setting("research_max_level") or 10)
    rtype = action_key.replace("research_", "")
    current_level = get_research_level(user_id, rtype)
    if current_level >= max_level:
        await safe_answer(query, "این تحقیق به سقف سطح رسیده.", show_alert=True)
        return

    cost1 = get_action_cost(user_id, action_key, 1)
    label = ACTION_LABELS[action_key]
    text = f"🔬 {label}\n\nسطح فعلی: {current_level}\nهزینه سطح بعدی: {cost_to_text(cost1)}\n\nچند سطح می‌خوای ارتقا بدی؟"
    await query.edit_message_text(text, reply_markup=quantity_prompt_keyboard(action_key, "menu_lab"))


# ============================================================
#  فاز ۱۰: رنکینگ، آمار من، درآمد روزانه رفرال
# ============================================================
def get_leaderboard(limit: int = 10):
    conn = get_db()
    players = conn.execute("SELECT user_id, country_name FROM players").fetchall()
    conn.close()
    ranked = [(p["user_id"], p["country_name"] or f"#{p['user_id']}", get_country_power(p["user_id"]))
              for p in players]
    ranked.sort(key=lambda x: x[2], reverse=True)
    return ranked[:limit]


def ranking_text() -> str:
    limit = int(get_setting("leaderboard_size") or 10)
    ranked = get_leaderboard(limit)
    if not ranked:
        return "🏆 *رنکینگ*\n\nهنوز بازیکنی ثبت نشده."
    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 *رنکینگ برترین کشورها (بر اساس قدرت نظامی)*\n"]
    for i, (uid, name, power) in enumerate(ranked):
        prefix = medals[i] if i < 3 else f"{i+1}."
        lines.append(f"{prefix} {name} — قدرت: {power:.0f}")
    return "\n".join(lines)


def get_war_record(user_id: int):
    conn = get_db()
    wins = conn.execute(
        "SELECT COUNT(*) as c FROM war_regular WHERE (attacker_id=? AND result='attacker_win') "
        "OR (defender_id=? AND result='defender_win')", (user_id, user_id)
    ).fetchone()["c"]
    losses = conn.execute(
        "SELECT COUNT(*) as c FROM war_regular WHERE (attacker_id=? AND result='defender_win') "
        "OR (defender_id=? AND result='attacker_win')", (user_id, user_id)
    ).fetchone()["c"]
    conn.close()
    return wins, losses


def get_referrals(user_id: int):
    conn = get_db()
    refs = conn.execute("SELECT user_id, country_name, gold FROM players WHERE referrer_id=?",
                         (user_id,)).fetchall()
    conn.close()
    return refs


def can_claim_referral_income(user_id: int) -> bool:
    conn = get_db()
    p = conn.execute("SELECT last_referral_claim FROM players WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    if not p or not p["last_referral_claim"]:
        return True
    cooldown_hours = int(get_setting("referral_claim_cooldown_hours") or 24)
    try:
        next_allowed = datetime.fromisoformat(p["last_referral_claim"]) + timedelta(hours=cooldown_hours)
        return datetime.utcnow() >= next_allowed
    except (ValueError, TypeError):
        return True


def claim_referral_income(user_id: int):
    if not can_claim_referral_income(user_id):
        return False, "هنوز ۲۴ ساعت از آخرین برداشتت نگذشته."

    refs = get_referrals(user_id)
    if not refs:
        return False, "هنوز هیچ زیرمجموعه‌ای نیاوردی."

    percent = float(get_setting("referral_daily_income_percent") or 5)
    total_bonus = round(sum(r["gold"] for r in refs) * percent / 100)

    conn = get_db()
    conn.execute("UPDATE players SET gold = gold + ?, last_referral_claim=? WHERE user_id=?",
                 (total_bonus, now_str(), user_id))
    conn.commit()
    conn.close()
    return True, total_bonus


def my_stats_text(user_id: int) -> str:
    calculate_and_apply_production(user_id)
    conn = get_db()
    p = conn.execute("SELECT * FROM players WHERE user_id=?", (user_id,)).fetchone()
    pop = conn.execute("SELECT * FROM population WHERE user_id=?", (user_id,)).fetchone()
    house_count = count_houses(user_id)
    factory_count = conn.execute("SELECT COUNT(*) as c FROM factories WHERE user_id=?",
                                  (user_id,)).fetchone()["c"]
    conn.close()

    power = get_country_power(user_id)
    wins, losses = get_war_record(user_id)
    alliance = get_player_alliance(user_id)
    referrals = get_referrals(user_id)

    total_pop = (pop["unemployed"] + pop["miners_fertilizer"] + pop["miners_oil"] +
                 pop["miners_metal"] + pop["factory_workers"] + pop["military_crew"])

    text = (
        f"📊 *آمار کشور: {p['country_name'] or 'بدون‌نام'}*\n\n"
        f"⚔️ قدرت نظامی: {power:.0f}\n"
        f"💰 پول: {p['gold']} | 🏅 کاپ: {p['cap_points']}\n"
        f"🏠 خونه: {house_count} | 🏭 کارخونه: {factory_count}\n"
        f"👥 جمعیت کل: {total_pop}\n"
        f"🤝 اتحاد: {alliance['name'] if alliance else 'بدون اتحاد'}\n\n"
        f"⚔️ رکورد جنگی: {wins} برد / {losses} باخت\n\n"
        f"👨‍👩‍👧 زیرمجموعه‌ها: {len(referrals)} نفر\n"
    )
    return text


def my_stats_keyboard(user_id: int):
    can_claim = can_claim_referral_income(user_id)
    buttons = []
    if can_claim:
        buttons.append([InlineKeyboardButton("🎁 برداشت درآمد روزانه رفرال", callback_data="claim_referral")])
    buttons.append([InlineKeyboardButton("🔄 بروزرسانی", callback_data="menu_stats")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت به منو", callback_data="menu_main")])
    return InlineKeyboardMarkup(buttons)


async def stats_ranking_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_answer(query)
    user_id = update.effective_user.id

    if query.data == "menu_ranking":
        await query.edit_message_text(
            ranking_text(),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")]]),
            parse_mode="Markdown"
        )
        return

    if query.data == "menu_stats":
        await query.edit_message_text(
            my_stats_text(user_id),
            reply_markup=my_stats_keyboard(user_id),
            parse_mode="Markdown"
        )
        return

    if query.data == "claim_referral":
        success, result = claim_referral_income(user_id)
        if success:
            await query.edit_message_text(
                f"✅ {result} پول از درآمد زیرمجموعه‌هات برداشت کردی!",
                reply_markup=my_stats_keyboard(user_id)
            )
        else:
            await safe_answer(query, result, show_alert=True)
        return


# ============================================================
#  فاز ۱۱: کانال و عضویت اجباری
# ============================================================
async def check_channel_membership(bot, user_id: int) -> bool:
    """چک عضویت کاربر تو کانال اعلامیه. اگه کانال تنظیم نشده یا خطا داد، fail-open (بلاک نمی‌کنیم)."""
    if not ANNOUNCEMENT_CHANNEL_ID or get_setting("force_channel_membership") != "1":
        return True
    try:
        member = await bot.get_chat_member(ANNOUNCEMENT_CHANNEL_ID, user_id)
        return member.status not in ("left", "kicked")
    except Exception:
        return True  # اگه بات دسترسی نداشت یا خطا خورد، بازی رو قفل نکن


def channel_join_keyboard():
    channel_link = ANNOUNCEMENT_CHANNEL_ID
    if channel_link and channel_link.startswith("@"):
        channel_link = f"https://t.me/{channel_link[1:]}"
    buttons = [[InlineKeyboardButton("📢 عضویت در کانال", url=channel_link or "https://t.me/")],
               [InlineKeyboardButton("✅ عضو شدم، چک کن", callback_data="check_membership")]]
    return InlineKeyboardMarkup(buttons)


async def require_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    if is_admin(user_id):
        return True
    ok = await check_channel_membership(context.bot, user_id)
    if ok:
        return True

    text = "🚫 برای بازی کردن باید عضو کانال اعلامیه‌ها بشی."
    if update.callback_query:
        await safe_answer(update.callback_query)
        try:
            await update.callback_query.edit_message_text(text, reply_markup=channel_join_keyboard())
        except BadRequest:
            pass
    elif update.message:
        await update.message.reply_text(text, reply_markup=channel_join_keyboard())
    return False


async def check_membership_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    ok = await check_channel_membership(context.bot, user_id)
    if ok:
        await safe_answer(query, "✅ عضویت تایید شد!")
        await query.edit_message_text(
            get_main_menu_text(user_id),
            reply_markup=main_menu_keyboard(user_id)
        )
    else:
        await safe_answer(query, "❌ هنوز عضو کانال نشدی.", show_alert=True)


# ---------- اعلامیه‌های خودکار ----------
async def log_announcement(a_type: str, related_id: int = None):
    conn = get_db()
    conn.execute("INSERT INTO channel_announcements (type, related_id, sent_at) VALUES (?, ?, ?)",
                 (a_type, related_id, now_str()))
    conn.commit()
    conn.close()


async def post_war_announcement(bot, attacker_id: int, defender_id: int, result: dict):
    if not ANNOUNCEMENT_CHANNEL_ID:
        return
    conn = get_db()
    attacker = conn.execute("SELECT country_name FROM players WHERE user_id=?", (attacker_id,)).fetchone()
    defender = conn.execute("SELECT country_name FROM players WHERE user_id=?", (defender_id,)).fetchone()
    conn.close()
    att_name = attacker["country_name"] or f"#{attacker_id}"
    def_name = defender["country_name"] or f"#{defender_id}"
    outcome = "🎉 حمله موفق بود" if result["result"] == "attacker_win" else "🛡️ دفاع موفق بود"

    text = (f"⚔️ *اعلامیه جنگ*\n\n"
            f"🏳️ {att_name} به 🏳️ {def_name} حمله کرد!\n"
            f"{outcome}\n"
            f"💥 دمیج مؤثر: {result['effective_damage']}")
    try:
        await bot.send_message(ANNOUNCEMENT_CHANNEL_ID, text, parse_mode="Markdown")
        await log_announcement("war")
    except Exception:
        pass


async def post_alliance_war_announcement(bot, war_id: int, event: str):
    if not ANNOUNCEMENT_CHANNEL_ID:
        return
    conn = get_db()
    war = conn.execute("SELECT * FROM war_alliance WHERE id=?", (war_id,)).fetchone()
    conn.close()
    if not war:
        return
    att = get_alliance(war["attacker_alliance_id"])
    defn = get_alliance(war["defender_alliance_id"])

    event_texts = {
        "declared": f"🗳 اتحاد «{att['name']}» جنگ قبیله‌ای علیه «{defn['name']}» اعلام کرد! رأی‌گیری شروع شد.",
        "started": f"🔥 جنگ قبیله‌ای بین «{att['name']}» و «{defn['name']}» شروع شد!",
        "finished": f"🏁 جنگ قبیله‌ای «{att['name']}» علیه «{defn['name']}» تموم شد!",
    }
    text = f"⚔️ *اعلامیه جنگ اتحادی*\n\n{event_texts.get(event, event)}"
    try:
        await bot.send_message(ANNOUNCEMENT_CHANNEL_ID, text, parse_mode="Markdown")
        await log_announcement("alliance_war", war_id)
    except Exception:
        pass


# ---------- پیام رهبر به کانال (به نام اتحاد یا کشور خودش) ----------
def announce_mode_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤝 به نام اتحاد", callback_data="announce_mode_alliance")],
        [InlineKeyboardButton("🏳️ به نام کشور خودم", callback_data="announce_mode_self")],
        [InlineKeyboardButton("🔙 لغو", callback_data="menu_alliance")],
    ])


# ============================================================
#  فاز ۸: شاپ‌ها
# ============================================================
RESOURCE_FIELD_MAP = {
    "oil": ("oil", "oil_cap"),
    "metal": ("metal", "metal_cap"),
    "fertilizer": ("fertilizer", "fertilizer_cap"),
    "electricity": ("electricity_civil", "electricity_civil_cap"),
}
RESOURCE_LABELS = {"oil": "نفت", "metal": "فلز", "fertilizer": "کود", "electricity": "برق عادی"}


# ---------- شاپ ادمین (منابع) ----------
def buy_admin_resource(user_id: int, resource_type: str, quantity: int):
    price = int(get_setting(f"admin_shop_{resource_type}_price") or 10)
    cost = price * quantity
    field, cap_field = RESOURCE_FIELD_MAP[resource_type]

    conn = get_db()
    p = conn.execute("SELECT gold FROM players WHERE user_id=?", (user_id,)).fetchone()
    if p["gold"] < cost:
        conn.close()
        return False, f"پول کافی نداری. هزینه: {cost}"

    res = conn.execute("SELECT * FROM resources WHERE user_id=?", (user_id,)).fetchone()
    space_left = res[cap_field] - res[field]
    if quantity > space_left:
        conn.close()
        return False, f"ظرفیت انبارت کافی نیست. فضای خالی: {space_left:.0f}"

    conn.execute("UPDATE players SET gold = gold - ? WHERE user_id=?", (cost, user_id))
    conn.execute(f"UPDATE resources SET {field} = {field} + ? WHERE user_id=?", (quantity, user_id))
    conn.commit()
    conn.close()
    return True, None


def admin_shop_menu_text() -> str:
    lines = ["🏦 *شاپ ادمین*\n\nقیمت هر واحد:\n"]
    for key, label in RESOURCE_LABELS.items():
        price = get_setting(f"admin_shop_{key}_price")
        lines.append(f"  {label}: {price} پول")
    return "\n".join(lines)


def admin_shop_keyboard():
    buttons = [[InlineKeyboardButton(f"🛒 خرید {label}", callback_data=f"shopres_{key}")]
               for key, label in RESOURCE_LABELS.items()]
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu_shops")])
    return InlineKeyboardMarkup(buttons)


# ---------- شاپ کاپ ----------
def buy_cap_metal(user_id: int, quantity: int):
    price = int(get_setting("cap_shop_metal_price") or 5)
    cost = price * quantity

    conn = get_db()
    p = conn.execute("SELECT cap_points FROM players WHERE user_id=?", (user_id,)).fetchone()
    if p["cap_points"] < cost:
        conn.close()
        return False, f"کاپ کافی نداری. هزینه: {cost}"

    res = conn.execute("SELECT metal, metal_cap FROM resources WHERE user_id=?", (user_id,)).fetchone()
    space_left = res["metal_cap"] - res["metal"]
    if quantity > space_left:
        conn.close()
        return False, f"ظرفیت انبار فلزت کافی نیست. فضای خالی: {space_left:.0f}"

    conn.execute("UPDATE players SET cap_points = cap_points - ? WHERE user_id=?", (cost, user_id))
    conn.execute("UPDATE resources SET metal = metal + ? WHERE user_id=?", (quantity, user_id))
    conn.commit()
    conn.close()
    return True, None


def buy_cap_special_item(user_id: int):
    cost = int(get_setting("cap_shop_special_item_cap_cost") or 200)
    reward = int(get_setting("cap_shop_special_item_gold_reward") or 5000)

    conn = get_db()
    p = conn.execute("SELECT cap_points FROM players WHERE user_id=?", (user_id,)).fetchone()
    if p["cap_points"] < cost:
        conn.close()
        return False, f"کاپ کافی نداری. هزینه: {cost}"

    conn.execute("UPDATE players SET cap_points = cap_points - ?, gold = gold + ? WHERE user_id=?",
                 (cost, reward, user_id))
    conn.commit()
    conn.close()
    return True, None


def cap_shop_keyboard():
    metal_price = get_setting("cap_shop_metal_price")
    special_cost = get_setting("cap_shop_special_item_cap_cost")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"⚙️ خرید فلز ({metal_price} کاپ/واحد)", callback_data="capshop_metal")],
        [InlineKeyboardButton(f"🎁 آیتم ویژه ({special_cost} کاپ)", callback_data="capshop_special")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="menu_shops")],
    ])


# ---------- شاپ نقشه‌ساخت ----------
def list_blueprint_shop():
    conn = get_db()
    items = conn.execute("SELECT * FROM blueprint_shop WHERE stock > 0").fetchall()
    conn.close()
    return items


def buy_blueprint(user_id: int, shop_id: int):
    conn = get_db()
    item = conn.execute("SELECT * FROM blueprint_shop WHERE id=?", (shop_id,)).fetchone()
    if not item or item["stock"] <= 0:
        conn.close()
        return False, "این نقشه دیگه موجود نیست."

    p = conn.execute("SELECT gold FROM players WHERE user_id=?", (user_id,)).fetchone()
    if p["gold"] < item["price"]:
        conn.close()
        return False, f"پول کافی نداری. قیمت: {item['price']}"

    conn.execute("UPDATE players SET gold = gold - ? WHERE user_id=?", (item["price"], user_id))
    conn.execute("UPDATE blueprint_shop SET stock = stock - 1 WHERE id=?", (shop_id,))
    conn.execute("""INSERT INTO blueprints (user_id, item_code, item_type, damage, is_active, crew_required)
                     VALUES (?, ?, ?, ?, 0, ?)""",
                 (user_id, item["item_code"], item["item_type"], item["damage_value"], item["crew_required"]))
    conn.commit()
    conn.close()
    return True, None


def get_owned_blueprints(user_id: int):
    conn = get_db()
    items = conn.execute("SELECT * FROM blueprints WHERE user_id=?", (user_id,)).fetchall()
    conn.close()
    return items


def install_blueprint(user_id: int, blueprint_id: int):
    conn = get_db()
    bp = conn.execute("SELECT * FROM blueprints WHERE id=? AND user_id=?", (blueprint_id, user_id)).fetchone()
    if not bp:
        conn.close()
        return False, "این نقشه مال تو نیست."

    factory = conn.execute("SELECT * FROM factories WHERE user_id=? AND type=?",
                            (user_id, bp["item_type"])).fetchone()
    if not factory:
        conn.close()
        return False, f"اول باید کارخونه {bp['item_type']} بسازی."

    conn.execute("UPDATE blueprints SET is_active=0 WHERE user_id=? AND item_type=?", (user_id, bp["item_type"]))
    conn.execute("UPDATE blueprints SET is_active=1 WHERE id=?", (blueprint_id,))
    conn.execute("UPDATE factories SET blueprint_id=? WHERE id=?", (blueprint_id, factory["id"]))
    conn.commit()
    conn.close()
    return True, None


def blueprint_shop_keyboard():
    items = list_blueprint_shop()
    buttons = [[InlineKeyboardButton(
        f"{i['item_code']} ({i['item_type']}) — {i['price']} پول [موجودی: {i['stock']}]",
        callback_data=f"bpbuy_{i['id']}"
    )] for i in items]
    buttons.append([InlineKeyboardButton("📦 نقشه‌های من (نصب)", callback_data="bpown_list")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu_shops")])
    return InlineKeyboardMarkup(buttons)


def owned_blueprints_keyboard(user_id: int):
    items = get_owned_blueprints(user_id)
    buttons = [[InlineKeyboardButton(
        f"{'✅ ' if i['is_active'] else ''}{i['item_code']} ({i['item_type']})",
        callback_data=f"bpinstall_{i['id']}"
    )] for i in items]
    if not buttons:
        buttons.append([InlineKeyboardButton("❌ نقشه‌ای نداری", callback_data="menu_shops")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu_shops")])
    return InlineKeyboardMarkup(buttons)


# ---------- بازار بازیکنان ----------
MARKET_CATEGORIES = {
    "oil": "نفت", "metal": "فلز", "fertilizer": "کود", "food": "غذا", "electricity": "برق",
    "tank": "تانک", "jet": "جنگنده", "ship": "کشتی", "missile": "موشک",
}


def create_market_listing(seller_id: int, category: str, item_code, quantity: int, price_per_unit: int):
    conn = get_db()
    if category in RESOURCE_FIELD_MAP or category == "food":
        field = "food" if category == "food" else RESOURCE_FIELD_MAP[category][0]
        res = conn.execute("SELECT * FROM resources WHERE user_id=?", (seller_id,)).fetchone()
        if res[field] < quantity:
            conn.close()
            return None, "موجودی کافی نداری."
        conn.execute(f"UPDATE resources SET {field} = {field} - ? WHERE user_id=?", (quantity, seller_id))
        item_code = None
    else:
        u = conn.execute("SELECT * FROM military_units WHERE user_id=? AND item_code=?",
                          (seller_id, item_code)).fetchone()
        if not u or u["quantity"] < quantity:
            conn.close()
            return None, "موجودی کافی نداری."
        conn.execute("UPDATE military_units SET quantity = quantity - ? WHERE id=?", (quantity, u["id"]))

    code = generate_listing_code()
    conn.execute("""INSERT INTO market_listings (listing_code, seller_id, item_category, item_code,
                                                    quantity, price_per_unit, status, created_at)
                     VALUES (?, ?, ?, ?, ?, ?, 'active', ?)""",
                 (code, seller_id, category, item_code, quantity, price_per_unit, now_str()))
    conn.commit()
    conn.close()
    return code, None


def get_active_listings(category: str = None):
    conn = get_db()
    if category:
        rows = conn.execute("SELECT * FROM market_listings WHERE status='active' AND item_category=?",
                             (category,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM market_listings WHERE status='active'").fetchall()
    conn.close()
    return rows


def buy_market_listing(buyer_id: int, listing_code: str):
    conn = get_db()
    listing = conn.execute("SELECT * FROM market_listings WHERE listing_code=? AND status='active'",
                            (listing_code,)).fetchone()
    if not listing:
        conn.close()
        return False, "این آگهی دیگه فعال نیست."

    total_price = listing["quantity"] * listing["price_per_unit"]
    buyer = conn.execute("SELECT gold FROM players WHERE user_id=?", (buyer_id,)).fetchone()
    if buyer["gold"] < total_price:
        conn.close()
        return False, f"پول کافی نداری. قیمت کل: {total_price}"

    category = listing["item_category"]
    if category in RESOURCE_FIELD_MAP or category == "food":
        field = "food" if category == "food" else RESOURCE_FIELD_MAP[category][0]
        cap_field = "food_cap" if category == "food" else RESOURCE_FIELD_MAP[category][1]
        res = conn.execute("SELECT * FROM resources WHERE user_id=?", (buyer_id,)).fetchone()
        if res[field] + listing["quantity"] > res[cap_field]:
            conn.close()
            return False, "ظرفیت انبارت کافی نیست."
        conn.execute(f"UPDATE resources SET {field} = {field} + ? WHERE user_id=?",
                     (listing["quantity"], buyer_id))
    else:
        existing = conn.execute("SELECT * FROM military_units WHERE user_id=? AND item_code=?",
                                 (buyer_id, listing["item_code"])).fetchone()
        if existing:
            conn.execute("UPDATE military_units SET quantity = quantity + ? WHERE id=?",
                         (listing["quantity"], existing["id"]))
        else:
            seller_unit = conn.execute("SELECT damage_per_unit, crew_per_unit FROM military_units WHERE item_code=? LIMIT 1",
                                       (listing["item_code"],)).fetchone()
            dmg = seller_unit["damage_per_unit"] if seller_unit else 20
            crew = seller_unit["crew_per_unit"] if seller_unit else 1
            conn.execute("""INSERT INTO military_units (user_id, item_code, item_type, quantity,
                                                          crew_per_unit, damage_per_unit)
                             VALUES (?, ?, ?, ?, ?, ?)""",
                         (buyer_id, listing["item_code"], category, listing["quantity"], crew, dmg))

    conn.execute("UPDATE players SET gold = gold - ? WHERE user_id=?", (total_price, buyer_id))
    conn.execute("UPDATE players SET gold = gold + ? WHERE user_id=?", (total_price, listing["seller_id"]))
    conn.execute("UPDATE market_listings SET status='sold' WHERE id=?", (listing["id"],))
    conn.commit()
    conn.close()
    return True, None


def cancel_market_listing(seller_id: int, listing_code: str):
    conn = get_db()
    listing = conn.execute("SELECT * FROM market_listings WHERE listing_code=? AND status='active'",
                            (listing_code,)).fetchone()
    if not listing or listing["seller_id"] != seller_id:
        conn.close()
        return False, "آگهی پیدا نشد یا مال تو نیست."

    category = listing["item_category"]
    if category in RESOURCE_FIELD_MAP or category == "food":
        field = "food" if category == "food" else RESOURCE_FIELD_MAP[category][0]
        conn.execute(f"UPDATE resources SET {field} = {field} + ? WHERE user_id=?",
                     (listing["quantity"], seller_id))
    else:
        existing = conn.execute("SELECT * FROM military_units WHERE user_id=? AND item_code=?",
                                 (seller_id, listing["item_code"])).fetchone()
        if existing:
            conn.execute("UPDATE military_units SET quantity = quantity + ? WHERE id=?",
                         (listing["quantity"], existing["id"]))

    conn.execute("UPDATE market_listings SET status='cancelled' WHERE id=?", (listing["id"],))
    conn.commit()
    conn.close()
    return True, None


def market_category_keyboard():
    buttons = [[InlineKeyboardButton(label, callback_data=f"market_cat_{key}")]
               for key, label in MARKET_CATEGORIES.items()]
    buttons.append([InlineKeyboardButton("➕ ثبت آگهی فروش", callback_data="market_sell")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu_shops")])
    return InlineKeyboardMarkup(buttons)


def market_listings_keyboard(category: str):
    listings = get_active_listings(category)
    buttons = []
    for l in listings:
        label = f"{l['listing_code']} — {l['quantity']:.0f} × {l['price_per_unit']} پول"
        buttons.append([InlineKeyboardButton(label, callback_data=f"market_buy_{l['listing_code']}")])
    if not buttons:
        buttons.append([InlineKeyboardButton("❌ آگهی‌ای نیست", callback_data="menu_shops")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="market_browse")])
    return InlineKeyboardMarkup(buttons)


def market_sell_category_keyboard():
    buttons = [[InlineKeyboardButton(label, callback_data=f"marketsell_cat_{key}")]
               for key, label in MARKET_CATEGORIES.items()]
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu_shops")])
    return InlineKeyboardMarkup(buttons)


# ---------- فروش فوری ----------
def get_instant_sell_value(category: str) -> float:
    ratio = float(get_setting("instant_sell_ratio") or 4)
    if category in RESOURCE_FIELD_MAP:
        base = float(get_setting(f"admin_shop_{category}_price") or 10)
    elif category == "food":
        base = float(get_setting("admin_shop_fertilizer_price") or 5)
    else:
        base = float(get_setting(f"instant_sell_unit_value_{category}") or 50)
    return base / ratio


def instant_sell(user_id: int, category: str, item_code, quantity: int):
    unit_value = get_instant_sell_value(category)
    total = round(unit_value * quantity)

    conn = get_db()
    if category in RESOURCE_FIELD_MAP or category == "food":
        field = "food" if category == "food" else RESOURCE_FIELD_MAP[category][0]
        res = conn.execute("SELECT * FROM resources WHERE user_id=?", (user_id,)).fetchone()
        if res[field] < quantity:
            conn.close()
            return False, "موجودی کافی نداری."
        conn.execute(f"UPDATE resources SET {field} = {field} - ? WHERE user_id=?", (quantity, user_id))
    else:
        u = conn.execute("SELECT * FROM military_units WHERE user_id=? AND item_code=?",
                          (user_id, item_code)).fetchone()
        if not u or u["quantity"] < quantity:
            conn.close()
            return False, "موجودی کافی نداری."
        conn.execute("UPDATE military_units SET quantity = quantity - ? WHERE id=?", (quantity, u["id"]))

    conn.execute("UPDATE players SET gold = gold + ? WHERE user_id=?", (total, user_id))
    conn.commit()
    conn.close()
    return True, total


def instant_sell_keyboard(user_id: int):
    buttons = []
    for key, label in RESOURCE_LABELS.items():
        buttons.append([InlineKeyboardButton(f"⚡ {label}", callback_data=f"instsell_{key}")])
    buttons.append([InlineKeyboardButton("⚡ غذا", callback_data="instsell_food")])
    units = get_owned_units(user_id)
    for u in units:
        buttons.append([InlineKeyboardButton(f"⚡ {u['item_code']}", callback_data=f"instsell_{u['item_type']}_{u['item_code']}")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu_shops")])
    return InlineKeyboardMarkup(buttons)


# ---------- منوی اصلی شاپ‌ها ----------
def shops_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏦 شاپ ادمین (منابع)", callback_data="shop_admin")],
        [InlineKeyboardButton("📜 شاپ نقشه‌ساخت", callback_data="shop_blueprint")],
        [InlineKeyboardButton("🏅 شاپ کاپ", callback_data="shop_cap")],
        [InlineKeyboardButton("🛒 بازار بازیکنان", callback_data="market_browse")],
        [InlineKeyboardButton("⚡ فروش فوری", callback_data="shop_instant")],
        [InlineKeyboardButton("🔙 بازگشت به منو", callback_data="menu_main")],
    ])


async def shops_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_answer(query)
    user_id = update.effective_user.id
    data = query.data

    if data == "menu_shops":
        await query.edit_message_text("🏪 *شاپ‌ها*\n\nکدوم شاپ رو می‌خوای؟", reply_markup=shops_menu_keyboard(),
                                       parse_mode="Markdown")
        return

    # ---- شاپ ادمین ----
    if data == "shop_admin":
        await query.edit_message_text(admin_shop_menu_text(), reply_markup=admin_shop_keyboard(),
                                       parse_mode="Markdown")
        return

    if data.startswith("shopres_"):
        resource_type = data.replace("shopres_", "")
        set_pending_action(user_id, "buy_admin_resource", {"resource_type": resource_type})
        price = get_setting(f"admin_shop_{resource_type}_price")
        await query.edit_message_text(f"چند تا می‌خوای بخری؟ (قیمت هر واحد: {price} پول)\nعدد رو تایپ کن.")
        return

    # ---- شاپ کاپ ----
    if data == "shop_cap":
        await query.edit_message_text("🏅 شاپ کاپ", reply_markup=cap_shop_keyboard())
        return

    if data == "capshop_metal":
        set_pending_action(user_id, "buy_cap_metal", {})
        price = get_setting("cap_shop_metal_price")
        await query.edit_message_text(f"چند واحد فلز می‌خوای بخری؟ (قیمت هر واحد: {price} کاپ)\nعدد رو تایپ کن.")
        return

    if data == "capshop_special":
        success, error = buy_cap_special_item(user_id)
        if success:
            reward = get_setting("cap_shop_special_item_gold_reward")
            await query.edit_message_text(f"✅ آیتم ویژه خریداری شد! {reward} پول گرفتی.",
                                           reply_markup=cap_shop_keyboard())
        else:
            await safe_answer(query, error, show_alert=True)
        return

    # ---- شاپ نقشه‌ساخت ----
    if data == "shop_blueprint":
        await query.edit_message_text("📜 شاپ نقشه‌ساخت", reply_markup=blueprint_shop_keyboard())
        return

    if data.startswith("bpbuy_"):
        shop_id = int(data.replace("bpbuy_", ""))
        success, error = buy_blueprint(user_id, shop_id)
        if success:
            await query.edit_message_text("✅ نقشه خریداری شد! از بخش «نقشه‌های من» نصبش کن.",
                                           reply_markup=blueprint_shop_keyboard())
        else:
            await safe_answer(query, error, show_alert=True)
        return

    if data == "bpown_list":
        await query.edit_message_text("📦 نقشه‌های من (برای نصب انتخاب کن):",
                                       reply_markup=owned_blueprints_keyboard(user_id))
        return

    if data.startswith("bpinstall_"):
        blueprint_id = int(data.replace("bpinstall_", ""))
        success, error = install_blueprint(user_id, blueprint_id)
        if success:
            await query.edit_message_text("✅ نقشه نصب شد! کارخونه از الان این مدل رو می‌سازه.",
                                           reply_markup=owned_blueprints_keyboard(user_id))
        else:
            await safe_answer(query, error, show_alert=True)
        return

    # ---- بازار بازیکنان ----
    if data == "market_browse":
        await query.edit_message_text("🛒 بازار بازیکنان — یه دسته انتخاب کن:",
                                       reply_markup=market_category_keyboard())
        return

    if data.startswith("market_cat_"):
        category = data.replace("market_cat_", "")
        await query.edit_message_text(f"🛒 آگهی‌های «{MARKET_CATEGORIES.get(category, category)}»:",
                                       reply_markup=market_listings_keyboard(category))
        return

    if data.startswith("market_buy_"):
        code = data.replace("market_buy_", "")
        listing = get_active_listings()
        target = next((l for l in listing if l["listing_code"] == code), None)
        if not target:
            await safe_answer(query, "این آگهی دیگه فعال نیست.", show_alert=True)
            return
        total = target["quantity"] * target["price_per_unit"]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ تایید خرید", callback_data=f"marketconfirm_{code}")],
            [InlineKeyboardButton("❌ لغو", callback_data="market_browse")],
        ])
        cat_label = MARKET_CATEGORIES.get(target["item_category"], target["item_category"])
        await query.edit_message_text(
            f"🛒 تایید خرید:\n\n{cat_label} × {target['quantity']:.0f}\nقیمت کل: {total} پول",
            reply_markup=kb
        )
        return

    if data.startswith("marketconfirm_"):
        code = data.replace("marketconfirm_", "")
        success, error = buy_market_listing(user_id, code)
        if success:
            await query.edit_message_text("✅ خرید انجام شد!", reply_markup=shops_menu_keyboard())
        else:
            await safe_answer(query, error, show_alert=True)
        return

    if data == "market_sell":
        await query.edit_message_text("چی می‌خوای بفروشی؟", reply_markup=market_sell_category_keyboard())
        return

    if data.startswith("marketsell_cat_"):
        category = data.replace("marketsell_cat_", "")
        if category in ("tank", "jet", "ship", "missile"):
            units = [u for u in get_owned_units(user_id) if u["item_type"] == category]
            if not units:
                await safe_answer(query, "چیزی از این دسته نداری.", show_alert=True)
                return
            buttons = [[InlineKeyboardButton(f"{u['item_code']} ({u['quantity']:.0f})",
                                              callback_data=f"marketsell_item_{u['item_code']}")] for u in units]
            buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu_shops")])
            await query.edit_message_text("کدوم مدل؟", reply_markup=InlineKeyboardMarkup(buttons))
        else:
            set_pending_action(user_id, "market_sell_quantity", {"category": category, "item_code": None})
            await query.edit_message_text("چند تا می‌خوای بفروشی؟ عدد رو تایپ کن.")
        return

    if data.startswith("marketsell_item_"):
        item_code = data.replace("marketsell_item_", "")
        conn = get_db()
        u = conn.execute("SELECT item_type FROM military_units WHERE user_id=? AND item_code=?",
                          (user_id, item_code)).fetchone()
        conn.close()
        set_pending_action(user_id, "market_sell_quantity", {"category": u["item_type"], "item_code": item_code})
        await query.edit_message_text("چند تا می‌خوای بفروشی؟ عدد رو تایپ کن.")
        return

    # ---- فروش فوری ----
    if data == "shop_instant":
        await query.edit_message_text("⚡ فروش فوری — چی می‌خوای بفروشی؟ (۱/۴ قیمت بازار)",
                                       reply_markup=instant_sell_keyboard(user_id))
        return

    if data.startswith("instsell_"):
        rest = data.replace("instsell_", "")
        if "_" in rest:
            item_type, item_code = rest.split("_", 1)
            set_pending_action(user_id, "instant_sell_quantity", {"category": item_type, "item_code": item_code})
        else:
            set_pending_action(user_id, "instant_sell_quantity", {"category": rest, "item_code": None})
        unit_value = get_instant_sell_value(rest.split("_")[0])
        await query.edit_message_text(f"چند تا می‌خوای بفروشی؟ (ارزش هر واحد: {unit_value:.1f} پول)\nعدد رو تایپ کن.")
        return


# ============================================================
#  فاز ۱۲: پنل ادمین
# ============================================================
SETTINGS_CATEGORIES = {
    "build": ("🏗️ ساخت‌وساز", [
        ("house_build_gold", "قیمت خونه (پول)"), ("house_build_metal", "قیمت خونه (فلز)"),
        ("power_civil_build_gold", "نیروگاه عادی (پول)"), ("power_civil_build_metal", "نیروگاه عادی (فلز)"),
        ("power_industrial_build_gold", "نیروگاه اتمی (پول)"), ("power_industrial_build_metal", "نیروگاه اتمی (فلز)"),
        ("mine_metal_build_gold", "معدن فلز (پول)"), ("mine_metal_build_fertilizer", "معدن فلز (کود)"),
        ("land_upgrade_gold", "ارتقای طول کشور (پول)"), ("land_upgrade_fertilizer", "ارتقای طول کشور (کود)"),
        ("land_upgrade_electricity", "ارتقای طول کشور (برق)"),
    ]),
    "military": ("🏭 کارخونه و نظامی", [
        ("factory_tank_build_gold", "کارخونه تانک (پول)"), ("factory_tank_build_metal", "کارخونه تانک (فلز)"),
        ("factory_jet_build_gold", "کارخونه جنگنده (پول)"), ("factory_jet_build_metal", "کارخونه جنگنده (فلز)"),
        ("factory_ship_build_gold", "کارخونه کشتی (پول)"), ("factory_ship_build_metal", "کارخونه کشتی (فلز)"),
        ("factory_missile_build_gold", "کارخونه موشک (پول)"), ("factory_missile_build_metal", "کارخونه موشک (فلز)"),
        ("factory_metal_cost_per_unit", "مصرف فلز هر واحد تولیدی"),
        ("factory_electricity_cost_per_unit", "مصرف برق صنعتی هر واحد"),
        ("basic_tank_damage", "دمیج تانک پایه"), ("basic_jet_damage", "دمیج جنگنده پایه"),
        ("basic_ship_damage", "دمیج کشتی پایه"), ("basic_missile_damage", "دمیج موشک پایه"),
    ]),
    "defense": ("🛡️ پدافند", [
        ("defense_tier1_rate", "نرخ رهگیری تیر ۱ (٪)"), ("defense_tier2_rate", "نرخ رهگیری تیر ۲ (٪)"),
        ("defense_tier3_rate", "نرخ رهگیری تیر ۳ (٪)"), ("defense_tier4_rate", "نرخ رهگیری تیر ۴ (٪)"),
        ("defense_repair_base_hours", "زمان پایه تعمیر (ساعت)"),
        ("defense_repair_gold_per_tier", "هزینه تعمیر هر تیر (پول)"),
    ]),
    "war": ("⚔️ جنگ", [
        ("war_power_gap_percent", "حداکثر تفاوت قدرت مجاز (٪)"),
        ("war_admin_timeout_hours", "تایم‌اوت تایید ادمین (ساعت)"),
        ("war_regular_duration_hours", "مدت جنگ عادی (ساعت)"),
        ("war_cap_reward_per_effective_damage", "کاپ به‌ازای هر واحد دمیج مؤثر"),
        ("war_alliance_duration_hours", "مدت جنگ اتحادی (ساعت)"),
        ("war_alliance_shield_hours", "مدت سپر بعد جنگ اتحادی (ساعت)"),
        ("war_alliance_cap_per_destroyed", "کاپ به‌ازای هر کشور نابودشده"),
    ]),
    "alliance": ("🤝 اتحاد", [
        ("alliance_create_gold_cost", "هزینه ساخت اتحاد"),
        ("alliance_default_max_members", "ظرفیت پایه اعضا"),
        ("alliance_gift_max_percent", "سقف گیفت (٪ دارایی)"),
        ("alliance_gift_cooldown_hours", "کول‌داون گیفت (ساعت)"),
        ("alliance_kick_cooldown_hours", "کول‌داون بعد اخراج (ساعت)"),
        ("alliance_war_min_members", "حداقل عضو برای جنگ اتحادی"),
    ]),
    "shop": ("🏪 شاپ‌ها", [
        ("admin_shop_oil_price", "قیمت نفت (شاپ ادمین)"), ("admin_shop_metal_price", "قیمت فلز (شاپ ادمین)"),
        ("admin_shop_fertilizer_price", "قیمت کود (شاپ ادمین)"), ("admin_shop_electricity_price", "قیمت برق (شاپ ادمین)"),
        ("cap_shop_metal_price", "قیمت فلز با کاپ"), ("cap_shop_special_item_cap_cost", "هزینه آیتم ویژه (کاپ)"),
        ("cap_shop_special_item_gold_reward", "جایزه آیتم ویژه (پول)"),
        ("instant_sell_ratio", "نسبت فروش فوری (۱/X)"),
    ]),
    "research": ("🔬 تحقیقات", [
        ("research_armor_bonus_per_level", "بونوس زره هر سطح (٪)"),
        ("research_oil_refine_bonus_per_level", "بونوس پالایش نفت هر سطح (٪)"),
        ("research_metal_bonus_per_level", "بونوس فرآوری فلز هر سطح (٪)"),
        ("research_food_bonus_per_level", "بونوس کشاورزی هر سطح (٪)"),
        ("research_upgrade_base_gold", "هزینه پایه ارتقای تحقیق"),
        ("research_max_level", "سقف سطح تحقیق"),
    ]),
    "production": ("🌾 تولید و جمعیت", [
        ("mine_fertilizer_rate_per_worker", "نرخ تولید کود هر کارگر"),
        ("mine_oil_rate_per_worker", "نرخ تولید نفت هر کارگر"),
        ("mine_metal_rate_per_worker", "نرخ تولید فلز هر کارگر"),
        ("farm_food_rate_per_level", "نرخ تولید غذا هر سطح مزرعه"),
        ("population_food_consumption_per_hour", "مصرف غذای هر نفر در ساعت"),
        ("house_hp", "اچ‌پی هر خونه"), ("farm_hp", "اچ‌پی هر مزرعه"),
    ]),
}


def admin_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ تنظیم قیمت‌ها", callback_data="admin_settings")],
        [InlineKeyboardButton("⚔️ حمله‌های در انتظار تایید", callback_data="admin_pending_attacks")],
        [InlineKeyboardButton("🤝 مدیریت اتحادها", callback_data="admin_alliances")],
        [InlineKeyboardButton("📊 آمار", callback_data="admin_stats")],
        [InlineKeyboardButton("🔙 بازگشت به منو", callback_data="menu_main")],
    ])


def admin_settings_categories_keyboard():
    buttons = [[InlineKeyboardButton(label, callback_data=f"admin_cat_{key}")]
               for key, (label, _) in SETTINGS_CATEGORIES.items()]
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu_admin")])
    return InlineKeyboardMarkup(buttons)


def admin_category_keyboard(cat_key: str):
    _, items = SETTINGS_CATEGORIES[cat_key]
    buttons = []
    for key, label in items:
        value = get_setting(key)
        buttons.append([InlineKeyboardButton(f"{label}: {value}", callback_data=f"admin_editset_{key}")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_settings")])
    return InlineKeyboardMarkup(buttons)


def admin_pending_attacks_keyboard():
    pending = get_pending_admin_attacks()
    buttons = []
    for w in pending:
        conn = get_db()
        att = conn.execute("SELECT country_name FROM players WHERE user_id=?", (w["attacker_id"],)).fetchone()
        defn = conn.execute("SELECT country_name FROM players WHERE user_id=?", (w["defender_id"],)).fetchone()
        conn.close()
        att_name = att["country_name"] if att else str(w["attacker_id"])
        def_name = defn["country_name"] if defn else str(w["defender_id"])
        buttons.append([InlineKeyboardButton(f"✅ تایید: {att_name}→{def_name}", callback_data=f"admin_approveatk_{w['id']}")])
        buttons.append([InlineKeyboardButton(f"❌ رد: {att_name}→{def_name}", callback_data=f"admin_rejectatk_{w['id']}")])
    if not pending:
        buttons.append([InlineKeyboardButton("هیچ درخواستی نیست", callback_data="menu_admin")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu_admin")])
    return InlineKeyboardMarkup(buttons)


def admin_alliances_keyboard():
    conn = get_db()
    alliances = conn.execute("SELECT * FROM alliances").fetchall()
    conn.close()
    buttons = [[InlineKeyboardButton(f"{a['name']}{'👑(ادمین)' if a['is_admin_alliance'] else ''}",
                                       callback_data=f"admin_allview_{a['id']}")] for a in alliances]
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu_admin")])
    return InlineKeyboardMarkup(buttons)


def admin_alliance_members_keyboard(alliance_id: int):
    members = get_alliance_members(alliance_id)
    buttons = [[InlineKeyboardButton(f"👢 اخراج {m['country_name'] or m['user_id']}",
                                       callback_data=f"admin_kickmember_{alliance_id}_{m['user_id']}")]
               for m in members]
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_alliances")])
    return InlineKeyboardMarkup(buttons)


def admin_stats_text() -> str:
    today = datetime.utcnow().date().isoformat()
    conn = get_db()
    total_users = conn.execute("SELECT COUNT(*) as c FROM players").fetchone()["c"]
    wars_today = conn.execute(
        "SELECT COUNT(*) as c FROM war_regular WHERE start_time LIKE ?", (f"{today}%",)
    ).fetchone()["c"]
    alliance_wars_today = conn.execute(
        "SELECT COUNT(*) as c FROM war_alliance WHERE start_time LIKE ?", (f"{today}%",)
    ).fetchone()["c"]
    announcements_today = conn.execute(
        "SELECT COUNT(*) as c FROM channel_announcements WHERE sent_at LIKE ?", (f"{today}%",)
    ).fetchone()["c"]
    alliances_today = conn.execute(
        "SELECT COUNT(*) as c FROM alliances WHERE created_at LIKE ?", (f"{today}%",)
    ).fetchone()["c"]
    total_alliances = conn.execute("SELECT COUNT(*) as c FROM alliances").fetchone()["c"]
    conn.close()

    return (
        f"📊 *آمار بازی*\n\n"
        f"👥 کل کاربران ثبت‌شده: {total_users}\n"
        f"🤝 کل اتحادها: {total_alliances} (امروز: {alliances_today})\n"
        f"⚔️ جنگ عادی امروز: {wars_today}\n"
        f"⚔️ جنگ اتحادی امروز: {alliance_wars_today}\n"
        f"📢 اعلامیه‌های امروز: {announcements_today}\n"
    )


async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_answer(query)
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return
    data = query.data

    if data == "menu_admin":
        await query.edit_message_text("👑 *پنل ادمین*", reply_markup=admin_main_keyboard(), parse_mode="Markdown")
        return

    if data == "admin_settings":
        await query.edit_message_text("⚙️ کدوم دسته رو می‌خوای تنظیم کنی؟",
                                       reply_markup=admin_settings_categories_keyboard())
        return

    if data.startswith("admin_cat_"):
        cat_key = data.replace("admin_cat_", "")
        label = SETTINGS_CATEGORIES[cat_key][0]
        await query.edit_message_text(f"{label}\n\nروی هرکدوم بزن تا مقدارشو تغییر بدی:",
                                       reply_markup=admin_category_keyboard(cat_key))
        return

    if data.startswith("admin_editset_"):
        setting_key = data.replace("admin_editset_", "")
        current = get_setting(setting_key)
        set_pending_action(user_id, "admin_set_setting", {"key": setting_key})
        await query.edit_message_text(f"مقدار فعلی: {current}\n\nمقدار جدید رو بفرست (عدد):")
        return

    if data == "admin_pending_attacks":
        await query.edit_message_text("⚔️ درخواست‌های حمله در انتظار تایید:",
                                       reply_markup=admin_pending_attacks_keyboard())
        return

    if data.startswith("admin_approveatk_"):
        war_id = int(data.replace("admin_approveatk_", ""))
        result, error = approve_pending_attack(war_id)
        if result:
            war_hours = get_setting("war_regular_duration_hours")
            await query.edit_message_text(
                f"✅ حمله تایید شد و شروع شد.\nدمیج خام: {result['raw_damage']}\n"
                f"نتیجه بعد از {war_hours} ساعت اعلام می‌شه.",
                reply_markup=admin_pending_attacks_keyboard()
            )
            war = get_db().execute("SELECT attacker_id, defender_id FROM war_regular WHERE id=?", (war_id,)).fetchone()
            try:
                await context.bot.send_message(war["attacker_id"], "✅ ادمین حمله‌ت رو تایید کرد! نتیجه به‌زودی اعلام می‌شه.")
                await context.bot.send_message(war["defender_id"], "🚨 کشور شما مورد حمله (تایید ادمین) قرار گرفت! نتیجه به‌زودی مشخص می‌شه.")
            except Exception:
                pass
        else:
            await safe_answer(query, error, show_alert=True)
        return

    if data.startswith("admin_rejectatk_"):
        war_id = int(data.replace("admin_rejectatk_", ""))
        war = get_db().execute("SELECT attacker_id FROM war_regular WHERE id=?", (war_id,)).fetchone()
        reject_pending_attack(war_id)
        await query.edit_message_text("❌ درخواست رد شد.", reply_markup=admin_pending_attacks_keyboard())
        if war:
            try:
                await context.bot.send_message(war["attacker_id"], "❌ ادمین درخواست حمله‌ت رو رد کرد.")
            except Exception:
                pass
        return

    if data == "admin_alliances":
        await query.edit_message_text("🤝 اتحادها:", reply_markup=admin_alliances_keyboard())
        return

    if data.startswith("admin_allview_"):
        alliance_id = int(data.replace("admin_allview_", ""))
        await query.edit_message_text("اعضا (برای اخراج بزن):",
                                       reply_markup=admin_alliance_members_keyboard(alliance_id))
        return

    if data.startswith("admin_kickmember_"):
        parts = data.replace("admin_kickmember_", "").split("_")
        alliance_id, target_id = int(parts[0]), int(parts[1])
        success, error = kick_member(user_id, target_id)
        if success:
            await query.edit_message_text("✅ عضو اخراج شد.", reply_markup=admin_alliance_members_keyboard(alliance_id))
            try:
                await context.bot.send_message(target_id, "🚨 ادمین شما رو از اتحاد اخراج کرد.")
            except Exception:
                pass
        else:
            await safe_answer(query, error, show_alert=True)
        return

    if data == "admin_stats":
        await query.edit_message_text(admin_stats_text(), reply_markup=admin_main_keyboard(), parse_mode="Markdown")
        return


# ============================================================
#  فاز ۱۳: زمان‌بند خودکار (APScheduler از طریق JobQueue تلگرام)
# ============================================================
async def job_process_regular_wars(context: ContextTypes.DEFAULT_TYPE):
    """جنگ‌های عادی که زمانشون تموم شده رو نتیجه‌گیری و اطلاع‌رسانی می‌کنه"""
    now = now_str()
    conn = get_db()
    due_wars = conn.execute(
        "SELECT id, attacker_id, defender_id FROM war_regular WHERE status='ongoing' AND end_time <= ?", (now,)
    ).fetchall()
    conn.close()

    for w in due_wars:
        resolve_regular_war(w["id"])
        conn2 = get_db()
        war = conn2.execute("SELECT * FROM war_regular WHERE id=?", (w["id"],)).fetchone()
        conn2.close()
        if not war:
            continue
        result_dict = {
            "result": war["result"], "raw_damage": war["total_damage"],
            "blocked_damage": war["defense_blocked"],
            "effective_damage": max(0, war["total_damage"] - war["defense_blocked"]),
        }
        outcome_attacker = "🎉 حمله‌ت موفق بود!" if war["result"] == "attacker_win" else "😔 دفاع حریف موفق بود."
        outcome_defender = "🛡️ دفاعت موفق بود!" if war["result"] == "defender_win" else "🚨 کشورت شکست خورد!"
        try:
            await context.bot.send_message(
                w["attacker_id"],
                f"⚔️ نتیجه حمله‌ت مشخص شد!\n{outcome_attacker}\n"
                f"دمیج مؤثر: {result_dict['effective_damage']:.0f}"
            )
        except Exception:
            pass
        try:
            await context.bot.send_message(
                w["defender_id"],
                f"⚔️ نتیجه حمله‌ای که بهت شد مشخص شد!\n{outcome_defender}\n"
                f"دمیج مؤثر وارده: {result_dict['effective_damage']:.0f}"
            )
        except Exception:
            pass
        await post_war_announcement(context.bot, w["attacker_id"], w["defender_id"], result_dict)


async def job_process_alliance_wars(context: ContextTypes.DEFAULT_TYPE):
    """جنگ‌های اتحادی که زمانشون تموم شده رو نتیجه‌گیری می‌کنه"""
    now = now_str()
    conn = get_db()
    due_wars = conn.execute(
        "SELECT id, attacker_alliance_id, defender_alliance_id FROM war_alliance "
        "WHERE status='ongoing' AND end_time <= ?", (now,)
    ).fetchall()
    conn.close()

    for w in due_wars:
        result = resolve_alliance_war(w["id"])
        await post_alliance_war_announcement(context.bot, w["id"], "finished")

        conn2 = get_db()
        att_members = get_alliance_members(w["attacker_alliance_id"])
        conn2.close()
        for m in att_members:
            try:
                await context.bot.send_message(
                    m["user_id"],
                    f"🏁 جنگ اتحادی تموم شد!\nکشورهای نابودشده: {result['destroyed_count']}\n"
                    f"کاپ اضافه‌شده به گاوصندوق: {result['cap_earned']}"
                )
            except Exception:
                pass


async def job_process_repairs(context: ContextTypes.DEFAULT_TYPE):
    """پدافندهایی که زمان تعمیرشون تموم شده رو فعال و به مالکشون اطلاع می‌ده"""
    now = now_str()
    conn = get_db()
    due_repairs = conn.execute(
        "SELECT id, user_id, tier FROM defenses WHERE under_repair_until IS NOT NULL AND under_repair_until <= ?",
        (now,)
    ).fetchall()
    for r in due_repairs:
        conn.execute("UPDATE defenses SET hits_remaining=max_hits, under_repair_until=NULL WHERE id=?", (r["id"],))
    conn.commit()
    conn.close()

    for r in due_repairs:
        try:
            await context.bot.send_message(r["user_id"], f"🔧 تعمیر پدافند تیر {r['tier']} تموم شد و دوباره آماده‌ست!")
        except Exception:
            pass


async def job_process_pending_attack_timeouts(context: ContextTypes.DEFAULT_TYPE):
    """درخواست‌های حمله خارج از محدوده که ادمین تا ۱۲ ساعت جواب نداده، خودکار بر اساس تفاوت قدرت
    فعلی تصمیم‌گیری می‌شه: اگه زیر حد مجاز باشه تایید، وگرنه رد می‌شه."""
    now = now_str()
    conn = get_db()
    due = conn.execute(
        "SELECT * FROM war_regular WHERE status='pending_admin' AND admin_timeout_check <= ?", (now,)
    ).fetchall()
    conn.close()

    gap_limit = float(get_setting("war_power_gap_percent") or 70)
    for w in due:
        gap = power_gap_percent(get_country_power(w["attacker_id"]), get_country_power(w["defender_id"]))
        if gap <= gap_limit:
            result, error = approve_pending_attack(w["id"])
            if result:
                try:
                    await context.bot.send_message(
                        w["attacker_id"],
                        "⏳ ادمین ۱۲ ساعت جواب نداد؛ چون تفاوت قدرت الان تو محدوده مجازه، حمله خودکار تایید شد!"
                    )
                    await context.bot.send_message(w["defender_id"], "🚨 حمله‌ای در انتظار تایید، خودکار تایید و شروع شد.")
                except Exception:
                    pass
        else:
            reject_pending_attack(w["id"])
            try:
                await context.bot.send_message(
                    w["attacker_id"],
                    "⏳ ادمین ۱۲ ساعت جواب نداد و چون تفاوت قدرت هنوز زیاده، درخواست خودکار رد شد."
                )
            except Exception:
                pass


async def periodic_check_job(context: ContextTypes.DEFAULT_TYPE):
    """هر ۵ دقیقه اجرا می‌شه؛ همه چک‌های زمان‌بندی‌شده رو انجام می‌ده"""
    try:
        await job_process_regular_wars(context)
    except Exception as e:
        logger.error(f"خطا در پردازش جنگ‌های عادی: {e}")
    try:
        await job_process_alliance_wars(context)
    except Exception as e:
        logger.error(f"خطا در پردازش جنگ‌های اتحادی: {e}")
    try:
        await job_process_repairs(context)
    except Exception as e:
        logger.error(f"خطا در پردازش تعمیرات: {e}")
    try:
        await job_process_pending_attack_timeouts(context)
    except Exception as e:
        logger.error(f"خطا در پردازش تایم‌اوت حمله‌ها: {e}")


# ============================================================
#  اجرای اصلی
# ============================================================
def main():
    if not BOT_TOKEN:
        raise RuntimeError("لطفاً BOT_TOKEN رو در متغیرهای محیطی Railway تنظیم کن.")

    init_db()
    init_global_settings()
    init_blueprint_shop()

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

    # فاز ۷: جنگ اتحادی
    war_patterns = "^(menu_alliance_war|warall_)"
    app.add_handler(CallbackQueryHandler(alliance_war_callback, pattern=war_patterns))
    app.add_handler(CommandHandler("start_alliance_war", start_alliance_war_command))

    # فاز ۸: شاپ‌ها
    shop_patterns = ("^(menu_shops|shop_|shopres_|capshop_|bpbuy_|bpown_|bpinstall_|market_|"
                      "marketconfirm_|marketsell_|instsell_)")
    app.add_handler(CallbackQueryHandler(shops_callback, pattern=shop_patterns))

    # فاز ۹: آزمایشگاه/تحقیقات
    app.add_handler(CallbackQueryHandler(research_callback, pattern="^research_"))

    # فاز ۱۰: رنکینگ/آمار/رفرال
    app.add_handler(CallbackQueryHandler(stats_ranking_callback, pattern="^claim_referral$"))

    # فاز ۱۱: کانال و عضویت اجباری
    app.add_handler(CallbackQueryHandler(check_membership_callback, pattern="^check_membership$"))

    # فاز ۱۲: پنل ادمین
    admin_patterns = "^(admin_)"
    app.add_handler(CallbackQueryHandler(admin_panel_callback, pattern=admin_patterns))

    # پیام‌های متنی (برای وارد کردن تعداد دلخواه) - باید بعد از کامندها ثبت بشه
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_input_handler))

    # فاز ۱۳: زمان‌بند خودکار - هر ۵ دقیقه چک می‌کنه: نتیجه جنگ‌های تموم‌شده، تعمیرات، تایم‌اوت ادمین
    if app.job_queue is not None:
        app.job_queue.run_repeating(periodic_check_job, interval=300, first=15)
        logger.info("زمان‌بند خودکار (هر ۵ دقیقه) فعال شد.")
    else:
        logger.warning(
            "⚠️ job_queue در دسترس نیست! باید requirements.txt رو با "
            "'python-telegram-bot[job-queue]==21.6' آپدیت کنی وگرنه جنگ‌ها هیچ‌وقت نتیجه‌گیری نمی‌شن."
        )

    logger.info("بات در حال اجراست...")
    app.run_polling()


if __name__ == "__main__":
    main()
