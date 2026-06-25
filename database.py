import sqlite3
import random
from datetime import datetime, timedelta
import pytz
import jdatetime

DB_NAME = "camelot_bank.db"
TEHRAN_TZ = pytz.timezone('Asia/Tehran')

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
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
    
    # 12. loan_settings
    c.execute('''CREATE TABLE IF NOT EXISTS loan_settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')
    
    # 13. loan_payments
    c.execute('''CREATE TABLE IF NOT EXISTS loan_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        loan_id INTEGER,
        installment_number INTEGER,
        amount INTEGER,
        due_date TIMESTAMP,
        paid_date TIMESTAMP,
        fine INTEGER DEFAULT 0,
        credit_penalty INTEGER DEFAULT 0,
        status TEXT DEFAULT 'pending',
        FOREIGN KEY (loan_id) REFERENCES loans(id)
    )''')
    
    # 14. support_tickets
    c.execute('''CREATE TABLE IF NOT EXISTS support_tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        message TEXT,
        reply TEXT,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        replied_at TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')
    
    # 15. system_logs (جدول جدید برای ذخیره همه لاگ‌ها)
    c.execute('''CREATE TABLE IF NOT EXISTS system_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        log_type TEXT,
        title TEXT,
        content TEXT,
        actor_id INTEGER,
        target_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (actor_id) REFERENCES users(id),
        FOREIGN KEY (target_id) REFERENCES users(id)
    )''')
    
    # تنظیمات پیش‌فرض عمومی
    default_settings = [
        ('registration_bonus', '100'),
        ('transfer_fee_percent', '0'),
        ('transfer_fee_fixed', '0'),
        ('monthly_transfer_limit', '50000'),
        ('suspicious_limit', '30000'),
        ('welcome_message', 'درود👋\nخوش اومدین به بانک کملوت💰\n\nبرای انجام عملیات های بانکی خود، از منوی ربات استفاده کنید.'),
    ]
    for key, value in default_settings:
        c.execute('INSERT OR IGNORE INTO system_settings (key, value) VALUES (?, ?)', (key, value))
    
    loan_default_settings = [
        ('loan_min_amount', '1000'),
        ('loan_max_amount', '1000000'),
        ('loan_grace_period_days', '14'),
        ('loan_daily_fine_percent', '1'),
        ('loan_daily_credit_penalty', '1'),
        ('loan_min_credit_score_to_unblock', '300'),
        ('loan_delay_days_to_block', '30'),
        ('loan_interest_rate_percent', '5'),
        ('loan_early_payment_bonus_percent', '20'),
        ('loan_max_multiplier_turnover', '3'),
        ('loan_credit_score_divider', '10'),
        ('loan_default_installments', '6'),
        ('loan_enabled_for_citizens', '1'),
    ]
    for key, value in loan_default_settings:
        c.execute('INSERT OR IGNORE INTO loan_settings (key, value) VALUES (?, ?)', (key, value))
    
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

def get_loan_setting(key):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT value FROM loan_settings WHERE key = ?', (key,))
    row = c.fetchone()
    conn.close()
    return row['value'] if row else None

def set_loan_setting(key, value):
    conn = get_db()
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO loan_settings (key, value) VALUES (?, ?)', (key, value))
    conn.commit()
    conn.close()

def get_all_loan_settings():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT key, value FROM loan_settings')
    rows = c.fetchall()
    conn.close()
    return {row['key']: row['value'] for row in rows}

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
    now = datetime.now(TEHRAN_TZ)
    jnow = jdatetime.datetime.fromgregorian(datetime=now)
    date_part = jnow.strftime("%Y%m%d")
    random_part = random.randint(1000, 9999)
    return f"TX-{date_part}-{random_part}"

def log_audit(actor_id, action, target=None, details=None):
    conn = get_db()
    c = conn.cursor()
    c.execute('INSERT INTO audit_logs (actor_id, action, target, details) VALUES (?, ?, ?, ?)',
              (actor_id, action, target, details))
    conn.commit()
    conn.close()

# ---------- توابع سیستمی جدید ----------
def add_system_log(log_type, title, content, actor_id=None, target_id=None):
    """ذخیره یک لاگ در سیستم"""
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT INTO system_logs (log_type, title, content, actor_id, target_id)
        VALUES (?, ?, ?, ?, ?)
    ''', (log_type, title, content, actor_id, target_id))
    conn.commit()
    conn.close()

def get_system_logs(limit=50, offset=0, log_type=None):
    """دریافت لاگ‌های سیستم با صفحه‌بندی"""
    conn = get_db()
    c = conn.cursor()
    query = '''
        SELECT sl.*, 
               u1.camelot_name as actor_name, 
               u2.camelot_name as target_name
        FROM system_logs sl
        LEFT JOIN users u1 ON sl.actor_id = u1.id
        LEFT JOIN users u2 ON sl.target_id = u2.id
    '''
    params = []
    if log_type:
        query += ' WHERE sl.log_type = ?'
        params.append(log_type)
    query += ' ORDER BY sl.created_at DESC LIMIT ? OFFSET ?'
    params.extend([limit, offset])
    c.execute(query, params)
    logs = c.fetchall()
    
    # دریافت تعداد کل
    count_query = 'SELECT COUNT(*) FROM system_logs'
    if log_type:
        count_query += ' WHERE log_type = ?'
        c.execute(count_query, (log_type,))
    else:
        c.execute(count_query)
    total = c.fetchone()[0]
    conn.close()
    return logs, total

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

# ---------- توابع وام ----------
def get_active_loan(account_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM loans WHERE account_id = ? AND status IN ("active", "delayed")', (account_id,))
    loan = c.fetchone()
    conn.close()
    return loan

def create_loan(account_id, amount, installments, interest_rate):
    from utils import calculate_installments
    conn = get_db()
    c = conn.cursor()
    
    total_with_interest = amount + (amount * interest_rate / 100)
    installment_amount = total_with_interest // installments
    remainder = total_with_interest % installments
    
    c.execute('''INSERT INTO loans (account_id, amount, remaining_amount, interest, installments, paid_installments, status, due_date)
                 VALUES (?, ?, ?, ?, ?, 0, 'active', ?)''',
              (account_id, amount, total_with_interest, interest_rate, installments, datetime.now(TEHRAN_TZ)))
    loan_id = c.lastrowid
    
    grace_days = int(get_loan_setting('loan_grace_period_days') or 14)
    for i in range(installments):
        due_date = datetime.now(TEHRAN_TZ) + timedelta(days=grace_days * (i + 1))
        amt = installment_amount + (1 if i == installments - 1 else 0)
        c.execute('''INSERT INTO loan_payments (loan_id, installment_number, amount, due_date, status)
                     VALUES (?, ?, ?, ?, 'pending')''',
                  (loan_id, i + 1, amt, due_date))
    
    conn.commit()
    conn.close()
    return loan_id

def apply_loan_penalties(loan_id):
    conn = get_db()
    c = conn.cursor()
    
    c.execute('SELECT * FROM loans WHERE id = ?', (loan_id,))
    loan = c.fetchone()
    if not loan:
        conn.close()
        return
    
    c.execute('SELECT * FROM loan_payments WHERE loan_id = ? AND status = "pending" AND due_date < ?', 
              (loan_id, datetime.now(TEHRAN_TZ)))
    payments = c.fetchall()
    
    daily_fine_percent = int(get_loan_setting('loan_daily_fine_percent') or 1)
    daily_credit_penalty = int(get_loan_setting('loan_daily_credit_penalty') or 1)
    
    total_fine = 0
    total_credit_penalty = 0
    
    for payment in payments:
        due = datetime.strptime(payment['due_date'], '%Y-%m-%d %H:%M:%S.%f')
        now = datetime.now(TEHRAN_TZ)
        if now > due:
            delay_days = (now - due).days
            if delay_days > 0:
                fine = (payment['amount'] * daily_fine_percent // 100) * delay_days
                credit_penalty = daily_credit_penalty * delay_days
                total_fine += fine
                total_credit_penalty += credit_penalty
                c.execute('UPDATE loan_payments SET fine = ?, credit_penalty = ? WHERE id = ?', 
                          (fine, credit_penalty, payment['id']))
    
    if total_fine > 0:
        c.execute('UPDATE loans SET fine = fine + ? WHERE id = ?', (total_fine, loan_id))
    
    conn.commit()
    conn.close()
    
    if total_credit_penalty > 0:
        c = conn.cursor()
        c.execute('SELECT credit_score, user_id FROM accounts WHERE id = ?', (loan['account_id'],))
        acc = c.fetchone()
        if acc:
            new_score = acc['credit_score'] - total_credit_penalty
            if new_score < 0:
                new_score = 0
            c.execute('UPDATE accounts SET credit_score = ? WHERE id = ?', (new_score, loan['account_id']))
            c.execute('INSERT INTO credit_history (account_id, old_score, new_score, reason) VALUES (?, ?, ?, ?)',
                      (loan['account_id'], acc['credit_score'], new_score, f'جریمه تأخیر وام {loan_id}'))
            conn.commit()
        conn.close()
    
    return total_fine, total_credit_penalty

# ---------- توابع تراکنش ----------
def get_user_transactions(user_id, limit=20, offset=0, tx_type=None):
    conn = get_db()
    c = conn.cursor()
    
    acc = get_account_by_user_id(user_id)
    if not acc:
        conn.close()
        return [], 0
    
    account_number = acc['account_number']
    
    query = '''
        SELECT * FROM transactions 
        WHERE sender_account = ? OR receiver_account = ?
    '''
    params = [account_number, account_number]
    
    if tx_type:
        query += ' AND type = ?'
        params.append(tx_type)
    
    count_query = query.replace('*', 'COUNT(*)')
    c.execute(count_query, params)
    total = c.fetchone()[0]
    
    query += ' ORDER BY created_at DESC LIMIT ? OFFSET ?'
    params.extend([limit, offset])
    c.execute(query, params)
    transactions = c.fetchall()
    
    conn.close()
    return transactions, total

def get_transaction_details(txid):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM transactions WHERE txid = ?', (txid,))
    tx = c.fetchone()
    conn.close()
    return tx