"""
Super Quality Bot for Profit Tracking
Author: AI Assistant
Description: Полнофункциональный бот для учёта профитов с удобным интерфейсом,
             настройкой визуала (паки, карты, прозвон), статистикой и управлением.
             Команды в группах: только /top, /topd, /topw, /card, /prozvon, /help.
             Личные сообщения: полное меню с кнопками.
             Функция повторения стикеров удалена.
Используется Python 3.11+ и aiogram 3.x.
"""

import asyncio
import logging
import sqlite3
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, URLInputFile
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

# ==================== Конфигурация ====================
BOT_TOKEN = "8446547516:AAE7TpuEcdJjACpDzqcKol5gl8WxUWcAaoQ"
OWNER_ID = 7634532827

# Настройки базы данных
DB_NAME = "profits.db"

# Настройки логирования
logging.basicConfig(level=logging.INFO)

# ==================== Инициализация бота ====================
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ==================== Вспомогательная функция безопасного редактирования ====================
async def safe_edit_message(message: Message, text: str, reply_markup=None):
    """Редактирует сообщение, игнорируя ошибку 'message is not modified'."""
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            # Игнорируем - контент не изменился
            pass
        else:
            raise e

# ==================== Функция автоудаления сообщений ====================
async def delete_after_delay(bot: Bot, chat_id: int, user_msg_id: int, bot_msg_id: int, delay: int):
    """Удаляет сообщение пользователя и ответ бота через delay секунд."""
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, user_msg_id)
    except Exception:
        pass
    try:
        await bot.delete_message(chat_id, bot_msg_id)
    except Exception:
        pass

# ==================== Работа с базой данных ====================
def init_db():
    """Инициализация таблиц SQLite."""
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    # Таблица пользователей
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            joined_date TEXT,
            hide_name INTEGER DEFAULT 0,
            is_admin INTEGER DEFAULT 0
        )
    """)

    # Таблица профитов
    cur.execute("""
        CREATE TABLE IF NOT EXISTS profits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            date TEXT,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    """)

    # Таблица настроек (key-value)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # Устанавливаем настройки по умолчанию, если их нет
    default_settings = {
        'chat_id': '',  # ID чата для публикации профитов
        'card_text': 'Информация о картах отсутствует.',
        'prozvon_buttons': json.dumps([]),  # Список [{"text": "...", "url": "..."}]
        'packs_buttons': json.dumps([]),
        'alert_text': '🆕 <b>Новый профит!</b>\n\n🧑‍💻 Воркер: {user_name}\n💰 Профит: {amount} руб.',
        'alert_photo_url': '',  # Ссылка на изображение (Telegraph)
    }
    for key, value in default_settings.items():
        cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))

    conn.commit()
    conn.close()

# Вспомогательные функции для работы с БД
def db_get_user(user_id: int) -> Optional[Dict]:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, full_name, joined_date, hide_name, is_admin FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        return {
            'user_id': row[0],
            'username': row[1],
            'full_name': row[2],
            'joined_date': row[3],
            'hide_name': bool(row[4]),
            'is_admin': bool(row[5])
        }
    return None

def db_create_user(user_id: int, username: str = None, full_name: str = None):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO users (user_id, username, full_name, joined_date, hide_name, is_admin) VALUES (?, ?, ?, ?, 0, 0)",
        (user_id, username, full_name, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def db_update_user_hide(user_id: int, hide: bool):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE users SET hide_name=? WHERE user_id=?", (1 if hide else 0, user_id))
    conn.commit()
    conn.close()

def db_add_profit(user_id: int, amount: float):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO profits (user_id, amount, date) VALUES (?, ?, ?)",
        (user_id, amount, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def db_get_user_total_profit(user_id: int) -> float:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT SUM(amount) FROM profits WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row[0] else 0.0

def db_get_top_all(limit: int = 10) -> List[Dict]:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT u.user_id, u.username, u.full_name, u.hide_name, SUM(p.amount) as total
        FROM profits p
        JOIN users u ON u.user_id = p.user_id
        GROUP BY u.user_id
        ORDER BY total DESC
        LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    conn.close()
    result = []
    for row in rows:
        result.append({
            'user_id': row[0],
            'username': row[1],
            'full_name': row[2],
            'hide_name': bool(row[3]),
            'total': row[4]
        })
    return result

def db_get_top_daily(limit: int = 10) -> List[Dict]:
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT u.user_id, u.username, u.full_name, u.hide_name, SUM(p.amount) as total
        FROM profits p
        JOIN users u ON u.user_id = p.user_id
        WHERE p.date >= ?
        GROUP BY u.user_id
        ORDER BY total DESC
        LIMIT ?
    """, (today_start, limit))
    rows = cur.fetchall()
    conn.close()
    result = []
    for row in rows:
        result.append({
            'user_id': row[0],
            'username': row[1],
            'full_name': row[2],
            'hide_name': bool(row[3]),
            'total': row[4]
        })
    return result

def db_get_top_weekly(limit: int = 10) -> List[Dict]:
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT u.user_id, u.username, u.full_name, u.hide_name, SUM(p.amount) as total
        FROM profits p
        JOIN users u ON u.user_id = p.user_id
        WHERE p.date >= ?
        GROUP BY u.user_id
        ORDER BY total DESC
        LIMIT ?
    """, (week_ago, limit))
    rows = cur.fetchall()
    conn.close()
    result = []
    for row in rows:
        result.append({
            'user_id': row[0],
            'username': row[1],
            'full_name': row[2],
            'hide_name': bool(row[3]),
            'total': row[4]
        })
    return result

def db_get_setting(key: str) -> str:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else ''

def db_set_setting(key: str, value: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def db_get_all_admins() -> List[int]:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE is_admin=1")
    rows = cur.fetchall()
    conn.close()
    return [row[0] for row in rows]

def db_set_admin(user_id: int, admin: bool = True):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE users SET is_admin=? WHERE user_id=?", (1 if admin else 0, user_id))
    conn.commit()
    conn.close()

def db_get_chat_id() -> Optional[int]:
    chat_id_str = db_get_setting('chat_id')
    if chat_id_str:
        try:
            return int(chat_id_str)
        except:
            return None
    return None

def db_set_chat_id(chat_id: int):
    db_set_setting('chat_id', str(chat_id))

def db_clear_chat_id():
    db_set_setting('chat_id', '')

# ==================== Машины состояний (FSM) ====================
class AddProfitStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_amount = State()

class EditVisualStates(StatesGroup):
    choosing_section = State()
    # Для карты
    editing_card_text = State()
    # Для плиток (паки, прозвон)
    waiting_for_button_text = State()
    waiting_for_button_url = State()
    waiting_for_edit_text = State()
    waiting_for_edit_url = State()

class AddAdminStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_confirm = State()

class RemoveAdminStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_confirm = State()

class SetChatStates(StatesGroup):
    waiting_for_chat_id = State()
    waiting_for_confirm = State()

# ==================== Клавиатуры ====================
def get_main_keyboard(is_admin: bool = False, is_owner: bool = False) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="📊 Моя статистика"))
    builder.row(KeyboardButton(text="📦 Паки"), KeyboardButton(text="🗺 Карты"))
    builder.row(KeyboardButton(text="📞 Прозвон"))
    if is_admin:
        builder.row(KeyboardButton(text="➕ Новый профит"))
        builder.row(KeyboardButton(text="🎨 Изменить визуал"))
    if is_owner:
        builder.row(KeyboardButton(text="👑 Управление"))
    return builder.as_markup(resize_keyboard=True)

def get_cancel_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="🚫 Отмена"))
    return builder.as_markup(resize_keyboard=True)

def get_owner_panel_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="➕ Добавить админа"), KeyboardButton(text="❌ Удалить админа"))
    builder.row(KeyboardButton(text="📢 Установить чат"), KeyboardButton(text="🗑 Удалить чат"))
    builder.row(KeyboardButton(text="🔙 Назад"))
    return builder.as_markup(resize_keyboard=True)

def get_edit_visual_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📦 Паки", callback_data="edit_packs"))
    builder.row(InlineKeyboardButton(text="🗺 Карты", callback_data="edit_card"))
    builder.row(InlineKeyboardButton(text="📞 Прозвон", callback_data="edit_prozvon"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="edit_back"))
    return builder.as_markup()

def get_buttons_edit_keyboard(buttons: List[Dict], prefix: str) -> InlineKeyboardMarkup:
    """Клавиатура для редактирования списка плиток (паки, прозвон) с возможностью удаления"""
    builder = InlineKeyboardBuilder()
    for i, btn in enumerate(buttons):
        # Кнопка редактирования
        builder.row(InlineKeyboardButton(
            text=f"✏️ {btn['text']}",
            callback_data=f"{prefix}_edit_{i}"
        ))
        # Кнопка удаления под ней
        builder.row(InlineKeyboardButton(
            text=f"❌ Удалить: {btn['text']}",
            callback_data=f"{prefix}_delete_{i}"
        ))
    builder.row(InlineKeyboardButton(text="➕ Добавить", callback_data=f"{prefix}_add"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"{prefix}_back"))
    return builder.as_markup()

def get_confirm_keyboard(action: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да", callback_data=f"confirm_{action}"),
        InlineKeyboardButton(text="❌ Нет", callback_data=f"cancel_{action}")
    )
    return builder.as_markup()

def get_stats_switch_keyboard(current: str) -> InlineKeyboardMarkup:
    """Клавиатура для переключения между периодами статистики."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📅 День" + (" ✅" if current == "day" else ""), callback_data="stats_day"),
        InlineKeyboardButton(text="📆 Неделя" + (" ✅" if current == "week" else ""), callback_data="stats_week"),
        InlineKeyboardButton(text="🏆 Всё время" + (" ✅" if current == "all" else ""), callback_data="stats_all")
    )
    return builder.as_markup()

# ==================== Проверки прав ====================
def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID

async def is_admin(user_id: int) -> bool:
    user = db_get_user(user_id)
    return user and user['is_admin']

def is_chat_configured() -> bool:
    return db_get_chat_id() is not None

# ==================== Обработчики только для личных сообщений ====================
@dp.message(CommandStart(), F.chat.type == "private")
async def cmd_start(message: Message, state: FSMContext):
    """Обработчик /start в личных сообщениях. Регистрирует пользователя и показывает главное меню."""
    user_id = message.from_user.id
    db_create_user(
        user_id,
        message.from_user.username,
        message.from_user.full_name
    )
    admin = await is_admin(user_id)
    owner = is_owner(user_id)
    await message.answer(
        f"👋 Привет, {message.from_user.full_name}!\n"
        f"Я бот для учёта профитов. Используй кнопки ниже.",
        reply_markup=get_main_keyboard(admin, owner)
    )
    await state.clear()

# Обработчик отмены только в личных сообщениях
@dp.message(F.text == "🚫 Отмена", F.chat.type == "private")
async def cancel_handler(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    admin = await is_admin(user_id)
    owner = is_owner(user_id)
    await message.answer("Действие отменено.", reply_markup=get_main_keyboard(admin, owner))

# Кнопка "Назад" из панели владельца (только в личных сообщениях)
@dp.message(F.text == "🔙 Назад", F.chat.type == "private")
async def back_to_main(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    admin = await is_admin(user_id)
    owner = is_owner(user_id)
    await message.answer("Главное меню", reply_markup=get_main_keyboard(admin, owner))

# ==================== Панель владельца (только в личных сообщениях) ====================
@dp.message(F.text == "👑 Управление", F.chat.type == "private")
async def owner_panel(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        await message.answer("У вас нет прав.")
        return
    await message.answer(
        "👑 Панель управления владельца:",
        reply_markup=get_owner_panel_keyboard()
    )

# Добавление админа (только в личных сообщениях)
@dp.message(F.text == "➕ Добавить админа", F.chat.type == "private")
async def add_admin_start(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        await message.answer("У вас нет прав.")
        return
    await message.answer(
        "Введите ID пользователя, которого хотите сделать администратором:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AddAdminStates.waiting_for_user_id)

@dp.message(AddAdminStates.waiting_for_user_id, F.text, F.chat.type == "private")
async def add_admin_user_id(message: Message, state: FSMContext):
    try:
        user_id = int(message.text.strip())
    except:
        await message.answer("Некорректный ID. Введите число.")
        return
    user = db_get_user(user_id)
    if not user:
        await message.answer("Пользователь не найден в базе. Возможно, он ещё не запускал бота.")
        return
    await state.update_data(target_admin_id=user_id)
    await message.answer(
        f"Подтвердите назначение администратором пользователя {user['full_name']} (ID: {user_id})",
        reply_markup=get_confirm_keyboard("add_admin")
    )
    await state.set_state(AddAdminStates.waiting_for_confirm)

@dp.callback_query(AddAdminStates.waiting_for_confirm, F.data.startswith(("confirm_", "cancel_")))
async def add_admin_confirm(callback: CallbackQuery, state: FSMContext):
    action = callback.data.split("_", 1)
    confirm = action[0]
    action_name = action[1]
    if confirm == "confirm" and action_name == "add_admin":
        data = await state.get_data()
        user_id = data['target_admin_id']
        db_set_admin(user_id, True)
        await callback.message.edit_text("✅ Администратор добавлен.")
        await bot.send_message(user_id, "Вам назначены права администратора в боте.")
    else:
        await callback.message.edit_text("Отменено.")
    await state.clear()
    await callback.answer()
    # Возвращаем в панель владельца
    await callback.message.answer("Панель управления", reply_markup=get_owner_panel_keyboard())

# Удаление админа (только в личных сообщениях)
@dp.message(F.text == "❌ Удалить админа", F.chat.type == "private")
async def remove_admin_start(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        await message.answer("У вас нет прав.")
        return
    await message.answer(
        "Введите ID администратора, которого хотите лишить прав:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(RemoveAdminStates.waiting_for_user_id)

@dp.message(RemoveAdminStates.waiting_for_user_id, F.text, F.chat.type == "private")
async def remove_admin_user_id(message: Message, state: FSMContext):
    try:
        user_id = int(message.text.strip())
    except:
        await message.answer("Некорректный ID.")
        return
    user = db_get_user(user_id)
    if not user:
        await message.answer("Пользователь не найден.")
        return
    if not user['is_admin']:
        await message.answer("Этот пользователь не является администратором.")
        return
    if user_id == OWNER_ID:
        await message.answer("Нельзя удалить владельца.")
        return
    await state.update_data(target_admin_id=user_id)
    await message.answer(
        f"Подтвердите снятие прав администратора с пользователя {user['full_name']} (ID: {user_id})",
        reply_markup=get_confirm_keyboard("remove_admin")
    )
    await state.set_state(RemoveAdminStates.waiting_for_confirm)

@dp.callback_query(RemoveAdminStates.waiting_for_confirm, F.data.startswith(("confirm_", "cancel_")))
async def remove_admin_confirm(callback: CallbackQuery, state: FSMContext):
    action = callback.data.split("_", 1)
    confirm = action[0]
    action_name = action[1]
    if confirm == "confirm" and action_name == "remove_admin":
        data = await state.get_data()
        user_id = data['target_admin_id']
        db_set_admin(user_id, False)
        await callback.message.edit_text("✅ Права администратора сняты.")
        await bot.send_message(user_id, "Ваши права администратора в боте были отозваны.")
    else:
        await callback.message.edit_text("Отменено.")
    await state.clear()
    await callback.answer()
    await callback.message.answer("Панель управления", reply_markup=get_owner_panel_keyboard())

# Установка чата (только в личных сообщениях)
@dp.message(F.text == "📢 Установить чат", F.chat.type == "private")
async def set_chat_start(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        await message.answer("У вас нет прав.")
        return
    await message.answer(
        "Введите ID чата (с -100), куда будут отправляться профиты.\n"
        "Убедитесь, что бот добавлен в чат и является администратором.",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(SetChatStates.waiting_for_chat_id)

@dp.message(SetChatStates.waiting_for_chat_id, F.text, F.chat.type == "private")
async def set_chat_id(message: Message, state: FSMContext):
    try:
        chat_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Некорректный ID. Введите число, например: -1001234567890")
        return
    if not str(chat_id).startswith('-100'):
        await message.answer("⚠️ ID должен начинаться с -100 (это ID супергруппы).")
        return
    try:
        chat_member = await bot.get_chat_member(chat_id, bot.id)
        if chat_member.status not in ('administrator', 'creator'):
            await message.answer(
                "❌ Бот не является администратором в этом чате.\n"
                "Пожалуйста, добавьте бота в чат и назначьте администратором."
            )
            return
    except Exception as e:
        await message.answer(
            f"❌ Не удалось проверить права бота в чате.\n"
            f"Ошибка: {e}\n\n"
            f"Убедитесь, что чат существует, бот добавлен в него и является администратором."
        )
        return
    await state.update_data(chat_id=chat_id)
    await message.answer(
        f"✅ Проверка пройдена! Чат ID: {chat_id}\n"
        f"Подтвердите установку этого чата для публикаций.",
        reply_markup=get_confirm_keyboard("set_chat")
    )
    await state.set_state(SetChatStates.waiting_for_confirm)

@dp.callback_query(SetChatStates.waiting_for_confirm, F.data.startswith(("confirm_", "cancel_")))
async def set_chat_confirm(callback: CallbackQuery, state: FSMContext):
    action = callback.data.split("_", 1)
    confirm = action[0]
    action_name = action[1]
    if confirm == "confirm" and action_name == "set_chat":
        data = await state.get_data()
        chat_id = data['chat_id']
        db_set_chat_id(chat_id)
        await callback.message.edit_text("✅ Чат для публикаций успешно установлен!")
        await bot.send_message(chat_id, "✅ Бот настроен и готов публиковать профиты в этом чате.")
    else:
        await callback.message.edit_text("❌ Установка чата отменена.")
    await state.clear()
    await callback.answer()
    await callback.message.answer("Панель управления", reply_markup=get_owner_panel_keyboard())

# Удаление чата (только в личных сообщениях)
@dp.message(F.text == "🗑 Удалить чат", F.chat.type == "private")
async def clear_chat(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        await message.answer("У вас нет прав.")
        return
    current_chat = db_get_chat_id()
    if not current_chat:
        await message.answer("Чат для публикаций не настроен.")
        return
    db_clear_chat_id()
    await message.answer("✅ Чат для публикаций удалён.")
    await message.answer("Панель управления", reply_markup=get_owner_panel_keyboard())

# ==================== Кнопки меню (только в личных сообщениях) ====================
@dp.message(F.text == "📊 Моя статистика", F.chat.type == "private")
async def my_stats(message: Message):
    user_id = message.from_user.id
    user = db_get_user(user_id)
    if not user:
        await message.answer("Ошибка: пользователь не найден.")
        return

    total_profit = db_get_user_total_profit(user_id)
    joined = datetime.fromisoformat(user['joined_date'])
    days_in_bot = (datetime.now() - joined).days

    hide_status = "скрыто" if user['hide_name'] else "показывается"

    text = (
        f"👤 <b>Твой профиль</b>\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"👤 Ник: @{user['username'] if user['username'] else 'отсутствует'}\n"
        f"📅 В боте: {days_in_bot} дн.\n"
        f"💰 <b>Профит:</b> {total_profit:.2f} руб.\n"
        f"👀 Имя в профитах: {hide_status}"
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="🔒 Скрыть имя" if not user['hide_name'] else "🔓 Показывать имя",
                callback_data="toggle_hide_name"
            )]
        ]
    )
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "toggle_hide_name")
async def toggle_hide_name(callback: CallbackQuery):
    # Это может быть как в личке, так и везде, но логика едина
    user_id = callback.from_user.id
    user = db_get_user(user_id)
    if not user:
        await callback.answer("Ошибка")
        return
    new_hide = not user['hide_name']
    db_update_user_hide(user_id, new_hide)
    await callback.answer(f"Имя теперь {'скрыто' if new_hide else 'показывается'}")
    total_profit = db_get_user_total_profit(user_id)
    joined = datetime.fromisoformat(user['joined_date'])
    days_in_bot = (datetime.now() - joined).days
    text = (
        f"👤 <b>Твой профиль</b>\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"👤 Ник: @{user['username'] if user['username'] else 'отсутствует'}\n"
        f"📅 В боте: {days_in_bot} дн.\n"
        f"💰 <b>Профит:</b> {total_profit:.2f} руб.\n"
        f"👀 Имя в профитах: {'скрыто' if new_hide else 'показывается'}"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="🔒 Скрыть имя" if not new_hide else "🔓 Показывать имя",
                callback_data="toggle_hide_name"
            )]
        ]
    )
    await safe_edit_message(callback.message, text, reply_markup=kb)

@dp.message(F.text == "📦 Паки", F.chat.type == "private")
async def show_packs(message: Message):
    buttons_json = db_get_setting('packs_buttons')
    try:
        buttons = json.loads(buttons_json)
    except:
        buttons = []
    if not buttons:
        await message.answer("Паки пока не настроены.")
        return
    kb = InlineKeyboardBuilder()
    for btn in buttons:
        kb.row(InlineKeyboardButton(text=btn['text'], url=btn['url']))
    await message.answer("📦 Доступные паки:", reply_markup=kb.as_markup())

@dp.message(F.text == "🗺 Карты", F.chat.type == "private")
async def show_card(message: Message):
    card_text = db_get_setting('card_text')
    await message.answer(card_text, parse_mode=ParseMode.HTML)

@dp.message(F.text == "📞 Прозвон", F.chat.type == "private")
async def show_prozvon(message: Message):
    buttons_json = db_get_setting('prozvon_buttons')
    try:
        buttons = json.loads(buttons_json)
    except:
        buttons = []
    if not buttons:
        await message.answer("Прозвон пока не настроен.")
        return
    kb = InlineKeyboardBuilder()
    for btn in buttons:
        kb.row(InlineKeyboardButton(text=btn['text'], url=btn['url']))
    await message.answer("📞 Контакты для прозвона:", reply_markup=kb.as_markup())

# ==================== Админская кнопка "➕ Новый профит" (только в личных сообщениях) ====================
@dp.message(F.text == "➕ Новый профит", F.chat.type == "private")
async def add_profit_start(message: Message, state: FSMContext):
    if not (await is_admin(message.from_user.id) or is_owner(message.from_user.id)):
        await message.answer("У вас нет прав администратора.")
        return
    if not is_chat_configured():
        await message.answer("⚠️ Сначала владелец должен настроить чат для публикаций.")
        return
    await message.answer(
        "Введите ID пользователя, которому хотите начислить профит:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AddProfitStates.waiting_for_user_id)

@dp.message(AddProfitStates.waiting_for_user_id, F.text, F.chat.type == "private")
async def add_profit_user_id(message: Message, state: FSMContext):
    try:
        user_id = int(message.text.strip())
    except:
        await message.answer("Некорректный ID. Введите число.")
        return
    user = db_get_user(user_id)
    if not user:
        await message.answer("Пользователь с таким ID не найден в базе. Возможно, он ещё не запускал бота.")
        return
    await state.update_data(target_user_id=user_id)
    await message.answer("Введите сумму профита (в рублях):")
    await state.set_state(AddProfitStates.waiting_for_amount)

@dp.message(AddProfitStates.waiting_for_amount, F.text, F.chat.type == "private")
async def add_profit_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.strip().replace(',', '.'))
    except:
        await message.answer("Некорректная сумма. Введите число.")
        return

    data = await state.get_data()
    target_user_id = data['target_user_id']
    target_user = db_get_user(target_user_id)

    db_add_profit(target_user_id, amount)

    alert_text_template = db_get_setting('alert_text')
    photo_url = db_get_setting('alert_photo_url')

    if target_user['hide_name']:
        user_name_display = "скрыл имя"
    else:
        user_name_display = target_user['username'] or target_user['full_name'] or f"ID {target_user_id}"

    alert_text = alert_text_template.replace("{user_name}", user_name_display).replace("{amount}", f"{amount:.2f}")

    chat_id = db_get_chat_id()
    if chat_id:
        try:
            if photo_url:
                await bot.send_photo(chat_id, photo=URLInputFile(photo_url), caption=alert_text, parse_mode=ParseMode.HTML)
            else:
                await bot.send_message(chat_id, alert_text, parse_mode=ParseMode.HTML)
        except Exception as e:
            await message.answer(f"Ошибка отправки в чат: {e}")
    else:
        await message.answer("Чат не настроен.")

    try:
        await bot.send_message(
            target_user_id,
            f"🎉 Вам начислен профит: {amount:.2f} руб.\n"
            f"Подробности в общем чате."
        )
    except:
        pass

    admin = await is_admin(message.from_user.id)
    owner = is_owner(message.from_user.id)
    await message.answer("✅ Профит успешно добавлен!", reply_markup=get_main_keyboard(admin, owner))
    await state.clear()

# ==================== Админская кнопка "🎨 Изменить визуал" (только в личных сообщениях) ====================
@dp.message(F.text == "🎨 Изменить визуал", F.chat.type == "private")
async def edit_visual_start(message: Message, state: FSMContext):
    if not (await is_admin(message.from_user.id) or is_owner(message.from_user.id)):
        await message.answer("У вас нет прав.")
        return
    await message.answer(
        "Выберите, что хотите изменить:",
        reply_markup=get_edit_visual_keyboard()
    )
    await state.set_state(EditVisualStates.choosing_section)

# Обработчики для каждого раздела (callback'и могут быть везде, но состояние есть только в личке)
@dp.callback_query(StateFilter(EditVisualStates.choosing_section), F.data.startswith("edit_"))
async def edit_visual_section(callback: CallbackQuery, state: FSMContext):
    section = callback.data.split("_")[1]  # packs, card, prozvon, back
    if section == "back":
        await state.clear()
        await callback.message.delete()
        admin = await is_admin(callback.from_user.id) or is_owner(callback.from_user.id)
        owner = is_owner(callback.from_user.id)
        await callback.message.answer("Главное меню", reply_markup=get_main_keyboard(admin, owner))
        await callback.answer()
        return

    if section == "packs":
        await state.update_data(section='packs')
        buttons_json = db_get_setting('packs_buttons')
        try:
            buttons = json.loads(buttons_json)
        except:
            buttons = []
        await safe_edit_message(
            callback.message,
            "Редактирование паков:",
            reply_markup=get_buttons_edit_keyboard(buttons, 'packs')
        )
    elif section == "card":
        await state.update_data(section='card')
        await safe_edit_message(
            callback.message,
            "Отправьте новый текст для карты (можно использовать HTML-теги):\n"
            "Текущий текст:\n" + db_get_setting('card_text'),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="edit_back")]])
        )
        await state.set_state(EditVisualStates.editing_card_text)
    elif section == "prozvon":
        await state.update_data(section='prozvon')
        buttons_json = db_get_setting('prozvon_buttons')
        try:
            buttons = json.loads(buttons_json)
        except:
            buttons = []
        await safe_edit_message(
            callback.message,
            "Редактирование прозвона:",
            reply_markup=get_buttons_edit_keyboard(buttons, 'prozvon')
        )
    await callback.answer()

# Редактирование текста карты (только в личных сообщениях, потому что состояние)
@dp.message(EditVisualStates.editing_card_text, F.text, F.chat.type == "private")
async def edit_card_text(message: Message, state: FSMContext):
    db_set_setting('card_text', message.html_text)
    await message.answer("✅ Текст карты обновлён!")
    await state.clear()
    admin = await is_admin(message.from_user.id) or is_owner(message.from_user.id)
    owner = is_owner(message.from_user.id)
    await message.answer("Главное меню", reply_markup=get_main_keyboard(admin, owner))

# Редактирование плиток (паки/прозвон) - обработчики callback'ов
@dp.callback_query(F.data.startswith(('packs_', 'prozvon_')))
async def handle_buttons_edit(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split('_')
    prefix = parts[0]  # packs или prozvon
    cmd = parts[1]     # edit, add, delete, back

    if cmd == 'back':
        # Вернуться к выбору раздела
        await safe_edit_message(
            callback.message,
            "Выберите, что хотите изменить:",
            reply_markup=get_edit_visual_keyboard()
        )
        await state.set_state(EditVisualStates.choosing_section)
        await callback.answer()
        return

    if cmd == 'add':
        await state.update_data(editing_prefix=prefix, edit_index=None)
        await safe_edit_message(
            callback.message,
            "Введите название для новой кнопки (текст):"
        )
        await state.set_state(EditVisualStates.waiting_for_button_text)
        await callback.answer()
        return

    if cmd == 'edit':
        index = int(parts[2])
        await state.update_data(editing_prefix=prefix, edit_index=index)
        key = f"{prefix}_buttons"
        buttons_json = db_get_setting(key)
        buttons = json.loads(buttons_json)
        btn = buttons[index]
        await safe_edit_message(
            callback.message,
            f"Редактирование кнопки:\n"
            f"Текущий текст: {btn['text']}\n"
            f"Текущий URL: {btn['url']}\n\n"
            f"Введите новый текст для кнопки (или отправьте '0', чтобы оставить без изменений):"
        )
        await state.set_state(EditVisualStates.waiting_for_edit_text)
        await callback.answer()
        return

    if cmd == 'delete':
        index = int(parts[2])
        key = f"{prefix}_buttons"
        buttons_json = db_get_setting(key)
        buttons = json.loads(buttons_json)
        deleted = buttons.pop(index)
        db_set_setting(key, json.dumps(buttons, ensure_ascii=False))
        await safe_edit_message(
            callback.message,
            f"✅ Кнопка '{deleted['text']}' удалена.\n"
            f"Редактирование {prefix}:",
            reply_markup=get_buttons_edit_keyboard(buttons, prefix)
        )
        await callback.answer()
        return

# Обработка ввода текста для новой кнопки (только в личных сообщениях)
@dp.message(EditVisualStates.waiting_for_button_text, F.text, F.chat.type == "private")
async def handle_button_text(message: Message, state: FSMContext):
    text = message.text.strip()
    await state.update_data(temp_text=text)
    await message.answer("Теперь отправьте ссылку (URL):")
    await state.set_state(EditVisualStates.waiting_for_button_url)

@dp.message(EditVisualStates.waiting_for_button_url, F.text, F.chat.type == "private")
async def handle_button_url(message: Message, state: FSMContext):
    url = message.text.strip()
    data = await state.get_data()
    prefix = data['editing_prefix']
    text = data['temp_text']
    key = f"{prefix}_buttons"
    buttons_json = db_get_setting(key)
    buttons = json.loads(buttons_json)
    buttons.append({'text': text, 'url': url})
    db_set_setting(key, json.dumps(buttons, ensure_ascii=False))
    await message.answer("✅ Кнопка добавлена!")
    await state.clear()
    admin = await is_admin(message.from_user.id) or is_owner(message.from_user.id)
    owner = is_owner(message.from_user.id)
    await message.answer("Главное меню", reply_markup=get_main_keyboard(admin, owner))

# Обработка редактирования текста существующей кнопки (только в личных сообщениях)
@dp.message(EditVisualStates.waiting_for_edit_text, F.text, F.chat.type == "private")
async def handle_edit_text(message: Message, state: FSMContext):
    new_text = message.text.strip()
    data = await state.get_data()
    prefix = data['editing_prefix']
    index = data['edit_index']
    key = f"{prefix}_buttons"
    buttons_json = db_get_setting(key)
    buttons = json.loads(buttons_json)
    if new_text != '0':
        buttons[index]['text'] = new_text
        db_set_setting(key, json.dumps(buttons, ensure_ascii=False))
    await state.update_data(temp_edit_text=new_text if new_text != '0' else None)
    await message.answer("Введите новый URL для кнопки (или '0', чтобы оставить без изменений):")
    await state.set_state(EditVisualStates.waiting_for_edit_url)

@dp.message(EditVisualStates.waiting_for_edit_url, F.text, F.chat.type == "private")
async def handle_edit_url(message: Message, state: FSMContext):
    new_url = message.text.strip()
    data = await state.get_data()
    prefix = data['editing_prefix']
    index = data['edit_index']
    key = f"{prefix}_buttons"
    buttons_json = db_get_setting(key)
    buttons = json.loads(buttons_json)
    if new_url != '0':
        buttons[index]['url'] = new_url
        db_set_setting(key, json.dumps(buttons, ensure_ascii=False))
    await message.answer("✅ Кнопка обновлена!")
    await state.clear()
    admin = await is_admin(message.from_user.id) or is_owner(message.from_user.id)
    owner = is_owner(message.from_user.id)
    await message.answer("Главное меню", reply_markup=get_main_keyboard(admin, owner))

# ==================== Команды в групповом чате с автоудалением ====================
async def send_group_response(message: Message, text: str, delay: int = 60, reply_markup: InlineKeyboardMarkup = None):
    """Отправляет ответ в группу и планирует удаление."""
    bot_msg = await message.reply(text, reply_markup=reply_markup)
    asyncio.create_task(delete_after_delay(bot, message.chat.id, message.message_id, bot_msg.message_id, delay))

@dp.message(Command("top"), F.chat.type.in_({"group", "supergroup"}))
async def group_top(message: Message):
    top = db_get_top_all(10)
    if not top:
        await send_group_response(message, "Пока нет профитов.", 60)
        return
    lines = ["<b>🏆 Топ за всё время:</b>"]
    for i, u in enumerate(top, 1):
        name = u['username'] or u['full_name'] or f"ID {u['user_id']}"
        if u['hide_name']:
            name = "Скрыто"
        lines.append(f"{i}. {name} — {u['total']:.2f} руб.")
    await send_group_response(message, "\n".join(lines), 60, get_stats_switch_keyboard("all"))

@dp.message(Command("topd"), F.chat.type.in_({"group", "supergroup"}))
async def group_topd(message: Message):
    top = db_get_top_daily(10)
    if not top:
        await send_group_response(message, "За сегодня профитов нет.", 60)
        return
    lines = ["<b>📅 Топ за сегодня:</b>"]
    for i, u in enumerate(top, 1):
        name = u['username'] or u['full_name'] or f"ID {u['user_id']}"
        if u['hide_name']:
            name = "Скрыто"
        lines.append(f"{i}. {name} — {u['total']:.2f} руб.")
    await send_group_response(message, "\n".join(lines), 60, get_stats_switch_keyboard("day"))

@dp.message(Command("topw"), F.chat.type.in_({"group", "supergroup"}))
async def group_topw(message: Message):
    top = db_get_top_weekly(10)
    if not top:
        await send_group_response(message, "За последние 7 дней профитов нет.", 60)
        return
    lines = ["<b>📆 Топ за неделю:</b>"]
    for i, u in enumerate(top, 1):
        name = u['username'] or u['full_name'] or f"ID {u['user_id']}"
        if u['hide_name']:
            name = "Скрыто"
        lines.append(f"{i}. {name} — {u['total']:.2f} руб.")
    await send_group_response(message, "\n".join(lines), 60, get_stats_switch_keyboard("week"))

@dp.callback_query(F.data.startswith("stats_"))
async def stats_switch(callback: CallbackQuery):
    """Переключение между периодами статистики по инлайн-кнопкам."""
    period = callback.data.split("_")[1]  # day, week, all
    if period == "day":
        top = db_get_top_daily(10)
        title = "📅 Топ за сегодня"
        current = "day"
    elif period == "week":
        top = db_get_top_weekly(10)
        title = "📆 Топ за неделю"
        current = "week"
    else:  # all
        top = db_get_top_all(10)
        title = "🏆 Топ за всё время"
        current = "all"
    if not top:
        await callback.answer("Нет данных")
        return
    lines = [f"<b>{title}:</b>"]
    for i, u in enumerate(top, 1):
        name = u['username'] or u['full_name'] or f"ID {u['user_id']}"
        if u['hide_name']:
            name = "Скрыто"
        lines.append(f"{i}. {name} — {u['total']:.2f} руб.")
    await safe_edit_message(callback.message, "\n".join(lines), reply_markup=get_stats_switch_keyboard(current))
    await callback.answer()

@dp.message(Command("card"), F.chat.type.in_({"group", "supergroup"}))
async def group_card(message: Message):
    card_text = db_get_setting('card_text')
    await send_group_response(message, card_text, 30)

@dp.message(Command("prozvon"), F.chat.type.in_({"group", "supergroup"}))
async def group_prozvon(message: Message):
    buttons_json = db_get_setting('prozvon_buttons')
    try:
        buttons = json.loads(buttons_json)
    except:
        buttons = []
    if not buttons:
        await send_group_response(message, "Прозвон не настроен.", 15)
        return
    kb = InlineKeyboardBuilder()
    for btn in buttons:
        kb.row(InlineKeyboardButton(text=btn['text'], url=btn['url']))
    bot_msg = await message.reply("📞 Контакты для прозвона:", reply_markup=kb.as_markup())
    asyncio.create_task(delete_after_delay(bot, message.chat.id, message.message_id, bot_msg.message_id, 15))

@dp.message(Command("help"), F.chat.type.in_({"group", "supergroup"}))
async def group_help(message: Message):
    text = (
        "🆘 <b>Доступные команды в чате:</b>\n"
        "/top - топ за всё время\n"
        "/topd - топ за сегодня\n"
        "/topw - топ за неделю\n"
        "/card - информация о картах\n"
        "/prozvon - контакты для прозвона\n"
        "/help - это сообщение\n\n"
        "<i>Сообщения будут автоматически удалены через указанное время.</i>"
    )
    await send_group_response(message, text, 15)

# ==================== Запуск бота ====================
async def main():
    init_db()
    # Устанавливаем владельца как админа
    db_set_admin(OWNER_ID, True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())