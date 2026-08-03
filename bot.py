import os
import time
import random
import logging
import sqlite3
import secrets
import string

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_IDS = {
    int(x) for x in os.environ.get("ADMIN_IDS", "").replace(" ", "").split(",") if x.isdigit()
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "farm.db")

START_COINS = 500
START_FLOUR = 50
START_STORAGE = 1000
STORAGE_UPGRADE_COST = 250
STORAGE_UPGRADE_AMOUNT = 1000
DAILY_COOLDOWN_SECONDS = 24 * 3600
DAILY_BASE_REFERENCE = 300

LIVESTOCK_BUILDINGS = {
    "مرغداری": {
        "emoji": "🐔", "buy_cost": 2000, "animal_key": "مرغ", "animal_cost": 50,
        "base_max_animals": 130, "base_buffer_cap": 1300, "rate_per_animal_hour": 0.3,
        "output": "تخم_مرغ", "output_emoji": "🥚",
    },
    "گاوداری": {
        "emoji": "🐄", "buy_cost": 3000, "animal_key": "گاو", "animal_cost": 400,
        "base_max_animals": 100, "base_buffer_cap": 1000, "rate_per_animal_hour": 0.3,
        "output": "شیر", "output_emoji": "🥛",
    },
    "گوسفندداری": {
        "emoji": "🐑", "buy_cost": 2500, "animal_key": "گوسفند", "animal_cost": 250,
        "base_max_animals": 110, "base_buffer_cap": 1100, "rate_per_animal_hour": 0.3,
        "output": "پشم", "output_emoji": "🧶",
    },
}

FARM_BUILDINGS = {
    "مزرعه_گندم":      {"emoji": "🌾", "buy_cost": 1500, "crop": "گندم",      "plant_cost": 12, "plant_seconds": 900, "yield_qty": 50, "buffer_cap": 2000},
    "مزرعه_برنج":      {"emoji": "🍚", "buy_cost": 1500, "crop": "برنج",      "plant_cost": 15, "plant_seconds": 900, "yield_qty": 50, "buffer_cap": 2000},
    "مزرعه_نیشکر":     {"emoji": "🎋", "buy_cost": 1500, "crop": "نیشکر",     "plant_cost": 14, "plant_seconds": 900, "yield_qty": 50, "buffer_cap": 2000},
    "مزرعه_سیب_زمینی": {"emoji": "🥔", "buy_cost": 1500, "crop": "سیب_زمینی", "plant_cost": 13, "plant_seconds": 900, "yield_qty": 50, "buffer_cap": 2000},
}

FACTORY_BUILDINGS = {
    "کارخونه_خمیر":  {"emoji": "🥟", "buy_cost": 1000, "input": "ارد",     "input_qty": 20,  "output": "خمیر", "output_qty": 15, "seconds": 300},
    "کارخونه_نان":   {"emoji": "🍞", "buy_cost": 1200, "input": "خمیر",    "input_qty": 15,  "output": "نان",  "output_qty": 15, "seconds": 300},
    "کارخونه_نیمرو": {"emoji": "🍳", "buy_cost": 800,  "input": "تخم_مرغ", "input_qty": 10,  "output": "نیمرو", "output_qty": 10, "seconds": 180},
    "کارخونه_نخ":    {"emoji": "🧵", "buy_cost": 1000, "input": "پشم",     "input_qty": 100, "output": "نخ",   "output_qty": 40, "seconds": 300},
    "کارخونه_پارچه": {"emoji": "🧣", "buy_cost": 1200, "input": "نخ",      "input_qty": 40,  "output": "پارچه", "output_qty": 40, "seconds": 300},
    "کارخونه_ماست":  {"emoji": "🥣", "buy_cost": 900,  "input": "شیر",     "input_qty": 100, "output": "ماست", "output_qty": 40, "seconds": 300},
}

BUILDING_UPGRADE_RATIO = 0.5
LEVEL_ANIMAL_BONUS = 50
LEVEL_BUFFER_BONUS = 500
LEVEL_RATE_BONUS = 0.10

BUY_CATALOG = {
    "نون":     {"emoji": "🥖"},
    "کیک":     {"emoji": "🎂"},
    "پیتزا":   {"emoji": "🍕"},
    "هات_داگ": {"emoji": "🌭"},
    "سوسیس":   {"emoji": "🌭"},
    "فرنچ":    {"emoji": "🍟"},
    "پنیر":    {"emoji": "🧀"},
    "لباس":    {"emoji": "👚"},
    "ارد":     {"emoji": "⬜"},
    "شکر":     {"emoji": "⬜"},
}
BUY_BATCH = 10

DEFAULT_BUY_PRICES = {
    "نون": 10, "کیک": 40, "پیتزا": 35, "هات_داگ": 20, "سوسیس": 15,
    "فرنچ": 12, "پنیر": 18, "لباس": 50, "ارد": 5, "شکر": 6,
}
DEFAULT_SELL_PRICES = {
    "گندم": 42, "برنج": 52, "نیشکر": 49, "سیب_زمینی": 45,
    "تخم_مرغ": 2, "پشم": 2, "شیر": 2,
    "خمیر": 3, "نان": 6, "نخ": 3, "پارچه": 6, "ماست": 5, "نیمرو": 5,
    "نون": 6, "کیک": 25, "پیتزا": 22, "هات_داگ": 12, "سوسیس": 9,
    "فرنچ": 7, "پنیر": 11, "لباس": 30, "ارد": 3, "شکر": 3,
}
ALL_PRICED_ITEMS = sorted(set(DEFAULT_BUY_PRICES) | set(DEFAULT_SELL_PRICES))

ITEM_EMOJI = {
    "گندم": "🌾", "برنج": "🍚", "نیشکر": "🎋", "سیب_زمینی": "🥔",
    "تخم_مرغ": "🥚", "شیر": "🥛", "پشم": "🧶",
    "خمیر": "🥟", "نان": "🍞", "نیمرو": "🍳", "نخ": "🧵", "پارچه": "🧣", "ماست": "🥣",
    **{k: v["emoji"] for k, v in BUY_CATALOG.items()},
}

ALL_BUILDINGS = {}
for k, v in LIVESTOCK_BUILDINGS.items():
    ALL_BUILDINGS[k] = {"kind": "livestock", **v}
for k, v in FARM_BUILDINGS.items():
    ALL_BUILDINGS[k] = {"kind": "farm", **v}
for k, v in FACTORY_BUILDINGS.items():
    ALL_BUILDINGS[k] = {"kind": "factory", **v}

CAT_TITLE = {"livestock": "دامداری", "farm": "مزرعه", "factory": "کارخونه"}
CAT_EMOJI = {"livestock": "🥚", "farm": "🌱", "factory": "🏭"}
CAT_REGISTRY = {"livestock": LIVESTOCK_BUILDINGS, "farm": FARM_BUILDINGS, "factory": FACTORY_BUILDINGS}


def db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS players (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            coins INTEGER DEFAULT 500,
            storage_capacity INTEGER DEFAULT 1000,
            last_daily_ts REAL DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            user_id INTEGER, item_key TEXT, quantity INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, item_key)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS owned_buildings (
            user_id INTEGER, building_key TEXT, level INTEGER DEFAULT 1,
            PRIMARY KEY (user_id, building_key)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS livestock_state (
            user_id INTEGER, building_key TEXT,
            animal_count INTEGER DEFAULT 0, buffer_qty REAL DEFAULT 0,
            last_update_ts REAL DEFAULT 0, total_collected INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, building_key)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS farm_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, building_key TEXT,
            ready_at REAL, collected INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS factory_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, building_key TEXT,
            ready_at REAL, collected INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS item_prices (
            item_key TEXT PRIMARY KEY, buy_price INTEGER DEFAULT 0, sell_price INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS serials (
            code TEXT PRIMARY KEY, amount INTEGER, created_by INTEGER,
            redeemed_by INTEGER DEFAULT NULL, created_at REAL
        )
    """)
    for item in ALL_PRICED_ITEMS:
        c.execute(
            "INSERT OR IGNORE INTO item_prices (item_key, buy_price, sell_price) VALUES (?, ?, ?)",
            (item, DEFAULT_BUY_PRICES.get(item, 0), DEFAULT_SELL_PRICES.get(item, 0)),
        )
    conn.commit()
    conn.close()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def get_price(item_key: str):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT buy_price, sell_price FROM item_prices WHERE item_key=?", (item_key,))
    row = c.fetchone()
    conn.close()
    if not row:
        return 0, 0
    return row["buy_price"], row["sell_price"]


def set_price(item_key: str, buy_price: int, sell_price: int):
    conn = db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO item_prices (item_key, buy_price, sell_price) VALUES (?, ?, ?)
        ON CONFLICT(item_key) DO UPDATE SET buy_price=excluded.buy_price, sell_price=excluded.sell_price
    """, (item_key, buy_price, sell_price))
    conn.commit()
    conn.close()


def ensure_player(user_id: int, username: str):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM players WHERE user_id=?", (user_id,))
    is_new = c.fetchone() is None
    if is_new:
        c.execute(
            "INSERT INTO players (user_id, username, coins, storage_capacity) VALUES (?, ?, ?, ?)",
            (user_id, username or str(user_id), START_COINS, START_STORAGE),
        )
    else:
        c.execute("UPDATE players SET username=? WHERE user_id=?", (username or str(user_id), user_id))
    conn.commit()
    conn.close()
    if is_new:
        add_to_inventory(user_id, "ارد", START_FLOUR)


def get_player(user_id: int):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT * FROM players WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row


def get_inventory(user_id: int):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT item_key, quantity FROM inventory WHERE user_id=?", (user_id,))
    rows = c.fetchall()
    conn.close()
    return {r["item_key"]: r["quantity"] for r in rows}


def total_stored(user_id: int) -> int:
    return sum(get_inventory(user_id).values())


def add_to_inventory(user_id: int, item_key: str, qty) -> int:
    qty = int(qty)
    if qty <= 0:
        return 0
    player = get_player(user_id)
    cap = player["storage_capacity"] if player else START_STORAGE
    room = max(0, cap - total_stored(user_id))
    added = min(qty, room)
    if added <= 0:
        return 0
    conn = db()
    c = conn.cursor()
    c.execute("SELECT quantity FROM inventory WHERE user_id=? AND item_key=?", (user_id, item_key))
    row = c.fetchone()
    if row:
        c.execute("UPDATE inventory SET quantity = quantity + ? WHERE user_id=? AND item_key=?", (added, user_id, item_key))
    else:
        c.execute("INSERT INTO inventory (user_id, item_key, quantity) VALUES (?, ?, ?)", (user_id, item_key, added))
    conn.commit()
    conn.close()
    return added


def remove_from_inventory(user_id: int, item_key: str, qty: int) -> bool:
    inv = get_inventory(user_id)
    if inv.get(item_key, 0) < qty:
        return False
    conn = db()
    c = conn.cursor()
    c.execute("UPDATE inventory SET quantity = quantity - ? WHERE user_id=? AND item_key=?", (qty, user_id, item_key))
    conn.commit()
    conn.close()
    return True


def fmt_countdown(seconds_left: float) -> str:
    seconds_left = max(0, int(seconds_left))
    h = seconds_left // 3600
    m = (seconds_left % 3600) // 60
    s = seconds_left % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


async def safe_answer(query, **kwargs):
    try:
        await query.answer(**kwargs)
    except Exception:
        pass


def building_label(key: str) -> str:
    return key.replace("_", " ")


def get_owned_buildings(user_id: int):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT building_key, level FROM owned_buildings WHERE user_id=?", (user_id,))
    rows = c.fetchall()
    conn.close()
    return {r["building_key"]: r["level"] for r in rows}


def owns_building(user_id: int, building_key: str) -> bool:
    return building_key in get_owned_buildings(user_id)


def buy_building(user_id: int, building_key: str):
    info = ALL_BUILDINGS[building_key]
    owned = get_owned_buildings(user_id)
    if building_key in owned:
        return False, "این ساختمون رو قبلاً خریدی؛ هر ساختمون فقط یه‌بار قابل خریده."
    player = get_player(user_id)
    if player["coins"] < info["buy_cost"]:
        return False, f"سکه کافی نداری. هزینه: {info['buy_cost']}"
    conn = db()
    c = conn.cursor()
    c.execute("UPDATE players SET coins = coins - ? WHERE user_id=?", (info["buy_cost"], user_id))
    c.execute("INSERT INTO owned_buildings (user_id, building_key, level) VALUES (?, ?, 1)", (user_id, building_key))
    if info["kind"] == "livestock":
        c.execute(
            "INSERT INTO livestock_state (user_id, building_key, animal_count, buffer_qty, last_update_ts, total_collected) VALUES (?, ?, 0, 0, ?, 0)",
            (user_id, building_key, time.time()),
        )
    conn.commit()
    conn.close()
    return True, "خریداری شد."


def upgrade_building(user_id: int, building_key: str):
    info = ALL_BUILDINGS[building_key]
    owned = get_owned_buildings(user_id)
    if building_key not in owned:
        return False, "این ساختمون رو نداری."
    level = owned[building_key]
    cost = int(info["buy_cost"] * level * BUILDING_UPGRADE_RATIO)
    player = get_player(user_id)
    if player["coins"] < cost:
        return False, f"سکه کافی نداری. هزینه ارتقا: {cost}"
    conn = db()
    c = conn.cursor()
    c.execute("UPDATE players SET coins = coins - ? WHERE user_id=?", (cost, user_id))
    c.execute("UPDATE owned_buildings SET level = level + 1 WHERE user_id=? AND building_key=?", (user_id, building_key))
    conn.commit()
    conn.close()
    return True, f"ارتقا به سطح {level + 1} انجام شد."


def get_upgrade_cost(user_id: int, building_key: str) -> int:
    owned = get_owned_buildings(user_id)
    level = owned.get(building_key, 1)
    info = ALL_BUILDINGS[building_key]
    return int(info["buy_cost"] * level * BUILDING_UPGRADE_RATIO)


def livestock_caps(building_key: str, level: int):
    info = LIVESTOCK_BUILDINGS[building_key]
    max_animals = info["base_max_animals"] + LEVEL_ANIMAL_BONUS * (level - 1)
    buffer_cap = info["base_buffer_cap"] + LEVEL_BUFFER_BONUS * (level - 1)
    rate_mult = 1 + LEVEL_RATE_BONUS * (level - 1)
    return max_animals, buffer_cap, rate_mult


def sync_livestock(user_id: int, building_key: str):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT * FROM livestock_state WHERE user_id=? AND building_key=?", (user_id, building_key))
    state = c.fetchone()
    if not state:
        conn.close()
        return
    owned = get_owned_buildings(user_id)
    level = owned.get(building_key, 1)
    info = LIVESTOCK_BUILDINGS[building_key]
    _, buffer_cap, rate_mult = livestock_caps(building_key, level)
    now = time.time()
    elapsed_hours = max(0, now - state["last_update_ts"]) / 3600
    produced = state["animal_count"] * info["rate_per_animal_hour"] * rate_mult * elapsed_hours
    new_buffer = min(buffer_cap, state["buffer_qty"] + produced)
    c.execute(
        "UPDATE livestock_state SET buffer_qty=?, last_update_ts=? WHERE user_id=? AND building_key=?",
        (new_buffer, now, user_id, building_key),
    )
    conn.commit()
    conn.close()


def get_livestock_state(user_id: int, building_key: str):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT * FROM livestock_state WHERE user_id=? AND building_key=?", (user_id, building_key))
    row = c.fetchone()
    conn.close()
    return row


def buy_animal(user_id: int, building_key: str):
    sync_livestock(user_id, building_key)
    info = LIVESTOCK_BUILDINGS[building_key]
    owned = get_owned_buildings(user_id)
    if building_key not in owned:
        return False, "اول باید خود ساختمون رو بخری."
    level = owned[building_key]
    max_animals, _, _ = livestock_caps(building_key, level)
    state = get_livestock_state(user_id, building_key)
    if state["animal_count"] >= max_animals:
        return False, f"ظرفیت پر شده (حداکثر {max_animals} تا)."
    player = get_player(user_id)
    if player["coins"] < info["animal_cost"]:
        return False, f"سکه کافی نداری. هزینه هر {info['animal_key']}: {info['animal_cost']}"
    conn = db()
    c = conn.cursor()
    c.execute("UPDATE players SET coins = coins - ? WHERE user_id=?", (info["animal_cost"], user_id))
    c.execute("UPDATE livestock_state SET animal_count = animal_count + 1 WHERE user_id=? AND building_key=?", (user_id, building_key))
    conn.commit()
    conn.close()
    return True, f"یه {info['animal_key']} اضافه شد."


def collect_livestock(user_id: int, building_key: str) -> int:
    sync_livestock(user_id, building_key)
    info = LIVESTOCK_BUILDINGS[building_key]
    state = get_livestock_state(user_id, building_key)
    amount = int(state["buffer_qty"])
    if amount <= 0:
        return 0
    added = add_to_inventory(user_id, info["output"], amount)
    conn = db()
    c = conn.cursor()
    c.execute(
        "UPDATE livestock_state SET buffer_qty = buffer_qty - ?, total_collected = total_collected + ? WHERE user_id=? AND building_key=?",
        (added, added, user_id, building_key),
    )
    conn.commit()
    conn.close()
    return added


def collect_all_livestock(user_id: int):
    owned = get_owned_buildings(user_id)
    results = {}
    for key in LIVESTOCK_BUILDINGS:
        if key in owned:
            added = collect_livestock(user_id, key)
            if added > 0:
                results[key] = added
    return results


def build_prod_menu_keyboard():
    buttons = [
        [InlineKeyboardButton("🥚 دامداری", callback_data="catlist:livestock")],
        [InlineKeyboardButton("🌱 مزرعه", callback_data="catlist:farm")],
        [InlineKeyboardButton("🏭 کارخونه", callback_data="catlist:factory")],
    ]
    return InlineKeyboardMarkup(buttons)


def build_category_list(user_id: int, kind: str):
    registry = CAT_REGISTRY[kind]
    owned = get_owned_buildings(user_id)
    owned_in_cat = [k for k in registry if k in owned]
    title = f"{CAT_EMOJI[kind]}—{CAT_TITLE[kind]} من—{CAT_EMOJI[kind]}"
    lines = [title, ""]
    buttons = []
    if not owned_in_cat:
        lines.append(f"هنوز هیچ {CAT_TITLE[kind]}‌ای نخریدی.")
    else:
        for key in owned_in_cat:
            info = registry[key]
            level = owned[key]
            lines.append(f"{info['emoji']} {building_label(key)} (سطح {level})")
            buttons.append([InlineKeyboardButton(f"{info['emoji']} {building_label(key)}", callback_data=f"bld:{key}")])
    if kind == "livestock" and owned_in_cat:
        buttons.append([InlineKeyboardButton("📥 جمع‌آوری همه", callback_data="collectall:livestock")])
    buttons.append([InlineKeyboardButton(f"🛒 خرید {CAT_TITLE[kind]} جدید", callback_data=f"shopcat:{kind}")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="prodmenu")])
    return "\n".join(lines), InlineKeyboardMarkup(buttons)


def build_livestock_building_panel(user_id: int, key: str):
    sync_livestock(user_id, key)
    info = LIVESTOCK_BUILDINGS[key]
    owned = get_owned_buildings(user_id)
    level = owned[key]
    max_animals, buffer_cap, rate_mult = livestock_caps(key, level)
    state = get_livestock_state(user_id, key)
    rate_per_hour = state["animal_count"] * info["rate_per_animal_hour"] * rate_mult
    upgrade_cost = get_upgrade_cost(user_id, key)
    lines = [
        f"{info['emoji']}—دامداری: {info['animal_key']}—{info['emoji']}",
        "",
        f"سطح: {level}",
        f"{info['emoji']} تعداد {info['animal_key']}: {state['animal_count']}/{max_animals}",
        f"{info['output_emoji']} میزان تولید: {rate_per_hour:.2f} {building_label(info['output'])} در ساعت",
        f"ظرفیت بافر: {int(state['buffer_qty'])}/{buffer_cap}",
        "",
        f"محصولات جمع‌آوری‌شده تا کنون: +{state['total_collected']} عدد {building_label(info['output'])}",
    ]
    buttons = [
        [InlineKeyboardButton("📥 جمع‌آوری", callback_data=f"livecollect:{key}")],
        [InlineKeyboardButton(f"➕ اضافه کردن {info['animal_key']} ({info['animal_cost']} سکه)", callback_data=f"buyanimal:{key}")],
        [InlineKeyboardButton(f"✨ ارتقای دامداری ({upgrade_cost} سکه)", callback_data=f"upgrade:{key}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="catlist:livestock")],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(buttons)


def build_farm_building_panel(user_id: int, key: str):
    info = FARM_BUILDINGS[key]
    owned = get_owned_buildings(user_id)
    level = owned[key]
    upgrade_cost = get_upgrade_cost(user_id, key)
    conn = db()
    c = conn.cursor()
    c.execute("SELECT * FROM farm_jobs WHERE user_id=? AND building_key=? AND collected=0", (user_id, key))
    job = c.fetchone()
    conn.close()
    now = time.time()
    lines = [f"{info['emoji']}—مزرعه: {info['crop']}—{info['emoji']}", "", f"سطح: {level}"]
    buttons = []
    if job:
        left = job["ready_at"] - now
        if left <= 0:
            lines.append(f"✅ آماده برداشت! ({info['yield_qty']} {info['crop']})")
            buttons.append([InlineKeyboardButton("📥 برداشت", callback_data=f"farmharvest:{job['id']}")])
        else:
            lines.append(f"⏰ زمان باقی‌مونده: {fmt_countdown(left)}")
    else:
        lines.append(f"هزینه کاشت: {info['plant_cost']} سکه | زمان: {info['plant_seconds']//60} دقیقه")
        buttons.append([InlineKeyboardButton(f"🌱 کاشت ({info['plant_cost']} سکه)", callback_data=f"farmstart:{key}")])
    buttons.append([InlineKeyboardButton(f"✨ ارتقا ({upgrade_cost} سکه)", callback_data=f"upgrade:{key}")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="catlist:farm")])
    return "\n".join(lines), InlineKeyboardMarkup(buttons)


def build_factory_building_panel(user_id: int, key: str):
    info = FACTORY_BUILDINGS[key]
    owned = get_owned_buildings(user_id)
    level = owned[key]
    upgrade_cost = get_upgrade_cost(user_id, key)
    inv = get_inventory(user_id)
    conn = db()
    c = conn.cursor()
    c.execute("SELECT * FROM factory_jobs WHERE user_id=? AND building_key=? AND collected=0", (user_id, key))
    job = c.fetchone()
    conn.close()
    now = time.time()
    lines = [f"{info['emoji']}—کارخونه: {building_label(info['output'])}—{info['emoji']}", "", f"سطح: {level}"]
    buttons = []
    if job:
        left = job["ready_at"] - now
        if left <= 0:
            lines.append(f"✅ آماده برداشت! ({info['output_qty']} {info['output']})")
            buttons.append([InlineKeyboardButton("📥 برداشت", callback_data=f"factharvest:{job['id']}")])
        else:
            lines.append(f"⏰ زمان باقی‌مونده: {fmt_countdown(left)}")
    else:
        have = inv.get(info["input"], 0)
        lines.append(f"نیاز: {info['input_qty']} {info['input']} (داری: {have})")
        buttons.append([InlineKeyboardButton("🏭 تولید", callback_data=f"factstart:{key}")])
    buttons.append([InlineKeyboardButton(f"✨ ارتقا ({upgrade_cost} سکه)", callback_data=f"upgrade:{key}")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="catlist:factory")])
    return "\n".join(lines), InlineKeyboardMarkup(buttons)


def build_building_panel(user_id: int, key: str):
    kind = ALL_BUILDINGS[key]["kind"]
    if kind == "livestock":
        return build_livestock_building_panel(user_id, key)
    if kind == "farm":
        return build_farm_building_panel(user_id, key)
    return build_factory_building_panel(user_id, key)


def build_inventory_text(user_id: int):
    inv = get_inventory(user_id)
    player = get_player(user_id)
    used = sum(inv.values())
    lines = [f"📦 انباری ({used}/{player['storage_capacity']})", ""]
    if not inv or used == 0:
        lines.append("انبارت خالیه.")
    for key, qty in inv.items():
        if qty <= 0:
            continue
        emoji = ITEM_EMOJI.get(key, "📦")
        lines.append(f"{emoji} {building_label(key)}: {qty}")
    lines.append(f"\n💰 سکه: {player['coins']}")
    return "\n".join(lines)


def build_shop_root_keyboard():
    buttons = [
        [InlineKeyboardButton("🥚 خرید دامداری", callback_data="shopcat:livestock")],
        [InlineKeyboardButton("🌱 خرید زمین مزرعه", callback_data="shopcat:farm")],
        [InlineKeyboardButton("🏭 خرید کارخونه پردازش", callback_data="shopcat:factory")],
        [InlineKeyboardButton("🛍 خرید مستقیم آیتم", callback_data="shop:buy_menu")],
        [InlineKeyboardButton("💰 فروش سریع همه چی", callback_data="shop:sellall")],
        [InlineKeyboardButton("📦 ارتقای انبار", callback_data="shop:upgrade_storage")],
    ]
    return InlineKeyboardMarkup(buttons)


def build_shop_category_view(user_id: int, kind: str):
    registry = CAT_REGISTRY[kind]
    owned = get_owned_buildings(user_id)
    lines = [f"🛒 خرید {CAT_TITLE[kind]}", ""]
    buttons = []
    for key, info in registry.items():
        label = building_label(key)
        if key in owned:
            lines.append(f"✅ {info['emoji']} {label} — قبلاً خریدی")
        else:
            lines.append(f"{info['emoji']} {label} — هزینه {info['buy_cost']} سکه")
            buttons.append([InlineKeyboardButton(f"خرید {label}", callback_data=f"buybuild:{key}")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت به شاپ", callback_data="shop:back")])
    return "\n".join(lines), InlineKeyboardMarkup(buttons)


def build_buy_menu_keyboard():
    items = list(BUY_CATALOG.items())
    rows = []
    for i in range(0, len(items), 2):
        row = []
        for key, info in items[i:i + 2]:
            label = building_label(key)
            buy_price, _ = get_price(key)
            row.append(InlineKeyboardButton(f"{info['emoji']} {label} ({buy_price})", callback_data=f"buyitem:{key}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("🔙 بازگشت به شاپ", callback_data="shop:back")])
    return InlineKeyboardMarkup(rows)


def generate_serial_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = "S2W-" + "".join(secrets.choice(alphabet) for _ in range(6))
        conn = db()
        c = conn.cursor()
        c.execute("SELECT code FROM serials WHERE code=?", (code,))
        exists = c.fetchone()
        conn.close()
        if not exists:
            return code


def create_serial(user_id: int, amount: int):
    code = generate_serial_code()
    conn = db()
    c = conn.cursor()
    c.execute("INSERT INTO serials (code, amount, created_by, created_at) VALUES (?, ?, ?, ?)", (code, amount, user_id, time.time()))
    conn.commit()
    conn.close()
    return code


def redeem_serial(code: str, user_id: int):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT * FROM serials WHERE code=?", (code,))
    row = c.fetchone()
    if not row:
        conn.close()
        return None, "کد پیدا نشد."
    if row["redeemed_by"] is not None:
        conn.close()
        return None, "این کد قبلاً استفاده شده."
    c.execute("UPDATE serials SET redeemed_by=? WHERE code=?", (user_id, code))
    c.execute("UPDATE players SET coins = coins + ? WHERE user_id=?", (row["amount"], user_id))
    conn.commit()
    conn.close()
    return row["amount"], None


def get_daily_reference_cost(user_id: int) -> float:
    owned = get_owned_buildings(user_id)
    if not owned:
        return DAILY_BASE_REFERENCE
    costs = [ALL_BUILDINGS[k]["buy_cost"] * lvl * BUILDING_UPGRADE_RATIO for k, lvl in owned.items()]
    return sum(costs) / len(costs)


async def daily_gift_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_player(user.id, user.username or user.first_name)
    player = get_player(user.id)
    now = time.time()
    remaining = DAILY_COOLDOWN_SECONDS - (now - player["last_daily_ts"])
    if remaining > 0:
        await update.effective_message.reply_text(f"⏰ هنوز زوده! {fmt_countdown(remaining)} دیگه صبر کن.")
        return
    reference = get_daily_reference_cost(user.id)
    fraction = random.triangular(0.01, 1.0, 0.2)
    reward = max(10, round(reference * fraction))
    conn = db()
    c = conn.cursor()
    c.execute("UPDATE players SET coins = coins + ?, last_daily_ts = ? WHERE user_id=?", (reward, now, user.id))
    conn.commit()
    conn.close()
    await update.effective_message.reply_text(f"🎁 هدیه روزانه‌ت: {reward} سکه!\nفردا دوباره سر بزن.")


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_player(user.id, user.username or user.first_name)
    guide = (
        f"🌱 به Seed2Wealth خوش اومدی، {user.first_name}!\n\n"
        f"شما {START_COINS} سکه و {START_FLOUR} واحد آرد اولیه گرفتی.\n\n"
        "📖 قوانین بازی:\n"
        "🐔 دامداری — اول ساختمون رو از شاپ بخر، بعد جدا حیوان بخر و اضافه کن. تولید مداومه، باید مرتب جمع‌آوری کنی.\n"
        "🌾 مزرعه — اول زمین رو از شاپ بخر. برای کاشت هر بار مستقیم سکه میدی؛ بعد از یه مدت برداشت می‌کنی و ۳-۴ برابر سود می‌فروشی.\n"
        "🏭 کارخونه پردازش — هر محصول فرعی کارخونه اختصاصی خودشو لازم داره؛ ورودیش فقط از تولید خودته.\n"
        "📦 انباری — ظرفیت کلی محدود داره (قابل ارتقا).\n"
        "🛍 شاپ — خرید مستقیم چندتا آیتم تزئینی، فروش سریع، ارتقای انبار.\n"
        "🎁 سریال — کد هدیه بساز و به دوستات بده؛ اونا با فرستادن کد تو پیوی ربات سکه می‌گیرن.\n"
        "🎉 هدیه روزانه — هر ۲۴ ساعت یه‌بار، یه جایزه شانسی می‌گیری (بر اساس ثروتت).\n\n"
        "⚠️ هر ساختمون فقط یه‌بار قابل خریده.\n\n"
        "دستورات: تولید | انباری | شاپ | قیمت <آیتم> | سریال <مقدار> | هدیه روزانه"
    )
    await update.effective_message.reply_text(guide)


async def production_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_player(user.id, user.username or user.first_name)
    await update.effective_message.reply_text("🏗 تولید — کدوم بخش؟", reply_markup=build_prod_menu_keyboard())


async def inventory_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_player(user.id, user.username or user.first_name)
    await update.effective_message.reply_text(build_inventory_text(user.id))


async def shop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_player(user.id, user.username or user.first_name)
    await update.effective_message.reply_text("🛍 شاپ — چی می‌خوای بخری؟", reply_markup=build_shop_root_keyboard())


async def price_query_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE, item_name: str):
    item_key = item_name.strip().replace(" ", "_")
    if item_key not in ALL_PRICED_ITEMS:
        await update.effective_message.reply_text("همچین آیتمی نداریم.")
        return
    buy_price, sell_price = get_price(item_key)
    await update.effective_message.reply_text(
        f"{ITEM_EMOJI.get(item_key,'📦')} {item_name}\nخرید: {buy_price} سکه\nفروش: {sell_price} سکه"
    )


async def price_set_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE, args: str):
    user = update.effective_user
    if not is_admin(user.id):
        await update.effective_message.reply_text("فقط ادمین می‌تونه قیمت‌ها رو تغییر بده.")
        return
    parts = args.split()
    if len(parts) < 3:
        await update.effective_message.reply_text("فرمت درست: تنظیم قیمت <آیتم> <خرید> <فروش>\nمثال: تنظیم قیمت نان 10 20")
        return
    buy_str, sell_str = parts[-2], parts[-1]
    item_name = " ".join(parts[:-2])
    item_key = item_name.strip().replace(" ", "_")
    if item_key not in ALL_PRICED_ITEMS:
        await update.effective_message.reply_text("همچین آیتمی نداریم.")
        return
    if not (buy_str.isdigit() and sell_str.isdigit()):
        await update.effective_message.reply_text("قیمت‌ها باید عدد باشن.")
        return
    set_price(item_key, int(buy_str), int(sell_str))
    await update.effective_message.reply_text(f"✅ قیمت {item_name} آپدیت شد. خرید: {buy_str} | فروش: {sell_str}")


async def serial_create_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE, amount_str: str):
    user = update.effective_user
    ensure_player(user.id, user.username or user.first_name)
    if not amount_str.isdigit() or int(amount_str) <= 0:
        await update.effective_message.reply_text("فرمت درست: سریال <مقدار>\nمثال: سریال 500")
        return
    amount = int(amount_str)
    admin = is_admin(user.id)
    if not admin:
        player = get_player(user.id)
        if player["coins"] < amount:
            await update.effective_message.reply_text("سکه کافی برای ساخت این سریال نداری.")
            return
        conn = db()
        c = conn.cursor()
        c.execute("UPDATE players SET coins = coins - ? WHERE user_id=?", (amount, user.id))
        conn.commit()
        conn.close()
    code = create_serial(user.id, amount)
    note = " (بدون کسر موجودی، چون ادمینی)" if admin else ""
    await update.effective_message.reply_text(
        f"🎁 سریال ساخته شد{note}:\n`{code}`\nارزش: {amount} سکه\n\n"
        "هرکسی این کد رو تو پیوی ربات بفرسته، این مقدار سکه بهش اضافه میشه.",
        parse_mode="Markdown",
    )


async def serial_redeem_private(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str):
    user = update.effective_user
    ensure_player(user.id, user.username or user.first_name)
    amount, error = redeem_serial(code, user.id)
    if error:
        await update.effective_message.reply_text(f"❌ {error}")
        return
    await update.effective_message.reply_text(f"✅ کد فعال شد! {amount} سکه به حسابت اضافه شد.")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.effective_message.text or "").strip()
    chat_type = update.effective_chat.type

    if text == "تولید":
        await production_cmd(update, context)
        return
    if text == "انباری":
        await inventory_cmd(update, context)
        return
    if text == "شاپ":
        await shop_cmd(update, context)
        return
    if text in ("هدیه روزانه", "هدیه‌روزانه"):
        await daily_gift_cmd(update, context)
        return
    if text.startswith("تنظیم قیمت"):
        await price_set_cmd(update, context, text[len("تنظیم قیمت"):].strip())
        return
    if text.startswith("قیمت"):
        await price_query_cmd(update, context, text[len("قیمت"):].strip())
        return
    if text.startswith("سریال"):
        await serial_create_cmd(update, context, text[len("سریال"):].strip())
        return

    if chat_type == "private" and text.upper().startswith("S2W-"):
        await serial_redeem_private(update, context, text.upper().strip())
        return


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_answer(query)
    user = query.from_user
    ensure_player(user.id, user.username or user.first_name)
    data = query.data

    if data == "prodmenu":
        await query.edit_message_text("🏗 تولید — کدوم بخش؟", reply_markup=build_prod_menu_keyboard())
        return

    if data.startswith("catlist:"):
        kind = data.split(":", 1)[1]
        text, kb = build_category_list(user.id, kind)
        await query.edit_message_text(text, reply_markup=kb)
        return

    if data.startswith("bld:"):
        key = data.split(":", 1)[1]
        text, kb = build_building_panel(user.id, key)
        await query.edit_message_text(text, reply_markup=kb)
        return

    if data == "collectall:livestock":
        results = collect_all_livestock(user.id)
        text, kb = build_category_list(user.id, "livestock")
        if results:
            note_lines = [f"{LIVESTOCK_BUILDINGS[k]['output_emoji']} {v} {building_label(LIVESTOCK_BUILDINGS[k]['output'])}" for k, v in results.items()]
            note = "\n\n✅ جمع‌آوری شد:\n" + "\n".join(note_lines)
        else:
            note = "\n\nچیزی برای جمع‌آوری نبود."
        await query.edit_message_text(text + note, reply_markup=kb)
        return

    if data == "shop:back":
        await query.edit_message_text("🛍 شاپ — چی می‌خوای بخری؟", reply_markup=build_shop_root_keyboard())
        return

    if data.startswith("shopcat:"):
        kind = data.split(":", 1)[1]
        text, kb = build_shop_category_view(user.id, kind)
        await query.edit_message_text(text, reply_markup=kb)
        return

    if data.startswith("buybuild:"):
        key = data.split(":", 1)[1]
        ok, msg = buy_building(user.id, key)
        kind = ALL_BUILDINGS[key]["kind"]
        text, kb = build_shop_category_view(user.id, kind)
        if not ok:
            await query.answer(msg, show_alert=True)
            return
        await query.edit_message_text(text + f"\n\n✅ {msg}", reply_markup=kb)
        return

    if data.startswith("upgrade:"):
        key = data.split(":", 1)[1]
        ok, msg = upgrade_building(user.id, key)
        if not ok:
            await query.answer(msg, show_alert=True)
            return
        text, kb = build_building_panel(user.id, key)
        await query.edit_message_text(text + f"\n\n✅ {msg}", reply_markup=kb)
        return

    if data.startswith("buyanimal:"):
        key = data.split(":", 1)[1]
        ok, msg = buy_animal(user.id, key)
        if not ok:
            await query.answer(msg, show_alert=True)
            return
        text, kb = build_building_panel(user.id, key)
        await query.edit_message_text(text, reply_markup=kb)
        return

    if data.startswith("livecollect:"):
        key = data.split(":", 1)[1]
        added = collect_livestock(user.id, key)
        text, kb = build_building_panel(user.id, key)
        note = f"\n\n✅ {added} واحد جمع‌آوری شد." if added > 0 else "\n\nهنوز چیزی برای جمع‌آوری نیست."
        await query.edit_message_text(text + note, reply_markup=kb)
        return

    if data.startswith("farmstart:"):
        key = data.split(":", 1)[1]
        info = FARM_BUILDINGS[key]
        if not owns_building(user.id, key):
            await query.answer("اول باید این زمین رو بخری.", show_alert=True)
            return
        conn = db()
        c = conn.cursor()
        c.execute("SELECT id FROM farm_jobs WHERE user_id=? AND building_key=? AND collected=0", (user.id, key))
        if c.fetchone():
            conn.close()
            await query.answer("این مزرعه الان داره تولید می‌کنه.", show_alert=True)
            return
        player = get_player(user.id)
        if player["coins"] < info["plant_cost"]:
            conn.close()
            await query.answer(f"سکه کافی نداری. هزینه کاشت: {info['plant_cost']}", show_alert=True)
            return
        c.execute("UPDATE players SET coins = coins - ? WHERE user_id=?", (info["plant_cost"], user.id))
        c.execute(
            "INSERT INTO farm_jobs (user_id, building_key, ready_at, collected) VALUES (?, ?, ?, 0)",
            (user.id, key, time.time() + info["plant_seconds"]),
        )
        conn.commit()
        conn.close()
        text, kb = build_building_panel(user.id, key)
        await query.edit_message_text(text, reply_markup=kb)
        return

    if data.startswith("farmharvest:"):
        job_id = int(data.split(":", 1)[1])
        conn = db()
        c = conn.cursor()
        c.execute("SELECT * FROM farm_jobs WHERE id=? AND user_id=?", (job_id, user.id))
        job = c.fetchone()
        conn.close()
        if not job or job["collected"] or job["ready_at"] > time.time():
            await query.answer("هنوز آماده نیست یا قبلاً برداشت شده.", show_alert=True)
            return
        info = FARM_BUILDINGS[job["building_key"]]
        added = add_to_inventory(user.id, info["crop"], info["yield_qty"])
        conn = db()
        c = conn.cursor()
        c.execute("UPDATE farm_jobs SET collected=1 WHERE id=?", (job_id,))
        conn.commit()
        conn.close()
        text, kb = build_building_panel(user.id, job["building_key"])
        await query.edit_message_text(text + f"\n\n✅ {added} واحد {info['crop']} برداشت شد.", reply_markup=kb)
        return

    if data.startswith("factstart:"):
        key = data.split(":", 1)[1]
        info = FACTORY_BUILDINGS[key]
        if not owns_building(user.id, key):
            await query.answer("اول باید این کارخونه رو بخری.", show_alert=True)
            return
        conn = db()
        c = conn.cursor()
        c.execute("SELECT id FROM factory_jobs WHERE user_id=? AND building_key=? AND collected=0", (user.id, key))
        if c.fetchone():
            conn.close()
            await query.answer("این کارخونه الان داره تولید می‌کنه.", show_alert=True)
            return
        conn.close()
        if not remove_from_inventory(user.id, info["input"], info["input_qty"]):
            await query.answer(f"مواد اولیه کافی نداری ({info['input_qty']} {info['input']} لازمه).", show_alert=True)
            return
        conn = db()
        c = conn.cursor()
        c.execute(
            "INSERT INTO factory_jobs (user_id, building_key, ready_at, collected) VALUES (?, ?, ?, 0)",
            (user.id, key, time.time() + info["seconds"]),
        )
        conn.commit()
        conn.close()
        text, kb = build_building_panel(user.id, key)
        await query.edit_message_text(text, reply_markup=kb)
        return

    if data.startswith("factharvest:"):
        job_id = int(data.split(":", 1)[1])
        conn = db()
        c = conn.cursor()
        c.execute("SELECT * FROM factory_jobs WHERE id=? AND user_id=?", (job_id, user.id))
        job = c.fetchone()
        conn.close()
        if not job or job["collected"] or job["ready_at"] > time.time():
            await query.answer("هنوز آماده نیست یا قبلاً برداشت شده.", show_alert=True)
            return
        info = FACTORY_BUILDINGS[job["building_key"]]
        added = add_to_inventory(user.id, info["output"], info["output_qty"])
        conn = db()
        c = conn.cursor()
        c.execute("UPDATE factory_jobs SET collected=1 WHERE id=?", (job_id,))
        conn.commit()
        conn.close()
        text, kb = build_building_panel(user.id, job["building_key"])
        await query.edit_message_text(text + f"\n\n✅ {added} واحد {info['output']} برداشت شد.", reply_markup=kb)
        return

    if data == "shop:buy_menu":
        await query.edit_message_text("🛍 خرید مستقیم — کدومو می‌خوای؟ (هر تپ = ۱۰ واحد)", reply_markup=build_buy_menu_keyboard())
        return

    if data.startswith("buyitem:"):
        item_key = data.split(":", 1)[1]
        buy_price, _ = get_price(item_key)
        total_cost = buy_price * BUY_BATCH
        player = get_player(user.id)
        if player["coins"] < total_cost:
            await query.answer(f"سکه کافی نداری. هزینه {BUY_BATCH} واحد: {total_cost}", show_alert=True)
            return
        added = add_to_inventory(user.id, item_key, BUY_BATCH)
        if added <= 0:
            await query.answer("انبارت پره، جا نداری.", show_alert=True)
            return
        actual_cost = buy_price * added
        conn = db()
        c = conn.cursor()
        c.execute("UPDATE players SET coins = coins - ? WHERE user_id=?", (actual_cost, user.id))
        conn.commit()
        conn.close()
        await query.answer(f"✅ {added} واحد {building_label(item_key)} خریدی ({actual_cost} سکه).", show_alert=True)
        return

    if data == "shop:sellall":
        inv = get_inventory(user.id)
        total_coins = 0
        conn = db()
        c = conn.cursor()
        for item_key, qty in inv.items():
            if qty <= 0:
                continue
            _, sell_price = get_price(item_key)
            if sell_price <= 0:
                continue
            total_coins += qty * sell_price
            c.execute("UPDATE inventory SET quantity=0 WHERE user_id=? AND item_key=?", (user.id, item_key))
        c.execute("UPDATE players SET coins = coins + ? WHERE user_id=?", (total_coins, user.id))
        conn.commit()
        conn.close()
        await query.edit_message_text(f"✅ همه‌چی فروخته شد. {total_coins} سکه دریافت کردی.", reply_markup=build_shop_root_keyboard())
        return

    if data == "shop:upgrade_storage":
        player = get_player(user.id)
        if player["coins"] < STORAGE_UPGRADE_COST:
            await query.answer(f"سکه کافی نداری. هزینه: {STORAGE_UPGRADE_COST}", show_alert=True)
            return
        conn = db()
        c = conn.cursor()
        c.execute(
            "UPDATE players SET coins = coins - ?, storage_capacity = storage_capacity + ? WHERE user_id=?",
            (STORAGE_UPGRADE_COST, STORAGE_UPGRADE_AMOUNT, user.id),
        )
        conn.commit()
        conn.close()
        await query.edit_message_text(f"✅ ظرفیت انبار {STORAGE_UPGRADE_AMOUNT} واحد بیشتر شد.", reply_markup=build_shop_root_keyboard())
        return


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN تنظیم نشده. اونو تو Railway Variables بذار.")
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(button_handler))

    log.info("Farm bot starting (polling)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
