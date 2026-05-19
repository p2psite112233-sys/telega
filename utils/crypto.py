import aiohttp
from config import CRYPTO_BOT_TOKEN, CRYPTO_API_URL

async def crypto_get_rate() -> float:
    """Получает курс USDT/RUB из CryptoBot."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{CRYPTO_API_URL}/getExchangeRates",
                headers={"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
            ) as resp:
                data = await resp.json()
                if data.get("ok"):
                    for rate in data["result"]:
                        if rate["source"] == "USDT" and rate["target"] == "RUB":
                            return float(rate["rate"])
    except:
        pass
    return 90.0

async def crypto_create_invoice(amount_usdt: float, user_id: int) -> dict | None:
    """Создаёт инвойс в CryptoBot."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{CRYPTO_API_URL}/createInvoice",
                headers={"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN},
                json={
                    "asset": "USDT",
                    "amount": str(round(amount_usdt, 2)),
                    "description": f"Пополнение баланса (ID: {user_id})",
                    "expires_in": 900
                }
            ) as resp:
                data = await resp.json()
                if data.get("ok"):
                    return data["result"]
    except:
        pass
    return None

async def crypto_check_invoice(invoice_id: int) -> str:
    """Проверяет статус инвойса."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{CRYPTO_API_URL}/getInvoices",
                headers={"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN},
                params={"invoice_ids": str(invoice_id)}
            ) as resp:
                data = await resp.json()
                if data.get("ok") and data["result"]["items"]:
                    return data["result"]["items"][0]["status"]
    except:
        pass
    return "unknown"

async def crypto_create_check_debug(amount_usdt: float) -> str:
    """Возвращает полный ответ CryptoBot для отладки."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{CRYPTO_API_URL}/createCheck",
                headers={"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN},
                json={"asset": "USDT", "amount": str(round(amount_usdt, 2))}
            ) as resp:
                data = await resp.json()
                return str(data)
    except Exception as e:
        return str(e)

async def crypto_create_check(amount_usdt: float) -> dict | None:
    """Создаёт чек в CryptoBot для выплаты воркеру."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{CRYPTO_API_URL}/createCheck",
                headers={"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN},
                json={
                    "asset": "USDT",
                    "amount": str(round(amount_usdt, 2))
                }
            ) as resp:
                data = await resp.json()
                print(f"[createCheck] response: {data}", flush=True)
                if data.get("ok"):
                    return data["result"]
    except Exception as e:
        print(f"[createCheck] error: {e}", flush=True)
    return None
    """Создаёт чек в CryptoBot для выплаты воркеру."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{CRYPTO_API_URL}/createCheck",
                headers={"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN},
                json={
                    "asset": "USDT",
                    "amount": str(round(amount_usdt, 2))
                }
            ) as resp:
                data = await resp.json()
                print(f"[createCheck] response: {data}", flush=True)
                if data.get("ok"):
                    return data["result"]
    except Exception as e:
        print(f"[createCheck] error: {e}", flush=True)
    return None
