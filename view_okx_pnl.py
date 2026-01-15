import os
import ccxt
from dotenv import load_dotenv
from datetime import datetime
import pytz

def view_okx_pnl_history():
    """
    Подключается к OKX Spot, загружает историю сделок
    и рассчитывает PnL для закрытых позиций.
    """
    print("\n--- [OKX Spot PnL History Viewer] ---")
    load_dotenv()

    # 1. Загрузка ключей
    api_key = os.getenv("OKX_MASTER_KEY")
    secret_key = os.getenv("OKX_MASTER_SECRET")
    password = os.getenv("OKX_MASTER_PASSWORD")

    if not all([api_key, secret_key, password]):
        print("❌ Ошибка: Ключи OKX не найдены в .env.")
        return

    # 2. Подключение
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
        # 3. Загружаем последние 50 сделок
        print("\n⏳ Загружаем историю сделок...")
        my_trades = exchange.fetch_my_trades(limit=50)

        if not my_trades:
            print("ℹ️ История сделок пуста.")
            return
            
        # 4. Группируем сделки по парам (BTC/USDT, ETH/USDT...)
        trades_by_symbol = {}
        for trade in my_trades:
            symbol = trade['symbol']
            if symbol not in trades_by_symbol:
                trades_by_symbol[symbol] = []
            trades_by_symbol[symbol].append(trade)

        print(f"\n--- Анализ PnL по последним сделкам ---")
        berlin_tz = pytz.timezone('Europe/Berlin')

        # 5. Анализируем каждую пару
        for symbol, trades in trades_by_symbol.items():
            # Сортируем сделки от старых к новым
            trades.sort(key=lambda x: x['timestamp'])
            
            # Логика для Spot: ищем пару Buy -> Sell
            # Упрощенная модель: считаем, что каждая продажа закрывает предыдущую покупку
            
            last_buy_price = None
            last_buy_qty = 0
            
            for trade in trades:
                side = trade['side']
                price = trade['price']
                amount = trade['amount']
                cost = trade['cost'] # Сумма в USDT
                
                # Форматируем дату
                dt_utc = datetime.utcfromtimestamp(trade['timestamp'] / 1000)
                dt_berlin = pytz.utc.localize(dt_utc).astimezone(berlin_tz)
                dt_str = dt_berlin.strftime('%d.%m.%Y %H:%M')

                if side == 'buy':
                    print(f"\n[ПОКУПКА] {dt_str} | {symbol} | {amount} @ ${price:,.2f} | Сумма: ${cost:,.2f}")
                    # Запоминаем последнюю покупку
                    last_buy_price = price
                    last_buy_qty = amount

                elif side == 'sell' and last_buy_price is not None:
                    # Если была покупка до этого, считаем PnL
                    print(f"[ПРОДАЖА] {dt_str} | {symbol} | {amount} @ ${price:,.2f} | Сумма: ${cost:,.2f}")
                    
                    # Считаем PnL (упрощенно, считая что продали столько же, сколько купили)
                    pnl = (price - last_buy_price) * last_buy_qty
                    
                    if pnl > 0:
                        print(f"  ✅ ПРОФИТ: ${pnl:,.4f}")
                    else:
                        print(f"  🔻 УБЫТОК: ${pnl:,.4f}")
                    
                    # Сбрасываем, чтобы искать следующую пару
                    last_buy_price = None

    except Exception as e:
        print(f"❌ Произошла ошибка: {e}")

if __name__ == "__main__":
    view_okx_pnl_history()