import logging
from aiogram import types, F, Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime, timedelta
from aiogram.fsm.context import FSMContext

import db
from config import ADMIN_ID

logger = logging.getLogger(__name__)

def register_admin(dp, bot: Bot):

    @dp.message(F.text == "/admin")
    async def admin_main_menu(message: types.Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID: return
        await state.clear()
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data="adm_stats_menu")],
            [InlineKeyboardButton(text="👥 Воркеры", callback_data="adm_workers_menu")],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="adm_close")]
        ])
        await message.answer("🛠 <b>Панель администратора</b>", reply_markup=kb)

    @dp.callback_query(F.data == "adm_stats_menu")
    async def stats_menu(call: types.CallbackQuery, state: FSMContext):
        await state.clear()
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📅 День", callback_data="st_day"),
                InlineKeyboardButton(text="📆 Неделя", callback_data="st_week"),
                InlineKeyboardButton(text="🗓 Месяц", callback_data="st_month")
            ],
            [InlineKeyboardButton(text="⏪ Назад", callback_data="adm_back_to_main")]
        ])
        await call.message.edit_text("📈 <b>Выберите период для отчета:</b>", reply_markup=kb)
        await call.answer()

    @dp.callback_query(F.data.startswith("st_"))
    async def process_stats(call: types.CallbackQuery):
        period = call.data.split("_")[1]
        now = datetime.now()
        
        if period == "day": since = now - timedelta(days=1); label = "день"
        elif period == "week": since = now - timedelta(weeks=1); label = "неделю"
        else: since = now - timedelta(days=30); label = "месяц"

        try:
            since_naive = since.replace(tzinfo=None)

            # 1. Считаем заказы по статусам
            orders_stats = await db.db_fetchall("""
                SELECT status, COUNT(*) as count, SUM(total_usdt) as sum_usdt, SUM(amount) as sum_rub 
                FROM orders WHERE created_at >= $1 GROUP BY status
            """, since_naive)

            stats_dict = {s: 0 for s in ['NEW', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED']}
            total_orders = 0
            turnover_usdt = 0.0
            turnover_rub = 0.0

            for row in orders_stats:
                status = row['status']
                count = row['count']
                stats_dict[status] = count
                total_orders += count
                if status == 'COMPLETED':
                    turnover_usdt = float(row['sum_usdt'] or 0)
                    turnover_rub = float(row['sum_rub'] or 0)

            # 2. Пополнения (из таблицы invoices)
            topup_row = await db.db_fetchone("SELECT SUM(amount) as total FROM invoices WHERE status='paid' AND created_at >= $1", since_naive)
            total_topup = float(topup_row['total'] or 0) if topup_row else 0.0

            # 3. Пользователи и воркеры
            clients_count = await db.db_fetchone("SELECT COUNT(DISTINCT user_id) as count FROM orders WHERE created_at >= $1", since_naive)
            workers_count = await db.db_fetchone("SELECT COUNT(*) as count FROM workers")
            
            # 4. Топ воркеров (кто закрыл больше всех USDT)
            top_worker = await db.db_fetchone("""
                SELECT worker_id, SUM(total_usdt * 0.8) as profit 
                FROM orders WHERE status='COMPLETED' AND created_at >= $1 
                GROUP BY worker_id ORDER BY profit DESC LIMIT 1
            """, since_naive)

            # Формируем текст
            text = (
                f"📊 <b>Статистика за {label}</b>\n\n"
                f"📋 <b>Заявки</b>\n"
                f"• Всего: {total_orders}\n"
                f"• 🟡 Новые: {stats_dict.get('NEW', 0)}\n"
                f"• 🟢 В работе: {stats_dict.get('IN_PROGRESS', 0)}\n"
                f"• ✅ Завершённые: {stats_dict.get('COMPLETED', 0)}\n"
                f"• ❌ Отменённые: {stats_dict.get('CANCELLED', 0)}\n\n"
                f"💰 <b>Финансы</b>\n"
                f"• Оборот: {turnover_usdt:.4f} USDT ({turnover_rub:.0f} RUB)\n"
                f"• Чистая прибыль: {(turnover_usdt * 0.2):.4f} USDT\n"
                f"• Пополнено: {total_topup:.4f} USDT\n"
                f"• Выведено воркерами: 0.0000 USDT\n\n"
                f"👥 <b>Пользователи</b>\n"
                f"• Активных клиентов: {clients_count['count'] if clients_count else 0}\n"
                f"• Всего воркеров: {workers_count['count'] if workers_count else 0}\n\n"
                f"🏆 <b>Топ воркеров</b>\n"
            )
            
            if top_worker and top_worker['worker_id']:
                text += f"  1. ID {top_worker['worker_id']} — {top_worker['profit']:.4f} USDT"
            else:
                text += "  Данных пока нет"

            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏪ Назад", callback_data="adm_stats_menu")]
            ])
            await call.message.edit_text(text, reply_markup=kb)
            
        except Exception as e:
            logger.error(f"Ошибка статистики: {e}")
            await call.message.answer(f"⚠️ Ошибка формирования отчета: <code>{e}</code>")
        
        await call.answer()

    @dp.callback_query(F.data == "adm_back_to_main")
    async def back_to_main(call: types.CallbackQuery, state: FSMContext):
        await admin_main_menu(call.message, state)
        await call.answer()

    @dp.callback_query(F.data == "adm_close")
    async def close_admin(call: types.CallbackQuery):
        await call.message.delete()
        await call.answer()
