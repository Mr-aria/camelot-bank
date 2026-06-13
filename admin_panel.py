from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import get_db, get_user_by_telegram_id, get_account_by_user_id, log_audit
from utils import update_credit_score
import json

async def admin_users_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """منوی مدیریت کاربران"""
    keyboard = [
        [InlineKeyboardButton("🔍 جستجوی کاربر", callback_data="admin_search_user")],
        [InlineKeyboardButton("📋 لیست همه کاربران", callback_data="admin_list_users")],
        [InlineKeyboardButton("➕ افزایش موجودی", callback_data="admin_add_balance")],
        [InlineKeyboardButton("➖ کاهش موجودی", callback_data="admin_remove_balance")],
        [InlineKeyboardButton("🔒 مسدودسازی حساب", callback_data="admin_block_account")],
        [InlineKeyboardButton("🔓 رفع مسدودی", callback_data="admin_unblock_account")],
        [InlineKeyboardButton("🧊 بلوکه کردن موجودی", callback_data="admin_freeze_balance")],
        [InlineKeyboardButton("📝 یادداشت مدیریتی", callback_data="admin_add_note")],
        [InlineKeyboardButton("⚖️ تغییر امتیاز اعتباری", callback_data="admin_change_score")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_panel")],
    ]
    return InlineKeyboardMarkup(keyboard)

async def search_user_by_national_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🔍 کد ملی کاربر را وارد کنید:")
    context.user_data['admin_action'] = 'search_by_national'

async def search_user_by_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🔍 شماره حساب کاربر را وارد کنید:")
    context.user_data['admin_action'] = 'search_by_account'

async def show_user_info(update: Update, context: ContextTypes.DEFAULT_TYPE, identifier: str, search_type: str):
    """نمایش اطلاعات کامل کاربر"""
    db = get_db()
    cursor = db.cursor()
    
    if search_type == 'national':
        cursor.execute('SELECT * FROM users WHERE national_id = ?', (identifier,))
    else:
        cursor.execute('''
            SELECT u.*, a.* FROM users u
            JOIN accounts a ON u.id = a.user_id
            WHERE a.account_number = ?
        ''', (identifier,))
    
    user = cursor.fetchone()
    if not user:
        await update.callback_query.edit_message_text("❌ کاربر یافت نشد.")
        db.close()
        return
    
    # گرفتن حساب کاربر
    cursor.execute('SELECT * FROM accounts WHERE user_id = ?', (user['id'],))
    acc = cursor.fetchone()
    db.close()
    
    if not acc:
        await update.callback_query.edit_message_text("❌ حساب بانکی برای این کاربر یافت نشد.")
        return
    
    # نقش به فارسی
    role_names = {'citizen': 'شهروند', 'employee': 'کارمند', 'king': 'شاه', 'owner': 'مالک'}
    role_persian = role_names.get(user['role'], 'نامشخص')
    
    status_names = {'active': '✅ فعال', 'blocked': '🚫 مسدود'}
    status_persian = status_names.get(acc['status'], 'نامشخص')
    
    info = f"""👤 **اطلاعات کاربر**
━━━━━━━━━━━━━━━━━━━
📛 **نام واقعی:** {user['real_name']}
⚔️ **نام کملوتی:** {user['camelot_name']}
🆔 **کد ملی:** {user['national_id']}
🏦 **شماره حساب:** {acc['account_number']}
🔐 **رمز حساب:** {acc['password']}
💰 **موجودی:** {acc['balance']} ART
🔒 **موجودی بلوکه:** {acc['blocked_balance']} ART
⭐ **امتیاز اعتباری:** {acc['credit_score']}
👑 **نقش:** {role_persian}
📊 **وضعیت:** {status_persian}
📝 **یادداشت:** {acc['notes'] or 'ندارد'}
━━━━━━━━━━━━━━━━━━━
"""
    
    keyboard = [
        [InlineKeyboardButton("💰 افزایش موجودی", callback_data=f"admin_add_bal_{acc['id']}")],
        [InlineKeyboardButton("🔒 مسدودسازی", callback_data=f"admin_block_{acc['id']}")],
        [InlineKeyboardButton("📝 افزودن یادداشت", callback_data=f"admin_note_{acc['id']}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_users")],
    ]
    await update.callback_query.edit_message_text(info, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def admin_add_balance(update: Update, context: ContextTypes.DEFAULT_TYPE, account_id: int):
    query = update.callback_query
    await query.answer()
    context.user_data['admin_action'] = f'add_balance_{account_id}'
    await query.edit_message_text("💰 مبلغ مورد نظر را به ART وارد کنید:")

async def process_admin_add_balance(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    try:
        amount = int(text)
        if amount <= 0:
            await update.message.reply_text("❌ مبلغ باید مثبت باشد.")
            return
    except:
        await update.message.reply_text("❌ لطفاً یک عدد معتبر وارد کنید.")
        return
    
    action = context.user_data.get('admin_action', '')
    if not action.startswith('add_balance_'):
        return
    
    account_id = int(action.split('_')[2])
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT balance, user_id FROM accounts WHERE id = ?', (account_id,))
    acc = cursor.fetchone()
    
    if not acc:
        await update.message.reply_text("❌ حساب یافت نشد.")
        db.close()
        return
    
    new_balance = acc['balance'] + amount
    cursor.execute('UPDATE accounts SET balance = ? WHERE id = ?', (new_balance, account_id))
    
    # ثبت در لاگ
    log_audit(update.effective_user.id, 'manual_deposit', f'account:{account_id}', f'amount:{amount}')
    
    db.commit()
    db.close()
    
    # ارسال اعلان به کاربر
    try:
        await context.bot.send_message(
            acc['user_id'],
            f"💰 مبلغ {amount} ART به حساب شما واریز شد.\nموجودی جدید: {new_balance} ART"
        )
    except:
        pass
    
    await update.message.reply_text(f"✅ مبلغ {amount} ART با موفقیت واریز شد.")
    context.user_data.pop('admin_action', None)

async def admin_list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''
        SELECT u.id, u.real_name, u.camelot_name, u.national_id, a.account_number, a.balance, a.credit_score
        FROM users u
        JOIN accounts a ON u.id = a.user_id
        ORDER BY a.balance DESC
        LIMIT 20
    ''')
    users = cursor.fetchall()
    db.close()
    
    if not users:
        await query.edit_message_text("📭 هیچ کاربری یافت نشد.")
        return
    
    text = "📋 **لیست کاربران (۲۰ ثروتمند اول)**\n━━━━━━━━━━━━━━━━━━━\n"
    for idx, u in enumerate(users, 1):
        text += f"{idx}. {u['camelot_name']}\n"
        text += f"   🏦 {u['account_number']} | 💰 {u['balance']} ART\n"
        text += f"   ⭐ {u['credit_score']}\n\n"
    
    keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_users")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')