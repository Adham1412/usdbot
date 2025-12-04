import asyncio
import logging
import requests
import os
import sys
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ContentType
from aiohttp import web

# --- SOZLAMALAR ---

# 1. Telegram Bot Tokeningiz
TELEGRAM_TOKEN = os.getenv("BOT_TOKEN", "SIZNING_TELEGRAM_BOT_TOKENINGIZ")

# 2. OpenWeatherMap API Kaliti (Token)
# https://home.openweathermap.org/api_keys saytidan olasiz
WEATHER_TOKEN = os.getenv("WEATHER_TOKEN", "933114d1b96dce040e4af37f330744c0")

# Valyuta API (Bepul)
CURRENCY_API_URL = "https://open.er-api.com/v6/latest/UZS"

# --- LOGGING ---
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

# --- GLOBAL O'ZGARUVCHILAR ---
exchange_rates = {"USD": None, "EUR": None}
user_states = {}

# --- LUG'ATLAR (TARJIMA UCHUN) ---
weather_translations = {
    "Clear": "☀️ Ochiq (Quyoshli)",
    "Clouds": "☁️ Bulutli",
    "Rain": "🌧 Yomg'ir",
    "Drizzle": "🌦 Yengil yomg'ir",
    "Thunderstorm": "⛈ Momoqaldiroq",
    "Snow": "❄️ Qor",
    "Mist": "🌫 Tuman",
    "Smoke": "🌫 Tutun/Chang",
    "Haze": "🌫 Dim/Chang",
    "Dust": "🌪 Changli",
    "Fog": "🌫 Quyuq tuman",
    "Sand": "🌪 Qum bo'roni",
    "Ash": "🌋 Vulqon kuli",
    "Squall": "🌬 Kuchli shamol",
    "Tornado": "🌪 Tornado"
}

# --- YORDAMCHI FUNKSIYALAR ---

def get_rates():
    """Valyuta kurslarini yangilash"""
    try:
        resp = requests.get(CURRENCY_API_URL, timeout=5).json()
        rates = resp.get("rates", {})
        if "USD" in rates: exchange_rates["USD"] = 1 / rates["USD"]
        if "EUR" in rates: exchange_rates["EUR"] = 1 / rates["EUR"]
        return True
    except Exception as e:
        logger.error(f"Valyuta xatosi: {e}")
        return False

def get_forecast(lat, lon):
    """
    OpenWeatherMap orqali 5 kunlik prognozni oladi.
    Token talab qilinadi.
    """
    url = "https://api.openweathermap.org/data/2.5/forecast"
    params = {
        "lat": lat,
        "lon": lon,
        "appid": WEATHER_TOKEN,
        "units": "metric", # Gradus Selsiyda olish
        "lang": "ru"       # Aslida o'zimiz tarjima qilamiz, lekin zaxira uchun
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Ob-havo xatosi: {e}")
        return None

def format_weather_report(data):
    """
    JSON ma'lumotni ixcham dizaynga o'girish.
    API har 3 soatlik ma'lumot beradi, biz kunlik qilib saralaymiz.
    """
    city = data["city"]["name"]
    country = data["city"]["country"]
    list_data = data["list"]
    
    report = f"📍 <b>{city}, {country}</b> hududi uchun prognoz:\n\n"
    
    processed_days = []
    
    for item in list_data:
        # Sana va vaqtni olamiz
        dt_txt = item["dt_txt"] # "2023-10-10 12:00:00"
        date_obj = datetime.strptime(dt_txt, "%Y-%m-%d %H:%M:%S")
        day_str = date_obj.strftime("%d.%m") # "10.10"
        
        # Bizga faqat kunduzi soat 12:00 yoki unga yaqin vaqt kerak (kunlik umumiy holat uchun)
        if day_str not in processed_days and (11 <= date_obj.hour <= 14):
            temp = round(item["main"]["temp"])
            desc_main = item["weather"][0]["main"]
            wind_speed = item["wind"]["speed"]
            
            # Tarjima qilish
            uzb_desc = weather_translations.get(desc_main, desc_main)
            
            # Emojilar bilan bezash
            temp_sign = "+" if temp > 0 else ""
            
            # Format: 📅 10.10 | ☀️ Quyoshli | 🌡 +22°C
            line = f"📅 <b>{day_str}</b> | {uzb_desc}\n🌡 Harorat: <b>{temp_sign}{temp}°C</b> | 💨 Shamol: {wind_speed} m/s\n〰️〰️〰️〰️〰️〰️\n"
            
            report += line
            processed_days.append(day_str)
            
            # 5 kunlik limit (ba'zida API 6-kunni ham qisman beradi)
            if len(processed_days) >= 5:
                break
    
    return report

# --- KLAVIATURALAR ---
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🌤 Ob-havo (Joylashuv)"), KeyboardButton(text="💵 Valyuta Kursi")],
        [KeyboardButton(text="🔄 Valyuta Ayirboshlash")]
    ],
    resize_keyboard=True
)

location_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📍 Joylashuvni ulashish", request_location=True)],
        [KeyboardButton(text="🔙 Bekor qilish")]
    ],
    resize_keyboard=True
)

calc_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🇺🇸 USD ➡️ UZS"), KeyboardButton(text="🇺🇿 UZS ➡️ USD")],
        [KeyboardButton(text="🇪🇺 EUR ➡️ UZS"), KeyboardButton(text="🔙 Bosh menyu")]
    ],
    resize_keyboard=True
)

# --- HANDLERLAR ---

async def start_handler(message: Message):
    await message.answer(
        "👋 Salom! Men mukammal yordamchi botman.\n\n"
        "⛅️ <b>Ob-havo:</b> Aniq va ixcham prognoz.\n"
        "💰 <b>Valyuta:</b> Dollar va Yevro hisob-kitobi.",
        reply_markup=main_kb,
        parse_mode="HTML"
    )

async def weather_ask(message: Message):
    await message.answer(
        "Ob-havo ma'lumotini olish uchun <b>pastdagi tugma</b> orqali joylashuvingizni yuboring 👇",
        reply_markup=location_kb,
        parse_mode="HTML"
    )

async def weather_response(message: Message):
    if not WEATHER_TOKEN or WEATHER_TOKEN == "SIZNING_OPENWEATHER_TOKENINGIZ":
        await message.answer("⚠️ Bot sozlamalarida Ob-havo Tokeni kiritilmagan.")
        return

    lat = message.location.latitude
    lon = message.location.longitude
    
    msg = await message.answer("🔄 Ma'lumotlar yuklanmoqda...")
    
    weather_data = get_forecast(lat, lon)
    
    if weather_data:
        formatted_text = format_weather_report(weather_data)
        await bot.delete_message(message.chat.id, msg.message_id)
        await message.answer(formatted_text, reply_markup=main_kb, parse_mode="HTML")
    else:
        await message.answer("❌ Ob-havo ma'lumotini olib bo'lmadi. Keyinroq urinib ko'ring.", reply_markup=main_kb)

async def currency_rates(message: Message):
    get_rates()
    usd = exchange_rates.get("USD")
    eur = exchange_rates.get("EUR")
    
    if usd and eur:
        text = (
            "🏦 <b>Markaziy Bank Kurslari:</b>\n\n"
            f"🇺🇸 <b>1 USD</b> = {usd:,.2f} so'm\n"
            f"🇪🇺 <b>1 EUR</b> = {eur:,.2f} so'm"
        )
    else:
        text = "⚠️ Kurslarni yuklab bo'lmadi."
        
    await message.answer(text, reply_markup=main_kb, parse_mode="HTML")

async def calc_menu(message: Message):
    await message.answer("Valyuta yo'nalishini tanlang:", reply_markup=calc_kb)

async def calc_start(message: Message):
    text = message.text
    user_id = message.from_user.id
    
    if text == "🔙 Bosh menyu":
        user_states.pop(user_id, None)
        return await start_handler(message)
    
    if "USD ➡️ UZS" in text: user_states[user_id] = "usd_to_uzs"
    elif "UZS ➡️ USD" in text: user_states[user_id] = "uzs_to_usd"
    elif "EUR ➡️ UZS" in text: user_states[user_id] = "eur_to_uzs"
    
    await message.answer("Summani kiriting (faqat raqam):", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔙 Bekor qilish")]], resize_keyboard=True))

async def text_router(message: Message):
    text = message.text
    user_id = message.from_user.id

    # Menyu buyruqlari
    if text == "🌤 Ob-havo (Joylashuv)": return await weather_ask(message)
    if text == "💵 Valyuta Kursi": return await currency_rates(message)
    if text == "🔄 Valyuta Ayirboshlash": return await calc_menu(message)
    if text == "🔙 Bekor qilish": 
        user_states.pop(user_id, None)
        return await start_handler(message)
    
    # Hisob-kitob jarayoni
    state = user_states.get(user_id)
    if state:
        try:
            amount = float(text.replace(",", "."))
            if not exchange_rates["USD"]: get_rates()
            
            res_text = ""
            if state == "usd_to_uzs":
                res = amount * exchange_rates["USD"]
                res_text = f"🇺🇸 {amount:,.2f} USD = 🇺🇿 {res:,.2f} UZS"
            elif state == "uzs_to_usd":
                res = amount / exchange_rates["USD"]
                res_text = f"🇺🇿 {amount:,.2f} UZS = 🇺🇸 {res:,.2f} USD"
            elif state == "eur_to_uzs":
                res = amount * exchange_rates["EUR"]
                res_text = f"🇪🇺 {amount:,.2f} EUR = 🇺🇿 {res:,.2f} UZS"
            
            await message.answer(f"✅ <b>Natija:</b>\n{res_text}", parse_mode="HTML", reply_markup=calc_kb)
        except ValueError:
            await message.answer("⚠️ Iltimos, to'g'ri raqam kiriting.")

# --- WEB SERVER (RENDER UCHUN) ---
async def health_check(request):
    return web.Response(text="Bot is running")

async def start_web_server():
    port = int(os.environ.get("PORT", 8080))
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

# --- MAIN ---
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

dp.message.register(start_handler, Command("start"))
dp.message.register(weather_response, F.content_type == ContentType.LOCATION)
dp.message.register(calc_start, F.text.contains("➡️"))
dp.message.register(text_router)

async def main():
    await asyncio.gather(
        start_web_server(),
        dp.start_polling(bot)
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass

