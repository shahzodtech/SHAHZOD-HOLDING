import os
import io
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

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
ADMIN_ID = os.getenv("ADMIN_ID", "")
PRIMARY_MODEL = "gemini-3.8-flash"

client = genai.Client(api_key=GEMINI_API_KEY)

# ----------------- AGENTLAR KO'RSATMALARI -----------------
ORCHESTRATOR_PROMPT = """Sen — foydalanuvchining shaxsiy 'Chief of Staff' (Bosh Boshqaruvchi) agentisan. 
Foydalanuvchi — bank xodimi va o'zining shaxsiy loyihalarining asoschisi.
Qo'lingda 4 ta mutaxassis bor: MOLIYA, KARYERA, BIZNES, EDTECH.
Agentlarning fikrlarini umumlashtirib, aniq harakatlar rejasi va xulosani ber."""

AGENTS = {
    "MOLIYA": "Sen — Bosh Hisobchisan. Byudjet, daromad/xarajat, risklar va moliyaviy rentabellikni raqamlar bilan bahola.",
    "KARYERA": "Sen — Bank Karyerasi Mentorsan. Bankdagi asosiy ish, o'sish, KPI va vaqt balansi bo'yicha baho ber.",
    "BIZNES": "Sen — Biznes Strategisan. Bankdan tashqari yangi bizneslar, startaplar va bozor imkoniyatlarini bahola.",
    "EDTECH": "Sen — EdTech PM san. Ingliz tili o'rgatuvchi Telegram Mini App ilovasi metodikasi va funksiyalariga javob ber."
}

async def call_gemini_safe(contents, system_instruction=None, temperature=0.4):
    config = {"temperature": temperature}
    if system_instruction:
        config["system_instruction"] = system_instruction

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=PRIMARY_MODEL,
                contents=contents,
                config=config
            )
            return response.text
        except Exception as e:
            if attempt == 2:
                raise e
            await asyncio.sleep(2)

async def transcribe_voice(audio_bytes: bytes) -> str:
    audio_part = genai_types.Part.from_bytes(
        data=audio_bytes,
        mime_type="audio/ogg"
    )
    prompt = "Ushbu ovozli xabarda aytilgan gaplarni aniq o'zbek tilida matn qilib yozib ber. Faqat matnni yoz, ortiqcha izoh qo'shma."
    res = await call_gemini_safe(contents=[prompt, audio_part], temperature=0.1)
    return res.strip()

# ----------------- MAJLIS O'TKAZISH MANTIQI -----------------
async def run_meeting(user_query: str, status_msg: types.Message):
    await status_msg.edit_text(f"🗣 <b>Sizning topshirig'ingiz:</b>\n«{user_query}»\n\n🏛 <b>Majlis boshlanmoqda...</b>")
    
    meeting_results = {}
    
    # 4 ta agentni parallel ravishda ishga tushirish (tez ishlashi uchun)
    tasks = []
    agent_names = list(AGENTS.keys())
    
    for name in agent_names:
        tasks.append(call_gemini_safe(contents=user_query, system_instruction=AGENTS[name], temperature=0.4))
    
    await status_msg.edit_text(
        f"🗣 <b>Topshiriq:</b> «{user_query}»\n\n"
        "🏛 <b>Majlis zalida muhokama ketmoqda:</b>\n"
        "⏳ <i>Moliya, Karyera, Biznes va EdTech agentlari tahlil qilmoqda...</i>"
    )
    
    responses = await asyncio.gather(*tasks, return_exceptions=True)
    
    for name, resp in zip(agent_names, responses):
        if isinstance(resp, Exception):
            meeting_results[name] = "Tahlil jarayonida xatolik yuz berdi."
        else:
            meeting_results[name] = resp

    # Jonli hisobot matnini shakllantirish (yashirmasdan ochiq ko'rsatish)
    await status_msg.edit_text("🏛 <b>Majlis yakunlandi! Bosh Boshqaruvchi yakuniy xulosani tayyorlamoqda...</b>")

    ctx = f"Topshiriq: {user_query}\n" + "\n".join([f"[{k}]: {v}" for k, v in meeting_results.items()])
    final_decision = await call_gemini_safe(
        contents=f"{ctx}\n\nUshbu agentlar fikrlaridan kelib chiqib, Asoschi uchun aniq qadamlar va yakuniy qaror ber.",
        system_instruction=ORCHESTRATOR_PROMPT,
        temperature=0.3
    )

    full_report = (
        f"🏛 <b>XOLDING KENGASHI MAJLISI BAYONI</b>\n\n"
        f"🎯 <b>Mavzu:</b> {user_query}\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔹 <b>MOLIYA (Bosh Hisobchi):</b>\n{meeting_results['MOLIYA']}\n\n"
        f"🔹 <b>KARYERA (Bank Mentori):</b>\n{meeting_results['KARYERA']}\n\n"
        f"🔹 <b>BIZNES (Biznes Strateg):</b>\n{meeting_results['BIZNES']}\n\n"
        f"🔹 <b>EDTECH (Mahsulot Menejeri):</b>\n{meeting_results['EDTECH']}\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👑 <b>BOSH BOSHQARUVCHI (CHIEF OF STAFF) QARORI:</b>\n\n{final_decision}"
    )

    await status_msg.delete()
    
    # Telegram xabar limiti (4096 belgi) dan oshsa bo'lib yuborish
    if len(full_report) > 4000:
        for i in range(0, len(full_report), 4000):
            await status_msg.chat.send_message(full_report[i:i+4000])
    else:
        await status_msg.chat.send_message(full_report)

# ----------------- TELEGRAM BOT -----------------
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

@dp.message(CommandStart())
async def handle_start(message: types.Message):
    if ADMIN_ID and str(message.from_user.id) != str(ADMIN_ID).strip():
        await message.answer("Kechirasiz, bu shaxsiy xolding boti.")
        return
    await message.answer(
        "<b>Assalomu alaykum, Hurmatli Asoschi! 👑</b>\n\n"
        "Xolding majlislar zali tayyor. Ovozli xabar yoki yozma topshiriq yuboring — 4 ta mutaxassis o'zaro muhokama qilib, majlis hisobotini to'liq ko'rsatadi!"
    )

@dp.message(F.text)
async def handle_text(message: types.Message):
    if ADMIN_ID and str(message.from_user.id) != str(ADMIN_ID).strip():
        return
    status_msg = await message.answer("⏳ <i>Majlis chaqirilmoqda...</i>")
    try:
        await run_meeting(message.text, status_msg)
    except Exception as e:
        await status_msg.edit_text(f"⚠️ Xatolik yuz berdi: {str(e)}")

@dp.message(F.voice)
async def handle_voice(message: types.Message):
    if ADMIN_ID and str(message.from_user.id) != str(ADMIN_ID).strip():
        return
    status_msg = await message.answer("🎤 <i>Ovozli xabaringiz eshitilmoqda...</i>")
    try:
        voice_file = await bot.get_file(message.voice.file_id)
        voice_io = io.BytesIO()
        await bot.download_file(voice_file.file_path, voice_io)
        voice_bytes = voice_io.getvalue()

        user_query = await transcribe_voice(voice_bytes)
        await run_meeting(user_query, status_msg)
    except Exception as e:
        await status_msg.edit_text(f"⚠️ Xatolik yuz berdi: {str(e)}")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot muvaffaqiyatli ishlamoqda!"))
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def main():
    await start_web_server()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
