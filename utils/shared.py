from config import ADMIN_ID

# Список ID воркеров для быстрой проверки и рассылок
# Заполняется при старте бота из БД (в main.py)
workers = set()

# Кэш ролей (чтобы не дергать БД на каждое сообщение)
users_role = {}

def set_role(user_id: int, role: str):
    """Назначает роль пользователю в кэше"""
    users_role[user_id] = role
    if role == "worker":
        workers.add(user_id)
    elif role == "user" and user_id in workers:
        workers.remove(user_id)

def get_role(user_id: int) -> str:
    """Возвращает роль: admin > worker > user"""
    if user_id == ADMIN_ID:
        return "admin"
    return users_role.get(user_id, "user")
