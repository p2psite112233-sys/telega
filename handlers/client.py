import logging
from aiogram import types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

import db
from config import PROFILE_BANNER_FILE_ID, ADMIN_ID
from handlers.common import WorkerRegStates
from handlers.dispute import DisputeStates

logger = logging.getLogger(__name__)

CLIENT_MENU_TEXT = (
    "<b><tg-emoji emoji-id='5298668674532538341'>🏠</tg-emoji> Send$Paid — Главное меню</b>\n\n"
    "<blockquote>Бот поможет получить карту под оплату, перевести деньги на карту/СБП, "
    "пополнить номер телефона или оплатить готовый QR-код.\n"
    "Все этапы заявки фиксируются внутри сервиса.</blockquote>\n\n"
    "<tg-emoji emoji-id='5276037216244624892'>💼</tg-emoji> Комиссия сервиса: <b>20%</b> от суммы, но не меньше 30 RUB\n"
    "<tg-emoji emoji-id='5276229330131772747'>🆕</tg-emoji> Уникальная карта: дополнительно <b>+5%</b>\n"
    "<tg-emoji emoji-id='5278647306525108244'>🔳</tg-emoji> QR-оплата: скидка по комиссии <b>-8%</b>\n"
    "<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> Работаем <b>24/7</b>"
)

CLIENT_MENU_KEYBOARD = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="💳 Карта под оплату", callback_data="client_card"),
        InlineKeyboardButton(text="🏦 Перевод на карту", callback_data="client_transfer")
    ],
    [
        InlineKeyboardButton(text="📳 Пополнить номер", callback_data="client_phone"),
        InlineKeyboardButton(text="◾️ Оплата QR-Кода", callback_data="client_qr")
    ],
    [InlineKeyboardButton(text="🤑 Пополнить баланс", callback_data="client_topup")],
    [
        InlineKeyboardButton(text="🙋‍♂️ Профиль", callback_data="client_profile"),
        InlineKeyboardButton(text="📄 Стать исполнителем", callback_data="client_become_worker")
    ],
    [InlineKeyboardButton(text="🆘 Поддержка", url="https://t.me/usudhsuhd")]
])


def get_type_label(transfer_type):
    if transfer_type == "sbp":
        return "Перевод по СБП"
    elif transfer_type == "card":
        return "Перевод по номеру карты"
    elif transfer_type == "phone":
        return "Пополнение номера"
    return "Карта под оплату"


def register_client(dp, bot):

    @dp.callback_query(F.data.startswith("cancel_order_"))
    async def cancel_order(call: types.CallbackQuery):
        order_id = int(call.data.split("_")[2])
        uid = call.from_user.id
        row = await db.db_fetchone("SELECT status, total_usdt, worker_id FROM orders WHERE id=$1 AND user_id=$2", order_id, uid)
        if not row:
            return await call.answer("❌ Заявка не найдена", show_alert=True)
        status = row["status"]
        if status == "DONE":
            return await call.answer("❌ Нельзя отменить завершённую заявку", show_alert=True)
        if status not in ("NEW", "IN_PROGRESS"):
            return await call.answer("❌ Заявку нельзя отменить", show_alert=True)
        result = await db.db_execute(
            "UPDATE orders SET status='CANCELLED' WHERE id=$1 AND status IN ('NEW', 'IN_PROGRESS')", order_id
        )
        if "UPDATE 0" in result:
            return await call.answer("❌ Заявка уже отменена или завершена", show_alert=True)
        total_usdt = float(row["total_usdt"]) if row["total_usdt"] else 0.0
        worker_id = row["worker_id"]
        await db.unfreeze_back(uid, total_usdt)
        try:
            await call.message.edit_text(f"❌ Заявка #{order_id} отменена\n\n💰 Средства возвращены на баланс")
        except Exception as e:
            logger.error(f"[cancel_order] edit error: {e}")
        await call.answer("✅ Заявка отменена", show_alert=True)
        if worker_id:
            try:
                await bot.send_message(worker_id, f"❌ Заявка #{order_id} была отменена клиентом")
            except:
                pass

    @dp.callback_query(F.data.startswith("client_paid_"))
    async def client_paid(call: types.CallbackQuery):
        parts = call.data.split("_")
        order_id = int(parts[2])
        uid = call.from_user.id
        row = await db.db_fetchone(
            "SELECT worker_id, amount, status, client_message_id, total_usdt, amount_usdt, "
            "transfer_type, transfer_phone, transfer_bank, transfer_recipient_name FROM orders WHERE id=$1 AND user_id=$2",
            order_id, uid
        )
        if not row:
            return await call.answer("❌ Заявка не найдена", show_alert=True)
        worker_id = row["worker_id"]
        amount = float(row["amount"])
        status = row["status"]
        client_msg_id = row["client_message_id"]
        total_usdt = float(row["total_usdt"]) if row["total_usdt"] else 0.0
        amount_usdt = float(row["amount_usdt"]) if row["amount_usdt"] else 0.0
        transfer_type = row["transfer_type"]
        transfer_phone = row["transfer_phone"] or ""
        transfer_bank = row["transfer_bank"] or ""
        transfer_name = row["transfer_recipient_name"] or ""

        if status == "DONE":
            return await call.answer("✅ Заявка уже завершена", show_alert=True)
        result = await db.db_execute("UPDATE orders SET status='DONE' WHERE id=$1 AND status IN ('IN_PROGRESS', 'DISPUTE')", order_id)
        if "UPDATE 0" in result:
            return await call.answer("✅ Заявка уже завершена", show_alert=True)
        try:
            await call.message.delete()
        except:
            pass
        await db.unfreeze_to_worker(uid, worker_id, total_usdt, amount_usdt)
        client_balance_new = await db.get_balance(uid)

        commission = max(round(amount * 0.20, 2), 30)
        worker_net_usdt = round((total_usdt - amount_usdt) * 0.8, 4)
        worker_total_usdt = round(amount_usdt + worker_net_usdt, 4)

        if transfer_type == "sbp":
            type_label = "Перевод по СБП"
            req_line = f"▸ <tg-emoji emoji-id='5278304890257436355'>📱</tg-emoji> <code>{transfer_phone}</code>"
        elif transfer_type == "card":
            type_label = "Перевод по номеру карты"
            req_line = f"▸ <tg-emoji emoji-id='5445353829304387411'>💳</tg-emoji> <code>{transfer_phone}</code>"
        elif transfer_type == "phone":
            type_label = "Пополнение номера"
            req_line = f"▸ <tg-emoji emoji-id='5278304890257436355'>📱</tg-emoji> <code>{transfer_phone}</code>"
        else:
            type_label = "Карта под оплату"
            req_line = None

        w_row = await db.db_fetchone("SELECT worker_message_id FROM orders WHERE id=$1", order_id)
        if w_row and w_row["worker_message_id"]:
            try:
                await bot.delete_message(chat_id=worker_id, message_id=w_row["worker_message_id"])
            except:
                pass

        if transfer_type in ("sbp", "card"):
            client_text = (
                f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> <b>#{order_id} · {type_label}</b>\n\n"
                f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> {amount:.2f} RUB\n\n"
                f"<tg-emoji emoji-id='5444856076954520455'>📋</tg-emoji> Куда переводили:\n"
                f"{req_line}\n"
                f"▸ <tg-emoji emoji-id='5332455502917949981'>🏦</tg-emoji> {transfer_bank}\n"
                f"▸ <tg-emoji emoji-id='5275979556308674886'>👤</tg-emoji> {transfer_name}\n\n"
                f"<tg-emoji emoji-id='5206476089127372379'>✅</tg-emoji> Заявка завершена!\n"
                f"<tg-emoji emoji-id='5201691993775818138'>💸</tg-emoji> Списано: {total_usdt:.4f} USDT\n"
                f"<tg-emoji emoji-id='5445221832074483553'>💼</tg-emoji> Ваш баланс: {client_balance_new:.2f} USDT"
            )
            worker_text = (
                f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> <b>#{order_id} · {type_label}</b>\n\n"
                f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> {amount:.2f} RUB\n\n"
                f"<tg-emoji emoji-id='5444856076954520455'>📋</tg-emoji> Куда переводили:\n"
                f"{req_line}\n"
                f"▸ <tg-emoji emoji-id='5332455502917949981'>🏦</tg-emoji> {transfer_bank}\n"
                f"▸ <tg-emoji emoji-id='5275979556308674886'>👤</tg-emoji> {transfer_name}\n\n"
                f"<tg-emoji emoji-id='5445221832074483553'>💼</tg-emoji> Итог сделки:\n"
                f"▸ <tg-emoji emoji-id='5201691993775818138'>💵</tg-emoji> Ваш заработок: +{commission * 0.8:.2f} RUB\n"
                f"▸ <tg-emoji emoji-id='5276229330131772747'>💎</tg-emoji> В USDT: +{worker_net_usdt:.4f} USDT\n"
                f"▸ <tg-emoji emoji-id='5190806721286657692'>📊</tg-emoji> Зачислено: {worker_total_usdt:.4f} USDT\n"
                f"▸ <tg-emoji emoji-id='5206476089127372379'>✅</tg-emoji> Заявка завершена!"
            )
        elif transfer_type == "phone":
            client_text = (
                f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> <b>#{order_id} · Пополнение номера</b>\n\n"
                f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> {amount:.2f} RUB\n"
                f"<tg-emoji emoji-id='5278304890257436355'>📱</tg-emoji> Номер: <code>{transfer_phone}</code>\n\n"
                f"<tg-emoji emoji-id='5206476089127372379'>✅</tg-emoji> Заявка завершена!\n"
                f"<tg-emoji emoji-id='5201691993775818138'>💸</tg-emoji> Списано: {total_usdt:.4f} USDT\n"
                f"<tg-emoji emoji-id='5445221832074483553'>💼</tg-emoji> Ваш баланс: {client_balance_new:.2f} USDT"
            )
            worker_text = (
                f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> <b>#{order_id} · Пополнение номера</b>\n\n"
                f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> {amount:.2f} RUB\n"
                f"<tg-emoji emoji-id='5278304890257436355'>📱</tg-emoji> Номер: <code>{transfer_phone}</code>\n\n"
                f"<tg-emoji emoji-id='5445221832074483553'>💼</tg-emoji> Итог сделки:\n"
                f"▸ <tg-emoji emoji-id='5201691993775818138'>💵</tg-emoji> Ваш заработок: +{commission * 0.8:.2f} RUB\n"
                f"▸ <tg-emoji emoji-id='5276229330131772747'>💎</tg-emoji> В USDT: +{worker_net_usdt:.4f} USDT\n"
                f"▸ <tg-emoji emoji-id='5190806721286657692'>📊</tg-emoji> Зачислено: {worker_total_usdt:.4f} USDT\n"
                f"▸ <tg-emoji emoji-id='5206476089127372379'>✅</tg-emoji> Заявка завершена!"
            )
        else:
            client_text = (
                f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> <b>#{order_id} · Карта под оплату</b>\n\n"
                f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> {amount:.2f} RUB\n\n"
                f"<tg-emoji emoji-id='5444856076954520455'>📋</tg-emoji> Итог сделки:\n"
                f"▸ <tg-emoji emoji-id='5206476089127372379'>✅</tg-emoji> Оплата подтверждена\n"
                f"▸ <tg-emoji emoji-id='5201691993775818138'>💸</tg-emoji> Списано: {total_usdt:.4f} USDT\n"
                f"▸ <tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> Остаток баланса: {client_balance_new:.2f} USDT\n\n"
                f"<tg-emoji emoji-id='5406926593698312391'>🎉</tg-emoji> Спасибо за использование Send$Paid!"
            )
            worker_text = (
                f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> <b>#{order_id} · Карта под оплату</b>\n\n"
                f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> {amount:.2f} RUB\n\n"
                f"<tg-emoji emoji-id='5445221832074483553'>💼</tg-emoji> Итог сделки:\n"
                f"▸ <tg-emoji emoji-id='5201691993775818138'>💵</tg-emoji> Ваш заработок: +{commission * 0.8:.2f} RUB\n"
                f"▸ <tg-emoji emoji-id='5276229330131772747'>💎</tg-emoji> В USDT: +{worker_net_usdt:.4f} USDT\n"
                f"▸ <tg-emoji emoji-id='5190806721286657692'>📊</tg-emoji> Зачислено: {worker_total_usdt:.4f} USDT\n"
                f"▸ <tg-emoji emoji-id='5206476089127372379'>✅</tg-emoji> Заявка завершена!"
            )

        try:
            await bot.edit_message_text(
                chat_id=uid, message_id=client_msg_id,
                text=client_text, parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"[client_paid] edit error: {e}")

        await call.answer("✅ Оплата подтверждена!", show_alert=True)

        try:
            await bot.send_message(worker_id, worker_text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"[client_paid] send_message error: {e}")

    @dp.callback_query(
        (
            F.data.startswith("lk_") |
            F.data.startswith("client_") |
            F.data.startswith("cards_") |
            F.data.startswith("card_") |
            F.data.startswith("history_") |
            F.data.startswith("worker_history_") |
            F.data.startswith("active_order_")
        )
        & ~F.data.startswith("client_paid_")
        & ~F.data.startswith("client_card")
        & ~F.data.startswith("client_topup")
        & ~F.data.startswith("client_transfer")
        & ~F.data.startswith("client_phone")
        & ~F.data.startswith("client_withdraw")
        & ~F.data.startswith("send_req_")
        & ~F.data.startswith("worker_confirm_")
        & ~F.data.startswith("worker_apply")
        & ~F.data.startswith("take_")
        & ~F.data.startswith("lk_available")
        & ~F.data.in_({"card_unique_yes", "card_unique_no", "client_support", "lk_withdraw"})
    )
    async def lk_buttons(call: types.CallbackQuery, state: FSMContext):
        uid = call.from_user.id
        chat_id = call.message.chat.id

        try:
            await call.message.delete()
        except:
            pass

        if call.data == "client_become_worker":
            await bot.send_message(
                chat_id,
                "<tg-emoji emoji-id='5197269100878907942'>📝</tg-emoji> <b>Заявка на роль исполнителя</b>\n"
                "<blockquote>Заполните короткую анкету, чтобы мы могли рассмотреть вас на роль оплатчика.\n"
                "Все ответы отправятся одной заявкой на рассмотрение администрации после финальной проверки.</blockquote>\n"
                "Что важно:\n• можно вернуться к предыдущему вопросу;\n"
                "• можно отменить заполнение в любой момент;\n• перед отправкой будет итоговая сверка.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✍️ Отправить заявку", callback_data="worker_apply")],
                    [InlineKeyboardButton(text="🔙 Домой", callback_data="client_back_menu")]
                ])
            )
            return await call.answer()

        if call.data == "client_back_menu":
            from config import BANNER_FILE_ID
            await bot.send_photo(chat_id, photo=BANNER_FILE_ID, caption=CLIENT_MENU_TEXT, reply_markup=CLIENT_MENU_KEYBOARD, parse_mode="HTML")
            return await call.answer()

        if call.data == "client_profile":
            username = f"@{call.from_user.username}" if call.from_user.username else "нет username"
            balance = await db.get_balance(uid)
            frozen = await db.get_frozen(uid)
            row = await db.db_fetchone("SELECT COUNT(*) FROM orders WHERE user_id=$1 AND status='DONE'", uid)
            closed = row["count"] if row else 0
            row = await db.db_fetchone("SELECT COUNT(*) FROM orders WHERE user_id=$1 AND status='IN_PROGRESS'", uid)
            active = row["count"] if row else 0
            row = await db.db_fetchone("SELECT COUNT(*) FROM invoices WHERE user_id=$1 AND status='paid'", uid)
            paid_count = row["count"] if row else 0
            text = (
                f"<tg-emoji emoji-id='5275979556308674886'>👤</tg-emoji> <b>Личный профиль</b>\n<blockquote>{username} [{uid}]</blockquote>\n\n"
                f"<tg-emoji emoji-id='5445221832074483553'>💼</tg-emoji> <b>Финансы</b>\n• Баланс: <b>{balance:.2f} USDT</b>\n• Заморожено: <b>{frozen:.2f} USDT</b>\n\n"
                f"<tg-emoji emoji-id='5231200819986047254'>📊</tg-emoji> <b>Статистика</b>\n• Закрыто заявок: {closed} шт\n• Активных заявок: {active} шт\n• Успешных пополнений: {paid_count} шт"
            )
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔗 Реферальная ссылка", callback_data="client_ref")],
                [InlineKeyboardButton(text="📚 История", callback_data="client_history")],
                [InlineKeyboardButton(text="💸 Вывод", callback_data="client_withdraw")],
                [InlineKeyboardButton(text="🏠 В меню", callback_data="client_back_menu")]
            ])
            await bot.send_photo(chat_id, photo=PROFILE_BANNER_FILE_ID, caption=text, reply_markup=keyboard, parse_mode="HTML")
            return await call.answer()

        if call.data == "client_ref":
            ref_link = f"https://t.me/{(await bot.get_me()).username}?start={uid}"
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад в профиль", callback_data="client_profile")]])
            await bot.send_message(chat_id, f"🔗 <b>Ваша реферальная ссылка:</b>\n<code>{ref_link}</code>", parse_mode="HTML", reply_markup=keyboard)
            return await call.answer()

        if call.data == "client_support":
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 В меню", callback_data="client_back_menu")]])
            await bot.send_message(chat_id, "🆘 <b>Поддержка сервиса</b>\n\nПо всем вопросам обращайтесь к администратору: @usudhsuhd", parse_mode="HTML", reply_markup=keyboard)
            return await call.answer()

        if call.data == "lk_cards":
            cards = await db.db_fetchall("SELECT id, card_number, expiry FROM cards WHERE worker_id=$1", uid)
            card_buttons = []
            for card in cards:
                masked = f"{card['card_number'][:6]}{'*'*6}{card['card_number'][-4:]} · {card['expiry']}"
                card_buttons.append([InlineKeyboardButton(text=f"💳 {masked}", callback_data=f"card_view_{card['id']}")])
            card_buttons.append([InlineKeyboardButton(text="➕ Добавить карту", callback_data="cards_add")])
            card_buttons.append([InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")])
            await bot.send_message(chat_id, f"<tg-emoji emoji-id='5445353829304387411'>💳</tg-emoji> Управление картами\n\nВыберите карту или добавьте новую.\n\n<tg-emoji emoji-id='5445221832074483553'>💼</tg-emoji> Сохранено карт: {len(cards)}", reply_markup=InlineKeyboardMarkup(inline_keyboard=card_buttons))
            return await call.answer()

        if call.data == "cards_add":
            await state.set_state(WorkerRegStates.waiting_for_card_data)
            await bot.send_message(chat_id, f"<tg-emoji emoji-id='5397916757333654639'>➕</tg-emoji> Добавление карты\n\nОтправьте данные карты в любом удобном виде.\nБот сам найдет номер, срок и CVV.")
            return await call.answer()

        if call.data == "lk_home":
            username = f"@{call.from_user.username}" if call.from_user.username else "нет username"
            balance = await db.get_balance(uid)
            row = await db.db_fetchone("SELECT COUNT(*) FROM orders WHERE worker_id=$1 AND status='DONE'", uid)
            done_count = row["count"] if row else 0
            row = await db.db_fetchone("SELECT COUNT(*) FROM orders WHERE worker_id=$1 AND status='IN_PROGRESS'", uid)
            active_count = row["count"] if row else 0
            text = (
                f"<tg-emoji emoji-id='5332724926216428039'>🛠</tg-emoji> <b>Профиль работника</b>\n"
                f"Аккаунт: {username}\n\n"
                f"<tg-emoji emoji-id='5445221832074483553'>💼</tg-emoji> <b>Финансы</b>\n"
                f"• Доступно: <b>{balance:.2f} USDT</b>\n\n"
                f"<tg-emoji emoji-id='5231200819986047254'>📊</tg-emoji> <b>Статистика</b>\n"
                f"• Выполнено: {done_count} шт\n"
                f"• В работе: {active_count} шт"
            )
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💸 Вывод средств", callback_data="lk_withdraw")],
                [InlineKeyboardButton(text="🟢 Активные заявки", callback_data="lk_active"),
                 InlineKeyboardButton(text="📚 История заявок", callback_data="lk_history")],
                [InlineKeyboardButton(text="💳 Управление картами", callback_data="lk_cards")]
            ])
            await bot.send_photo(chat_id, photo=PROFILE_BANNER_FILE_ID, caption=text, reply_markup=keyboard, parse_mode="HTML")
            return await call.answer()

        if call.data.startswith("card_view_"):
            card_id = int(call.data.split("_")[2])
            row = await db.db_fetchone("SELECT card_number, expiry, cvv, bank, created_at FROM cards WHERE id=$1 AND worker_id=$2", card_id, uid)
            if not row:
                return await call.answer("❌ Карта не найдена", show_alert=True)
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🗑 Удалить карту", callback_data=f"card_delete_{card_id}")],
                [InlineKeyboardButton(text="◀️ К списку карт", callback_data="lk_cards")],
                [InlineKeyboardButton(text="🏠 В кабинет", callback_data="lk_home")]
            ])
            await bot.send_message(chat_id, f"<tg-emoji emoji-id='5445353829304387411'>💳</tg-emoji> Карточка карты\n\n<tg-emoji emoji-id='5445353829304387411'>💳</tg-emoji> Номер: {row['card_number']}\n<tg-emoji emoji-id='5274055917766202507'>📅</tg-emoji> Срок: {row['expiry']}\n<tg-emoji emoji-id='5443127283898405358'>🔐</tg-emoji> Код: {row['cvv']}\n<tg-emoji emoji-id='5332455502917949981'>🏦</tg-emoji> Банк: {row['bank']}\n<tg-emoji emoji-id='5276412364458059956'>🕒</tg-emoji> Добавлена: {row['created_at']}", reply_markup=keyboard)
            return await call.answer()

        if call.data.startswith("card_delete_"):
            card_id = int(call.data.split("_")[2])
            await db.db_execute("DELETE FROM cards WHERE id=$1 AND worker_id=$2", card_id, uid)
            await call.answer("✅ Карта удалена", show_alert=True)
            cards = await db.db_fetchall("SELECT id, card_number, expiry FROM cards WHERE worker_id=$1", uid)
            card_buttons = []
            for card in cards:
                masked = f"{card['card_number'][:6]}{'*'*6}{card['card_number'][-4:]} · {card['expiry']}"
                card_buttons.append([InlineKeyboardButton(text=f"💳 {masked}", callback_data=f"card_view_{card['id']}")])
            card_buttons.append([InlineKeyboardButton(text="➕ Добавить карту", callback_data="cards_add")])
            card_buttons.append([InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")])
            await bot.send_message(chat_id, f"<tg-emoji emoji-id='5445353829304387411'>💳</tg-emoji> Управление картами\n\nСохранено карт: {len(cards)}", reply_markup=InlineKeyboardMarkup(inline_keyboard=card_buttons))
            return await call.answer()

        if call.data == "lk_active":
            orders = await db.db_fetchall(
                "SELECT id, amount, total_usdt, transfer_type FROM orders WHERE worker_id=$1 AND status='IN_PROGRESS' ORDER BY id DESC", uid
            )
            if not orders:
                await bot.send_message(chat_id, f"<tg-emoji emoji-id='5278611606756942667'>🟢</tg-emoji> Активных заявок нет", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")]
                ]))
                return await call.answer()
            buttons = []
            for order in orders:
                t = order["transfer_type"]
                if t == "sbp":
                    label = "📲 СБП"
                elif t == "card":
                    label = "💳 По карте"
                elif t == "phone":
                    label = "📱 Пополнение номера"
                else:
                    label = "💳 Карта под оплату"
                buttons.append([InlineKeyboardButton(
                    text=f"🟢 {label} #{order['id']} — {float(order['amount']):.0f} RUB",
                    callback_data=f"active_order_{order['id']}"
                )])
            buttons.append([InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")])
            await bot.send_message(
                chat_id, f"<tg-emoji emoji-id='5278611606756942667'>🟢</tg-emoji> <b>Активные заявки</b>\n\nВыберите заявку для управления:",
                parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
            )
            return await call.answer()

        if call.data.startswith("active_order_"):
            order_id = int(call.data.split("_")[2])
            await bot.send_message(
                chat_id,f"<tg-emoji emoji-id='5197269100878907942'>📄</tg-emoji> Открываю заявку...",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📄 Посмотреть заявку", callback_data=f"chat_view_order_{order_id}")]
                ])
            )
            return await call.answer()

        if call.data.startswith("lk_history"):
            parts = call.data.split("_")
            filter_type = parts[2] if len(parts) > 2 else "all"
            page = int(parts[3]) if len(parts) > 3 else 0
            offset = page * 10
            status_map = {
                "all": "status IN ('IN_PROGRESS', 'DONE', 'CANCELLED')",
                "done": "status='DONE'",
                "active": "status='IN_PROGRESS'",
                "cancelled": "status='CANCELLED'"
            }
            where = status_map.get(filter_type, status_map["all"])
            orders = await db.db_fetchall(
                f"SELECT id, amount, total_usdt, status FROM orders WHERE worker_id=$1 AND {where} ORDER BY id DESC LIMIT 11 OFFSET {offset}", uid
            )
            has_next = len(orders) == 11
            orders = orders[:10]
            filter_kb = [
                [
                    InlineKeyboardButton(text="📋 Все", callback_data="lk_history_all_0"),
                    InlineKeyboardButton(text="✅ Закрыто", callback_data="lk_history_done_0"),
                    InlineKeyboardButton(text="🟢 Активные", callback_data="lk_history_active_0"),
                    InlineKeyboardButton(text="❌ Отмена", callback_data="lk_history_cancelled_0"),
                ]
            ]
            if not orders:
                filter_kb.append([InlineKeyboardButton(text="🏠 В кабинет", callback_data="lk_home")])
                await bot.send_photo(
                    chat_id, photo=PROFILE_BANNER_FILE_ID,
                    caption=f"<tg-emoji emoji-id='5361741454685256344'>📚</tg-emoji> <b>История воркера</b>\n\n<blockquote>Заявок не найдено.</blockquote>",
                    parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=filter_kb)
                )
                return await call.answer()
            buttons = list(filter_kb)
            for order in orders:
                total_usdt = float(order["total_usdt"]) if order["total_usdt"] else 0
                status = order["status"]
                if status == "DONE": icon = "✅"
                elif status == "IN_PROGRESS": icon = "🟢"
                elif status == "CANCELLED": icon = "❌"
                else: icon = "🟡"
                buttons.append([InlineKeyboardButton(
                    text=f"{icon} #{order['id']} — {float(order['amount']):.0f} RUB",
                    callback_data=f"worker_history_order_{order['id']}"
                )])
            nav = []
            if page > 0:
                nav.append(InlineKeyboardButton(text="◀️", callback_data=f"lk_history_{filter_type}_{page-1}"))
            nav.append(InlineKeyboardButton(text=f"• {page+1} •", callback_data="noop"))
            if has_next:
                nav.append(InlineKeyboardButton(text="▶️", callback_data=f"lk_history_{filter_type}_{page+1}"))
            if len(nav) > 1:
                buttons.append(nav)
            buttons.append([InlineKeyboardButton(text="🏠 В кабинет", callback_data="lk_home")])
            await bot.send_photo(
                chat_id, photo=PROFILE_BANNER_FILE_ID,
                caption=f"<tg-emoji emoji-id='5361741454685256344'>📚</tg-emoji> <b>История воркера</b>\n\n<blockquote>Выберите запись из истории, чтобы открыть подробную карточку.</blockquote>",
                parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
            )
            return await call.answer()

        if call.data.startswith("worker_history_order_"):
            order_id = int(call.data.split("_")[3])
            row = await db.db_fetchone(
                "SELECT id, amount, total_usdt, status, transfer_type FROM orders WHERE id=$1 AND worker_id=$2",
                order_id, uid
            )
            if not row:
                return await call.answer("❌ Заявка не найдена", show_alert=True)
            if row["status"] == "IN_PROGRESS":
                await bot.send_message(chat_id, f"<tg-emoji emoji-id='5197269100878907942'>📄</tg-emoji> Открываю заявку...", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📄 Посмотреть заявку", callback_data=f"chat_view_order_{order_id}")]
                ]))
                return await call.answer()
            total_usdt = float(row["total_usdt"]) if row["total_usdt"] else 0
            type_label = get_type_label(row["transfer_type"])
            if row["status"] == "DONE": status_text = "<tg-emoji emoji-id='5206476089127372379'>✅</tg-emoji> Завершена"
            elif row["status"] == "CANCELLED": status_text = "<tg-emoji emoji-id='5278578973595427038'>❌</tg-emoji> Отменена"
            else: status_text = "<tg-emoji emoji-id='5278753302023004775'>🟡</tg-emoji> Новая"
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="lk_history")]])
            await bot.send_message(
                chat_id,
                f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> <b>#{row['id']} · {type_label}</b>\n\n"
                f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> {float(row['amount']):.2f} RUB\n"
                f"<tg-emoji emoji-id='5276229330131772747'>💎</tg-emoji> Зачислено: {total_usdt:.4f} USDT\n"
                f"<tg-emoji emoji-id='5231200819986047254'>📊</tg-emoji> Статус: {status_text}",
                parse_mode="HTML", reply_markup=keyboard
            )
            return await call.answer()

        if call.data.startswith("client_history"):
            parts = call.data.split("_")
            filter_type = parts[2] if len(parts) > 2 else "all"
            page = int(parts[3]) if len(parts) > 3 else 0
            offset = page * 10
            status_map = {
                "all": "status IN ('NEW', 'IN_PROGRESS', 'DONE', 'CANCELLED')",
                "done": "status='DONE'",
                "active": "status IN ('NEW', 'IN_PROGRESS')",
                "cancelled": "status='CANCELLED'"
            }
            where = status_map.get(filter_type, status_map["all"])
            orders = await db.db_fetchall(
                f"SELECT id, amount, total_usdt, status FROM orders WHERE user_id=$1 AND {where} ORDER BY id DESC LIMIT 11 OFFSET {offset}", uid
            )
            has_next = len(orders) == 11
            orders = orders[:10]
            filter_kb = [
                [
                    InlineKeyboardButton(text="📋 Все", callback_data="client_history_all_0"),
                    InlineKeyboardButton(text="✅ Закрыто", callback_data="client_history_done_0"),
                    InlineKeyboardButton(text="🟢 Активные", callback_data="client_history_active_0"),
                    InlineKeyboardButton(text="❌ Отмена", callback_data="client_history_cancelled_0"),
                ]
            ]
            if not orders:
                filter_kb.append([InlineKeyboardButton(text="🏠 В меню", callback_data="client_back_menu")])
                await bot.send_photo(
                    chat_id, photo=PROFILE_BANNER_FILE_ID,
                    caption=f"<tg-emoji emoji-id='5361741454685256344'>📚</tg-emoji> <b>История клиента</b>\n\n<blockquote>Заявок не найдено.</blockquote>",
                    parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=filter_kb)
                )
                return await call.answer()
            buttons = list(filter_kb)
            for order in orders:
                total_usdt = float(order["total_usdt"]) if order["total_usdt"] else 0
                status = order["status"]
                if status == "DONE": icon = "✅"
                elif status == "IN_PROGRESS": icon = "🟢"
                elif status == "CANCELLED": icon = "❌"
                else: icon = "🟡"
                buttons.append([InlineKeyboardButton(
                    text=f"{icon} #{order['id']} — {float(order['amount']):.0f} RUB",
                    callback_data=f"history_order_{order['id']}"
                )])
            nav = []
            if page > 0:
                nav.append(InlineKeyboardButton(text="◀️", callback_data=f"client_history_{filter_type}_{page-1}"))
            nav.append(InlineKeyboardButton(text=f"• {page+1} •", callback_data="noop"))
            if has_next:
                nav.append(InlineKeyboardButton(text="▶️", callback_data=f"client_history_{filter_type}_{page+1}"))
            if len(nav) > 1:
                buttons.append(nav)
            buttons.append([InlineKeyboardButton(text="🏠 В меню", callback_data="client_back_menu")])
            await bot.send_photo(
                chat_id, photo=PROFILE_BANNER_FILE_ID,
                caption=f"<tg-emoji emoji-id='5361741454685256344'>📚</tg-emoji> <b>История клиента</b>\n\n<blockquote>Выберите запись из истории, чтобы открыть подробную карточку.</blockquote>",
                parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
            )
            return await call.answer()

        if call.data.startswith("history_order_"):
            order_id = int(call.data.split("_")[2])
            row = await db.db_fetchone(
                "SELECT id, amount, total_usdt, status, transfer_type FROM orders WHERE id=$1 AND user_id=$2",
                order_id, uid
            )
            if not row:
                return await call.answer("❌ Заявка не найдена", show_alert=True)
            if row["status"] in ("IN_PROGRESS", "DISPUTE"):
                await bot.send_message(chat_id, f"<tg-emoji emoji-id='5197269100878907942'>📄</tg-emoji> Открываю заявку...", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📄 Посмотреть заявку", callback_data=f"chat_view_client_order_{order_id}")]
                ]))
                return await call.answer()
            total_usdt = float(row["total_usdt"]) if row["total_usdt"] else 0
            status = row["status"]
            type_label = get_type_label(row["transfer_type"])
            if status == "DONE": status_text = "<tg-emoji emoji-id='5206476089127372379'>✅</tg-emoji> Завершена"
            elif status == "CANCELLED": status_text = "<tg-emoji emoji-id='5278578973595427038'>❌</tg-emoji> Отменена"
            elif status == "NEW": status_text = "<tg-emoji emoji-id='5278753302023004775'>🟡</tg-emoji> Новая"
            else: status_text = status
            buttons = [[InlineKeyboardButton(text="◀️ Назад", callback_data="client_history")]]
            if status == "NEW":
                buttons.insert(0, [InlineKeyboardButton(text="❌ Отменить заявку", callback_data=f"cancel_order_{row['id']}")])
            await bot.send_message(
                chat_id,
                f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> <b>#{row['id']} · {type_label}</b>\n\n"
                f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> {float(row['amount']):.2f} RUB\n"
                f"<tg-emoji emoji-id='5201691993775818138'>💸</tg-emoji> Списано: {total_usdt:.4f} USDT\n"
                f"<tg-emoji emoji-id='5231200819986047254'>📊</tg-emoji> Статус: {status_text}",
                parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
            )
            return await call.answer()

        await call.answer("🚧 Раздел в разработке", show_alert=True)
