import os
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

import telebot
import json
from datetime import datetime, timedelta
from pathlib import Path
import os
from groq import Groq

# ==========================================================
# НАСТРОЙКИ
# ==========================================================

# Telegram Bot Token (от @BotFather)

# Groq API Key (бесплатный с console.groq.com)
# (Я взял тот, что был у вас в комментарии с gsk_)

# Путь к файлам (для PythonAnywhere используйте /home/username/)
DATA_DIR = Path("data")
CONTEXT_FILE = DATA_DIR / "context.json"

# Создаем папку для данных
DATA_DIR.mkdir(exist_ok=True)

# ==========================================================
# ИНИЦИАЛИЗАЦИЯ
# ==========================================================

bot = telebot.TeleBot(BOT_TOKEN)
groq_client = Groq(api_key=GROQ_API_KEY)


# ==========================================================
# РАБОТА С КОНТЕКСТОМ
# ==========================================================

def load_context():
    """Загружает контекст из файла"""
    if CONTEXT_FILE.exists():
        with open(CONTEXT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_context(context):
    """Сохраняет контекст в файл"""
    with open(CONTEXT_FILE, "w", encoding="utf-8") as f:
        json.dump(context, f, ensure_ascii=False, indent=2)


def add_to_context(user_id, message_text):
    """Добавляет сообщение в контекст пользователя"""
    context = load_context()

    if str(user_id) not in context:
        context[str(user_id)] = []

    # Добавляем новое сообщение с временной меткой
    context[str(user_id)].append({
        "timestamp": datetime.now().isoformat(),
        "text": message_text
    })

    # Оставляем только последние 10 дней
    cutoff_date = datetime.now() - timedelta(days=10)
    context[str(user_id)] = [
        entry for entry in context[str(user_id)]
        if datetime.fromisoformat(entry["timestamp"]) > cutoff_date
    ]

    save_context(context)
    return context[str(user_id)]


def get_context_summary(user_id):
    """Формирует краткое резюме контекста для нейросети"""
    context = load_context()
    user_context = context.get(str(user_id), [])

    if not user_context:
        return "Это первое сообщение пользователя."

    summary = "Последние записи пользователя (до 10 дней):\n\n"
    for entry in user_context[-20:]:  # Последние 20 записей
        date = datetime.fromisoformat(entry["timestamp"]).strftime("%d.%m %H:%M")
        summary += f"[{date}] {entry['text']}\n"

    return summary


# ==========================================================
# ИНТЕГРАЦИЯ С НЕЙРОСЕТЬЮ
# ==========================================================

def get_ai_response(user_message, user_id):
    """Отправляет запрос в Groq API с контекстом"""

    # Получаем контекст пользователя
    context_summary = get_context_summary(user_id)

    # Системный промпт с инструкциями
    system_prompt = f"""Ты — умный персональный помощник и дневник.
    ПРАВИЛА:
    1. ВСЕГДА отвечай полностью, не обрывай текст на полуслове.
    2. Если пользователь просит вывести записи, выводи их списком. 
    3. ВАЖНО: Пользователь попросил сдвигать время в записях на +3 часа. Всегда прибавляй 3 часа к времени из контекста при выводе.
    4. Анализируй сон и привычки, давай короткие и полезные советы (2-4 предложения).
    5. Отвечай дружелюбно, по-русски.

    Контекст записей пользователя:
    {context_summary}
    """

    # Формируем сообщение для API
    messages = [
        {"role": "system", "content": system_prompt + context_summary},
        {"role": "user", "content": user_message}
    ]

    try:
        # Отправляем запрос в Groq
        completion = groq_client.chat.completions.create(
            model="openai/gpt-oss-120b",  # <-- Самая мощная доступная модель
            messages=messages,
            temperature=0.7,
            max_tokens=500,
            top_p=1,
            stream=False,
        )

        return completion.choices[0].message.content

    except Exception as e:
        print(f"Ошибка Groq API: {e}")
        return "⚠️ Произошла ошибка при обработке. Попробуйте позже."


# ==========================================================
# ОБРАБОТКА СООБЩЕНИЙ
# ==========================================================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    """Приветственное сообщение"""
    welcome_text = (
        "🧠 Привет! Я твой умный дневник с нейросетью.\n\n"
        "Я буду:\n"
        "• Запоминать всё, что ты пишешь (до 10 дней)\n"
        "• Анализировать твои привычки и паттерны\n"
        "• Давать полезные советы\n"
        "• Поддерживать тебя!\n\n"
        "Просто пиши мне о своём дне, мыслях, планах.\n"
        "Например:\n"
        "• 'Сегодня спал 6 часов, чувствую себя разбитым'\n"
        "• 'Сделал тренировку, горжусь собой!'\n"
        "• 'Не могу сосредоточиться на работе'\n\n"
        "Попробуй написать что-нибудь!"
    )
    bot.reply_to(message, welcome_text)


@bot.message_handler(commands=['stats'])
def show_stats(message):
    """Показывает статистику записей"""
    context = load_context()
    user_context = context.get(str(message.chat.id), [])

    if not user_context:
        bot.reply_to(message, "📊 Пока нет записей. Начни писать мне!")
        return

    total_entries = len(user_context)
    first_date = datetime.fromisoformat(user_context[0]["timestamp"]).strftime("%d.%m.%Y")
    last_date = datetime.fromisoformat(user_context[-1]["timestamp"]).strftime("%d.%m.%Y")

    stats_text = (
        f"📊 **Твоя статистика:**\n\n"
        f"📝 Всего записей: {total_entries}\n"
        f"📅 Первая запись: {first_date}\n"
        f"📅 Последняя запись: {last_date}\n\n"
        f"Я анализирую последние 10 дней и готов давать советы!"
    )
    bot.reply_to(message, stats_text, parse_mode="Markdown")


@bot.message_handler(commands=['clear'])
def clear_context(message):
    """Очищает контекст пользователя"""
    context = load_context()
    if str(message.chat.id) in context:
        del context[str(message.chat.id)]
        save_context(context)
        bot.reply_to(message, "🗑️ Контекст очищен! Начинаем с чистого листа.")
    else:
        bot.reply_to(message, "Контекст уже пуст.")


@bot.message_handler(func=lambda message: True)
def handle_message(message):
    """Обрабатывает все обычные сообщения"""
    user_id = message.chat.id
    user_text = message.text

    # Сохраняем сообщение в контекст
    add_to_context(user_id, user_text)

    # Получаем ответ от нейросети
    ai_response = get_ai_response(user_text, user_id)

    # Отправляем ответ
    bot.reply_to(message, ai_response)


# ==========================================================
# ЗАПУСК
# ==========================================================

if __name__ == "__main__":
    print("🤖 Умный дневник запущен...")
    print("Бот анализирует контекст до 10 дней и дает советы!")
    bot.polling(none_stop=True)