from datetime import datetime
from src import config
from src.database import RegistryDatabase

db = RegistryDatabase()

def get_system_prompt():
    db_schema = db.get_schema()
    current_date = datetime.now().strftime("%d.%m.%Y")
    try:
        last_update_date = db.last_update_time() or "Неизвестно"
    except Exception:
        last_update_date = "Ошибка при получении"
    config.load_prompts()
    return config.current_system_prompt.format(
        db_schema=db_schema,
        user_prompt=config.current_user_prompt,
        current_date=current_date,
        last_update_date=last_update_date,
    )
