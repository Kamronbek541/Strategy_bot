# import os
# import math
# import pandas as pd
# import pandas_ta as ta
# import ccxt
# from dotenv import load_dotenv

# load_dotenv()
# exchange = ccxt.binance()

# def format_price(price):
#     try:
#         price = float(price)
#         if price == 0:
#             return "0.00"
#         elif price < 0.0001:
#             return f"{price:.8f}".rstrip('0').rstrip('.')
#         elif price < 0.01:
#             return f"{price:.6f}".rstrip('0').rstrip('.')
#         elif price < 1:
#             return f"{price:.5f}".rstrip('0').rstrip('.')
#         elif price < 10:
#             return f"{price:.4f}".rstrip('0').rstrip('.')
#         elif price < 1000:
#             return f"{price:.3f}".rstrip('0').rstrip('.')
#         else:
#             return f"{price:.2f}".rstrip('0').rstrip('.')
#     except:
#         return str(price)

# def get_general_market_sentiment() -> float:
#     print("News analysis is temporarily disabled.")
#     return 0.0

# def fetch_data(symbol="BTC/USDT", timeframe="1h", limit=200):
#     print(f"Fetching {symbol} {timeframe} data...")
#     try:
#         bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
#         df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
#         df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
#         return df
#     except Exception as e:
#         print(f"Error fetching data for {symbol}: {e}")
#         return pd.DataFrame()

# def compute_features(df):
#     if df.empty: 
#         return df

#     df.ta.ema(length=12, append=True, col_names=('EMA_fast',))
#     df.ta.ema(length=26, append=True, col_names=('EMA_slow',))
#     df.ta.rsi(length=14, append=True, col_names=('RSI',))
#     df.ta.atr(length=14, append=True, col_names=('ATR',))
#     df.ta.bbands(length=20, append=True, col_names=('BB_lower', 'BB_mid', 'BB_upper', 'BB_width', 'BB_percent'))
    
#     if len(df) >= 20:
#         df['volume_z'] = (df['volume'] - df['volume'].rolling(20).mean()) / df['volume'].rolling(20).std()
#     else:
#         df['volume_z'] = 0
        
#     return df


# def calculate_position_size(
#     entry_price: float, 
#     stop_loss_price: float, 
#     target_price: float, 
#     account_balance: float, 
#     risk_per_trade_pct: float
# ) -> dict:

#     if any(v is None for v in [entry_price, stop_loss_price, target_price, account_balance, risk_per_trade_pct]):
#         return {}
    
#     risk_amount_usd = account_balance * (risk_per_trade_pct / 100.0)
#     sl_distance = abs(entry_price - stop_loss_price)
#     if sl_distance == 0: return {}
    
#     position_size_asset = risk_amount_usd / sl_distance
#     position_size_usd = position_size_asset * entry_price
    
#     tp_distance = abs(target_price - entry_price)
#     potential_profit_usd = position_size_asset * tp_distance
    
#     risk_reward_ratio = potential_profit_usd / risk_amount_usd if risk_amount_usd > 0 else 0
    
#     return {
#         "position_size_asset": f"{position_size_asset:.4f}",
#         "position_size_usd": f"${position_size_usd:,.2f}",
#         "potential_loss_usd": f"${risk_amount_usd:,.2f}",
#         "potential_profit_usd": f"${potential_profit_usd:,.2f}", 
#         "risk_reward_ratio": f"1:{risk_reward_ratio:.2f}"
#     }

# def generate_decisive_signal(df, symbol_ccxt: str, risk_settings: dict, display_timeframe: str):
#     if df.empty or len(df) < 20: 
#         return None, None
    
#     latest = df.iloc[-1]
#     long_score, short_score = 0, 0
    
#     long_factors = []
#     short_factors = []
    
#     is_trend_up = latest['EMA_fast'] > latest['EMA_slow']
#     if is_trend_up:
#         long_score += 1
#         long_factors.append("Bullish Trend (EMA)")
#     else:
#         short_score += 1
#         short_factors.append("Bearish Trend (EMA)")
    
#     if latest['RSI'] > 52:
#         long_score += 1
#         long_factors.append(f"Strong Momentum (RSI more than 52)")
#     if latest['RSI'] < 48:
#         short_score += 1
#         short_factors.append(f"Weak Momentum (RSI less than 48)")
        

#     volume_z = latest.get('volume_z', 0)
    

#     if len(df) > 11:
#         recent_avg_volume = df['volume'].iloc[-11:-1].mean()
#         if latest['volume'] > recent_avg_volume * 2.0:  
#             if is_trend_up:
#                 long_score += 1.5
#                 long_factors.append("Volume Impulse")
#             else:
#                 short_score += 1.5
#                 short_factors.append("Volume Impulse")
#         elif volume_z > 0:
#             if is_trend_up:
#                 long_score += 0.5
#             else:
#                 short_score += 0.5

#     bb_width = latest.get('BB_width', 0)
#     if bb_width > df['BB_width'].rolling(50).mean().iloc[-1]:
#         if is_trend_up:
#             long_score += 0.5
#         else:
#             short_score += 0.5

#     current_price = latest['close']
    
#     if long_score > short_score:
#         view = "long"
#         notes = "Key factors: " + ", ".join(long_factors) + "."
#         stop = current_price - 1.8 * latest['ATR']
#         target1 = current_price + 2.2 * latest['ATR']
#     else:
#         view = "short"
#         notes = "Key factors: " + ", ".join(short_factors) + "."
#         stop = current_price + 1.8 * latest['ATR']
#         target1 = current_price - 2.2 * latest['ATR']

#     risk_data = calculate_position_size(current_price, stop, target1, risk_settings['balance'], risk_settings['risk_pct'])
    
#     trade_plan = {
#         "symbol": symbol_ccxt.replace("/", ""),
#         "timeframe": display_timeframe,
#         "view": view,
#         "strategy": "Impulse Analysis",
#         "entry_zone": [format_price(current_price * 0.999), format_price(current_price * 1.001)],
#         "stop": format_price(stop),
#         "targets": [format_price(target1)],
#         "confidence": min(0.9, 0.5 + max(long_score, short_score) * 0.1),
#         "notes": notes
#     }
    
#     trade_plan.update(risk_data)
    
#     context = {
#         'trend': "Upward (Fast EMA > Slow EMA)" if is_trend_up else "Downward (Fast EMA < Slow EMA)",
#         'rsi': f"{latest['RSI']:.2f}",
#         'volume': f"Above average (Z-Score: {volume_z:.2f})" if volume_z > 0 else f"Below average (Z-Score: {volume_z:.2f})",
#         'final_scores': f"Long: {long_score:.1f} vs Short: {short_score:.1f}",
#         'final_view': view,
#         'reasoning': "Bullish trend with supportive indicators" if view == "long" else "Bearish trend with supportive indicators"
#     }
    
#     return trade_plan, context

# def generate_signal(df, symbol_ccxt: str, news_score: float, risk_settings: dict, timeframe="1h"):
#     """'Осторожная' версия. Теперь возвращает (trade_plan, context)."""
#     if df.empty or len(df) < 50: 
#         return None, None
    
#     latest = df.iloc[-1]
#     long_score, short_score = 0, 0
    
#     long_factors = []
#     short_factors = []
    
#     is_trend_up = latest['EMA_fast'] > latest['EMA_slow']
#     if is_trend_up:
#         long_score += 1
#         long_factors.append("Uptrend")
#     else:
#         short_score += 1
#         short_factors.append("Downtrend")

#     if latest['RSI'] > 55:
#         long_score += 1
#         long_factors.append(f"Bullish RSI ({latest['RSI']:.0f})")
#     if latest['RSI'] < 45:
#         short_score += 1
#         short_factors.append(f"Bearish RSI ({latest['RSI']:.0f})")

#     volume_z = latest.get('volume_z', 0)
#     if volume_z > 0.8:
#         if is_trend_up:
#             long_score += 1
#             long_factors.append("Elevated Volume")
#         else:
#             short_score += 1
#             short_factors.append("Elevated Volume")

#     bb_width = latest.get('BB_width', 0)
#     if bb_width > df['BB_width'].rolling(50).mean().iloc[-1]:
#         if is_trend_up:
#             long_score += 0.5
#         else:
#             short_score += 0.5

#     CONFIDENCE_THRESHOLD = 2.5
#     current_price = latest['close']
    
#     trade_plan = None
#     context = {
#         'trend': "Upward" if is_trend_up else "Downward",
#         'rsi': f"{latest['RSI']:.2f}",
#         'volume': f"Elevated (Z-Score: {volume_z:.2f})" if volume_z > 0.8 else f"Normal (Z-Score: {volume_z:.2f})",
#         'volatility': "High" if bb_width > df['BB_width'].rolling(50).mean().iloc[-1] else "Normal",
#         'final_scores': f"Long: {long_score:.1f} vs Short: {short_score:.1f}"
#     }
    
#     if long_score >= CONFIDENCE_THRESHOLD and latest['RSI'] < 80:
#         stop = current_price - 1.8 * latest['ATR']
#         target1 = current_price + 2.2 * latest['ATR']

#         risk_data = calculate_position_size(current_price, stop, target1, risk_settings['balance'], risk_settings['risk_pct'])
        
#         trade_plan = {
#             "symbol": symbol_ccxt.replace("/", ""),
#             "timeframe": timeframe,
#             "view": "long",
#             "strategy": f"Confluence Score: {long_score:.1f}",
#             "entry_zone": [format_price(current_price), format_price(current_price * 1.002)],
#             "stop": format_price(stop),
#             "targets": [format_price(target1)],
#             "confidence": min(0.9, 0.5 + (long_score - CONFIDENCE_THRESHOLD) * 0.1),
#             "notes": f"Multiple bullish factors converged: " + ", ".join(long_factors) + f". Market sentiment ({news_score:.2f})."
#         }
#         trade_plan.update(risk_data)
#         context['final_view'] = "long"
#         context['reasoning'] = "Strong bullish confluence with multiple confirming indicators"
        
#     elif short_score >= CONFIDENCE_THRESHOLD and latest['RSI'] > 20:
#         stop = current_price + 1.8 * latest['ATR']
#         target1 = current_price - 2.2 * latest['ATR']
        
#         risk_data = calculate_position_size(current_price, stop, target1, risk_settings['balance'], risk_settings['risk_pct'])
        
#         trade_plan = {
#             "symbol": symbol_ccxt.replace("/", ""),
#             "timeframe": timeframe,
#             "view": "short",
#             "strategy": f"Confluence Score: {short_score:.1f}",
#             "entry_zone": [format_price(current_price * 0.998), format_price(current_price)],
#             "stop": format_price(stop),
#             "targets": [format_price(target1)],
#             "confidence": min(0.9, 0.5 + (short_score - CONFIDENCE_THRESHOLD) * 0.1),
#             "notes": f"Multiple bearish factors converged: " + ", ".join(short_factors) + f". Market sentiment ({news_score:.2f})."
#         }
#         trade_plan.update(risk_data)
#         context['final_view'] = "short"
#         context['reasoning'] = "Strong bearish confluence with multiple confirming indicators"
#     else: 
#         context['final_view'] = "neutral"
        
#         metrics = {
#             "Trend": 'Up' if is_trend_up else 'Down',
#             "RSI": f"{latest['RSI']:.2f}",
#             "Volume": f"{latest.get('volume_z', 0):.2f}",
#             "Sentiment": f"{news_score:.2f}" if news_score != 0 else "N/A"
#         }
        
#         trade_plan = {
#             "symbol": symbol_ccxt.replace("/", ""),
#             "timeframe": timeframe,
#             "view": "neutral",
#             "notes": f"No strong confluence of factors found (Score L:{long_score:.1f}/S:{short_score:.1f} vs Threshold:{CONFIDENCE_THRESHOLD}).",
#             "metrics": metrics 
#         }
#     print("\n--- [CORE ANALYZER] Generated Trade Plan ---")
#     import json
#     print(json.dumps(trade_plan, indent=2))
#     print("------------------------------------------\n")

#     return trade_plan, context



# core_analyzer.py (v-FINAL - OpenRouter/DeepSeek & Risk Reward)
import os
import math
import pandas as pd
import pandas_ta as ta
import ccxt
import json
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# --- НАСТРОЙКА OPENROUTER (DeepSeek) ---
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

if OPENROUTER_API_KEY:
    client = OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=OPENROUTER_API_KEY,
        default_headers={
            "HTTP-Referer": "https://t.me/BlackAladinBot",
            "X-Title": "BlackAladin",
        }
    )
else:
    client = None

# Используем обычный ccxt (синхронный), так как запускаем в потоке
exchange = ccxt.binance()

def format_price(price):
    """Умное форматирование цены."""
    try:
        price = float(price)
        if price == 0: return "0.00"
        if price < 0.0001: return f"{price:.8f}".rstrip('0').rstrip('.')
        if price < 0.01: return f"{price:.6f}".rstrip('0').rstrip('.')
        if price < 1: return f"{price:.5f}".rstrip('0').rstrip('.')
        if price < 10: return f"{price:.4f}".rstrip('0').rstrip('.')
        if price < 1000: return f"{price:.3f}".rstrip('0').rstrip('.')
        return f"{price:.2f}".rstrip('0').rstrip('.')
    except: return str(price)

def get_general_market_sentiment() -> float:
    """
    ВРЕМЕННАЯ ЗАГЛУШКА.
    Если захочешь включить новости через DeepSeek, раскомментируй логику ниже.
    """
    # if not client: return 0.0
    # ... логика запроса к Cryptopanic и анализа через deepseek/deepseek-chat ...
    print("News analysis is temporarily disabled.")
    return 0.0

def fetch_data(symbol="BTC/USDT", timeframe="1h", limit=200):
    print(f"Fetching {symbol} {timeframe} data...")
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        print(f"Error fetching data for {symbol}: {e}")
        return pd.DataFrame()

def compute_features(df):
    if df.empty: return df
    
    # Индикаторы
    df.ta.ema(length=12, append=True, col_names=('EMA_fast',))
    df.ta.ema(length=26, append=True, col_names=('EMA_slow',))
    df.ta.rsi(length=14, append=True, col_names=('RSI',))
    df.ta.atr(length=14, append=True, col_names=('ATR',))
    df.ta.bbands(length=20, append=True, col_names=('BB_lower', 'BB_mid', 'BB_upper', 'BB_width', 'BB_percent'))
    
    if len(df) >= 20:
        df['volume_z'] = (df['volume'] - df['volume'].rolling(20).mean()) / df['volume'].rolling(20).std()
    else:
        df['volume_z'] = 0
    return df

def calculate_position_size(entry_price: float, stop_loss_price: float, target_price: float, account_balance: float, risk_per_trade_pct: float) -> dict:
    """Рассчитывает размер позиции, убыток, прибыль и R:R."""
    if any(v is None for v in [entry_price, stop_loss_price, target_price, account_balance, risk_per_trade_pct]):
        return {}
    
    risk_amount_usd = account_balance * (risk_per_trade_pct / 100.0)
    sl_distance = abs(entry_price - stop_loss_price)
    if sl_distance == 0: return {}
    
    position_size_asset = risk_amount_usd / sl_distance
    position_size_usd = position_size_asset * entry_price
    
    # Расчет прибыли и R:R
    tp_distance = abs(target_price - entry_price)
    potential_profit_usd = position_size_asset * tp_distance
    risk_reward_ratio = potential_profit_usd / risk_amount_usd if risk_amount_usd > 0 else 0
    
    return {
        "position_size_asset": f"{position_size_asset:.4f}",
        "position_size_usd": f"${position_size_usd:,.2f}",
        "potential_loss_usd": f"${risk_amount_usd:,.2f}",
        "potential_profit_usd": f"${potential_profit_usd:,.2f}", # Новое поле
        "risk_reward_ratio": f"1:{risk_reward_ratio:.2f}"        # Новое поле
    }

def generate_decisive_signal(df, symbol_ccxt: str, risk_settings: dict, display_timeframe: str):
    """
    Финальная версия для ГРАФИКОВ.
    """
    if df.empty or len(df) < 20: return None, None
    
    latest = df.iloc[-1]
    long_score, short_score = 0, 0
    long_factors, short_factors = [], []
    
    # 1. Тренд
    is_trend_up = latest['EMA_fast'] > latest['EMA_slow']
    if is_trend_up:
        long_score += 1; long_factors.append("Bullish Trend")
    else:
        short_score += 1; short_factors.append("Bearish Trend")
    
    # 2. RSI
    if latest['RSI'] > 52:
        long_score += 1; long_factors.append("Momentum (RSI more than 52)")
    if latest['RSI'] < 48:
        short_score += 1; short_factors.append("Momentum (RSI less than 48)")
    
    # 3. Объем
    volume_z = latest.get('volume_z', 0)
    
    # 4. Импульс
    if len(df) > 11:
        recent_avg_volume = df['volume'].iloc[-11:-1].mean()
        if latest['volume'] > recent_avg_volume * 2.0:
            impulse_msg = "Volume Impulse"
            if is_trend_up: long_score += 1.5; long_factors.append(impulse_msg)
            else: short_score += 1.5; short_factors.append(impulse_msg)
        elif volume_z > 0:
             if is_trend_up: long_score += 0.5
             else: short_score += 0.5

    # 5. Bollinger Bands
    if latest.get('BB_width', 0) > df['BB_width'].rolling(50).mean().iloc[-1]:
         if is_trend_up: long_score += 0.5
         else: short_score += 0.5

    current_price = latest['close']
    
    # Определение направления
    if long_score > short_score:
        view = "long"
        notes = "Key factors: " + ", ".join(long_factors) + "."
        stop = current_price - 1.8 * latest['ATR']
        target1 = current_price + 2.2 * latest['ATR']
        reasoning = "Bullish trend with supportive indicators"
    else:
        view = "short"
        notes = "Key factors: " + ", ".join(short_factors) + "."
        stop = current_price + 1.8 * latest['ATR']
        target1 = current_price - 2.2 * latest['ATR']
        reasoning = "Bearish trend with supportive indicators"

    # Расчет риска
    risk_data = calculate_position_size(current_price, stop, target1, risk_settings['balance'], risk_settings['risk_pct'])
    
    trade_plan = {
        "symbol": symbol_ccxt.replace("/", ""),
        "timeframe": display_timeframe,
        "view": view,
        "strategy": "Impulse Analysis",
        "entry_zone": [format_price(current_price * 0.999), format_price(current_price * 1.001)],
        "stop": format_price(stop),
        "targets": [format_price(target1)],
        "confidence": min(0.9, 0.5 + max(long_score, short_score) * 0.1),
        "notes": notes
    }
    trade_plan.update(risk_data)
    
    context = {
        'trend': "Up" if is_trend_up else "Down",
        'rsi': f"{latest['RSI']:.2f}",
        'volume': f"Z-Score: {volume_z:.2f}",
        'final_scores': f"Long: {long_score:.1f} vs Short: {short_score:.1f}",
        'final_view': view,
        'reasoning': reasoning
    }
    
    return trade_plan, context

def generate_signal(df, symbol_ccxt: str, news_score: float, risk_settings: dict, timeframe="1h"):
    """
    Осторожная версия для API.
    """
    if df.empty or len(df) < 50: return None, None
    
    latest = df.iloc[-1]
    long_score, short_score = 0, 0
    long_factors, short_factors = [], []
    
    is_trend_up = latest['EMA_fast'] > latest['EMA_slow']
    if is_trend_up:
        long_score += 1; long_factors.append("Uptrend")
    else:
        short_score += 1; short_factors.append("Downtrend")

    if latest['RSI'] > 55:
        long_score += 1; long_factors.append(f"Bullish RSI")
    if latest['RSI'] < 45:
        short_score += 1; short_factors.append(f"Bearish RSI")

    volume_z = latest.get('volume_z', 0)
    if volume_z > 0.8:
        if is_trend_up: long_score += 1; long_factors.append("High Volume")
        else: short_score += 1; short_factors.append("High Volume")

    if latest.get('BB_width', 0) > df['BB_width'].rolling(50).mean().iloc[-1]:
        if is_trend_up: long_score += 0.5
        else: short_score += 0.5

    CONFIDENCE_THRESHOLD = 2.5
    current_price = latest['close']
    trade_plan = None
    
    # Контекст
    context = {
        'trend': "Up" if is_trend_up else "Down",
        'rsi': f"{latest['RSI']:.2f}",
        'volume': f"Z-Score: {volume_z:.2f}",
        'final_scores': f"Long: {long_score:.1f} vs Short: {short_score:.1f}"
    }

    if long_score >= CONFIDENCE_THRESHOLD and latest['RSI'] < 80:
        stop = current_price - 1.8 * latest['ATR']; target1 = current_price + 2.2 * latest['ATR']
        risk_data = calculate_position_size(current_price, stop, target1, risk_settings['balance'], risk_settings['risk_pct'])
        
        trade_plan = {
            "symbol": symbol_ccxt.replace("/", ""), "timeframe": timeframe, "view": "long",
            "entry_zone": [format_price(current_price), format_price(current_price * 1.002)],
            "stop": format_price(stop), "targets": [format_price(target1)],
            "notes": f"Confluence: " + ", ".join(long_factors) + "."
        }
        trade_plan.update(risk_data)
        context['final_view'] = "long"
        context['reasoning'] = "Strong bullish confluence"
        
    elif short_score >= CONFIDENCE_THRESHOLD and latest['RSI'] > 20:
        stop = current_price + 1.8 * latest['ATR']; target1 = current_price - 2.2 * latest['ATR']
        risk_data = calculate_position_size(current_price, stop, target1, risk_settings['balance'], risk_settings['risk_pct'])
        
        trade_plan = {
            "symbol": symbol_ccxt.replace("/", ""), "timeframe": timeframe, "view": "short",
            "entry_zone": [format_price(current_price * 0.998), format_price(current_price)],
            "stop": format_price(stop), "targets": [format_price(target1)],
            "notes": f"Confluence: " + ", ".join(short_factors) + "."
        }
        trade_plan.update(risk_data)
        context['final_view'] = "short"
        context['reasoning'] = "Strong bearish confluence"
    else:
        context['final_view'] = "neutral"
        metrics = {"Trend": 'Up' if is_trend_up else 'Down', "RSI": f"{latest['RSI']:.2f}", "Volume": f"{volume_z:.2f}"}
        trade_plan = {
            "symbol": symbol_ccxt.replace("/", ""), "timeframe": timeframe, "view": "neutral",
            "notes": f"No strong confluence found (Score L:{long_score:.1f}/S:{short_score:.1f}).",
            "metrics": metrics
        }

    return trade_plan, context