import telebot
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from groq import Groq
from flask import Flask, request

# ==========================================================
# НАСТРОЙКИ
# ==========================================================

# Ключи берутся из переменных окружения (безопасно!)
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Путь к файлам данных
DATA_DIR = Path("data")
CONTEXT_FILE = DATA_DIR / "context.json"
DATA_DIR.mkdir(exist_ok=True)

# Инициализация бота (threaded=False важен для Webhook)
bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
groq_client = Groq(api_key=GROQ_API_KEY)


# ==========================================================
# РАБОТА С КОНТЕКСТОМ
# ==========================================================

def load_context():
    if CONTEXT_FILE.exists():
        with open(CONTEXT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_context(context):
    with open(CONTEXT_FILE, "w", encoding="utf-8") as f:
        json.dump(context, f, ensure_ascii=False, indent=2)


def add_to_context(user_id, message_text):
    context = load_context()
    if str(user_id) not in context:
        context[str(user_id)] = []

    context[str(user_id)].append({
        "timestamp": datetime.now().isoformat(),
        "text": message_text
    })

    # Оставляем записи только за последние 15 дней
    cutoff_date = datetime.now() - timedelta(days=15)
    context[str(user_id)] = [
        entry for entry in context[str(user_id)]
        if datetime.fromisoformat(entry["timestamp"]) > cutoff_date
    ]
    save_context(context)


def get_context_summary(user_id):
    context = load_context()
    user_context = context.get(str(user_id), [])

    if not user_context:
        return "Это первое сообщение пользователя."

    summary = "История записей пользователя:\n"
    for entry in user_context[-30:]:
        date = datetime.fromisoformat(entry["timestamp"]).strftime("%d.%m %H:%M")
        summary += f"[{date}] {entry['text']}\n"
    return summary


# ==========================================================
# ИНТЕГРАЦИЯ С НЕЙРОСЕТЬЮ
# ==========================================================

def get_ai_response(user_message, user_id):
    context_summary = get_context_summary(user_id)

    system_prompt = f"""Ты — умный персональный помощник и дневник.
ПРАВИЛА:
1. ВСЕГДА отвечай полностью, НИКОГДА не обрывай текст на полуслове.
2. Анализируй сон и привычки, давай короткие и полезные советы (2-4 предложения).
3. Отвечай дружелюбно, по-русски.
4. Помни: пользователь просил сдвигать время в записях на +3 часа при выводе, но в этом промпте просто анализируй факты.

Контекст записей пользователя:
{context_summary}
"""

    try:
        completion = groq_client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            temperature=0.7,
            max_tokens=2000,  # Увеличили лимит, чтобы не обрывалось
            top_p=1,
            stream=False,
        )
        return completion.choices[0].message.content
    except Exception as e:
        print(f"Ошибка Groq API: {e}")
        return "⚠️ Произошла ошибка при обработке. Попробуйте позже."


# ==========================================================
# ОБРАБОТКА КОМАНД И СООБЩЕНИЙ
# ==========================================================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message,
                 "🧠 Привет! Я твой умный дневник.\n\nПросто пиши мне о своём дне. \nИспользуй /q, чтобы вывести все записи (время будет +3ч).")


@bot.message_handler(commands=['clear'])
def clear_context(message):
    context = load_context()
    if str(message.chat.id) in context:
        del context[str(message.chat.id)]
        save_context(context)
        bot.reply_to(message, "🗑️ Память очищена! Начинаем с чистого листа.")
    else:
        bot.reply_to(message, "Память уже пуста.")


@bot.message_handler(commands=['q'])
def show_all_records(message):
    """Выводит все записи пользователя с учётом +3 часов"""
    context = load_context()
    user_context = context.get(str(message.chat.id), [])

    if not user_context:
        bot.reply_to(message, "📭 У тебя пока нет записей. Начни писать мне!")
        return

    records_text = "📋 **Твои записи (время сдвинуто на +3ч):**\n\n"
    for entry in user_context:
        original_time = datetime.fromisoformat(entry["timestamp"])
        shifted_time = original_time + timedelta(hours=3)
        time_str = shifted_time.strftime("%d.%m %H:%M")
        records_text += f"- [{time_str}] {entry['text']}\n"

    if records_text.strip():
        bot.reply_to(message, records_text, parse_mode="Markdown")
    else:
        bot.reply_to(message, "Не удалось сформировать список.")


@bot.message_handler(content_types=['text'])
def handle_message(message):
    """Обрабатывает обычные текстовые сообщения через ИИ"""
    user_id = message.chat.id
    user_text = message.text.strip()

    # Игнорируем пустые сообщения и команды (команды обрабатываются выше)
    if not user_text or user_text.startswith('/'):
        return

    add_to_context(user_id, user_text)
    ai_response = get_ai_response(user_text, user_id)

    # ЗАЩИТА: если ИИ вернул пустоту
    if not ai_response or not ai_response.strip():
        ai_response = "🤔 Хм, не знаю что ответить. Попробуй переформулировать."

    bot.reply_to(message, ai_response)


# ==========================================================
# НАСТРОЙКА WEBHOOK (для стабильной работы на PythonAnywhere)
# ==========================================================

app = Flask(__name__)


@app.route('/' + os.getenv("BOT_TOKEN"), methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    else:
        return 'Error', 403


if __name__ == "__main__":
    # Запускаем веб-сервер на порту 5000 (требование PythonAnywhere)
    app.run(host='0.0.0.0', port=5000, debug=False)