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

START_COINS = 10000
START_FLOUR = 50
START_STORAGE = 1000
STORAGE_UPGRADE_COST = 250
STORAGE_UPGRADE_AMOUNT = 1000
DAILY_COOLDOWN_SECONDS = 24 * 3600
DAILY_BASE_REFERENCE = 300
MAX_BATCH_HOURS = 40

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
    "مزرعه_گندم":      {"emoji": "🌾", "buy_cost": 9000, "crop": "گندم",      "plant_cost": 12, "plant_seconds": 900, "yield_qty": 50},
    "مزرعه_برنج":      {"emoji": "🍚", "buy_cost": 13000, "crop": "برنج",      "plant_cost": 15, "plant_seconds": 900, "yield_qty": 50},
    "مزرعه_نیشکر":     {"emoji": "🎋", "buy_cost": 15000, "crop": "نیشکر",     "plant_cost": 14, "plant_seconds": 900, "yield_qty": 50},
    "مزرعه_سیب_زمینی": {"emoji": "🥔", "buy_cost": 17000, "crop": "سیب_زمینی", "plant_cost": 13, "plant_seconds": 900, "yield_qty": 50},
}

FACTORY_BUILDINGS = {
    "کارخونه_خمیر":    {"emoji": "🥟", "buy_cost": 7000, "input": "ارد",      "input_qty": 20, "output": "خمیر",  "output_qty": 15, "seconds": 300},
    "کارخونه_نان":     {"emoji": "🍞", "buy_cost": 12000, "input": "خمیر",     "input_qty": 15, "output": "نان",   "output_qty": 15, "seconds": 300},
    "کارخونه_نیمرو":   {"emoji": "🍳", "buy_cost": 13000,  "input": "تخم_مرغ",  "input_qty": 10, "output": "نیمرو", "output_qty": 10, "seconds": 180},
    "کارخونه_نخ":      {"emoji": "🧵", "buy_cost": 15000, "input": "پشم",      "input_qty": 100, "output": "نخ",   "output_qty": 40, "seconds": 300},
    "کارخونه_پارچه":   {"emoji": "🧣", "buy_cost": 12000, "input": "نخ",       "input_qty": 40, "output": "پارچه", "output_qty": 40, "seconds": 300},
    "کارخونه_ماست":    {"emoji": "🥣", "buy_cost": 9000,  "input": "شیر",      "input_qty": 100, "output": "ماست", "output_qty": 40, "seconds": 300},
    "کارخونه_پنیر":    {"emoji": "🧀", "buy_cost": 11000, "input": "شیر",      "input_qty": 80, "output": "پنیر",  "output_qty": 30, "seconds": 350},
    "کارخونه_کیک":     {"emoji": "🎂", "buy_cost": 100000, "input": "شکر",      "input_qty": 30, "output": "کیک",   "output_qty": 10, "seconds": 400},
    "کارخونه_پیتزا":   {"emoji": "🍕", "buy_cost": 130000, "input": "پنیر",     "input_qty": 20, "output": "پیتزا", "output_qty": 10, "seconds": 400},
    "کارخونه_سوسیس":   {"emoji": "🌭", "buy_cost": 70000,  "input": "ارد",      "input_qty": 15, "output": "سوسیس", "output_qty": 10, "seconds": 200},
    "کارخونه_هات_داگ": {"emoji": "🌭", "buy_cost": 90000,  "input": "سوسیس",    "input_qty": 10, "output": "هات_داگ", "output_qty": 10, "seconds": 250},
    "کارخونه_فرنچ":    {"emoji": "🍟", "buy_cost": 80000,  "input": "سیب_زمینی", "input_qty": 30, "output": "فرنچ", "output_qty": 20, "seconds": 200},
    "کارخونه_لباس":    {"emoji": "👚", "buy_cost": 140000, "input": "پارچه",    "input_qty": 20, "output": "لباس",  "output_qty": 10, "seconds": 400},
}

BUILDING_UPGRADE_RATIO = 0.5
LEVEL_ANIMAL_BONUS = 50
LEVEL_BUFFER_BONUS = 500
LEVEL_RATE_BONUS = 0.10

BUY_CATALOG = {
    "ارد":  {"emoji": "⬜"},
    "شکر":  {"emoji": "⬜"},
}

DEFAULT_BUY_PRICES = {"ارد": 5, "شکر": 6}
DEFAULT_SELL_PRICES = {
    "گندم": 90, "برنج": 150, "نیشکر": 80, "سیب_زمینی"  5,
    "60:"تخم_مرغ": 50, "پشم": 70, "شیر":,
    "خمیر": 100, "نان": 110, "نخ": 100, "پارچه": 80, "ماست": 90, "نیمرو": 5,
    "پنیر": 330, "کیک": 2500, "پیتزا": 2200, "سوسیس": 800, "هات_داگ": 12,
    "فرنچ": 800, "لباس": 550, "ارد": 95, "شکر": 3,
}
ALL_PRICED_ITEMS = sorted(set(DEFAULT_BUY_PRICES) | set(DEFAULT_SELL_PRICES))

ITEM_EMOJI = {
    "گندم": "🌾", "برنج": "🍚", "نیشکر": "🎋", "سیب_زمینی": "🥔",
    "تخم_مرغ": "🥚", "شیر": "🥛", "پشم": "🧶",
    **{v["output"]: v["emoji"] for v in FACTORY_BUILDINGS.values()},
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

PENDING_ACTIONS = {}


def fnum(n) -> str:
    return f"{int(n):,}"


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
            user_id INTEGER PRIMARY KEY, username TEXT,
            coins INTEGER DEFAULT 500, storage_capacity INTEGER DEFAULT 1000,
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
            ready_at REAL, batch_qty INTEGER DEFAULT 1, collected INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS factory_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, building_key TEXT,
            ready_at REAL, batch_qty INTEGER DEFAULT 1, collected INTEGER DEFAULT 0
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
        return False, f"سکه کافی نداری. هزینه: {fnum(info['buy_cost'])}"
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
        return False, f"سکه کافی نداری. هزینه ارتقا: {fnum(cost)}"
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


def max_affordable_animals(user_id: int, building_key: str) -> int:
    sync_livestock(user_id, building_key)
    info = LIVESTOCK_BUILDINGS[building_key]
    owned = get_owned_buildings(user_id)
    level = owned.get(building_key, 1)
    max_animals, _, _ = livestock_caps(building_key, level)
    state = get_livestock_state(user_id, building_key)
    room = max(0, max_animals - state["animal_count"])
    player = get_player(user_id)
    max_afford = player["coins"] // info["animal_cost"] if info["animal_cost"] > 0 else 0
    return max(0, min(room, max_afford))


def execute_buy_animal(user_id: int, building_key: str, qty: int):
    if qty <= 0:
        return False, "تعداد نامعتبره."
    info = LIVESTOCK_BUILDINGS[building_key]
    max_qty = max_affordable_animals(user_id, building_key)
    qty = min(qty, max_qty)
    if qty <= 0:
        return False, "سکه کافی نداری یا ظرفیت پره."
    cost = info["animal_cost"] * qty
    conn = db()
    c = conn.cursor()
    c.execute("UPDATE players SET coins = coins - ? WHERE user_id=?", (cost, user_id))
    c.execute("UPDATE livestock_state SET animal_count = animal_count + ? WHERE user_id=? AND building_key=?", (qty, user_id, building_key))
    conn.commit()
    conn.close()
    return True, f"✅ {fnum(qty)} تا {info['animal_key']} اضافه شد ({fnum(cost)} سکه)."


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


def max_farm_batch(user_id: int, building_key: str) -> int:
    info = FARM_BUILDINGS[building_key]
    player = get_player(user_id)
    max_afford = player["coins"] // info["plant_cost"] if info["plant_cost"] > 0 else 0
    max_time_cap = int((MAX_BATCH_HOURS * 3600) // info["plant_seconds"])
    return max(0, min(max_afford, max_time_cap))


def execute_farm_plant(user_id: int, building_key: str, qty: int):
    if qty <= 0:
        return False, "تعداد نامعتبره."
    info = FARM_BUILDINGS[building_key]
    conn = db()
    c = conn.cursor()
    c.execute("SELECT id FROM farm_jobs WHERE user_id=? AND building_key=? AND collected=0", (user_id, building_key))
    if c.fetchone():
        conn.close()
        return False, "این مزرعه الان داره تولید می‌کنه."
    max_qty = max_farm_batch(user_id, building_key)
    qty = min(qty, max_qty)
    if qty <= 0:
        conn.close()
        return False, "سکه کافی نداری."
    cost = info["plant_cost"] * qty
    seconds = info["plant_seconds"] * qty
    c.execute("UPDATE players SET coins = coins - ? WHERE user_id=?", (cost, user_id))
    c.execute(
        "INSERT INTO farm_jobs (user_id, building_key, ready_at, batch_qty, collected) VALUES (?, ?, ?, ?, 0)",
        (user_id, building_key, time.time() + seconds, qty),
    )
    conn.commit()
    conn.close()
    return True, f"✅ کاشت {fnum(qty)} بار شروع شد ({fnum(cost)} سکه)."


def max_factory_batch(user_id: int, building_key: str) -> int:
    info = FACTORY_BUILDINGS[building_key]
    inv = get_inventory(user_id)
    have = inv.get(info["input"], 0)
    max_by_input = have // info["input_qty"] if info["input_qty"] > 0 else 0
    max_time_cap = int((MAX_BATCH_HOURS * 3600) // info["seconds"])
    return max(0, min(max_by_input, max_time_cap))


def execute_factory_start(user_id: int, building_key: str, qty: int):
    if qty <= 0:
        return False, "تعداد نامعتبره."
    info = FACTORY_BUILDINGS[building_key]
    conn = db()
    c = conn.cursor()
    c.execute("SELECT id FROM factory_jobs WHERE user_id=? AND building_key=? AND collected=0", (user_id, building_key))
    if c.fetchone():
        conn.close()
        return False, "این کارخونه الان داره تولید می‌کنه."
    conn.close()
    max_qty = max_factory_batch(user_id, building_key)
    qty = min(qty, max_qty)
    if qty <= 0:
        return False, "مواد اولیه کافی نداری."
    total_input = info["input_qty"] * qty
    if not remove_from_inventory(user_id, info["input"], total_input):
        return False, "مواد اولیه کافی نداری."
    seconds = info["seconds"] * qty
    conn = db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO factory_jobs (user_id, building_key, ready_at, batch_qty, collected) VALUES (?, ?, ?, ?, 0)",
        (user_id, building_key, time.time() + seconds, qty),
    )
    conn.commit()
    conn.close()
    return True, f"✅ تولید {fnum(qty)} بار شروع شد ({fnum(total_input)} {info['input']} مصرف شد)."


def execute_buy_item(user_id: int, item_key: str, qty: int):
    if qty <= 0:
        return False, "تعداد نامعتبره."
    buy_price, _ = get_price(item_key)
    player = get_player(user_id)
    max_afford = player["coins"] // buy_price if buy_price > 0 else 0
    room = max(0, player["storage_capacity"] - total_stored(user_id))
    qty = min(qty, max_afford, room)
    if qty <= 0:
        return False, "سکه کافی نداری یا انبارت پره."
    cost = buy_price * qty
    added = add_to_inventory(user_id, item_key, qty)
    conn = db()
    c = conn.cursor()
    c.execute("UPDATE players SET coins = coins - ? WHERE user_id=?", (cost, user_id))
    conn.commit()
    conn.close()
    return True, f"✅ {fnum(added)} واحد {building_label(item_key)} خریدی ({fnum(cost)} سکه)."


def execute_sell_item(user_id: int, item_key: str, qty: int):
    if qty <= 0:
        return False, "تعداد نامعتبره."
    inv = get_inventory(user_id)
    have = inv.get(item_key, 0)
    qty = min(qty, have)
    if qty <= 0:
        return False, "این آیتم رو نداری."
    _, sell_price = get_price(item_key)
    revenue = sell_price * qty
    remove_from_inventory(user_id, item_key, qty)
    conn = db()
    c = conn.cursor()
    c.execute("UPDATE players SET coins = coins + ? WHERE user_id=?", (revenue, user_id))
    conn.commit()
    conn.close()
    return True, f"✅ {fnum(qty)} واحد {building_label(item_key)} فروختی ({fnum(revenue)} سکه گرفتی)."


def quantity_keyboard(kind: str, key: str, back_cb: str):
    row = [InlineKeyboardButton(f"{p}%", callback_data=f"qty:{kind}:{key}:{p}") for p in (20, 50, 80, 100)]
    return InlineKeyboardMarkup([row, [InlineKeyboardButton("🔙 بازگشت", callback_data=back_cb)]])


def compute_max_for(kind: str, user_id: int, key: str) -> int:
    if kind == "buyitem":
        buy_price, _ = get_price(key)
        player = get_player(user_id)
        max_afford = player["coins"] // buy_price if buy_price > 0 else 0
        room = max(0, player["storage_capacity"] - total_stored(user_id))
        return max(0, min(max_afford, room))
    if kind == "sellitem":
        return get_inventory(user_id).get(key, 0)
    if kind == "buyanimal":
        return max_affordable_animals(user_id, key)
    if kind == "farmplant":
        return max_farm_batch(user_id, key)
    if kind == "factstart":
        return max_factory_batch(user_id, key)
    return 0


def execute_action(kind: str, user_id: int, key: str, qty: int):
    if kind == "buyitem":
        return execute_buy_item(user_id, key, qty)
    if kind == "sellitem":
        return execute_sell_item(user_id, key, qty)
    if kind == "buyanimal":
        return execute_buy_animal(user_id, key, qty)
    if kind == "farmplant":
        return execute_farm_plant(user_id, key, qty)
    if kind == "factstart":
        return execute_factory_start(user_id, key, qty)
    return False, "دستور نامعتبر."


async def show_quantity_prompt(query, user_id: int, kind: str, key: str, header: str, back_cb: str):
    max_qty = compute_max_for(kind, user_id, key)
    text = (
        f"{header}\n\n"
        f"حداکثر ممکن الان: {fnum(max_qty)}\n\n"
        "چند تا می‌خوای؟ روی همین پیام ریپلای کن و یه عدد بفرست، یا از درصدهای زیر انتخاب کن:"
    )
    kb = quantity_keyboard(kind, key, back_cb)
    await query.edit_message_text(text, reply_markup=kb)
    PENDING_ACTIONS[query.message.message_id] = {"user_id": user_id, "kind": kind, "key": key, "back_cb": back_cb}


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
    lines = [f"—————{CAT_EMOJI[kind]} {CAT_TITLE[kind]}—————", ""]
    buttons = []
    if not owned_in_cat:
        lines.append(f"هنوز هیچ {CAT_TITLE[kind]}‌ای نخریدی.")
    else:
        for key in owned_in_cat:
            info = registry[key]
            if kind == "livestock":
                sync_livestock(user_id, key)
                state = get_livestock_state(user_id, key)
                lines.append(f"{info['emoji']} {info['animal_key']} --> {fnum(state['buffer_qty'])} {building_label(info['output'])}")
            elif kind == "farm":
                conn = db()
                c = conn.cursor()
                c.execute("SELECT * FROM farm_jobs WHERE user_id=? AND building_key=? AND collected=0", (user_id, key))
                job = c.fetchone()
                conn.close()
                if job:
                    left = job["ready_at"] - time.time()
                    if left <= 0:
                        lines.append(f"✅ {info['emoji']} {info['crop']} آماده برداشت!")
                    else:
                        lines.append(f"⏰ {fmt_countdown(left)} <-- {info['emoji']} {info['crop']} {fnum(info['yield_qty']*job['batch_qty'])}")
                else:
                    lines.append(f"{info['emoji']} {info['crop']} — آماده کاشت")
            else:
                conn = db()
                c = conn.cursor()
                c.execute("SELECT * FROM factory_jobs WHERE user_id=? AND building_key=? AND collected=0", (user_id, key))
                job = c.fetchone()
                conn.close()
                if job:
                    left = job["ready_at"] - time.time()
                    if left <= 0:
                        lines.append(f"✅ {info['emoji']} {info['output']} آماده برداشت!")
                    else:
                        lines.append(f"⏰ {fmt_countdown(left)} <-- {info['emoji']} {building_label(info['output'])} {fnum(info['output_qty']*job['batch_qty'])}")
                else:
                    lines.append(f"{info['emoji']} {building_label(info['output'])} — آماده تولید")
            buttons.append([InlineKeyboardButton(f"{info['emoji']} {building_label(key)}", callback_data=f"bld:{key}")])

    lines.append("")
    lines.append(f"کدوم {CAT_TITLE[kind]}؟")

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
        f"دامداری {info['animal_key']} :",
        "",
        f"سطح : {level}",
        f"{info['emoji']} تعداد حیوانات : {fnum(state['animal_count'])} / {fnum(max_animals)}",
        f"{info['output_emoji']} میزان تولید : {rate_per_hour:.2f} {building_label(info['output'])} در ساعت",
        f"ظرفیت تولید : {fnum(buffer_cap)}",
        "",
        "محصولات جمع‌آوری‌شده تا کنون :",
        f"+ {fnum(state['total_collected'])} عدد {building_label(info['output'])}",
    ]
    buttons = [
        [InlineKeyboardButton("📥 جمع‌آوری", callback_data=f"livecollect:{key}")],
        [InlineKeyboardButton(f"➕ اضافه کردن {info['animal_key']}", callback_data=f"buyanimal_prompt:{key}")],
        [InlineKeyboardButton(f"✨ ارتقای دامداری ({fnum(upgrade_cost)} سکه)", callback_data=f"upgrade:{key}")],
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
    player = get_player(user_id)
    max_batch = max_farm_batch(user_id, key)
    lines = [f"{info['emoji']} مزرعه {info['crop']}", "", f"سطح : {level}", f"زمان ساخت (هر واحد) : {info['plant_seconds']} ثانیه"]
    buttons = []
    if job:
        left = job["ready_at"] - now
        total_yield = info["yield_qty"] * job["batch_qty"]
        if left <= 0:
            lines.append(f"\n✅ آماده برداشت! ({fnum(total_yield)} {info['crop']})")
            buttons.append([InlineKeyboardButton("📥 برداشت", callback_data=f"farmharvest:{job['id']}")])
        else:
            lines.append(f"\n⏰ زمان باقی‌مونده : {fmt_countdown(left)}")
            lines.append(f"در حال ساخت : {fnum(job['batch_qty'])} بار (مجموع {fnum(total_yield)} {info['crop']})")
    else:
        lines.append(f"\nموارد لازم برای هر بار ساخت:\n- سکه 💰 : {fnum(info['plant_cost'])} عدد (داری {fnum(player['coins'])})")
        lines.append(f"\n⏰ محدودیت ساخت : {MAX_BATCH_HOURS} ساعت (حداکثر {fnum(max_batch)} بار)")
        buttons.append([InlineKeyboardButton("🌱 کاشت", callback_data=f"farmplant_prompt:{key}")])
    buttons.append([InlineKeyboardButton(f"✨ ارتقا ({fnum(upgrade_cost)} سکه)", callback_data=f"upgrade:{key}")])
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
    max_batch = max_factory_batch(user_id, key)
    lines = [f"{info['emoji']} کارخونه {building_label(info['output'])}", "", f"سطح : {level}", f"زمان ساخت (هر واحد) : {info['seconds']} ثانیه"]
    buttons = []
    if job:
        left = job["ready_at"] - now
        total_yield = info["output_qty"] * job["batch_qty"]
        if left <= 0:
            lines.append(f"\n✅ آماده برداشت! ({fnum(total_yield)} {building_label(info['output'])})")
            buttons.append([InlineKeyboardButton("📥 برداشت", callback_data=f"factharvest:{job['id']}")])
        else:
            lines.append(f"\n⏰ زمان باقی‌مونده : {fmt_countdown(left)}")
            lines.append(f"در حال تولید : {fnum(job['batch_qty'])} بار (مجموع {fnum(total_yield)} {building_label(info['output'])})")
    else:
        have = inv.get(info["input"], 0)
        lines.append(f"\nموارد لازم برای هر بار تولید:\n- {info['input_qty']} عدد {building_label(info['input'])} (داری {fnum(have)})")
        lines.append(f"\n⏰ محدودیت ساخت : {MAX_BATCH_HOURS} ساعت (حداکثر {fnum(max_batch)} بار)")
        buttons.append([InlineKeyboardButton("🏭 تولید", callback_data=f"factstart_prompt:{key}")])
    buttons.append([InlineKeyboardButton(f"✨ ارتقا ({fnum(upgrade_cost)} سکه)", callback_data=f"upgrade:{key}")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="catlist:factory")])
    return "\n".join(lines), InlineKeyboardMarkup(buttons)


def build_building_panel(user_id: int, key: str):
    kind = ALL_BUILDINGS[key]["kind"]
    if kind == "livestock":
        return build_livestock_building_panel(user_id, key)
    if kind == "farm":
        return build_farm_building_panel(user_id, key)
    return build_factory_building_panel(user_id, key)


def build_inventory_text_and_keyboard(user_id: int):
    inv = get_inventory(user_id)
    player = get_player(user_id)
    used = sum(inv.values())
    lines = ["انباری کاربر :", "", f"ظرفیت : {fnum(used)}/{fnum(player['storage_capacity'])}", f"موجودی : {fnum(player['coins'])} 💰", "", "ایتم‌ها 📦:"]
    if not inv or used == 0:
        lines.append("انبارت خالیه.")
    for key, qty in inv.items():
        if qty <= 0:
            continue
        emoji = ITEM_EMOJI.get(key, "📦")
        lines.append(f"{building_label(key)} <- {emoji} {fnum(qty)} عدد")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✨ ارتقا انبار", callback_data="invupgrade")]])
    return "\n".join(lines), kb


def build_shop_root_keyboard():
    buttons = [
        [InlineKeyboardButton("🛒 خرید ایتم", callback_data="shop:buy_menu")],
        [InlineKeyboardButton("🏷 فروش ایتم", callback_data="shop:sell_menu")],
        [InlineKeyboardButton("🏭 خرید کارخونه", callback_data="shopcat:factory")],
        [InlineKeyboardButton("🌱 خرید مزرعه", callback_data="shopcat:farm"),
         InlineKeyboardButton("🥚 خرید دامداری", callback_data="shopcat:livestock")],
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
            lines.append(f"{info['emoji']} {label} — هزینه {fnum(info['buy_cost'])} سکه")
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
            row.append(InlineKeyboardButton(f"{info['emoji']} {label} ({buy_price})", callback_data=f"buyitem_prompt:{key}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("🔙 بازگشت به شاپ", callback_data="shop:back")])
    return InlineKeyboardMarkup(rows)


def build_sell_menu_keyboard(user_id: int):
    inv = get_inventory(user_id)
    owned_items = [(k, q) for k, q in inv.items() if q > 0]
    rows = []
    for i in range(0, len(owned_items), 2):
        row = []
        for key, qty in owned_items[i:i + 2]:
            emoji = ITEM_EMOJI.get(key, "📦")
            row.append(InlineKeyboardButton(f"{emoji} {building_label(key)} ({qty})", callback_data=f"sellitem_prompt:{key}"))
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
    await update.effective_message.reply_text(f"🎁 هدیه روزانه‌ت: {fnum(reward)} سکه!\nفردا دوباره سر بزن.")


GUIDE_TEXT = (
    "🌱 راهنمای Seed2Wealth\n\n"
    "این بات یه بازی اقتصادی/مزرعه‌ایه. هر کاربر کشاورز خودشه و باید با خرید ساختمون، تولید محصول، پردازش، و فروش، ثروتش رو زیاد کنه.\n\n"
    "📖 بخش‌ها:\n"
    "🐔 دامداری — اول ساختمون (مرغداری/گاوداری/گوسفندداری) رو از شاپ بخر، بعد حیوان اضافه کن. تولید مداومه؛ باید مرتب جمع‌آوری کنی.\n"
    "🌾 مزرعه — اول زمین رو از شاپ بخر. کاشت با سکه انجام میشه (میشه چندبار یک‌جا کاشت). محصول رو با ۳-۴ برابر سود می‌فروشی.\n"
    "🏭 کارخونه — هر محصول فرعی (نان، پنیر، کیک، پیتزا، سوسیس، هات‌داگ، فرنچ، لباس، نیمرو، پارچه، ماست...) کارخونه اختصاصی خودشو لازم داره.\n"
    "📦 انباری — ظرفیت کلی محدود داره (قابل ارتقا، دکمه‌ش زیر خود پیام انباری هست).\n"
    "🛍 شاپ — خرید مواد پایه (آرد/شکر)، فروش آیتم‌ها، خرید ساختمون‌های جدید، ارتقای انبار.\n"
    "🎁 سریال — کد هدیه بساز و به دوستات بده؛ اونا با فرستادن کد تو پیوی ربات سکه می‌گیرن.\n"
    "🎉 هدیه روزانه — هر ۲۴ ساعت یه‌بار، جایزه شانسی می‌گیری.\n\n"
    "💡 برای خرید/فروش/کاشت/اضافه‌کردن حیوان: بعد از انتخاب، یا روی پیام ریپلای کن و یه عدد بفرست، یا از دکمه‌های درصد (۲۰٪/۵۰٪/۸۰٪/۱۰۰٪) استفاده کن.\n\n"
    "⚠️ هر ساختمون فقط یه‌بار قابل خریده.\n\n"
    "دستورات: تولید | انباری | شاپ | قیمت <آیتم> | سریال <مقدار> | هدیه روزانه | راهنما"
)


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_player(user.id, user.username or user.first_name)
    await update.effective_message.reply_text(f"🌱 به Seed2Wealth خوش اومدی، {user.first_name}!\n\n" + GUIDE_TEXT)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(GUIDE_TEXT)


async def production_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_player(user.id, user.username or user.first_name)
    await update.effective_message.reply_text("🏗 تولید — کدوم بخش؟", reply_markup=build_prod_menu_keyboard())


async def inventory_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_player(user.id, user.username or user.first_name)
    text, kb = build_inventory_text_and_keyboard(user.id)
    await update.effective_message.reply_text(text, reply_markup=kb)


async def shop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_player(user.id, user.username or user.first_name)
    await update.effective_message.reply_text("برای خرید اومدی یا فروش؟", reply_markup=build_shop_root_keyboard())


async def price_query_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE, item_name: str):
    item_key = item_name.strip().replace(" ", "_")
    if item_key not in ALL_PRICED_ITEMS:
        await update.effective_message.reply_text("همچین آیتمی نداریم.")
        return
    buy_price, sell_price = get_price(item_key)
    await update.effective_message.reply_text(
        f"{ITEM_EMOJI.get(item_key,'📦')} {item_name}\nخرید: {fnum(buy_price)} سکه\nفروش: {fnum(sell_price)} سکه"
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
        f"🎁 سریال ساخته شد{note}:\n`{code}`\nارزش: {fnum(amount)} سکه\n\n"
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
    await update.effective_message.reply_text(f"✅ کد فعال شد! {fnum(amount)} سکه به حسابت اضافه شد.")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.effective_message.text or "").strip()
    chat_type = update.effective_chat.type
    user = update.effective_user

    reply_to = update.effective_message.reply_to_message
    if reply_to and reply_to.message_id in PENDING_ACTIONS and text.isdigit():
        pending = PENDING_ACTIONS[reply_to.message_id]
        if pending["user_id"] == user.id:
            ensure_player(user.id, user.username or user.first_name)
            qty = int(text)
            ok, msg = execute_action(pending["kind"], user.id, pending["key"], qty)
            await update.effective_message.reply_text(msg)
            del PENDING_ACTIONS[reply_to.message_id]
            return

    if text == "تولید":
        await production_cmd(update, context)
        return
    if text == "انباری":
        await inventory_cmd(update, context)
        return
    if text == "شاپ":
        await shop_cmd(update, context)
        return
    if text == "راهنما":
        await help_cmd(update, context)
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
            note_lines = [f"{LIVESTOCK_BUILDINGS[k]['emoji']} {fnum(v)} {building_label(LIVESTOCK_BUILDINGS[k]['output'])}" for k, v in results.items()]
            note = "\n\n✅ جمع‌آوری شد:\n" + "\n".join(note_lines)
        else:
            note = "\n\nچیزی برای جمع‌آوری نبود."
        await query.edit_message_text(text + note, reply_markup=kb)
        return

    if data == "invupgrade":
        player = get_player(user.id)
        if player["coins"] < STORAGE_UPGRADE_COST:
            await query.answer(f"سکه کافی نداری. هزینه: {fnum(STORAGE_UPGRADE_COST)}", show_alert=True)
            return
        conn = db()
        c = conn.cursor()
        c.execute(
            "UPDATE players SET coins = coins - ?, storage_capacity = storage_capacity + ? WHERE user_id=?",
            (STORAGE_UPGRADE_COST, STORAGE_UPGRADE_AMOUNT, user.id),
        )
        conn.commit()
        conn.close()
        text, kb = build_inventory_text_and_keyboard(user.id)
        await query.edit_message_text(text + f"\n\n✅ ظرفیت انبار {fnum(STORAGE_UPGRADE_AMOUNT)} واحد بیشتر شد.", reply_markup=kb)
        return

    if data == "shop:back":
        await query.edit_message_text("برای خرید اومدی یا فروش؟", reply_markup=build_shop_root_keyboard())
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

    if data.startswith("buyanimal_prompt:"):
        key = data.split(":", 1)[1]
        info = LIVESTOCK_BUILDINGS[key]
        await show_quantity_prompt(query, user.id, "buyanimal", key, f"➕ خرید {info['animal_key']} — هزینه هر واحد: {fnum(info['animal_cost'])} سکه", f"bld:{key}")
        return

    if data.startswith("farmplant_prompt:"):
        key = data.split(":", 1)[1]
        info = FARM_BUILDINGS[key]
        await show_quantity_prompt(query, user.id, "farmplant", key, f"🌱 کاشت {info['crop']} — هزینه هر واحد: {fnum(info['plant_cost'])} سکه", f"bld:{key}")
        return

    if data.startswith("factstart_prompt:"):
        key = data.split(":", 1)[1]
        info = FACTORY_BUILDINGS[key]
        await show_quantity_prompt(query, user.id, "factstart", key, f"🏭 تولید {building_label(info['output'])} — هر واحد نیاز به {info['input_qty']} {info['input']}", f"bld:{key}")
        return

    if data.startswith("buyitem_prompt:"):
        key = data.split(":", 1)[1]
        info = BUY_CATALOG[key]
        buy_price, _ = get_price(key)
        await show_quantity_prompt(query, user.id, "buyitem", key, f"{info['emoji']} خرید {building_label(key)} — قیمت هر واحد: {fnum(buy_price)} سکه", "shop:buy_menu")
        return

    if data.startswith("sellitem_prompt:"):
        key = data.split(":", 1)[1]
        _, sell_price = get_price(key)
        emoji = ITEM_EMOJI.get(key, "📦")
        await show_quantity_prompt(query, user.id, "sellitem", key, f"{emoji} فروش {building_label(key)} — قیمت هر واحد: {fnum(sell_price)} سکه", "shop:sell_menu")
        return

    if data.startswith("qty:"):
        _, kind, key, percent_str = data.split(":", 3)
        max_qty = compute_max_for(kind, user.id, key)
        qty = max(1, round(max_qty * int(percent_str) / 100)) if max_qty > 0 else 0
        ok, msg = execute_action(kind, user.id, key, qty)
        if not ok:
            await query.answer(msg, show_alert=True)
            return
        pending = PENDING_ACTIONS.pop(query.message.message_id, None)
        back_cb = pending["back_cb"] if pending else "prodmenu"
        if back_cb.startswith("bld:"):
            bkey = back_cb.split(":", 1)[1]
            text, kb = build_building_panel(user.id, bkey)
        elif back_cb == "shop:buy_menu":
            text, kb = "🛍 خرید مستقیم — کدومو می‌خوای؟", build_buy_menu_keyboard()
        elif back_cb == "shop:sell_menu":
            text, kb = "🏷 فروش ایتم — کدومو می‌خوای بفروشی؟", build_sell_menu_keyboard(user.id)
        else:
            text, kb = "🏗 تولید — کدوم بخش؟", build_prod_menu_keyboard()
        await query.edit_message_text(text + f"\n\n{msg}", reply_markup=kb)
        return

    if data.startswith("livecollect:"):
        key = data.split(":", 1)[1]
        added = collect_livestock(user.id, key)
        text, kb = build_building_panel(user.id, key)
        note = f"\n\n✅ {fnum(added)} واحد جمع‌آوری شد." if added > 0 else "\n\nهنوز چیزی برای جمع‌آوری نیست."
        await query.edit_message_text(text + note, reply_markup=kb)
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
        total_yield = info["yield_qty"] * job["batch_qty"]
        added = add_to_inventory(user.id, info["crop"], total_yield)
        conn = db()
        c = conn.cursor()
        c.execute("UPDATE farm_jobs SET collected=1 WHERE id=?", (job_id,))
        conn.commit()
        conn.close()
        text, kb = build_building_panel(user.id, job["building_key"])
        await query.edit_message_text(text + f"\n\n✅ {fnum(added)} واحد {info['crop']} برداشت شد.", reply_markup=kb)
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
        total_yield = info["output_qty"] * job["batch_qty"]
        added = add_to_inventory(user.id, info["output"], total_yield)
        conn = db()
        c = conn.cursor()
        c.execute("UPDATE factory_jobs SET collected=1 WHERE id=?", (job_id,))
        conn.commit()
        conn.close()
        text, kb = build_building_panel(user.id, job["building_key"])
        await query.edit_message_text(text + f"\n\n✅ {fnum(added)} واحد {info['output']} برداشت شد.", reply_markup=kb)
        return

    if data == "shop:buy_menu":
        await query.edit_message_text("🛍 خرید مستقیم — کدومو می‌خوای؟", reply_markup=build_buy_menu_keyboard())
        return

    if data == "shop:sell_menu":
        inv = get_inventory(user.id)
        if not any(q > 0 for q in inv.values()):
            await query.answer("انبارت خالیه.", show_alert=True)
            return
        await query.edit_message_text("🏷 فروش ایتم — کدومو می‌خوای بفروشی؟", reply_markup=build_sell_menu_keyboard(user.id))
        return

    if data == "shop:upgrade_storage":
        player = get_player(user.id)
        if player["coins"] < STORAGE_UPGRADE_COST:
            await query.answer(f"سکه کافی نداری. هزینه: {fnum(STORAGE_UPGRADE_COST)}", show_alert=True)
            return
        conn = db()
        c = conn.cursor()
        c.execute(
            "UPDATE players SET coins = coins - ?, storage_capacity = storage_capacity + ? WHERE user_id=?",
            (STORAGE_UPGRADE_COST, STORAGE_UPGRADE_AMOUNT, user.id),
        )
        conn.commit()
        conn.close()
        await query.edit_message_text(f"✅ ظرفیت انبار {fnum(STORAGE_UPGRADE_AMOUNT)} واحد بیشتر شد.", reply_markup=build_shop_root_keyboard())
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
