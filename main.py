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

# Kalitlar
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
ADMIN_ID = os.getenv("ADMIN_ID", "")
PRIMARY_MODEL = "gemini-2.5-flash"
FALLBACK_MODEL = "gemini-2.5-pro"

client = genai.Client(api_key=GEMINI_API_KEY)

# ----------------- AGENTLAR KO'RSATMALARI -----------------
ORCHESTRATOR_PROMPT = """Sen — foydalanuvchining shaxsiy 'Chief of Staff' (Bosh Boshqaruvchi) agentisan. 
Foydalanuvchi — bank xodimi va o'zining shaxsiy loyihalarining asoschisi.
Sening qo'lingda 4 ta mutaxassis bor: MOLIYA, KARYERA, BIZNES, EDTECH.
Vazifang: kelgan topshiriqni tahlil qilib, tegishli agentlar xulosasini birlashtirish va foydalanuvchiga yagona, lo'nda va amaliy qaror berish."""

MOLIYA_PROMPT = "Sen — Bosh Hisobchisan. Byudjet, daromad/xarajat, risklar va moliyaviy rentabellikni raqamlar bilan hisoblab berasan."
KARYERA_PROMPT = "Sen — Bank Karyerasi Mentorsan. Bankdagi o'sish, KPI bajarish va martaba ko'tarilishi bo'yicha maslahat berasan."
BIZNES_PROMPT = "Sen — Biznes Strategisan. Bankdan tashqari yangi bizneslar, startaplar va bozor imkoniyatlarini tahlil qilasan."
EDTECH_PROMPT = "Sen — EdTech PM san. 15-40 yoshlilar uchun ingliz tili o'rgatuvchi Telegram Mini App ilovasi metodikasi va funksiyalariga javob berasan."

# ----------------- AI BILAN ISHLASH (XATOLARNI USHLASH BILAN) -----------------
async def call_gemini_safe(contents, system_instruction=None, temperature=0.4):
    """503 yuklama xatosi berganda qayta urinish va zaxira modelga o'tish"""
    models_to_try = [PRIMARY_MODEL, FALLBACK_MODEL]
    config = {"temperature": temperature}
    if system_instruction:
        config["system_instruction"] = system_instruction

    last_error = None
    for model in models_to_try:
        for attempt in range(3):  # Har bir modelni 3 martagacha qayta sinab ko'radi
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config
                )
                return response.text
            except Exception as e:
                last_error = e
                err_str = str(e)
                if "503" in err_str or "UNAVAILABLE" in err_str:
                    await asyncio.sleep(2)  # 2 soniya kutib qayta urinadi
                    continue
                else:
                    break
    raise last_error

async def run_ai(prompt_system: str, text: str) -> str:
    return await call_gemini_safe(contents=text, system_instruction=prompt_system, temperature=0.4)

async def transcribe_voice(audio_bytes: bytes) -> str:
    audio_part = genai_types.Part.from_bytes(
        data=audio_bytes,
        mime_type="audio/ogg"
    )
    prompt = "Ushbu audio xabarda aytilgan gaplarni aynan o'zbek tilida matn qilib yozib ber. Faqat matnni o'zini yoz, boshqa hech narsa qo'shma."
    res_text = await call_gemini_safe(contents=[prompt, audio_part], temperature=0.1)
    return res_text.strip()

async def orchestrator_decide(user_query: str) -> list:
    router_prompt = f"""Quyidagi topshiriq uchun qaysi mutaxassislar kerak?
Topshiriq: "{user_query}"
Faqat kerakli kalit so'zlarni vergul bilan yoz (ortiqcha so'zsiz): MOLIYA, KARYERA, BIZNES, EDTECH"""
    res_text = await call_gemini_safe(contents=router_prompt, temperature=0.1)
    return [x.strip() for x in res_text.upper().split(",") if x.strip()]

# ----------------- ASOSIY ISHLOV BERISH MANTIQI -----------------
async def process_task(user_query: str, status_msg: types.Message):
    needed = await orchestrator_decide(user_query)
    if not needed:
        needed = ["BIZNES", "MOLIYA"]

    await status_msg.edit_text(f"<i>📋 Majlisga chaqirildi: <b>{', '.join(needed)}</b>...</i>")
    meeting = {}

    for ag in needed:
        if "MOLIYA" in ag:
            meeting["MOLIYA"] = await run_ai(MOLIYA_PROMPT, user_query)
        elif "KARYERA" in ag:
            meeting["KARYERA"] = await run_ai(KARYERA_PROMPT, user_query)
        elif "BIZNES" in ag:
            meeting["BIZNES"] = await run_ai(BIZNES_PROMPT, user_query)
        elif "EDTECH" in ag:
            meeting["EDTECH"] = await run_ai(EDTECH_PROMPT, user_query)

    await status_msg.edit_text("<i>👑 Yakuniy qaror tuzilmoqda...</i>")
    
    ctx = f"Topshiriq: {user_query}\n" + "\n".join([f"[{k}]: {v}" for k, v in meeting.items()])
    final_ans = await run_ai(ORCHESTRATOR_PROMPT, f"{ctx}\n\nFoydalanuvchiga yagona yakuniy reja va xulosa taqdim et.")

    details = "".join([f"\n\n🔹 <b>{k}:</b>\n{v}" for k, v in meeting.items()])
    res = f"<b>👑 BOSH BOSHQARUVCHI QARORI:</b>\n\n{final_ans}\n\n──────────────────\n<b>📝 MAJLIS TAFSILOTLARI:</b><tg-spoiler>{details}</tg-spoiler>"

    await status_msg.delete()
    if len(res) > 4000:
        for i in range(0, len(res), 4000):
            await status_msg.chat.send_message(res[i:i+4000])
    else:
        await status_msg.chat.send_message(res)

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
        "Barcha 4 ta agentingiz shay holatda.\n"
        "Menga yozma xabar yuborishingiz yoki <b>ovozli xabar (golos)</b> tashlashingiz mumkin. Majlis o'tkazib hisobot beraman!"
    )

@dp.message(F.text)
async def handle_text(message: types.Message):
    if ADMIN_ID and str(message.from_user.id) != str(ADMIN_ID).strip():
        return

    status_msg = await message.answer("<i>⚙️ Boshqaruvchi: Topshiriq o'rganilmoqda...</i>")
    try:
        await process_task(message.text, status_msg)
    except Exception as e:
        await status_msg.edit_text(f"⚠️ Xatolik: {str(e)}")

@dp.message(F.voice)
async def handle_voice(message: types.Message):
    if ADMIN_ID and str(message.from_user.id) != str(ADMIN_ID).strip():
        return

    status_msg = await message.answer("<i>🎤 Ovozli xabaringiz tinglanmoqda va tahlil qilinmoqda...</i>")
    try:
        voice_file = await bot.get_file(message.voice.file_id)
        voice_io = io.BytesIO()
        await bot.download_file(voice_file.file_path, voice_io)
        voice_bytes = voice_io.getvalue()

        user_query = await transcribe_voice(voice_bytes)
        await status_msg.edit_text(f"<i>🗣 Siz aytdingiz:</i> «{user_query}»\n\n<i>⚙️ Topshiriq bo'yicha agentlar chaqirilmoqda...</i>")
        await process_task(user_query, status_msg)
    except Exception as e:
        await status_msg.edit_text(f"⚠️ Xatolik: {str(e)}")

# Render portini ushlab turuvchi web server
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
