import sys
import traceback
import psycopg2
from config import DATABASE_URL

print(f"Connecting to DB: {DATABASE_URL[:40] if DATABASE_URL else 'NOT SET'}...")
try:
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()
    print("DB connected OK")
except Exception as e:
    print(f"DB CONNECTION ERROR: {e}")
    traceback.print_exc()
    sys.exit(1)

# ===== СОЗДАНИЕ ТАБЛИЦ =====
cur.execute("""
CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    amount REAL,
    status TEXT,
    worker_id BIGINT,
    client_message_id BIGINT,
    worker_message_id BIGINT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS workers (
    user_id BIGINT PRIMARY KEY
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS balances (
    user_id BIGINT PRIMARY KEY,
    balance REAL DEFAULT 0.0
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS invoices (
    invoice_id BIGINT PRIMARY KEY,
    user_id BIGINT,
    amount REAL,
    status TEXT DEFAULT 'active'
)
""")

cur.execute("""
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

# Убедимся что колонка frozen существует
cur.execute("ALTER TABLE balances ADD COLUMN IF NOT EXISTS frozen REAL DEFAULT 0.0")
# Обнуляем NULL значения
cur.execute("UPDATE balances SET frozen = 0.0 WHERE frozen IS NULL")

# ===== ХЕЛПЕРЫ =====
def get_balance(user_id: int) -> float:
    with psycopg2.connect(DATABASE_URL) as c:
        with c.cursor() as cur2:
            cur2.execute("SELECT balance FROM balances WHERE user_id=%s", (user_id,))
            row = cur2.fetchone()
    return float(row[0]) if row and row[0] is not None else 0.0

def get_frozen(user_id: int) -> float:
    with psycopg2.connect(DATABASE_URL) as c:
        with c.cursor() as cur2:
            cur2.execute("SELECT frozen FROM balances WHERE user_id=%s", (user_id,))
            row = cur2.fetchone()
    return float(row[0]) if row and row[0] is not None else 0.0

def db_fetchone(query: str, params: tuple):
    """Читает одну строку через свежее соединение."""
    with psycopg2.connect(DATABASE_URL) as c:
        with c.cursor() as cur2:
            cur2.execute(query, params)
            return cur2.fetchone()

def db_fetchall(query: str, params: tuple):
    """Читает все строки через свежее соединение."""
    with psycopg2.connect(DATABASE_URL) as c:
        with c.cursor() as cur2:
            cur2.execute(query, params)
            return cur2.fetchall()

def add_balance(user_id: int, amount: float):
    cur.execute("""
        INSERT INTO balances (user_id, balance) VALUES (%s, %s)
        ON CONFLICT (user_id) DO UPDATE SET balance = balances.balance + %s
    """, (user_id, amount, amount))

def freeze_balance(user_id: int, amount: float) -> bool:
    """Замораживает сумму на балансе. Возвращает False если недостаточно средств."""
    c = psycopg2.connect(DATABASE_URL)
    c.autocommit = True
    cur2 = c.cursor()
    cur2.execute("SELECT balance FROM balances WHERE user_id=%s", (user_id,))
    row = cur2.fetchone()
    if not row or row[0] < amount:
        c.close()
        return False
    cur2.execute("""
        UPDATE balances SET balance = balance - %s, frozen = frozen + %s WHERE user_id=%s
    """, (amount, amount, user_id))
    c.close()
    return True

def unfreeze_to_worker(client_id: int, worker_id: int, amount: float):
    """Списывает с frozen клиента и зачисляет воркеру."""
    cur.execute("UPDATE balances SET frozen = frozen - %s WHERE user_id=%s", (amount, client_id))
    cur.execute("""
        INSERT INTO balances (user_id, balance) VALUES (%s, %s)
        ON CONFLICT (user_id) DO UPDATE SET balance = balances.balance + %s
    """, (worker_id, amount, amount))

def unfreeze_back(user_id: int, amount: float):
    """Возвращает замороженную сумму обратно на баланс (отмена заявки)."""
    cur.execute("""
        UPDATE balances SET balance = balance + %s, frozen = frozen - %s WHERE user_id=%s
    """, (amount, amount, user_id))
