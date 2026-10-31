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

# Siz kiritgan modellar kaskadi
MODELS_CASCADE = [
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-pro-preview",
    "argon"
]

client = genai.Client(api_key=GEMINI_API_KEY)

# ----------------- AGENTLAR RO'YXATI VA DIRECTIVASI -----------------
ORCHESTRATOR_PROMPT = """Sen — Asoschining shaxsiy 'Chief of Staff' (Bosh Boshqaruvchi) agentisan. 
Majlis raisisan. Mutaxassislaring (Moliya, Karyera, Biznes, EdTech) bir-biri bilan qizg'in bahslashdi.
Sening vazifang: Majlisdagi bahslarni tahlil qilib, Asoschi uchun ortiqcha gap-so'zlarsiz, qat'iy va amaliy yakuniy qaror hamda qadam-baqadam harakat rejasini tasdiqlash."""

AGENTS = {
    "MOLIYA": "Sen — Qat'iy Bosh Hisobchisan. Har doim xarajatlarni qisqartirish, risklarni kamaytirish va pulni asrash tarafidursan. Boshqa agentlarning xomxayol va qimmat g'oyalariga e'tiroz bildirishdan tortinma. (3-4 gapda lo'nda fikr bildir).",
    "KARYERA": "Sen — Bank Karyerasi Mentorsan. Asoschining bankdagi asosiy ishi, obro'si, KPI va vaqt balansini himoya qilasan. Boshqa agentlarga uning vaqti cheklanganligini va bankdagi ishiga xalal bermaslik kerakligini eslatasan. (3-4 gapda lo'nda fikr bildir).",
    "BIZNES": "Sen — Jasur Biznes Strategisan. Katta daromad, yangi bozorlar va agressiv o'sish tarafdorisan. Moliya agentining haddan tashqari qo'rquviga va Karyeraning sekinlik haqidagi gaplariga e'tiroz bildirasan. (3-4 gapda lo'nda fikr bildir).",
    "EDTECH": "Sen — Zamonaviy EdTech PM san. Telegram Mini App orqali ingliz tili o'rgatish metodikasi va foydalanuvchilar qiziqishini himoya qilasan. Mahsulot tezroq chiqishi uchun texnik yechimlarni ilgari surasan. (3-4 gapda lo'nda fikr bildir)."
}

# ----------------- ISHONCHLI AI CHAQIRUVI -----------------
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

# ----------------- JONLI MUNOZARALI MAJLIS REJIMI -----------------
async def execute_live_board_debate(user_query: str, status_msg: types.Message):
    clean_text = user_query.strip().lower()
    short_words = ["salom", "shu yerdamisan", "qalesan", "kim bor", "bosh agent", "assalomu alaykum", "alo"]
    
    if any(sw in clean_text for sw in short_words) and len(clean_text.split()) <= 4:
        quick_resp = await call_gemini_safe(
            contents=user_query,
            system_instruction=ORCHESTRATOR_PROMPT + "\nFoydalanuvchiga hurmat bilan javob ber, majlis zali to'liq yig'ilganini bildir.",
            temperature=0.3
        )
        await status_msg.edit_text(f"👑 <b>Bosh Boshqaruvchi:</b>\n\n{clean_html(quick_resp)}")
        return

    safe_query = clean_html(user_query)
    
    # 1-BOSQICH: Dastlabki fikrlar
    await status_msg.edit_text(
        f"🗣 <b>Topshiriq:</b> «{safe_query}»\n\n"
        f"🏛 <b>1-BOSQICH: Mutaxassislar o'z takliflarini o'rtaga tashlamoqda...</b>"
    )

    tasks_round1 = [
        call_gemini_safe(
            contents=f"Asoschi topshirig'i: '{user_query}'. O'z sohang bo'yicha dastlabki taklifingni bildir.",
            system_instruction=AGENTS[name],
            temperature=0.5
        )
        for name in AGENTS.keys()
    ]
    round1_res = await asyncio.gather(*tasks_round1, return_exceptions=True)
    round1_dict = {name: clean_html(str(res)) for name, res in zip(AGENTS.keys(), round1_res)}

    # 2-BOSQICH: O'zaro munozara va bahs (bir-biriga e'tiroz bildirish)
    await status_msg.edit_text(
        f"🗣 <b>Topshiriq:</b> «{safe_query}»\n\n"
        f"🔥 <b>2-BOSQICH: Majlis zalida qizg'in bahs ketmoqda!</b>\n"
        f"<i>Mutaxassislar bir-birining taklifiga e'tiroz bildirmoqda...</i>"
    )

    summary_r1 = "\n".join([f"[{k} taklifi]: {v}" for k, v in round1_dict.items()])

    tasks_round2 = [
        call_gemini_safe(
            contents=(
                f"Asoschi topshirig'i: '{user_query}'\n\n"
                f"Boshqa hamkasblaringning takliflari:\n{summary_r1}\n\n"
                f"Sen {name}san. Hamkasblaringning (ayniqsa senga zid bo'lganlarining) fikrlariga bevosita murojaat qilib, o'z e'tirozingni yoki taklifingni qat'iy bildir. Masalan, Moliya Biznesga, Karyera esa vaqtga e'tiroz bildirsin. (3-4 gapda jonli bahslash)."
            ),
            system_instruction=AGENTS[name],
            temperature=0.6
        )
        for name in AGENTS.keys()
    ]
    round2_res = await asyncio.gather(*tasks_round2, return_exceptions=True)
    round2_dict = {name: clean_html(str(res)) for name, res in zip(AGENTS.keys(), round2_res)}

    # 3-BOSQICH: Bosh Boshqaruvchi yakuniy qarori
    await status_msg.edit_text(
        f"🗣 <b>Topshiriq:</b> «{safe_query}»\n\n"
        f"⚖️ <b>Bahs yakunlandi! Rais yakuniy hukm va rejani tuzmoqda...</b>"
    )

    debate_log = "\n\n".join([
        f"[{k} AGENTI]:\n• Dastlabki fikr: {round1_dict[k]}\n• Bahsdagi e'tirozi: {round2_dict[k]}"
        for k in AGENTS.keys()
    ])

    final_decision_raw = await call_gemini_safe(
        contents=(
            f"Topshiriq: '{user_query}'\n\n"
            f"Kengashdagi o'zaro bahs va e'tirozlar tafsiloti:\n{debate_log}\n\n"
            f"Sen Rais sifatida ushbu barcha e'tiroz va xatarlarni (moliyaviy xarajat, bankdagi ish vaqti, biznes foydasi) hisobga olib, Asoschi uchun qat'iy xulosa va 3-4 bosqichli amaliy qadamlar rejasini ber."
        ),
        system_instruction=ORCHESTRATOR_PROMPT,
        temperature=0.3
    )
    final_decision = clean_html(final_decision_raw)

    # Yakuniy hisobotni Telegram formatiga yig'ish
    full_report = (
        f"🏛 <b>XOLDING KENGASHI: JONLI MAJLIS VA MUNOZARA</b>\n\n"
        f"🎯 <b>Mavzu:</b> «{safe_query}»\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💬 <b>1-BOSQICH: DASTLABKI TAKLIFLAR</b>\n\n"
        f"💰 <b>Moliya:</b> {round1_dict['MOLIYA']}\n\n"
        f"📈 <b>Biznes:</b> {round1_dict['BIZNES']}\n\n"
        f"🏦 <b>Karyera:</b> {round1_dict['KARYERA']}\n\n"
        f"🎓 <b>EdTech:</b> {round1_dict['EDTECH']}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔥 <b>2-BOSQICH: O'ZARO E'TIROZ VA BAHS</b>\n\n"
        f"💰 <b>Moliya e'tirozi:</b> {round2_dict['MOLIYA']}\n\n"
        f"📈 <b>Biznes javobi:</b> {round2_dict['BIZNES']}\n\n"
        f"🏦 <b>Karyera ogohlantirishi:</b> {round2_dict['KARYERA']}\n\n"
        f"🎓 <b>EdTech yechimi:</b> {round2_dict['EDTECH']}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👑 <b>BOSH BOSHQARUVCHI (CHIEF OF STAFF) QARORI:</b>\n\n{final_decision}"
    )

    await status_msg.delete()

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
    if ADMIN_ID and str(message.from_user.id) != ADMIN_ID:
        await message.answer("Kechirasiz, bu shaxsiy xolding boti.")
        return
    await message.answer(
        "<b>Assalomu alaykum, Hurmatli Asoschi! 👑</b>\n\n"
        "Kengash a'zolari majlislar zalida to'plandi.\n"
        "Topshiriq bering (yozma yoki ovozli) — agentlar o'rtasida jonli bahs-munozara o'tkazib, yakuniy qarorni taqdim etamiz!"
    )

@dp.message(F.text)
async def handle_text(message: types.Message):
    if ADMIN_ID and str(message.from_user.id) != ADMIN_ID:
        return
    status_msg = await message.answer("⏳ <i>Majlis zalida eshiklar yopilmoqda...</i>")
    try:
        await execute_live_board_debate(message.text, status_msg)
    except Exception as e:
        await status_msg.edit_text(f"⚠️ Xatolik yuz berdi: {clean_html(str(e))}")

@dp.message(F.voice)
async def handle_voice(message: types.Message):
    if ADMIN_ID and str(message.from_user.id) != ADMIN_ID:
        return
    status_msg = await message.answer("🎤 <i>Ovozli xabaringiz majlis zalida eshitilmoqda...</i>")
    try:
        voice_file = await bot.get_file(message.voice.file_id)
        voice_io = io.BytesIO()
        await bot.download_file(voice_file.file_path, voice_io)
        voice_bytes = voice_io.getvalue()

        user_query = await transcribe_voice(voice_bytes)
        await execute_live_board_debate(user_query, status_msg)
    except Exception as e:
        await status_msg.edit_text(f"⚠️ Ovozli xabarni tahlil qilishda xatolik: {clean_html(str(e))}")

# ----------------- RENDER WEB SERVER -----------------
async def start_web_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Shahzod Holding Bot faol!"))
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
