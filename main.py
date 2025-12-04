import asyncio
import locale
import logging
import requests
import os
import sys
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ContentType
from aiohttp import web

# --- Sozlamalar ---
# Valyuta API
CURRENCY_API_URL = "https://open.er-api.com/v6/latest/UZS" # UZS ga nisbatan olamiz osonroq bo'lishi uchun

# Ob-havo API (Open-Meteo - bepul, API key shart emas)
WEATHER_API_URL = "https://api.open-meteo.com/v1/forecast"

TELEGRAM_TOKEN = os.getenv("BOT_TOKEN", "SIZNING_TOKENINGIZ") # Bu yerga o'z tokeningizni qo'ying

# Locale
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
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# --- Global o'zgaruvchilar ---
exchange_rates = {"USD": None, "EUR": None} # Kurslar saqlanadigan joy
user_states = {}
subscriptions = {}
user_messages = {}

USERS_FILE = "users.txt"

# --- Yordamchi Funksiyalar ---

def get_weather_description(code):
    """Ob-havo kodini o'zbekchaga o'girish"""
    # WMO Weather interpretation codes (WW)
    weather_codes = {
        0: "Musaffo osmon ☀️",
        1: "Asosan ochiq 🌤",
        2: "Qisman bulutli ⛅",
        3: "Bulutli ☁️",
        45: "Tuman 🌫",
        48: "Qirovli tuman 🌫",
        51: "Yengil aylanma yomg'ir 🌧",
        53: "O'rtacha aylanma yomg'ir 🌧",
        55: "Kuchli aylanma yomg'ir 🌧",
        61: "Yengil yomg'ir 💧",
        63: "O'rtacha yomg'ir 🌧",
        65: "Kuchli yomg'ir ☔️",
        71: "Yengil qor ❄️",
        73: "O'rtacha qor ❄️",
        75: "Kuchli qor 🌨",
        80: "Jala ⛈",
        81: "Kuchli jala ⛈",
        82: "Juda kuchli jala ⛈",
        95: "Momoqaldiroq ⚡️",
        96: "Momoqaldiroq va do'l ⛈",
        99: "Kuchli momoqaldiroq va do'l ⛈"
    }
    return weather_codes.get(code, "Noaniq ob-havo")

def register_user(user_id: int):
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, "w", encoding="utf-8") as f: pass
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        users = f.read().splitlines()
    if str(user_id) not in users:
        with open(USERS_FILE, "a", encoding="utf-8") as f:
            f.write(f"{user_id}\n")

async def register_message(bot: Bot, chat_id: int, message_id: int, limit: int = 3):
    if chat_id not in user_messages: user_messages[chat_id] = []
    user_messages[chat_id].append(message_id)
    while len(user_messages[chat_id]) > limit:
        old_msg_id = user_messages[chat_id].pop(0)
        try: await bot.delete_message(chat_id, old_msg_id)
        except: pass

async def send_and_manage(message: Message, text: str, reply_markup=None):
    sent = await message.answer(text, reply_markup=reply_markup)
    await register_message(message.bot, message.chat.id, sent.message_id)
    return sent

# --- API so'rovlari ---

def fetch_rates():
    """Valyuta kurslarini yangilash"""
    try:
        # API bizga 1 UZS qancha USD bo'lishini beradi, bizga teskarisi kerak
        resp = requests.get(CURRENCY_API_URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        rates = data.get("rates", {})
        
        # 1 USD necha so'm
        if "USD" in rates:
            exchange_rates["USD"] = 1 / rates["USD"]
        # 1 EUR necha so'm
        if "EUR" in rates:
            exchange_rates["EUR"] = 1 / rates["EUR"]
            
        logger.info(f"Kurslar yangilandi: USD={exchange_rates['USD']}, EUR={exchange_rates['EUR']}")
        return True
    except Exception as e:
        logger.error(f"Valyuta API xatosi: {e}")
        return False

def get_weekly_weather(lat, lon):
    """7 kunlik ob-havo ma'lumotini olish"""
    try:
        params = {
            "latitude": lat,
            "longitude": lon,
            "daily": "weathercode,temperature_2m_max,temperature_2m_min",
            "timezone": "auto"
        }
        resp = requests.get(WEATHER_API_URL, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Ob-havo API xatosi: {e}")
        return None

async def update_rate_task():
    while True:
        fetch_rates()
        await asyncio.sleep(1800) # Har 30 minutda yangilash

async def auto_notify(bot: Bot):
    while True:
        if exchange_rates["USD"] and exchange_rates["EUR"]:
            msg = (f"🔔 Kunlik Kurs:\n"
                   f"🇺🇸 1 USD = {exchange_rates['USD']:,.2f} UZS\n"
                   f"🇪🇺 1 EUR = {exchange_rates['EUR']:,.2f} UZS")
            for user_id, active in subscriptions.items():
                if active:
                    try: await bot.send_message(user_id, msg)
                    except: pass
        await asyncio.sleep(86400)

# --- Klaviaturalar ---

main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="💵 Kurslar (USD/EUR)")],
        [KeyboardButton(text="🔄 Valyuta Ayirboshlash"), KeyboardButton(text="🌤 Ob-havo")],
        [KeyboardButton(text="⚙️ Sozlamalar / Yordam")]
    ], resize_keyboard=True
)

exchange_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🇺🇸 USD ➡️ UZS"), KeyboardButton(text="🇺🇿 UZS ➡️ USD")],
        [KeyboardButton(text="🇪🇺 EUR ➡️ UZS"), KeyboardButton(text="🇺🇿 UZS ➡️ EUR")],
        [KeyboardButton(text="🔙 Asosiy menyu")]
    ], resize_keyboard=True
)

location_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📍 Joylashuvni yuborish", request_location=True)],
        [KeyboardButton(text="🔙 Asosiy menyu")]
    ], resize_keyboard=True
)

settings_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🔔 Avto yangilash (Yoqish/O'chirish)")],
        [KeyboardButton(text="🔙 Asosiy menyu")]
    ], resize_keyboard=True
)

# --- Handlerlar ---

async def start_cmd(message: Message):
    register_user(message.from_user.id)
    await send_and_manage(message, "Assalomu alaykum! Botga xush kelibsiz.", reply_markup=main_kb)

async def show_rates(message: Message):
    if not exchange_rates["USD"]: fetch_rates()
    
    usd = exchange_rates.get("USD")
    eur = exchange_rates.get("EUR")
    
    if usd and eur:
        text = (f"🏦 Markaziy bank kursi bo'yicha:\n\n"
                f"🇺🇸 1 USD = {usd:,.2f} UZS\n"
                f"🇪🇺 1 EUR = {eur:,.2f} UZS")
    else:
        text = "⚠️ Kurslarni yuklab bo'lmadi."
    await send_and_manage(message, text)

async def weather_start(message: Message):
    await send_and_manage(message, "Ob-havo ma'lumotini olish uchun joylashuvingizni yuboring 👇", reply_markup=location_kb)

async def location_handler(message: Message):
    if not message.location:
        return
    
    lat = message.location.latitude
    lon = message.location.longitude
    
    await message.answer("🌤 Ma'lumotlar olinmoqda...", reply_markup=main_kb)
    
    data = get_weekly_weather(lat, lon)
    
    if not data or "daily" not in data:
        await send_and_manage(message, "❌ Ob-havo ma'lumotini olib bo'lmadi.")
        return

    daily = data["daily"]
    dates = daily["time"]
    codes = daily["weathercode"]
    max_temps = daily["temperature_2m_max"]
    min_temps = daily["temperature_2m_min"]
    
    report = "📅 **7 Kunlik Ob-havo Prognozi:**\n\n"
    
    for i in range(7): # 7 kun
        date_obj = datetime.strptime(dates[i], "%Y-%m-%d")
        date_str = date_obj.strftime("%d.%m") # Sana: 05.12 kabi
        desc = get_weather_description(codes[i])
        temp = f"{min_temps[i]}°C ... {max_temps[i]}°C"
        
        report += f"🗓 **{date_str}**: {desc}\n🌡 {temp}\n➖➖➖➖➖➖\n"
        
    await send_and_manage(message, report)

async def exchange_menu(message: Message):
    await send_and_manage(message, "Qaysi valyutani ayirboshlamoqchisiz?", reply_markup=exchange_kb)

async def settings_menu(message: Message):
    await send_and_manage(message, "Sozlamalar bo'limi:", reply_markup=settings_kb)

async def back_to_main(message: Message):
    user_states.pop(message.from_user.id, None)
    await send_and_manage(message, "Asosiy menyu:", reply_markup=main_kb)

# Konvertatsiya boshlanishi
async def convert_start(message: Message):
    text = message.text
    user_id = message.from_user.id
    
    if "USD ➡️ UZS" in text:
        user_states[user_id] = "usd_to_uzs"
        lbl = "USD"
    elif "UZS ➡️ USD" in text:
        user_states[user_id] = "uzs_to_usd"
        lbl = "so'm"
    elif "EUR ➡️ UZS" in text:
        user_states[user_id] = "eur_to_uzs"
        lbl = "EUR"
    elif "UZS ➡️ EUR" in text:
        user_states[user_id] = "uzs_to_eur"
        lbl = "so'm"
    else:
        return
        
    await send_and_manage(message, f"Qancha {lbl} miqdorini o'girmoqchisiz? Raqam kiriting:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔙 Asosiy menyu")]], resize_keyboard=True))

async def toggle_notify(message: Message):
    uid = message.from_user.id
    subscriptions[uid] = not subscriptions.get(uid, False)
    status = "yoqildi ✅" if subscriptions[uid] else "o'chirildi ⛔️"
    await send_and_manage(message, f"Avto yangilash {status}")

# Matnli xabarlar va hisob-kitob
async def text_handler(message: Message):
    await register_message(message.bot, message.chat.id, message.message_id)
    text = message.text
    user_id = message.from_user.id
    
    # Menyular navigatsiyasi
    if text == "🔙 Asosiy menyu": return await back_to_main(message)
    if text == "💵 Kurslar (USD/EUR)": return await show_rates(message)
    if text == "🌤 Ob-havo": return await weather_start(message)
    if text == "🔄 Valyuta Ayirboshlash": return await exchange_menu(message)
    if text == "⚙️ Sozlamalar / Yordam": return await settings_menu(message)
    if text == "🔔 Avto yangilash (Yoqish/O'chirish)": return await toggle_notify(message)
    
    if text in ["🇺🇸 USD ➡️ UZS", "🇺🇿 UZS ➡️ USD", "🇪🇺 EUR ➡️ UZS", "🇺🇿 UZS ➡️ EUR"]:
        return await convert_start(message)

    # Hisoblash jarayoni
    state = user_states.get(user_id)
    if state:
        try:
            amount = float(text.replace(",", "."))
            usd_rate = exchange_rates.get("USD", 0)
            eur_rate = exchange_rates.get("EUR", 0)
            
            if not usd_rate or not eur_rate:
                await send_and_manage(message, "⚠️ Kurs olinmagan, biroz kuting.")
                return

            res_text = ""
            if state == "usd_to_uzs":
                res = amount * usd_rate
                res_text = f"🇺🇸 {amount:,.2f} USD = 🇺🇿 {res:,.2f} UZS"
            elif state == "uzs_to_usd":
                res = amount / usd_rate
                res_text = f"🇺🇿 {amount:,.2f} UZS = 🇺🇸 {res:,.2f} USD"
            elif state == "eur_to_uzs":
                res = amount * eur_rate
                res_text = f"🇪🇺 {amount:,.2f} EUR = 🇺🇿 {res:,.2f} UZS"
            elif state == "uzs_to_eur":
                res = amount / eur_rate
                res_text = f"🇺🇿 {amount:,.2f} UZS = 🇪🇺 {res:,.2f} EUR"
            
            await send_and_manage(message, f"✅ Natija:\n{res_text}")
            # Hisoblagandan keyin menyuga qaytish yoki davom etish
            # user_states.pop(user_id) # Agar bir marta hisoblab menyuga qaytish kerak bo'lsa shuni oching
            
        except ValueError:
            await send_and_manage(message, "⚠️ Iltimos, faqat raqam kiriting.")

# --- Web Server (Render uchun) ---
async def health_check(request):
    return web.Response(text="Bot ishlamoqda!")

async def start_web_server():
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
    dp.message.register(location_handler, F.content_type == ContentType.LOCATION) # Joylashuvni ushlash
    dp.message.register(text_handler)

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
