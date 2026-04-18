import asyncio, sqlite3, os
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# 1. Настройки
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
# Путь к базе в "сейфе" Amvera
DB_PATH = '/data/base.db'

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS knowledge (keyword TEXT, content TEXT, file_type TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS queue (keyword TEXT, user_id INTEGER)')
    conn.commit()
    conn.close()

def get_all_answers(user_text):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT keyword, content, file_type FROM knowledge")
    rows = cursor.fetchall()
    conn.close()
    user_text = user_text.lower().strip()
    results = []
    for keyword_str, content, f_type in rows:
        keywords = [k.strip().lower() for k in keyword_str.split(',')]
        if user_text in keywords:
            results.append((content, f_type))
    return results

def add_answer(keyword, content, file_type):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    clean_key = keyword.replace("❓ Новый вопрос:", "").split("\n")[0].strip().lower()
    cursor.execute("INSERT INTO knowledge VALUES (?, ?, ?)", (clean_key, content, file_type))
    conn.commit()
    conn.close()
    return clean_key

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def start(m: types.Message):
    kb = [[KeyboardButton(text="📚 Список тем"), KeyboardButton(text="ℹ️ Помощь")]]
    keyboard = ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
    await m.answer("👋 Бот запущен! База данных теперь в безопасности.", reply_markup=keyboard)

@dp.message(F.text == "📚 Список тем")
@dp.message(Command("list"))
async def list_topics(m: types.Message):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT keyword FROM knowledge ORDER BY keyword")
    rows = cursor.fetchall()
    conn.close()
    if rows:
        builder = []
        for r in rows:
            full_key = r[0] # Берем текст из кортежа
            display = full_key.split(',')[0].strip().capitalize()
            # Ограничиваем callback_data, чтобы Telegram не ругался
            call_data = full_key.split(',')[0].strip()[:20]
            builder.append([InlineKeyboardButton(text=display, callback_data=f"get_{call_data}")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=builder)
        await m.answer("📚 **Выбери предмет:**", reply_markup=keyboard)
    else:
        await m.answer("База пока пуста. Напиши тему, чтобы я её выучил!")

# --- БЛОК ПОМОЩИ ---
@dp.message(F.text.contains("Помощь"))
async def help_cmd(m: types.Message):
    await m.answer(
        "📖 **Шпаргалка по боту:**\n\n"
        "1️⃣ **Кнопка 'Список тем'** — покажет всё, что бот уже знает (нажимай на кнопки-предметы).\n"
        "2️⃣ **Просто напиши слово** (например, 'матан') — если ответ есть, бот его сразу скинет.\n"
        "3️⃣ **Если ответа нет** — бот перешлет твой вопрос старосте, и она добавит инфу.\n\n"
        "✨ Всё просто!"
    )

@dp.message(Command("clear"), F.from_user.id == ADMIN_ID)
async def clear_topic(m: types.Message):
    topic = m.text.replace("/clear ", "").lower().strip()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM knowledge WHERE keyword LIKE ?", (f"%{topic}%",))
    conn.commit()
    conn.close()
    await m.answer(f"🗑 Тема '{topic}' удалена!")

@dp.callback_query(F.data.startswith("get_"))
async def send_topic_data(callback: types.CallbackQuery):
    topic_name = callback.data.replace("get_", "")
    results = get_all_answers(topic_name)
    if results:
        for content, f_type in results:
            if f_type == "text": await callback.message.answer(content)
            elif f_type == "doc": await callback.message.answer_document(content)
            elif f_type == "photo": await callback.message.answer_photo(content)
    await callback.answer()

@dp.message(F.from_user.id == ADMIN_ID, F.reply_to_message)
async def admin_reply(m: types.Message):
    parent_msg = m.reply_to_message.text or m.reply_to_message.caption
    if not parent_msg or "Новый вопрос:" not in parent_msg: return
    q_text = parent_msg.replace("❓ Новый вопрос:", "").split("\n")[0].strip().lower()
    
    if m.document:
        add_answer(q_text, m.document.file_id, "doc")
    elif m.photo:
        add_answer(q_text, m.photo[-1].file_id, "photo")
    elif m.text:
        add_answer(q_text, m.text, "text")
        
    await m.answer(f"✅ Сохранено!")

@dp.message()
async def handle_all(m: types.Message):
    if not m.text or m.text.startswith("/"): return
    res = get_all_answers(m.text)
    if res:
        for content, f_type in res:
            if f_type == "text": await m.answer(content)
            elif f_type == "doc": await m.answer_document(content)
            elif f_type == "photo": await m.answer_photo(content)
    else:
        if m.from_user.id != ADMIN_ID:
            await m.answer("Этого нет в базе, передал старосте!")
        await bot.send_message(ADMIN_ID, f"❓ Новый вопрос: {m.text}\n\nСделай Reply.")

async def main():
    init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
