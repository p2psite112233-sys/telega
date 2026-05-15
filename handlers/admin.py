from aiogram import types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime, timedelta

import db
from config import ADMIN_ID


def register_admin(dp, bot):

    @dp.message(F.text == "/stats")
    async def stats(message: types.Message):
        if message.from_user.id != ADMIN_ID:
            return

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📅 День", callback_data="stats_day"),
                InlineKeyboardButton(text="📆 Неделя", callback_data="stats_week"),
                InlineKeyboardButton(text="🗓 Месяц", callback_data="stats_month")
            ]
        ])
        await message.answer(
            "<b>📊 Статистика Send$Paid</b>\n\nВыберите период:",
            parse_mode="HTML",
            reply_markup=keyboard
        )

    @dp.callback_query(F.data.startswith("stats_"))
    async def stats_period(call: types.CallbackQuery):
        if call.from_user.id != ADMIN_ID:
            return await call.answer("Нет доступа", show_alert=True)

        period = call.data.split("_")[1]
        now = datetime.utcnow()

        if period == "day":
            since = now - timedelta(days=1)
            label = "за день"
        elif period == "week":
            since = now - timedelta(weeks=1)
            label = "за неделю"
        else:
            since = now - timedelta(days=30)
            label = "за месяц"

        # Все заявки одним запросом
        row = await db.db_fetchone("""
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status='DONE') as done,
                COUNT(*) FILTER (WHERE status='IN_PROGRESS') as active,
                COUNT(*) FILTER (WHERE status='NEW') as new,
                COUNT(*) FILTER (WHERE status='CANCELLED') as cancelled,
                SUM(total_usdt) FILTER (WHERE status='DONE') as turnover_usdt,
                SUM(amount) FILTER (WHERE status='DONE') as turnover_rub
            FROM orders WHERE created_at >= $1
        """, since)

        total_orders = row["total"] or 0
        done_orders = row["done"] or 0
        active_orders = row["active"] or 0
        new_orders = row["new"] or 0
        cancelled_orders = row["cancelled"] or 0
        turnover_usdt = float(row["turnover_usdt"]) if row["turnover_usdt"] else 0.0
        turnover_rub = float(row["turnover_rub"]) if row["turnover_rub"] else 0.0

        # Прибыль бота
        row = await db.db_fetchone("SELECT SUM(amount) FROM bot_profit WHERE created_at >= $1", since)
        bot_profit = float(row["sum"]) if row and row["sum"] else 0.0

        # Пополнения за период
        row = await db.db_fetchone(
            "SELECT SUM(amount) FROM invoices WHERE status='paid' AND created_at >= $1", since
        )
        total_topped = float(row["sum"]) if row and row["sum"] else 0.0

        # Выводы воркеров
        row = await db.db_fetchone("SELECT SUM(amount) FROM withdrawals WHERE created_at >= $1", since)
        total_withdrawn = float(row["sum"]) if row and row["sum"] else 0.0

        # Пользователи
        row = await db.db_fetchone("SELECT COUNT(DISTINCT user_id) FROM orders WHERE created_at >= $1", since)
        users_count = row["count"] if row else 0

        row = await db.db_fetchone("SELECT COUNT(*) FROM workers")
        workers_count = row["count"] if row else 0

        # Топ воркеров
        top_workers = await db.db_fetchall("""
            SELECT worker_id, SUM(total_usdt * 0.8) as earned
            FROM orders
            WHERE status='DONE' AND created_at >= $1
            GROUP BY worker_id
            ORDER BY earned DESC
            LIMIT 5
        """, since)

        top_text = ""
        for i, w in enumerate(top_workers, 1):
            earned = float(w["earned"]) if w["earned"] else 0
            top_text += f"  {i}. ID {w['worker_id']} — {earned:.4f} USDT\n"

        text = (
            f"<b>📊 Статистика {label}</b>\n\n"
            f"<b>📋 Заявки</b>\n"
            f"• Всего: {total_orders}\n"
            f"• 🟡 Новые: {new_orders}\n"
            f"• 🟢 В работе: {active_orders}\n"
            f"• ✅ Завершённые: {done_orders}\n"
            f"• ❌ Отменённые: {cancelled_orders}\n\n"
            f"<b>💰 Финансы</b>\n"
            f"• Оборот: {turnover_usdt:.4f} USDT ({turnover_rub:.0f} RUB)\n"
            f"• Чистая прибыль: {bot_profit:.4f} USDT\n"
            f"• Пополнено: {total_topped:.4f} USDT\n"
            f"• Выведено воркерами: {total_withdrawn:.4f} USDT\n\n"
            f"<b>👥 Пользователи</b>\n"
            f"• Активных клиентов: {users_count}\n"
            f"• Всего воркеров: {workers_count}\n\n"
            f"<b>🏆 Топ воркеров</b>\n"
            f"{top_text if top_text else '  Нет данных'}"
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📅 День", callback_data="stats_day"),
                InlineKeyboardButton(text="📆 Неделя", callback_data="stats_week"),
                InlineKeyboardButton(text="🗓 Месяц", callback_data="stats_month")
            ]
        ])

        try:
            await call.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        except Exception as e:
            print(f"[stats] edit error: {e}")
            await call.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
        await call.answer()
