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

    # --- СТАТИСТИКА ---
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
            orders_rows = await db.db_fetchall("SELECT status, total_usdt FROM orders WHERE created_at >= $1", since_naive)
            done_count, turnover = 0, 0.0
            for r in orders_rows:
                if str(r['status']).upper() in ['DONE', 'SUCCESS', 'COMPLETED']:
                    done_count += 1
                    turnover += float(r['total_usdt'] or 0)

            new_users = await db.db_fetchone("SELECT COUNT(*) as count FROM balances WHERE created_at >= $1", since_naive)
            total_users = await db.db_fetchone("SELECT COUNT(*) as count FROM balances")
            profit_row = await db.db_fetchone("SELECT SUM(amount) as total FROM bot_profit WHERE created_at >= $1", since_naive)
            net_profit = float(profit_row['total'] or 0) if profit_row and profit_row['total'] else 0.0

            text = (
                f"📊 <b>Статистика за {label}</b>\n\n"
                f"👥 <b>Аудитория:</b>\n"
                f"• Новых юзеров: <b>{new_users['count']}</b>\n"
                f"• Всего в базе: <b>{total_users['count']}</b>\n\n"
                f"📋 <b>Активность:</b>\n"
                f"• Успешных сделок: <b>{done_count}</b>\n\n"
                f"💰 <b>Финансы:</b>\n"
                f"• Оборот: <code>{turnover:.2f}</code> USDT\n"
                f"• Прибыль бота: <b>{net_profit:.4f}</b> USDT"
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏪ Назад", callback_data="adm_stats_menu")]])
            await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except:
            await call.answer("Ошибка в БД", show_alert=True)
        await call.answer()

    # --- КАССА ---
    @dp.callback_query(F.data == "adm_finance_menu")
    async def finance_menu(call: types.CallbackQuery):
        profit = await db.db_fetchone("SELECT SUM(amount) as total FROM bot_profit")
        withdraws = await db.db_fetchone("SELECT SUM(amount) as total FROM withdrawals")
        text = (
            "💰 <b>Финансовый аудит</b>\n\n"
            f"💵 Прибыль бота: <b>{float(profit['total'] or 0):.4f} USDT</b>\n"
            f"💸 Выплачено: <b>{float(withdraws['total'] or 0):.4f} USDT</b>"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏪ Назад", callback_data="adm_back_to_main")]])
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await call.answer()

    # --- УПРАВЛЕНИЕ ВОРКЕРАМИ ---
    @dp.callback_query(F.data == "adm_workers_manage")
    async def workers_manage(call: types.CallbackQuery):
        count = await db.db_fetchone("SELECT COUNT(*) FROM workers")
        apps = await db.db_fetchone("SELECT COUNT(*) FROM worker_applications WHERE status='pending'")
        text = f"👥 <b>Воркеры</b>\n\nВ штате: {count['count']}\nЗаявок: {apps['count']}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📨 Просмотр заявок", callback_data="adm_view_apps")],
            [InlineKeyboardButton(text="➕ Назначить по ID", callback_data="adm_add_worker_manual")],
            [InlineKeyboardButton(text="⏪ Назад", callback_data="adm_back_to_main")]
        ])
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await call.answer()

    @dp.callback_query(F.data == "adm_view_apps")
    async def view_apps(call: types.CallbackQuery):
        apps = await db.db_fetchall("SELECT user_id FROM worker_applications WHERE status='pending' LIMIT 5")
        if not apps: return await call.answer("📩 Новых заявок нет", show_alert=True)
        
        await call.message.delete()
        for app in apps:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Принять", callback_data=f"app_accept_{app['user_id']}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"app_decline_{app['user_id']}")
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
            try: await bot.send_message(t_id, "🎉 Ваша заявка одобрена! Теперь вы воркер.")
            except: pass
            await call.message.edit_text(f"✅ Юзер <code>{t_id}</code> принят в воркеры.")
        else:
            await db.db_execute("UPDATE worker_applications SET status='declined' WHERE user_id=$1", t_id)
            await call.message.edit_text(f"❌ Заявка <code>{t_id}</code> отклонена.")
        await call.answer()

    @dp.callback_query(F.data == "adm_add_worker_manual")
    async def add_worker_start(call: types.CallbackQuery, state: FSMContext):
        await state.set_state(AdminStates.waiting_for_worker_id)
        await call.message.edit_text("🔢 Введите ID юзера для назначения воркером:", 
                                     reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="adm_back_to_main")]]))
        await call.answer()

    @dp.message(AdminStates.waiting_for_worker_id)
    async def add_worker_finish(message: types.Message, state: FSMContext):
        try:
            t_id = int(message.text.strip())
            await db.db_execute("INSERT INTO workers (user_id) VALUES ($1) ON CONFLICT DO NOTHING", t_id)
            set_role(t_id, "worker")
            await message.answer(f"✅ Юзер <code>{t_id}</code> теперь воркер.")
            await state.clear()
            await send_admin_menu(message)
        except:
            await message.answer("Введите корректный ID (число).")

    # --- РАССЫЛКА ---
    @dp.callback_query(F.data == "adm_broadcast")
    async def broadcast_start(call: types.CallbackQuery, state: FSMContext):
        await state.set_state(AdminStates.waiting_for_broadcast_text)
        await call.message.edit_text("📢 Введите текст рассылки:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="adm_back_to_main")]]))
        await call.answer()

    @dp.message(AdminStates.waiting_for_broadcast_text)
    async def broadcast_finish(message: types.Message, state: FSMContext):
        query = "SELECT user_id FROM balances UNION SELECT user_id FROM workers UNION SELECT user_id FROM invoices"
        rows = await db.db_fetchall(query)
        u_ids = list(set([r['user_id'] for r in rows]))
        
        status_msg = await message.answer(f"🚀 Рассылка на {len(u_ids)} чел...")
        sent = 0
        for uid in u_ids:
            try:
                await bot.send_message(uid, message.text, parse_mode="HTML")
                sent += 1
                await asyncio.sleep(0.05)
            except: pass
            
        await status_msg.edit_text(f"✅ Готово! Доставлено: {sent}")
        await state.clear()
        await send_admin_menu(message)

    @dp.callback_query(F.data == "adm_close")
    async def close_admin(call: types.CallbackQuery):
        await call.message.delete()
        await call.answer()
