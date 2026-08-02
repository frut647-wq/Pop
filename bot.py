import os
import time
import logging
import sqlite3

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

BOT_TOKEN = os.environ.get("8831054190:AAGr2EcBY4OAAdWcIO9LO-QyZSqOfzyRurI", "")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "farm.db")

START_COINS = 1500
START_STORAGE = 2000

# کاتالوگ کامل آیتم‌های قابل خرید از شاپ (هر تپ = ۱۰ واحد)
BUY_CATALOG = {
    "نون":        {"emoji": "🥖", "buy": 10},
    "کیک":        {"emoji": "🎂", "buy": 40},
    "پیتزا":      {"emoji": "🍕", "buy": 35},
    "هات_داگ":    {"emoji": "🌭", "buy": 20},
    "سوسیس":      {"emoji": "🌭", "buy": 15},
    "فرنچ":       {"emoji": "🍟", "buy": 12},
    "پنیر":       {"emoji": "🧀", "buy": 18},
    "لباس":       {"emoji": "👚", "buy": 50},
    "خمیر":       {"emoji": "⚪", "buy": 8},
    "نیمرو":      {"emoji": "🍳", "buy": 8},
    "تخم_مرغ":    {"emoji": "🥚", "buy": 6},
    "شیر":        {"emoji": "🥛", "buy": 6},
    "پشم":        {"emoji": "🧶", "buy": 6},
    "ارد":        {"emoji": "⬜", "buy": 5},
    "شکر":        {"emoji": "⬜", "buy": 6},
    "گندم":       {"emoji": "🌾", "buy": 4},
    "سیب_زمینی":  {"emoji": "🥔", "buy": 4},
    "نیشکر":      {"emoji": "🎋", "buy": 4},
    "برنج":       {"emoji": "🍚", "buy": 4},
    "مرغ":        {"emoji": "🐔", "buy": 300},
    "گوسفند":     {"emoji": "🐑", "buy": 350},
    "گاو":        {"emoji": "🐄", "buy": 500},
}
BUY_BATCH = 10

# ------------------------------------------------------------------
# تعریف منابع مزرعه و دامداری (تولید دسته‌ای: بعد از X ثانیه Y واحد آماده میشه)
# seconds رو برای تست می‌تونی کم‌تر بذاری، الان رو مقیاس دقیقه‌ست
# ------------------------------------------------------------------
FARM_SLOTS = {
    "گندم":       {"emoji": "🌾", "yield": 960, "seconds": 900},
    "برنج":       {"emoji": "🍚", "yield": 480, "seconds": 900},
    "نیشکر":      {"emoji": "🎋", "yield": 720, "seconds": 900},
    "سیب_زمینی":  {"emoji": "🥔", "yield": 720, "seconds": 900},
}

LIVESTOCK_SLOTS = {
    "تخم_مرغ": {"emoji": "🥚", "yield": 404, "seconds": 700, "animal": "🐔 مرغ"},
    "پشم":     {"emoji": "🧶", "yield": 719, "seconds": 700, "animal": "🐑 گوسفند"},
    "شیر":     {"emoji": "🥛", "yield": 719, "seconds": 700, "animal": "🐄 گاو"},
}

ALL_PRODUCTION_SLOTS = {**FARM_SLOTS, **LIVESTOCK_SLOTS}

# ------------------------------------------------------------------
# زنجیره‌های تولید کارخونه (چند زنجیره مجزا)
# ------------------------------------------------------------------
FACTORY_RECIPES = {
    "خمیر":  {"emoji": "🥟", "input": "گندم",  "input_qty": 100, "output_qty": 40, "seconds": 300},
    "نان":   {"emoji": "🍞", "input": "خمیر",  "input_qty": 40,  "output_qty": 40, "seconds": 300},
    "نخ":    {"emoji": "🧵", "input": "پشم",   "input_qty": 100, "output_qty": 40, "seconds": 300},
    "پارچه": {"emoji": "🧣", "input": "نخ",    "input_qty": 40,  "output_qty": 40, "seconds": 300},
    "ماست":  {"emoji": "🥣", "input": "شیر",   "input_qty": 100, "output_qty": 40, "seconds": 300},
}

# قیمت فروش هر واحد (سکه) — فقط برای آیتم‌های قابل فروش تو شاپ
SELL_PRICES = {
    "گندم": 1, "برنج": 1, "نیشکر": 1, "سیب_زمینی": 1,
    "تخم_مرغ": 2, "پشم": 2, "شیر": 2,
    "خمیر": 3, "نان": 6, "نخ": 3, "پارچه": 6, "ماست": 5,
    "نون": 6, "کیک": 25, "پیتزا": 22, "هات_داگ": 12, "سوسیس": 9,
    "فرنچ": 7, "پنیر": 11, "لباس": 30, "نیمرو": 5, "ارد": 3, "شکر": 3,
    "مرغ": 150, "گوسفند": 175, "گاو": 250,
}

# هزینه ارتقای ساختمان‌ها (سطح فعلی -> هزینه ارتقا به سطح بعد)
UPGRADE_BASE_COST = 300
STORAGE_UPGRADE_COST = 250
STORAGE_UPGRADE_AMOUNT = 1000


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
            storage_capacity INTEGER DEFAULT 2000,
            farm_level INTEGER DEFAULT 1,
            livestock_level INTEGER DEFAULT 1,
            factory_level INTEGER DEFAULT 1
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            user_id INTEGER,
            item_key TEXT,
            quantity INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, item_key)
        )
    """)
    # هر اسلات تولید (مزرعه/دامداری) وضعیتش: کی شروع شده و کِی آماده میشه
    c.execute("""
        CREATE TABLE IF NOT EXISTS production_slots (
            user_id INTEGER,
            slot_key TEXT,
            ready_at REAL DEFAULT 0,
            running INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, slot_key)
        )
    """)
    # کارهای در حال انجام کارخونه
    c.execute("""
        CREATE TABLE IF NOT EXISTS factory_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            recipe_key TEXT,
            ready_at REAL,
            collected INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


def ensure_player(user_id: int, username: str):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM players WHERE user_id=?", (user_id,))
    if not c.fetchone():
        c.execute(
            "INSERT INTO players (user_id, username, coins, storage_capacity) VALUES (?, ?, ?, ?)",
            (user_id, username or str(user_id), START_COINS, START_STORAGE),
        )
        conn.commit()
    else:
        c.execute("UPDATE players SET username=? WHERE user_id=?", (username or str(user_id), user_id))
        conn.commit()
    conn.close()


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
    inv = get_inventory(user_id)
    return sum(inv.values())


def add_to_inventory(user_id: int, item_key: str, qty: int) -> int:
    """اضافه می‌کنه به انبار با توجه به ظرفیت؛ مقداری که واقعاً اضافه شد رو برمی‌گردونه"""
    if qty <= 0:
        return 0
    player = get_player(user_id)
    room = max(0, player["storage_capacity"] - total_stored(user_id))
    added = min(qty, room)
    if added <= 0:
        return 0
    conn = db()
    c = conn.cursor()
    c.execute("SELECT quantity FROM inventory WHERE user_id=? AND item_key=?", (user_id, item_key))
    row = c.fetchone()
    if row:
        c.execute(
            "UPDATE inventory SET quantity = quantity + ? WHERE user_id=? AND item_key=?",
            (added, user_id, item_key),
        )
    else:
        c.execute(
            "INSERT INTO inventory (user_id, item_key, quantity) VALUES (?, ?, ?)",
            (user_id, item_key, added),
        )
    conn.commit()
    conn.close()
    return added


def remove_from_inventory(user_id: int, item_key: str, qty: int) -> bool:
    inv = get_inventory(user_id)
    if inv.get(item_key, 0) < qty:
        return False
    conn = db()
    c = conn.cursor()
    c.execute(
        "UPDATE inventory SET quantity = quantity - ? WHERE user_id=? AND item_key=?",
        (qty, user_id, item_key),
    )
    conn.commit()
    conn.close()
    return True


def get_slot_state(user_id: int, slot_key: str):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT * FROM production_slots WHERE user_id=? AND slot_key=?", (user_id, slot_key))
    row = c.fetchone()
    conn.close()
    return row


def start_slot(user_id: int, slot_key: str, seconds: int):
    ready_at = time.time() + seconds
    conn = db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO production_slots (user_id, slot_key, ready_at, running)
        VALUES (?, ?, ?, 1)
        ON CONFLICT(user_id, slot_key) DO UPDATE SET ready_at=excluded.ready_at, running=1
    """, (user_id, slot_key, ready_at))
    conn.commit()
    conn.close()


def clear_slot(user_id: int, slot_key: str):
    conn = db()
    c = conn.cursor()
    c.execute("UPDATE production_slots SET running=0 WHERE user_id=? AND slot_key=?", (user_id, slot_key))
    conn.commit()
    conn.close()


def fmt_countdown(seconds_left: float) -> str:
    seconds_left = max(0, int(seconds_left))
    h = seconds_left // 3600
    m = (seconds_left % 3600) // 60
    s = seconds_left % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


async def safe_answer(query):
    try:
        await query.answer()
    except Exception:
        pass


# ------------------------------------------------------------------
# نمایش پنل تولید (مزرعه یا دامداری)
# ------------------------------------------------------------------
def build_production_text_and_keyboard(user_id: int, category: str):
    slots = FARM_SLOTS if category == "farm" else LIVESTOCK_SLOTS
    title = "🌱—مزرعه—🌱" if category == "farm" else "🥚—دامداری—🥚"
    lines = [title, ""]
    buttons = []
    now = time.time()
    for key, info in slots.items():
        state = get_slot_state(user_id, key)
        label = key.replace("_", " ")
        prefix = info.get("animal", "")
        if state and state["running"]:
            left = state["ready_at"] - now
            if left <= 0:
                lines.append(f"✅ {info['emoji']} {label} آماده‌ست! ({info['yield']} واحد)")
                buttons.append([InlineKeyboardButton(f"برداشت {label}", callback_data=f"harvest:{key}")])
            else:
                lines.append(f"⏰ {fmt_countdown(left)} <-- {info['emoji']} {label} {info['yield']}")
        else:
            extra = f"{prefix} " if prefix else ""
            lines.append(f"▶️ {extra}{info['emoji']} {label} — آماده شروع تولید")
            buttons.append([InlineKeyboardButton(f"شروع تولید {label}", callback_data=f"start:{key}")])

    buttons.append([
        InlineKeyboardButton("🏭 کارخونه", callback_data="menu:factory"),
        InlineKeyboardButton("🌱 مزرعه", callback_data="menu:farm"),
        InlineKeyboardButton("🥚 دامداری", callback_data="menu:livestock"),
    ])
    return "\n".join(lines), InlineKeyboardMarkup(buttons)


def build_factory_text_and_keyboard(user_id: int):
    lines = ["🏭—کارخونه—🏭", ""]
    buttons = []
    inv = get_inventory(user_id)

    conn = db()
    c = conn.cursor()
    c.execute("SELECT * FROM factory_jobs WHERE user_id=? AND collected=0", (user_id,))
    active_jobs = c.fetchall()
    conn.close()

    active_by_recipe = {j["recipe_key"]: j for j in active_jobs}
    now = time.time()

    for key, r in FACTORY_RECIPES.items():
        job = active_by_recipe.get(key)
        if job:
            left = job["ready_at"] - now
            if left <= 0:
                lines.append(f"✅ {r['emoji']} {key} آماده‌ست! ({r['output_qty']} واحد)")
                buttons.append([InlineKeyboardButton(f"برداشت {key}", callback_data=f"fcollect:{job['id']}")])
            else:
                lines.append(f"⏰ {fmt_countdown(left)} <-- {r['emoji']} {key} در حال تولید")
        else:
            have = inv.get(r["input"], 0)
            lines.append(
                f"{r['emoji']} {key}: نیاز به {r['input_qty']} {r['input']} (موجودی شما: {have})"
            )
            buttons.append([InlineKeyboardButton(f"تولید {key}", callback_data=f"fstart:{key}")])

    buttons.append([
        InlineKeyboardButton("🏭 کارخونه", callback_data="menu:factory"),
        InlineKeyboardButton("🌱 مزرعه", callback_data="menu:farm"),
        InlineKeyboardButton("🥚 دامداری", callback_data="menu:livestock"),
    ])
    return "\n".join(lines), InlineKeyboardMarkup(buttons)


def build_inventory_text(user_id: int):
    inv = get_inventory(user_id)
    player = get_player(user_id)
    used = sum(inv.values())
    lines = [f"📦 انباری ({used}/{player['storage_capacity']})", ""]
    if not inv:
        lines.append("انبارت خالیه.")
    for key, qty in inv.items():
        if qty <= 0:
            continue
        info = ALL_PRODUCTION_SLOTS.get(key) or FACTORY_RECIPES.get(key) or BUY_CATALOG.get(key)
        emoji = info["emoji"] if info else "📦"
        lines.append(f"{emoji} {key.replace('_', ' ')}: {qty}")
    lines.append(f"\n💰 سکه: {player['coins']}")
    return "\n".join(lines)


def build_shop_keyboard():
    buttons = [
        [InlineKeyboardButton("🛒 خرید ایتم", callback_data="shop:buy_menu")],
        [InlineKeyboardButton("💰 فروش سریع همه محصولات پردازش‌شده", callback_data="shop:sellall")],
        [InlineKeyboardButton("🏭 ارتقای کارخونه", callback_data="shop:upgrade_factory")],
        [InlineKeyboardButton("🌱 ارتقای مزرعه", callback_data="shop:upgrade_farm")],
        [InlineKeyboardButton("🥚 ارتقای دامداری", callback_data="shop:upgrade_livestock")],
        [InlineKeyboardButton("📦 ارتقای انبار", callback_data="shop:upgrade_storage")],
    ]
    return InlineKeyboardMarkup(buttons)


def build_buy_menu_keyboard():
    items = list(BUY_CATALOG.items())
    rows = []
    for i in range(0, len(items), 2):
        row = []
        for key, info in items[i:i + 2]:
            label = key.replace("_", " ")
            row.append(InlineKeyboardButton(f"{info['emoji']} {label}", callback_data=f"buy:{key}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("🔙 بازگشت به شاپ", callback_data="shop:back")])
    return InlineKeyboardMarkup(rows)


# ------------------------------------------------------------------
# دستورات
# ------------------------------------------------------------------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_player(user.id, user.username or user.first_name)
    await update.effective_message.reply_text(
        "🌱 به Seed2Wealth خوش اومدی!\n\n"
        f"شما در ابتدا {START_COINS} سکه دارید.\n"
        "دستورات:\n"
        "تولید - مزرعه و دامداری خودت رو مدیریت کن\n"
        "انباری - موجودی خودت رو ببین\n"
        "شاپ - خرید و فروش و ارتقا"
    )


async def production_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_player(user.id, user.username or user.first_name)
    text, kb = build_production_text_and_keyboard(user.id, "farm")
    # ترکیب مزرعه + دامداری تو یه پیام مثل تصویر نمونه
    farm_text, _ = build_production_text_and_keyboard(user.id, "farm")
    live_text, _ = build_production_text_and_keyboard(user.id, "livestock")
    combined = farm_text + "\n\n" + live_text + "\n\nکدوم قسمت؟"
    buttons = [
        [InlineKeyboardButton("🏭 کارخونه", callback_data="menu:factory")],
        [InlineKeyboardButton("🌱 مزرعه", callback_data="menu:farm"),
         InlineKeyboardButton("🥚 دامداری", callback_data="menu:livestock")],
    ]
    await update.effective_message.reply_text(combined, reply_markup=InlineKeyboardMarkup(buttons))


async def inventory_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_player(user.id, user.username or user.first_name)
    await update.effective_message.reply_text(build_inventory_text(user.id))


async def shop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_player(user.id, user.username or user.first_name)
    await update.effective_message.reply_text(
        "🛍 شاپ — برای خرید اومدی یا فروش؟", reply_markup=build_shop_keyboard()
    )


# ------------------------------------------------------------------
# دستورات متنی فارسی (بدون اسلش، مثل بازی نمونه)
# ------------------------------------------------------------------
TEXT_COMMANDS = {
    "تولید": production_cmd,
    "انباری": inventory_cmd,
    "شاپ": shop_cmd,
}


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.effective_message.text or "").strip()
    handler = TEXT_COMMANDS.get(text)
    if handler:
        await handler(update, context)


# ------------------------------------------------------------------
# دکمه‌ها
# ------------------------------------------------------------------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_answer(query)
    user = query.from_user
    ensure_player(user.id, user.username or user.first_name)
    data = query.data

    if data == "menu:farm":
        text, kb = build_production_text_and_keyboard(user.id, "farm")
        await query.edit_message_text(text, reply_markup=kb)
        return
    if data == "menu:livestock":
        text, kb = build_production_text_and_keyboard(user.id, "livestock")
        await query.edit_message_text(text, reply_markup=kb)
        return
    if data == "menu:factory":
        text, kb = build_factory_text_and_keyboard(user.id)
        await query.edit_message_text(text, reply_markup=kb)
        return

    if data.startswith("start:"):
        slot_key = data.split(":", 1)[1]
        info = ALL_PRODUCTION_SLOTS[slot_key]
        state = get_slot_state(user.id, slot_key)
        if state and state["running"]:
            await query.answer("این قبلاً شروع شده.", show_alert=True)
            return
        start_slot(user.id, slot_key, info["seconds"])
        category = "farm" if slot_key in FARM_SLOTS else "livestock"
        text, kb = build_production_text_and_keyboard(user.id, category)
        await query.edit_message_text(text, reply_markup=kb)
        return

    if data.startswith("harvest:"):
        slot_key = data.split(":", 1)[1]
        info = ALL_PRODUCTION_SLOTS[slot_key]
        state = get_slot_state(user.id, slot_key)
        if not state or not state["running"] or state["ready_at"] > time.time():
            await query.answer("هنوز آماده نیست.", show_alert=True)
            return
        added = add_to_inventory(user.id, slot_key, info["yield"])
        clear_slot(user.id, slot_key)
        category = "farm" if slot_key in FARM_SLOTS else "livestock"
        text, kb = build_production_text_and_keyboard(user.id, category)
        note = f"\n\n✅ {added} واحد {slot_key.replace('_',' ')} به انبار اضافه شد."
        if added < info["yield"]:
            note += " (انبارت پر بود، بخشیش از دست رفت — انبار رو ارتقا بده!)"
        await query.edit_message_text(text + note, reply_markup=kb)
        return

    if data.startswith("fstart:"):
        recipe_key = data.split(":", 1)[1]
        r = FACTORY_RECIPES[recipe_key]
        if not remove_from_inventory(user.id, r["input"], r["input_qty"]):
            await query.answer(f"مواد اولیه کافی نداری ({r['input_qty']} {r['input']} لازمه).", show_alert=True)
            return
        conn = db()
        c = conn.cursor()
        c.execute(
            "INSERT INTO factory_jobs (user_id, recipe_key, ready_at, collected) VALUES (?, ?, ?, 0)",
            (user.id, recipe_key, time.time() + r["seconds"]),
        )
        conn.commit()
        conn.close()
        text, kb = build_factory_text_and_keyboard(user.id)
        await query.edit_message_text(text, reply_markup=kb)
        return

    if data.startswith("fcollect:"):
        job_id = int(data.split(":", 1)[1])
        conn = db()
        c = conn.cursor()
        c.execute("SELECT * FROM factory_jobs WHERE id=? AND user_id=?", (job_id, user.id))
        job = c.fetchone()
        conn.close()
        if not job or job["collected"] or job["ready_at"] > time.time():
            await query.answer("هنوز آماده نیست یا قبلاً برداشت شده.", show_alert=True)
            return
        r = FACTORY_RECIPES[job["recipe_key"]]
        added = add_to_inventory(user.id, job["recipe_key"], r["output_qty"])
        conn = db()
        c = conn.cursor()
        c.execute("UPDATE factory_jobs SET collected=1 WHERE id=?", (job_id,))
        conn.commit()
        conn.close()
        text, kb = build_factory_text_and_keyboard(user.id)
        await query.edit_message_text(text + f"\n\n✅ {added} واحد {job['recipe_key']} برداشت شد.", reply_markup=kb)
        return

    if data == "shop:buy_menu":
        await query.edit_message_text("🛒 خرید ایتم — کدومو می‌خوای؟ (هر تپ = ۱۰ واحد)", reply_markup=build_buy_menu_keyboard())
        return

    if data == "shop:back":
        await query.edit_message_text("🛍 شاپ — برای خرید اومدی یا فروش؟", reply_markup=build_shop_keyboard())
        return

    if data.startswith("buy:"):
        item_key = data.split(":", 1)[1]
        info = BUY_CATALOG[item_key]
        total_cost = info["buy"] * BUY_BATCH
        player = get_player(user.id)
        if player["coins"] < total_cost:
            await query.answer(f"سکه کافی نداری. هزینه {BUY_BATCH} واحد: {total_cost}", show_alert=True)
            return
        added = add_to_inventory(user.id, item_key, BUY_BATCH)
        if added <= 0:
            await query.answer("انبارت پره، جا نداری.", show_alert=True)
            return
        actual_cost = info["buy"] * added
        conn = db()
        c = conn.cursor()
        c.execute("UPDATE players SET coins = coins - ? WHERE user_id=?", (actual_cost, user.id))
        conn.commit()
        conn.close()
        await query.answer(f"✅ {added} واحد {item_key.replace('_',' ')} خریدی ({actual_cost} سکه).", show_alert=True)
        return

    if data == "shop:sellall":
        inv = get_inventory(user.id)
        total_coins = 0
        conn = db()
        c = conn.cursor()
        for item_key, qty in inv.items():
            if qty <= 0 or item_key not in SELL_PRICES:
                continue
            total_coins += qty * SELL_PRICES[item_key]
            c.execute("UPDATE inventory SET quantity=0 WHERE user_id=? AND item_key=?", (user.id, item_key))
        c.execute("UPDATE players SET coins = coins + ? WHERE user_id=?", (total_coins, user.id))
        conn.commit()
        conn.close()
        await query.edit_message_text(f"✅ همه محصولات فروخته شد. {total_coins} سکه دریافت کردی.", reply_markup=build_shop_keyboard())
        return

    if data.startswith("shop:upgrade_"):
        what = data.split("_", 1)[1]  # factory / farm / livestock / storage
        player = get_player(user.id)
        if what == "storage":
            cost = STORAGE_UPGRADE_COST
            if player["coins"] < cost:
                await query.answer(f"سکه کافی نداری. هزینه: {cost}", show_alert=True)
                return
            conn = db()
            c = conn.cursor()
            c.execute(
                "UPDATE players SET coins = coins - ?, storage_capacity = storage_capacity + ? WHERE user_id=?",
                (cost, STORAGE_UPGRADE_AMOUNT, user.id),
            )
            conn.commit()
            conn.close()
            await query.edit_message_text(
                f"✅ ظرفیت انبار {STORAGE_UPGRADE_AMOUNT} واحد بیشتر شد.", reply_markup=build_shop_keyboard()
            )
            return
        else:
            level_col = f"{what}_level"
            current_level = player[level_col]
            cost = UPGRADE_BASE_COST * current_level
            if player["coins"] < cost:
                await query.answer(f"سکه کافی نداری. هزینه: {cost}", show_alert=True)
                return
            conn = db()
            c = conn.cursor()
            c.execute(
                f"UPDATE players SET coins = coins - ?, {level_col} = {level_col} + 1 WHERE user_id=?",
                (cost, user.id),
            )
            conn.commit()
            conn.close()
            await query.edit_message_text(
                f"✅ {what} به سطح {current_level + 1} ارتقا پیدا کرد.", reply_markup=build_shop_keyboard()
            )
            return


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN تنظیم نشده. اونو تو Railway Variables بذار.")
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(MessageHandler(filters.Regex("^(تولید|انباری|شاپ)$"), handle_text))
    app.add_handler(CallbackQueryHandler(button_handler))

    log.info("Farm bot starting (polling)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
