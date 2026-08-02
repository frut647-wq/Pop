import os
import time
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

START_COINS = 200
START_FLOUR = 50  # آرد اولیه که میشه به خمیر و بعد نان تبدیلش کرد
START_STORAGE = 2000

# کاتالوگ کامل آیتم‌های قابل خرید از شاپ (هر تپ = ۱۰ واحد) — فقط اسم و ایموجی، قیمت از دیتابیس میاد
BUY_CATALOG = {
    "نون":        {"emoji": "🥖"},
    "کیک":        {"emoji": "🎂"},
    "پیتزا":      {"emoji": "🍕"},
    "هات_داگ":    {"emoji": "🌭"},
    "سوسیس":      {"emoji": "🌭"},
    "فرنچ":       {"emoji": "🍟"},
    "پنیر":       {"emoji": "🧀"},
    "لباس":       {"emoji": "👚"},
    "خمیر":       {"emoji": "⚪"},
    "نیمرو":      {"emoji": "🍳"},
    "تخم_مرغ":    {"emoji": "🥚"},
    "شیر":        {"emoji": "🥛"},
    "پشم":        {"emoji": "🧶"},
    "ارد":        {"emoji": "⬜"},
    "شکر":        {"emoji": "⬜"},
    "گندم":       {"emoji": "🌾"},
    "سیب_زمینی":  {"emoji": "🥔"},
    "نیشکر":      {"emoji": "🎋"},
    "برنج":       {"emoji": "🍚"},
    "مرغ":        {"emoji": "🐔"},
    "گوسفند":     {"emoji": "🐑"},
    "گاو":        {"emoji": "🐄"},
}
BUY_BATCH = 10

# ------------------------------------------------------------------
# تعریف منابع مزرعه و دامداری (تولید دسته‌ای: بعد از X ثانیه Y واحد آماده میشه)
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
# زنجیره‌های تولید کارخونه — آرد به خمیر به نان، پشم به نخ به پارچه، شیر به ماست
# ------------------------------------------------------------------
FACTORY_RECIPES = {
    "خمیر":  {"emoji": "🥟", "input": "ارد",  "input_qty": 20,  "output_qty": 15, "seconds": 300},
    "نان":   {"emoji": "🍞", "input": "خمیر", "input_qty": 15,  "output_qty": 15, "seconds": 300},
    "نخ":    {"emoji": "🧵", "input": "پشم",  "input_qty": 100, "output_qty": 40, "seconds": 300},
    "پارچه": {"emoji": "🧣", "input": "نخ",   "input_qty": 40,  "output_qty": 40, "seconds": 300},
    "ماست":  {"emoji": "🥣", "input": "شیر",  "input_qty": 100, "output_qty": 40, "seconds": 300},
}

# قیمت پیش‌فرض خرید/فروش — فقط برای seed اولیه دیتابیس؛ بعدش با دستور «تنظیم قیمت» قابل تغییره
DEFAULT_BUY_PRICES = {
    "نون": 10, "کیک": 40, "پیتزا": 35, "هات_داگ": 20, "سوسیس": 15,
    "فرنچ": 12, "پنیر": 18, "لباس": 50, "خمیر": 8, "نیمرو": 8,
    "تخم_مرغ": 6, "شیر": 6, "پشم": 6, "ارد": 5, "شکر": 6,
    "گندم": 4, "سیب_زمینی": 4, "نیشکر": 4, "برنج": 4,
    "مرغ": 300, "گوسفند": 350, "گاو": 500,
}
DEFAULT_SELL_PRICES = {
    "گندم": 1, "برنج": 1, "نیشکر": 1, "سیب_زمینی": 1,
    "تخم_مرغ": 2, "پشم": 2, "شیر": 2,
    "خمیر": 3, "نان": 6, "نخ": 3, "پارچه": 6, "ماست": 5,
    "نون": 6, "کیک": 25, "پیتزا": 22, "هات_داگ": 12, "سوسیس": 9,
    "فرنچ": 7, "پنیر": 11, "لباس": 30, "نیمرو": 5, "ارد": 3, "شکر": 3,
    "مرغ": 150, "گوسفند": 175, "گاو": 250,
}
ALL_PRICED_ITEMS = sorted(set(DEFAULT_BUY_PRICES) | set(DEFAULT_SELL_PRICES))

# هزینه ارتقای ساختمان‌ها
UPGRADE_BASE_COST = 300
STORAGE_UPGRADE_COST = 250
STORAGE_UPGRADE_AMOUNT = 1000

ITEM_EMOJI = {**{k: v["emoji"] for k, v in ALL_PRODUCTION_SLOTS.items()},
              **{k: v["emoji"] for k, v in FACTORY_RECIPES.items()},
              **{k: v["emoji"] for k, v in BUY_CATALOG.items()}}


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
            coins INTEGER DEFAULT 200,
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
    c.execute("""
        CREATE TABLE IF NOT EXISTS production_slots (
            user_id INTEGER,
            slot_key TEXT,
            ready_at REAL DEFAULT 0,
            running INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, slot_key)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS factory_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            recipe_key TEXT,
            ready_at REAL,
            collected INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS item_prices (
            item_key TEXT PRIMARY KEY,
            buy_price INTEGER DEFAULT 0,
            sell_price INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS serials (
            code TEXT PRIMARY KEY,
            amount INTEGER,
            created_by INTEGER,
            redeemed_by INTEGER DEFAULT NULL,
            created_at REAL
        )
    """)
    # seed قیمت‌های پیش‌فرض (فقط اگه قبلاً ست نشده باشن)
    for item in ALL_PRICED_ITEMS:
        c.execute(
            "INSERT OR IGNORE INTO item_prices (item_key, buy_price, sell_price) VALUES (?, ?, ?)",
            (item, DEFAULT_BUY_PRICES.get(item, 0), DEFAULT_SELL_PRICES.get(item, 0)),
        )
    conn.commit()
    conn.close()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ------------------------------------------------------------------
# قیمت‌ها
# ------------------------------------------------------------------
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


# ------------------------------------------------------------------
# بازیکن‌ها و انبار
# ------------------------------------------------------------------
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
    inv = get_inventory(user_id)
    return sum(inv.values())


def add_to_inventory(user_id: int, item_key: str, qty: int) -> int:
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


async def safe_answer(query, **kwargs):
    try:
        await query.answer(**kwargs)
    except Exception:
        pass


# ------------------------------------------------------------------
# پنل تولید (مزرعه/دامداری)
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
        emoji = ITEM_EMOJI.get(key, "📦")
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
            buy_price, _ = get_price(key)
            row.append(InlineKeyboardButton(f"{info['emoji']} {label} ({buy_price})", callback_data=f"buy:{key}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("🔙 بازگشت به شاپ", callback_data="shop:back")])
    return InlineKeyboardMarkup(rows)


# ------------------------------------------------------------------
# سریال (کد هدیه)
# ------------------------------------------------------------------
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
    c.execute(
        "INSERT INTO serials (code, amount, created_by, created_at) VALUES (?, ?, ?, ?)",
        (code, amount, user_id, time.time()),
    )
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


# ------------------------------------------------------------------
# دستورات
# ------------------------------------------------------------------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_player(user.id, user.username or user.first_name)
    guide = (
        f"🌱 به Seed2Wealth خوش اومدی، {user.first_name}!\n\n"
        f"شما {START_COINS} سکه و {START_FLOUR} واحد آرد (ارد) اولیه گرفتی.\n\n"
        "📖 این بازی چی داره:\n"
        "🌾 مزرعه — گندم، برنج، نیشکر، سیب‌زمینی با تایمر تولید میشن\n"
        "🐔 دامداری — تخم‌مرغ، پشم، شیر\n"
        "🏭 کارخونه — سه زنجیره تولید: آرد→خمیر→نان | پشم→نخ→پارچه | شیر→ماست\n"
        "📦 انباری — با ظرفیت محدود (قابل ارتقا)\n"
        "🛒 شاپ — خرید مستقیم آیتم‌ها، فروش سریع، ارتقای مزرعه/دامداری/کارخونه/انبار\n"
        "🎁 سریال — کد هدیه بساز و به دوستات بده؛ اونا با فرستادن کد تو پیوی ربات سکه می‌گیرن\n\n"
        "🚫 این بازی چی نداره:\n"
        "بازی‌های دیگه (ریاضی، حدس، جنگ، ماشین) تو بات‌های جدا هستن، نه اینجا.\n\n"
        "🎮 شروع سریع: تو گروه بنویس «تولید»، وارد کارخونه شو، دکمه «تولید خمیر» رو بزن (از همون آردت مصرف میشه)، بعد از آماده شدن «نان» بساز و تو شاپ بفروش.\n\n"
        "دستورات: تولید | انباری | شاپ | قیمت <آیتم> | سریال <مقدار>"
    )
    await update.effective_message.reply_text(guide)


async def production_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_player(user.id, user.username or user.first_name)
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
        await update.effective_message.reply_text(
            "فرمت درست: تنظیم قیمت <آیتم> <خرید> <فروش>\nمثال: تنظیم قیمت نان 10 20"
        )
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
    await update.effective_message.reply_text(
        f"✅ قیمت {item_name} آپدیت شد. خرید: {buy_str} | فروش: {sell_str}"
    )


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
        f"🎁 سریال ساخته شد{note}:\n`{code}`\n"
        f"ارزش: {amount} سکه\n\n"
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


# ------------------------------------------------------------------
# مسیریابی متن — فقط دستورات شناخته‌شده جواب می‌گیرن، بقیه پیام‌های گروه نادیده گرفته میشن
# ------------------------------------------------------------------
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
    if text.startswith("تنظیم قیمت"):
        await price_set_cmd(update, context, text[len("تنظیم قیمت"):].strip())
        return
    if text.startswith("قیمت"):
        await price_query_cmd(update, context, text[len("قیمت"):].strip())
        return
    if text.startswith("سریال"):
        await serial_create_cmd(update, context, text[len("سریال"):].strip())
        return

    # فقط تو پیوی: اگه متن شبیه کد سریال بود، امتحان کن ردیمش کنه
    if chat_type == "private" and text.upper().startswith("S2W-"):
        await serial_redeem_private(update, context, text.upper().strip())
        return

    # هر چیز دیگه‌ای (چه تو گروه چه تو پیوی) نادیده گرفته میشه


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
        await query.answer(f"✅ {added} واحد {item_key.replace('_',' ')} خریدی ({actual_cost} سکه).", show_alert=True)
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
        await query.edit_message_text(f"✅ همه محصولات فروخته شد. {total_coins} سکه دریافت کردی.", reply_markup=build_shop_keyboard())
        return

    if data.startswith("shop:upgrade_"):
        what = data.split("_", 1)[1]
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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(button_handler))

    log.info("Farm bot starting (polling)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
