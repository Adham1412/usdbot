import asyncio
import locale
import logging
import requests
import os
import sys
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiohttp import web  # Render portni tinglashi uchun kerak

# --- Sozlamalar ---
API_URL = "https://open.er-api.com/v6/latest/USD"

# Tokenni Render "Environment Variables" bo'limidan oladi.
# Agar topilmasa, kod ichidagi (test uchun) ishlatiladi.
TELEGRAM_TOKEN = os.getenv("BOT_TOKEN", "")

# Locale: minglik bo‘laklarga bo‘lish uchun
try:
    locale.setlocale(locale.LC_ALL, 'uz_UZ.UTF-8')
except locale.Error:
    try:
        locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
    except:
        locale.setlocale(locale.LC_ALL, '')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout) # Render loglarini konsolga chiqarish uchun
    ]
)
logger = logging.getLogger(__name__)

# --- Foydalanuvchilar fayli ---
# DIQQAT: Render bepul versiyasida fayllar vaqtinchalik.
# Bot qayta ishga tushsa, users.txt o'chib ketishi mumkin.
USERS_FILE = "users.txt"

def register_user(user_id: int):
    """Foydalanuvchini faylga yozib boradi"""
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            pass

    with open(USERS_FILE, "r", encoding="utf-8") as f:
        users = f.read().splitlines()

    if str(user_id) not in users:
        with open(USERS_FILE, "a", encoding="utf-8") as f:
            f.write(f"{user_id}\n")
        logger.info(f"✅ Yangi foydalanuvchi qo‘shildi: {user_id}")
    else:
        logger.info(f"ℹ️ Foydalanuvchi ro‘yxatda bor: {user_id}")

# --- Global o'zgaruvchilar ---
usd_to_uzs_rate = None   # global cache
user_states = {}         # foydalanuvchi holati
subscriptions = {}       # foydalanuvchi avto yangilash rejimi
user_messages = {}       # foydalanuvchi va bot xabarlarini boshqarish

# --- Yordamchi funksiyalar (xabarlarni boshqarish) ---
async def register_message(bot: Bot, chat_id: int, message_id: int, limit: int = 5):
    """Bot va foydalanuvchi yuborgan xabarlarni ro'yxatga oladi va eski xabarlarni o'chiradi"""
    if chat_id not in user_messages:
        user_messages[chat_id] = []
    user_messages[chat_id].append(message_id)

    while len(user_messages[chat_id]) > limit:
        old_msg_id = user_messages[chat_id].pop(0)
        try:
            await bot.delete_message(chat_id, old_msg_id)
        except Exception as e:
            # Xabar allaqachon o'chirilgan bo'lishi mumkin
            pass

async def send_and_manage(message: Message, text: str, reply_markup=None):
    """Bot xabarini yuborib, boshqaruvga qo'shadi"""
    sent = await message.answer(text, reply_markup=reply_markup)
    await register_message(message.bot, message.chat.id, sent.message_id)
    return sent

# --- Kurs olish ---
def fetch_usd_to_uzs():
    try:
        resp = requests.get(API_URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if "rates" in data and "UZS" in data["rates"]:
            return float(data["rates"]["UZS"])
    except Exception as e:
        logger.error(f"API xatosi: {e}")
    return None

async def update_rate_task():
    global usd_to_uzs_rate
    while True:
        rate = fetch_usd_to_uzs()
        if rate:
            usd_to_uzs_rate = rate
            logger.info(f"Kurs yangilandi: 1 USD = {usd_to_uzs_rate:,.2f} UZS")
        else:
            logger.error("Kursni yangilab bo'lmadi, eski kurs qolmoqda.")
        await asyncio.sleep(600)  # 10 minutda yangilash

# --- Avto yangilash ---
async def auto_notify(bot: Bot):
    while True:
        if usd_to_uzs_rate:
            for user_id, active in subscriptions.items():
                if active:
                    kurs_text = f"{usd_to_uzs_rate:,.2f}"
                    try:
                        await bot.send_message(user_id, f"🔔 Avto yangilash:\n1 USD = {kurs_text} UZS")
                    except Exception as e:
                        logger.error(f"{user_id} ga yuborishda xato: {e}")
        await asyncio.sleep(86400)  # 24 soatda yuborish

# --- Klaviatura ---
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="💵 Kursni ko‘rsat")],
        [KeyboardButton(text="🔄 USD → UZS"), KeyboardButton(text="🔁 UZS → USD")],
        [KeyboardButton(text="🔔 Avto yangilashni yoqish/o‘chirish")],
        [KeyboardButton(text="ℹ️ Yordam")]
    ],
    resize_keyboard=True
)

# --- Komandalar ---
async def start_cmd(message: Message):
    register_user(message.from_user.id)
    await send_and_manage(message, "Salom! Men USD ↔ UZS botman.\nKerakli tugmani tanlang 👇", reply_markup=main_kb)

async def help_cmd(message: Message):
    await send_and_manage(
        message,
        "💵 Kursni ko‘rsat – 1 USD kursini ko‘rsatadi\n"
        "🔄 USD → UZS – Siz dollar miqdorini yuborasiz, men so‘mga aylantiraman\n"
        "🔁 UZS → USD – Siz so‘m miqdorini yuborasiz, men dollarga aylantiraman\n"
        "🔔 Avto yangilash – 24 soatda kursni avtomatik yuborib turadi"
    )

async def rate_cmd(message: Message):
    if usd_to_uzs_rate is None:
        await send_and_manage(message, "Kurs hozircha olinmadi.")
        return
    kurs_text = f"{usd_to_uzs_rate:,.2f}"
    await send_and_manage(message, f"1 USD = {kurs_text} UZS")

async def usd_to_uzs_start(message: Message):
    user_states[message.from_user.id] = "usd_to_uzs"
    await send_and_manage(message, "Necha USD miqdorini so‘mga o‘girishni xohlaysiz? Raqam kiriting.")

async def uzs_to_usd_start(message: Message):
    user_states[message.from_user.id] = "uzs_to_usd"
    await send_and_manage(message, "Necha so‘mni dollarga o‘girishni xohlaysiz? Raqam kiriting.")

async def toggle_auto_notify(message: Message):
    user_id = message.from_user.id
    current = subscriptions.get(user_id, False)
    subscriptions[user_id] = not current
    if subscriptions[user_id]:
        await send_and_manage(message, "✅ Avto yangilash yoqildi. Sizga har 24 soatda kurs yuboriladi.")
    else:
        await send_and_manage(message, "⛔ Avto yangilash o‘chirildi.")

# --- Text handler ---
async def text_handler(message: Message):
    await register_message(message.bot, message.chat.id, message.message_id)

    user_id = message.from_user.id
    text = (message.text or "").strip()

    if text == "💵 Kursni ko‘rsat":
        return await rate_cmd(message)
    if text == "🔄 USD → UZS":
        return await usd_to_uzs_start(message)
    if text == "🔁 UZS → USD":
        return await uzs_to_usd_start(message)
    if text == "ℹ️ Yordam":
        return await help_cmd(message)
    if text == "🔔 Avto yangilashni yoqish/o‘chirish":
        return await toggle_auto_notify(message)

    if user_id in user_states:
        if usd_to_uzs_rate is None:
            await send_and_manage(message, "Kurs hozircha olinmadi.")
            return
        try:
            amount = float(text.replace(",", "."))
            if user_states[user_id] == "usd_to_uzs":
                result = amount * usd_to_uzs_rate
                usd_text = f"{amount:,.2f}"
                uzs_text = f"{result:,.2f}"
                await send_and_manage(message, f"{usd_text} USD = {uzs_text} UZS")
            elif user_states[user_id] == "uzs_to_usd":
                result = amount / usd_to_uzs_rate
                uzs_text = f"{amount:,.2f}"
                usd_text = f"{result:,.2f}"
                await send_and_manage(message, f"{uzs_text} UZS = {usd_text} USD")
        except ValueError:
            await send_and_manage(message, "Iltimos, faqat raqam kiriting.")
        user_states.pop(user_id, None)
    else:
        await send_and_manage(message, "Kerakli tugmani tanlang 👇", reply_markup=main_kb)

# --- Render uchun Dummy Web Server ---
async def health_check(request):
    return web.Response(text="Bot is running OK!")

async def start_web_server():
    # Render PORT environment o'zgaruvchisini beradi
    port = int(os.environ.get("PORT", 8080))
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"🌍 Web server {port}-portda ishga tushdi")

# --- Asosiy ---
async def main():
    bot = Bot(token=TELEGRAM_TOKEN)
    dp = Dispatcher()

    dp.message.register(start_cmd, Command("start"))
    dp.message.register(text_handler)

    # Web server va Botni parallel ishga tushiramiz
    await asyncio.gather(
        update_rate_task(),
        auto_notify(bot),
        start_web_server(),
        dp.start_polling(bot)
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):

        logger.info("Bot to'xtatildi")
