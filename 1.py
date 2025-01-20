from telethon import TelegramClient, events
import os
import json

# Загружаем конфигурационные данные из config.json
with open('config.json', 'r') as config_file:
    config = json.load(config_file)

API_ID = config['API_ID']
API_HASH = config['API_HASH']
BOT_TOKEN = config['BOT_TOKEN']

# Создаем клиент бота
bot = TelegramClient('bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# Обработчик команды /start
@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    await event.reply('Привет! Я бот на Telethon.')



if __name__ == '__main__':
    print('Бот запущен')
    bot.run_until_disconnected()