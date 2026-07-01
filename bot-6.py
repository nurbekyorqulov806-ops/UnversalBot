# -*- coding: utf-8 -*-
"""
MULTI-BOT (aiogram versiyasi)
==============================
Funksiyalar: Video/MP3 yuklash, Ob-havo, Tarjimon, Admin aloqa, Statistika

O'rnatish:
    pip install aiogram
    pip install yt-dlp
    pip install deep-translator
    pip install requests

FFmpeg kompyuterga alohida o'rnatilgan bo'lishi kerak (video/mp3 uchun).
"""

import asyncio
import logging
import os
import re
import sqlite3
import time
from datetime import datetime

import requests
import yt_dlp
from deep_translator import GoogleTranslator

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    KeyboardButton,
)

# =========================================================
#                      SOZLAMALAR
# =========================================================

BOT_TOKEN = "8846416813:AAHftKVm22sf8XS222O3YA0TvGEz0cD7VO0"     # @BotFather'dan olgan token
ADMIN_ID =  7969924873                          # Sening Telegram ID'ing (@userinfobot orqali)


TEMP_DIR = "temp_files"
os.makedirs(TEMP_DIR, exist_ok=True)

DB_PATH = "stats.db"


WAITING_FEEDBACK = "waiting_feedback"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# =========================================================
#                  BAZA (STATISTIKA UCHUN)
# =========================================================

def db_connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            first_seen TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action_type TEXT,
            created_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ad_views (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def log_user(user_id: int, username: str, first_name: str):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if cur.fetchone() is None:
        cur.execute(
            "INSERT INTO users (user_id, username, first_name, first_seen) VALUES (?, ?, ?, ?)",
            (user_id, username, first_name, datetime.now().isoformat()),
        )
        conn.commit()
    conn.close()


def log_action(user_id: int, action_type: str):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO actions (user_id, action_type, created_at) VALUES (?, ?, ?)",
        (user_id, action_type, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def log_ad_view(user_id: int):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO ad_views (user_id, created_at) VALUES (?, ?)",
        (user_id, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_stats():
    conn = db_connect()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) as c FROM users")
    total_users = cur.fetchone()["c"]



    today = datetime.now().strftime("%Y-%m-%d")
    cur.execute("SELECT COUNT(*) as c FROM users WHERE first_seen LIKE ?", (f"{today}%",))
    today_new_users = cur.fetchone()["c"]

    cur.execute("SELECT action_type, COUNT(*) as c FROM actions GROUP BY action_type")
    by_type = cur.fetchall()

    cur.execute("""
        SELECT user_id, username, first_name, first_seen
        FROM users ORDER BY first_seen DESC LIMIT 10
    """)
    recent_users = cur.fetchall()

    conn.close()
    return {
        "total_users": total_users,
        "today_new_users": today_new_users,
        "by_type": by_type,
        "recent_users": recent_users,
    }


def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


# Foydalanuvchi holati (qaysi rejimda turgani)
USER_STATE = {}
USER_TRANSLATE_DIR = {}


# =========================================================
#                      KLAVIATURALAR
# =========================================================

def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎬 Link-Video", callback_data="mode_video"),
            InlineKeyboardButton(text="🎵 Link-MP3", callback_data="mode_mp3"),
        ],
        [
            InlineKeyboardButton(text="☁️ Ob-havo", callback_data="mode_weather"),
            InlineKeyboardButton(text="🌐 Tarjimon", callback_data="mode_translate"),
        ],
        [
            InlineKeyboardButton(text="📩 Admin", callback_data="mode_admin"),
        ],
    ])


def back_to_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Bosh menyu", callback_data="main_menu")]
    ])


def location_request_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Joylashuvni yuborish", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


TRANSLATE_DIRECTIONS = {
    "tr_en_ru": ("en", "ru", "Ingliz ➜ Rus"),
    "tr_en_uz": ("en", "uz", "Ingliz ➜ Uzbek"),
    "tr_uz_en": ("uz", "en", "Uzbek ➜ Ingliz"),
    "tr_uz_ru": ("uz", "ru", "Uzbek ➜ Rus"),
    "tr_ru_en": ("ru", "en", "Rus ➜ Ingliz"),
    "tr_ru_uz": ("ru", "uz", "Rus ➜ Uzbek"),
}


def translate_directions_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🇬🇧➜🇷🇺 Ingliz-Rus", callback_data="tr_en_ru"),
            InlineKeyboardButton(text="🇬🇧➜🇺🇿 Ingliz-Uzbek", callback_data="tr_en_uz"),
        ],
        [
            InlineKeyboardButton(text="🇺🇿➜🇬🇧 Uzbek-Ingliz", callback_data="tr_uz_en"),
            InlineKeyboardButton(text="🇺🇿➜🇷🇺 Uzbek-Rus", callback_data="tr_uz_ru"),
        ],
        [
            InlineKeyboardButton(text="🇷🇺➜🇬🇧 Rus-Ingliz", callback_data="tr_ru_en"),
            InlineKeyboardButton(text="🇷🇺➜🇺🇿 Rus-Uzbek", callback_data="tr_ru_uz"),
        ],
        [InlineKeyboardButton(text="⬅️ Bosh menyu", callback_data="main_menu")],
    ])




def is_valid_url(text: str) -> bool:
    return bool(re.match(r"^https?://", text.strip()))


# =========================================================
#                      BUYRUQLAR
# =========================================================

@dp.message(CommandStart())
async def start(message: Message):
    user = message.from_user
    log_user(user.id, user.username or "", user.first_name or "")
    USER_STATE.pop(user.id, None)

    text = (
        f"👋 Assalomu alaykum, <b>{user.first_name}</b>!\n\n"
        "Men ko'p funksiyali yordamchi botman 🤖\n\n"
        "Men bilan quyidagilarni qila olasiz:\n"
        "🎬 Video yuklab olish (YouTube, Instagram, TikTok)\n"
        "🎵 Videodan yoki linkdan MP3 ajratib olish\n"
        "☁️ Joylashuvingiz bo'yicha ob-havo ma'lumoti\n"
        "🌐 Ingliz-Rus-Uzbek tillari orasida tarjima\n\n"
        "Quyidagi menyudan kerakli bo'limni tanlang 👇"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=main_menu_keyboard())


@dp.message(Command("stats"))
async def stats_command(message: Message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return

    s = get_stats()

    type_lines = "".join(f"   • {row['action_type']}: {row['c']} marta\n" for row in s["by_type"]) or "   • Hali faollik bo'lmagan\n"

    recent_lines = ""
    for u in s["recent_users"]:
        uname = f"@{u['username']}" if u["username"] else "(username yo'q)"
        recent_lines += f"   • {u['first_name']} {uname} — ID: <code>{u['user_id']}</code>\n"
    if not recent_lines:
        recent_lines = "   • Hali foydalanuvchi yo'q\n"

    text = (
        "📊 <b>Bot statistikasi</b>\n\n"
        f"👥 Jami foydalanuvchilar: <b>{s['total_users']}</b>\n"
        f"🆕 Bugun qo'shilgan: <b>{s['today_new_users']}</b>\n"
        f"🗂 <b>Funksiyalar bo'yicha foydalanish:</b>\n{type_lines}\n"
        f"🆕 <b>Oxirgi 10 foydalanuvchi:</b>\n{recent_lines}"
    )
    await message.answer(text, parse_mode="HTML")


# =========================================================
#                  INLINE TUGMALAR (CALLBACKS)
# =========================================================

@dp.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery):
    USER_STATE.pop(callback.from_user.id, None)
    await callback.message.edit_text(
        "🏠 <b>Bosh menyu</b>\n\nKerakli bo'limni tanlang 👇",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )
    await callback.answer()


@dp.callback_query(F.data == "mode_video")
async def cb_mode_video(callback: CallbackQuery):
    user_id = callback.from_user.id
    USER_STATE[user_id] = "waiting_video_link"
    text = (
        "🎬 <b>Video yuklab olish</b>\n\n"
        "YouTube, Instagram yoki TikTok havolasini (link) yuboring — "
        "men videoni yuklab beraman.\n\n"
        "⚠️ Video hajmi 50 MB dan oshmasligi kerak."
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=back_to_menu_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "mode_mp3")
async def cb_mode_mp3(callback: CallbackQuery):
    user_id = callback.from_user.id
    USER_STATE[user_id] = "waiting_mp3_link"
    text = (
        "🎵 <b>MP3 ajratib olish</b>\n\n"
        "YouTube, Instagram yoki TikTok havolasini (link) yuboring — "
        "men shu videodan audio (MP3) ajratib beraman."
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=back_to_menu_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "mode_weather")
async def cb_mode_weather(callback: CallbackQuery):
    user_id = callback.from_user.id
    USER_STATE[user_id] = "waiting_location"
    await callback.message.edit_text(
        "☁️ <b>Ob-havo ma'lumoti</b>\n\nQuyidagi tugma orqali joylashuvingizni yuboring 👇",
        parse_mode="HTML",
    )
    await bot.send_message(
        chat_id=user_id,
        text="📍 Joylashuvni yuborish uchun pastdagi tugmani bosing:",
        reply_markup=location_request_keyboard(),
    )
    await callback.answer()


@dp.callback_query(F.data == "mode_translate")
async def cb_mode_translate(callback: CallbackQuery):
    await callback.message.edit_text(
        "🌐 <b>Tarjimon</b>\n\nQaysi tildan qaysi tilga o'girmoqchisiz?",
        parse_mode="HTML",
        reply_markup=translate_directions_keyboard(),
    )
    await callback.answer()


@dp.callback_query(F.data == "mode_admin")
async def cb_mode_admin(callback: CallbackQuery):
    user_id = callback.from_user.id
    USER_STATE[user_id] = WAITING_FEEDBACK
    await callback.message.edit_text(
        "📩 <b>Admin bilan aloqa</b>\n\n"
        "Fikrlaringiz, takliflaringiz yoki boshqa biror yordam kerak bo'lsa, "
        "shu yerga yozishingiz mumkin. Xabaringiz to'g'ridan-to'g'ri adminga yetadi.",
        parse_mode="HTML",
    )
    await bot.send_message(chat_id=user_id, text="✍️ Xabaringizni yozing:", reply_markup=ReplyKeyboardRemove())
    await callback.answer()


@dp.callback_query(F.data.in_(TRANSLATE_DIRECTIONS.keys()))
async def cb_translate_direction(callback: CallbackQuery):
    user_id = callback.from_user.id
    src, dest, label = TRANSLATE_DIRECTIONS[callback.data]
    USER_TRANSLATE_DIR[user_id] = (src, dest)
    USER_STATE[user_id] = "waiting_translate_text"
    text = (
        f"🌐 Yo'nalish: <b>{label}</b>\n\n"
        "Endi tarjima qilmoqchi bo'lgan so'z yoki gapni yozing.\n"
        "⚠️ Faqat matn qabul qilinadi, raqam emas."
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=back_to_menu_keyboard())
    await callback.answer()


# =========================================================
#                  OB-HAVO (Open-Meteo API)
# =========================================================

WEATHER_CODE_INFO = {
    0: ("☀️", "Ochiq, quyoshli"), 1: ("🌤️", "Asosan ochiq"),
    2: ("⛅", "Qisman bulutli"), 3: ("☁️", "Bulutli"),
    45: ("🌫️", "Tuman"), 48: ("🌫️", "Muzlovchi tuman"),
    51: ("🌦️", "Yengil yomg'ir (mayda)"), 53: ("🌦️", "O'rtacha yomg'ir (mayda)"),
    55: ("🌧️", "Kuchli yomg'ir (mayda)"), 61: ("🌧️", "Yengil yomg'ir"),
    63: ("🌧️", "O'rtacha yomg'ir"), 65: ("🌧️", "Kuchli yomg'ir"),
    71: ("🌨️", "Yengil qor"), 73: ("🌨️", "O'rtacha qor"),
    75: ("❄️", "Kuchli qor"), 80: ("🌦️", "Yomg'ir jalasi"),
    81: ("🌧️", "O'rtacha jala"), 82: ("⛈️", "Kuchli jala"),
    95: ("⛈️", "Chaqmoqli bo'ron"), 96: ("⛈️", "Do'l bilan bo'ron"),
    99: ("⛈️", "Kuchli do'l bilan bo'ron"),
}


@dp.message(F.location)
async def handle_location(message: Message):
    user = message.from_user
    user_id = user.id
    loc = message.location

    await message.answer("⏳ Ob-havo aniqlanmoqda...", reply_markup=ReplyKeyboardRemove())

    try:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": loc.latitude,
            "longitude": loc.longitude,
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,wind_speed_10m,weather_code",
            "timezone": "auto",
        }
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        current = data["current"]

        temp = round(current["temperature_2m"])
        feels = round(current["apparent_temperature"])
        humidity = current["relative_humidity_2m"]
        wind = current["wind_speed_10m"]
        code = current["weather_code"]
        emoji, description = WEATHER_CODE_INFO.get(code, ("🌡️", "Noma'lum holat"))

        text = (
            f"{emoji} <b>Hozirgi ob-havo</b>\n\n"
            f"🌡️ Harorat: <b>{temp}°C</b> (his qilinishi: {feels}°C)\n"
            f"📋 Holat: {description}\n"
            f"💧 Namlik: {humidity}%\n"
            f"💨 Shamol: {wind} km/soat\n"
        )
        log_action(user_id, "weather")
        await message.answer(text, parse_mode="HTML", reply_markup=main_menu_keyboard())


    except Exception:
        logger.exception("Ob-havo xatosi")
        await message.answer(
            "😔 Ob-havo ma'lumotini olishda xatolik yuz berdi. Birozdan keyin qayta urinib ko'ring.",
            reply_markup=main_menu_keyboard(),
        )

    USER_STATE.pop(user_id, None)


def translate_text(text: str, src: str, dest: str) -> str:
    return GoogleTranslator(source=src, target=dest).translate(text)


# =========================================================
#              VIDEO / MP3 YUKLAB OLISH (yt-dlp)
# =========================================================

async def download_and_send(message: Message, url: str, mode: str):
    """mode: 'video' yoki 'audio' - aynan sen tashlagan koddagi yondashuv asosida"""
    user_id = message.from_user.id
    USER_STATE.pop(user_id, None)

    status_msg = await message.answer("⏳ Yuklanmoqda, biroz kuting...")

    file_key = f"{user_id}_{int(time.time())}"
    output_template = os.path.join(TEMP_DIR, f"{file_key}.%(ext)s")

    try:
        if mode == "audio":
            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": output_template,
                "noplaylist": True,
                "quiet": True,
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
            }
        else:
            ydl_opts = {
                "format": "best[height<=480]/best",
                "outtmpl": output_template,
                "noplaylist": True,
                "quiet": True,
            }

        cookies_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
            "cookies.txt"
        )

        if "instagram.com" in url and os.path.exists(cookies_path):
            ydl_opts["cookiefile"] = cookies_path




        def run_download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                return info

        # yt-dlp sinxron (blocking) ishlaydi, shuning uchun alohida thread'da chaqiramiz
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, run_download)
        title = info.get("title", "fayl")
        uploader = info.get("uploader", "")

        produced_file = None
        for fname in os.listdir(TEMP_DIR):
            if fname.startswith(file_key):
                produced_file = os.path.join(TEMP_DIR, fname)
                break

        if not produced_file or not os.path.exists(produced_file):
            raise FileNotFoundError("Yuklangan fayl topilmadi")

        caption = f"✅ <b>{title}</b>"
        if uploader:
            caption += f"\n👤 {uploader}"

        file_input = FSInputFile(produced_file)
        if mode == "audio":
            await bot.send_audio(chat_id=user_id, audio=file_input, caption=caption, parse_mode="HTML")
        else:
            await bot.send_video(chat_id=user_id, video=file_input, caption=caption, parse_mode="HTML")

        log_action(user_id, f"download_{mode}")
        await status_msg.delete()

    except Exception as e:
        logger.exception("Yuklab olish xatosi")
        err_text = str(e)[:200]
        await status_msg.edit_text(
            f"❌ Xatolik: havola noto'g'ri, fayl juda katta, yoki sayt qo'llab-quvvatlanmaydi.\n\n"
            f"<code>{err_text}</code>",
            parse_mode="HTML",
        )
    finally:
        for fname in os.listdir(TEMP_DIR):
            if fname.startswith(file_key):
                try:
                    os.remove(os.path.join(TEMP_DIR, fname))
                except OSError:
                    pass


# =========================================================
#              MATN XABARLARI (tarjima, admin, link)
# =========================================================

@dp.message(F.text)
async def handle_text(message: Message):
    user = message.from_user
    user_id = user.id
    text = message.text.strip()
    state = USER_STATE.get(user_id)

    log_user(user_id, user.username or "", user.first_name or "")

    if state == WAITING_FEEDBACK:
        username_part = f"@{user.username}" if user.username else "(username yo'q)"
        admin_text = (
            f"📩 <b>Yangi xabar</b>\n\n"
            f"👤 Kimdan: {user.first_name} {username_part}\n"
            f"🆔 ID: <code>{user_id}</code>\n\n"
            f"💬 Xabar:\n{text}"
        )
        await bot.send_message(chat_id=ADMIN_ID, text=admin_text, parse_mode="HTML")
        log_action(user_id, "admin_feedback")
        await message.answer("✅ Jo'natildi! Xabaringiz adminga yetkazildi, rahmat.", reply_markup=main_menu_keyboard())
        USER_STATE.pop(user_id, None)
        return

    if state == "waiting_translate_text":
        if text.replace(" ", "").isdigit():
            await message.answer("⚠️ Faqat matn (so'z yoki gap) kiritish mumkin, raqam emas.")
            return

        src, dest = USER_TRANSLATE_DIR.get(user_id, ("en", "uz"))
        try:
            translated = translate_text(text, src, dest)
            if not translated or translated.strip().lower() == text.strip().lower():
                result_text = f"😔 Afsus, \"{text}\" so'zi/gap tarjimasi topilmadi."
            else:
                result_text = f"🌐 <b>{text}</b>\n➡️ {translated}"
            log_action(user_id, "translate")
        except Exception:
            logger.exception("Tarjima xatosi")
            result_text = "😔 Afsus, bu so'z/gap tarjima qilinmadi. Birozdan keyin qayta urinib ko'ring."

        await message.answer(result_text, parse_mode="HTML", reply_markup=back_to_menu_keyboard())
        return

    if state == "waiting_video_link":
        if not is_valid_url(text):
            await message.answer("⚠️ Iltimos, to'g'ri havola (link) yuboring.")
            return
        await download_and_send(message, text, mode="video")
        return

    if state == "waiting_mp3_link":
        if not is_valid_url(text):
            await message.answer("⚠️ Iltimos, to'g'ri havola (link) yuboring.")
            return
        await download_and_send(message, text, mode="audio")
        return

    await message.answer("Quyidagi menyudan kerakli bo'limni tanlang 👇", reply_markup=main_menu_keyboard())


# =========================================================
#                        MAIN
# =========================================================

async def main():
    init_db()
    logger.info("Bot ishga tushdi...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
