import os
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import urlparse
import requests

import telebot
import schedule

# Получение токенов из переменных окружения
BOT_TOKEN = os.environ.get('BOT_TOKEN')

if not BOT_TOKEN:
    print("Ошибка: Необходимо установить переменную окружения BOT_TOKEN")
    exit(1)

# Инициализация бота
bot = telebot.TeleBot(BOT_TOKEN)

# Глобальные словари для хранения данных
user_sources = {}      # {telegram_id: [url1, url2]}
sent_articles = {}     # {telegram_id: [link1, link2]}
news_count = {}        # {telegram_id: 0}
user_states = {}       # {telegram_id: 'waiting_for_sources'}

# Лимит бесплатных новостей
FREE_NEWS_LIMIT = 10

def parse_rss_feed(url):
    """Парсит RSS-ленту с помощью requests и xml.etree"""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        root = ET.fromstring(response.content)
        
        # Находим все элементы item
        items = []
        for item in root.findall('.//item'):
            title = item.find('title')
            description = item.find('description')
            link = item.find('link')
            
            if title is not None and link is not None:
                items.append({
                    'title': title.text or '',
                    'summary': description.text if description is not None else '',
                    'link': link.text or ''
                })
        
        return items
    except Exception as e:
        print(f"Ошибка при парсинге RSS: {e}")
        return []

def is_valid_rss_url(url):
    """Проверяет, является ли URL валидной RSS-лентой"""
    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return False
        
        # Попробуем загрузить и распарсить RSS
        items = parse_rss_feed(url)
        return len(items) > 0
    except:
        return False

def process_article(article_data):
    """Обрабатывает статью и возвращает готовый пост"""
    try:
        title = article_data.get('title', 'Без заголовка')
        summary = article_data.get('summary', '')
        link = article_data.get('link', '')
        
        # Простая обработка
        processed_text = f"📰 {title}\n\n{summary}\n\n🔗 Источник: {link}"
        
        return processed_text
        
    except Exception as e:
        print(f"Ошибка при обработке статьи: {e}")
        # Возвращаем базовую версию
        title = article_data.get('title', 'Без заголовка')
        summary = article_data.get('summary', '')
        link = article_data.get('link', '')
        
        return f"📰 {title}\n\n{summary}\n\n🔗 Источник: {link}"

def monitor_news():
    """Функция мониторинга новостей, запускается по расписанию"""
    print(f"[{datetime.now()}] Запуск мониторинга новостей...")
    
    for user_id, sources in user_sources.items():
        # Проверяем лимит новостей
        if news_count.get(user_id, 0) >= FREE_NEWS_LIMIT:
            continue
            
        try:
            for source_url in sources:
                # Парсим RSS-ленту
                items = parse_rss_feed(source_url)
                
                if not items:
                    continue
                
                # Получаем список уже отправленных статей
                user_sent = sent_articles.get(user_id, [])
                
                # Проверяем новые статьи
                for item in items[:5]:  # Берем только последние 5 статей
                    article_link = item.get('link', '')
                    
                    if article_link and article_link not in user_sent:
                        # Обрабатываем статью
                        post = process_article(item)
                        
                        # Отправляем пост пользователю
                        try:
                            bot.send_message(user_id, post, parse_mode='HTML')
                            
                            # Обновляем данные
                            if user_id not in sent_articles:
                                sent_articles[user_id] = []
                            sent_articles[user_id].append(article_link)
                            
                            news_count[user_id] = news_count.get(user_id, 0) + 1
                            
                            print(f"[{datetime.now()}] Отправлена новость пользователю {user_id}")
                            
                            # Проверяем лимит после отправки
                            if news_count.get(user_id, 0) >= FREE_NEWS_LIMIT:
                                bot.send_message(
                                    user_id,
                                    "�� Пробный период завершен. Вы получили 10 новостных постов. "
                                    "Если вы хотите продолжить использовать 'Новостного Агента' без ограничений, "
                                    "свяжитесь с нами для настройки полной версии: @newsagent_support"
                                )
                                break
                                
                        except Exception as e:
                            print(f"Ошибка отправки сообщения пользователю {user_id}: {e}")
                
        except Exception as e:
            print(f"Ошибка при обработке источников пользователя {user_id}: {e}")

def run_scheduler():
    """Запускает планировщик в отдельном потоке"""
    schedule.every().hour.do(monitor_news)
    
    while True:
        schedule.run_pending()
        time.sleep(60)  # Проверяем каждую минуту

# Команда /start
@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    
    # Обнуляем данные пользователя
    user_sources[user_id] = []
    sent_articles[user_id] = []
    news_count[user_id] = 0
    user_states[user_id] = 'waiting_for_sources'
    
    welcome_text = (
        "�� Добро пожаловать в 'Новостной Агент'!\n\n"
        "Я помогу вам получать новости из ваших RSS-источников.\n\n"
        "📋 Как начать:\n"
        "1. Пришлите мне ссылки на RSS-ленты (по одной в сообщении)\n"
        "2. Когда закончите, отправьте команду /done\n\n"
        "🎁 Пробный период: 10 бесплатных новостей\n"
        "⏰ Проверка новостей: каждый час\n\n"
        "Присылайте ваши RSS-ссылки!"
    )
    
    bot.send_message(user_id, welcome_text)

# Команда /done
@bot.message_handler(commands=['done'])
def done_command(message):
    user_id = message.from_user.id
    
    if user_id not in user_sources or not user_sources[user_id]:
        bot.send_message(
            user_id,
            "❌ Вы еще не добавили ни одного RSS-источника. "
            "Пожалуйста, сначала пришлите ссылки на RSS-ленты."
        )
        return
    
    user_states[user_id] = 'monitoring'
    
    sources_count = len(user_sources[user_id])
    sources_list = "\n".join([f"• {url}" for url in user_sources[user_id]])
    
    confirmation_text = (
        f"✅ Отлично! Настройка завершена.\n\n"
        f"📊 Добавлено источников: {sources_count}\n"
        f"�� Источники:\n{sources_list}\n\n"
        f"�� Мониторинг запущен! Я буду проверять новости каждый час.\n"
        f"📬 Новости будут приходить автоматически.\n\n"
        f"�� Осталось бесплатных новостей: {FREE_NEWS_LIMIT}"
    )
    
    bot.send_message(user_id, confirmation_text)

# Команда /status
@bot.message_handler(commands=['status'])
def status_command(message):
    user_id = message.from_user.id
    
    if user_id not in user_sources:
        bot.send_message(
            user_id,
            "❌ Вы еще не начали работу с ботом. Используйте /start для начала."
        )
        return
    
    sources_count = len(user_sources.get(user_id, []))
    sent_count = news_count.get(user_id, 0)
    remaining = FREE_NEWS_LIMIT - sent_count
    
    status_text = (
        f"📊 Ваша статистика:\n\n"
        f"📰 RSS-источников: {sources_count}\n"
        f"📬 Отправлено новостей: {sent_count}\n"
        f"🎁 Осталось бесплатных: {remaining}\n\n"
        f"🔄 Статус: {'Активен' if remaining > 0 else 'Пробный период завершен'}"
    )
    
    bot.send_message(user_id, status_text)

# Обработка текстовых сообщений (RSS-ссылки)
@bot.message_handler(func=lambda message: True)
def handle_text_message(message):
    user_id = message.from_user.id
    text = message.text.strip()
    
    # Проверяем состояние пользователя
    if user_states.get(user_id) != 'waiting_for_sources':
        bot.send_message(
            user_id,
            "❓ Неизвестная команда. Используйте /start для начала работы или /status для проверки статистики."
        )
        return
    
    # Проверяем, является ли текст URL
    if not (text.startswith('http://') or text.startswith('https://')):
        bot.send_message(
            user_id,
            "❌ Пожалуйста, пришлите корректную ссылку на RSS-ленту (начинающуюся с http:// или https://)"
        )
        return
    
    # Проверяем валидность RSS-ссылки
    if not is_valid_rss_url(text):
        bot.send_message(
            user_id,
            "❌ Не удалось загрузить RSS-ленту по этой ссылке. "
            "Пожалуйста, проверьте корректность ссылки и попробуйте еще раз."
        )
        return
    
    # Добавляем источник
    if user_id not in user_sources:
        user_sources[user_id] = []
    
    if text in user_sources[user_id]:
        bot.send_message(
            user_id,
            "⚠️ Этот источник уже добавлен."
        )
        return
    
    user_sources[user_id].append(text)
    
    # Получаем название RSS-ленты
    try:
        items = parse_rss_feed(text)
        feed_title = "RSS-лента" if items else "RSS-лента"
    except:
        feed_title = 'RSS-лента'
    
    bot.send_message(
        user_id,
        f"✅ Источник добавлен: {feed_title}\n"
        f"�� {text}\n\n"
        f"�� Всего источников: {len(user_sources[user_id])}\n"
        f"📝 Когда закончите добавлять источники, отправьте /done"
    )

# Запуск планировщика в отдельном потоке
scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
scheduler_thread.start()

if __name__ == "__main__":
    print("🤖 Запуск 'Новостного Агента'...")
    print("📅 Планировщик запущен (проверка каждый час)")
    print("�� Бот готов к работе!")
    
    try:
        bot.polling(none_stop=True)
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен пользователем")
    except Exception as e:
        print(f"❌ Ошибка при запуске бота: {e}")
