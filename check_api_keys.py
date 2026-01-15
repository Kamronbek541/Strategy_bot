import os
import time
import hmac
import hashlib
import json
from urllib.parse import urlencode

import requests
from binance.um_futures import UMFutures
from pybit.unified_trading import HTTP as BybitHTTP
from dotenv import load_dotenv

load_dotenv()


def check_binance():
    print("\n=== BINANCE FUTURES TEST ===")
    key = os.getenv("BINANCE_MASTER_KEY")
    secret = os.getenv("BINANCE_MASTER_SECRET")

    if not key or not secret:
        print("⛔ BINANCE: Нет ключей в .env")
        return

    try:
        client = UMFutures(
            key=key,
            secret=secret,
            base_url="https://testnet.binancefuture.com"
        )
        # простой приватный запрос – инфо по аккаунту
        account = client.account()
        if "canTrade" in account:
            print("✅ BINANCE: Ключи рабочие, приватный запрос прошёл.")
        else:
            print("⚠️ BINANCE: Ответ странный, но запрос прошёл:", account)
    except Exception as e:
        print(f"❌ BINANCE ERROR: {e}")


def check_bybit():
    print("\n=== BYBIT TEST ===")
    key = os.getenv("BYBIT_MASTER_KEY")
    secret = os.getenv("BYBIT_MASTER_SECRET")

    if not key or not secret:
        print("⛔ BYBIT: Нет ключей в .env")
        return

    try:
        # HTTP-клиент unified_trading (как в WebSocket)
        session = BybitHTTP(
            testnet=True,
            api_key=key,
            api_secret=secret,
        )
        # простой приватный запрос – балансы
        res = session.get_wallet_balance(accountType="UNIFIED")
        if res.get("retCode") == 0:
            print("✅ BYBIT: Ключи рабочие, приватный запрос прошёл.")
        else:
            print("⚠️ BYBIT: API ответило ошибкой:", res)
    except Exception as e:
        print(f"❌ BYBIT ERROR: {e}")


def bingx_sign(secret: str, params: dict) -> str:
    """HMAC SHA256 подпись для BingX (по строке query_string)."""
    query_string = urlencode(sorted(params.items()))
    signature = hmac.new(
        secret.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return signature, query_string


def check_bingx():
    """
    Проверка BingX USDT-M:
    - не через listenKey (там часто меняют пути),
    - а через простой приватный запрос по swap API,
      чтобы понять, что ключи/подпись ок.
    """
    print("\n=== BINGX TEST ===")
    key = os.getenv("BINGX_MASTER_KEY")
    secret = os.getenv("BINGX_MASTER_SECRET")

    if not key or not secret:
        print("⛔ BINGX: Нет ключей в .env")
        return

    # базовый URL для perp futures (swap)
    BASE_URL = "https://open-api.bingx.com"

    # пример: получить инфо по аккаунту USDT-M (перпетулы)
    # Эндпоинт может отличаться в зависимости от доки/версии.
    # Тут мы тестируем сам факт, что:
    #  - заголовок X-BX-APIKEY корректен
    #  - подпись проходит
    #  - и видим "правильную" ошибку (например, нет прав/тестнет и т.д.)
    path = "/openApi/swap/v2/user/balance"   # <--- если вернёт 100400, значит путь не существует

    timestamp = int(time.time() * 1000)
    params = {
        "timestamp": timestamp,
        # возможно ещё recvWindow, если нужно:
        # "recvWindow": 5000,
    }

    signature, query_string = bingx_sign(secret, params)

    url = f"{BASE_URL}{path}"
    final_url = f"{url}?{query_string}&signature={signature}"
    headers = {
        "X-BX-APIKEY": key
    }

    try:
        resp = requests.get(final_url, headers=headers)
        print("HTTP статус:", resp.status_code)
        print("RAW ответ:", resp.text)

        if resp.status_code != 200:
            print("❌ BINGX: HTTP ошибка, см. текст выше.")
            return

        data = resp.json()
        code = data.get("code")

        if code == 0:
            print("✅ BINGX: Ключи и подпись приняты, приватный запрос прошёл.")
        elif code == 100401:
            print("⛔ BINGX: Проблема с подписью/ключом (100401).")
        elif code == 100400:
            print("⛔ BINGX: 'this api is not exist' (100400) – путь эндпоинта неверный.")
            print("   Значит ключи могут быть ОК, но URL надо сверить с докой.")
        else:
            print(f"⚠️ BINGX: API вернуло код {code}: {data}")
    except Exception as e:
        print(f"❌ BINGX ERROR (requests): {e}")


def main():
    print("=== API KEYS CHECKER ===")
    check_binance()
    check_bybit()
    check_bingx()
    print("\nГотово. Смотри сообщения выше для каждой биржи.")


if __name__ == "__main__":
    main()
