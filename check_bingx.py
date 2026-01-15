
import ccxt
import os
import json
from datetime import datetime

# Load Environment Variables (Simulated for this script)
# You should ensure 'dotenv' is installed or source .env before running
# But for simplicity, we will try to read .env manually if os.environ is empty
def load_env():
    try:
        with open('.env', 'r') as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    key, value = line.strip().split('=', 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    os.environ[key] = value
    except Exception as e:
        print(f"⚠️ Could not load .env file: {e}")

load_env()

API_KEY = os.getenv("BINGX_MASTER_KEY")
SECRET_KEY = os.getenv("BINGX_MASTER_SECRET")

if not API_KEY or not SECRET_KEY:
    print("❌ Error: BINGX_MASTER_KEY or BINGX_MASTER_SECRET not found in .env")
    exit(1)

print(f"🔑 Keys found: {API_KEY[:4]}...{API_KEY[-4:]}")

def check_bingx():
    print("\n--- Connecting to BingX (Swap/Futures) ---")
    try:
        # Initialize BingX for Swap (Perpetual Futures)
        exchange = ccxt.bingx({
            'apiKey': API_KEY,
            'secret': SECRET_KEY,
            'options': {'defaultType': 'swap'}  # Crucial for futures
        })
        
        # 1. Check Balance
        print("💰 Fetching Balance...")
        balance = exchange.fetch_balance()
        usdt_bal = balance['total'].get('USDT', 0)
        print(f"✅ Balance: {usdt_bal} USDT")

        # 2. Check Positions
        print("\n📊 Fetching Open Positions...")
        positions = exchange.fetch_positions()
        active_positions = [p for p in positions if float(p['contracts']) > 0]
        
        if active_positions:
            for p in active_positions:
                print(f"   • {p['symbol']} | Size: {p['contracts']} | Side: {p['side']} | PNL: {p['unrealizedPnl']}")
        else:
            print("   (No open positions)")

        # 3. Check Recent Trades (History)
        print("\n📜 Fetching Recent Trades (Last 10)...")
        # Note: fetch_my_trades might require a symbol argument on some exchanges
        # We'll try without symbol first, or iterate a few common symbols if needed
        try:
            trades = exchange.fetch_my_trades(limit=10) # Some exchanges support this, some need symbol
            if trades:
                for t in trades:
                    print(f"   • {t['datetime']} | {t['symbol']} | {t['side']} | {t['amount']} @ {t['price']}")
            else:
                print("   (No recent trades found via generic fetch)")
        except Exception as e:
            print(f"   ⚠️ Generic fetch failed: {e}")
            print("   Trying specific symbols (BTC/USDT:USDT, ETH/USDT:USDT)...")
            
            for sym in ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT']:
                try:
                    t = exchange.fetch_my_trades(symbol=sym, limit=5)
                    if t:
                        print(f"   ✅ Found for {sym}:")
                        for tr in t:
                            print(f"      - {tr['datetime']} | {tr['side']} | {tr['amount']} @ {tr['price']}")
                except Exception as inner_e:
                    # Ignore symbol not found, irrelevant
                    pass

    except Exception as e:
        print(f"\n❌ Error connecting to BingX: {e}")
        # Print full traceback for debugging
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_bingx()
