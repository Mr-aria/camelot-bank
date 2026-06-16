from database import get_db, log_audit
from datetime import datetime
import pytz
import jdatetime

TEHRAN_TZ = pytz.timezone('Asia/Tehran')

def create_bank_account(user_id, username, real_name, camelot_name, national_id, password):
    from database import generate_account_number, get_setting
    
    conn = get_db()
    c = conn.cursor()
    
    c.execute('''INSERT INTO users (telegram_id, username, real_name, camelot_name, national_id, role)
                 VALUES (?, ?, ?, ?, ?, 'citizen')''',
              (user_id, username, real_name, camelot_name, national_id))
    user_db_id = c.lastrowid
    
    acc_num = generate_account_number()
    bonus = int(get_setting('registration_bonus') or 0)
    
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
    now = datetime.now(TEHRAN_TZ)
    jnow = jdatetime.datetime.fromgregorian(datetime=now)
    jalali_date = jnow.strftime("%Y/%m/%d - %H:%M")
    
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
    receipt += f"\n🕐 تاریخ: {jalali_date}"
    receipt += f"\n✅ وضعیت: موفق"
    
    return receipt

def send_notification(user_id, title, message):
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

# ---------- توابع وام ----------
def get_avg_monthly_turnover(account_number):
    from database import get_db
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT AVG(amount) as avg_monthly FROM (
            SELECT SUM(amount) as amount 
            FROM transactions 
            WHERE sender_account = ? 
            AND created_at >= date('now', '-3 months')
            GROUP BY strftime('%Y-%m', created_at)
        )
    ''', (account_number,))
    row = c.fetchone()
    conn.close()
    if row and row['avg_monthly']:
        return int(row['avg_monthly'])
    return 0

def calculate_max_loan_amount(user_id):
    from database import get_db, get_account_by_user_id, get_user_by_telegram_id, get_loan_setting
    multiplier = int(get_loan_setting('loan_max_multiplier_turnover') or 3)
    divider = int(get_loan_setting('loan_credit_score_divider') or 10)
    max_abs = int(get_loan_setting('loan_max_amount') or 1000000)
    min_amt = int(get_loan_setting('loan_min_amount') or 1000)
    
    user = get_user_by_telegram_id(user_id)
    if not user:
        return 0
    acc = get_account_by_user_id(user['id'])
    if not acc:
        return 0
    
    avg_turnover = get_avg_monthly_turnover(acc['account_number'])
    credit_score = acc['credit_score']
    
    max_loan = (avg_turnover * multiplier) + (credit_score // divider)
    
    if max_loan < min_amt:
        max_loan = min_amt
    if max_loan > max_abs:
        max_loan = max_abs
    
    return max_loan

def has_active_loan(account_id):
    from database import get_db
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id FROM loans WHERE account_id = ? AND status IN ("active", "delayed")', (account_id,))
    row = c.fetchone()
    conn.close()
    return row is not None

def calculate_installments(amount, interest_rate, installments_count):
    total_with_interest = amount + (amount * interest_rate / 100)
    return total_with_interest / installments_count

def get_loan_status_text(loan):
    if loan['status'] == 'active':
        return "✅ فعال"
    elif loan['status'] == 'delayed':
        return "⚠️ معوق"
    elif loan['status'] == 'paid':
        return "✅ تسویه شده"
    else:
        return "❌ نامشخص"

def format_loan_info(loan, account):
    from database import get_db
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) as total, SUM(amount) as paid FROM loan_payments WHERE loan_id = ? AND status = "paid"', (loan['id'],))
    paid_info = c.fetchone()
    conn.close()
    
    paid_installments = paid_info['total'] if paid_info else 0
    paid_amount = paid_info['paid'] if paid_info else 0
    
    remaining = loan['remaining_amount'] - paid_amount + loan['fine']
    
    text = f"""🏦 **اطلاعات وام شما**
━━━━━━━━━━━━━━━━━━━
💰 مبلغ وام: {loan['amount']} ART
📊 سود ({loan['interest']}%): {loan['amount'] * loan['interest'] // 100} ART
💸 جریمه: {loan['fine']} ART
📅 تعداد اقساط: {loan['installments']}
✅ اقساط پرداخت شده: {paid_installments}
📦 مانده بدهی: {remaining} ART
📋 وضعیت: {get_loan_status_text(loan)}
━━━━━━━━━━━━━━━━━━━"""
    return text

def check_and_block_low_credit(account_id):
    from database import get_db, get_loan_setting
    min_score = int(get_loan_setting('loan_min_credit_score_to_unblock') or 300)
    
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT credit_score, user_id FROM accounts WHERE id = ?', (account_id,))
    acc = c.fetchone()
    if acc and acc['credit_score'] < min_score:
        c.execute('UPDATE accounts SET status = "blocked" WHERE id = ?', (account_id,))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

# ---------- توابع تراکنش ----------
def format_transaction_summary(tx, user_account_number):
    """فرمت خلاصه تراکنش با علامت مثبت/منفی و نمایش طرف مقابل"""
    types = {
        'transfer': '💸 انتقال وجه',
        'loan': '🏦 دریافت وام',
        'loan_payment': '💰 پرداخت قسط',
        'manual_deposit': '📥 واریز دستی',
        'manual_withdraw': '📤 برداشت دستی',
        'tax': '🏛 مالیات',
        'treasury': '🏦 خزانه'
    }
    tx_type = types.get(tx['type'], tx['type'])
    
    created = datetime.strptime(tx['created_at'], '%Y-%m-%d %H:%M:%S')
    jcreated = jdatetime.datetime.fromgregorian(datetime=created)
    date_str = jcreated.strftime('%Y/%m/%d')
    
    # تشخیص جهت تراکنش
    if tx['sender_account'] == user_account_number:
        # پرداخت (پول از حساب من خارج شده)
        sign = '-'
        amount_display = f"{sign}{tx['amount']} ART"
        # طرف مقابل: گیرنده
        receiver = get_user_by_account_number(tx['receiver_account'])
        opposite_name = receiver['camelot_name'] if receiver else 'نامشخص'
        opposite_info = f"به {opposite_name} (حساب {tx['receiver_account']})"
    elif tx['receiver_account'] == user_account_number:
        # دریافت (پول به حساب من واریز شده)
        sign = '+'
        amount_display = f"{sign}{tx['amount']} ART"
        # طرف مقابل: فرستنده
        sender = get_user_by_account_number(tx['sender_account'])
        opposite_name = sender['camelot_name'] if sender else 'نامشخص'
        opposite_info = f"از {opposite_name} (حساب {tx['sender_account']})"
    else:
        # تراکنش‌های داخلی (مثلاً وام) که هر دو حساب متعلق به کاربر است
        sign = ''
        amount_display = f"{tx['amount']} ART"
        opposite_info = 'داخلی'
    
    return f"📌 {tx_type}\n   💰 {amount_display}   🕐 {date_str}\n   {opposite_info}"

def format_transaction_detail(tx, user_account):
    """فرمت جزئیات کامل یک تراکنش"""
    types = {
        'transfer': '💸 انتقال وجه',
        'loan': '🏦 دریافت وام',
        'loan_payment': '💰 پرداخت قسط',
        'manual_deposit': '📥 واریز دستی',
        'manual_withdraw': '📤 برداشت دستی',
        'tax': '🏛 مالیات',
        'treasury': '🏦 خزانه'
    }
    tx_type = types.get(tx['type'], tx['type'])
    
    created = datetime.strptime(tx['created_at'], '%Y-%m-%d %H:%M:%S')
    jcreated = jdatetime.datetime.fromgregorian(datetime=created)
    date_str = jcreated.strftime('%Y/%m/%d - %H:%M')
    
    status = "✅ موفق" if tx['status'] == 'success' else "❌ لغو شده"
    
    detail = f"""📋 **جزئیات تراکنش**
━━━━━━━━━━━━━━━━━━━
🔖 شماره: `{tx['txid']}`
📌 نوع: {tx_type}
💰 مبلغ: {tx['amount']} ART
💸 کارمزد: {tx['fee']} ART
🕐 تاریخ: {date_str}
📊 وضعیت: {status}"""

    if tx['reason']:
        detail += f"\n📝 علت: {tx['reason']}"
    
    if tx['sender_account']:
        detail += f"\n🏦 حساب مبدأ: `{tx['sender_account']}`"
    if tx['receiver_account']:
        detail += f"\n🏦 حساب مقصد: `{tx['receiver_account']}`"
    
    detail += "\n━━━━━━━━━━━━━━━━━━━"
    return detail