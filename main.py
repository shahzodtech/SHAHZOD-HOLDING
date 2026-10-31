import os
import io
import html
import asyncio
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv
from google import genai
from google.genai import types as genai_types

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
ADMIN_ID = os.getenv("ADMIN_ID", "").strip()

MODELS_CASCADE = [
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-pro-preview",
    "argon"
]

client = genai.Client(api_key=GEMINI_API_KEY)

# ----------------- MUSTAHKAM AI CHAQIRUVI -----------------
async def call_gemini_safe(contents, system_instruction=None, temperature=0.6) -> str:
    config = {"temperature": temperature}
    if system_instruction:
        config["system_instruction"] = system_instruction

    last_error = None
    for model_name in MODELS_CASCADE:
        for attempt in range(2):
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=model_name,
                    contents=contents,
                    config=config
                )
                if response and response.text:
                    return response.text.strip()
            except Exception as e:
                last_error = e
                err_text = str(e).lower()
                if "404" in err_text or "not_found" in err_text or "not available" in err_text:
                    break
                await asyncio.sleep(1)
    raise last_error

async def transcribe_voice(audio_bytes: bytes) -> str:
    audio_part = genai_types.Part.from_bytes(
        data=audio_bytes,
        mime_type="audio/ogg"
    )
    prompt = "Ushbu ovozli xabardagi gaplarni to'liq o'zbek tilida matn qilib yozib ber. Boshqa hech narsa qo'shma."
    return await call_gemini_safe(contents=[prompt, audio_part], temperature=0.1)

def clean_html(text: str) -> str:
    return html.escape(text.replace("**", "").replace("##", ""))

# ----------------- MAJLISNI SIMULYATSIYA QILISH -----------------
MEETING_SYSTEM_PROMPT = """Sen — Shahzod Holdingning 'Chief of Staff' (Bosh Boshqaruvchi) agentisan va boshqaruv kengashi raisisan.
Asoschi — bank xodimi va shaxsiy startap/biznes loyihalari bor.
Kengash a'zolari:
1. MOLIYA: Juda qat'iy bosh hisobchi, doim tejash, xarajatlarni qisqartirish, byudjet va risklarni sanaydi.
2. BIZNES: Jasur strateg, katta daromad, bozorga tez chiqish va tavakkalchilik tarafdori.
3. KARYERA: Bank mentori, Asoschining bankdagi asosiy ishiga xalal bermaslik, KPI, ish vaqti va martaba balansi bo'yicha qayg'uradi.
4. EDTECH: Telegram Mini App orqali ingliz tili o'rgatish metodikasi va mahsulotini himoya qiladi.

Sening vazifang — Asoschi bergan topshiriq bo'yicha majlis bayonini xuddi jonli teatr/munozara shaklida aniq ko'rsatib berish.
Javobing aynan quyidagi tuzilishda va belgilangan bo'limlar bilan bo'lishi SHART:

===1-RAUND: DASTLABKI TAKLIFLAR===
MOLIYA: (Moliya agentining taklifi va raqamlari)
BIZNES: (Biznes strategining taklifi)
KARYERA: (Karyera mentorining bank ishiga nisbatan ogohlantirishi)
EDTECH: (EdTech PM ning mahsulot bo'yicha taklifi)

===2-RAUND: O'ZARO MUNOZARA VA E'TIROZLAR===
MOLIYA E'TIROZI: (Moliya agenti Biznes yoki EdTech taklifiga xarajat tufayli keskin e'tiroz bildiradi)
BIZNES JAVOBI: (Biznes strateg Moliya va Karyeraning xavotirlariga qarshi dalillar keltiradi)
KARYERA OGOHLANTIRISHI: (Karyera agenti Asoschining bankdagi vaqti yetmasligini eslatadi)
EDTECH YECHIMI: (EdTech qanday qilib avtomatlashtirish orqali vaqtni tejash mumkinligini aytadi)

===3-RAUND: YAKUNIY QAROR===
BOSH BOSHQARUVCHI: (Rais sifatida barcha bahslarni jamlab, Asoschi uchun 3-4 bosqichli aniq va amaliy harakatlar rejasini e'lon qil)."""

async def run_live_board(user_query: str, chat_id: int):
    clean_text = user_query.strip().lower()
    short_words = ["salom", "shu yerdamisan", "qalesan", "kim bor", "bosh agent", "assalomu alaykum", "alo"]
    
    if any(sw in clean_text for sw in short_words) and len(clean_text.split()) <= 4:
        quick = await call_gemini_safe(
            contents=user_query,
            system_instruction="Sen Shahzod Holding Boshqaruvchisisan. Hurmat bilan, lo'nda qilib barcha agentlar majlisga shay ekanini bildir.",
            temperature=0.3
        )
        await bot.send_message(chat_id, f"👑 <b>Bosh Boshqaruvchi:</b>\n\n{clean_html(quick)}")
        return

    safe_q = clean_html(user_query)
    
    # 1. Boshlang'ich xabar
    status = await bot.send_message(
        chat_id,
        f"🏛 <b>XOLDING KENGASHI MAJLISI CHAQRILDI</b>\n\n"
        f"🎯 <b>Kun tartibidagi masala:</b>\n«{safe_q}»\n\n"
        f"⏳ <i>Bosh Boshqaruvchi, Moliya, Biznes, Karyera va EdTech mutaxassislari majlis stoliga yig'ilmoqda...</i>"
    )

    try:
        # Barcha majlis bitta to'liq va mustahkam so'rovda shakllantiriladi
        full_meeting = await call_gemini_safe(
            contents=f"Asoschi topshirig'i: '{user_query}'. Yuqoridagi ko'rsatma asosida to'liq majlis munozarasini yozib ber.",
            system_instruction=MEETING_SYSTEM_PROMPT,
            temperature=0.7
        )

        await status.delete()

        # Agar bloklarga bo'lingan bo'lsa, chiroyli qilib xabar-ba-xabar yuboramiz
        if "===1-RAUND" in full_meeting and "===2-RAUND" in full_meeting:
            parts = full_meeting.split("===")
            # Har bir qismni alohida yuborish
            for i in range(1, len(parts), 2):
                header = parts[i].strip()
                content = parts[i+1].strip() if i+1 < len(parts) else ""
                
                msg_text = f"📌 <b>{clean_html(header)}</b>\n\n{clean_html(content)}"
                await bot.send_message(chat_id, msg_text)
                await asyncio.sleep(0.8) # Xabarlar oraliq bilan tushishi uchun
        else:
            # Agar format bo'linmagan bo'lsa, to'liq hisobotni to'g'ridan-to'g'ri yuborish
            res_msg = f"🏛 <b>MAJLIS HISOBOTI:</b>\n\n{clean_html(full_meeting)}"
            if len(res_msg) > 4000:
                for chunk in range(0, len(res_msg), 4000):
                    await bot.send_message(chat_id, res_msg[chunk:chunk+4000])
            else:
                await bot.send_message(chat_id, res_msg)

    except Exception as e:
        await bot.send_message(chat_id, f"⚠️ Majlisni o'tkazishda xatolik yuz berdi: {clean_html(str(e))}")

# ----------------- TELEGRAM BOT HANDLERLARI -----------------
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

@dp.message(CommandStart())
async def handle_start(message: types.Message):
    if ADMIN_ID and str(message.from_user.id) != ADMIN_ID:
        await message.answer("Kechirasiz, bu shaxsiy xolding boti.")
        return
    await message.answer(
        "<b>Assalomu alaykum, Hurmatli Asoschi! 👑</b>\n\n"
        "Xolding boshqaruv kengashi shay.\n"
        "Menga yozma yoki ovozli topshiriq yuboring — agentlar o'rtasida to'liq munozara o'tkazib, hisobot beramiz!"
    )

@dp.message(F.text)
async def handle_text(message: types.Message):
    if ADMIN_ID and str(message.from_user.id) != ADMIN_ID:
        return
    await run_live_board(message.text, message.chat.id)

@dp.message(F.voice)
async def handle_voice(message: types.Message):
    if ADMIN_ID and str(message.from_user.id) != ADMIN_ID:
        return
    wait_msg = await message.answer("🎤 <i>Ovozli xabaringiz eshitilmoqda...</i>")
    try:
        voice_file = await bot.get_file(message.voice.file_id)
        voice_io = io.BytesIO()
        await bot.download_file(voice_file.file_path, voice_io)
        voice_bytes = voice_io.getvalue()

        user_query = await transcribe_voice(voice_bytes)
        await wait_msg.delete()
        await run_live_board(user_query, message.chat.id)
    except Exception as e:
        await wait_msg.edit_text(f"⚠️ Ovozni o'qishda xatolik: {clean_html(str(e))}")

# ----------------- RENDER WEB SERVER -----------------
async def start_web_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Shahzod Holding Bot ishlamoqda!"))
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def main():
    await start_web_server()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
