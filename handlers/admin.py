import logging
from aiogram import types, F, Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime, timedelta, timezone

import db
from config import ADMIN_ID
from utils.shared import set_role

logger = logging.getLogger(__name__)

def register_admin(dp, bot: Bot):

    # --- 1. ОБРАБОТКА ЗАЯВОК ВОРКЕРОВ (Прием/Отказ) ---
    @dp.callback_query(F.data.startswith("adm_ap_"))
    async def admin_decision(call: types.CallbackQuery):
        if call.from_user.id != ADMIN_ID:
            return await call.answer("Нет доступа", show_alert=True)

        # Формат callback: adm_ap_[yes/no]_[user_id]
        parts = call.data.split("_")
        decision = parts[2]
        target_id = int(parts[3])

        if decision == "yes":
            # Сохраняем в БД воркеров
            await db.db_execute("INSERT INTO workers (user_id) VALUES ($1) ON CONFLICT DO NOTHING", target_id)
            set_role(target_id, "worker")
            
            try:
                await bot.send_message(
                    target_id, 
                    "🎉 <b>Ваша заявка одобрена!</b>\nТеперь вам доступны функции воркера. Введите /start для обновления меню.",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Failed to notify user {target_id}: {e}")
            
            await call.message.edit_text(call.message.text + "\n\n✅ <b>Статус: ПРИНЯТ</b>", parse_mode="HTML")
        
        else:
            # Кулдаун 7 дней при отказе
            next_apply = datetime.now(timezone.utc) + timedelta(days=7)
            await db.db_execute(
                """INSERT INTO worker_applications (user_id, status, next_apply_at) 
                   VALUES ($1, 'rejected', $2) 
                   ON CONFLICT (user_id) DO UPDATE SET next_apply_at=$2, status='rejected'""",
                target_id, next_apply
            )
            
            try:
                await bot.send_message(
                    target_id, 
                    "❌ <b>Ваша заявка отклонена.</b>\nПовторная подача возможна через 7 дней.",
                    parse_mode="HTML"
                )
            except:
                pass
            
            await call.message.edit_text(call.message.text + "\n\n🔴 <b>Статус: ОТКЛОНЕН</b>", parse_mode="HTML")
        
        await call.answer()

    # --- 2. НАЧИСЛЕНИЕ БАЛАНСА (Ручное) ---
    # Команда: /give [ID] [СУММА]
    @dp.message(F.text.startswith("/give"))
    async def admin_give_balance(message: types.Message):
        if message.from_user.id != ADMIN_ID:
            return
        
        try:
            args = message.text.split()
            if len(args) < 3:
                return await message.answer("📝 Формат: <code>/give [ID] [Сумма]</code>", parse_mode="HTML")
                
            target_id = int(args[1])
            amount = float(args[2])
            
            await db.add_balance(target_id, amount)
            new_balance = await db.get_balance(target_id)
            
            await message.answer(
                f"✅ <b>Баланс пополнен!</b>\n\n"
                f"👤 Юзер: <code>{target_id}</code>\n"
                f"💰 Начислено: <b>{amount} USDT</b>\n"
                f"💎 Итоговый баланс: <b>{new_balance} USDT</b>",
                parse_mode="HTML"
            )
            
            try:
                await bot.send_message(
                    target_id, 
                    f"🎁 <b>Вам начислен баланс!</b>\n\nСумма: <code>{amount} USDT</code>\nПроверьте состояние в профиле.",
                    parse_mode="HTML"
                )
            except:
                pass
                
        except ValueError:
            await message.answer("❌ Ошибка: проверьте ID и сумму (число).")
        except Exception as e:
            logger.error(f"Give balance error: {e}")
            await message.answer(f"❌ Ошибка БД: {e}")

    # --- 3. СТАТИСТИКА ---
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
        now = datetime.now(timezone.utc)

        if period == "day":
            since = now - timedelta(days=1)
            label = "за день"
        elif period == "week":
            since = now - timedelta(weeks=1)
            label = "за неделю"
        else:
            since = now - timedelta(days=30)
            label = "за месяц"

        # Сбор данных из БД
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

        # Прибыль и Пополнения
        profit_row = await db.db_fetchone("SELECT SUM(amount) FROM bot_profit WHERE created_at >= $1", since)
        bot_profit = float(profit_row["sum"]) if profit_row and profit_row["sum"] else 0.0

        invoices_row = await db.db_fetchone("SELECT SUM(amount) FROM invoices WHERE status='paid' AND created_at >= $1", since)
        total_topped = float(invoices_row["sum"]) if invoices_row and invoices_row["sum"] else 0.0

        # Воркеры
        workers_count_row = await db.db_fetchone("SELECT COUNT(*) FROM workers")
        workers_count = workers_count_row["count"] if workers_count_row else 0

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
            f"• Пополнено: {total_topped:.4f} USDT\n\n"
            f"<b>👥 Воркеры</b>\n"
            f"• Всего в штате: {workers_count}\n"
            f"<b>🏆 Топ периода:</b>\n"
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
        except:
            await call.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
        
        await call.answer()
