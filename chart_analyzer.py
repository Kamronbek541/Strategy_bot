# import cv2
# import numpy as np
# import pytesseract
# import base64
# import json
# import re
# from openai import OpenAI
# from dotenv import load_dotenv
# import os

# load_dotenv()
# OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


# def analyze_chart_with_gpt(image_path: str) -> dict | None:
#     if not client:
#         return None

#     try:
#         with open(image_path, "rb") as image_file:
#             base64_image = base64.b64encode(image_file.read()).decode('utf-8')
        
#         response = client.chat.completions.create(
#             model="gpt-4o",
#             response_format={"type": "json_object"},
#             messages=[
#                 {
#                     "role": "system",
#                     "content": "You are a helpful assistant designed to extract information from cryptocurrency charts and output it in JSON format."
#                 },
#                 {
#                     "role": "user",
#                     "content": [
#                         {
#                             "type": "text", 
#                             "text": "Analyze this chart image and extract the ticker symbol  and the timeframe. For the timeframe, use formats like '15m', '1h', '4h', '1D'. For the ticker respond with ONLY the ticker symbol which is availavble on Binance  Respond with a JSON object containing 'ticker' and 'timeframe' keys. And respond not immediatly but after 15 sec"
#                         },
#                         {
#                             "type": "image_url",
#                             "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
#                         }
#                     ]
#                 }
#             ],
#             max_tokens=50,
#         )

#         response_text = response.choices[0].message.content
#         print(f"GPT-4 Vision Raw JSON response: {response_text}")
        
#         data = json.loads(response_text)
#         ticker = data.get('ticker', '').upper().replace('/', '')
#         timeframe = data.get('timeframe', '15m').lower() # По умолчанию 15м
        
#         if not ticker:
#             return None
            
#         result = {"ticker": ticker, "timeframe": timeframe}
#         print(f"GPT-4 Vision identified: {result}")
#         return result
        
#     except Exception as e:
#         print(f"Error during GPT-4 Vision analysis: {e}")
#         return None


# def find_candlesticks(image_path: str):
#     chart_info = analyze_chart_with_gpt(image_path)
#     image = cv2.imread(image_path)
#     if image is None: return [], chart_info
    
#     hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
#     lower_red1 = np.array([0, 100, 100]); upper_red1 = np.array([10, 255, 255])
#     lower_red2 = np.array([160, 100, 100]); upper_red2 = np.array([180, 255, 255])
#     red_mask = cv2.bitwise_or(cv2.inRange(hsv, lower_red1, upper_red1), cv2.inRange(hsv, lower_red2, upper_red2))
#     lower_green = np.array([40, 50, 50]); upper_green = np.array([80, 255, 255])
#     green_mask = cv2.inRange(hsv, lower_green, upper_green)
#     combined_mask = cv2.bitwise_or(red_mask, green_mask)
#     contours, _ = cv2.findContours(combined_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
#     candlesticks = []
#     for cnt in contours:
#         x, y, w, h = cv2.boundingRect(cnt)
#         if h > 5 and w > 1 and h / w > 1.2 and w < 30:
#             candlesticks.append({"body_x": x, "body_y": y, "body_w": w, "body_h": h})
#     candlesticks.sort(key=lambda c: c["body_x"])
#     print(f"Found {len(candlesticks)} potential candlesticks.")
#     return candlesticks, chart_info

# def candlesticks_to_ohlc(candlesticks: list):
#     if not candlesticks: 
#         return []
    
#     all_lows = [c.get('low') for c in candlesticks]
#     all_highs = [c.get('high') for c in candlesticks]
#     min_low = min(all_lows)
#     max_high = max(all_highs)
#     price_range = max_high - min_low
    
#     if price_range == 0: 
#         return []
    
#     ohlc_data = []
#     for c in candlesticks:
#         high = c.get('high')
#         low = c.get('low')
        
#         high_norm = 1 - (high - min_low) / price_range
#         low_norm = 1 - (low - min_low) / price_range
        
#         if c['color'] == 'green':
#             open_norm = 1 - ((c['body_y'] + c['body_h']) - min_low) / price_range
#             close_norm = 1 - (c['body_y'] - min_low) / price_range
#         else:
#             open_norm = 1 - (c['body_y'] - min_low) / price_range
#             close_norm = 1 - ((c['body_y'] + c['body_h']) - min_low) / price_range
            
#         ohlc_data.append({
#             'open': open_norm, 
#             'high': high_norm, 
#             'low': low_norm, 
#             'close': close_norm
#         })
    
#     return ohlc_data



# chart_analyzer.py (v-OpenRouter - Correct Headers)
import cv2
import numpy as np
import base64
import json
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Настраиваем клиент с правильными заголовками твоего бота
if OPENROUTER_API_KEY:
    client = OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=OPENROUTER_API_KEY,
        default_headers={
            "HTTP-Referer": "https://t.me/BlackAladinBot", # Твой бот
            "X-Title": "BlackAladin",
        }
    )
else:
    client = None

def analyze_chart_with_gpt(image_path: str) -> dict | None:
    """Использует GPT-4o через OpenRouter для распознавания тикера."""
    if not client:
        print("WARNING: OpenRouter API key not found.")
        return None

    try:
        with open(image_path, "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode('utf-8')

        print("--- Sending image to OpenRouter (GPT-4o) ---")
        
        response = client.chat.completions.create(
            # Используем GPT-4o через OpenRouter
            model="openai/gpt-4o-2024-08-06", 
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": "You are a crypto chart analyzer. Output JSON only."
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text", 
                            "text": "Identify the ticker symbol (e.g. BTCUSDT) and timeframe (e.g. 15m) from this chart. Return JSON with keys 'ticker' and 'timeframe'."
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
                        }
                    ]
                }
            ],
            max_tokens=100,
        )

        response_text = response.choices[0].message.content
        print(f"OpenRouter Raw JSON: {response_text}")
        
        data = json.loads(response_text)
        ticker = data.get('ticker', '').upper().replace('/', '')
        timeframe = data.get('timeframe', '15m').lower()
        
        if not ticker: return None
            
        result = {"ticker": ticker, "timeframe": timeframe}
        print(f"AI identified: {result}")
        return result
        
    except Exception as e:
        print(f"Error during OpenRouter Vision analysis: {e}")
        return None

def find_candlesticks(image_path: str):
    """Гибридный метод."""
    # 1. Спрашиваем AI
    chart_info = analyze_chart_with_gpt(image_path)
    
    # 2. Ищем свечи (для подстраховки)
    image = cv2.imread(image_path)
    if image is None: return [], chart_info
    
    # Стандартная CV логика для поиска свечей
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    lower_red1 = np.array([0, 100, 100]); upper_red1 = np.array([10, 255, 255])
    lower_red2 = np.array([160, 100, 100]); upper_red2 = np.array([180, 255, 255])
    red_mask = cv2.bitwise_or(cv2.inRange(hsv, lower_red1, upper_red1), cv2.inRange(hsv, lower_red2, upper_red2))
    lower_green = np.array([40, 50, 50]); upper_green = np.array([80, 255, 255])
    green_mask = cv2.inRange(hsv, lower_green, upper_green)
    combined_mask = cv2.bitwise_or(red_mask, green_mask)
    contours, _ = cv2.findContours(combined_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candlesticks = []
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if h > 5 and w > 1 and h / w > 1.2 and w < 30:
            candlesticks.append({"body_x": x, "body_y": y, "body_w": w, "body_h": h})
    
    candlesticks.sort(key=lambda c: c["body_x"])
    print(f"Found {len(candlesticks)} potential candlesticks.")
    return candlesticks, chart_info

def candlesticks_to_ohlc(candlesticks: list):
    if not candlesticks: return []
    all_lows = [c.get('low', c['body_y'] + c['body_h']) for c in candlesticks]
    all_highs = [c.get('high', c['body_y']) for c in candlesticks]
    min_low = min(all_lows); max_high = max(all_highs); price_range = max_high - min_low
    if price_range == 0: return []
    ohlc_data = []
    for c in candlesticks:
        high = c.get('high', c['body_y']); low = c.get('low', c['body_y'] + c['body_h'])
        high_norm = 1 - (high - min_low) / price_range; low_norm = 1 - (low - min_low) / price_range
        if c['color'] == 'green': open_norm = 1 - ((c['body_y'] + c['body_h']) - min_low) / price_range; close_norm = 1 - (c['body_y'] - min_low) / price_range
        else: open_norm = 1 - (c['body_y'] - min_low) / price_range; close_norm = 1 - ((c['body_y'] + c['body_h']) - min_low) / price_range
        ohlc_data.append({'open': open_norm, 'high': high_norm, 'low': low_norm, 'close': close_norm})
    return ohlc_data