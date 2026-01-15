# update_keys.py
from database import save_user_api_keys

# ВСТАВЬ СЮДА НОВЫЕ КЛЮЧИ
NEW_KEY = "fU2n9AVjrEAeh5nqMSeWJDcBE8hvbEXUKGaGqG8LGl8wn1BJj3mEyBoD0wpkSA0F"
NEW_SECRET = "твой_новыйtbLxaObjj1EHihIV1jfOm6vKMwcT7gKFRtVBQfjWC4hLI1L783Y7boqV7g3nmafc_secret_key"
USER_ID = 8462621561

print(f"Обновляем ключи для {USER_ID}...")
save_user_api_keys(USER_ID, "binance", NEW_KEY, NEW_SECRET)
print("✅ Готово! Перезапускай бота.")