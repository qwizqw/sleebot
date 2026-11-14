import telebot
import json
import os
import urllib.request
import urllib.parse
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
    PROFILE_FILE.write_text(
        "Студент, изучаю Python, умею делать Telegram-ботов, ищу стажировку или Junior позицию.",
        encoding="utf-8",
    )

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
        "text": message_text,
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
# ПОИСК ВАКАНСИЙ HH.RU (Официальный API)
# ==========================================================

def search_hh_vacancies(query):
    try:
        import xml.etree.ElementTree as ET
        import re

        encoded_query = urllib.parse.quote(query)
        # Используем RSS-канал, он гораздо реже блокируется защитой
        url = f"https://hh.ru/search/vacancy/rss?text={encoded_query}"

        # Заголовки настоящего браузера Chrome, чтобы обмануть DDoS-Guard
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/rss+xml, application/xml, text/xml, */*',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'Referer': 'https://hh.ru/'
        }

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response:
            xml_data = response.read()

        root = ET.fromstring(xml_data)
        vacancies = []

        # Берем до 5 первых вакансий
        for item in root.findall('.//item')[:5]:
            title = item.find('title').text if item.find('title') is not None else "Без названия"
            link = item.find('link').text if item.find('link') is not None else ""
            desc = item.find('description').text if item.find('description') is not None else ""

            # Очищаем описание от HTML-тегов (<p>, <br> и т.д.) и обрезаем до 250 символов
            clean_desc = re.sub(r'<[^>]+>', ' ', desc)
            clean_desc = re.sub(r'\s+', ' ', clean_desc).strip()[:250] + "..."

            vacancies.append(f"📌 {title}\n📝 {clean_desc}\n🔗 {link}")

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
    1. Кратко (1-2 предложения на каждую) оцени, насколько вакансия подходит профилю пользователя.
    2. Выбери ОДНУ самую подходящую вакансию.
    3. ОБЯЗАТЕЛЬНО выведи ссылку на эту выбранную вакансию (скопируй её из блока "Найденные вакансии" после слова "🔗").
    4. Напиши для неё готовое, профессиональное и живое сопроводительное письмо, которое пользователь сможет просто скопировать и вставить на hh.ru. Не используй шаблонные фразы вроде "Я увидел вашу вакансию". Пиши конкретно по делу."""
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
                {"role": "user", "content": user_message},
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

@bot.message_handler(commands=["start"])
def send_welcome(message):
    bot.reply_to(
        message,
        "🧠 Привет! Я твой умный помощник.\n\n"
        "📝 Пиши о своём дне (я всё запомню).\n"
        "🔍 Используй /find <запрос>, чтобы найти вакансии на hh.ru и получить готовое сопроводительное письмо.\n"
        "⚙️ Используй /profile <текст>, чтобы обновить свои навыки.\n"
        "📋 Используй /q, чтобы вывести все свои записи (время +3ч).",
    )

@bot.message_handler(commands=['help'])
def send_help(message):
    help_text = (
        "🤖 **Доступные команды:**\n\n"
        "📝 *Просто напиши текст* — я запомню это как запись в дневнике и дам совет.\n"
        "🔍 `/find <запрос>` — найти вакансии на hh.ru и получить готовое сопроводительное письмо.\n"
        "📋 `/q` — вывести все твои записи (время сдвинуто на +3ч).\n"
        "⚙️ `/profile <текст>` — обновить информацию о твоих навыках и целях для поиска работы.\n"
        "🗑️ `/clear` — очистить историю записей.\n"
        "❓ `/help` — показать это сообщение."
    )
    bot.reply_to(message, help_text, parse_mode="Markdown")

@bot.message_handler(commands=["clear"])
def clear_context(message):
    context = load_context()
    if str(message.chat.id) in context:
        del context[str(message.chat.id)]
        save_context(context)
        bot.reply_to(message, "🗑️ Память очищена!")

@bot.message_handler(commands=["q"])
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

@bot.message_handler(commands=["profile"])
def set_profile(message):
    new_profile = message.text.replace("/profile", "", 1).strip()
    if new_profile:
        save_profile(new_profile)
        bot.reply_to(
            message,
            f"✅ Профиль обновлен!\n\nТеперь я знаю о тебе: \n_{new_profile}_",
            parse_mode="Markdown",
        )
    else:
        bot.reply_to(
            message,
            f"📄 Твой текущий профиль:\n\n_{get_profile()}_\n\n"
            "Чтобы изменить, напиши: `/profile Твои новые навыки`",
            parse_mode="Markdown",
        )

@bot.message_handler(commands=["find"])
def find_jobs(message):
    query = message.text.replace("/find", "", 1).strip()
    if not query:
        bot.reply_to(message, "❌ Укажи запрос. Пример: `/find python junior удаленно`")
        return

    bot.reply_to(message, "⏳ Ищу вакансии на hh.ru и анализирую их... (это займет ~10 секунд)")

    vacancies = search_hh_vacancies(query)

    if not vacancies:
        bot.reply_to(
            message,
            "😕 По запросу ничего не найдено. Попробуй изменить формулировку "
            "(например, убери 'junior', напиши город отдельно или используй синонимы).",
        )
        return

    vacancies_text = "\n---\n".join(vacancies)
    ai_response = get_ai_response(
        query, message.chat.id, is_job_search=True, vacancies_text=vacancies_text
    )

    if len(ai_response) > 4000:
        bot.reply_to(message, ai_response[:4000] + "\n\n...(сообщение обрезано из-за длины)")
    else:
        bot.reply_to(message, ai_response)

@bot.message_handler(content_types=["text"])
def handle_message(message):
    user_id = message.chat.id
    user_text = message.text.strip()

    if not user_text or user_text.startswith("/"):
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

@app.route("/" + os.getenv("BOT_TOKEN"), methods=["POST"])
def webhook():
    if request.headers.get("content-type") == "application/json":
        json_string = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "", 200
    else:
        return "Error", 403

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)