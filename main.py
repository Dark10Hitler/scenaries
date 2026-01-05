import os
import hashlib
import json
import base64
import asyncio
import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

load_dotenv()

# --- Конфигурация ---
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")
CRYPTOMUS_KEY = os.getenv("CRYPTOMUS_API_KEY")
CRYPTOMUS_MERCHANT = os.getenv("CRYPTOMUS_MERCHANT_ID")
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# --- База Данных ---
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    user_id = Column(String, primary_key=True)
    balance = Column(Integer, default=10)

Base.metadata.create_all(bind=engine)

# --- Инициализация API и Бота ---
app = FastAPI()
bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Вспомогательные функции Cryptomus ---
def create_cryptomus_invoice(user_id: str, amount: str, count: int):
    payload = {
        "amount": amount,
        "currency": "USD",
        "order_id": f"{user_id}_{count}_{os.urandom(4).hex()}",
        "url_callback": "https://scenaries.onrender.com/cryptomus_webhook"
    }
    data_json = json.dumps(payload)
    sign = hashlib.md5((base64.b64encode(data_json.encode()).decode() + CRYPTOMUS_KEY).encode()).hexdigest()
    
    headers = {
        "merchant": CRYPTOMUS_MERCHANT,
        "sign": sign,
        "Content-Type": "application/json"
    }
    try:
        res = requests.post("https://api.cryptomus.com/v1/payment", headers=headers, data=data_json, timeout=10)
        return res.json().get("result", {}).get("url")
    except:
        return None

# --- Логика Telegram Бота ---
@dp.message(F.text.startswith("/start"))
async def cmd_start(message: types.Message):
    user_id_from_url = message.text.replace("/start ", "")
    if user_id_from_url == "/start":
        await message.answer("🚀 Please access the payment section via the official website to top up your balance.")
        return

    # Клавиатура с английским текстом и маркетинговыми акцентами
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Standard: 10 Scripts — $2", callback_data=f"buy_2_10_{uid}")],
        [InlineKeyboardButton(text="🔥 Popular: 30 Scripts — $4 (50% OFF)", callback_data=f"buy_4_30_{uid}")],
        [InlineKeyboardButton(text="💎 Pro: 100 Scripts — $10 (60% OFF)", callback_data=f"buy_10_100_{uid}")]
    ])

    # Приветственное сообщение
    await message.answer(
        f"💳 **Secure Checkout for ID: {uid}**\n\n"
        f"Choose your credit pack below to unlock professional AI scriptwriting, storyboards, and viral thumbnails.\n\n"
        f"⚡ **FLASH SALE:** Limited time discounts up to 60% applied!", 
        reply_markup=kb,
        parse_mode="Markdown"
    )
@dp.callback_query(F.data.startswith("buy_"))
async def process_buy(callback: types.CallbackQuery):
    _, price, count, uid = callback.data.split("_")
    pay_url = create_cryptomus_invoice(uid, price, count)
    if pay_url:
        await callback.message.edit_text(
            f"Пакет: {count} запросов за {price}$.\nОплатите по кнопке ниже:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Оплатить Криптовалютой", url=pay_url)]
            ])
        )
    else:
        await callback.answer("Ошибка связи с платежной системой.")

# --- API Эндпоинты ---
class GenerateReq(BaseModel):
    user_id: str
    prompt: str

@app.get("/get_balance/{user_id}")
async def get_bal(user_id: str):
    db = SessionLocal()
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        user = User(user_id=user_id, balance=10)
        db.add(user)
        db.commit()
        db.refresh(user)
    bal = user.balance
    db.close()
    return {"balance": bal}

@app.post("/generate")
async def gen(req: GenerateReq):
    db = SessionLocal()
    user = db.query(User).filter(User.user_id == req.user_id).first()
    
    if not user:
        user = User(user_id=req.user_id, balance=10)
        db.add(user)
        db.commit()
        db.refresh(user)

    if user.balance <= 0:
        db.close()
        raise HTTPException(status_code=403, detail="Insufficient balance")

    # Ключевые исправления для OpenRouter
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://scenaries.onrender.com", # Требуется OpenRouter
        "X-Title": "AI Scenario Generator"
    }
    
    payload = {
        "model": "anthropic/claude-3.5-sonnet",
        "messages": [
    {
        "role": "system", 
        "content": """Ты — мировой эксперт по виральному маркетингу, элитный режиссер и нейро-психолог. 
        Твоя специализация: создание контента, который удерживает внимание и становится виральным. 
        Ты мыслишь категориями дофаминовых петель, визуальных зацепок и профессионального киноязыка.

        Твой ответ должен быть безупречно структурирован и состоять из двух элитных блоков:

        БЛОК 1: Viral Hook Matrix (Психология внимания)
        Предложи 3 стратегических варианта начала ролика. Ты должен использовать триггеры FOMO, любопытства или визуального шока:
        - Вариант А (Агрессивный/Pain-Point): Резкий вход, бьющий в боль аудитории.
        - Вариант Б (Интригующий/Story-Gap): Создание открытой петли, которую хочется закрыть.
        - Вариант В (Визуальный/Eye-Candy): Необычное действие или ракурс.
        Для каждого варианта укажи 'Прогноз удержания' (Retention Forecast %) и объясни психологический механизм, почему зритель не пролистнет.

        БЛОК 2: Director's Storyboard (Техническая карта)
        Создай раскадровку уровня Голливудских стандартов в виде Markdown-таблицы. Для каждой сцены пропиши:
        1. Визуал: Опиши крупность плана (Close-up, Wide, POV), освещение и движение камеры.
        2. Текст: Лаконичный, мощный скрипт (Voiceover или текст на экране).
        3. Звук (SFX): Звуковые акценты для повышения динамики.
        4. AI Video Prompt: Профессиональный промт на английском для Runway Gen-3/Luma Dream Machine, включающий технические параметры камеры и освещения (cinematic lighting, 4k, hyper-realistic).

        Будь дерзким в креативе, используй сленг кинопроизводства и делай упор на эстетику."""
    },
    {"role": "user", "content": req.prompt}
]
    }
    
    try:
        # Используем asyncio для предотвращения блокировки
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(
            None, 
            lambda: requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=45)
        )
        
        if resp.status_code == 200:
            result = resp.json()
            script_content = result['choices'][0]['message']['content']
            user.balance -= 1
            db.commit()
            return {"script": script_content, "balance": user.balance}
        else:
            print(f"OpenRouter Error: {resp.text}")
            raise HTTPException(status_code=resp.status_code, detail="AI Service Error")
    except Exception as e:
        print(f"Generate Error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@app.post("/cryptomus_webhook")
async def webhook(request: Request):
    try:
        data = await request.json()
        if data.get('status') in ['paid', 'completed']:
            order_id = data.get('order_id')
            parts = order_id.split('_')
            if len(parts) >= 2:
                u_id, count = parts[0], int(parts[1])
                db = SessionLocal()
                user = db.query(User).filter(User.user_id == u_id).first()
                if user:
                    user.balance += count
                    db.commit()
                    try:
                        await bot.send_message(u_id, f"✅ Оплата прошла! Вам начислено {count} запросов. Обновите страницу на сайте.")
                    except: pass
                db.close()
    except: pass
    return {"status": "ok"}

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(dp.start_polling(bot))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))



