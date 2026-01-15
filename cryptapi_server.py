from flask import Flask, request, jsonify
from database import credit_tokens_from_payment, get_text
import os
import asyncio
from telegram import Bot
from telegram.constants import ParseMode

# Загружаем переменные, чтобы получить доступ к токену бота
from dotenv import load_dotenv
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
# ... другие импорты, если нужны (например, telegram.Bot) ...

app = Flask(__name__)

@app.route('/cryptapi_webhook', methods=['GET', 'POST'])
def handle_webhook():
    # 1. Получаем данные (CryptAPI может слать GET или POST)
    data = request.args.to_dict()
    
    print("Received Webhook from CryptAPI:", data)

    # 2. Проверка безопасности
    if data.get('secret') != 'SOME_SECRET_WORD_TO_VALIDATE':
        return 'error: invalid secret', 403
        
    try:
        # 3. Извлекаем данные
        user_id = int(data.get('user_id'))
        amount = float(data.get('value_coin'))
        txid = data.get('txid_in')
        
        # (Опционально) Проверка, что мы еще не обрабатывали эту транзакцию
        # if is_tx_hash_used(txid): return "*ok*"
        
        # 4. Пополняем баланс в БД
        credit_tokens_from_payment(user_id, amount)
        
        # 5. Отправляем уведомление юзеру
        try:
            bot = Bot(token=TELEGRAM_TOKEN)
            msg = get_text(user_id, "msg_payment_received_notification", amount=amount)
            # Flask is sync, passing async call to event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(bot.send_message(chat_id=user_id, text=msg, parse_mode=ParseMode.HTML))
            loop.close()
            print(f"Notification sent to user {user_id}")
        except Exception as notify_error:
             print(f"Failed to send notification: {notify_error}")
        
        # 6. Отвечаем CryptAPI
        return '*ok*'
        
    except Exception as e:
        print(f"Webhook processing error: {e}")
        return 'error', 500

if __name__ == '__main__':
    # Запускаем на порту 8080 (тот же, что и в ngrok)
    app.run(host='0.0.0.0', port=8080)
