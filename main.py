import os
import hashlib
import json
import base64
import asyncio
import secrets
import requests
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, DateTime
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
    user_id = Column(String, primary_key=True) # Telegram ID
    lovable_id = Column(String, unique=True, index=True) # Публичный ID: scen_...
    username = Column(String)
    balance = Column(Integer, default=3)
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# --- Вспомогательные функции ---
def generate_lovable_id():
    """Генерирует ID в стиле Lovable: scen_mjxynckq_9ho58phs"""
    p1 = secrets.token_hex(4)
    p2 = secrets.token_hex(4)
    return f"scen_{p1}_{p2}"

def create_cryptomus_invoice(user_id: str, amount: str, count: int):
    payload = {
        "amount": amount,
        "currency": "USD",
        "order_id": f"{user_id}_{count}_{os.urandom(2).hex()}",
        "url_callback": "https://scenaries.onrender.com/cryptomus_webhook",
        "lifetime": 3600
    }
    data_json = json.dumps(payload)
    data_base64 = base64.b64encode(data_json.encode()).decode()
    sign = hashlib.md5((data_base64 + CRYPTOMUS_KEY).encode()).hexdigest()
    
    headers = {
        "merchant": CRYPTOMUS_MERCHANT,
        "sign": sign,
        "Content-Type": "application/json"
    }
    
    try:
        res = requests.post("https://api.cryptomus.com/v1/payment", headers=headers, data=data_json, timeout=15)
        response_data = res.json()
        if response_data.get("state") == 0:
            return response_data.get("result", {}).get("url")
    except Exception as e:
        print(f"Cryptomus Error: {e}")
    return None

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

# --- Логика Telegram Бота ---

@dp.message(F.text.startswith("/start"))
async def cmd_start(message: types.Message):
    db = SessionLocal()
    # Ищем юзера по TG ID
    user = db.query(User).filter(User.user_id == str(message.from_user.id)).first()
    
    if not user:
        # Создаем нового с уникальным Lovable ID
        user = User(
            user_id=str(message.from_user.id),
            lovable_id=generate_lovable_id(),
            username=message.from_user.username or "User",
            balance=3
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    profile_text = (
        f"🚀 **ScriptAI: Authentication Successful**\n"
        f"──────────────────\n"
        f"👤 **User:** @{user.username}\n"
        f"🆔 **Telegram ID:** `{user.user_id}`\n"
        f"🔑 **Access ID:** `{user.lovable_id}`\n"
        f"💰 **Balance:** `{user.balance}` Credits\n"
        f"──────────────────\n"
        f"☝️ **Copy your Access ID and paste it on the website to login.**"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Go to Website", url="https://script-ai-web.vercel.app/")],
        [InlineKeyboardButton(text="💳 Buy Credits", callback_data=f"buy_menu_{user.user_id}")]
    ])

    await message.answer(profile_text, parse_mode="Markdown", reply_markup=kb)
    db.close()

@dp.callback_query(F.data.startswith("buy_menu_"))
async def show_buy_menu(callback: types.CallbackQuery):
    uid = callback.data.split("_")[-1]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Standard: 10 Scripts — $2", callback_data=f"buy_2_10_{uid}")],
        [InlineKeyboardButton(text="🔥 Popular: 30 Scripts — $4", callback_data=f"buy_4_30_{uid}")],
        [InlineKeyboardButton(text="💎 Pro: 100 Scripts — $10", callback_data=f"buy_10_100_{uid}")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="back_to_profile")]
    ])
    await callback.message.edit_text("💳 **Select a package to top up:**", reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("buy_"))
async def process_buy(callback: types.CallbackQuery):
    try:
        _, price, count, uid = callback.data.split("_")
        pay_url = create_cryptomus_invoice(uid, price, int(count))
        
        if pay_url:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Pay with Crypto", url=pay_url)],
                [InlineKeyboardButton(text="❌ Cancel", callback_data="back_to_profile")]
            ])
            await callback.message.edit_text(f"🌟 **Order: {count} Scripts**\nPrice: ${price}\n\nProceed to payment:", reply_markup=kb)
        else:
            await callback.answer("Invoice error. Try again.", show_alert=True)
    except: pass

# --- API Эндпоинты ---

class GenerateReq(BaseModel):
    user_id: str # Здесь может быть либо TG ID, либо Lovable ID (обработаем оба)
    prompt: str

@app.get("/auth/{l_id}")
async def get_auth_data(l_id: str):
    """Специальный эндпоинт для входа с сайта через Lovable ID"""
    db = SessionLocal()
    user = db.query(User).filter(User.lovable_id == l_id).first()
    if not user:
        db.close()
        raise HTTPException(status_code=404, detail="Access ID not found")
    
    res = {
        "user_id": user.user_id,
        "lovable_id": user.lovable_id,
        "username": user.username,
        "balance": user.balance
    }
    db.close()
    return res

@app.get("/get_balance/{user_id}")
async def get_bal(user_id: str):
    db = SessionLocal()
    # Проверяем и по TG ID, и по Lovable ID для гибкости
    user = db.query(User).filter((User.user_id == user_id) | (User.lovable_id == user_id)).first()
    if not user:
        db.close()
        return {"balance": 0, "error": "not found"}
    bal = user.balance
    db.close()
    return {"balance": bal}

@app.post("/generate")
async def gen(req: GenerateReq):
    db = SessionLocal()
    # Поиск юзера
    user = db.query(User).filter((User.user_id == req.user_id) | (User.lovable_id == req.user_id)).first()
    
    if not user or user.balance <= 0:
        db.close()
        raise HTTPException(status_code=403, detail="Insufficient balance")

    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://scenaries.onrender.com",
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

        БЛОК 2: Director's Storyboard (Technical Production Map)
        Вместо таблицы используй СТРОГУЮ структуру списка для каждой сцены. Это КРИТИЧЕСКИ важно для корректного отображения в интерфейсе. 
        Для каждой сцены обязательно используй следующий формат:
        [SCENE_START]
        SCENE_NUMBER: (номер сцены)
        TIMING: (0:00 - 0:05)
        VISUAL: (Тип плана: Close-up/Wide/POV. Опиши освещение и движение камеры)
        TEXT: (Скрипт озвучки или текст на экране)
        SFX: (Звуковые эффекты и музыкальный акцент)
        AI_VIDEO_PROMPT: (Профессиональный промт на английском для Runway/Luma: cinematic, 4k, hyper-realistic, camera movement)
        [SCENE_END]

        Повтори этот блок для каждой сцены (минимум 4 сцены). Не используй символы '|' или '---'.
        Будь дерзким в креативе, используй сленг кинопроизводства и делай упор на эстетику.
        
        БЛОК 3: Universal AI Agent Master-Prompt (The God-Prompt).
        Сгенерируй один монолитный, профессионально структурированный промт на английском языке для вставки в ChatGPT/Claude/Gemini. 

        Этот промт должен быть оформлен в блоке 'Copy-Paste for AI Agent' и включать:
        1. ROLE: Назначение ИИ роли Senior Content Strategist & Viral Growth Expert.
        2. CONTEXT: Краткое изложение сгенерированного выше сценария (тема, хук, ключевые сцены).
        3. IMAGE GENERATION TASK (IMPORTANT): Четкая инструкция для ИИ-агента создать 5 детальных, фотореалистичных промтов для Midjourney/DALL-E 3, которые визуализируют ключевые моменты этого сценария с указанием параметров (aspect ratio, lighting, camera lens).
        4. CONTENT EXPANSION: Задача на написание 5 виральных постов для разных платформ (X, Instagram, LinkedIn), подбор 20 трендовых хештегов и разработку стратегии ответов в комментариях для повышения вовлеченности.
        5. FORMAT: Инструкция выдавать ответ в структурированном виде, удобном для немедленного копирования.

        Инструкция для тебя: Сделай этот мастер-промт максимально адаптивным, чтобы пользователь одним кликом получил полную маркетинговую поддержку своего видео.

        БЛОК 2: Viral Success Kit  
        "content": Ты — элитный стратег по виральному контенту с охватом 100 млн+ зрителей. 
        Твоя задача — превратить идею пользователя в виральную бомбу.

        ОТВЕТ ДОЛЖЕН БЫТЬ СТРОГО ПО СЛЕДУЮЩЕЙ СТРУКТУРЕ:
🚀 VIRAL HOOK LAB (Первые 3 секунды)
Для каждой категории предложи один убойный заголовок:
1. 😱 **[TRIGGER: FEAR]** — (Бей в страх потери или ошибки).
2. 👀 **[TRIGGER: CURIOSITY]** — (Создай информационный вакуум, который нужно закрыть).
3. 💎 **[TRIGGER: VALUE]** — (Обещай конкретный результат за короткое время).
4. 🔥 **[TRIGGER: CONTROVERSY]** — (Разрушь популярный миф).

🏷️ SMART HASHTAG ENGINE (Алгоритмический буст)
Сгенерируй хэштеги в три столбика для копирования:
- **Broad (Охватные):** 3 общих тега.
- **Niche (Тематические):** 5 узких тегов по теме запроса.
- **Trend (Тренды 2026):** 3 системных тега для попадания в рекомендации.

🎬 DIRECTOR'S STORYBOARD
Опиши сценарий по сценам, используя формат:
[SCENE_START]
SCENE_NUMBER: ...
TIMING: ...
VISUAL: (Детальный план и освещение)
TEXT: (Что произносит диктор)
SFX: (Звуки и музыка)
AI_VIDEO_PROMPT: (Промт для Runway/Luma на английском)
[SCENE_END]

🤖 COPY-PASTE FOR AI AGENT
Сгенерируй монолитный God-Prompt на английском языке для ChatGPT/Midjourney, чтобы полностью упаковать этот ролик (описания, превью, посты)."""

    },
            {"role": "user", "content": req.prompt}
        ]
    }
    
    try:
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(
            None, 
            lambda: requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=60)
        )
        
        if resp.status_code == 200:
            result = resp.json()
            script_content = result['choices'][0]['message']['content']
            user.balance -= 1
            db.commit()
            return {"script": script_content, "balance": user.balance}
        else:
            raise HTTPException(status_code=resp.status_code, detail="AI Service Error")
    except Exception as e:
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
                        await bot.send_message(u_id, f"✅ Payment Received! +{count} Scripts added to your balance.")
                    except: pass
                db.close()
    except: pass
    return {"status": "ok"}

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(dp.start_polling(bot))

if __name__ == "__main__":
    import uvicorn
    # На Render порт берется из переменной окружения PORT
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
