
import sqlite3

DB_NAME = "aladdin_dev.db"

def migrate_db():
    print(f"🔄 Migrating {DB_NAME} (Ratner -> Bro-Bot)...")
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # 1. Update users table
        cursor.execute("UPDATE users SET selected_strategy = 'bro-bot' WHERE selected_strategy = 'ratner'")
        print(f"✅ Updated users table: {cursor.rowcount} rows affected.")
        
        # 2. Update user_exchanges table
        # Check if table has strategy column first (it should)
        cursor.execute("UPDATE user_exchanges SET strategy = 'bro-bot' WHERE strategy = 'ratner'")
        print(f"✅ Updated user_exchanges table: {cursor.rowcount} rows affected.")
        
        conn.commit()
        conn.close()
        print("🎉 Migration Complete.")
    except Exception as e:
        print(f"❌ Migration Failed: {e}")

if __name__ == "__main__":
    migrate_db()
