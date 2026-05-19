import logging
from aiogram import types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

logger = logging.getLogger(__name__)


def register_transfer(dp, bot):

    @dp.callback_query(F.data == "client_transfer")
    async def transfer_start(call: types.CallbackQuery):
        try:
            await call.message.delete()
        except:
            pass

        await call.message.answer(
            "<b>🏦 Перевод на карту</b>\n\n"
            "<blockquote>Выберите тип перевода. Исполнитель переведёт нужную сумму "
            "на указанные реквизиты.</blockquote>\n\n"
            "Выберите тип перевода:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="📲 СБП", callback_data="transfer_sbp"),
                    InlineKeyboardButton(text="💳 По номеру карты", callback_data="transfer_card")
                ],
                [InlineKeyboardButton(text="🏠 Назад", callback_data="client_back_menu")]
            ])
        )
        await call.answer()

    @dp.callback_query(F.data == "transfer_sbp")
    async def transfer_sbp(call: types.CallbackQuery):
        await call.answer("🚧 Раздел в разработке", show_alert=True)

    @dp.callback_query(F.data == "transfer_card")
    async def transfer_card(call: types.CallbackQuery):
        await call.answer("🚧 Раздел в разработке", show_alert=True)
