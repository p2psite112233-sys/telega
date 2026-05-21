import asyncio
import logging
from aiogram import types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

import db
from config import PROFILE_BANNER_FILE_ID, BANNER_FILE_ID
from utils.shared import get_role, workers
from handlers.dispute import update_client_dispute_msg

logger = logging.getLogger(__name__)

class WorkerStates(StatesGroup):
    waiting_for_code = State()

def order_info(order_id: int, amount: float, total_usdt: float, unique: bool = False) -> str:
    commission = max(round(amount * (0.25 if unique else 0.20), 2), 30)
    total_rub = round(amount + commission, 2)
    amount_usdt = round(total_usdt * amount / total_rub, 4) if total_rub else 0
    commission_usdt = round(total_usdt - amount_usdt, 4)
    worker_net_usdt = round(commission_usdt * 0.8, 4)
    worker_total_usdt = round(amount_usdt + worker_net_usdt, 4)
    unique_text = "✅ Уникальная" if unique else "❌ Обычная"
    return (
        f"⚡️ <b>#{order_id} · Карта под оплату</b>\n\n"
        f"💰 {amount:.2f} RUB · {unique_text}\n\n"
        f"💵 Ваш заработок: +{commission * 0.8:.2f} RUB (+{worker_net_usdt:.4f} USDT)\n"
        f"📊 К зачислению: <b>{worker_total_usdt:.4f} USDT</b>"
    )

def order_info_transfer(order_id: int, amount: float, total_usdt: float, transfer_type: str,
                        phone_or_card: str, bank: str = "", name: str = "") -> str:
    commission = max(round(amount * 0.20, 2), 30)
    total_rub = round(amount + commission, 2)
    amount_usdt = round(total_usdt * amount / total_rub, 4) if total_rub else 0
    commission_usdt = round(total_usdt - amount_usdt, 4)
    worker_net_usdt = round(commission_usdt * 0.8, 4)
    worker_total_usdt = round(amount_usdt + worker_net_usdt, 4)

    if transfer_type == "sbp":
        type_label = "Перевод по СБП"
        req = f"▸ 📱 <code>{phone_or_card}</code>"
        extra = f"▸ 🏦 {bank}\n▸ 👤 {name}\n"
    elif transfer_type == "card":
        type_label = "Перевод по номеру карты"
        req = f"▸ 💳 <code>{phone_or_card}</code>"
        extra = f"▸ 🏦 {bank}\n▸ 👤 {name}\n"
    else:  # phone
        type_label = "Пополнение номера"
        req = f"▸ 📱 <code>{phone_or_card}</code>"
        extra = ""

    return (
        f"⚡️ <b>#{order_id} · {type_label}</b>\n\n"
        f"💰 {amount:.2f} RUB\n\n"
        f"📋 Реквизиты:\n"
        f"{req}\n"
        f"{extra}\n"
        f"💵 Ваш заработок: +{commission * 0.8:.2f} RUB (+{worker_net_usdt:.4f} USDT)\n"
        f"📊 К зачислению: <b>{worker_total_usdt:.4f} USDT</b>"
    )

def register_worker(dp, bot):

    @dp.message(F.text == "/lk")
    async def lk(message: types.Message):
        uid = message.from_user.id
        role = get_role(uid)
        username = f"@{message.from_user.username}" if message.from_user.username else f"ID: {uid}"
        balance = await db.get_balance(uid)

        if role not in ["worker", "admin"]:
            frozen = await db.get_frozen(uid)
            c_done = await db.db_fetchone("SELECT COUNT(*) FROM orders WHERE user_id=$1 AND status='DONE'", uid)
            c_active = await db.db_fetchone("SELECT COUNT(*) FROM orders WHERE user_id=$1 AND status='IN_PROGRESS'", uid)
            paid_count = await db.db_fetchone("SELECT COUNT(*) FROM invoices WHERE user_id=$1 AND status='paid'", uid)
            text = (
                f"<b>👤 Личный профиль</b>\n"
                f"<blockquote>{username}</blockquote>\n\n"
                f"<b>💼 Финансы</b>\n"
                f"• Баланс: <b>{balance:.2f} USDT</b>\n"
                f"• Заморожено: <b>{frozen:.2f} USDT</b>\n\n"
                f"<b>📊 Статистика</b>\n"
                f"• Закрыто: {c_done['count']} шт\n"
                f"• Активно: {c_active['count']} шт\n"
                f"• Пополнений: {paid_count['count']} шт"
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔗 Реферал", callback_data="client_ref"),
                 InlineKeyboardButton(text="📚 История", callback_data="client_history")],
                [InlineKeyboardButton(text="🏠 Меню", callback_data="client_back_menu")]
            ])
            return await message.answer_photo(photo=PROFILE_BANNER_FILE_ID, caption=text, reply_markup=kb, parse_mode="HTML")

        w_done = await db.db_fetchone("SELECT COUNT(*) FROM orders WHERE worker_id=$1 AND status='DONE'", uid)
        w_active = await db.db_fetchone("SELECT COUNT(*) FROM orders WHERE worker_id=$1 AND status='IN_PROGRESS'", uid)
        text = (
            f"🛠 <b>Профиль работника</b>\n"
            f"Аккаунт: {username}\n\n"
            f"💼 <b>Финансы</b>\n"
            f"• Доступно: <b>{balance:.2f} USDT</b>\n\n"
            f"📊 <b>Статистика</b>\n"
            f"• Выполнено: {w_done['count']} шт\n"
            f"• В работе: {w_active['count']} шт"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💸 Вывод", callback_data="lk_withdraw")],
            [InlineKeyboardButton(text="🟢 Активные", callback_data="lk_available"),
             InlineKeyboardButton(text="📚 История", callback_data="lk_history")],
            [InlineKeyboardButton(text="💳 Карты", callback_data="lk_cards")]
        ])
        await message.answer_photo(photo=PROFILE_BANNER_FILE_ID, caption=text, reply_markup=kb, parse_mode="HTML")

    @dp.callback_query(F.data == "lk_available")
    async def lk_active(call: types.CallbackQuery):
        orders = await db.db_fetchall(
            "SELECT id, amount, status, transfer_type FROM orders WHERE status='NEW' ORDER BY id DESC LIMIT 20"
        )
        try:
            await call.message.delete()
        except:
            pass

        if not orders:
            await call.message.answer(
                "📭 <b>Активных заявок пока нет</b>\n\nОжидайте новых!",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")]
                ])
            )
            return await call.answer()

        buttons = []
        for order in orders:
            t = order["transfer_type"]
            if t == "sbp":
                label = "📲 СБП"
            elif t == "card":
                label = "💳 Перевод по карте"
            elif t == "phone":
                label = "📱 Пополнение номера"
            else:
                label = "💳 Карта под оплату"
            buttons.append([InlineKeyboardButton(
                text=f"{label} #{order['id']} — {float(order['amount']):.0f} RUB",
                callback_data=f"take_{order['id']}"
            )])
        buttons.append([InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")])

        await call.message.answer_photo(
            photo=BANNER_FILE_ID,
            caption=(
                "<b>📥 Доступные заявки</b>\n\n"
                "<blockquote>Здесь отображаются все активные заявки от клиентов, которые ещё не взяты в работу.\n"
                "Нажмите на заявку, чтобы просмотреть детали и взять её.</blockquote>"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
        await call.answer()

    @dp.callback_query(F.data == "lk_home")
    async def lk_home(call: types.CallbackQuery):
        uid = call.from_user.id
        username = f"@{call.from_user.username}" if call.from_user.username else f"ID: {uid}"
        balance = await db.get_balance(uid)
        w_done = await db.db_fetchone("SELECT COUNT(*) FROM orders WHERE worker_id=$1 AND status='DONE'", uid)
        w_active = await db.db_fetchone("SELECT COUNT(*) FROM orders WHERE worker_id=$1 AND status='IN_PROGRESS'", uid)
        text = (
            f"🛠 <b>Профиль работника</b>\n"
            f"Аккаунт: {username}\n\n"
            f"💼 <b>Финансы</b>\n"
            f"• Доступно: <b>{balance:.2f} USDT</b>\n\n"
            f"📊 <b>Статистика</b>\n"
            f"• Выполнено: {w_done['count']} шт\n"
            f"• В работе: {w_active['count']} шт"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💸 Вывод", callback_data="lk_withdraw")],
            [InlineKeyboardButton(text="📥 Заявки", callback_data="lk_available"),
             InlineKeyboardButton(text="📚 История", callback_data="lk_history")],
            [InlineKeyboardButton(text="💳 Карты", callback_data="lk_cards")]
        ])
        try:
            await call.message.delete()
        except:
            pass
        await call.message.answer_photo(photo=PROFILE_BANNER_FILE_ID, caption=text, reply_markup=kb, parse_mode="HTML")
        await call.answer()

    @dp.callback_query(F.data.startswith("take_"))
    async def take(call: types.CallbackQuery):
        uid = call.from_user.id
        if get_role(uid) not in ["worker", "admin"]:
            return await call.answer("Нет доступа", show_alert=True)

        order_id = int(call.data.split("_")[1])
        res = await db.db_execute(
            "UPDATE orders SET status='IN_PROGRESS', worker_id=$1 WHERE id=$2 AND status='NEW'",
            uid, order_id
        )
        if "UPDATE 0" in res:
            return await call.answer("❌ Заявку уже забрали!", show_alert=True)

        broadcasts = await db.db_fetchall(
            "SELECT worker_id, message_id FROM order_broadcasts WHERE order_id=$1", order_id
        )
        for b in broadcasts:
            if b["worker_id"] == uid:
                continue
            try:
                await bot.edit_message_text(
                    chat_id=b["worker_id"],
                    message_id=b["message_id"],
                    text=f"⚙️ Заявка #{order_id} уже принята другим исполнителем."
                )
                await asyncio.sleep(0.05)
            except:
                pass
        await db.db_execute("DELETE FROM order_broadcasts WHERE order_id=$1", order_id)

        order = await db.db_fetchone(
            "SELECT user_id, amount, client_message_id, total_usdt, is_unique, transfer_type, transfer_phone, transfer_bank, transfer_recipient_name FROM orders WHERE id=$1",
            order_id
        )
        amount = float(order["amount"])
        total_usdt = float(order["total_usdt"]) if order["total_usdt"] else 0.0
        is_unique = order["is_unique"] or False
        transfer_type = order["transfer_type"]

        if transfer_type in ("sbp", "card", "phone"):
            phone_or_card = order["transfer_phone"] or ""
            bank = order["transfer_bank"] or ""
            name = order["transfer_recipient_name"] or ""

            if transfer_type == "sbp":
                type_label = "Перевод по СБП"
                req_label = f"▸ 📱 <code>{phone_or_card}</code>"
                req_extra = f"▸ 🏦 {bank}\n▸ 👤 {name}\n\n"
            elif transfer_type == "card":
                type_label = "Перевод по номеру карты"
                req_label = f"▸ 💳 <code>{phone_or_card}</code>"
                req_extra = f"▸ 🏦 {bank}\n▸ 👤 {name}\n\n"
            else:
                type_label = "Пополнение номера"
                req_label = f"▸ 📱 <code>{phone_or_card}</code>"
                req_extra = "\n"

            new_msg = await bot.send_message(
                chat_id=order["user_id"],
                text=(
                    f"⚡️ <b>#{order_id} · {type_label}</b>\n\n"
                    f"💰 {amount:.2f} RUB\n\n"
                    f"📋 Реквизиты:\n"
                    f"{req_label}\n"
                    f"{req_extra}"
                    f"🟢 В работе · 👨‍💻 Исполнитель принял заявку\n\n"
                    f"⏳ Ожидайте"
                ),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Выполнено", callback_data=f"client_paid_{order_id}")],
                    [InlineKeyboardButton(text="🆘 Спор", callback_data=f"dispute_{order_id}")],
                    [InlineKeyboardButton(text="📄 Написать сообщение", callback_data=f"chat_write_{order_id}")],
                    [InlineKeyboardButton(text="🏠 Домой", callback_data="client_back_menu")]
                ])
            )
            await db.db_execute("UPDATE orders SET client_message_id=$1 WHERE id=$2", new_msg.message_id, order_id)
            try:
                await bot.delete_message(order["user_id"], order["client_message_id"])
            except:
                pass

            try:
                await call.message.delete()
            except:
                pass

            worker_msg = await call.message.answer(
                order_info_transfer(order_id, amount, total_usdt, transfer_type, phone_or_card, bank, name),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Выполнено", callback_data=f"sbp_done_{order_id}")],
                    [InlineKeyboardButton(text="🆘 Спор", callback_data=f"worker_dispute_{order_id}")],
                    [InlineKeyboardButton(text="📄 Написать сообщение", callback_data=f"chat_write_{order_id}")],
                    [InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")]
                ])
            )
            await db.db_execute("UPDATE orders SET worker_message_id=$1 WHERE id=$2", worker_msg.message_id, order_id)

        else:
            new_msg = await bot.send_message(
                chat_id=order["user_id"],
                text=(
                    f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> <b>#{order_id} · Карта под оплату</b>\n\n"
                    f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> {amount:.2f} RUB\n\n"
                    f"<tg-emoji emoji-id='5278753302023004775'>📋</tg-emoji> Статус заявки:\n"
                    f"▸ <tg-emoji emoji-id='5278611606756942667'>🟢</tg-emoji> В работе\n"
                    f"▸ <tg-emoji emoji-id='5275979556308674886'>👨‍💻</tg-emoji> Исполнитель назначен\n"
                    f"▸ <tg-emoji emoji-id='5276412364458059956'>⏳</tg-emoji> Реквизиты готовятся\n\n"
                    f"<tg-emoji emoji-id='5276395476646653290'>💬</tg-emoji> Скоро исполнитель отправит реквизиты для оплаты"
                    
                ),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="❌ Отменить заявку", callback_data=f"cancel_order_{order_id}")],
                    [InlineKeyboardButton(text="📄 Написать сообщение", callback_data=f"chat_write_{order_id}")],
                    [InlineKeyboardButton(text="🏠 Домой", callback_data="client_back_menu")]
                ])
            )
            await db.db_execute("UPDATE orders SET client_message_id=$1 WHERE id=$2", new_msg.message_id, order_id)
            try:
                await bot.delete_message(order["user_id"], order["client_message_id"])
            except Exception as e:
                logger.error(f"[take] delete old msg error: {e}")

            try:
                await call.message.delete()
            except:
                pass

            await call.message.answer(
                order_info(order_id, amount, total_usdt, unique=is_unique),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💳 Отправить реквизиты", callback_data=f"send_req_{order_id}")],
                    [InlineKeyboardButton(text="🆘 Спор", callback_data=f"worker_dispute_{order_id}")],
                    [InlineKeyboardButton(text="📄 Написать сообщение", callback_data=f"chat_write_{order_id}")],
                    [InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")]
                ])
            )

        await call.answer()

    @dp.callback_query(F.data.startswith("sbp_done_"))
    async def sbp_done(call: types.CallbackQuery):
        order_id = int(call.data.split("_")[2])
        uid = call.from_user.id

        row = await db.db_fetchone(
            "SELECT user_id, amount, total_usdt, amount_usdt, client_message_id, worker_message_id, status, transfer_type FROM orders WHERE id=$1 AND worker_id=$2",
            order_id, uid
        )
        if not row:
            return await call.answer("❌ Заявка не найдена", show_alert=True)
        if row["status"] == "DONE":
            return await call.answer("✅ Заявка уже завершена", show_alert=True)

        amount = float(row["amount"])
        transfer_type = row["transfer_type"]
        if transfer_type == "card":
            type_label = "Перевод по номеру карты"
        elif transfer_type == "phone":
            type_label = "Пополнение номера"
        else:
            type_label = "Перевод по СБП"

        try:
            await bot.edit_message_text(
                chat_id=row["user_id"],
                message_id=row["client_message_id"],
                text=(
                    f"⚡️ <b>#{order_id} · {type_label}</b>\n\n"
                    f"💰 {amount:.2f} RUB\n\n"
                    f"✅ Исполнитель сообщает что выполнил.\n"
                    f"Подтвердите получение или откройте спор."
                ),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Выполнено", callback_data=f"client_paid_{order_id}")],
                    [InlineKeyboardButton(text="🆘 Спор", callback_data=f"dispute_{order_id}")],
                    [InlineKeyboardButton(text="📄 Написать сообщение", callback_data=f"chat_write_{order_id}")],
                    [InlineKeyboardButton(text="🏠 Домой", callback_data="client_back_menu")]
                ])
            )
        except Exception as e:
            logger.error(f"[sbp_done] edit client msg error: {e}")

        try:
            await call.message.delete()
        except:
            pass

        total_usdt = float(row["total_usdt"]) if row["total_usdt"] else 0.0
        commission = max(round(amount * 0.20, 2), 30)
        total_rub = round(amount + commission, 2)
        amount_usdt = round(total_usdt * amount / total_rub, 4) if total_rub else 0
        commission_usdt = round(total_usdt - amount_usdt, 4)
        worker_net_usdt = round(commission_usdt * 0.8, 4)
        worker_total_usdt = round(amount_usdt + worker_net_usdt, 4)

        worker_msg = await bot.send_message(
            chat_id=uid,
            text=(
                f"⚡️ <b>#{order_id} · {type_label}</b>\n\n"
                f"💰 {amount:.2f} RUB\n\n"
                f"⏳ Ожидаем подтверждения от клиента\n\n"
                f"📊 К зачислению: <b>{worker_total_usdt:.4f} USDT</b>"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🆘 Спор", callback_data=f"worker_dispute_{order_id}")],
                [InlineKeyboardButton(text="📄 Написать сообщение", callback_data=f"chat_write_{order_id}")],
                [InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")]
            ])
        )
        await db.db_execute("UPDATE orders SET worker_message_id=$1 WHERE id=$2", worker_msg.message_id, order_id)
        await call.answer("✅ Клиент уведомлён", show_alert=True)

    @dp.callback_query(F.data.startswith("send_req_"))
    async def send_req(call: types.CallbackQuery):
        order_id = int(call.data.split("_")[2])
        uid = call.from_user.id

        order = await db.db_fetchone("SELECT id FROM orders WHERE id=$1 AND worker_id=$2", order_id, uid)
        if not order:
            return await call.answer("❌ Нет доступа к этой заявке", show_alert=True)

        cards = await db.db_fetchall("SELECT id, card_number, expiry, bank FROM cards WHERE worker_id=$1", uid)
        if not cards:
            return await call.answer("❌ У вас нет карт. Добавьте карту в /lk", show_alert=True)

        card_buttons = []
        for card in cards:
            masked = f"{card['card_number'][:6]}{'*'*6}{card['card_number'][-4:]} · {card['bank']}"
            card_buttons.append([
                InlineKeyboardButton(text=f"💳 {masked}", callback_data=f"req_card_{order_id}_{card['id']}")
            ])

        keyboard = InlineKeyboardMarkup(inline_keyboard=card_buttons)
        try:
            await call.message.delete()
        except:
            pass
        await call.message.answer(f"💳 Выберите карту для заявки #{order_id}:", reply_markup=keyboard)
        await call.answer()

    @dp.callback_query(F.data.startswith("req_card_"))
    async def req_card(call: types.CallbackQuery):
        parts = call.data.split("_")
        order_id = int(parts[2])
        card_id = int(parts[3])
        uid = call.from_user.id

        card = await db.db_fetchone(
            "SELECT card_number, expiry, cvv, bank FROM cards WHERE id=$1 AND worker_id=$2",
            card_id, uid
        )
        order = await db.db_fetchone(
            "SELECT user_id, amount, client_message_id, total_usdt, status, is_unique FROM orders WHERE id=$1 AND worker_id=$2",
            order_id, uid
        )
        if not card or not order:
            return await call.answer("❌ Ошибка данных", show_alert=True)

        user_id = order["user_id"]
        amount = float(order["amount"])
        total_usdt = float(order["total_usdt"]) if order.get("total_usdt") else 0.0
        status = order["status"]
        is_unique = order["is_unique"] or False

        card_data = (
            f"🏦 Банк: {card['bank']}\n"
            f"💳 Номер карты: <code>{card['card_number']}</code>\n"
            f"📅 Срок: {card['expiry']}\n"
            f"🔐 CVV: <code>{card['cvv']}</code>"
        )
        await db.db_execute("UPDATE orders SET dispute_card_data=$1 WHERE id=$2", card_data, order_id)

        if status == "DISPUTE":
            d_row = await db.db_fetchone("SELECT dispute_reason FROM orders WHERE id=$1", order_id)
            d_reason = d_row["dispute_reason"] if d_row and d_row["dispute_reason"] else "—"
            await update_client_dispute_msg(bot, order_id, user_id, amount, d_reason, card_data=card_data)
        else:
            new_msg = await bot.send_message(
                chat_id=user_id,
                text=(
                    f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> <b>#{order_id} · Карта под оплату</b>\n\n"
                    f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> {amount:.2f} RUB\n\n"
                    f"<tg-emoji emoji-id='5444856076954520455'>📋</tg-emoji> Реквизиты для оплаты:\n"
                    f"▸ <tg-emoji emoji-id='5332455502917949981'>🏦</tg-emoji> {card['bank']}\n"
                    f"▸ <tg-emoji emoji-id='5445353829304387411'>💳</tg-emoji> <code>{card['card_number']}</code>\n"
                    f"▸ <tg-emoji emoji-id='5274055917766202507'>📅</tg-emoji> {card['expiry']}\n"
                    f"▸ <tg-emoji emoji-id='5443127283898405358'>🔐</tg-emoji> <code>{card['cvv']}</code>\n\n"
                    f"<tg-emoji emoji-id='5276412364458059956'>⏳</tg-emoji> Запросите код для успешной оплаты"
                ),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔑 Запросить код", callback_data=f"request_code_{order_id}")],
                    [InlineKeyboardButton(text="🆘 Спор", callback_data=f"dispute_{order_id}")],
                    [InlineKeyboardButton(text="📄 Написать сообщение", callback_data=f"chat_write_{order_id}")],
                    [InlineKeyboardButton(text="🏠 Домой", callback_data="client_back_menu")]
                ])
            )
            await db.db_execute("UPDATE orders SET client_message_id=$1 WHERE id=$2", new_msg.message_id, order_id)
            try:
                await bot.delete_message(user_id, order["client_message_id"])
            except Exception as e:
                logger.error(f"[req_card] delete error: {e}")

        await call.answer("✅ Реквизиты отправлены клиенту", show_alert=True)
        worker_msg = await call.message.answer(
            f"{order_info(order_id, amount, total_usdt, unique=is_unique)}\n\n"
            f"✅ Реквизиты отправлены · ⏳ Ждём запрос кода",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🆘 Спор", callback_data=f"worker_dispute_{order_id}")],
                [InlineKeyboardButton(text="📄 Написать сообщение", callback_data=f"chat_write_{order_id}")],
                [InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")]
            ])
        )
        old_worker_msg_id = None
        try:
            w_row = await db.db_fetchone("SELECT worker_message_id FROM orders WHERE id=$1", order_id)
            if w_row:
                old_worker_msg_id = w_row["worker_message_id"]
        except:
            pass
        await db.db_execute("UPDATE orders SET worker_message_id=$1 WHERE id=$2", worker_msg.message_id, order_id)
        if old_worker_msg_id:
            try:
                await bot.delete_message(chat_id=uid, message_id=old_worker_msg_id)
            except:
                pass
        try:
            await call.message.delete()
        except:
            pass

    @dp.callback_query(F.data.startswith("request_code_"))
    async def request_code(call: types.CallbackQuery):
        order_id = int(call.data.split("_")[2])
        row = await db.db_fetchone(
            "SELECT worker_id, status FROM orders WHERE id=$1 AND user_id=$2",
            order_id, call.from_user.id
        )
        if not row or row["worker_id"] is None:
            return await call.answer("❌ Нет доступа", show_alert=True)

        try:
            await call.message.delete()
        except:
            pass

        worker_id = row["worker_id"]
        status = row["status"]
        order = await db.db_fetchone("SELECT amount, total_usdt, dispute_reason, dispute_card_data, is_unique FROM orders WHERE id=$1", order_id)
        amount = float(order["amount"]) if order else 0.0
        total_usdt = float(order["total_usdt"]) if order and order["total_usdt"] else 0.0
        is_unique = (order["is_unique"] or False) if order else False

        if status == "DISPUTE":
            d_reason = order["dispute_reason"] or "—"
            card_data = order["dispute_card_data"] or ""
            await update_client_dispute_msg(bot, order_id, call.from_user.id, amount, d_reason, card_data=card_data, code_requested=True)
        else:
            card_data = order["dispute_card_data"] or ""
            card_block = f"📋 Реквизиты для оплаты:\n{card_data}\n\n" if card_data else ""
            new_client_msg = await bot.send_message(
                call.from_user.id,
                f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> <b>#{order_id} · Карта под оплату</b>\n\n"
                f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> {amount:.2f} RUB\n\n"
                f"<tg-emoji emoji-id='5444856076954520455'>📋</tg-emoji> Реквизиты для оплаты:\n"
                f"▸ <tg-emoji emoji-id='5332455502917949981'>🏦</tg-emoji> {card['bank']}\n"
                f"▸ <tg-emoji emoji-id='5445353829304387411'>💳</tg-emoji> <code>{card['card_number']}</code>\n"
                f"▸ <tg-emoji emoji-id='5274055917766202507'>📅</tg-emoji> {card['expiry']}\n"
                f"▸ <tg-emoji emoji-id='5443127283898405358'>🔐</tg-emoji> <code>{card['cvv']}</code>\n\n"
                f"<tg-emoji emoji-id='5397782960512444700'>🔑</tg-emoji> Код запрошен у исполнителя\n"
                f"<tg-emoji emoji-id='5276412364458059956'>⏳</tg-emoji> Ожидайте код...",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🆘 Спор", callback_data=f"dispute_{order_id}")],
                    [InlineKeyboardButton(text="📄 Написать сообщение", callback_data=f"chat_write_{order_id}")],
                    [InlineKeyboardButton(text="🏠 Домой", callback_data="client_back_menu")]
                ])
            )
            await db.db_execute("UPDATE orders SET client_message_id=$1 WHERE id=$2", new_client_msg.message_id, order_id)

        try:
            w_row = await db.db_fetchone("SELECT worker_message_id FROM orders WHERE id=$1", order_id)
            if w_row and w_row["worker_message_id"]:
                await bot.delete_message(chat_id=worker_id, message_id=w_row["worker_message_id"])
        except:
            pass

        await db.db_execute("UPDATE orders SET code_requested=TRUE WHERE id=$1", order_id)

        new_worker_msg = await bot.send_message(
            worker_id,
            f"{order_info(order_id, amount, total_usdt, unique=is_unique)}\n\n"
            f"🔑 Клиент запросил код",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📥 Отправить код", callback_data=f"send_code_{order_id}")],
                [InlineKeyboardButton(text="🆘 Спор", callback_data=f"worker_dispute_{order_id}")],
                [InlineKeyboardButton(text="📄 Написать сообщение", callback_data=f"chat_write_{order_id}")],
                [InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")]
            ])
        )
        await db.db_execute("UPDATE orders SET worker_message_id=$1 WHERE id=$2", new_worker_msg.message_id, order_id)
        await call.answer("Запрос отправлен 📩")

    @dp.callback_query(F.data.startswith("send_code_"))
    async def send_code(call: types.CallbackQuery, state: FSMContext):
        order_id = int(call.data.split("_")[2])
        order = await db.db_fetchone(
            "SELECT id, worker_message_id FROM orders WHERE id=$1 AND worker_id=$2", order_id, call.from_user.id
        )
        if not order:
            return await call.answer("❌ Нет доступа", show_alert=True)
        if not order["worker_message_id"]:
            return await call.answer("⏳ Клиент ещё не запросил код", show_alert=True)
        await state.set_state(WorkerStates.waiting_for_code)
        try:
            await call.message.delete()
        except:
            pass
        msg = await call.message.answer("🔐 Введите код для клиента одним сообщением:")
        await state.update_data(active_order_id=order_id, ask_code_msg_id=msg.message_id)
        await call.answer()

    @dp.message(WorkerStates.waiting_for_code)
    async def process_code(message: types.Message, state: FSMContext):
        data = await state.get_data()
        order_id = data.get("active_order_id")
        ask_code_msg_id = data.get("ask_code_msg_id")
        code = message.text.strip()
        worker_id = message.from_user.id

        row = await db.db_fetchone(
            "SELECT user_id, amount, total_usdt, client_message_id, status, dispute_reason, dispute_card_data, is_unique FROM orders WHERE id=$1", order_id
        )
        if not row:
            await state.clear()
            return await message.answer("❌ Ошибка: заявка не найдена")

        user_id = row["user_id"]
        amount = float(row["amount"])
        total_usdt = float(row["total_usdt"]) if row["total_usdt"] else 0.0
        client_msg_id = row["client_message_id"]
        status = row["status"]
        is_unique = row["is_unique"] or False

        if ask_code_msg_id:
            try:
                await bot.delete_message(chat_id=message.chat.id, message_id=ask_code_msg_id)
            except:
                pass
        try:
            await message.delete()
        except:
            pass

        await db.db_execute("UPDATE orders SET dispute_code=$1 WHERE id=$2", code, order_id)

        if status == "DISPUTE":
            d_reason = row["dispute_reason"] or "—"
            card_data = row["dispute_card_data"] or ""
            await update_client_dispute_msg(bot, order_id, user_id, amount, d_reason, card_data=card_data, code=code)
        else:
            card_data = row["dispute_card_data"] or ""
            card_block = f"📋 Реквизиты для оплаты:\n{card_data}\n\n" if card_data else ""
            new_msg = await bot.send_message(
                chat_id=user_id,
                text=(
                    f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> <b>#{order_id} · Карта под оплату</b>\n\n"
                    f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> {amount:.2f} RUB\n\n"
                    f"{card_block}"
                    f"<tg-emoji emoji-id='5397782960512444700'>🔑</tg-emoji> Код подтверждения: <code>{code}</code>\n\n"
                    f"<tg-emoji emoji-id='5276412364458059956'>⏳</tg-emoji> Нажмите кнопку ниже, если оплата прошла успешно"
                ),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Оплата прошла", callback_data=f"client_paid_{order_id}")],
                    [InlineKeyboardButton(text="🆘 Спор", callback_data=f"dispute_{order_id}")],
                    [InlineKeyboardButton(text="📄 Написать сообщение", callback_data=f"chat_write_{order_id}")],
                    [InlineKeyboardButton(text="🏠 Домой", callback_data="client_back_menu")]
                ])
            )
            await db.db_execute("UPDATE orders SET client_message_id=$1 WHERE id=$2", new_msg.message_id, order_id)
            try:
                await bot.delete_message(chat_id=user_id, message_id=client_msg_id)
            except Exception as e:
                logger.error(f"[process_code] delete error: {e}")

        try:
            w_row = await db.db_fetchone("SELECT worker_message_id FROM orders WHERE id=$1", order_id)
            if w_row and w_row["worker_message_id"]:
                await bot.delete_message(chat_id=worker_id, message_id=w_row["worker_message_id"])
        except:
            pass

        worker_msg = await bot.send_message(
            chat_id=worker_id,
            text=(
                f"{order_info(order_id, amount, total_usdt, unique=is_unique)}\n\n"
                f"✅ Код отправлен · ⏳ Ждём подтверждения клиента"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🆘 Спор", callback_data=f"worker_dispute_{order_id}")],
                [InlineKeyboardButton(text="📄 Написать сообщение", callback_data=f"chat_write_{order_id}")],
                [InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")]
            ])
        )
        await db.db_execute("UPDATE orders SET worker_message_id=$1 WHERE id=$2", worker_msg.message_id, order_id)
        await state.clear()
