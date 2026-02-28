"""
Super Quality Bot for Profit Tracking
Author: AI Assistant
Description: Бот для учёта профитов с системой заявок, статистикой и настройкой.
Добавлен шаблон приветствия, который отправляется пользователю после одобрения заявки.
Редактируется через кнопку "Шаблон приветствия" в разделе "Изменить визуал".
Исправлена работа кнопки для aiogram 3.24.0 и Python 3.14.2.
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

DB_NAME = "profits.db"

logging.basicConfig(level=logging.INFO)

# ==================== Инициализация бота ====================
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ==================== Вспомогательные функции ====================
async def safe_edit_message(message: Message, text: str, reply_markup=None):
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise

async def delete_after_delay(bot: Bot, chat_id: int, user_msg_id: int, bot_msg_id: int, delay: int):
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

    cur.execute("PRAGMA table_info(users)")
    columns = [col[1] for col in cur.fetchall()]
    if 'is_approved' not in columns:
        cur.execute("ALTER TABLE users ADD COLUMN is_approved INTEGER DEFAULT 0")
    if 'blocked_until' not in columns:
        cur.execute("ALTER TABLE users ADD COLUMN blocked_until TEXT")

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

    # Таблица настроек
    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # Настройки по умолчанию
    default_settings = {
        'chat_id': '',
        'card_text': 'Информация о картах отсутствует.',
        'prozvon_buttons': json.dumps([]),
        'packs_buttons': json.dumps([]),
        'alert_text': '🆕 <b>Новый профит!</b>\n\n🧑‍💻 Воркер: {user_name}\n💰 Профит: {amount} руб.',
        'alert_photo_url': '',
        'welcome_template': '✅ Ваша заявка одобрена!\nДобро пожаловать в нашу команду!\nНАШ ЧАТ - https://t.me/+DQv89CZX0KYxMzVi',
        'questions': json.dumps([
            "Откуда вы о нас узнали?",
            "Сколько вы готовы уделять времени?",
            "Если уже работали в этой сфере, то какие были результаты?"
        ])
    }
    for key, value in default_settings.items():
        cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))

    conn.commit()
    conn.close()

# Функции для пользователей
def db_get_user(user_id: int) -> Optional[Dict]:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, full_name, joined_date, hide_name, is_admin, is_approved, blocked_until FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        return {
            'user_id': row[0],
            'username': row[1],
            'full_name': row[2],
            'joined_date': row[3],
            'hide_name': bool(row[4]),
            'is_admin': bool(row[5]),
            'is_approved': bool(row[6]),
            'blocked_until': row[7]
        }
    return None

def db_create_user(user_id: int, username: str = None, full_name: str = None):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO users (user_id, username, full_name, joined_date, hide_name, is_admin, is_approved, blocked_until) VALUES (?, ?, ?, ?, 0, 0, 0, NULL)",
        (user_id, username, full_name, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def db_update_user_approval(user_id: int, approved: bool, blocked_until: str = None):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE users SET is_approved=?, blocked_until=? WHERE user_id=?", (1 if approved else 0, blocked_until, user_id))
    conn.commit()
    conn.close()

def db_update_user_hide(user_id: int, hide: bool):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE users SET hide_name=? WHERE user_id=?", (1 if hide else 0, user_id))
    conn.commit()
    conn.close()

# Профиты
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

def db_get_total_profit_all() -> float:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT SUM(amount) FROM profits")
    row = cur.fetchone()
    conn.close()
    return row[0] if row[0] else 0.0

def db_get_total_profit_daily() -> float:
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT SUM(amount) FROM profits WHERE date >= ?", (today_start,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row[0] else 0.0

def db_get_total_profit_weekly() -> float:
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT SUM(amount) FROM profits WHERE date >= ?", (week_ago,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row[0] else 0.0

# Настройки
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

def db_get_questions() -> List[str]:
    qs = db_get_setting('questions')
    try:
        return json.loads(qs)
    except:
        return []

def db_set_questions(qs: List[str]):
    db_set_setting('questions', json.dumps(qs, ensure_ascii=False))

# Функции для шаблона приветствия
def db_get_welcome_template() -> str:
    return db_get_setting('welcome_template')

def db_set_welcome_template(text: str):
    db_set_setting('welcome_template', text)

# Админы
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

# Чат
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

# ==================== Машины состояний ====================
class AddProfitStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_amount = State()

class EditVisualStates(StatesGroup):
    choosing_section = State()
    editing_card_text = State()
    waiting_for_button_text = State()
    waiting_for_button_url = State()
    waiting_for_edit_text = State()
    waiting_for_edit_url = State()
    editing_questions = State()
    editing_question_index = State()
    adding_question = State()
    editing_welcome_template = State()  # состояние для редактирования шаблона приветствия

class AddAdminStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_confirm = State()

class RemoveAdminStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_confirm = State()

class SetChatStates(StatesGroup):
    waiting_for_chat_id = State()
    waiting_for_confirm = State()

class ApplicationStates(StatesGroup):
    waiting_for_answer = State()

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
    builder.row(InlineKeyboardButton(text="📋 Анкета", callback_data="edit_questions"))
    builder.row(InlineKeyboardButton(text="📨 Шаблон приветствия", callback_data="edit_welcome_template"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="edit_back"))
    return builder.as_markup()

def get_questions_edit_keyboard(questions: List[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for i, q in enumerate(questions):
        builder.row(InlineKeyboardButton(text=f"✏️ {q[:30]}...", callback_data=f"q_edit_{i}"))
        builder.row(InlineKeyboardButton(text=f"❌ Удалить {i+1}", callback_data=f"q_del_{i}"))
    builder.row(InlineKeyboardButton(text="➕ Добавить вопрос", callback_data="q_add"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="q_back"))
    return builder.as_markup()

def get_buttons_edit_keyboard(buttons: List[Dict], prefix: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for i, btn in enumerate(buttons):
        builder.row(InlineKeyboardButton(text=f"✏️ {btn['text']}", callback_data=f"{prefix}_edit_{i}"))
        builder.row(InlineKeyboardButton(text=f"❌ Удалить: {btn['text']}", callback_data=f"{prefix}_delete_{i}"))
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
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📅 День" + (" ✅" if current == "day" else ""), callback_data="stats_day"),
        InlineKeyboardButton(text="📆 Неделя" + (" ✅" if current == "week" else ""), callback_data="stats_week"),
        InlineKeyboardButton(text="🏆 Всё время" + (" ✅" if current == "all" else ""), callback_data="stats_all")
    )
    return builder.as_markup()

def get_application_actions_keyboard(user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Одобрить", callback_data=f"app_approve_{user_id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"app_reject_{user_id}")
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

async def is_user_approved(user_id: int) -> bool:
    user = db_get_user(user_id)
    if not user:
        return False
    if user['is_approved']:
        return True
    if user['blocked_until']:
        blocked = datetime.fromisoformat(user['blocked_until'])
        if datetime.now() < blocked:
            return False
        else:
            db_update_user_approval(user_id, False, None)
    return False

# ==================== Обработчики личных сообщений ====================
@dp.message(CommandStart(), F.chat.type == "private")
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    db_create_user(user_id, message.from_user.username, message.from_user.full_name)

    if await is_user_approved(user_id) or await is_admin(user_id) or is_owner(user_id):
        admin = await is_admin(user_id) or is_owner(user_id)
        owner = is_owner(user_id)
        await message.answer(
            f"👋 С возвращением, {message.from_user.full_name}!",
            reply_markup=get_main_keyboard(admin, owner)
        )
        await state.clear()
        return

    user = db_get_user(user_id)
    if user['blocked_until']:
        blocked = datetime.fromisoformat(user['blocked_until'])
        if datetime.now() < blocked:
            days_left = (blocked - datetime.now()).days + 1
            await message.answer(f"⏳ Ваша заявка была отклонена. Вы сможете подать повторно через {days_left} дн.")
            return
        else:
            db_update_user_approval(user_id, False, None)

    questions = db_get_questions()
    if not questions:
        db_update_user_approval(user_id, True, None)
        await message.answer("✅ Доступ получен.")
        return

    await state.update_data(answers=[], current_q=0, questions=questions)
    await message.answer(f"📝 Вопрос 1/{len(questions)}:\n{questions[0]}")
    await state.set_state(ApplicationStates.waiting_for_answer)

@dp.message(ApplicationStates.waiting_for_answer, F.text, F.chat.type == "private")
async def process_application_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    answers = data['answers']
    questions = data['questions']
    current_q = data['current_q']
    answers.append(message.text)
    current_q += 1
    if current_q < len(questions):
        await state.update_data(answers=answers, current_q=current_q)
        await message.answer(f"📝 Вопрос {current_q+1}/{len(questions)}:\n{questions[current_q]}")
    else:
        user_id = message.from_user.id
        user = db_get_user(user_id)
        username = f"@{user['username']}" if user['username'] else "нет username"
        text = f"‼️ <b>НОВАЯ ЗАЯВКА НА ВСТУПЛЕНИЕ</b>\n\n"
        text += f"🆔 ID: <code>{user_id}</code>\n"
        text += f"👤 Имя: {user['full_name']}\n"
        text += f"📱 Username: {username}\n\n"
        for i, (q, a) in enumerate(zip(questions, answers)):
            text += f"<b>{i+1}. {q}</b>\n{a}\n\n"
        admins = db_get_all_admins() + [OWNER_ID]
        sent = False
        for admin_id in set(admins):
            try:
                await bot.send_message(admin_id, text, reply_markup=get_application_actions_keyboard(user_id))
                sent = True
            except:
                pass
        if not sent:
            await message.answer("❌ Не удалось отправить заявку администраторам. Попробуйте позже.")
        else:
            await message.answer("✅ Ваша заявка отправлена администраторам. Ожидайте решения.")
        await state.clear()

@dp.callback_query(F.data.startswith(("app_approve_", "app_reject_")))
async def handle_application_decision(callback: CallbackQuery):
    if not (await is_admin(callback.from_user.id) or is_owner(callback.from_user.id)):
        await callback.answer("У вас нет прав.")
        return
    action, target_user_id = callback.data.split('_')[1], int(callback.data.split('_')[2])
    target_user = db_get_user(target_user_id)
    if not target_user:
        await callback.answer("Пользователь не найден.")
        await callback.message.delete()
        return
    if action == "approve":
        db_update_user_approval(target_user_id, True, None)
        # Отправляем шаблон приветствия
        welcome_text = db_get_welcome_template()
        try:
            await bot.send_message(target_user_id, welcome_text)
        except:
            pass
        await callback.message.edit_text(callback.message.html_text + "\n\n✅ Заявка одобрена.")
    else:
        blocked_until = (datetime.now() + timedelta(days=3)).isoformat()
        db_update_user_approval(target_user_id, False, blocked_until)
        try:
            await bot.send_message(target_user_id, "❌ Ваша заявка отклонена. Вы сможете подать повторно через 3 дня.")
        except:
            pass
        await callback.message.edit_text(callback.message.html_text + "\n\n❌ Заявка отклонена.")
    await callback.answer()

@dp.message(F.text == "🚫 Отмена", F.chat.type == "private")
async def cancel_handler(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    admin = await is_admin(user_id) or is_owner(user_id)
    owner = is_owner(user_id)
    await message.answer("Действие отменено.", reply_markup=get_main_keyboard(admin, owner))

@dp.message(F.text == "🔙 Назад", F.chat.type == "private")
async def back_to_main(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    admin = await is_admin(user_id) or is_owner(user_id)
    owner = is_owner(user_id)
    await message.answer("Главное меню", reply_markup=get_main_keyboard(admin, owner))

# ==================== Панель владельца (только для владельца) ====================
@dp.message(F.text == "👑 Управление", F.chat.type == "private")
async def owner_panel(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        await message.answer("У вас нет прав.")
        return
    await message.answer("👑 Панель управления владельца:", reply_markup=get_owner_panel_keyboard())

@dp.message(F.text == "➕ Добавить админа", F.chat.type == "private")
async def add_admin_start(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        await message.answer("У вас нет прав.")
        return
    await message.answer("Введите ID пользователя, которого хотите сделать администратором:", reply_markup=get_cancel_keyboard())
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
    await callback.message.answer("Панель управления", reply_markup=get_owner_panel_keyboard())

@dp.message(F.text == "❌ Удалить админа", F.chat.type == "private")
async def remove_admin_start(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        await message.answer("У вас нет прав.")
        return
    await message.answer("Введите ID администратора, которого хотите лишить прав:", reply_markup=get_cancel_keyboard())
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
    await callback.message.answer("Панель управления", reply_markup=get_owner_panel_keyboard())

@dp.message(F.text == "📢 Установить чат", F.chat.type == "private")
async def set_chat_start(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        await message.answer("У вас нет прав.")
        return
    await message.answer(
        "Введите ID чата (с -100), куда будут отправляться профиты.\nУбедитесь, что бот добавлен в чат и является администратором.",
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
            await message.answer("❌ Бот не является администратором в этом чате.")
            return
    except Exception as e:
        await message.answer(f"❌ Не удалось проверить права бота в чате. Ошибка: {e}")
        return
    await state.update_data(chat_id=chat_id)
    await message.answer(
        f"✅ Проверка пройдена! Чат ID: {chat_id}\nПодтвердите установку.",
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
    await callback.message.answer("Панель управления", reply_markup=get_owner_panel_keyboard())

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

# ==================== Кнопки меню (только для одобренных пользователей) ====================
@dp.message(F.text == "📊 Моя статистика", F.chat.type == "private")
async def my_stats(message: Message):
    if not await is_user_approved(message.from_user.id) and not await is_admin(message.from_user.id) and not is_owner(message.from_user.id):
        await message.answer("⏳ Ваша заявка ещё не одобрена.")
        return
    user_id = message.from_user.id
    user = db_get_user(user_id)
    if not user:
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
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text="🔒 Скрыть имя" if not user['hide_name'] else "🔓 Показывать имя",
        callback_data="toggle_hide_name"
    )]])
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "toggle_hide_name")
async def toggle_hide_name(callback: CallbackQuery):
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
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text="🔒 Скрыть имя" if not new_hide else "🔓 Показывать имя",
        callback_data="toggle_hide_name"
    )]])
    await safe_edit_message(callback.message, text, reply_markup=kb)

@dp.message(F.text == "📦 Паки", F.chat.type == "private")
async def show_packs(message: Message):
    if not await is_user_approved(message.from_user.id) and not await is_admin(message.from_user.id) and not is_owner(message.from_user.id):
        await message.answer("⏳ Ваша заявка ещё не одобрена.")
        return
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
    if not await is_user_approved(message.from_user.id) and not await is_admin(message.from_user.id) and not is_owner(message.from_user.id):
        await message.answer("⏳ Ваша заявка ещё не одобрена.")
        return
    card_text = db_get_setting('card_text')
    await message.answer(card_text, parse_mode=ParseMode.HTML)

@dp.message(F.text == "📞 Прозвон", F.chat.type == "private")
async def show_prozvon(message: Message):
    if not await is_user_approved(message.from_user.id) and not await is_admin(message.from_user.id) and not is_owner(message.from_user.id):
        await message.answer("⏳ Ваша заявка ещё не одобрена.")
        return
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

# ==================== Админская кнопка "➕ Новый профит" (только для админов) ====================
@dp.message(F.text == "➕ Новый профит", F.chat.type == "private")
async def add_profit_start(message: Message, state: FSMContext):
    if not (await is_admin(message.from_user.id) or is_owner(message.from_user.id)):
        await message.answer("У вас нет прав администратора.")
        return
    if not is_chat_configured():
        await message.answer("⚠️ Сначала владелец должен настроить чат для публикаций.")
        return
    await message.answer("Введите ID пользователя, которому хотите начислить профит:", reply_markup=get_cancel_keyboard())
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
        await bot.send_message(target_user_id, f"🎉 Вам начислен профит: {amount:.2f} руб.\nПодробности в общем чате.")
    except:
        pass

    admin = await is_admin(message.from_user.id)
    owner = is_owner(message.from_user.id)
    await message.answer("✅ Профит успешно добавлен!", reply_markup=get_main_keyboard(admin, owner))
    await state.clear()

# ==================== Админская кнопка "🎨 Изменить визуал" (только для админов) ====================
@dp.message(F.text == "🎨 Изменить визуал", F.chat.type == "private")
async def edit_visual_start(message: Message, state: FSMContext):
    if not (await is_admin(message.from_user.id) or is_owner(message.from_user.id)):
        await message.answer("У вас нет прав.")
        return
    await message.answer("Выберите, что хотите изменить:", reply_markup=get_edit_visual_keyboard())
    await state.set_state(EditVisualStates.choosing_section)

# Обработчик для кнопок редактирования (кроме шаблона приветствия)
@dp.callback_query(StateFilter(EditVisualStates.choosing_section), F.data.startswith("edit_"), F.data != "edit_welcome_template")
async def edit_visual_section(callback: CallbackQuery, state: FSMContext):
    section = callback.data.split("_")[1]
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
        buttons = json.loads(db_get_setting('packs_buttons'))
        await safe_edit_message(callback.message, "Редактирование паков:", reply_markup=get_buttons_edit_keyboard(buttons, 'packs'))
        await callback.answer()
    elif section == "card":
        await state.update_data(section='card')
        await safe_edit_message(
            callback.message,
            "Отправьте новый текст для карты (можно использовать HTML-теги):\nТекущий текст:\n" + db_get_setting('card_text'),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="edit_back")]])
        )
        await state.set_state(EditVisualStates.editing_card_text)
        await callback.answer()
    elif section == "prozvon":
        await state.update_data(section='prozvon')
        buttons = json.loads(db_get_setting('prozvon_buttons'))
        await safe_edit_message(callback.message, "Редактирование прозвона:", reply_markup=get_buttons_edit_keyboard(buttons, 'prozvon'))
        await callback.answer()
    elif section == "questions":
        questions = db_get_questions()
        await safe_edit_message(callback.message, "Редактирование вопросов анкеты:", reply_markup=get_questions_edit_keyboard(questions))
        await state.update_data(section='questions')
        await callback.answer()
    else:
        await callback.answer()

# ==================== Обработчик для кнопки "Шаблон приветствия" (не зависит от состояния) ====================
@dp.callback_query(F.data == "edit_welcome_template")
async def edit_welcome_template_start(callback: CallbackQuery, state: FSMContext):
    # Проверяем права
    if not (await is_admin(callback.from_user.id) or is_owner(callback.from_user.id)):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    # Сразу отвечаем на callback, чтобы кнопка перестала крутиться
    await callback.answer()
    # Отправляем новое сообщение с запросом текста
    await callback.message.answer(
        f"📝 <b>Редактирование шаблона приветствия</b>\n\n"
        f"Текущий текст:\n{db_get_welcome_template()}\n\n"
        f"Отправьте новый текст сообщения, которое получит пользователь при одобрении заявки.\n"
        f"Можно использовать HTML-теги.\n\n"
        f"Чтобы отменить, нажмите кнопку ниже.",
        reply_markup=get_cancel_keyboard()
    )
    # Устанавливаем состояние для ввода
    await state.set_state(EditVisualStates.editing_welcome_template)

@dp.message(EditVisualStates.editing_card_text, F.text, F.chat.type == "private")
async def edit_card_text(message: Message, state: FSMContext):
    db_set_setting('card_text', message.html_text)
    await message.answer("✅ Текст карты обновлён!")
    await state.clear()
    admin = await is_admin(message.from_user.id) or is_owner(message.from_user.id)
    owner = is_owner(message.from_user.id)
    await message.answer("Главное меню", reply_markup=get_main_keyboard(admin, owner))

# ==================== Редактирование шаблона приветствия ====================
@dp.message(EditVisualStates.editing_welcome_template, F.text, F.chat.type == "private")
async def save_welcome_template(message: Message, state: FSMContext):
    new_text = message.text.strip()
    if new_text.lower() in ("отмена", "/cancel", "0") or new_text == "🚫 Отмена":
        await message.answer("❌ Изменение шаблона приветствия отменено.")
    else:
        db_set_welcome_template(message.html_text)
        await message.answer("✅ Шаблон приветствия обновлён!")
    await state.clear()
    admin = await is_admin(message.from_user.id) or is_owner(message.from_user.id)
    owner = is_owner(message.from_user.id)
    await message.answer("Главное меню", reply_markup=get_main_keyboard(admin, owner))

# ==================== Редактирование вопросов анкеты ====================
@dp.callback_query(F.data.startswith(("q_edit_", "q_del_", "q_add", "q_back")))
async def handle_questions_edit(callback: CallbackQuery, state: FSMContext):
    action = callback.data.split('_')[1]
    questions = db_get_questions()

    if action == "back":
        await safe_edit_message(callback.message, "Выберите, что хотите изменить:", reply_markup=get_edit_visual_keyboard())
        await state.set_state(EditVisualStates.choosing_section)
        await callback.answer()
        return

    if action == "add":
        await callback.message.edit_text("Введите текст нового вопроса:")
        await state.set_state(EditVisualStates.adding_question)
        await callback.answer()
        return

    index = int(callback.data.split('_')[2])
    if action == "edit":
        await state.update_data(edit_q_index=index)
        await callback.message.edit_text(f"Введите новый текст для вопроса {index+1}:\nТекущий: {questions[index]}")
        await state.set_state(EditVisualStates.editing_question_index)
        await callback.answer()
        return
    elif action == "del":
        del questions[index]
        db_set_questions(questions)
        await callback.message.edit_text("✅ Вопрос удалён.\nРедактирование вопросов:", reply_markup=get_questions_edit_keyboard(questions))
        await callback.answer()
        return

@dp.message(EditVisualStates.adding_question, F.text, F.chat.type == "private")
async def add_question_text(message: Message, state: FSMContext):
    questions = db_get_questions()
    questions.append(message.text.strip())
    db_set_questions(questions)
    await message.answer("✅ Вопрос добавлен!")
    await state.clear()
    admin = await is_admin(message.from_user.id) or is_owner(message.from_user.id)
    owner = is_owner(message.from_user.id)
    await message.answer("Главное меню", reply_markup=get_main_keyboard(admin, owner))

@dp.message(EditVisualStates.editing_question_index, F.text, F.chat.type == "private")
async def edit_question_text(message: Message, state: FSMContext):
    data = await state.get_data()
    index = data['edit_q_index']
    questions = db_get_questions()
    questions[index] = message.text.strip()
    db_set_questions(questions)
    await message.answer("✅ Вопрос обновлён!")
    await state.clear()
    admin = await is_admin(message.from_user.id) or is_owner(message.from_user.id)
    owner = is_owner(message.from_user.id)
    await message.answer("Главное меню", reply_markup=get_main_keyboard(admin, owner))

# ==================== Редактирование плиток (паки/прозвон) ====================
@dp.callback_query(F.data.startswith(('packs_', 'prozvon_')))
async def handle_buttons_edit(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split('_')
    prefix = parts[0]
    cmd = parts[1]
    if cmd == 'back':
        await safe_edit_message(callback.message, "Выберите, что хотите изменить:", reply_markup=get_edit_visual_keyboard())
        await state.set_state(EditVisualStates.choosing_section)
        await callback.answer()
        return
    if cmd == 'add':
        await state.update_data(editing_prefix=prefix, edit_index=None)
        await safe_edit_message(callback.message, "Введите название для новой кнопки (текст):")
        await state.set_state(EditVisualStates.waiting_for_button_text)
        await callback.answer()
        return
    if cmd == 'edit':
        index = int(parts[2])
        await state.update_data(editing_prefix=prefix, edit_index=index)
        key = f"{prefix}_buttons"
        buttons = json.loads(db_get_setting(key))
        btn = buttons[index]
        await safe_edit_message(callback.message,
            f"Редактирование кнопки:\nТекущий текст: {btn['text']}\nТекущий URL: {btn['url']}\n\nВведите новый текст для кнопки (или '0' без изменений):")
        await state.set_state(EditVisualStates.waiting_for_edit_text)
        await callback.answer()
        return
    if cmd == 'delete':
        index = int(parts[2])
        key = f"{prefix}_buttons"
        buttons = json.loads(db_get_setting(key))
        deleted = buttons.pop(index)
        db_set_setting(key, json.dumps(buttons, ensure_ascii=False))
        await safe_edit_message(callback.message, f"✅ Кнопка '{deleted['text']}' удалена.\nРедактирование {prefix}:",
                                reply_markup=get_buttons_edit_keyboard(buttons, prefix))
        await callback.answer()
        return

@dp.message(EditVisualStates.waiting_for_button_text, F.text, F.chat.type == "private")
async def handle_button_text(message: Message, state: FSMContext):
    await state.update_data(temp_text=message.text.strip())
    await message.answer("Теперь отправьте ссылку (URL):")
    await state.set_state(EditVisualStates.waiting_for_button_url)

@dp.message(EditVisualStates.waiting_for_button_url, F.text, F.chat.type == "private")
async def handle_button_url(message: Message, state: FSMContext):
    url = message.text.strip()
    data = await state.get_data()
    prefix = data['editing_prefix']
    text = data['temp_text']
    key = f"{prefix}_buttons"
    buttons = json.loads(db_get_setting(key))
    buttons.append({'text': text, 'url': url})
    db_set_setting(key, json.dumps(buttons, ensure_ascii=False))
    await message.answer("✅ Кнопка добавлена!")
    await state.clear()
    admin = await is_admin(message.from_user.id) or is_owner(message.from_user.id)
    owner = is_owner(message.from_user.id)
    await message.answer("Главное меню", reply_markup=get_main_keyboard(admin, owner))

@dp.message(EditVisualStates.waiting_for_edit_text, F.text, F.chat.type == "private")
async def handle_edit_text(message: Message, state: FSMContext):
    new_text = message.text.strip()
    data = await state.get_data()
    prefix = data['editing_prefix']
    index = data['edit_index']
    key = f"{prefix}_buttons"
    buttons = json.loads(db_get_setting(key))
    if new_text != '0':
        buttons[index]['text'] = new_text
        db_set_setting(key, json.dumps(buttons, ensure_ascii=False))
    await state.update_data(temp_edit_text=new_text if new_text != '0' else None)
    await message.answer("Введите новый URL для кнопки (или '0' без изменений):")
    await state.set_state(EditVisualStates.waiting_for_edit_url)

@dp.message(EditVisualStates.waiting_for_edit_url, F.text, F.chat.type == "private")
async def handle_edit_url(message: Message, state: FSMContext):
    new_url = message.text.strip()
    data = await state.get_data()
    prefix = data['editing_prefix']
    index = data['edit_index']
    key = f"{prefix}_buttons"
    buttons = json.loads(db_get_setting(key))
    if new_url != '0':
        buttons[index]['url'] = new_url
        db_set_setting(key, json.dumps(buttons, ensure_ascii=False))
    await message.answer("✅ Кнопка обновлена!")
    await state.clear()
    admin = await is_admin(message.from_user.id) or is_owner(message.from_user.id)
    owner = is_owner(message.from_user.id)
    await message.answer("Главное меню", reply_markup=get_main_keyboard(admin, owner))

# ==================== Команды в групповом чате ====================
async def send_group_response(message: Message, text: str, delay: int = 60, reply_markup: InlineKeyboardMarkup = None):
    bot_msg = await message.reply(text, reply_markup=reply_markup)
    asyncio.create_task(delete_after_delay(bot, message.chat.id, message.message_id, bot_msg.message_id, delay))

@dp.message(Command("top"), F.chat.type.in_({"group", "supergroup"}))
async def group_top(message: Message):
    top = db_get_top_all(10)
    total = db_get_total_profit_all()
    if not top:
        await send_group_response(message, f"Пока нет профитов.\n<b>Общая касса:</b> {total:.2f} руб.", 60)
        return
    lines = [f"<b>🏆 Топ за всё время:</b>"]
    for i, u in enumerate(top, 1):
        name = u['username'] or u['full_name'] or f"ID {u['user_id']}"
        if u['hide_name']:
            name = "Скрыто"
        lines.append(f"{i}. {name} — {u['total']:.2f} руб.")
    lines.append(f"\n<b>Общая касса:</b> {total:.2f} руб.")
    await send_group_response(message, "\n".join(lines), 60, get_stats_switch_keyboard("all"))

@dp.message(Command("topd"), F.chat.type.in_({"group", "supergroup"}))
async def group_topd(message: Message):
    top = db_get_top_daily(10)
    total = db_get_total_profit_daily()
    if not top:
        await send_group_response(message, f"За сегодня профитов нет.\n<b>Общая касса за сегодня:</b> {total:.2f} руб.", 60)
        return
    lines = [f"<b>📅 Топ за сегодня:</b>"]
    for i, u in enumerate(top, 1):
        name = u['username'] or u['full_name'] or f"ID {u['user_id']}"
        if u['hide_name']:
            name = "Скрыто"
        lines.append(f"{i}. {name} — {u['total']:.2f} руб.")
    lines.append(f"\n<b>Общая касса за сегодня:</b> {total:.2f} руб.")
    await send_group_response(message, "\n".join(lines), 60, get_stats_switch_keyboard("day"))

@dp.message(Command("topw"), F.chat.type.in_({"group", "supergroup"}))
async def group_topw(message: Message):
    top = db_get_top_weekly(10)
    total = db_get_total_profit_weekly()
    if not top:
        await send_group_response(message, f"За последние 7 дней профитов нет.\n<b>Общая касса за неделю:</b> {total:.2f} руб.", 60)
        return
    lines = [f"<b>📆 Топ за неделю:</b>"]
    for i, u in enumerate(top, 1):
        name = u['username'] or u['full_name'] or f"ID {u['user_id']}"
        if u['hide_name']:
            name = "Скрыто"
        lines.append(f"{i}. {name} — {u['total']:.2f} руб.")
    lines.append(f"\n<b>Общая касса за неделю:</b> {total:.2f} руб.")
    await send_group_response(message, "\n".join(lines), 60, get_stats_switch_keyboard("week"))

@dp.callback_query(F.data.startswith("stats_"))
async def stats_switch(callback: CallbackQuery):
    period = callback.data.split("_")[1]
    if period == "day":
        top = db_get_top_daily(10)
        total = db_get_total_profit_daily()
        title = "📅 Топ за сегодня"
        current = "day"
    elif period == "week":
        top = db_get_top_weekly(10)
        total = db_get_total_profit_weekly()
        title = "📆 Топ за неделю"
        current = "week"
    else:
        top = db_get_top_all(10)
        total = db_get_total_profit_all()
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
    lines.append(f"\n<b>Общая касса:</b> {total:.2f} руб.")
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

@dp.message(Command("mp"), F.chat.type.in_({"group", "supergroup"}))
async def group_my_profile(message: Message):
    user_id = message.from_user.id
    user = db_get_user(user_id)
    if not user:
        await send_group_response(message, "Вы не зарегистрированы. Напишите боту в личные сообщения.", 15)
        return
    total_profit = db_get_user_total_profit(user_id)
    joined = datetime.fromisoformat(user['joined_date'])
    days_in_bot = (datetime.now() - joined).days
    text = (
        f"👤 <b>Профиль пользователя</b>\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"👤 Имя: {user['full_name']}\n"
        f"📱 Username: @{user['username'] if user['username'] else 'нет'}\n"
        f"📅 В боте: {days_in_bot} дн.\n"
        f"💰 <b>Профит:</b> {total_profit:.2f} руб."
    )
    await send_group_response(message, text, 15)

@dp.message(Command("help"), F.chat.type.in_({"group", "supergroup"}))
async def group_help(message: Message):
    text = (
        "🆘 <b>Доступные команды в чате:</b>\n"
        "/top - топ за всё время + общая касса\n"
        "/topd - топ за сегодня + общая касса\n"
        "/topw - топ за неделю + общая касса\n"
        "/card - информация о картах\n"
        "/prozvon - контакты для прозвона\n"
        "/mp - показать свой профиль\n"
        "/help - это сообщение\n\n"
        "<i>Сообщения будут автоматически удалены через указанное время.</i>"
    )
    await send_group_response(message, text, 15)

# ==================== Запуск бота ====================
async def main():
    init_db()
    db_set_admin(OWNER_ID, True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())