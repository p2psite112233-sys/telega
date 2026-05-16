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

    # --- 1. ГЛАВНОЕ МЕНЮ ---
    @dp.message(F.text == "/admin")
    async def admin_main_menu(message: types.Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await state.clear()
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика проекта", callback_data="adm_stats_main")],
            [InlineKeyboardButton(text="👥 Управление воркерами", callback_data="adm_workers_manage")],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="adm_close")]
        ])
        await message.answer("🛠 <b>Панель администратора</b>", parse_mode="HTML", reply_markup=kb)

    # --- 2. ВЫБОР ПЕРИОДА СТАТИСТИКИ ---
    @dp.callback_query(F.data == "adm_stats_main")
    async def stats_entry(call: types.CallbackQuery):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📅 День", callback_data="stats_day"),
                InlineKeyboardButton(text="📆 Неделя", callback_data="stats_week"),
                InlineKeyboardButton(text="🗓 Месяц", callback_data="stats_month")
            ],
            [InlineKeyboardButton(text="⏪ Назад", callback_data="adm_back_to_main")]
        ])
        await call.message.edit_text("📊 <b>Выберите период статистики:</b>", parse_mode="HTML", reply_markup=kb)

    # --- 3. ХЕНДЛЕР САМОЙ СТАТИСТИКИ (ТО, ЧТО НЕ РАБОТАЛО) ---
    @dp.callback_query(F.data.startswith("stats_"))
    async def stats_period(call: types.CallbackQuery):
        if call.from_user.id != ADMIN_ID: return await call.answer("Нет доступа")
        
        period = call.data.split("_")[1]
        now = datetime.now(timezone.utc)

        if period == "day": since = now - timedelta(days=1); label = "за день"
        elif period == "week": since = now - timedelta(weeks=1); label = "за неделю"
        else: since = now - timedelta(days=30); label = "за месяц"

        # Запрос статистики
        row = await db.db_fetchone("""
            SELECT 
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status='DONE') as done,
                SUM(total_usdt) FILTER (WHERE status='DONE') as turnover_usdt
            FROM orders WHERE created_at >= $1
        """, since)

        total = row["total"] or 0
        done = row["done"] or 0
        turnover = float(row["turnover_usdt"]) if row["turnover_usdt"] else 0.0

        text = (
            f"<b>📊 Статистика {label}</b>\n\n"
            f"• Всего заявок: {total}\n"
            f"• Выполнено: {done}\n"
            f"• Оборот: {turnover:.2f} USDT"
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏪ Назад", callback_data="adm_stats_main")]
        ])
        
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        await call.answer()

    # --- 4. УПРАВЛЕНИЕ ВОРКЕРАМИ ---
    @dp.callback_query(F.data == "adm_workers_manage")
    async def workers_menu(call: types.CallbackQuery):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Найти по ID", callback_data="adm_find_worker")],
            [InlineKeyboardButton(text="⏪ Назад", callback_data="adm_back_to_main")]
        ])
        await call.message.edit_text("👤 <b>Управление воркерами</b>", parse_mode="HTML", reply_markup=kb)

    @dp.callback_query(F.data == "adm_find_worker")
    async def find_worker_start(call: types.CallbackQuery, state: FSMContext):
        await state.set_state(AdminPanel.waiting_for_id)
        await call.message.edit_text("⌨️ <b>Введите ID воркера:</b>", parse_mode="HTML")

    @dp.message(AdminPanel.waiting_for_id)
    async def worker_profile(message: types.Message, state: FSMContext):
        if not message.text.isdigit(): return await message.answer("❌ Введите ID цифрами:")
        
        target_id = int(message.text)
        worker = await db.db_fetchone("SELECT * FROM workers WHERE user_id=$1", target_id)
        if not worker: return await message.answer("❌ Воркер не найден.")

        is_banned = worker.get("is_banned", False)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🚫 Бан" if not is_banned else "🔓 Разбан", callback_data=f"adm_u_ban_{target_id}"),
                InlineKeyboardButton(text="🗑 Уволить", callback_data=f"adm_u_fire_{target_id}")
            ],
            [InlineKeyboardButton(text="⏪ Назад", callback_data="adm_workers_manage")]
        ])
        await message.answer(f"👤 <b>Профиль:</b> <code>{target_id}</code>\nСтатус: {'БАН' if is_banned else 'ОК'}", 
                             parse_mode="HTML", reply_markup=kb)
        await state.clear()

    # --- 5. ЛОГИКА БАНА/УВОЛЬНЕНИЯ ---
    @dp.callback_query(F.data.startswith("adm_u_"))
    async def process_user_actions(call: types.CallbackQuery):
        parts = call.data.split("_")
        action, target_id = parts[2], int(parts[3])
        
        if action == "ban":
            await db.db_execute("UPDATE workers SET is_banned = NOT is_banned WHERE user_id=$1", target_id)
            await call.answer("Статус изменен", show_alert=True)
        elif action == "fire":
            await db.db_execute("DELETE FROM workers WHERE user_id=$1", target_id)
            set_role(target_id, "client")
            await call.answer("Уволен", show_alert=True)
        
        await call.message.delete()
        await admin_main_menu(call.message, None)

    # --- 6. ПРИЕМ ЗАЯВОК (ИЗ APPLY.PY) ---
    @dp.callback_query(F.data.startswith("adm_ap_"))
    async def admin_decision(call: types.CallbackQuery):
        parts = call.data.split("_")
        decision, target_id = parts[2], int(parts[3])

        if decision == "yes":
            await db.db_execute("INSERT INTO workers (user_id) VALUES ($1) ON CONFLICT DO NOTHING", target_id)
            set_role(target_id, "worker")
            await bot.send_message(target_id, "✅ Ваша заявка одобрена!")
            await call.message.edit_text(call.message.text + "\n\n🟢 <b>Статус: ПРИНЯТ</b>", parse_mode="HTML")
        else:
            await bot.send_message(target_id, "❌ Заявка отклонена.")
            await call.message.edit_text(call.message.text + "\n\n🔴 <b>Статус: ОТКЛОНЕН</b>", parse_mode="HTML")
        await call.answer()

    # --- НАВИГАЦИЯ ---
    @dp.callback_query(F.data == "adm_back_to_main")
    async def back_to_main(call: types.CallbackQuery, state: FSMContext):
        await state.clear()
        await admin_main_menu(call.message, state)

    @dp.callback_query(F.data == "adm_close")
    async def close_adm(call: types.CallbackQuery):
        await call.message.delete()
