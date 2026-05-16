import logging
from aiogram import types, F, Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime, timedelta, timezone
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

import db
from config import ADMIN_ID
from utils.shared import set_role

logger = logging.getLogger(__name__)

class AdminPanel(StatesGroup):
    waiting_for_id = State()

def register_admin(dp, bot: Bot):

    # --- ГЛАВНОЕ МЕНЮ ---
    @dp.message(F.text == "/admin")
    async def admin_main_menu(message: types.Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await state.clear()
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data="adm_stats_menu")],
            [InlineKeyboardButton(text="👥 Воркеры", callback_data="adm_workers_menu")],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="adm_close")]
        ])
        await message.answer("🛠 <b>Админ-панель</b>", parse_mode="HTML", reply_markup=kb)

    # --- ОБРАБОТКА ВСЕХ КНОПОК НАВИГАЦИИ ---
    @dp.callback_query(F.data == "adm_stats_menu")
    async def stats_menu(call: types.CallbackQuery):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📅 День", callback_data="st_day"),
                InlineKeyboardButton(text="📆 Неделя", callback_data="st_week"),
                InlineKeyboardButton(text="🗓 Месяц", callback_data="st_month")
            ],
            [InlineKeyboardButton(text="⏪ Назад", callback_data="adm_back")]
        ])
        await call.message.edit_text("📊 <b>Выберите период:</b>", parse_mode="HTML", reply_markup=kb)
        await call.answer()

    @dp.callback_query(F.data == "adm_workers_menu")
    async def workers_menu(call: types.CallbackQuery):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Найти воркера по ID", callback_data="adm_find")],
            [InlineKeyboardButton(text="⏪ Назад", callback_data="adm_back")]
        ])
        await call.message.edit_text("👤 <b>Управление персоналом</b>", parse_mode="HTML", reply_markup=kb)
        await call.answer()

    # --- ЛОГИКА СТАТИСТИКИ (поменял префикс на st_ для надежности) ---
    @dp.callback_query(F.data.startswith("st_"))
    async def process_stats(call: types.CallbackQuery):
        period = call.data.split("_")[1]
        now = datetime.now(timezone.utc)
        
        if period == "day": since = now - timedelta(days=1); lab = "день"
        elif period == "week": since = now - timedelta(weeks=1); lab = "неделю"
        else: since = now - timedelta(days=30); lab = "месяц"

        row = await db.db_fetchone("SELECT COUNT(*) as total FROM orders WHERE created_at >= $1", since)
        total = row["total"] if row else 0

        await call.message.edit_text(
            f"📈 Статистика за {lab}:\n\nВсего заказов: {total}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏪ Назад", callback_data="adm_stats_menu")]])
        )
        await call.answer()

    # --- ПОИСК И КНОПКИ УПРАВЛЕНИЯ ---
    @dp.callback_query(F.data == "adm_find")
    async def find_start(call: types.CallbackQuery, state: FSMContext):
        await state.set_state(AdminPanel.waiting_for_id)
        await call.message.edit_text("Введите ID воркера:")
        await call.answer()

    @dp.message(AdminPanel.waiting_for_id)
    async def find_finish(message: types.Message, state: FSMContext):
        if not message.text.isdigit(): return await message.answer("Только цифры!")
        target_id = int(message.text)
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚫 Бан/Разбан", callback_data=f"act_ban_{target_id}")],
            [InlineKeyboardButton(text="🗑 Уволить", callback_data=f"act_fire_{target_id}")],
            [InlineKeyboardButton(text="⏪ В меню", callback_data="adm_back")]
        ])
        await message.answer(f"Управление юзером <code>{target_id}</code>", parse_mode="HTML", reply_markup=kb)
        await state.clear()

    # --- ДЕЙСТВИЯ (БАН/УВОЛЬНЕНИЕ) ---
    @dp.callback_query(F.data.startswith("act_"))
    async def actions(call: types.CallbackQuery):
        parts = call.data.split("_")
        act, tid = parts[1], int(parts[2])
        
        if act == "ban":
            await db.db_execute("UPDATE workers SET is_banned = NOT is_banned WHERE user_id=$1", tid)
            await call.answer("Статус изменен")
        elif act == "fire":
            await db.db_execute("DELETE FROM workers WHERE user_id=$1", tid)
            set_role(tid, "client")
            await call.answer("Уволен")
        await call.message.delete()

    # --- СИСТЕМНЫЕ КНОПКИ ---
    @dp.callback_query(F.data == "adm_back")
    async def back(call: types.CallbackQuery, state: FSMContext):
        await admin_main_menu(call.message, state)
        await call.answer()

    @dp.callback_query(F.data == "adm_close")
    async def close(call: types.CallbackQuery):
        await call.message.delete()
        await call.answer()
