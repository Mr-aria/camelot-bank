import sqlite3
import random
from datetime import datetime, timedelta

DB_NAME = "camelot_bank.db"

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    
    # 1. users
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
    
    # 2. accounts
    c.execute('''CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        account_number TEXT UNIQUE,
        password TEXT,
        balance INTEGER DEFAULT 0,
        blocked_balance INTEGER DEFAULT 0,
        credit_score INTEGER DEFAULT 1000,
        status TEXT DEFAULT 'active',
        monthly_transfer_used INTEGER DEFAULT 0,
        notes TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')
    
    # 3. transactions
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        txid TEXT UNIQUE,
        sender_account TEXT,
        receiver_account TEXT,
        amount INTEGER,
        fee INTEGER DEFAULT 0,
        reason TEXT,
        type TEXT,
        status TEXT DEFAULT 'success',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # 4. loans
    c.execute('''CREATE TABLE IF NOT EXISTS loans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER,
        amount INTEGER,
        remaining_amount INTEGER,
        interest INTEGER DEFAULT 0,
        fine INTEGER DEFAULT 0,
        installments INTEGER,
        paid_installments INTEGER DEFAULT 0,
        status TEXT DEFAULT 'active',
        due_date TIMESTAMP,
        FOREIGN KEY (account_id) REFERENCES accounts(id)
    )''')
    
    # 5. credit_history
    c.execute('''CREATE TABLE IF NOT EXISTS credit_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER,
        old_score INTEGER,
        new_score INTEGER,
        reason TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # 6. notifications
    c.execute('''CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        title TEXT,
        message TEXT,
        is_read INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # 7. admin_requests
    c.execute('''CREATE TABLE IF NOT EXISTS admin_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        type TEXT,
        data TEXT,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # 8. audit_logs
    c.execute('''CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        actor_id INTEGER,
        action TEXT,
        target TEXT,
        details TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # 9. manager_pins
    c.execute('''CREATE TABLE IF NOT EXISTS manager_pins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE,
        pin TEXT,
        last_login TIMESTAMP,
        failed_attempts INTEGER DEFAULT 0,
        locked_until TIMESTAMP,
        session_expires TIMESTAMP
    )''')
    
    # 10. system_settings
    c.execute('''CREATE TABLE IF NOT EXISTS system_settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')
    
    # 11. treasury_log
    c.execute('''CREATE TABLE IF NOT EXISTS treasury_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action TEXT,
        amount INTEGER,
        reason TEXT,
        created_by INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # تنظیمات پیش‌فرض
    default_settings = [
        ('registration_bonus', '100'),
        ('transfer_fee_percent', '0'),
        ('transfer_fee_fixed', '0'),
        ('monthly_transfer_limit', '50000'),
        ('suspicious_limit', '30000'),
        ('loan_interest', '5'),
        ('loan_fine', '2'),
        ('loan_min_score', '500'),
        ('welcome_message', 'درود👋\nخوش اومدین به بانک کملوت💰\n\nبرای انجام عملیات های بانکی خود، از منوی ربات استفاده کنید.'),
    ]
    for key, value in default_settings:
        c.execute('INSERT OR IGNORE INTO system_settings (key, value) VALUES (?, ?)', (key, value))
    
    conn.commit()
    conn.close()
    print("✅ دیتابیس بانک کملوت با موفقیت ساخته شد")

# ---------- توابع کمکی ----------
def get_setting(key):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT value FROM system_settings WHERE key = ?', (key,))
    row = c.fetchone()
    conn.close()
    return row['value'] if row else None

def set_setting(key, value):
    conn = get_db()
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)', (key, value))
    conn.commit()
    conn.close()

def generate_account_number():
    conn = get_db()
    c = conn.cursor()
    while True:
        acc_num = str(random.randint(100000, 999999))
        c.execute('SELECT id FROM accounts WHERE account_number = ?', (acc_num,))
        if not c.fetchone():
            conn.close()
            return acc_num

def generate_txid():
    now = datetime.now()
    date_part = now.strftime("%Y%m%d")
    random_part = random.randint(1000, 9999)
    return f"TX-{date_part}-{random_part}"

def log_audit(actor_id, action, target=None, details=None):
    conn = get_db()
    c = conn.cursor()
    c.execute('INSERT INTO audit_logs (actor_id, action, target, details) VALUES (?, ?, ?, ?)',
              (actor_id, action, target, details))
    conn.commit()
    conn.close()

# ---------- توابع دریافت اطلاعات ----------
def get_user_by_telegram_id(telegram_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,))
    user = c.fetchone()
    conn.close()
    return user

def get_account_by_user_id(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM accounts WHERE user_id = ?', (user_id,))
    acc = c.fetchone()
    conn.close()
    return acc

def get_account_by_number(acc_num):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM accounts WHERE account_number = ?', (acc_num,))
    acc = c.fetchone()
    conn.close()
    return acc

def get_user_by_account_number(acc_num):
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT u.* FROM users u
        JOIN accounts a ON u.id = a.user_id
        WHERE a.account_number = ?
    ''', (acc_num,))
    user = c.fetchone()
    conn.close()
    return user

def get_balance(account_number):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT balance, blocked_balance FROM accounts WHERE account_number = ?', (account_number,))
    row = c.fetchone()
    conn.close()
    if row:
        return row['balance'], row['blocked_balance']
    return 0, 0

def send_notification(user_id, title, message):
    conn = get_db()
    c = conn.cursor()
    c.execute('INSERT INTO notifications (user_id, title, message) VALUES (?, ?, ?)',
              (user_id, title, message))
    conn.commit()
    conn.close()