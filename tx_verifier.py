from web3 import Web3
import json
import sqlite3
from database import DB_NAME, execute_write_query
from datetime import datetime

# --- CONFIG ---
BSC_RPC = "https://bsc-dataseed.binance.org/"
TARGET_ADDRESS = "0x6c639cac616254232d9c4d51b1c3646132b46c4a".lower()
USDT_CONTRACT = "0x55d398326f99059fF775485246999027B3197955".lower()
USDT_ABI = json.loads('[{"anonymous":false,"inputs":[{"indexed":true,"internalType":"address","name":"from","type":"address"},{"indexed":true,"internalType":"address","name":"to","type":"address"},{"indexed":false,"internalType":"uint256","name":"value","type":"uint256"}],"name":"Transfer","type":"event"}]')

w3 = Web3(Web3.HTTPProvider(BSC_RPC))

def verify_bsc_tx(tx_hash: str, user_id: int):
    """
    Verifies a BSC transaction for Top Up.
    Returns: (bool, float/str) -> (Success, Amount or Error Message)
    """
    try:
        tx_hash = tx_hash.strip()
        
        # 1. Check if Tx already processed
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM transactions WHERE tx_hash = ?", (tx_hash,))
        exists = cursor.fetchone()
        conn.close()
        
        if exists:
            return False, "Transaction already used/processed."
        
        # 2. Get Transaction Receipt
        try:
            receipt = w3.eth.get_transaction_receipt(tx_hash)
        except Exception:
            return False, "Transaction not found on BSC (check Hash)."

        if receipt['status'] != 1:
            return False, "Transaction Failed/Reverted."
            
        # 3. Parse Logs for Transfer Event
        contract = w3.eth.contract(address=Web3.to_checksum_address(USDT_CONTRACT), abi=USDT_ABI)
        
        transfer_found = False
        amount = 0.0
        
        # We need to find the log that transfers TO our address
        for log in receipt['logs']:
            if log['address'].lower() == USDT_CONTRACT:
                try:
                    event = contract.events.Transfer().process_log(log)
                    to_addr = event['args']['to'].lower()
                    value = event['args']['value']
                    
                    if to_addr == TARGET_ADDRESS:
                        # Found it!
                        transfer_found = True
                        amount = float(value) / 10**18 # USDT has 18 decimals on BSC
                        from_addr = event['args']['from']
                        break
                except: continue

        if not transfer_found:
            return False, "Transaction does not contain USDT transfer to Target Address."

        if amount <= 0:
             return False, "Invalid Amount."

        # 4. Success! Record in DB
        execute_write_query("""
            INSERT INTO transactions (tx_hash, user_id, amount, currency, from_address, status, created_at)
            VALUES (?, ?, ?, 'USDT', ?, 'success', ?)
        """, (tx_hash, user_id, amount, from_addr, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        
        # 5. Credit User
        execute_write_query("UPDATE users SET token_balance = token_balance + ? WHERE user_id = ?", (amount, user_id))
        
        return True, amount

    except Exception as e:
        print(f"Verify Error: {e}")
        return False, f"Verification Error: {str(e)}"
