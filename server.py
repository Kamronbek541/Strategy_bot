from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import asyncio
import os
from database import get_user_exchanges, get_user_decrypted_keys, get_user_language, save_user_language, execute_write_query
from exchange_utils import fetch_exchange_balance_safe, validate_exchange_credentials
from tx_verifier import verify_bsc_tx
import sqlite3
from database import DB_NAME

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- MODELS ---
class ConnectRequest(BaseModel):
    user_id: int
    exchange: str
    api_key: str
    secret: str
    password: str = None
    strategy: str = 'ratner'
    reserve: float = 0.0

class LanguageRequest(BaseModel):
    user_id: int
    language: str

class ReserveRequest(BaseModel):
    user_id: int
    exchange: str
    reserve: float

class TopUpRequest(BaseModel):
    user_id: int
    tx_id: str

# --- API ---

@app.get("/api/data")
async def get_user_data(user_id: int):
    """Returns total balance, connected exchanges list, current language, and internal token balance."""
    exchanges = get_user_exchanges(user_id)
    language = get_user_language(user_id)
    
    # Get internal token balance
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT token_balance FROM users WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    token_balance = res[0] if res else 0.0
    conn.close()
    
    total_balance = 0.0
    ex_list = []
    
    # Process exchanges concurrently? For simplicity loop (concurrent better)
    tasks = []
    
    for ex in exchanges:
        keys = get_user_decrypted_keys(user_id, ex['exchange_name'])
        if keys:
            tasks.append(
                fetch_exchange_balance_safe(
                    ex['exchange_name'], 
                    keys['apiKey'], 
                    keys['secret'], 
                    keys['password']
                )
            )
        else:
            tasks.append(asyncio.sleep(0, result=None)) # Dummy

    # Run all fetches
    if tasks:
        results = await asyncio.gather(*tasks)
    else:
        results = []

    for i, ex in enumerate(exchanges):
        bal = results[i]
        status = "Connected" if bal is not None else "Error"
        if not ex['is_active']: status = "Disconnected"
        
        real_bal = bal if bal is not None else 0.0
        if status == "Connected":
            total_balance += real_bal
            
        ex_list.append({
            "name": ex['exchange_name'].capitalize(),
            "status": status,
            "balance": real_bal,
            "icon": get_icon(ex['exchange_name']),
            "strategy": ex['strategy'],
            "reserve": ex['reserved_amount']
        })
        
    return {
        "totalBalance": total_balance,
        "pnl": "+0.0%", # Todo: calculate PnL
        "exchanges": ex_list,
        "language": language,
        "credits": token_balance
    }

@app.post("/api/topup")
async def top_up(req: TopUpRequest):
    success, result = verify_bsc_tx(req.tx_id, req.user_id)
    if success:
        return {"status": "ok", "msg": f"Successfully credited {result} USDT", "amount": result}
    else:
        raise HTTPException(status_code=400, detail=result)

@app.post("/api/language")
async def set_language(req: LanguageRequest):
    save_user_language(req.user_id, req.language)
    return {"status": "ok"}

@app.post("/api/reserve")
async def set_reserve(req: ReserveRequest):
    try:
        execute_write_query("""
            UPDATE user_exchanges 
            SET reserved_amount = ? 
            WHERE user_id = ? AND exchange_name = ?
        """, (req.reserve, req.user_id, req.exchange.lower()))
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/connect")
async def connect_exchange(req: ConnectRequest):
    # 1. Validate
    is_valid = await validate_exchange_credentials(req.exchange, req.api_key, req.secret, req.password)
    if not is_valid:
        raise HTTPException(status_code=400, detail="Invalid API Keys or Connection Failed")
    
    # 2. Save to DB
    try:
        from database import encrypt_data
        
        enc_secret = encrypt_data(req.secret)
        enc_pass = encrypt_data(req.password) if req.password else None
        
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Insert or Replace
        cursor.execute("""
            INSERT INTO user_exchanges (user_id, exchange_name, api_key, api_secret_encrypted, passphrase_encrypted, strategy, reserved_amount, is_active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, datetime('now'))
            ON CONFLICT(user_id, exchange_name) DO UPDATE SET
            api_key=excluded.api_key,
            api_secret_encrypted=excluded.api_secret_encrypted,
            passphrase_encrypted=excluded.passphrase_encrypted,
            strategy=excluded.strategy,
            reserved_amount=excluded.reserved_amount,
            is_active=1
        """, (req.user_id, req.exchange.lower(), req.api_key, enc_secret, enc_pass, req.strategy, req.reserve))
        
        conn.commit()
        conn.close()
        
        return {"status": "ok", "msg": "Exchange connected successfully"}
    except Exception as e:
        print(f"DB Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def get_icon(name):
    name = name.lower()
    if 'binance' in name: return "🔸"
    if 'okx' in name: return "⚫"
    if 'bingx' in name: return "🟦"
    if 'bybit' in name: return "⬛"
    return "🔹"

# --- STATIC FILES ---
# Mount webapp to root
app.mount("/", StaticFiles(directory="webapp", html=True), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
