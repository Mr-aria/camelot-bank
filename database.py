import sqlite3
import random
from datetime import datetime
import os

DB_NAME = "camelot_bank.db"

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    
    # ... (بقیه جداول مثل قبل، بدون تغییر) ...
    # فقط برای اختصار، همان جداول قبلی را نگه دارید. اما اگر از قبل دارند، نیازی نیست.
    # مهم: مطمئن شوید جدول users دارید:
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER UNIQUE,
        username TEXT,
        real_name TEXT,
        camelot_name TEXT,
        national_id TEXT UNIQUE,
        role TEXT DEFAULT 'citizen',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # سایر جداول را نیز مشابه قبل ایجاد کنید (از فایل قبلی database.py)
    # ... (برای اختصار حذف شد، اما باید همه جداول باشند)
    
    conn.commit()
    conn.close()
    print("✅ دیتابیس آماده است.")

def get_user_by_telegram_id(telegram_id):
    """دریافت کاربر با آیدی تلگرام (حتماً integer)"""
    conn = get_db()
    c = conn.cursor()
    # تبدیل به int برای اطمینان
    try:
        tid = int(telegram_id)
    except:
        conn.close()
        return None
    c.execute('SELECT * FROM users WHERE telegram_id = ?', (tid,))
    user = c.fetchone()
    conn.close()
    return user

# بقیه توابع قبلی (generate_account_number, get_account_by_user_id, ...) را بدون تغییر نگه دارید.