import asyncio
import sqlite3
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
# ВАЖНО: Импорты для всех типов кнопок
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# 1. Настройки (берем из переменных Kuberns)
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- ТЕХНИЧЕСКАЯ ЧАСТЬ ДЛЯ СЕРВЕРА (чтобы не падал) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_health_check():
    server = HTTPServer(('0.0.0.0', 8000), HealthCheckHandler)
    server.serve_forever()

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('base.db')
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS knowledge (keyword TEXT, content TEXT, file_type TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS queue (keyword TEXT, user_id INTEGER)')
    conn.commit()
    conn.close()

def get_all_answers(user_text):
    conn = sqlite3.connect('base.db')
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
    conn = sqlite3.connect('base.db')
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
    await m.answer("👋 Я в сети! Нажми на кнопку или напиши тему.", reply_markup=keyboard)

@dp.message(F.text == "📚 Список тем")
@dp.message(Command("list"))
async def list_topics(m: types.Message):
    conn = sqlite3.connect('base.db')
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT keyword FROM knowledge ORDER BY keyword")
    rows = cursor.fetchall()
    conn.close()
    
    if rows:
        builder = []
        for r in rows:
            topic = str(r[0]) # Берем именно ПЕРВЫЙ элемент и превращаем в текст
            builder.append([InlineKeyboardButton(text=topic, callback_data=f"get_{topic}")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=builder)
        await m.answer("📚 **Выбери тему:**", reply_markup=keyboard)
    else:
        await m.answer("База пока пуста.")

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
    
    content = m.document.file_id if m.document else (m.photo[-1].file_id if m.photo else m.text)
    f_type = "doc" if m.document else ("photo" if m.photo else "text")
    add_answer(q_text, content, f_type)
    await m.answer(f"✅ Сохранено для: {q_text}")

@dp.message()
async def handle_all(m: types.Message):
    if not m.text: return
    results = get_all_answers(m.text)
    if results:
        for content, f_type in results:
            if f_type == "text": await m.answer(content)
            elif f_type == "doc": await m.answer_document(content)
            elif f_type == "photo": await m.answer_photo(content)
    else:
        if m.from_user.id != ADMIN_ID:
            await m.answer("Этого нет в базе, передал старосте! ✨")
        await bot.send_message(ADMIN_ID, f"❓ Новый вопрос: {m.text}\n\nСделай Reply.")

async def main():
    init_db()
    # Запуск проверки здоровья в отдельном потоке
    threading.Thread(target=run_health_check, daemon=True).start()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
