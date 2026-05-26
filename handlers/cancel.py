import logging
from aiogram import types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import db

logger = logging.getLogger(__name__)


def register_cancel(dp, bot):

    @dp.callback_query(F.data.startswith("cancel_req_"))
    async def cancel_request(call: types.CallbackQuery):
        order_id = int(call.data.split("_")[2])
        uid = call.from_user.id

        row = await db.db_fetchone(
            "SELECT user_id, worker_id, status, amount, total_usdt FROM orders WHERE id=$1", order_id
        )
        if not row:
            return await call.answer("❌ Заявка не найдена", show_alert=True)

        status = row["status"]
        if status not in ("NEW", "IN_PROGRESS", "DISPUTE"):
            return await call.answer("❌ Нельзя отменить эту заявку", show_alert=True)

        user_id = row["user_id"]
        worker_id = row["worker_id"]

        # Определяем кто инициатор и кто получатель
        if uid == user_id:
            initiator = "client"
            recipient_id = worker_id
            initiator_label = "Клиент"
        elif uid == worker_id:
            initiator = "worker"
            recipient_id = user_id
            initiator_label = "Воркер"
        else:
            return await call.answer("❌ Нет доступа", show_alert=True)

        if recipient_id is None:
            # Воркер ещё не назначен — клиент может отменить сразу
            result = await db.db_execute(
                "UPDATE orders SET status='CANCELLED' WHERE id=$1 AND status='NEW'", order_id
            )
            if "UPDATE 0" in result:
                return await call.answer("❌ Заявка уже изменена", show_alert=True)
            total_usdt = float(row["total_usdt"] or 0)
            await db.unfreeze_back(user_id, total_usdt)
            try:
                await call.message.edit_text(
                    f"<tg-emoji emoji-id='5278578973595427038'>❌</tg-emoji> Заявка #{order_id} отменена.\n\n"
                    f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> Средства возвращены на баланс.",
                    parse_mode="HTML"
                )
            except:
                await call.answer("✅ Заявка отменена", show_alert=True)
            return await call.answer()

        amount = float(row["amount"])

        # Уведомляем другую сторону
        try:
            await bot.send_message(
                recipient_id,
                f"<tg-emoji emoji-id='5278578973595427038'>❌</tg-emoji> <b>Запрос на отмену заявки #{order_id}</b>\n\n"
                f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> Сумма: <b>{amount:.2f} RUB</b>\n\n"
                f"<tg-emoji emoji-id='5275979556308674886'>👤</tg-emoji> {initiator_label} запрашивает отмену сделки.\n"
                f"Если вы согласны — средства вернутся клиенту.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(text="✅ Подтвердить отмену", callback_data=f"cancel_confirm_{order_id}"),
                        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"cancel_reject_{order_id}")
                    ]
                ])
            )
        except Exception as e:
            logger.error(f"[cancel_request] notify error: {e}")

        try:
            await call.message.edit_text(
                f"<tg-emoji emoji-id='5276412364458059956'>⏳</tg-emoji> <b>Запрос на отмену отправлен</b>\n\n"
                f"Заявка #{order_id} · Ожидаем подтверждения другой стороны.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🏠 Домой", callback_data="client_back_menu" if initiator == "client" else "lk_home")]
                ])
            )
        except:
            pass
        await call.answer("📩 Запрос отправлен", show_alert=True)

    @dp.callback_query(F.data.startswith("cancel_confirm_"))
    async def cancel_confirm(call: types.CallbackQuery):
        order_id = int(call.data.split("_")[2])
        uid = call.from_user.id

        row = await db.db_fetchone(
            "SELECT user_id, worker_id, status, total_usdt FROM orders WHERE id=$1", order_id
        )
        if not row:
            return await call.answer("❌ Заявка не найдена", show_alert=True)

        status = row["status"]
        if status not in ("NEW", "IN_PROGRESS", "DISPUTE"):
            return await call.answer("❌ Заявка уже завершена или отменена", show_alert=True)

        user_id = row["user_id"]
        worker_id = row["worker_id"]
        total_usdt = float(row["total_usdt"] or 0)

        # Отменяем заявку и возвращаем средства
        result = await db.db_execute(
            "UPDATE orders SET status='CANCELLED' WHERE id=$1 AND status IN ('NEW','IN_PROGRESS','DISPUTE')", order_id
        )
        if "UPDATE 0" in result:
            return await call.answer("❌ Заявка уже изменена", show_alert=True)

        await db.unfreeze_back(user_id, total_usdt)

        # Уведомляем обе стороны
        try:
            await bot.send_message(
                user_id,
                f"<tg-emoji emoji-id='5278578973595427038'>❌</tg-emoji> <b>Заявка #{order_id} отменена</b>\n\n"
                f"<tg-emoji emoji-id='5255806447106679302'>💰</tg-emoji> Средства возвращены на баланс.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🏠 В меню", callback_data="client_back_menu")]
                ])
            )
        except Exception as e:
            logger.error(f"[cancel_confirm] notify client error: {e}")

        if worker_id and worker_id != uid:
            try:
                await bot.send_message(
                    worker_id,
                    f"<tg-emoji emoji-id='5278578973595427038'>❌</tg-emoji> <b>Заявка #{order_id} отменена</b>\n\n"
                    f"Отмена подтверждена. Средства возвращены клиенту.",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🏠 Домой", callback_data="lk_home")]
                    ])
                )
            except Exception as e:
                logger.error(f"[cancel_confirm] notify worker error: {e}")

        try:
            await call.message.edit_text(
                f"<tg-emoji emoji-id='5206476089127372379'>✅</tg-emoji> <b>Отмена подтверждена</b>\n\n"
                f"Заявка #{order_id} закрыта. Средства возвращены клиенту.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🏠 Домой", callback_data="client_back_menu" if uid == user_id else "lk_home")]
                ])
            )
        except:
            pass
        await call.answer("✅ Заявка отменена", show_alert=True)

    @dp.callback_query(F.data.startswith("cancel_reject_"))
    async def cancel_reject(call: types.CallbackQuery):
        order_id = int(call.data.split("_")[2])
        uid = call.from_user.id

        row = await db.db_fetchone(
            "SELECT user_id, worker_id, status FROM orders WHERE id=$1", order_id
        )
        if not row:
            return await call.answer("❌ Заявка не найдена", show_alert=True)

        user_id = row["user_id"]
        worker_id = row["worker_id"]

        # Определяем кто отклонил и кому уведомить
        if uid == user_id:
            notify_id = worker_id
            home_cb = "client_back_menu"
        else:
            notify_id = user_id
            home_cb = "lk_home"

        # Уведомляем инициатора об отклонении
        if notify_id:
            try:
                await bot.send_message(
                    notify_id,
                    f"<tg-emoji emoji-id='5278578973595427038'>❌</tg-emoji> <b>Запрос на отмену отклонён</b>\n\n"
                    f"Заявка #{order_id} продолжается.",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="📄 Открыть заявку",
                            callback_data=f"chat_view_order_{order_id}" if notify_id == worker_id else f"chat_view_client_order_{order_id}")]
                    ])
                )
            except Exception as e:
                logger.error(f"[cancel_reject] notify error: {e}")

        try:
            await call.message.edit_text(
                f"<tg-emoji emoji-id='5206476089127372379'>✅</tg-emoji> Вы отклонили запрос на отмену.\n\n"
                f"Заявка #{order_id} продолжается.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📄 Открыть заявку",
                        callback_data=f"chat_view_order_{order_id}" if uid == worker_id else f"chat_view_client_order_{order_id}")]
                ])
            )
        except:
            pass
        await call.answer("Запрос отклонён", show_alert=True)
