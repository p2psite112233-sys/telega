import sys
import traceback
import asyncpg
from config import DATABASE_URL

pool = None

async def init_db():
    global pool
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
        print("DB pool created OK")
    except Exception as e:
        print(f"DB POOL ERROR: {e}")
        traceback.print_exc()
        sys.exit(1)

    async with pool.acquire() as conn:
        # Создание таблиц
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                amount NUMERIC(18,8),
                status TEXT,
                worker_id BIGINT,
                client_message_id BIGINT,
                worker_message_id BIGINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS workers (
                user_id BIGINT PRIMARY KEY
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS balances (
                user_id BIGINT PRIMARY KEY,
                balance NUMERIC(18,8) DEFAULT 0.0,
                frozen NUMERIC(18,8) DEFAULT 0.0
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS invoices (
                invoice_id BIGINT PRIMARY KEY,
                user_id BIGINT,
                amount NUMERIC(18,8),
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS cards (
                id SERIAL PRIMARY KEY,
                worker_id BIGINT,
                card_number TEXT,
                expiry TEXT,
                cvv TEXT,
                bank TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Миграции (ALTER TABLE выполняются быстро, если колонки уже есть)
        await conn.execute("ALTER TABLE balances ADD COLUMN IF NOT EXISTS frozen NUMERIC(18,8) DEFAULT 0.0")
        await conn.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS client_message_id BIGINT")
        await conn.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS worker_message_id BIGINT")
        await conn.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS total_usdt NUMERIC(18,8) DEFAULT 0.0")
        await conn.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        await conn.execute("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        await conn.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS amount_usdt NUMERIC(18,8) DEFAULT 0.0")
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS worker_applications (
                user_id BIGINT PRIMARY KEY,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                next_apply_at TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_profit (
                id SERIAL PRIMARY KEY,
                amount NUMERIC(18,8),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS withdrawals (
                id SERIAL PRIMARY KEY,
                worker_id BIGINT,
                amount NUMERIC(18,8),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

    print("DB tables OK")


async def get_balance(user_id: int) -> float:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT balance FROM balances WHERE user_id=$1", user_id)
    return float(row["balance"]) if row and row["balance"] is not None else 0.0

async def get_frozen(user_id: int) -> float:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT frozen FROM balances WHERE user_id=$1", user_id)
    return float(row["frozen"]) if row and row["frozen"] is not None else 0.0

async def add_balance(user_id: int, amount: float):
    async with pool.acquire() as conn:
        # Оптимизировано: гарантируем, что frozen не станет NULL для новых юзеров
        await conn.execute("""
            INSERT INTO balances (user_id, balance, frozen) VALUES ($1, $2, 0.0)
            ON CONFLICT (user_id) DO UPDATE SET balance = balances.balance + $2
        """, user_id, amount)

async def freeze_balance(user_id: int, amount: float) -> bool:
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT balance FROM balances WHERE user_id=$1 FOR UPDATE", user_id
            )
            if not row or float(row["balance"]) < amount:
                return False
            await conn.execute("""
                UPDATE balances SET balance = balance - $1, frozen = frozen + $1
                WHERE user_id=$2
            """, amount, user_id)
    return True

async def unfreeze_to_worker(client_id: int, worker_id: int, total_usdt: float, amount_usdt: float = 0.0) -> bool:
    """
    total_usdt = полная сумма с комиссией
    amount_usdt = чистая сумма без комиссии
    воркер получает: amount_usdt + commission * 0.8
    """
    commission_usdt = total_usdt - amount_usdt
    worker_amount = round(amount_usdt + commission_usdt * 0.8, 8)
    bot_amount = round(commission_usdt * 0.2, 8)
    
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Защита: проверяем, списались ли замороженные средства у клиента
            status = await conn.execute(
                "UPDATE balances SET frozen = frozen - $1 WHERE user_id=$2 AND frozen >= $1",
                total_usdt, client_id
            )
            if "UPDATE 0" in status:
                return False  # У клиента не хватило замороженных средств, отменяем операцию
                
            await conn.execute("""
                INSERT INTO balances (user_id, balance, frozen) VALUES ($1, $2, 0.0)
                ON CONFLICT (user_id) DO UPDATE SET balance = balances.balance + $2
            """, worker_id, worker_amount)
            
            await conn.execute("""
                INSERT INTO bot_profit (amount) VALUES ($1)
            """, bot_amount)
    return True

async def unfreeze_back(user_id: int, amount: float):
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("""
                UPDATE balances SET balance = balance + $1, frozen = frozen - $1
                WHERE user_id=$2 AND frozen >= $1
            """, amount, user_id)

async def db_fetchone(query: str, *args):
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, *args)

async def db_fetchall(query: str, *args):
    async with pool.acquire() as conn:
        return await conn.fetch(query, *args)

async def db_execute(query: str, *args):
    async with pool.acquire() as conn:
        return await conn.execute(query, *args)

async def load_workers_from_db():
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM workers")
    return [row["user_id"] for row in rows]
