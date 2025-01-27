import os
import ipaddress
import json
import re
import time
from pathlib import Path
from typing import Dict, Any
import paramiko
import asyncio
from telethon import TelegramClient, events, Button


# ---------- Конфигурация ----------
CONFIG_FILE = Path('config.json')
with CONFIG_FILE.open('r', encoding="utf-8") as config_file:
    config = json.load(config_file)

# ---------- Константы ----------
API_ID = config['API_ID']
API_HASH = config['API_HASH']
BOT_TOKEN = config['BOT_TOKEN']
SERVERS_FILE = Path('servers.json')
SSH_TIMEOUT = 300  # 5 minutes in seconds

# ---------- Настройка Telegram клиента ----------
bot = TelegramClient('bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# ---------- Управление состоянием ----------
user_servers: Dict[str, Any] = {}  # Loaded from servers.json
console_mode: Dict[int, bool] = {}
ssh_connections: Dict[int, paramiko.SSHClient] = {}
last_activity: Dict[int, float] = {}
session_start_times: Dict[int, float] = {}

# ---------- Операции с файлами ----------
# сохраняет данные серверов в JSON файл
def save_servers():
    global user_servers
    with open(SERVERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(user_servers, f, ensure_ascii=False, indent=4)

# Загружает данные серверов из JSON файла
def load_servers():
    global user_servers
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

# Проверяет корректность введенных данных сервера
def validate_server_input(server_string):
    """Проверка формата ввода сервера"""
    try:
        name, ip, user, password = server_string.split(':')

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

# разделяем длинные сообщения на несколько частей
async def send_long_message(event, message):
    for i in range(0, len(message), 4096):
        await event.reply(message[i:i + 4096])
        
# ---------- Управление сессиями ----------
def format_remaining_time(user_id: int) -> str:
    """Format remaining SSH session time for display."""
    if user_id not in last_activity:
        return "Нет активных сессий"
    
    elapsed = time.time() - last_activity[user_id]
    remaining = SSH_TIMEOUT - elapsed
    
    if remaining <= 0:
        return "Session ending"
        
    minutes = int(remaining // 60)
    seconds = int(remaining % 60)
    return f"Time remaining: {minutes}m {seconds}s"

# Периодически проверяет и закрывает неактивные SSH соединения
async def maintain_ssh_connections():
    while True:
        current_time = time.time()
        to_close = []
        
        for user_id in last_activity:
            if current_time - last_activity[user_id] > SSH_TIMEOUT:
                to_close.append(user_id)
                
        for user_id in to_close:
            if user_id in ssh_connections:
                try:
                    ssh_connections[user_id].close()
                except Exception:
                    print(f"Ошибка при закрытии соединения с {user_id}")
                    pass
                del ssh_connections[user_id]
                del last_activity[user_id]
                console_mode[user_id] = False
                
        await asyncio.sleep(60)  # Проверка


# Создает или возвращает существующее SSH соединение для пользователя
async def get_ssh_connection(user_id, server):
    if user_id in ssh_connections and ssh_connections[user_id].get_transport() and ssh_connections[user_id].get_transport().is_active():
        return ssh_connections[user_id]
    
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            server['ip'],
            username=server['username'],
            password=server['password'],
            timeout=10
        )
        ssh_connections[user_id] = ssh
        last_activity[user_id] = time.time()
        return ssh
    except Exception as e:
        raise Exception(f"Ошибка подключения: {str(e)}")

# Выполняет SSH команду через постоянное соединение
async def execute_ssh_command(ip, username, password, command, user_id=None, event=None):    
    try:
        server = user_servers[user_id]
        ssh = await get_ssh_connection(user_id, server)
        last_activity[user_id] = time.time()
        
        stdin, stdout, stderr = ssh.exec_command(command)
        stdin.close() # закрываем для явного завершения ввода
        output = stdout.read().decode()
        error = stderr.read().decode()
        
        return output if output else error
    except Exception as e:
        return f"Ошибка: {str(e)}"

# Отображает главное меню с списком серверов
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

# Отображает меню управления для конкретного сервера
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

# ---------- Обработчики событий ----------
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
    global console_mode
    user_id = str(event.sender_id)

    # Пропуск команд
    if event.raw_text.startswith('/'):
        return
    
    # режим консоли
    if user_id in console_mode and console_mode[user_id]:
        if event.raw_text.lower() == 'exit':
            console_mode[user_id] = False
            if user_id in ssh_connections:
                ssh_connections[user_id].close()
                del ssh_connections[user_id]
                if user_id in last_activity:
                    del last_activity[user_id]
            buttons = [
                [Button.inline('🔄 Продолжить', 'continue_console')],
                [Button.inline('⬅️ Главное меню', 'back_to_main')]
            ]
            await event.reply('Выход из режима консоли', buttons=buttons)
            return
            
        if user_id in user_servers:
            server = user_servers[user_id]
            
            # Проверяем, существует ли активная сессия
            if int(user_id) not in last_activity:
                last_activity[int(user_id)] = time.time()
                session_start_times[int(user_id)] = time.time()
            
            result = await execute_ssh_command(
                server['ip'],
                server['username'],
                server['password'],
                event.raw_text,
                user_id
            )
            remaining_time = format_remaining_time(int(user_id))
            buttons = [
                [Button.inline('❌ Выход', 'exit_console')],
                [Button.inline('🔄Продлить сессию', 'console_time_add')]
            ]
            # Добавляем проверку длины сообщения
            formatted_result = f'```\n{result}\n```\n{remaining_time}'
            if len(formatted_result) > 4096:
                await send_long_message(event, formatted_result)
                # Отправляем кнопки отдельным сообщением
                await event.reply('Управление консолью:', buttons=buttons)
            else:
                await event.reply(formatted_result, buttons=buttons)
            return

    # добавление сервера    
    if ':' in event.raw_text:
        is_valid, error_message = validate_server_input(event.raw_text)
        if not is_valid:
            await event.reply(f'❌ {error_message}')
            return

        try:
            name, ip, username, password = event.raw_text.split(':')

            # SSH подключение
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
            await event.reply(f'❌ Ошибка при добавлении сервера {e}')
    else:
        if user_id in user_servers:
            await show_main_menu(event)
        else:
            await event.reply('Добавьте сервер в формате:\nназвание:IP:пользователь:пароль')

# Обработчик нажатий на кнопки
@bot.on(events.CallbackQuery)
async def callback_handler(event):
    global console_mode
    data = event.data.decode()
    user_id = str(event.sender_id)

    if data == 'back_to_main':
        await show_main_menu(event)
        return

    if data.startswith('console:'):
        server_name = data.split(':')[1]
        console_mode[user_id] = True
        await event.edit(
            "📟 Режим консоли активирован\n"
            "Введите команду для выполнения\n"
            "Для выхода напишите 'exit'"
        )
        return
    
    if data == 'continue_console':
        console_mode[user_id] = True
        await event.edit('Режим консоли активирован')
    elif data == 'exit_console':
        console_mode[user_id] = False
        await event.edit('Выход из консоли')
        await show_main_menu(event)
    elif data == 'back_to_main':
        await show_main_menu(event)
    if data.startswith('server:'):
        server_name = data.split(':')[1]
        await show_server_menu(event, server_name)
        return
        
    if data.startswith(('console:', 'stats:', 'reboot:', 'files:', 'security:')):
        action = data.split(':')[0]
        messages = {
            'console': 'console',
            'stats': 'stats',
            'reboot': 'reboot',
            'files': 'files',
            'security': 'security'
        }
        await event.answer(messages[action])

if __name__ == '__main__':
    print('Bot started time:', time.asctime())
    
    # Создаем и получаем event loop
    loop = asyncio.get_event_loop()
    
    # Создаем и запускаем задачу поддержки SSH соединений
    loop.create_task(maintain_ssh_connections())
    
    # Запускаем бота
    bot.run_until_disconnected()