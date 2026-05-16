import logging
import asyncio
import traceback
from datetime import datetime, timedelta
from aiogram import types, F, Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

import db
from config import ADMIN_ID
from utils.shared import set_role

logger = logging.getLogger(__name__)

class AdminStates(StatesGroup):
    waiting_for_broadcast_text = State()
    waiting_for_worker_id = State()

def register_admin(dp, bot: Bot):

    # --- ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ МЕНЮ ---
    async def send_admin_menu(message: types.Message):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 Статистика", callback_data="adm_stats_menu"),
                InlineKeyboardButton(text="💰 Касса", callback_data="adm_finance_menu")
            ],
            [
                InlineKeyboardButton(text="👥 Воркеры", callback_data="adm_workers_manage"),
                InlineKeyboardButton(text="📢 Рассылка", callback_data="adm_broadcast")
            ],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="adm_close")]
        ])
        text = "🛠 <b>Панель управления проектом</b>"
        try:
            await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await message.answer(text, reply_markup=kb, parse_mode="HTML")

    @dp.message(F.text == "/admin")
    async def admin_start(message: types.Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await state.clear()
        await send_admin_menu(message)

    @dp.callback_query(F.data == "adm_back_to_main")
    async def back_to_main(call: types.CallbackQuery, state: FSMContext):
        await state.clear()
        await send_admin_menu(call.message)
        await call.answer()

    # --- БЛОК 1: СТАТИСТИКА ---
    @dp.callback_query(F.data == "adm_stats_menu")
    async def stats_menu(call: types.CallbackQuery):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="День", callback_data="st_day"),
                InlineKeyboardButton(text="Неделя", callback_data="st_week"),
                InlineKeyboardButton(text="Месяц", callback_data="st_month")
            ],
            [InlineKeyboardButton(text="⏪ Назад", callback_data="adm_back_to_main")]
        ])
        await call.message.edit_text("📈 <b>Выберите период отчета:</b>", reply_markup=kb, parse_mode="HTML")
        await call.answer()

    @dp.callback_query(F.data.startswith("st_"))
    async def process_stats(call: types.CallbackQuery):
        period = call.data.split("_")[1]
        now = datetime.now()
        since = now - (timedelta(days=1) if period == "day" else timedelta(weeks=1) if period == "week" else timedelta(days=30))
        label = "день" if period == "day" else "неделю" if period == "week" else "месяц"

        try:
            since_naive = since.replace(tzinfo=None)
            orders_rows = await db.db_fetchall("SELECT status, total_usdt, amount FROM orders WHERE created_at >= $1", since_naive)
            
            stats = {'NEW': 0, 'IN_PROGRESS': 0, 'DONE': 0, 'CANCELLED': 0}
            turnover_usdt, turnover_rub = 0.0, 0.0

            for r in orders_rows:
                st = str(r['status']).upper()
                if st in ['DONE', 'SUCCESS', 'COMPLETED']:
                    stats['DONE'] += 1
                    turnover_usdt += float(r['total_usdt'] or 0)
                    turnover_rub += float(r['amount'] or 0)
                elif st in ['CANCELLED', 'REJECTED']: stats['CANCELLED'] += 1
                elif st in ['IN_PROGRESS', 'WAITING']: stats['IN_PROGRESS'] += 1
                else: stats['NEW'] += 1

            profit_row = await db.db_fetchone("SELECT SUM(amount) as total FROM bot_profit WHERE created_at >= $1", since_naive)
            net_profit = float(profit_row['total'] or 0) if profit_row and profit_row['total'] else 0.0

            text = (
                f"📊 <b>Статистика за {label}</b>\n\n"
                f"✅ Завершённые: {stats['DONE']}\n"
                f"💰 Оборот: <code>{turnover_usdt:.4f}</code> USDT\n"
                f"💎 Прибыль (4%): <b>{net_profit:.4f}</b> USDT\n"
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏪ Назад", callback_data="adm_stats_menu")]])
            await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception as e:
            logger.error(traceback.format_exc())
            await call.answer("Ошибка БД", show_alert=True)
        await call.answer()

    # --- БЛОК 2: КАССА ---
    @dp.callback_query(F.data == "adm_finance_menu")
    async def finance_menu(call: types.CallbackQuery):
        profit = await db.db_fetchone("SELECT SUM(amount) as total FROM bot_profit")
        withdraws = await db.db_fetchone("SELECT SUM(amount) as total FROM withdrawals")
        
        text = (
            "💰 <b>Финансовый аудит (Всего)</b>\n\n"
            f"💵 Чистая прибыль: <b>{float(profit['total'] or 0):.4f} USDT</b>\n"
            f"💸 Выплачено воркерам: <b>{float(withdraws['total'] or 0):.4f} USDT</b>"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏪ Назад", callback_data="adm_back_to_main")]])
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await call.answer()

    # --- БЛОК 3: ВОРКЕРЫ ---
    @dp.callback_query(F.data == "adm_workers_manage")
    async def workers_manage(call: types.CallbackQuery):
        count = await db.db_fetchone("SELECT COUNT(*) FROM workers")
        apps = await db.db_fetchone("SELECT COUNT(*) FROM worker_applications WHERE status='pending'")
        text = f"👥 <b>Воркеры</b>\n\nШтат: {count['count']}\nЗаявок: {apps['count']}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📨 Заявки", callback_data="adm_view_apps")],
            [InlineKeyboardButton(text="➕ Добавить по ID", callback_data="adm_add_worker_manual")],
            [InlineKeyboardButton(text="⏪ Назад", callback_data="adm_back_to_main")]
        ])
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await call.answer()

    @dp.callback_query(F.data == "adm_view_apps")
    async def view_apps(call: types.CallbackQuery):
        apps = await db.db_fetchall("SELECT user_id FROM worker_applications WHERE status='pending' LIMIT 5")
        if not apps: return await call.answer("Заявок нет", show_alert=True)
        await call.message.delete()
        for app in apps:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Принять", callback_data=f"app_accept_{app['user_id']}"),
                InlineKeyboardButton(text="❌ Отклон.", callback_data=f"app_decline_{app['user_id']}")
            ]])
            await call.message.answer(f"👤 Заявка: <code>{app['user_id']}</code>", reply_markup=kb, parse_mode="HTML")
        await call.answer()

    @dp.callback_query(F.data.startswith("app_"))
    async def process_app(call: types.CallbackQuery):
        parts = call.data.split("_")
        action, t_id = parts[1], int(parts[2])
        if action == "accept":
            await db.db_execute("INSERT INTO workers (user_id) VALUES ($1) ON CONFLICT DO NOTHING", t_id)
            await db.db_execute("UPDATE worker_applications SET status='accepted' WHERE user_id=$1", t_id)
            set_role(t_id, "worker")
            await call.message.edit_text(f"✅ {t_id} принят")
        else:
            await db.db_execute("UPDATE worker_applications SET status='declined' WHERE user_id=$1", t_id)
            await call.message.edit_text(f"❌ {t_id} отклонен")
        await call.answer()

    # --- БЛОК 4: РАССЫЛКА ---
    @dp.callback_query(F.data == "adm_broadcast")
    async def broadcast_start(call: types.CallbackQuery, state: FSMContext):
        await state.set_state(AdminStates.waiting_for_broadcast_text)
        await call.message.edit_text("📢 Введите текст рассылки:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="adm_back_to_main")]]))
        await call.answer()

    @dp.message(AdminStates.waiting_for_broadcast_text)
    async def broadcast_finish(message: types.Message, state: FSMContext):
        users = await db.db_fetchall("SELECT user_id FROM balances UNION SELECT user_id FROM invoices")
        await message.answer(f"🚀 Рассылка на {len(users)} чел...")
        for u in users:
            try:
                await bot.send_message(u['user_id'], message.text, parse_mode="HTML")
                await asyncio.sleep(0.05)
            except: pass
        await state.clear()
        await send_admin_menu(message)

    @dp.callback_query(F.data == "adm_close")
    async def close(call: types.CallbackQuery):
        await call.message.delete()
