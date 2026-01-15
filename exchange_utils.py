import asyncio
import ccxt
from binance.um_futures import UMFutures

async def fetch_exchange_balance_safe(exchange_name, api_key, secret, passphrase=None):
    """Helper to fetch USDT balance safely via thread."""
    exchange_name = exchange_name.lower()
    
    def _fetch():
        try:
            if exchange_name == 'binance':
                c = UMFutures(key=api_key, secret=secret, base_url="https://fapi.binance.com")
                acc = c.account()
                # Use 'walletBalance' (Total)
                return float(next((a['walletBalance'] for a in acc['assets'] if a['asset']=='USDT'), 0))
            elif exchange_name == 'okx':
                ex = ccxt.okx({'apiKey': api_key, 'secret': secret, 'password': passphrase, 'options': {'defaultType': 'spot'}})
                bal = ex.fetch_balance()
                return float(bal['USDT']['total']) # Total
            else: # bybit, bingx
                ex_class = getattr(ccxt, exchange_name)
                # Ensure correct options for futures
                options = {'defaultType': 'future'}
                if exchange_name == 'bingx': options['defaultType'] = 'swap' # Standardize if using ccxt
                
                ex = ex_class({'apiKey': api_key, 'secret': secret, 'options': options})
                bal = ex.fetch_balance() # Type might be needed for some
                return float(bal['USDT']['total']) # Total
        except Exception as e:
            print(f"Fetch Error ({exchange_name}): {e}")
            return None
            
    return await asyncio.to_thread(_fetch)

async def validate_exchange_credentials(exchange_name, api_key, secret, passphrase=None):
    """validates keys by trying to fetch balance. Returns True/False."""
    bal = await fetch_exchange_balance_safe(exchange_name, api_key, secret, passphrase)
    return bal is not None
