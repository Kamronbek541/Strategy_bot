import os
import ccxt
from dotenv import load_dotenv
from datetime import datetime
import pytz # <-- НОВЫЙ ИМПОРТ

def check_okx_spot_orders():
    """
    Подключается к OKX Spot и выводит активные ордера с датой по немецкому времени.
    """
    print("\n--- [OKX Spot Order Checker] ---")
    load_dotenv()

    api_key = os.getenv("OKX_MASTER_KEY")
    secret_key = os.getenv("OKX_MASTER_SECRET")
    password = os.getenv("OKX_MASTER_PASSWORD")

    if not all([api_key, secret_key, password]):
        print("❌ Ошибка: Ключи OKX не найдены в .env.")
        return

    try:
        exchange = ccxt.okx({
            'apiKey': api_key,
            'secret': secret_key,
            'password': password,
            'options': {'defaultType': 'spot'},
        })
        print("✅ Успешно подключились к OKX.")
    except Exception as e:
        print(f"❌ Ошибка подключения: {e}")
        return

    try:
        balance = exchange.fetch_balance()
        usdt_balance = balance.get('USDT', {}).get('total', 0)
        
        if usdt_balance > 0:
            print(f"💰 Общий баланс USDT: ${usdt_balance:,.2f}")

        open_orders = exchange.fetch_open_orders()

        if not open_orders:
            print("\n✅ Нет активных ордеров.")
            return

        print(f"\n--- Активные ордера на OKX Spot ({len(open_orders)}) ---")

        # --- НОВЫЙ БЛОК: Настройка часового пояса ---
        berlin_tz = pytz.timezone('Europe/Berlin')

        for order in open_orders:
            symbol = order['symbol']
            side = order['side'].upper()
            order_type = order['type']
            amount = order.get('amount', 0)
            price = order.get('price', 0)
            
            # --- НОВЫЙ БЛОК: Конвертация времени ---
            order_datetime_str = order.get('datetime', 'N/A')
            formatted_datetime = 'N/A'
            
            if order_datetime_str != 'N/A':
                # 1. Парсим строку в объект datetime (с часовым поясом UTC)
                utc_dt = datetime.fromisoformat(order_datetime_str.replace('Z', '+00:00'))
                
                # 2. Конвертируем в часовой пояс Берлина
                berlin_dt = utc_dt.astimezone(berlin_tz)
                
                # 3. Форматируем в нужный вид (День.Месяц.Год Час:Минута)
                formatted_datetime = berlin_dt.strftime('%d.%m.%Y %H:%M:%S')
            # ------------------------------------

            cost_usd = (amount * price) if price and amount else 0
            percentage = (cost_usd / usdt_balance * 100) if usdt_balance > 0 else 0

            print("-" * 30)
            print(f"🗓️  Datum:    {formatted_datetime} (Berlin)")
            print(f"🪙  Münze:    {symbol}")
            print(f"   - Typ:      {side} ({order_type})")
            print(f"   - Menge:    {amount}")
            print(f"   - Preis:    ${price:,.2f}")
            print(f"   - Summe:    ${cost_usd:,.2f}")
            print(f"   - % des Guthabens: {percentage:.2f}%")

    except ccxt.AuthenticationError:
        print("❌ Ошибка аутентификации.")
    except Exception as e:
        print(f"❌ Произошла ошибка: {e}")

if __name__ == "__main__":
    check_okx_spot_orders()