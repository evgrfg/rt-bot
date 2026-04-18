import asyncio
import os
import sqlite3
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


# --- 1. НАСТРОЙКИ ---
TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

if not TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required")
if not ADMIN_ID:
    raise ValueError("ADMIN_ID environment variable is required")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- 2. РАБОТА С БАЗОЙ ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('base.db')
    cursor = conn.cursor()
    # Создаем таблицы, если их нет
    cursor.execute('CREATE TABLE IF NOT EXISTS knowledge (keyword TEXT, content TEXT, file_type TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS queue (keyword TEXT, user_id INTEGER)')
    conn.commit()
    conn.close()

def add_to_queue(keyword, user_id):
    conn = sqlite3.connect('base.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO queue VALUES (?, ?)", (keyword.lower().strip(), user_id))
    conn.commit()
    conn.close()

def get_and_clear_queue(keyword):
    conn = sqlite3.connect('base.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM queue WHERE keyword = ?", (keyword.lower().strip(),))
    # Извлекаем ID из кортежей
    users = [row[0] for row in cursor.fetchall()]
    cursor.execute("DELETE FROM queue WHERE keyword = ?", (keyword.lower().strip(),))
    conn.commit()
    conn.close()
    return list(set(users)) # Только уникальные ID, чтобы не спамить одному человеку

def add_answer(keyword, content, file_type):
    conn = sqlite3.connect('base.db')
    cursor = conn.cursor()
    # Чистим ключ от системных пометок
    clean_key = keyword.replace("❓ Новый вопрос:", "").split("\n")[0].strip().lower()
    cursor.execute("INSERT INTO knowledge VALUES (?, ?, ?)", (clean_key, content, file_type))
    conn.commit()
    conn.close()
    return clean_key

def get_all_answers(user_text):
    conn = sqlite3.connect('base.db')
    cursor = conn.cursor()
    cursor.execute("SELECT keyword, content, file_type FROM knowledge")
    rows = cursor.fetchall()
    conn.close()
    
    user_text = user_text.lower().strip()
    results = []
    
    for keyword_str, content, f_type in rows:
        if not keyword_str: continue
        # Разбиваем ключи по запятой и проверяем
        keywords = [k.strip().lower() for k in keyword_str.split(',')]
        if user_text in keywords:
            results.append((content, f_type))
    return results

# --- 3. ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def start(m: types.Message):
    # Создаем кнопки
    kb = [
        [KeyboardButton(text="📚 Список тем"), KeyboardButton(text="ℹ️ Помощь")]
    ]
    # Собираем их в клавиатуру
    keyboard = ReplyKeyboardMarkup(
        keyboard=kb,
        resize_keyboard=True, # Чтобы кнопки были маленькими и аккуратными
        input_field_placeholder="Выберите пункт меню"
    )
    
    await m.answer(
        "👋 Привет! Я база знаний нашей группы.\n\n"
        "Нажми на кнопку ниже, чтобы увидеть список тем, или просто напиши ключевое слово.",
        reply_markup=keyboard
    )

@dp.message(Command("list"))
async def list_topics(m: types.Message):
    conn = sqlite3.connect('base.db')
    cursor = conn.cursor()
    # Берем уникальные темы в алфавитном порядке
    cursor.execute("SELECT DISTINCT keyword FROM knowledge ORDER BY keyword")
    rows = cursor.fetchall()
    conn.close()

    if rows:
        # Создаем клавиатуру с кнопками
        builder = []
        for r in rows:
            topic_name = r[0]
            # Создаем кнопку для каждой темы
            builder.append([InlineKeyboardButton(text=topic_name, callback_data=f"get_{topic_name}")])

        keyboard = InlineKeyboardMarkup(inline_keyboard=builder)
        await m.answer("📚 **Выбери интересующую тему:**", reply_markup=keyboard, parse_mode="Markdown")
    else:
        await m.answer("База пока пуста.")

@dp.message(F.from_user.id == ADMIN_ID, F.reply_to_message)
async def admin_reply(m: types.Message):
    parent_msg = m.reply_to_message.text or m.reply_to_message.caption
    if not parent_msg or "Новый вопрос:" not in parent_msg:
        return

    q_text = parent_msg.replace("❓ Новый вопрос:", "").split("\n")[0].strip().lower()
    
    # 1. Если прислали ФОТО
    if m.photo:
        # Берем последнее фото из списка (оно самое качественное)
        file_id = m.photo[-1].file_id
        add_answer(q_text, file_id, "photo")
        await m.answer(f"✅ Фото добавлено в тему: {q_text}")

    # 2. Если прислали ДОКУМЕНТ (файл)
    elif m.document:
        add_answer(q_text, m.document.file_id, "doc")
        await m.answer(f"✅ Файл добавлен в тему: {q_text}")

    # 3. Если прислали ПРОСТО ТЕКСТ
    elif m.text:
        add_answer(q_text, m.text, "text")
        await m.answer(f"✅ Текст добавлен в тему: {q_text}")
    
    # Плюс рассылка всем ожидающим (этот кусок у тебя уже есть ниже)
    
    # Рассылка всем, кто ждал этот конкретный ответ
    waiting_users = get_and_clear_queue(q_text)
    count = 0
    for user_id in waiting_users:
        try:
            if f_type == "doc":
                await bot.send_document(user_id, content, caption=f"Ответ по теме: {q_text}")
            else:
                await bot.send_message(user_id, f"Появился ответ на ваш вопрос '{q_text}':\n\n{content}")
            count += 1
        except:
            continue 

    await m.answer(f"✅ Готово! Ответ сохранен и отправлен {count} чел.")

@dp.message(F.text == "📚 Список тем")
async def list_via_button(m: types.Message):
    await list_topics(m) # Просто вызываем уже готовую функцию списка

@dp.message(F.text == "ℹ️ Помощь")
async def help_via_button(m: types.Message):
    await m.answer("Если нужной темы нет в списке — просто напиши её название боту. "
                   "Староста получит уведомление и добавит ответ!")

@dp.callback_query(F.data.startswith("get_"))
async def send_topic_data(callback: types.CallbackQuery):
    # Достаем название темы из данных кнопки
    topic_name = callback.data.replace("get_", "")

    # Используем нашу уже готовую функцию поиска
    results = get_all_answers(topic_name)

    if results:
        for content, f_type in results:
            if f_type == "text": await callback.message.answer(content)
            elif f_type == "doc": await callback.message.answer_document(content)
            elif f_type == "photo": await callback.message.answer_photo(content)

    # Убираем "часики" с кнопки в Telegram
    await callback.answer()

@dp.message()
async def handle_all(m: types.Message):
    if not m.text: return
    
    # Если это команда, которую мы не обработали выше (например, /clear_queue)
    if m.text.startswith('/'):
        # Если бот молчит на команды, значит мы их не прописали. 
        # Давай добавим простую проверку:
        if m.text == "/clear_queue":
            conn = sqlite3.connect('base.db')
            conn.cursor().execute("DELETE FROM queue")
            conn.commit()
            conn.close()
            await m.answer("🧹 Очередь очищена")
            return

    # Поиск в базе
    res = get_all_answers(m.text)
    if res:
        for content, f_type in res:
            if f_type == "text": await m.answer(content)
            elif f_type == "doc": await m.answer_document(content)
            elif f_type == "photo": await m.answer_photo(content)
    else:
        # Если ответа нет — ПЕРЕСЫЛАЕМ ВСЕГДА
        add_to_queue(m.text, m.from_user.id)
        # Шлем уведомление админу
        await bot.send_message(
            ADMIN_ID, 
            f"❓ Новый вопрос: {m.text}\n\nСделай Reply, чтобы ответить."
        )
        if m.from_user.id != ADMIN_ID:
            await m.answer("Этого нет в базе, я передал вопрос старосте!")

# --- 4. HEALTH CHECK SERVER ---
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.send_header('Content-Length', '2')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(b'OK')
    
    def log_message(self, format, *args):
        pass  # Suppress log output

def start_health_server():
    server = HTTPServer(('0.0.0.0', 8000), HealthHandler)
    server.serve_forever()

# --- 5. ЗАПУСК ---
async def main():
    print("Initializing database...")
    init_db()
    print("Deleting webhook...")
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Start health check server in a separate thread
    print("Starting health check server on 0.0.0.0:8000...")
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()
    print("Health check server started!")
    
    # Run bot polling
    print("Starting bot polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот выключен")
