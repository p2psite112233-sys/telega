def order_info(order_id: int, amount: float, total_usdt: float, unique: bool = False) -> str:
    """Форматирует информацию о заявке для воркера по твоей математике с минимальной комиссией 30 RUB"""
    # 1. Рублевая математика с защитой от маленьких сумм
    # Считаем стандартный процент комиссии (25% для уникальных, 20% для обычных карт)
    percent = 0.25 if unique else 0.20
    dirty_profit_rub = amount * percent
    
    # ПРОВЕРКА НА МИНИМАЛКУ: Если комиссия меньше 30 рублей, принудительно ставим 30 RUB
    if dirty_profit_rub < 30.0:
        dirty_profit_rub = 30.0
        
    total_rub = round(amount + dirty_profit_rub, 2)  # Сколько платит клиент в итоге
    worker_profit_rub = round(dirty_profit_rub * 0.80, 2)  # Заработок воркера (80% от спреда)

    # 2. Перевод в USDT по реальному курсу заявки
    rate = total_rub / total_usdt if total_usdt > 0 else 1.0
    amount_usdt = round(amount / rate, 4)
    worker_profit_usdt = round(worker_profit_rub / rate, 4)
    
    # Итого к начислению воркеру (Тело + 80% от спреда)
    worker_total_payout = amount_usdt + worker_profit_usdt 

    unique_text = "✅ Уникальная карта" if unique else "❌ Обычная карта"
    min_commission_note = " ⚠️ (Включена мин. комиссия 30 RUB)" if (amount * percent) < 30.0 else ""
    
    return (
        f"🆔 <b>ID заявки:</b> #{order_id}\n"
        f"💳 <b>Услуга:</b> Карта под оплату\n"
        f"🃏 {unique_text}\n\n"
        f"💰 <b>Сумма перевода:</b> {amount:.2f} RUB (~{amount_usdt:.4f} USDT)\n"
        f"💎 <b>Клиент оплатит:</b> {total_rub:.2f} RUB{min_commission_note}\n\n"
        f"💵 <b>Ваш чистый заработок:</b> +{worker_profit_rub:.2f} RUB (+{worker_profit_usdt:.4f} USDT)\n"
        f"📈 <b>Итог к зачислению вам:</b> <b>{worker_total_payout:.4f} USDT</b>"
    )
