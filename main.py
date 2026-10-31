import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv
from google import genai

load_dotenv()

# Kalitlar
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
ADMIN_ID = os.getenv("ADMIN_ID", "")
AI_MODEL = "gemini-2.5-flash"

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

# ----------------- AI BILAN ISHLASH FUNKSIYALARI -----------------
async def run_ai(prompt_system: str, text: str) -> str:
    response = client.models.generate_content(
        model=AI_MODEL,
        contents=text,
        config={"system_instruction": prompt_system, "temperature": 0.4}
    )
    return response.text

async def orchestrator_decide(user_query: str) -> list:
    router_prompt = f"""Quyidagi topshiriq uchun qaysi mutaxassislar kerak?
Topshiriq: "{user_query}"
Faqat kerakli kalit so'zlarni vergul bilan yoz (ortiqcha so'zsiz): MOLIYA, KARYERA, BIZNES, EDTECH"""
    res = client.models.generate_content(
        model=AI_MODEL,
        contents=router_prompt,
        config={"temperature": 0.1}
    )
    return [x.strip() for x in res.text.upper().split(",") if x.strip()]

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
        "Barcha 4 ta agentingiz (Moliya, Karyera, Biznes, EdTech) shay holatda.\n"
        "Menga istalgan savol yoki topshiriqni bering, majlis o'tkazib natijasini taqdim etaman!"
    )

@dp.message(F.text)
async def handle_request(message: types.Message):
    if ADMIN_ID and str(message.from_user.id) != str(ADMIN_ID).strip():
        return

    user_query = message.text
    status_msg = await message.answer("<i>⚙️ Boshqaruvchi: Topshiriq o'rganilmoqda...</i>")
    
    try:
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
                await message.answer(res[i:i+4000])
        else:
            await message.answer(res)

    except Exception as e:
        await status_msg.edit_text(f"⚠️ Xatolik: {str(e)}")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
