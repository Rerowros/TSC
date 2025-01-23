from telethon import TelegramClient, events, Button
import os
import json
import paramiko
import asyncio
import re
import ipaddress

# Загружаем конфигурационные данные из config.json
with open('config.json', 'r') as config_file:
    config = json.load(config_file)
    
API_ID = config['API_ID']
API_HASH = config['API_HASH']
BOT_TOKEN = config['BOT_TOKEN']

bot = TelegramClient('bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)
    
SERVERS_FILE = 'servers.json'
user_servers = {}  # Инициализация глобальной переменной

def save_servers():
    global user_servers  # Указываем, что используем глобальную переменную
    with open(SERVERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(user_servers, f, ensure_ascii=False, indent=4)

def load_servers():
    global user_servers  # Указываем, что используем глобальную переменную
    try:
        if os.path.exists(SERVERS_FILE):
            if os.path.getsize(SERVERS_FILE) > 0:
                with open(SERVERS_FILE, 'r', encoding='utf-8') as f:
                    user_servers = json.load(f)
                    return user_servers
            else:
                save_servers()
        else:
            save_servers()
        return {}
    except json.JSONDecodeError:
        print("Ошибка чтения JSON файла. Создаю новый.")
        save_servers()
        return {}




def validate_server_input(server_string):
    """Проверка формата ввода сервера"""
    try:
        name, ip, username, password = server_string.split(':')
        
        # Проверка минимальной длины полей
        if len(name) < 3 or len(username) < 2 or len(password) < 4:
            return False, "Слишком короткое имя сервера, имя пользователя или пароль"
            
        # Проверка IP адреса
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            return False, "Неверный формат IP адреса"
            
        # Проверка символов в имени сервера
        if not re.match(r'^[a-zA-Z0-9_-]+$', name):
            return False, "Имя сервера может содержать только буквы, цифры, - и _"
            
        return True, None
    except ValueError:
        return False, "Неверный формат. Используйте: название:IP:пользователь:пароль"



async def show_main_menu(event):
    user_id = str(event.sender_id)
    if user_id not in user_servers:
        await event.reply('Добавьте сервер в формате:\nназвание:IP:пользователь:пароль')
        return
    
    buttons = []
    server_info = user_servers[user_id]
    server_button = Button.inline(f"🖥️ {server_info['name']}", f"server:{server_info['name']}")
    buttons.append([server_button])
    await event.reply('Выберите сервер:', buttons=buttons)

async def show_server_menu(event, server_name):
    buttons = [
        [Button.inline('📊 Статистика', f'stats:{server_name}')],
        [
            Button.inline('💻 Консоль', f'console:{server_name}'),
            Button.inline('🔄 Перезагрузка', f'reboot:{server_name}')
        ],
        [
            Button.inline('📁 Файлы', f'files:{server_name}'),
            Button.inline('🔒 Безопасность', f'security:{server_name}')
        ],
        [Button.inline('⬅️ Назад', 'back_to_main')]
    ]
    await event.edit('Управление сервером:', buttons=buttons)


@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    global user_servers
    user_servers = load_servers()  
    user_id = str(event.sender_id)
    
    if user_id in user_servers:
        await show_main_menu(event)
    else:
        await event.reply('Добавьте сервер в формате:\nназвание:IP:пользователь:пароль')

@bot.on(events.NewMessage)
async def message_handler(event):
    user_id = str(event.sender_id)
    
    if event.raw_text.startswith('/'):
        return
        
    if ':' in event.raw_text:
        is_valid, error_message = validate_server_input(event.raw_text)
        
        if not is_valid:
            await event.reply(f'❌ {error_message}')
            return
            
        try:
            name, ip, username, password = event.raw_text.split(':')
            
            # Проверка SSH подключения
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            try:
                ssh.connect(ip, username=username, password=password, timeout=10)
                ssh.close()
                
                user_servers[user_id] = {
                    'name': name,
                    'ip': ip,
                    'username': username,
                    'password': password
                }
                save_servers()
                
                try:
                    await event.message.delete()
                except Exception as e:
                    print(f"Ошибка при удалении сообщения: {e}")
                
                await event.reply(f'✅ Сервер {name} успешно добавлен!')
                await show_main_menu(event)
                
            except Exception as e:
                await event.reply(f'❌ Ошибка подключения к серверу: {str(e)}')
                
        except Exception as e:
            await event.reply('❌ Ошибка при добавлении сервера')
    else:
        if user_id in user_servers:
            await show_main_menu(event)
        else:
            await event.reply('Добавьте сервер в формате:\nназвание:IP:пользователь:пароль')




@bot.on(events.CallbackQuery)
async def callback_handler(event):
    data = event.data.decode()
    
    if data == 'back_to_main':
        await show_main_menu(event)
        return
        
    if data.startswith('server:'):
        server_name = data.split(':')[1]
        await show_server_menu(event, server_name)
        return
        
    if data.startswith(('console:', 'stats:', 'reboot:', 'files:', 'security:')):
        action = data.split(':')[0]
        server_name = data.split(':')[1]
        messages = {
            'console': 'console',
            'stats': 'stats',
            'reboot': 'reboot',
            'files': 'files',
            'security': 'security'
        }
        await event.answer(messages[action])

if __name__ == '__main__':
    print('Бот запущен')
    bot.run_until_disconnected()