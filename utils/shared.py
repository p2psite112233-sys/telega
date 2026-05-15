from config import ADMIN_ID

# Глобальные хранилища (в оперативной памяти)
workers = set()
users_role = {}

def set_role(user_id: int, role: str):
    """
    Устанавливает роль пользователю и автоматически обновляет список воркеров.
    """
    users_role[user_id] = role
    
    if role == "worker":
        workers.add(user_id)
    else:
        # Если роль изменилась с воркера на юзера, убираем из рассылки
        workers.discard(user_id)

def get_role(user_id: int) -> str:
    """
    Возвращает текущую роль пользователя. 
    Администратор всегда имеет приоритет.
    """
    if user_id == ADMIN_ID:
        return "admin"
    return users_role.get(user_id, "user")

def is_worker(user_id: int) -> bool:
    """
    Быстрая проверка, является ли пользователь воркером или админом.
    """
    return get_role(user_id) in ["worker", "admin"]
