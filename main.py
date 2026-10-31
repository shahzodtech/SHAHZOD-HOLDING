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

# Kalitlar
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
ADMIN_ID = os.getenv("ADMIN_ID", "").strip()

# Model zaxira zanjiri (biri band bo'lsa yoki 404 bersa, avtomat keyingisiga o'tadi)
MODELS_CASCADE = [
    "gemini-3.8-flash",
    "gemini-3.1-pro-preview",
    "gemini-2.5-flash",
    "gemini-2.0-flash"
]

client = genai.Client(api_key=GEMINI_API_KEY)

# ----------------- AGENTLAR DIREKTIVASI -----------------
ORCHESTRATOR_PROMPT = """Sen — foydalanuvchining shaxsiy 'Chief of Staff' (Bosh Boshqaruvchi) agentisan. 
Foydalanuvchi — bank xodimi va o'zining shaxsiy loyihalarining asoschisi.
Qo'lingda 4 ta mutaxassis bor: MOLIYA, KARYERA, BIZNES, EDTECH.
Vazifang: Agentlar fikrlarini umumlashtirib, foydalanuvchiga amaliy, lo'nda va qat'iy yakuniy qaror hamda qadamlar rejasini berish. Javobda markdown (** yoki #) ishlatma, oddiy va tushunarli matnda yoz."""

AGENTS = {
    "MOLIYA": "Sen — Bosh Hisobchisan. Byudjet, daromad/xarajat, risklar va moliyaviy rentabellikni raqamlar bilan qisqa (maksimum 4-5 gapda) va aniq tahlil qil.",
    "KARYERA": "Sen — Bank Karyerasi Mentorsan. Bankdagi asosiy ish o'rni, martaba ko'tarilishi, KPI va vaqt balansi bo'yicha qisqa (maksimum 4-5 gapda) va aniq baho ber.",
    "BIZNES": "Sen — Biznes Strategisan. Bankdan tashqari yangi bizneslar, startaplar, bozor imkoniyatlari va risklarni qisqa (maksimum 4-5 gapda) va aniq tahlil qil.",
    "EDTECH": "Sen — EdTech Mahsulot Menejerisan. Ingliz tili o'rgatuvchi Telegram Mini App ilovasi metodikasi, auditoriyasi va funksiyalariga qisqa (maksimum 4-5 gapda) javob ber."
}

# ----------------- ISHONCHLI AI CHAQIRUVI (FAILSAFE ENGINE) -----------------
async def call_gemini_failsafe(contents, system_instruction=None, temperature=0.4) -> str:
    config = {"temperature": temperature}
    if system_instruction:
        config["system_instruction"] = system_instruction

    last_exception = None
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
            except Exception as exc:
                last_exception = exc
                err_text = str(exc).lower()
                logging.warning(f"Model {model_name} (urinish {attempt+1}) xatosi: {err_text}")
                
                if "404" in err_text or "not_found" in err_text or "not supported" in err_text:
                    break
                await asyncio.sleep(2)
                
    raise last_exception

async def transcribe_voice_safe(audio_bytes: bytes) -> str:
    audio_part = genai_types.Part.from_bytes(
        data=audio_bytes,
        mime_type="audio/ogg"
    )
    prompt = "Ushbu ovozli xabarda aytilgan barcha so'zlarni aynan o'zbek tilida matn holida yozib ber. Boshqa hech qanday izoh qo'shma."
    return await call_gemini_failsafe(contents=[prompt, audio_part], temperature=0.1)

def clean_html(text: str) -> str:
    """Telegram HTML rejimida xato bermasligi uchun belgilarni tozalash"""
    cleaned = text.replace("**", "").replace("##", "")
    return html.escape(cleaned)

# ----------------- MAJLISNI BOSHQARISH VA HISOBOT -----------------
async def execute_board_meeting(user_query: str, status_msg: types.Message):
    clean_text = user_query.strip().lower()
    short_words = ["salom", "shu yerdamisan", "qalesan", "kim bor", "bosh agent", "assalomu alaykum", "alo"]
    
    if any(sw in clean_text for sw in short_words) and len(clean_text.split()) <= 5:
        quick_resp = await call_gemini_failsafe(
            contents=user_query,
            system_instruction=ORCHESTRATOR_PROMPT + "\nFoydalanuvchiga hurmat bilan lo'nda javob qaytar, barcha 4 ta agent majlisga shay ekanini bildir.",
            temperature=0.3
        )
        await status_msg.edit_text(f"👑 <b>Bosh Boshqaruvchi:</b>\n\n{clean_html(quick_resp)}")
        return

    safe_query = clean_html(user_query)
    await status_msg.edit_text(
        f"🗣 <b>Topshiriq qabul qilindi:</b>\n«{safe_query}»\n\n"
        f"🏛 <b>Majlis chaqirildi!</b>\n"
        f"⏳ <i>Moliya, Karyera, Biznes va EdTech agentlari o'z xulosalarini tayyorlamoqda...</i>"
    )

    agent_names = list(AGENTS.keys())
    tasks = [
        call_gemini_failsafe(contents=user_query, system_instruction=AGENTS[name], temperature=0.4)
        for name in agent_names
    ]
    
    responses = await asyncio.gather(*tasks, return_exceptions=True)
    
    meeting_results = {}
    for name, resp in zip(agent_names, responses):
        if isinstance(resp, Exception):
            meeting_results[name] = f"⚠️ Vaqtinchalik javob bera olmadi ({clean_html(str(resp)[:50])})"
        else:
            meeting_results[name] = clean_html(resp)

    await status_msg.edit_text(
        f"🗣 <b>Topshiriq:</b> «{safe_query}»\n\n"
        f"✅ <b>Barcha 4 ta agent fikr bildirdi!</b>\n"
        f"👑 <i>Bosh Boshqaruvchi yakuniy qarorni shakllantirmoqda...</i>"
    )

    ctx = f"Asoschi topshirig'i: {user_query}\n\nAgentlar hisobotlari:\n" + "\n\n".join(
        [f"[{k} AGENTI]:\n{v}" for k, v in meeting_results.items()]
    )
    final_decision_raw = await call_gemini_failsafe(
        contents=f"{ctx}\n\nBarcha agentlarning fikrlarini tahlil qilib, Asoschiga aniq, qadam-baqadam harakatlar rejasini va yakuniy xulosani taqdim et.",
        system_instruction=ORCHESTRATOR_PROMPT,
        temperature=0.3
    )
    final_decision = clean_html(final_decision_raw)

    full_report = (
        f"🏛 <b>XOLDING KENGASHI MAJLISI BAYONI</b>\n\n"
        f"🎯 <b>Kun tartibidagi masala:</b>\n«{safe_query}»\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 <b>MOLIYA AGENTI (Bosh Hisobchi):</b>\n{meeting_results['MOLIYA']}\n\n"
        f"🏦 <b>KARYERA AGENTI (Bank Mentori):</b>\n{meeting_results['KARYERA']}\n\n"
        f"📈 <b>BIZNES AGENTI (Strateg):</b>\n{meeting_results['BIZNES']}\n\n"
        f"🎓 <b>EDTECH AGENTI (PM):</b>\n{meeting_results['EDTECH']}\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👑 <b>BOSH BOSHQARUVCHI QARORI:</b>\n\n{final_decision}"
    )

    await status_msg.delete()
    
    if len(full_report) > 4000:
        for i in range(0, len(full_report), 4000):
            await status_msg.chat.send_message(full_report[i:i+4000])
    else:
        await status_msg.chat.send_message(full_report)

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
        "Xolding majlislar zali to'liq sozlandi.\n"
        "Menga <b>yozma</b> yoki <b>ovozli xabar (golos)</b> yuboring — 4 ta agentingiz (Moliya, Karyera, Biznes, EdTech) majlis o'tkazib, batafsil hisobot beradi!"
    )

@dp.message(F.text)
async def handle_text(message: types.Message):
    if ADMIN_ID and str(message.from_user.id) != ADMIN_ID:
        return
    status_msg = await message.answer("⏳ <i>Topshiriq qabul qilindi, tahlil boshlanmoqda...</i>")
    try:
        await execute_board_meeting(message.text, status_msg)
    except Exception as e:
        await status_msg.edit_text(f"⚠️ Xatolik yuz berdi: {clean_html(str(e))}")

@dp.message(F.voice)
async def handle_voice(message: types.Message):
    if ADMIN_ID and str(message.from_user.id) != ADMIN_ID:
        return
    status_msg = await message.answer("🎤 <i>Ovozli xabaringiz tinglanmoqda...</i>")
    try:
        voice_file = await bot.get_file(message.voice.file_id)
        voice_io = io.BytesIO()
        await bot.download_file(voice_file.file_path, voice_io)
        voice_bytes = voice_io.getvalue()

        user_query = await transcribe_voice_safe(voice_bytes)
        await execute_board_meeting(user_query, status_msg)
    except Exception as e:
        await status_msg.edit_text(f"⚠️ Ovozli xabarni o'qishda xatolik: {clean_html(str(e))}")

# ----------------- RENDER PORT SERVERI -----------------
async def start_web_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Shahzod Holding Bot 24/7 ishlamoqda!"))
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Web server port {port} da ishga tushdi.")

async def main():
    await start_web_server()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
