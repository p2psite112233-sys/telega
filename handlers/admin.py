import logging
import traceback
from datetime import datetime, timedelta
from aiogram import types, F, Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

import db
from config import ADMIN_ID

logger = logging.getLogger(__name__)

def register_admin(dp, bot: Bot):

    # --- ГЛАВНОЕ МЕНЮ АДМИНКИ ---
    @dp.message(F.text == "/admin")
    async def admin_main_menu(message: types.Message, state: FSMContext):
        if message.from_user.id != ADMIN_ID:
            return
        
        # Сбрасываем любой зависший ввод (стейт)
        await state.clear()
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data="adm_stats_menu")],
            [InlineKeyboardButton(text="👥 Воркеры", callback_data="adm_workers_menu")],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="adm_close")]
        ])
        
        await message.answer(
            "🛠 <b>Панель администратора</b>\n\n"
            "Здесь вы можете просматривать отчеты и управлять системой.",
            reply_markup=kb,
            parse_mode="HTML"
        )

    # --- МЕНЮ ВЫБОРА ПЕРИОДА ---
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
        await call.message.edit_text("📈 <b>Выберите период для отчета:</b>", reply_markup=kb, parse_mode="HTML")
        await call.answer()

    # --- ОБРАБОТКА СТАТИСТИКИ ---
    @dp.callback_query(F.data.startswith("st_"))
    async def process_stats(call: types.CallbackQuery):
        period = call.data.split("_")[1]
        now = datetime.now()
        
        if period == "day":
            since = now - timedelta(days=1)
            label = "день"
        elif period == "week":
            since = now - timedelta(weeks=1)
            label = "неделю"
        else:
            since = now - timedelta(days=30)
            label = "месяц"

        try:
            # Убираем часовые пояса для совместимости с БД
            since_naive = since.replace(tzinfo=None)

            # 1. Заявки и Оборот (Берем из orders)
            # В твоем коде профиля используется статус DONE
            orders_rows = await db.db_fetchall("""
                SELECT status, total_usdt, amount FROM orders WHERE created_at >= $1
            """, since_naive)

            stats = {'NEW': 0, 'IN_PROGRESS': 0, 'DONE': 0, 'CANCELLED': 0}
            turnover_usdt = 0.0
            turnover_rub = 0.0

            for r in orders_rows:
                # Приводим статус к верхнему регистру для сравнения
                st = str(r['status']).upper() if r['status'] else "NEW"
                
                if st in ['DONE', 'SUCCESS', 'COMPLETED']:
                    stats['DONE'] += 1
                    turnover_usdt += float(r['total_usdt'] or 0)
                    turnover_rub += float(r['amount'] or 0)
                elif st in ['CANCELLED', 'REJECTED']:
                    stats['CANCELLED'] += 1
                elif st in ['IN_PROGRESS', 'WAITING']:
                    stats['IN_PROGRESS'] += 1
                else:
                    stats['NEW'] += 1

            # 2. Чистая прибыль (Из таблицы bot_profit, куда пишет db.py)
            profit_row = await db.db_fetchone("""
                SELECT SUM(amount) as total FROM bot_profit WHERE created_at >= $1
            """, since_naive)
            net_profit = float(profit_row['total'] or 0) if profit_row and profit_row['total'] else 0.0

            # 3. Пополнения (Из таблицы invoices, статус 'paid')
            topup_row = await db.db_fetchone("""
                SELECT SUM(amount) as total FROM invoices 
                WHERE status='paid' AND created_at >= $1
            """, since_naive)
            total_topup = float(topup_row['total'] or 0) if topup_row and topup_row['total'] else 0.0

            # 4. Выведено воркерами (Из таблицы withdrawals)
            withdraw_row = await db.db_fetchone("""
                SELECT SUM(amount) as total FROM withdrawals WHERE created_at >= $1
            """, since_naive)
            worker_payout = float(withdraw_row['total'] or 0) if withdraw_row and withdraw_row['total'] else 0.0

            # 5. Пользователи и Топ
            workers_count = await db.db_fetchone("SELECT COUNT(*) as count FROM workers")
            top_worker = await db.db_fetchone("""
                SELECT worker_id, SUM(total_usdt) as sales 
                FROM orders 
                WHERE (status='DONE' OR status='SUCCESS' OR status='COMPLETED') 
                AND created_at >= $1 
                GROUP BY worker_id ORDER BY sales DESC LIMIT 1
            """, since_naive)

            # Формируем итоговый текст
            text = (
                f"📊 <b>Статистика за {label}</b>\n\n"
                f"📋 <b>Заявки</b>\n"
                f"• Всего: {len(orders_rows)}\n"
                f"• 🟡 Новые: {stats['NEW']}\n"
                f"• 🟢 В работе: {stats['IN_PROGRESS']}\n"
                f"• ✅ Завершённые: {stats['DONE']}\n"
                f"• ❌ Отменённые: {stats['CANCELLED']}\n\n"
                f"💰 <b>Финансы</b>\n"
                f"• Оборот: <code>{turnover_usdt:.4f}</code> USDT (<code>{turnover_rub:.0f}</code> RUB)\n"
                f"• Чистая прибыль: <b>{net_profit:.4f}</b> USDT\n"
                f"• Пополнено: {total_topup:.4f} USDT\n"
                f"• Выведено воркерами: {worker_payout:.4f} USDT\n\n"
                f"👥 <b>Пользователи</b>\n"
                f"• Всего воркеров: {workers_count['count']}\n\n"
                f"🏆 <b>Топ воркеров</b>\n"
            )

            if top_worker and top_worker['worker_id']:
                text += f"  1. ID {top_worker['worker_id']} — {float(top_worker['sales']):.4f} USDT"
            else:
                text += "  Данных пока нет"

            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏪ Назад", callback_data="adm_stats_menu")]
            ])

            await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
            
        except Exception as e:
            logger.error(f"Ошибка статистики: {e}")
            traceback.print_exc()
            await call.message.answer(f"⚠️ Ошибка формирования отчета: <code>{e}</code>", parse_mode="HTML")
        
        await call.answer()

    # --- ВСПОМОГАТЕЛЬНЫЕ КНОПКИ ---
    @dp.callback_query(F.data == "adm_back_to_main")
    async def back_to_main(call: types.CallbackQuery, state: FSMContext):
        await admin_main_menu(call.message, state)
        await call.answer()

    @dp.callback_query(F.data == "adm_close")
    async def close_admin(call: types.CallbackQuery):
        try:
            await call.message.delete()
        except:
            pass
        await call.answer()
