import logging
import os
import openai
import sqlite3
import asyncio
from aiogram import Bot, Dispatcher, types
from openai.error import OpenAIError

# Чтение переменных окружения
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', 'YOUR_DEFAULT_TELEGRAM_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', 'YOUR_DEFAULT_OPENAI_KEY')
MODEL_NAME = os.getenv('MODEL_NAME', 'gpt-3.5-turbo-16k')
OPENAI_ORGANIZATION = os.getenv('OPENAI_ORGANIZATION', None)  # Если организация не указана, используется None
MAX_TOKENS = int(os.getenv('MAX_TOKENS', '16000'))  # Максимальное количество токенов для модели

openai.api_key = OPENAI_API_KEY

logging.basicConfig(level=logging.INFO, format='%(message)s')
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher(bot)

# Настройка SQLite
conn = sqlite3.connect('data/messages.db')
cursor = conn.cursor()

# Создание таблицы для хранения истории сообщений
cursor.execute('''CREATE TABLE IF NOT EXISTS message_history
                 (chat_id INTEGER, user_id INTEGER, role TEXT, content TEXT)''')
conn.commit()

# Для хранения username бота
BOT_USERNAME = None

@dp.message_handler(commands=['start', 'help'])
async def send_welcome(message: types.Message):
    welcome_text = f"""
Привет! Я ваш бот, созданный на основе технологии OpenAI. Вот что я умею:

1. Отвечать на разнообразные вопросы.
2. Сохранять контекст общения, что позволяет вести более сложные и связанные диалоги.
3. Работать в группах. Вы можете упомянуть меня, чтобы задать вопрос или ответить на мое сообщение.

Если вы хотите сбросить контекст общения и начать разговор заново, просто напишите мне "забудь".

Задайте свой вопрос или уточните, как я могу вам помочь!

**Настройки бота:**
- Используемая модель: {MODEL_NAME}
- Максимальное количество токенов: {MAX_TOKENS}
    """
    await message.answer(welcome_text, parse_mode=types.ParseMode.MARKDOWN)

@dp.message_handler(lambda message: message.text.lower().strip() == "забудь")
async def forget_history(message: types.Message):
    cursor.execute("DELETE FROM message_history WHERE chat_id=? AND user_id=?", (message.chat.id, message.from_user.id))
    conn.commit()
    await message.answer("Я забыл всю нашу предыдущую переписку.")

async def send_typing_status(chat_id: int, delay: int = 15):
    while True:
        await bot.send_chat_action(chat_id, "typing")
        await asyncio.sleep(delay)

@dp.message_handler(content_types=types.ContentTypes.TEXT)
async def handle_text_messages(message: types.Message):
    group_title = message.chat.title if message.chat.title else str(message.chat.id)
    if message.chat.type in ["group", "supergroup"]:
        logging.info(f"Received message in group: {group_title}")
        if BOT_USERNAME and f"@{BOT_USERNAME}" in message.text:
            logging.info(f"Detected mention of @{BOT_USERNAME}")
            text_without_mention = message.text.replace(f"@{BOT_USERNAME}", "").strip()
            
            # Проверка на команду "забудь"
            if text_without_mention.lower().strip() == "забудь":
                await forget_history(message)
                return
            
            await ask_openai(message, text_without_mention, message.chat.type, group_title)
            
        elif message.reply_to_message and message.reply_to_message.from_user.id == bot.id:
            # Проверка на команду "забудь"
            if message.text.lower().strip() == "забудь":
                await forget_history(message)
                return
            
            await ask_openai(message, message.text, message.chat.type, group_title)
        else:
            logging.info(f"Did not detect a mention or reply in group message: {group_title}.")
            return
    else:
        await ask_openai(message, message.text, "private", group_title)


async def ask_openai(message: types.Message, text: str, chat_type: str, group_title=None):
    chat_id = message.chat.id
    user_id = message.from_user.id
    typing_task = asyncio.create_task(send_typing_status(chat_id))

    # Добавляем сообщение пользователя в базу данных
    cursor.execute("INSERT INTO message_history (chat_id, user_id, role, content) VALUES (?, ?, ?, ?)",
                   (chat_id, user_id, 'user', text))
    conn.commit()

    # Получаем историю сообщений для данного пользователя
    cursor.execute("SELECT role, content FROM message_history WHERE chat_id=? AND user_id=? ORDER BY ROWID", (chat_id, user_id))
    user_messages = [{"role": role, "content": content} for role, content in cursor.fetchall()]

    # Логирование сообщения пользователя
    if chat_type in ["group", "supergroup"]:
        logging.info(f"[Group: {group_title}] {message.from_user.full_name} said: {text}")
    else:
        logging.info(f"[{chat_type}] {message.from_user.full_name} said: {text}")

    # Отправляем запрос к OpenAI
    try:
        response = openai.ChatCompletion.create(
            model=MODEL_NAME,
            messages=user_messages,
            organization=OPENAI_ORGANIZATION
        )
    except OpenAIError as e:
        logging.error(f"Error from OpenAI: {e}")
        error_message = str(e)
        user_notification = f"Извините, произошла ошибка при обработке вашего запроса: `{error_message}`."

        await bot.send_message(
            chat_id=message.chat.id,
            text=user_notification,
            reply_to_message_id=message.message_id if chat_type in ["group", "supergroup"] else None,
            parse_mode=types.ParseMode.MARKDOWN
        )
        typing_task.cancel()
        return
    response_text = response['choices'][0]['message']['content'].strip()
    total_tokens_used = response['usage']['total_tokens']
    token_percentage = (total_tokens_used / MAX_TOKENS) * 100

    # Отправляем ответ пользователю
    await bot.send_message(
        chat_id=message.chat.id,
        text=response_text,
        reply_to_message_id=message.message_id if chat_type in ["group", "supergroup"] else None,
        parse_mode=types.ParseMode.MARKDOWN
        typing_task.cancel()
    )

    # Добавляем ответ бота в базу данных
    cursor.execute("INSERT INTO message_history (chat_id, user_id, role, content) VALUES (?, ?, ?, ?)",
                   (chat_id, user_id, 'assistant', response_text))
    conn.commit()

    # Логирование ответа от OpenAI
    if chat_type in ["group", "supergroup"]:
        logging.info(f"[Group: {group_title}] Response from OpenAI: {response_text}")
    else:
        logging.info(f"[{chat_type}] Response from OpenAI: {response_text}")

    logging.info(f"Tokens used: {total_tokens_used} ({token_percentage:.2f}% of {MAX_TOKENS})")

async def on_startup(dp):
    global BOT_USERNAME
    BOT_USERNAME = (await bot.me).username
    logging.info(f"Initialized bot with username: @{BOT_USERNAME}")

if __name__ == '__main__':
    from aiogram import executor
    try:
        executor.start_polling(dp, on_startup=on_startup, skip_updates=True)
    finally:
        # Закрытие соединения с базой данных перед завершением работы
        conn.close()
