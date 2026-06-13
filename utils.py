from database import get_db, log_audit
from datetime import datetime

def create_bank_account(user_id, username, real_name, camelot_name, national_id, password):
    """ایجاد حساب بانکی جدید با username (برای ذخیره در دیتابیس)"""
    from database import generate_account_number, get_setting
    
    conn = get_db()
    c = conn.cursor()
    
    # اضافه کردن کاربر (با username)
    c.execute('''INSERT INTO users (telegram_id, username, real_name, camelot_name, national_id, role)
                 VALUES (?, ?, ?, ?, ?, 'citizen')''',
              (user_id, username, real_name, camelot_name, national_id))
    user_db_id = c.lastrowid
    
    # ساخت شماره حساب
    acc_num = generate_account_number()
    
    # موجودی اولیه
    bonus = int(get_setting('registration_bonus') or 0)
    
    # اضافه کردن حساب
    c.execute('''INSERT INTO accounts (user_id, account_number, password, balance, credit_score)
                 VALUES (?, ?, ?, ?, 1000)''',
              (user_db_id, acc_num, password, bonus))
    
    conn.commit()
    conn.close()
    
    log_audit(user_id, 'account_created', f'user_id:{user_db_id}', f'account:{acc_num}')
    return acc_num, bonus

def get_balance(account_number):
    from database import get_db
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT balance, blocked_balance FROM accounts WHERE account_number = ?', (account_number,))
    row = c.fetchone()
    conn.close()
    if row:
        return row['balance'], row['blocked_balance']
    return 0, 0

def format_balance(balance, blocked=0):
    usable = balance - blocked
    return f"""💰 موجودی حساب شما:
    
📊 موجودی کل: {balance} ART
🔒 موجودی بلوکه شده: {blocked} ART
✅ قابل برداشت: {usable} ART"""

def format_receipt(txid, tx_type, sender_info, receiver_info, amount, fee=0, reason=None):
    """ساخت رسید رسمی"""
    receipt = f"""🏦 بانک کملوت
━━━━━━━━━━━━━━━━━━━
📄 شماره تراکنش: {txid}
📋 نوع: {tx_type}
💰 مبلغ: {amount} ART"""
    
    if fee > 0:
        receipt += f"\n💸 کارمزد: {fee} ART"
    
    if reason:
        receipt += f"\n📝 علت: {reason}"
    
    receipt += f"\n━━━━━━━━━━━━━━━━━━━"
    receipt += f"\n👤 فرستنده: {sender_info}"
    receipt += f"\n👤 گیرنده: {receiver_info}"
    receipt += f"\n━━━━━━━━━━━━━━━━━━━"
    receipt += f"\n🕐 تاریخ: {datetime.now().strftime('%Y/%m/%d - %H:%M')}"
    receipt += f"\n✅ وضعیت: موفق"
    
    return receipt

def send_notification(user_id, title, message):
    """ذخیره پیام در صندوق پیام کاربر"""
    from database import get_db
    conn = get_db()
    c = conn.cursor()
    c.execute('INSERT INTO notifications (user_id, title, message) VALUES (?, ?, ?)',
              (user_id, title, message))
    conn.commit()
    conn.close()

def update_credit_score(account_id, new_score, reason):
    from database import get_db
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT credit_score FROM accounts WHERE id = ?', (account_id,))
    old = c.fetchone()
    if old:
        old_score = old['credit_score']
        c.execute('UPDATE accounts SET credit_score = ? WHERE id = ?', (new_score, account_id))
        c.execute('INSERT INTO credit_history (account_id, old_score, new_score, reason) VALUES (?, ?, ?, ?)',
                  (account_id, old_score, new_score, reason))
        conn.commit()
    conn.close()
