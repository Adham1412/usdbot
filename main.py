import asyncio
import logging
import requests
import os
import sys
import json
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ContentType
from aiohttp import web
   
# --- SOZLAMALAR ---
TELEGRAM_TOKEN = os.getenv("BOT_TOKEN", "SIZNING_TELEGRAM_BOT_TOKENINGIZ")
WEATHER_TOKEN = os.getenv("WEATHER_TOKEN", "933114d1b96dce040e4af37f330744c0")
CURRENCY_API_URL = "https://open.er-api.com/v6/latest/UZS"

# Xabarlar yuboriladigan vaqt (Soat) - Server vaqti bilan
DAILY_SEND_HOUR = 7  # Ertalab 07:00 da
SUBS_FILE = "subscribers.json"

# --- LOGGING ---
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

# --- GLOBAL O'ZGARUVCHILAR VA XOTIRA ---
exchange_rates = {"USD": None, "EUR": None}
user_states = {}

# Obunachilar bazasi (Fayldan o'qish va yozish)
def load_subs():
    if not os.path.exists(SUBS_FILE):
        return {"currency": [], "weather": {}}
    try:
        with open(SUBS_FILE, "r") as f:
            return json.load(f)
    except:
        return {"currency": [], "weather": {}}


def save_subs(data):
    with open(SUBS_FILE, "w") as f:
        json.dump(data, f)

# Dastlabki yuklash
subscriptions = load_subs()

# --- TARJIMALAR ---
weather_translations = {
    "Clear": "☀️ Ochiq", "Clouds": "☁️ Bulutli", "Rain": "🌧 Yomg'ir",
    "Drizzle": "🌦 Yengil yomg'ir", "Thunderstorm": "⛈ Momoqaldiroq",
    "Snow": "❄️ Qor", "Mist": "🌫 Tuman", "Fog": "🌫 Quyuq tuman",
    "Smoke": "🌫 Tutun", "Haze": "🌫 Chang", "Dust": "🌪 Changli",
    "Sand": "🌪 Qum", "Ash": "🌋 Kul", "Squall": "🌬 Shamol", "Tornado": "🌪 Tornado"
}

# --- YORDAMCHI FUNKSIYALAR ---
def get_rates():
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
    url = "https://api.openweathermap.org/data/2.5/forecast"
    params = {"lat": lat, "lon": lon, "appid": WEATHER_TOKEN, "units": "metric", "lang": "ru"}
    try:
        response = requests.get(url, params=params, timeout=10)
        payload = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else {}

        if response.status_code != 200 or not isinstance(payload, dict):
            logger.warning(f"OpenWeather API xatosi: status={response.status_code}, body={payload}")
            return None

        if payload.get("cod") not in (None, 200, "200"):
            logger.warning(f"OpenWeather API xatosi: {payload.get('message', 'unknown error')}")
            return None

        if not payload.get("list"):
            logger.warning(f"OpenWeather javobida forecast list yo'q: {payload}")
            return None

        return payload
    except Exception as e:
        logger.exception(f"Ob-havo so'rovi xatosi: {e}")
        return None


def format_weather_report(data, is_daily=False):
    if not isinstance(data, dict):
        return "⚠️ Ob-havo ma'lumotlari topilmadi."

    items = data.get("list") or []
    if not items:
        return "⚠️ Ob-havo ma'lumotlari topilmadi."

    city = (data.get("city") or {}).get("name") or data.get("name") or "Hudud"
    report = f"📍 <b>{city}</b> ob-havosi:\n\n"
    processed_days = set()
    visible_items = items[:8] if is_daily else items

    for item in visible_items:
        try:
            dt_txt = item.get("dt_txt")
            if not dt_txt:
                continue
            date_obj = datetime.strptime(dt_txt, "%Y-%m-%d %H:%M:%S")
            day_str = date_obj.strftime("%d.%m")
            hour = date_obj.hour

            # Kunduzgi vaqtni (11:00-14:00) yoki birinchi ma'lumotdan olish
            if day_str in processed_days:
                continue
            if not is_daily and not (11 <= hour <= 14):
                continue

            temp = round(item.get("main", {}).get("temp", 0))
            desc = (item.get("weather") or [{}])[0].get("main", "Unknown")
            uzb_desc = weather_translations.get(desc, desc)
            wind_speed = (item.get("wind") or {}).get("speed", 0)
            temp_sign = "+" if temp > 0 else ""

            report += f"📅 <b>{day_str}</b> | {uzb_desc}\n🌡 <b>{temp_sign}{temp}°C</b> | 💨 {wind_speed} m/s\n\n"
            processed_days.add(day_str)

            if len(processed_days) >= (1 if is_daily else 5):
                break
        except (TypeError, ValueError, KeyError):
            continue

    if report == f"📍 <b>{city}</b> ob-havosi:\n\n":
        return "⚠️ Ob-havo ma'lumotlari to'liq kelmadi."

    return report


def get_currency_text():
    get_rates()
    usd, eur = exchange_rates.get("USD"), exchange_rates.get("EUR")
    if usd and eur:
        return f"📅 Kunlik Valyuta:\n\n🇺🇸 1 USD = {usd:,.2f} so'm\n🇪🇺 1 EUR = {eur:,.2f} so'm"
    return None

# --- KLAVIATURALAR ---
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🌤 Ob-havo"), KeyboardButton(text="💵 Valyuta")],
        [KeyboardButton(text="🔔 Valyutani kunlik bilish"), KeyboardButton(text="🔔 Ob-havoni har kuni bilish")],
        [KeyboardButton(text="🔄 Ayirboshlash")]
    ], resize_keyboard=True
)

location_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="📍 Joylashuvni yuborish", request_location=True)], [KeyboardButton(text="🔙 Bekor qilish")]],
    resize_keyboard=True
)

calc_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="🇺🇸 USD ➡️ UZS"), KeyboardButton(text="🇺🇿 UZS ➡️ USD")], [KeyboardButton(text="🔙 Bosh menyu")]],
    resize_keyboard=True
)

# --- AVTOMATIK YUBORISH (SCHEDULER) ---
async def daily_scheduler(bot: Bot):
    while True:
        now = datetime.now()
        # Soat tekshirish (Masalan 07:00 da)
        if now.hour == DAILY_SEND_HOUR and now.minute == 0:
            # 1. Valyuta yuborish
            currency_text = get_currency_text()
            if currency_text:
                users_to_remove = []
                for user_id in subscriptions["currency"]:
                    try:
                        await bot.send_message(user_id, currency_text)
                        await asyncio.sleep(0.05) # Spam qilmaslik uchun
                    except:
                        users_to_remove.append(user_id) # Botni bloklaganlarni o'chirish
                
                # Tozalash
                if users_to_remove:
                    for uid in users_to_remove:
                        if uid in subscriptions["currency"]: subscriptions["currency"].remove(uid)
                    save_subs(subscriptions)

            # 2. Ob-havo yuborish
            users_to_remove_weather = []
            for user_str, coords in subscriptions["weather"].items():
                try:
                    w_data = get_forecast(coords["lat"], coords["lon"])
                    if w_data:
                        text = format_weather_report(w_data, is_daily=True)
                        await bot.send_message(int(user_str), "☀️ Xayrli tong! " + text, parse_mode="HTML")
                        await asyncio.sleep(0.05)
                except:
                    users_to_remove_weather.append(user_str)
            
            if users_to_remove_weather:
                for uid in users_to_remove_weather:
                    subscriptions["weather"].pop(uid, None)
                save_subs(subscriptions)

            # 1 soat kutamiz (qayta yubormaslik uchun)
            await asyncio.sleep(3600) 
        
        # Har 60 soniyada vaqtni tekshirib turadi
        await asyncio.sleep(60)

# --- HANDLERLAR ---

async def start_handler(message: Message):
    # Qisqa va lo'nda salomlashish
    await message.answer("👋 Salom! Valyuta va Ob-havo botiga xush kelibsiz.", reply_markup=main_kb)

async def weather_ask(message: Message, is_subscription=False):
    user_id = message.from_user.id
    if is_subscription:
        user_states[user_id] = "sub_weather_loc"
        text = "🔔 Har kuni ob-havo ma'lumotini olish uchun <b>joylashuvni</b> yuboring:"
    else:
        user_states[user_id] = "get_weather_once"
        text = "Joylashuvingizni yuboring:"
        
    await message.answer(text, reply_markup=location_kb, parse_mode="HTML")

async def toggle_currency_sub(message: Message):
    user_id = message.from_user.id
    if user_id in subscriptions["currency"]:
        subscriptions["currency"].remove(user_id)
        msg = "❌ Valyuta kursi bekor qilindi."
    else:
        subscriptions["currency"].append(user_id)
        msg = "✅ Valyuta kursi yoqildi. Har kuni 07:00 da yuboriladi."
    
    save_subs(subscriptions)
    await message.answer(msg, reply_markup=main_kb)

async def location_handler(message: Message):
    user_id = message.from_user.id
    lat = message.location.latitude
    lon = message.location.longitude
    state = user_states.get(user_id)

    msg = await message.answer("🔄 Yuklanmoqda...")

    # Obuna uchun joylashuv
    if state == "sub_weather_loc":
        subscriptions["weather"][str(user_id)] = {"lat": lat, "lon": lon}
        save_subs(subscriptions)
        await bot.delete_message(message.chat.id, msg.message_id)
        await message.answer("✅ Ob-havo  faollashdi! Har kuni 07:00 da yuboriladi.", reply_markup=main_kb)
        user_states.pop(user_id, None)
    
    # Bir martalik ko'rish uchun
    else:
        weather_data = get_forecast(lat, lon)
        await bot.delete_message(message.chat.id, msg.message_id)
        if weather_data:
            await message.answer(format_weather_report(weather_data), reply_markup=main_kb, parse_mode="HTML")
        else:
            await message.answer("⚠️ Ob-havo ma'lumotini olishda xatolik yuz berdi. Qayta urinib ko'ring.", reply_markup=main_kb)
        # Stateni tozalash
        if user_id in user_states and user_states[user_id] == "get_weather_once":
            user_states.pop(user_id, None)

async def currency_rates(message: Message):
    text = get_currency_text() or "⚠️ Kurslarni yuklab bo'lmadi."
    await message.answer(text, reply_markup=main_kb)

async def calc_start(message: Message):
    text = message.text
    user_id = message.from_user.id
    
    # Agar bu funksiyaga noto'g'ri kirib qolsa, routerga o'tkazamiz
    if "➡️" not in text:
        return await text_router(message)

    if "USD ➡️ UZS" in text: user_states[user_id] = "usd_to_uzs"
    elif "UZS ➡️ USD" in text: user_states[user_id] = "uzs_to_usd"
    
    # "Bosh menyu" tugmasini chiqaramiz
    await message.answer(
        "Summani kiriting:", 
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🔙 Bosh menyu")]], 
            resize_keyboard=True
        )
    )
async def text_router(message: Message):
    text = message.text
    user_id = message.from_user.id

    # --- TUGMALAR VA NAVIGATSIYA ---
    if text == "🌤 Ob-havo": 
        return await weather_ask(message, is_subscription=False)
    
    # MATN TO'G'IRLANDI (Klaviaturadagi bilan bir xil bo'lishi kerak)
    if text == "🔔 Ob-havoni har kuni bilish": 
        return await weather_ask(message, is_subscription=True)
    
    if text == "💵 Valyuta": 
        return await currency_rates(message)
    
    # MATN TO'G'IRLANDI
    if text == "🔔 Valyutani kunlik bilish": 
        return await toggle_currency_sub(message)
    
    if text == "🔄 Ayirboshlash": 
        await message.answer("Yo'nalishni tanlang:", reply_markup=calc_kb)
        return
    
    # BOSH MENYU VA BEKOR QILISH LOGIKASI SHU YERGA QO'SHILDI
    if text == "🔙 Bekor qilish" or text == "🔙 Bosh menyu":
        user_states.pop(user_id, None) # Eski holatni o'chiramiz
        return await start_handler(message)

    # --- KALKULYATOR MANTIQI ---
    state = user_states.get(user_id)
    if state in ["usd_to_uzs", "uzs_to_usd"]:
        try:
            # Vergulni nuqtaga almashtiramiz (kalkulyator xato bermasligi uchun)
            amount = float(text.replace(",", "."))
            if not exchange_rates["USD"]: get_rates()
            
            rate = exchange_rates["USD"]
            if state == "usd_to_uzs":
                res = amount * rate
                t = f"🇺🇸 {amount:,.2f} USD = 🇺🇿 {res:,.2f} UZS"
            else:
                res = amount / rate
                t = f"🇺🇿 {amount:,.2f} UZS = 🇺🇸 {res:,.2f} USD"
            
            # Natijadan keyin yana hisoblashda qolish uchun
            await message.answer(t, reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔙 Bosh menyu")]], resize_keyboard=True))
        except ValueError:
            await message.answer("⚠️ Iltimos, faqat raqam kiriting (Masalan: 100 yoki 10.5)")

# --- WEB SERVER ---
async def health_check(request): return web.Response(text="Bot is running")

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
dp.message.register(location_handler, F.content_type == ContentType.LOCATION)
dp.message.register(calc_start, F.text.contains("➡️"))
dp.message.register(text_router)

async def main():
    # Orqa fon vazifasini ishga tushiramiz (loop)
    asyncio.create_task(daily_scheduler(bot))
    
    await asyncio.gather(
        start_web_server(),
        dp.start_polling(bot)
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass




