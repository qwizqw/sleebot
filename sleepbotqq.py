import telebot
import json
import os
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from groq import Groq
from flask import Flask, request

# ==========================================================
# НАСТРОЙКИ
# ==========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

DATA_DIR = Path("data")
CONTEXT_FILE = DATA_DIR / "context.json"
PROFILE_FILE = DATA_DIR / "profile.txt"
DATA_DIR.mkdir(exist_ok=True)

# Создаем файл профиля, если его нет
if not PROFILE_FILE.exists():
    PROFILE_FILE.write_text("Студент, изучаю Python, умею делать Telegram-ботов, ищу стажировку или Junior позицию.",
                            encoding="utf-8")

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
groq_client = Groq(api_key=GROQ_API_KEY)


# ==========================================================
# РАБОТА С КОНТЕКСТОМ И ПРОФИЛЕМ
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

    cutoff_date = datetime.now() - timedelta(days=15)
    context[str(user_id)] = [
        entry for entry in context[str(user_id)]
        if datetime.fromisoformat(entry["timestamp"]) > cutoff_date
    ]
    save_context(context)


def get_profile():
    return PROFILE_FILE.read_text(encoding="utf-8").strip()


def save_profile(text):
    PROFILE_FILE.write_text(text, encoding="utf-8")


# ==========================================================
# ПОИСК ВАКАНСИЙ HH.RU (Безопасный RSS метод)
# ==========================================================

def search_hh_vacancies(query):
    try:
        # Кодируем запрос для URL и добавляем User-Agent, чтобы hh.ru не блокировал
        encoded_query = urllib.parse.quote(query)
        url = f"https://search.hh.ru/vacancy/rss?text={encoded_query}&period=1"  # period=1: только за последние 24 часа

        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            xml_data = response.read()

        root = ET.fromstring(xml_data)
        vacancies = []

        # Берем максимум 3 свежие вакансии, чтобы не перегружать нейросеть
        for item in root.findall('.//item')[:3]:
            title = item.find('title').text
            link = item.find('link').text
            # Описание в RSS часто содержит HTML, берем первые 200 символов для анализа
            desc = item.find('description').text
            clean_desc = desc[:300].replace('\n', ' ').strip() + "..."
            vacancies.append(f"Название: {title}\nОписание: {clean_desc}\nСсылка: {link}")

        return vacancies
    except Exception as e:
        print(f"Ошибка поиска hh.ru: {e}")
        return []


# ==========================================================
# ИНТЕГРАЦИЯ С НЕЙРОСЕТЬЮ
# ==========================================================

def get_ai_response(user_message, user_id, is_job_search=False, vacancies_text=""):
    context_summary = "Это первое сообщение."
    if not is_job_search:
        context = load_context()
        user_context = context.get(str(user_id), [])
        if user_context:
            context_summary = "История записей:\n"
            for entry in user_context[-15:]:
                date = datetime.fromisoformat(entry["timestamp"]).strftime("%d.%m %H:%M")
                context_summary += f"[{date}] {entry['text']}\n"

    user_profile = get_profile()

    if is_job_search and vacancies_text:
        system_prompt = f"""Ты — профессиональный карьерный консультант и помощник в поиске работы.
Профиль пользователя: {user_profile}

Найденные вакансии:
{vacancies_text}

Твоя задача:
1. Кратко (1 предложение на каждую) оцени, насколько вакансия подходит профилю пользователя.
2. Выбери ОДНУ самую подходящую вакансию.
3. Напиши для неё готовое, профессиональное и живое сопроводительное письмо, которое пользователь сможет просто скопировать и вставить на hh.ru. Не используй шаблонные фразы вроде "Я увидел вашу вакансию". Пиши конкретно по делу."""
    else:
        system_prompt = f"""Ты — умный персональный помощник и дневник.
ПРАВИЛА:
1. ВСЕГДА отвечай полностью, НИКОГДА не обрывай текст.
2. Анализируй привычки, давай короткие советы (2-4 предложения).
3. Помни: пользователь просил сдвигать время в записях на +3 часа при выводе.

Контекст:
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
            max_tokens=2000,
            top_p=1,
            stream=False,
        )
        return completion.choices[0].message.content
    except Exception as e:
        print(f"Ошибка Groq API: {e}")
        return "⚠️ Ошибка нейросети. Попробуйте позже."


# ==========================================================
# ОБРАБОТКА КОМАНД И СООБЩЕНИЙ
# ==========================================================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message,
                 "🧠 Привет! Я твой умный помощник.\n\n📝 Пиши о своём дне (я всё запомню).\n🔍 Используй /find <запрос>, чтобы найти вакансии на hh.ru и получить готовое сопроводительное письмо.\n⚙️ Используй /profile <текст>, чтобы обновить свои навыки.")


@bot.message_handler(commands=['clear'])
def clear_context(message):
    context = load_context()
    if str(message.chat.id) in context:
        del context[str(message.chat.id)]
        save_context(context)
        bot.reply_to(message, "🗑️ Память очищена!")


@bot.message_handler(commands=['q'])
def show_all_records(message):
    context = load_context()
    user_context = context.get(str(message.chat.id), [])
    if not user_context:
        bot.reply_to(message, "📭 У тебя пока нет записей.")
        return

    records_text = "📋 **Твои записи (время +3ч):**\n\n"
    for entry in user_context:
        original_time = datetime.fromisoformat(entry["timestamp"])
        shifted_time = original_time + timedelta(hours=3)
        time_str = shifted_time.strftime("%d.%m %H:%M")
        records_text += f"- [{time_str}] {entry['text']}\n"

    bot.reply_to(message, records_text, parse_mode="Markdown")


@bot.message_handler(commands=['profile'])
def set_profile(message):
    # Берем весь текст после команды /profile
    new_profile = message.text.replace('/profile', '', 1).strip()
    if new_profile:
        save_profile(new_profile)
        bot.reply_to(message, f"✅ Профиль обновлен!\n\nТеперь я знаю о тебе: \n_{new_profile}_", parse_mode="Markdown")
    else:
        bot.reply_to(message,
                     f"📄 Твой текущий профиль:\n\n_{get_profile()}_\n\nЧтобы изменить, напиши: `/profile Твои новые навыки`",
                     parse_mode="Markdown")


@bot.message_handler(commands=['find'])
def find_jobs(message):
    query = message.text.replace('/find', '', 1).strip()
    if not query:
        bot.reply_to(message, "❌ Укажи запрос. Пример: `/find python junior удаленно`")
        return

    bot.reply_to(message, "⏳ Ищу свежие вакансии на hh.ru и анализирую их... (это займет ~10 секунд)")

    vacancies = search_hh_vacancies(query)

    if not vacancies:
        bot.reply_to(message,
                     "😕 По запросу ничего не найдено за последние 24 часа. Попробуй изменить формулировку (например, убери 'junior' или добавь город).")
        return

    vacancies_text = "\n---\n".join(vacancies)
    ai_response = get_ai_response(query, message.chat.id, is_job_search=True, vacancies_text=vacancies_text)

    # Отправляем ответ частями, если он слишком длинный для Telegram (лимит 4096 символов)
    if len(ai_response) > 4000:
        bot.reply_to(message, ai_response[:4000] + "\n\n...(сообщение обрезано из-за длины, но письмо выше)")
    else:
        bot.reply_to(message, ai_response)


@bot.message_handler(content_types=['text'])
def handle_message(message):
    user_id = message.chat.id
    user_text = message.text.strip()

    if not user_text or user_text.startswith('/'):
        return

    add_to_context(user_id, user_text)
    ai_response = get_ai_response(user_text, user_id)

    if not ai_response or not ai_response.strip():
        ai_response = "🤔 Хм, не знаю что ответить. Попробуй переформулировать."

    bot.reply_to(message, ai_response)


# ==========================================================
# WEBHOOK (для PythonAnywhere)
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
    app.run(host='0.0.0.0', port=5000, debug=False)