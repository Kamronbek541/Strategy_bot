# webhook_server.py
import os
from fastapi import FastAPI, Request, Header
from dotenv import load_dotenv
import hmac
import hashlib
import json
from telegram import Bot
import asyncio

from database import activate_user

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
NOWPAYMENTS_IPN_SECRET = os.getenv("NOWPAYMENTS_IPN_SECRET")

app = FastAPI()
bot = Bot(token=TELEGRAM_TOKEN)

@app.post("/ipn_webhook")
async def handle_nowpayments_webhook(request: Request, x_nowpayments_sig: str = Header(None)):
    """Принимает уведомления от NOWPayments."""
    if not x_nowpayments_sig:
        print("Webhook error: No signature header")
        return {"status": "error", "message": "No signature"}

    body = await request.body()
    
    # 1. Проверяем подпись, чтобы убедиться, что это пришло от NOWPayments
    try:
        h = hmac.new(NOWPAYMENTS_IPN_SECRET.encode(), body, hashlib.sha512)
        signature = h.hexdigest()
        if signature != x_nowpayments_sig:
            print("Webhook error: Invalid signature")
            return {"status": "error", "message": "Invalid signature"}
    except Exception as e:
        print(f"Signature verification failed: {e}")
        return {"status": "error", "message": "Signature verification failed"}

    # 2. Если подпись верна, обрабатываем данные
    data = json.loads(body)
    payment_status = data.get("payment_status")
    order_id = data.get("order_id") # Мы сюда будем записывать user_id

    print(f"Received webhook for order {order_id} with status: {payment_status}")

    if payment_status == "finished":
        try:
            user_id = int(order_id)
            # 3. Активируем пользователя в базе
            activate_user(user_id)
            
            # 4. Отправляем ему сообщение об успехе
            success_message = "✅ Payment successful!\n\nWelcome to Aladdin! You can now use all my features. Press 'Analyze Chart 📈' to begin."
            await bot.send_message(chat_id=user_id, text=success_message)
            
            return {"status": "success"}
        except (ValueError, TypeError):
            print(f"Invalid order_id (user_id) received: {order_id}")
            return {"status": "error", "message": "Invalid order_id"}
            
    return {"status": "pending or failed"}

print("Webhook server is ready. Run with: uvicorn webhook_server:app --host 0.0.0.0 --port 8000")