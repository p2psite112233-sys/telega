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

# Состояния для админки
class AdminPanel(StatesGroup):
    waiting_for_id = State()      # Для поиска воркера
    waiting_for_balance = State() # Для начисления баланса
    waiting_for_amount = State()  # Сумма пополнения

def register_admin(dp, bot: Bot):

    # --- 1. ГЛАВНОЕ МЕНЮ АДМИНКИ ---
    @dp.message(F.text == "/admin")
    async def admin_main_menu(message: types.Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await state.clear()
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика проекта", callback_data="adm_stats_main")],
            [InlineKeyboardButton(text="👥 Управление воркерами", callback_data="adm_workers_manage")],
            [InlineKeyboardButton(text="📢 Сделать рассылку", callback_data="adm_broadcast")]
        ])
        
        await message.answer("🛠 <b>Панель администратора</b>\n\nВыберите раздел для работы:", 
                             parse_mode="HTML", reply_markup=kb)

    # --- 2. ПОДМЕНЮ: УПРАВЛЕНИЕ ВОРКЕРАМИ ---
    @dp.callback_query(F.data == "adm_workers_manage")
    async def workers_menu(call: types.CallbackQuery, state: FSMContext):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Найти по ID", callback_data="adm_find_worker")],
            [InlineKeyboardButton(text="📜 Список всех (в лог)", callback_data="adm_list_workers")],
            [InlineKeyboardButton(text="⏪ Назад", callback_data="adm_back_to_main")]
        ])
        await call.message.edit_text("👤 <b>Управление персоналом</b>\n\nВведите ID для поиска или выберите действие:", 
                                     parse_mode="HTML", reply_markup=kb)

    # --- 3. ПОИСК ВОРКЕРА (FSM) ---
    @dp.callback_query(F.data == "adm_find_worker")
    async def find_worker_start(call: types.CallbackQuery, state: FSMContext):
        await state.set_state(AdminPanel.waiting_for_id)
        await call.message.edit_text("⌨️ <b>Введите Telegram ID воркера:</b>", parse_mode="HTML")

    @dp.message(AdminPanel.waiting_for_id)
    async def worker_profile(message: types.Message, state: FSMContext):
        if not message.text.isdigit():
            return await message.answer("❌ ID должен состоять только из цифр. Попробуйте еще раз:")
        
        target_id = int(message.text)
        worker = await db.db_fetchone("SELECT * FROM workers WHERE user_id=$1", target_id)
        
        if not worker:
            return await message.answer(f"❌ Юзер <code>{target_id}</code> не найден в базе воркеров.", parse_mode="HTML")
        
        await state.update_data(target_id=target_id)
        
        is_banned = worker.get("is_banned", False)
        status = "🔴 ЗАБЛОКИРОВАН" if is_banned else "🟢 АКТИВЕН"
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🚫 Бан" if not is_banned else "🔓 Разбан", callback_data=f"adm_usr_ban_{target_id}"),
                InlineKeyboardButton(text="🗑 Уволить", callback_data=f"adm_usr_fire_{target_id}")
            ],
            [InlineKeyboardButton(text="💰 Изменить баланс", callback_data=f"adm_usr_bal_edit")],
            [InlineKeyboardButton(text="⏪ Назад", callback_data="adm_workers_manage")]
        ])
        
        await message.answer(f"👤 <b>Профиль воркера:</b> <code>{target_id}</code>\n"
                             f"Статус: <b>{status}</b>", parse_mode="HTML", reply_markup=kb)

    # --- 4. ЛОГИКА КНОПОК (БАН / УВОЛЬНЕНИЕ) ---
    @dp.callback_query(F.data.startswith("adm_usr_"))
    async def process_user_actions(call: types.CallbackQuery, bot: Bot):
        parts = call.data.split("_")
        action = parts[2]
        
        if action == "bal": # Переход к балансу
            return await call.message.answer("Для изменения баланса используйте: <code>/give [ID] [сумма]</code>")

        target_id = int(parts[3])
        
        if action == "ban":
            await db.db_execute("UPDATE workers SET is_banned = NOT is_banned WHERE user_id=$1", target_id)
            await call.answer("Статус блокировки изменен", show_alert=True)
        
        elif action == "fire":
            await db.db_execute("DELETE FROM workers WHERE user_id=$1", target_id)
            set_role(target_id, "client")
            await call.message.answer(f"✅ Воркер {target_id} успешно уволен.")
            return await call.message.delete()

        # Обновляем сообщение (вызываем эмуляцию ввода ID)
        fake_msg = types.Message(message_id=0, date=datetime.now(), chat=call.message.chat, from_user=call.from_user, text=str(target_id))
        await worker_profile(fake_msg, None)

    # --- 5. ВЕРНУТЬСЯ В ГЛАВНОЕ МЕНЮ ---
    @dp.callback_query(F.data == "adm_back_to_main")
    async def back_to_main(call: types.CallbackQuery, state: FSMContext):
        await admin_main_menu(call.message, state)

    # --- 6. ТВОЯ СТАТИСТИКА (Вызов из меню) ---
    @dp.callback_query(F.data == "adm_stats_main")
    async def stats_entry(call: types.CallbackQuery):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📅 День", callback_data="stats_day"),
                InlineKeyboardButton(text="📆 Неделя", callback_data="stats_week"),
                InlineKeyboardButton(text="🗓 Месяц", callback_data="stats_month")
            ],
            [InlineKeyboardButton(text="⏪ Назад", callback_data="adm_back_to_main")]
        ])
        await call.message.edit_text("📊 <b>Выберите период статистики:</b>", parse_mode="HTML", reply_markup=keyboard)

    # --- ТУТ ДАЛЕЕ ИДУТ ТВОИ adm_ap_ (заявки) И stats_ (периоды) ---
    # Оставь их как есть, просто проверь callback_data
