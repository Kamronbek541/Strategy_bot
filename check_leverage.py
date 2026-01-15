import os
from dotenv import load_dotenv
from binance.um_futures import UMFutures

load_dotenv()

key = os.getenv("MASTER_API_KEY")
secret = os.getenv("MASTER_SECRET_KEY")

client = UMFutures(key=key, secret=secret, base_url="https://testnet.binancefuture.com")

symbol = "BTCUSDT"

print(f"--- ЗАПРОС ПЛЕЧА ДЛЯ {symbol} ---")
try:
    # Используем тот самый метод из документации
    positions = client.get_position_risk(symbol=symbol)
    
    # Печатаем ВЕСЬ ответ, чтобы видеть глазами
    print("Raw Response:", positions)
    
    if positions:
        # Обычно это список, берем первый элемент
        lev = positions[0].get('leverage')
        print(f"✅ LEVERAGE FOUND: {lev}x")
    else:
        print("❌ Пустой список позиций")

except Exception as e:
    print(f"❌ Ошибка: {e}")