import os
from urllib.parse import quote_plus

BOT_TOKEN = os.getenv("BOT_TOKEN")
CRYPTO_BOT_TOKEN = os.getenv("CRYPTO_BOT_TOKEN")
CRYPTO_API_URL = "https://pay.crypt.bot/api"
ADMIN_ID = 8538723496

_db_url = os.getenv("DATABASE_URL", "")
_db_password = os.getenv("DB_PASSWORD", "")
DATABASE_URL = _db_url.replace("[YOUR-PASSWORD]", quote_plus(_db_password))

# Баннеры
BANNER_FILE_ID = "AgACAgIAAxkBAAIC0WoG5sJR0bYbAdNbPaX4Db0fcbOIAALvEmsb1Hc4SDgCkVsM1xIhAQADAgADeQADOwQ"
PROFILE_BANNER_FILE_ID = "AgACAgIAAxkBAAIC22oG60BMhrR_cGdSTWlUOlceSuYSAAKaE2sbIOg5SIkS3QUK926nAQADAgADeQADOwQ"
CARD_BANNER_FILE_ID = "AgACAgIAAxkBAAIC92oG8dC8NL-jzOBotlCM2XGM-i86AALcE2sbIOg5SDV64bApD116AQADAgADeQADOwQ"
