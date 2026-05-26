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
    waiting_for_balance_uid = State()
    waiting_for_balance_amount = State()
    waiting_for_contest_target = State()

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
            [
                InlineKeyboardButton(text="💳 Баланс юзера", callback_data="adm_balance_menu"),
                InlineKeyboardButton(text="👤 Все юзеры", callback_data="adm_list_users")
            ],
            [InlineKeyboardButton(text="🆘 Активные споры", callback_data="adm_disputes")],
            [InlineKeyboardButton(text="📊 Общий оборот конкурса", callback_data="adm_contest")],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="adm_close")]
        ])
        text = f"<tg-emoji emoji-id='5332724926216428039'>🛠</tg-emoji> <b>Панель управления проектом</b>"
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
        await call.message.edit_text(f"<tg-emoji emoji-id='5244837092042750681'>📈</tg-emoji> <b>Выберите период отчета:</b>", reply_markup=kb, parse_mode="HTML")
        await call.answer()

    @dp.callback_query(F.data.startswith("st_"))
    async def process_stats(call: types.CallbackQuery):
        period = call.data.split("_")[1]
        now = datetime.utcnow()
        since = now - (timedelta(days=1) if period == "day" else timedelta(weeks=1) if period == "week" else timedelta(days=30))
        label = "день" if period == "day" else "неделю" if period == "week" else "месяц"
        try:
            since_naive = since
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
                f"<tg-emoji emoji-id='5231200819986047254'>📊</tg-emoji> <b>Статистика за {label}</b>\n\n"
                f"<tg-emoji emoji-id='5332724926216428039'>👥</tg-emoji> <b>Аудитория:</b>\n• Новых юзеров: <b>{new_users['count']}</b>\n• Всего в базе: <b>{total_users['count']}</b>\n\n"
                f"<tg-emoji emoji-id='5197269100878907942'>📋</tg-emoji> <b>Активность:</b>\n• Успешных сделок: <b>{done_count}</b>\n\n"
                f"<tg-emoji emoji-id='5312123810638483121'>💰</tg-emoji> <b>Финансы:</b>\n• Оборот: <code>{turnover_usdt:.4f}</code> USDT (<code>{turnover_rub:.0f}</code> RUB)\n• Прибыль бота: <b>{net_profit:.4f}</b> USDT")
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
                "<tg-emoji emoji-id='5312123810638483121'>💰</tg-emoji> <b>Финансовый аудит</b>\n\n"
                f"<tg-emoji emoji-id='5291914649481007565'>💵</tg-emoji> <b>Прибыль бота:</b> <code>{p_val:.4f}</code> USDT\n"
                f"<tg-emoji emoji-id='5201691993775818138'>💸</tg-emoji> <b>Выплачено:</b> <code>{w_val:.4f}</code> USDT\n"
                "--------------------------\n"
                f"<tg-emoji emoji-id='5312123810638483121'>💰</tg-emoji> <b>Оборот:</b> <code>{t_usdt:.4f}</code> USDT (<code>{t_rub:.0f}</code> RUB)\n"
                f"<tg-emoji emoji-id='5397916757333654639'>➕</tg-emoji> <b>Пополнено:</b> <code>{d_val:.4f}</code> USDT\n"
                f"<tg-emoji emoji-id='5443127283898405358'>📥</tg-emoji> <b>Выведено воркерами:</b> <code>{w_val:.4f}</code> USDT"
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
        text = f"<tg-emoji emoji-id='5332724926216428039'>👥</tg-emoji> <b>Управление воркерами</b>\n\nВ штате: <b>{count['count']}</b>\nЗаявок: <b>{apps['count']}</b>"
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
           f"<tg-emoji emoji-id='5275979556308674886'>👤</tg-emoji> <b>Воркер {name}</b>\n"
           f"ID: <code>{uid}</code>\n\n"
           f"<tg-emoji emoji-id='5206476089127372379'>✅</tg-emoji> Выполнено: {done['count']} заявок\n"
           f"<tg-emoji emoji-id='5312123810638483121'>💰</tg-emoji> Баланс: {balance:.2f} USDT"
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
            await bot.send_message(uid, f"<tg-emoji emoji-id='5278578973595427038'>❌</tg-emoji> Вы были сняты с должности воркера.")
        except:
            pass
        await call.message.edit_text(f"<tg-emoji emoji-id='5206476089127372379'>✅</tg-emoji> Воркер <code>{uid}</code> снят с должности.", parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏪ Назад", callback_data="adm_list_workers")]]))
        await call.answer()

    @dp.callback_query(F.data == "adm_view_apps")
    async def view_apps(call: types.CallbackQuery):
        apps = await db.db_fetchall("SELECT user_id FROM worker_applications WHERE status='pending' LIMIT 5")
        if not apps: return await call.answer(f"<tg-emoji emoji-id='5445355530111437729'>📩</tg-emoji> Заявок нет", show_alert=True)
        await call.message.delete()
        for app in apps:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Принять", callback_data=f"adm_ap_yes_{app['user_id']}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"adm_ap_no_{app['user_id']}")
            ]])
            await call.message.answer(f"<tg-emoji emoji-id='5275979556308674886'>👤</tg-emoji> Заявка от: <code>{app['user_id']}</code>", reply_markup=kb, parse_mode="HTML")
        await call.answer()

    @dp.callback_query(F.data.startswith("adm_ap_"))
    async def process_apply_decision(call: types.CallbackQuery):
        parts = call.data.split("_")
        action = parts[2]
        t_id = int(parts[3])
        if action == "yes":
            await db.db_execute("INSERT INTO workers (user_id) VALUES ($1) ON CONFLICT DO NOTHING", t_id)
            await db.db_execute("UPDATE worker_applications SET status='accepted' WHERE user_id=$1", t_id)
            set_role(t_id, "worker")
            try: await bot.send_message(t_id, f"<tg-emoji emoji-id='5406926593698312391'>🎉</tg-emoji> Ваша заявка на роль оплатчика одобрена!\n\nЖелаем удачной работы и успешных начинаний!<tg-emoji emoji-id='5192879906295397710'>❤️</tg-emoji>")
            except: pass
            await call.message.edit_text(f"<tg-emoji emoji-id='5206476089127372379'>✅</tg-emoji> Юзер <code>{t_id}</code> принят в воркеры.", parse_mode="HTML")
        else:
            await db.db_execute("UPDATE worker_applications SET status='declined' WHERE user_id=$1", t_id)
            try: await bot.send_message(t_id, f"<tg-emoji emoji-id='5278578973595427038'>❌</tg-emoji> Ваша заявка на роль оплатчика отклонена.\n\nПопробуйте подать заявку позже. Возможно мы пересмотрим решение.")
            except: pass
            await call.message.edit_text(f"<tg-emoji emoji-id='5278578973595427038'>❌</tg-emoji> Юзер <code>{t_id}</code> отклонён.", parse_mode="HTML")
        await call.answer()

    @dp.callback_query(F.data == "adm_add_worker_manual")
    async def add_worker_start(call: types.CallbackQuery, state: FSMContext):
        await state.set_state(AdminStates.waiting_for_worker_id)
        await call.message.edit_text(f"<tg-emoji emoji-id='5361741454685256344'>🔢</tg-emoji> Введите ID для назначения воркером:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="adm_back_to_main")]]))
        await call.answer()

    @dp.message(AdminStates.waiting_for_worker_id)
    async def add_worker_finish(message: types.Message, state: FSMContext):
        try:
            t_id = int(message.text.strip())
            await db.db_execute("INSERT INTO workers (user_id) VALUES ($1) ON CONFLICT DO NOTHING", t_id)
            set_role(t_id, "worker")
            await message.answer(f"<tg-emoji emoji-id='5206476089127372379'>✅</tg-emoji> Юзер {t_id} теперь воркер.")
            await state.clear()
            await send_admin_menu(message)
        except: await message.answer("Ошибка в ID.")

    @dp.callback_query(F.data == "adm_broadcast")
    async def broadcast_start(call: types.CallbackQuery, state: FSMContext):
        await state.set_state(AdminStates.waiting_for_broadcast_text)
        await call.message.edit_text(f"<tg-emoji emoji-id='5298609030321691620'>📢</tg-emoji> Введите текст рассылки:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="adm_back_to_main")]]))
        await call.answer()

    @dp.message(AdminStates.waiting_for_broadcast_text)
    async def broadcast_finish(message: types.Message, state: FSMContext):
        query = "SELECT user_id FROM balances UNION SELECT user_id FROM workers UNION SELECT user_id FROM invoices"
        rows = await db.db_fetchall(query)
        u_ids = list(set([r['user_id'] for r in rows]))
        status_msg = await message.answer(f"<tg-emoji emoji-id='5188481279963715781'>🚀</tg-emoji> Рассылка на {len(u_ids)} чел...")
        sent = 0
        for uid in u_ids:
            try:
                await bot.send_message(uid, message.text, parse_mode="HTML")
                sent += 1
                await asyncio.sleep(0.05)
            except: pass
        await status_msg.edit_text(f"<tg-emoji emoji-id='5206476089127372379'>✅</tg-emoji> Рассылка завершена. Получили: {sent}")
        await state.clear()
        await send_admin_menu(message)

    @dp.callback_query(F.data == "adm_balance_menu")
    async def balance_menu(call: types.CallbackQuery, state: FSMContext):
        await state.set_state(AdminStates.waiting_for_balance_uid)
        await call.message.edit_text(
            f"<tg-emoji emoji-id='5445353829304387411'>💳</tg-emoji> <b>Управление балансом</b>\n\nВведите ID пользователя:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="adm_back_to_main")]])
        )
        await call.answer()

    @dp.message(AdminStates.waiting_for_balance_uid)
    async def balance_uid_handler(message: types.Message, state: FSMContext):
        try:
            t_id = int(message.text.strip())
        except:
            return await message.answer(f"<tg-emoji emoji-id='5278578973595427038'>❌</tg-emoji> Введите корректный ID (число).")
        balance = await db.get_balance(t_id)
        await state.update_data(balance_uid=t_id)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Пополнить", callback_data=f"adm_bal_add_{t_id}")],
            [InlineKeyboardButton(text="➖ Списать", callback_data=f"adm_bal_sub_{t_id}")],
            [InlineKeyboardButton(text="🔄 Обнулить", callback_data=f"adm_bal_reset_{t_id}")],
            [InlineKeyboardButton(text="⏪ Назад", callback_data="adm_back_to_main")]
        ])
        await message.answer(
            f"<tg-emoji emoji-id='5275979556308674886'>👤</tg-emoji> ID: <code>{t_id}</code>\n<tg-emoji emoji-id='5312123810638483121'>💰</tg-emoji> Баланс: <b>{balance:.2f} USDT</b>",
            parse_mode="HTML", reply_markup=kb
        )
        await state.clear()

    @dp.callback_query(F.data.startswith("adm_bal_reset_"))
    async def bal_reset(call: types.CallbackQuery):
        t_id = int(call.data.split("_")[3])
        await db.db_execute("UPDATE balances SET balance=0 WHERE user_id=$1", t_id)
        await call.message.edit_text(f"<tg-emoji emoji-id='5206476089127372379'>✅</tg-emoji> Баланс юзера <code>{t_id}</code> обнулён.", parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏪ Назад", callback_data="adm_back_to_main")]]))
        await call.answer()

    @dp.callback_query(F.data.startswith("adm_bal_add_") | F.data.startswith("adm_bal_sub_"))
    async def bal_change_start(call: types.CallbackQuery, state: FSMContext):
        parts = call.data.split("_")
        action = parts[2]
        t_id = int(parts[3])
        await state.set_state(AdminStates.waiting_for_balance_amount)
        await state.update_data(bal_action=action, bal_uid=t_id)
        word = "пополнения" if action == "add" else "списания"
        await call.message.edit_text(
            f"<tg-emoji emoji-id='5445353829304387411'>💳</tg-emoji> Введите сумму {word} в USDT:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="adm_back_to_main")]])
        )
        await call.answer()

    @dp.message(AdminStates.waiting_for_balance_amount)
    async def bal_change_finish(message: types.Message, state: FSMContext):
        try:
            amount = float(message.text.strip())
            if amount <= 0: raise ValueError
        except:
            return await message.answer(f"<tg-emoji emoji-id='5278578973595427038'>❌</tg-emoji> Введите корректную сумму.")
        data = await state.get_data()
        action = data.get("bal_action")
        t_id = data.get("bal_uid")
        if action == "add":
            await db.db_execute("UPDATE balances SET balance=balance+$1 WHERE user_id=$2", amount, t_id)
            await message.answer(f"<tg-emoji emoji-id='5206476089127372379'>✅</tg-emoji> Баланс юзера <code>{t_id}</code> пополнен на <b>{amount:.2f} USDT</b>.", parse_mode="HTML")
        else:
            await db.db_execute("UPDATE balances SET balance=GREATEST(balance-$1, 0) WHERE user_id=$2", amount, t_id)
            await message.answer(f"<tg-emoji emoji-id='5206476089127372379'>✅</tg-emoji> С баланса юзера <code>{t_id}</code> списано <b>{amount:.2f} USDT</b>.", parse_mode="HTML")
        await state.clear()
        await send_admin_menu(message)

    @dp.callback_query(F.data == "adm_list_users")
    async def list_users(call: types.CallbackQuery):
        users = await db.db_fetchall("SELECT user_id, balance FROM balances ORDER BY user_id DESC LIMIT 30")
        if not users:
            return await call.answer(f"<tg-emoji emoji-id='5275979556308674886'>👤</tg-emoji> Юзеров нет", show_alert=True)
        buttons = []
        for u in users:
            uid = u['user_id']
            bal = float(u['balance'] or 0)
            try:
                chat = await bot.get_chat(uid)
                name = f"@{chat.username}" if chat.username else f"ID: {uid}"
            except:
                name = f"ID: {uid}"
            buttons.append([InlineKeyboardButton(text=f"👤 {name} • {bal:.2f} USDT", callback_data=f"adm_user_info_{uid}")])
        buttons.append([InlineKeyboardButton(text="⏪ Назад", callback_data="adm_back_to_main")])
        await call.message.edit_text(f"<tg-emoji emoji-id='5275979556308674886'>👤</tg-emoji> <b>Все юзеры:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        await call.answer()

    @dp.callback_query(F.data.startswith("adm_user_info_"))
    async def user_info(call: types.CallbackQuery):
        uid = int(call.data.split("_")[3])
        try:
            chat = await bot.get_chat(uid)
            name = f"@{chat.username}" if chat.username else f"ID: {uid}"
        except:
            name = f"ID: {uid}"
        balance = await db.get_balance(uid)
        frozen = await db.get_frozen(uid)
        done = await db.db_fetchone("SELECT COUNT(*) FROM orders WHERE user_id=$1 AND status='DONE'", uid)
        cancelled = await db.db_fetchone("SELECT COUNT(*) FROM orders WHERE user_id=$1 AND status='CANCELLED'", uid)
        active = await db.db_fetchone("SELECT COUNT(*) FROM orders WHERE user_id=$1 AND status IN ('NEW', 'IN_PROGRESS')", uid)
        text = (
            f"<tg-emoji emoji-id='5275979556308674886'>👤</tg-emoji> <b>{name}</b>\n"
            f"ID: <code>{uid}</code>\n\n"
            f"<tg-emoji emoji-id='5312123810638483121'>💰</tg-emoji> Баланс: <b>{balance:.2f} USDT</b>\n"
            f"<tg-emoji emoji-id='5296369303661067030'>🔒</tg-emoji> Заморожено: <b>{frozen:.2f} USDT</b>\n\n"
            f"<tg-emoji emoji-id='5231200819986047254'>📊</tg-emoji> <b>Статистика заявок:</b>\n"
            f"• Завершённых: {done['count']}\n"
            f"• Отменённых: {cancelled['count']}\n"
            f"• Активных: {active['count']}"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Пополнить", callback_data=f"adm_bal_add_{uid}")],
            [InlineKeyboardButton(text="➖ Списать", callback_data=f"adm_bal_sub_{uid}")],
            [InlineKeyboardButton(text="🔄 Обнулить", callback_data=f"adm_bal_reset_{uid}")],
            [InlineKeyboardButton(text="⏪ Назад", callback_data="adm_list_users")]
        ])
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        await call.answer()

    @dp.callback_query(F.data.startswith("dispute_refund_"))
    async def dispute_refund(call: types.CallbackQuery):
        order_id = int(call.data.split("_")[2])
        row = await db.db_fetchone("SELECT user_id, total_usdt FROM orders WHERE id=$1 AND status='DISPUTE'", order_id)
        if not row:
            return await call.answer("❌ Заявка не найдена или уже решена", show_alert=True)
        await db.db_execute("UPDATE orders SET status='CANCELLED' WHERE id=$1", order_id)
        await db.unfreeze_back(row['user_id'], float(row['total_usdt'] or 0))
        try:
            await bot.send_message(row['user_id'], f"<tg-emoji emoji-id='5206476089127372379'>✅</tg-emoji> Спор по заявке #{order_id} решён в вашу пользу. Средства возвращены на баланс.")
        except: pass
        try:
            await call.message.delete()
        except: pass
        await call.message.answer(f"<tg-emoji emoji-id='5206476089127372379'>✅</tg-emoji> Спор #{order_id} — средства возвращены клиенту.")
        await call.answer("✅ Готово!", show_alert=True)

    @dp.callback_query(F.data.startswith("dispute_pay_worker_"))
    async def dispute_pay_worker(call: types.CallbackQuery):
        order_id = int(call.data.split("_")[3])
        row = await db.db_fetchone("SELECT user_id, worker_id, total_usdt, amount_usdt FROM orders WHERE id=$1 AND status='DISPUTE'", order_id)
        if not row:
            return await call.answer("❌ Заявка не найдена или уже решена", show_alert=True)
        await db.db_execute("UPDATE orders SET status='DONE' WHERE id=$1", order_id)
        await db.unfreeze_to_worker(row['user_id'], row['worker_id'], float(row['total_usdt'] or 0), float(row['amount_usdt'] or 0))
        try:
            await bot.send_message(row['worker_id'], f"<tg-emoji emoji-id='5206476089127372379'>✅</tg-emoji> Спор по заявке #{order_id} решён в вашу пользу. Средства зачислены.")
        except: pass
        try:
            await bot.send_message(row['user_id'], f"<tg-emoji emoji-id='5278578973595427038'>❌</tg-emoji> Спор по заявке #{order_id} решён не в вашу пользу.")
        except: pass
        try:
            await call.message.delete()
        except: pass
        await call.message.answer(f"<tg-emoji emoji-id='5206476089127372379'>✅</tg-emoji> Спор #{order_id} — средства отправлены воркеру.")
        await call.answer("✅ Готово!", show_alert=True)

    @dp.callback_query(F.data == "adm_disputes")
    async def active_disputes(call: types.CallbackQuery):
        disputes = await db.db_fetchall(
            "SELECT id, user_id, worker_id, amount FROM orders WHERE status='DISPUTE' ORDER BY id DESC LIMIT 20"
        )
        if not disputes:
            return await call.answer("✅ Активных споров нет", show_alert=True)
        buttons = []
        for d in disputes:
            buttons.append([InlineKeyboardButton(
                text=f"🆘 #{d['id']} — {float(d['amount']):.0f} RUB | К: {d['user_id']} В: {d['worker_id']}",
                callback_data=f"adm_dispute_info_{d['id']}"
            )])
        buttons.append([InlineKeyboardButton(text="⏪ Назад", callback_data="adm_back_to_main")])
        await call.message.edit_text(
            f"<tg-emoji emoji-id='5420323339723881652'>🆘</tg-emoji> <b>Активные споры</b>\n\nВсего: {len(disputes)}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
        await call.answer()

    @dp.callback_query(F.data.startswith("adm_dispute_info_"))
    async def dispute_info(call: types.CallbackQuery):
        order_id = int(call.data.split("_")[3])
        row = await db.db_fetchone(
            "SELECT id, user_id, worker_id, amount, total_usdt FROM orders WHERE id=$1 AND status='DISPUTE'", order_id
        )
        if not row:
            return await call.answer("❌ Спор не найден или уже решён", show_alert=True)
        text = (
            f"<tg-emoji emoji-id='5420323339723881652'>🆘</tg-emoji> <b>Спор по заявке #{order_id}</b>\n\n"
            f"<tg-emoji emoji-id='5275979556308674886'>👤</tg-emoji> Клиент: <code>{row['user_id']}</code>\n"
            f"<tg-emoji emoji-id='5440660757194744323'>👷</tg-emoji> Воркер: <code>{row['worker_id']}</code>\n"
            f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> Сумма: {float(row['amount']):.2f} RUB\n"
            f"<tg-emoji emoji-id='5276229330131772747'>💎</tg-emoji> Заморожено: {float(row['total_usdt'] or 0):.4f} USDT"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Вернуть клиенту", callback_data=f"dispute_refund_{order_id}")],
            [InlineKeyboardButton(text="💸 Отправить воркеру", callback_data=f"dispute_pay_worker_{order_id}")],
            [InlineKeyboardButton(text="⏪ Назад", callback_data="adm_disputes")]
        ])
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        await call.answer()

    @dp.callback_query(F.data == "adm_contest")
    async def contest_menu(call: types.CallbackQuery):
        row = await db.db_fetchone("SELECT * FROM contest WHERE status='active' ORDER BY id DESC LIMIT 1")
        if row:
            turnover = await db.db_fetchone("""
                SELECT SUM(o.amount) as total
                FROM orders o
                JOIN referrals r ON o.user_id = r.referred_id
                WHERE o.status IN ('DONE','SUCCESS','COMPLETED')
                  AND o.created_at >= $1
                  AND r.referred_id IN (
                      SELECT o2.user_id
                      FROM orders o2
                      WHERE o2.status IN ('DONE','SUCCESS','COMPLETED')
                        AND o2.created_at >= $1
                      GROUP BY o2.user_id
                      HAVING SUM(o2.total_usdt) >= 10
                  )
            """, row['started_at'], row['started_at'])
            current = float(turnover['total'] or 0)
            target = float(row['target_rub'])
            progress = min(current / target * 100, 100) if target > 0 else 0
            bar_filled = int(progress / 10)
            bar = "🟩" * bar_filled + "⬜" * (10 - bar_filled)

            top = await db.db_fetchall("""
                SELECT r.referrer_id, SUM(o.amount) as contrib
                FROM orders o
                JOIN referrals r ON o.user_id = r.referred_id
                WHERE o.status IN ('DONE','SUCCESS','COMPLETED')
                  AND o.created_at >= $1
                  AND r.referred_id IN (
                      SELECT o2.user_id
                      FROM orders o2
                      WHERE o2.status IN ('DONE','SUCCESS','COMPLETED')
                        AND o2.created_at >= $1
                      GROUP BY o2.user_id
                      HAVING SUM(o2.total_usdt) >= 10
                  )
                GROUP BY r.referrer_id
                ORDER BY contrib DESC
                LIMIT 3
            """, row['started_at'], row['started_at'])

            medals = [
                "<tg-emoji emoji-id='5440539497383087970'>⭐</tg-emoji>",
                "<tg-emoji emoji-id='5447203607294265305'>⭐</tg-emoji>",
                "<tg-emoji emoji-id='5453902265922376865'>⭐</tg-emoji>"
            ]
            prizes = [100, 60, 40]
            top_text = ""
            for i, t in enumerate(top):
                uid_top = t['referrer_id']
                contrib = float(t['contrib'] or 0)
                try:
                    chat = await bot.get_chat(uid_top)
                    name = f"@{chat.username}" if chat.username else f"ID: {uid_top}"
                except:
                    name = f"ID: {uid_top}"
                top_text += f"{medals[i]} {name} — {contrib:,.0f} RUB (+{prizes[i]} USDT)\n"

            if not top_text:
                top_text = "Пока нет участников\n"

            text = (
                f"<tg-emoji emoji-id='5231200819986047254'>📊</tg-emoji> <b>Конкурс активен</b>\n\n"
                f"<tg-emoji emoji-id='5440660757194744323'>🗓</tg-emoji> Старт: <b>{row['started_at'].strftime('%d.%m.%Y %H:%M')}</b>\n"
                f"<tg-emoji emoji-id='5397782960512444700'>🎯</tg-emoji> Цель: <b>{target:,.0f} RUB</b>\n\n"
                f"<tg-emoji emoji-id='5231005931550030290'>💰</tg-emoji> Текущий оборот: <b>{current:,.0f} RUB</b>\n"
                f"<tg-emoji emoji-id='5244837092042750681'>📈</tg-emoji> Прогресс: <b>{progress:.1f}%</b>\n"
                f"{bar}\n\n"
                f"<tg-emoji emoji-id='5244590801438138696'>🏆</tg-emoji> <b>Топ участников:</b>\n{top_text}"
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Обновить", callback_data="adm_contest")],
                [InlineKeyboardButton(text="🛑 Остановить конкурс", callback_data="adm_contest_stop")],
                [InlineKeyboardButton(text="⏪ Назад", callback_data="adm_back_to_main")]
            ])
        else:
            text = "<tg-emoji emoji-id='5231200819986047254'>📊</tg-emoji> <b>Конкурс</b>\n\nАктивных конкурсов нет."
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🚀 Запустить конкурс", callback_data="adm_contest_start")],
                [InlineKeyboardButton(text="⏪ Назад", callback_data="adm_back_to_main")]
            ])
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await call.answer()

    @dp.callback_query(F.data == "adm_contest_stop")
    async def contest_stop(call: types.CallbackQuery):
        await db.db_execute("UPDATE contest SET status='finished' WHERE status='active'")
        await call.message.edit_text(
            "🛑 <b>Конкурс остановлен.</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏪ Назад", callback_data="adm_contest")]
            ])
        )
        await call.answer()

    @dp.callback_query(F.data == "adm_contest_start")
    async def contest_start_prompt(call: types.CallbackQuery, state: FSMContext):
        await state.set_state(AdminStates.waiting_for_contest_target)
        await call.message.edit_text(
            "<tg-emoji emoji-id='5397782960512444700'>🎯</tg-emoji> Введите целевой оборот конкурса в RUB (число):",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Отмена", callback_data="adm_contest")]
            ])
        )
        await call.answer()

    @dp.message(AdminStates.waiting_for_contest_target)
    async def contest_start_finish(message: types.Message, state: FSMContext):
        try:
            target = float(message.text.strip().replace(",", "").replace(" ", ""))
            if target <= 0: raise ValueError
        except:
            return await message.answer("<tg-emoji emoji-id='5210952531676504517'>❌</tg-emoji> Введите корректную сумму (например: 1000000)")
        await db.db_execute(
            "INSERT INTO contest (target_rub, status) VALUES ($1, 'active')", target
        )
        await state.clear()
        await message.answer(
            f"<tg-emoji emoji-id='5206607081334906820'>✅</tg-emoji> Конкурс запущен! Цель: <b>{target:,.0f} RUB</b>",
            parse_mode="HTML"
        )
        await send_admin_menu(message)

    @dp.callback_query(F.data == "adm_close")
    async def close_admin(call: types.CallbackQuery):
        await call.message.delete()
        await call.answer()
