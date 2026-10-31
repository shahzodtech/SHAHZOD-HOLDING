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

# ----------------- AGENTLAR RO'YXATI VA PROMPTLAR -----------------
ORCHESTRATOR_PROMPT = """Sen — Asoschining shaxsiy 'Chief of Staff' (Bosh Boshqaruvchi) agentisan va majlis raisisan.
Vazifang: Agentlar munozarasini tahlil qilib, Asoschi uchun qat'iy xulosa va 3-4 bosqichli amaliy qadamlar rejasini taqdim etish."""

AGENTS = {
    "MOLIYA": {
        "title": "💰 MOLIYA AGENTI (Bosh Hisobchi)",
        "prompt": "Sen — Qat'iy Bosh Hisobchisan. Xarajatlarni tejash, rentabellik va moliyaviy risklarni hisoblashga javob berasan. Fikringni 3-4 ta lo'nda jumlada bildir."
    },
    "BIZNES": {
        "title": "📈 BIZNES AGENTI (Biznes Strateg)",
        "prompt": "Sen — Jasur Biznes Strategisan. Katta daromad, yangi bozorlar va tezkor o'sish tarafdorisan. Fikringni 3-4 ta lo'nda jumlada bildir."
    },
    "KARYERA": {
        "title": "🏦 KARYERA AGENTI (Bank Mentori)",
        "prompt": "Sen — Bank Karyerasi Mentorsan. Asoschining bankdagi asosiy ishi, KPI, obro'si va shaxsiy vaqtini himoya qilasan. Fikringni 3-4 ta lo'nda jumlada bildir."
    },
    "EDTECH": {
        "title": "🎓 EDTECH AGENTI (Mahsulot Menejeri)",
        "prompt": "Sen — EdTech PM san. Telegram Mini App orqali ingliz tili o'rgatish metodikasi, konversiya va qulaylik tarafdorisan. Fikringni 3-4 ta lo'nda jumlada bildir."
    }
}

# ----------------- ISHONCHLI AI FUNKSIYASI -----------------
async def call_gemini_safe(contents, system_instruction=None, temperature=0.5) -> str:
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

# ----------------- JONLI, KETMA-KET XABARLI MAJLIS -----------------
async def execute_live_board_debate(user_query: str, chat_id: int):
    clean_text = user_query.strip().lower()
    short_words = ["salom", "shu yerdamisan", "qalesan", "kim bor", "bosh agent", "assalomu alaykum", "alo"]
    
    # Qisqa salomlashuv
    if any(sw in clean_text for sw in short_words) and len(clean_text.split()) <= 4:
        quick_resp = await call_gemini_safe(
            contents=user_query,
            system_instruction=ORCHESTRATOR_PROMPT + "\nFoydalanuvchiga hurmat bilan lo'nda javob qaytar, barcha 4 ta agent majlisga shay ekanini bildir.",
            temperature=0.3
        )
        await bot.send_message(chat_id, f"👑 <b>Bosh Boshqaruvchi:</b>\n\n{clean_html(quick_resp)}")
        return

    safe_query = clean_html(user_query)
    
    # Majlis boshlanishi xabari
    await bot.send_message(
        chat_id,
        f"🏛 <b>XOLDING KENGASHI MAJLISI BOSHLANDI</b>\n\n"
        f"🎯 <b>Kun tartibi:</b> «{safe_query}»\n\n"
        f"<i>Bosh Boshqaruvchi majlisni ochiq deb e'lon qildi. So'z navbati mutaxassislarga berilmoqda...</i>"
    )

    round1_dict = {}

    # 1-RAUND: Har bir agent o'z taklifini alohida xabar qilib yozadi
    for key, data in AGENTS.items():
        resp = await call_gemini_safe(
            contents=f"Asoschi topshirig'i: '{user_query}'. O'z yo'nalishing bo'yicha aniq, lo'nda dastlabki taklifingni bildir.",
            system_instruction=data["prompt"],
            temperature=0.5
        )
        round1_dict[key] = resp
        msg = f"<b>{data['title']}:</b>\n\n{clean_html(resp)}"
        await bot.send_message(chat_id, msg)
        await asyncio.sleep(0.5)

    # 2-RAUND: O'zaro bahs va e'tirozlar
    await bot.send_message(
        chat_id,
        "🔥 <b>MAJLIS QIZIMOQDA: O'zaro e'tiroz va bahs-munozara boshlandi!</b>"
    )

    summary_r1 = "\n\n".join([f"[{k} taklifi]: {v}" for k, v in round1_dict.items()])

    round2_dict = {}
    for key, data in AGENTS.items():
        resp = await call_gemini_safe(
            contents=(
                f"Asoschi topshirig'i: '{user_query}'\n\n"
                f"Hamkasblaringning takliflari:\n{summary_r1}\n\n"
                f"Sen {key}san. Boshqa agentlarning (ayniqsa fikri to'g'ri kelmayotganlarning) gapiga to'g'ridan-to'g'ri e'tiroz bildir yoki taklifingni qat'iy himoya qil. 3-4 jumlada bahslash."
            ),
            system_instruction=data["prompt"],
            temperature=0.6
        )
        round2_dict[key] = resp
        msg = f"💬 <b>{data['title']} (e'tiroz/javob):</b>\n\n{clean_html(resp)}"
        await bot.send_message(chat_id, msg)
        await asyncio.sleep(0.5)

    # 3-RAUND: Bosh Boshqaruvchi yakuniy qarori
    debate_log = "\n\n".join([
        f"[{k} AGENTI]:\n• Dastlabki fikr: {round1_dict[k]}\n• Munozaradagi e'tirozi: {round2_dict[k]}"
        for k in AGENTS.keys()
    ])

    final_decision_raw = await call_gemini_safe(
        contents=(
            f"Topshiriq: '{user_query}'\n\n"
            f"Majlisdagi barcha bahslar va e'tirozlar:\n{debate_log}\n\n"
            f"Sen Rais sifatida ushbu barcha e'tiroz va risklarni (xarajat, bank ishi, daromad) hisobga olib, Asoschi uchun aniq qadam-baqadam reja va qat'iy yakuniy qarorni tasdiqla."
        ),
        system_instruction=ORCHESTRATOR_PROMPT,
        temperature=0.3
    )

    final_msg = (
        f"👑 <b>BOSH BOSHQARUVCHI (CHIEF OF STAFF) YAKUNIY QARORI:</b>\n\n"
        f"{clean_html(final_decision_raw)}"
    )
    await bot.send_message(chat_id, final_msg)

# ----------------- TELEGRAM BOT -----------------
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

@dp.message(CommandStart())
async def handle_start(message: types.Message):
    if ADMIN_ID and str(message.from_user.id)
