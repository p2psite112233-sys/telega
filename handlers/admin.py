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
            done_count, turnover_usdt, turnover_rub = 0, 0.0, 0.0
            for r in orders_rows:
                if str(r['status']).upper() in ['DONE', 'SUCCESS', 'COMPLETED']:
                    done_count += 1
                    turnover_usdt += float(r['total_usdt'] or 0)
                    turnover_rub += float(r['amount'] or 0)
            new_users = await db.db_fetchone("SELECT COUNT(*) as count FROM balances WHERE created_at >= $1", since_naive)
            total_users = await db.db_fetchone("SELECT COUNT(*) as count FROM balances")
            profit_row = await db.db_fetchone("SELECT SUM(amount) as total FROM bot_profit WHERE created_at >= $1", since_naive)
            net_profit = float(profit_row['total'] or 0) if profit_row and profit_row['total'] else 0.0
            text = (
                f"📊 <b>Статистика за {label}</b>\n\n"
                f"👥 <b>Аудитория:</b>\n• Новых юзеров: <b>{new_users['count']}</b>\n• Всего в базе: <b>{total_users['count']}</b>\n\n"
                f"📋 <b>Активность:</b>\n• Успешных сделок: <b>{done_count}</b>\n\n"
                f"💰 <b>Финансы:</b>\n• Оборот: <code>{turnover_usdt:.4f}</code> USDT (<code>{turnover_rub:.0f}</code> RUB)\n• Прибыль бота: <b>{net_profit:.4f}</b> USDT"
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏪ Назад", callback_data="adm_stats_menu")]])
            await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except:
            await call.answer("Ошибка в статистике", show_alert=True)
            return
        await call.answer()

    @dp.callback_query(F.data == "adm_finance_menu")
    async def finance_menu(call: types.CallbackQuery):
        try:
            profit = await db.db_fetchone("SELECT SUM(amount) as total FROM bot_profit")
            turnover_data = await db.db_fetchone("SELECT SUM(total_usdt) as usdt, SUM(amount) as rub FROM orders WHERE status IN ('DONE', 'SUCCESS', 'COMPLETED')")
            deposits = await db.db_fetchone("SELECT SUM(amount) as total FROM invoices WHERE status IN ('paid', 'SUCCESS')")
            withdraws = await db.db_fetchone("SELECT SUM(amount) as total FROM withdrawals")
            p_val = float(profit['total'] or 0)
            t_usdt = float(turnover_data['usdt'] or 0)
            t_rub = float(turnover_data['rub'] or 0)
            d_val = float(deposits['total'] or 0)
            w_val = float(withdraws['total'] or 0)
            text = (
                "💰 <b>Финансовый аудит</b>\n\n"
                f"💵 <b>Прибыль бота:</b> <code>{p_val:.4f}</code> USDT\n"
                f"💸 <b>Выплачено:</b> <code>{w_val:.4f}</code> USDT\n"
                "--------------------------\n"
                f"💰 <b>Оборот:</b> <code>{t_usdt:.4f}</code> USDT (<code>{t_rub:.0f}</code> RUB)\n"
                f"➕ <b>Пополнено:</b> <code>{d_val:.4f}</code> USDT\n"
                f"📥 <b>Выведено воркерами:</b> <code>{w_val:.4f}</code> USDT"
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏪ Назад", callback_data="adm_back_to_main")]])
            await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except:
            await call.answer("Ошибка в кассе", show_alert=True)
            return
        await call.answer()

    @dp.callback_query(F.data == "adm_workers_manage")
    async def workers_manage(call: types.CallbackQuery):
        count = await db.db_fetchone("SELECT COUNT(*) FROM workers")
        apps = await db.db_fetchone("SELECT COUNT(*) FROM worker_applications WHERE status='pending'")
        text = f"👥 <b>Управление воркерами</b>\n\nВ штате: <b>{count['count']}</b>\nЗаявок: <b>{apps['count']}</b>"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📨 Просмотр заявок", callback_data="adm_view_apps")],
            [InlineKeyboardButton(text="👥 Все воркеры", callback_data="adm_list_workers")],
            [InlineKeyboardButton(text="➕ Добавить по ID", callback_data="adm_add_worker_manual")],
            [InlineKeyboardButton(text="⏪ Назад", callback_data="adm_back_to_main")]
        ])
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await call.answer()

    @dp.callback_query(F.data == "adm_list_workers")
    async def list_workers(call: types.CallbackQuery):
        workers = await db.db_fetchall("SELECT w.user_id FROM workers w ORDER BY w.user_id DESC LIMIT 20")
        if not workers:
            return await call.answer("👥 Воркеров нет", show_alert=True)
        buttons = []
        for w in workers:
            uid = w['user_id']
            try:
                chat = await bot.get_chat(uid)
                name = f"@{chat.username}" if chat.username else f"ID: {uid}"
            except:
                name = f"ID: {uid}"
            buttons.append([InlineKeyboardButton(text=f"👤 {name}", callback_data=f"adm_worker_info_{uid}")])
        buttons.append([InlineKeyboardButton(text="⏪ Назад", callback_data="adm_workers_manage")])
        await call.message.edit_text("👥 <b>Список воркеров:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        await call.answer()

    @dp.callback_query(F.data.startswith("adm_worker_info_"))
    async def worker_info(call: types.CallbackQuery):
        uid = int(call.data.split("_")[3])
        try:
            chat = await bot.get_chat(uid)
            name = f"@{chat.username}" if chat.username else f"ID: {uid}"
        except:
            name = f"ID: {uid}"
        done = await db.db_fetchone("SELECT COUNT(*) FROM orders WHERE worker_id=$1 AND status='DONE'", uid)
        balance = await db.get_balance(uid)
        text = (
            f"👤 <b>Воркер {name}</b>\n"
            f"ID: <code>{uid}</code>\n\n"
            f"✅ Выполнено: {done['count']} заявок\n"
            f"💰 Баланс: {balance:.2f} USDT"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔴 Снять с должности", callback_data=f"adm_fire_worker_{uid}")],
            [InlineKeyboardButton(text="⏪ Назад", callback_data="adm_list_workers")]
        ])
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        await call.answer()

    @dp.callback_query(F.data.startswith("adm_fire_worker_"))
    async def fire_worker(call: types.CallbackQuery):
        uid = int(call.data.split("_")[3])
        await db.db_execute("DELETE FROM workers WHERE user_id=$1", uid)
        set_role(uid, "user")
        try:
            await bot.send_message(uid, "❌ Вы были сняты с должности воркера.")
        except:
            pass
        await call.message.edit_text(f"✅ Воркер <code>{uid}</code> снят с должности.", parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏪ Назад", callback_data="adm_list_workers")]]))
        await call.answer()

    @dp.callback_query(F.data == "adm_view_apps")
    async def view_apps(call: types.CallbackQuery):
        apps = await db.db_fetchall("SELECT user_id FROM worker_applications WHERE status='pending' LIMIT 5")
        if not apps: return await call.answer("📩 Заявок нет", show_alert=True)
        await call.message.delete()
        for app in apps:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Принять", callback_data=f"app_accept_{app['user_id']}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"app_decline_{app['user_id']}")
            ]])
            await call.message.answer(f"👤 Заявка от: <code>{app['user_id']}</code>", reply_markup=kb, parse_mode="HTML")
        await call.answer()

    # Хендлер для кнопок из adm_view_apps (app_accept_ / app_decline_)
    @dp.callback_query(F.data.startswith("app_"))
    async def process_app(call: types.CallbackQuery):
        parts = call.data.split("_")
        action, t_id = parts[1], int(parts[2])
        if action == "accept":
            await db.db_execute("INSERT INTO workers (user_id) VALUES ($1) ON CONFLICT DO NOTHING", t_id)
            await db.db_execute("UPDATE worker_applications SET status='accepted' WHERE user_id=$1", t_id)
            set_role(t_id, "worker")
            try: await bot.send_message(t_id, "🎉 Ваша заявка на роль оплатчика одобрена!\n\nЖелаем удачной работы и успешных начинаний!❤️")
            except: pass
            await call.message.edit_text(f"✅ Юзер {t_id} принят")
        else:
            await db.db_execute("UPDATE worker_applications SET status='declined' WHERE user_id=$1", t_id)
            try: await bot.send_message(t_id, "❌ Ваша заявка на роль оплатчика отклонена.\n\nПопробуйте подать заявку позже. Возможно мы пересмотрим решение.")
            except: pass
            await call.message.edit_text(f"❌ Юзер {t_id} отклонен")
        await call.answer()

    # Хендлер для кнопок из apply.py (adm_ap_yes_ / adm_ap_no_)
    @dp.callback_query(F.data.startswith("adm_ap_"))
    async def process_apply_decision(call: types.CallbackQuery):
        parts = call.data.split("_")
        action = parts[2]  # yes / no
        t_id = int(parts[3])
        if action == "yes":
            await db.db_execute("INSERT INTO workers (user_id) VALUES ($1) ON CONFLICT DO NOTHING", t_id)
            await db.db_execute("UPDATE worker_applications SET status='accepted' WHERE user_id=$1", t_id)
            set_role(t_id, "worker")
            try: await bot.send_message(t_id, "🎉 Ваша заявка на роль оплатчика одобрена!\n\nЖелаем удачной работы и успешных начинаний!❤️")
            except: pass
            await call.message.edit_text(f"✅ Юзер <code>{t_id}</code> принят в воркеры.", parse_mode="HTML")
        else:
            await db.db_execute("UPDATE worker_applications SET status='declined' WHERE user_id=$1", t_id)
            try: await bot.send_message(t_id, "❌ Ваша заявка на роль оплатчика отклонена.\n\nПопробуйте подать заявку позже. Возможно мы пересмотрим решение.")
            except: pass
            await call.message.edit_text(f"❌ Юзер <code>{t_id}</code> отклонён.", parse_mode="HTML")
        await call.answer()

    @dp.callback_query(F.data == "adm_add_worker_manual")
    async def add_worker_start(call: types.CallbackQuery, state: FSMContext):
        await state.set_state(AdminStates.waiting_for_worker_id)
        await call.message.edit_text("🔢 Введите ID для назначения воркером:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="adm_back_to_main")]]))
        await call.answer()

    @dp.message(AdminStates.waiting_for_worker_id)
    async def add_worker_finish(message: types.Message, state: FSMContext):
        try:
            t_id = int(message.text.strip())
            await db.db_execute("INSERT INTO workers (user_id) VALUES ($1) ON CONFLICT DO NOTHING", t_id)
            set_role(t_id, "worker")
            await message.answer(f"✅ Юзер {t_id} теперь воркер.")
            await state.clear()
            await send_admin_menu(message)
        except: await message.answer("Ошибка в ID.")

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
        await status_msg.edit_text(f"✅ Рассылка завершена. Получили: {sent}")
        await state.clear()
        await send_admin_menu(message)

    @dp.callback_query(F.data == "adm_close")
    async def close_admin(call: types.CallbackQuery):
        await call.message.delete()
        await call.answer()
