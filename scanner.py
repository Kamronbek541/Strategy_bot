# scanner.py (v4 - Final, Corrected Version)

import os
import time
import asyncio
from dotenv import load_dotenv
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

# Импортируем НУЖНЫЕ функции из нашего обновленного "мозга"
from core_analyzer import fetch_data, compute_features, generate_signal, get_general_market_sentiment
from bot import format_plan_to_message
from database import get_all_user_ids

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

ASSETS_TO_SCAN = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT", "BNB/USDT", "AVAX/USDT", "LINK/USDT", "MATIC/USDT", "PEPE/USDT"]
SCAN_INTERVAL_SECONDS = 60 * 60 * 2  # 2 часа
TIMEFRAME = "1h"

async def scan_market_and_notify(bot: Bot):
    print(f"--- Running market scan at {time.ctime()} ---")
    
    # ШАГ 1: Получаем настроение рынка ОДИН РАЗ
    market_sentiment = get_general_market_sentiment()
    print(f"General Market Sentiment (LLM): {market_sentiment:.2f}")

    all_signals = []
    for asset in ASSETS_TO_SCAN:
        try:
            print(f"Scanning {asset}...")
            ohlcv = fetch_data(symbol=asset, timeframe=TIMEFRAME)
            if ohlcv.empty:
                continue
            
            features = compute_features(ohlcv)
            # ШАГ 2: Передаем уже полученное настроение в функцию
            signal_plan = generate_signal(features, symbol_ccxt=asset, news_score=market_sentiment, timeframe=TIMEFRAME)
            all_signals.append(signal_plan)
            await asyncio.sleep(2)
        except Exception as e:
            print(f"Error scanning {asset}: {e}")
            
    # Отбираем и сортируем сигналы
    found_ideas = sorted([s for s in all_signals if s.get("view") in ["long", "short"]], key=lambda x: x.get('confidence', 0), reverse=True)
    
    user_ids = get_all_user_ids()
    if not user_ids:
        print("No users in the database to notify.")
        return

    print(f"Found {len(found_ideas)} actionable ideas. Notifying {len(user_ids)} users...")

    if not found_ideas:
        message_text = "🧞‍♂️ **Strategy Bot Market Scan | No setups**\n\nNo high-quality trade setups found in the last scan. The market is consolidating."
    else:
        header = f"🧞‍♂️ **Strategy Bot Market Scan | Top {len(found_ideas)} Ideas**\n\n"
        idea_messages = [format_plan_to_message(idea) for idea in found_ideas]
        message_text = header + "\n\n---\n\n".join(idea_messages)

    # Рассылка
    for user_id in user_ids:
        try:
            await bot.send_message(chat_id=user_id, text=message_text, parse_mode=ParseMode.HTML)
            print(f"Successfully sent notification to {user_id}")
        except TelegramError as e:
            print(f"Failed to send to {user_id}. Reason: {e}")
        await asyncio.sleep(0.1)

async def main():
    if not TELEGRAM_TOKEN:
        print("Error: TELEGRAM_TOKEN must be set.")
        return
        
    # --- ИСПРАВЛЕНИЕ: Простой и надежный способ создать бота ---
    bot = Bot(token=TELEGRAM_TOKEN)

    while True:
        await scan_market_and_notify(bot)
        print(f"Scan finished. Sleeping for {SCAN_INTERVAL_SECONDS / 3600} hours.")
        await asyncio.sleep(SCAN_INTERVAL_SECONDS)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Scanner stopped manually.")