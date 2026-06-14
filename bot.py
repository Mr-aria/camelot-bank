import logging
from datetime import datetime, timedelta
import pytz
import jdatetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler
import os

BOT_TOKEN = os.environ.get("BOT_TOKEN")
OWNER_ID = 1275490079
KING_ID = 1275490079
LOG_CHANNEL_ID = -1003999739601
EMPLOYEES_IDS = []

from database import (
    init_db, get_db, get_user_by_telegram_id, get_account_by_user_id,
    get_account_by_number, get_user_by_account_number, get_setting,
    get_loan_setting, set_loan_setting, get_all_loan_settings,
    generate_txid, log_audit, get_active_loan, create_loan,
    apply_loan_penalties
)
from utils import (
    create_bank_account, format_balance, format_receipt,
    calculate_max_loan_amount, has_active_loan, format_loan_info,
    check_and_block_low_credit, get_avg_monthly_turnover,
    calculate_installments
)

TEHRAN_TZ = pytz.timezone('Asia/Tehran')

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

NAME_REAL, NAME_CAMELOT, NATIONAL_ID, PASSWORD, CONFIRM = range(5)
TRANSFER_ACCOUNT, TRANSFER_AMOUNT, TRANSFER_REASON, TRANSFER_PASSWORD = range(10, 14)
LOAN_AMOUNT, LOAN_INSTALLMENTS, LOAN_CONFIRM = range(15, 18)
SETTING_KEY, SETTING_VALUE = range(18, 20)

# ---------- توابع کمکی ----------
def get_user_role_from_telegram_id(telegram_id):
    if telegram_id == OWNER_ID:
        return 'owner'
    elif telegram_id == KING_ID:
        return 'king'
    elif telegram_id in EMPLOYEES_IDS:
        return 'employee'
    return 'citizen'

def is_admin(user_id: int) -> bool:
    user = get_user_by_telegram_id(user_id)
    if user:
        return user['role'] in ['king', 'owner', 'employee']
    role = get_user_role_from_telegram_id(user_id)
    return role in ['king', 'owner', 'employee']

def get_user_role_display(user_id: int) -> str:
    user = get_user_by_telegram_id(user_id)
    if user:
        roles = {'citizen':'شهروند','employee':'کارمند','king':'شاه','owner':'مالک'}
        return roles.get(user['role'], 'شهروند')
    role = get_user_role_from_telegram_id(user_id)
    roles = {'citizen':'شهروند','employee':'کارمند','king':'شاه','owner':'مالک'}
    return roles.get(role, 'شهروند')

def get_jalali_date():
    now = datetime.now(TEHRAN_TZ)
    jnow = jdatetime.datetime.fromgregorian(datetime=now)
    return jnow.strftime("%Y/%m/%d - %H:%M")

async def log_to_channel(context, message: str):
    try:
        await context.bot.send_message(LOG_CHANNEL_ID, message)
    except Exception as e:
        logger.error(f"خطا در ارسال به کانال لاگ: {e}")

async def send_message_to_user(context, user_id: int, text: str):
    try:
        await context.bot.send_message(user_id, text)
    except Exception as e:
        logger.error(f"خطا در ارسال پیام به {user_id}: {e}")

def main_menu_keyboard(user_role: str = 'citizen'):
    keyboard = [
        [InlineKeyboardButton("💰 موجودی", callback_data="balance")],
        [InlineKeyboardButton("💸 انتقال وجه", callback_data="transfer")],
        [InlineKeyboardButton("🏦 وام", callback_data="loan")],
        [InlineKeyboardButton("📜 تراکنش‌های من", callback_data="my_transactions")],
        [InlineKeyboardButton("👤 اطلاعات حساب", callback_data="my_info")],
        [InlineKeyboardButton("📬 صندوق پیام", callback_data="notifications")],
        [InlineKeyboardButton("⚙️ تنظیمات", callback_data="settings")],
        [InlineKeyboardButton("🔄 تغییر شماره حساب", callback_data="change_account")],
        [InlineKeyboardButton("📈 اعتبار بانکی من", callback_data="my_credit")],
        [InlineKeyboardButton("🆘 پشتیبانی", callback_data="support")],
    ]
    if user_role in ['king', 'owner', 'employee']:
        keyboard.append([InlineKeyboardButton("👑 پنل مدیریت", callback_data="panel")])
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context):
    user_id = update.effective_user.id
    username = update.effective_user.username or "بدون یوزرنیم"
    user = get_user_by_telegram_id(user_id)

    if not user:
        context.user_data.clear()
        context.user_data['register_step'] = NAME_REAL
        context.user_data['username'] = username
        await update.message.reply_text(
            "🏦 **به بانک کملوت خوش آمدید!**\n\n"
            "برای افتتاح حساب، نام واقعی خود را وارد کنید.\n"
            "(برای لغو در هر مرحله، /cancel را بزنید)",
            parse_mode='Markdown'
        )
        return NAME_REAL

    acc = get_account_by_user_id(user['id'])
    if not acc:
        await update.message.reply_text("❌ خطا در سیستم. لطفاً دوباره /start کنید.")
        return

    welcome = get_setting('welcome_message') or "درود👋\nخوش اومدین به بانک کملوت💰"
    await update.message.reply_text(welcome, reply_markup=main_menu_keyboard(user['role']))
    return ConversationHandler.END

async def cancel(update: Update, context):
    user_id = update.effective_user.id
    user = get_user_by_telegram_id(user_id)
    context.user_data.clear()
    if user:
        acc = get_account_by_user_id(user['id'])
        if acc:
            await update.message.reply_text(
                "❌ عملیات لغو شد.",
                reply_markup=main_menu_keyboard(user['role'])
            )
        else:
            await update.message.reply_text("❌ عملیات لغو شد.")
    else:
        await update.message.reply_text("❌ عملیات لغو شد.\nبرای شروع مجدد /start بزنید.")
    return ConversationHandler.END

# ---------- بخش‌های عادی (موجودی، اطلاعات، اعتبار، پنل، برگشت) ----------
async def balance_callback(update: Update, context):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    user = get_user_by_telegram_id(user_id)
    if not user:
        await query.edit_message_text("❌ حساب ندارید. لطفاً /start بزنید.")
        return
    acc = get_account_by_user_id(user['id'])
    if not acc:
        await query.edit_message_text("❌ حساب بانکی یافت نشد.")
        return
    balance_text = format_balance(acc['balance'], acc['blocked_balance'])
    await query.edit_message_text(balance_text, reply_markup=main_menu_keyboard(user['role']))

async def my_info_callback(update: Update, context):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    user = get_user_by_telegram_id(user_id)
    if not user or not (acc := get_account_by_user_id(user['id'])):
        await query.edit_message_text("❌ اطلاعاتی یافت نشد.")
        return
    status_persian = "✅ فعال" if acc['status'] == 'active' else "🚫 مسدود"
    now_jalali = get_jalali_date()
    info_text = f"""👤 **اطلاعات حساب شما**
━━━━━━━━━━━━━━━━━━━
📛 نام واقعی: {user['real_name']}
⚔️ نام کملوتی: {user['camelot_name']}
🆔 کد ملی: {user['national_id']}
🏦 شماره حساب: `{acc['account_number']}`
⭐ امتیاز اعتباری: {acc['credit_score']}
👑 نقش: {get_user_role_display(user_id)}
📊 وضعیت: {status_persian}
🕐 آخرین به‌روزرسانی: {now_jalali}
━━━━━━━━━━━━━━━━━━━"""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 بررسی مجدد حساب", callback_data="refresh_role")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_menu")]
    ])
    await query.edit_message_text(info_text, reply_markup=keyboard, parse_mode='Markdown')

async def refresh_role(update: Update, context):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    if user_id == OWNER_ID:
        new_role = 'owner'
    elif user_id == KING_ID:
        new_role = 'king'
    elif user_id in EMPLOYEES_IDS:
        new_role = 'employee'
    else:
        new_role = 'citizen'
    
    user = get_user_by_telegram_id(user_id)
    if not user:
        await query.edit_message_text("❌ شما هنوز حساب بانکی ندارید. لطفاً اول /start کنید.")
        return
    
    current_role = user['role']
    if current_role == new_role:
        await query.edit_message_text(
            f"✅ نقش شما در حال حاضر همان {get_user_role_display(user_id)} است.",
            reply_markup=main_menu_keyboard(current_role)
        )
        return
    
    db = get_db()
    c = db.cursor()
    c.execute("UPDATE users SET role = ? WHERE telegram_id = ?", (new_role, user_id))
    db.commit()
    db.close()
    log_audit(user_id, 'role_refresh', f'old:{current_role}', f'new:{new_role}')
    
    await query.edit_message_text(
        f"✅ **نقش شما به‌روز شد!**\n\n"
        f"👑 نقش جدید: {get_user_role_display(user_id)}\n\n"
        f"لطفاً دوباره از منوی اصلی استفاده کنید.",
        reply_markup=main_menu_keyboard(new_role)
    )

async def my_credit_callback(update: Update, context):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    user = get_user_by_telegram_id(user_id)
    if not user or not (acc := get_account_by_user_id(user['id'])):
        await query.edit_message_text("❌ اطلاعاتی یافت نشد.")
        return
    score = acc['credit_score']
    if score >= 900:
        rating = "🟢 عالی"
    elif score >= 700:
        rating = "🟡 خوب"
    elif score >= 500:
        rating = "🟠 متوسط"
    elif score >= 300:
        rating = "🔴 ضعیف"
    else:
        rating = "⚫ بدحساب"
    await query.edit_message_text(
        f"📈 **اعتبار بانکی شما**\n━━━━━━━━━━━━━━━━━━━\n⭐ امتیاز: {score}\n🏷 رتبه: {rating}",
        reply_markup=main_menu_keyboard(user['role']),
        parse_mode='Markdown'
    )

async def panel_callback(update: Update, context):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await query.edit_message_text("⛔ دسترسی ندارید.")
        return
    user = get_user_by_telegram_id(user_id)
    role_persian = get_user_role_display(user_id)
    now_jalali = get_jalali_date()
    panel_text = f"👑 **پنل مدیریت**\n👤 نقش: {role_persian}\n🕐 {now_jalali}"
    keyboard = [
        [InlineKeyboardButton("👥 مدیریت کاربران", callback_data="admin_users")],
        [InlineKeyboardButton("💰 مدیریت مالی", callback_data="admin_finance")],
        [InlineKeyboardButton("🏦 مدیریت خزانه", callback_data="admin_treasury")],
        [InlineKeyboardButton("📨 درخواست‌های pending", callback_data="admin_requests")],
        [InlineKeyboardButton("⚙️ تنظیمات وام", callback_data="admin_loan_settings")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_menu")]
    ]
    await query.edit_message_text(panel_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def back_to_panel(update: Update, context):
    query = update.callback_query
    await query.answer()
    await panel_callback(update, context)

async def back_to_menu(update: Update, context):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    user = get_user_by_telegram_id(user_id)
    role = user['role'] if user else 'citizen'
    await query.edit_message_text(
        get_setting('welcome_message') or "منوی اصلی",
        reply_markup=main_menu_keyboard(role)
    )

# ---------- ثبت‌نام ----------
async def register_handler(update: Update, context):
    step = context.user_data.get('register_step')
    text = update.message.text
    if step == NAME_REAL:
        context.user_data['real_name'] = text
        context.user_data['register_step'] = NAME_CAMELOT
        await update.message.reply_text("⚔️ نام خود در کملوت را وارد کنید:\n(برای لغو /cancel بزنید)", parse_mode='Markdown')
        return NAME_CAMELOT
    elif step == NAME_CAMELOT:
        context.user_data['camelot_name'] = text
        context.user_data['register_step'] = NATIONAL_ID
        await update.message.reply_text("🆔 کد ملی ۶ رقمی را وارد کنید:\n(برای لغو /cancel بزنید)", parse_mode='Markdown')
        return NATIONAL_ID
    elif step == NATIONAL_ID:
        if not text.isdigit() or len(text) != 6:
            await update.message.reply_text("❌ کد ملی ۶ رقم باید باشد. دوباره وارد کنید:")
            return NATIONAL_ID
        db = get_db()
        c = db.cursor()
        c.execute('SELECT id FROM users WHERE national_id = ?', (text,))
        if c.fetchone():
            db.close()
            await update.message.reply_text("❌ این کد ملی قبلاً ثبت شده. کد دیگری وارد کنید:")
            return NATIONAL_ID
        db.close()
        context.user_data['national_id'] = text
        context.user_data['register_step'] = PASSWORD
        await update.message.reply_text("🔐 رمز ۴ رقمی برای حساب خود وارد کنید:\n(برای لغو /cancel بزنید)", parse_mode='Markdown')
        return PASSWORD
    elif step == PASSWORD:
        if not text.isdigit() or len(text) != 4:
            await update.message.reply_text("❌ رمز ۴ رقم باید باشد. دوباره وارد کنید:")
            return PASSWORD
        context.user_data['password'] = text
        context.user_data['register_step'] = CONFIRM
        confirm_text = f"""✅ اطلاعات را تأیید کنید:
📛 نام واقعی: {context.user_data['real_name']}
⚔️ نام کملوتی: {context.user_data['camelot_name']}
🆔 کد ملی: {context.user_data['national_id']}
🔐 رمز: ****
آیا صحیح است؟"""
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ بله", callback_data="confirm_yes")],
            [InlineKeyboardButton("❌ خیر (لغو)", callback_data="confirm_no")]
        ])
        await update.message.reply_text(confirm_text, reply_markup=keyboard, parse_mode='Markdown')
        return CONFIRM
    return ConversationHandler.END

async def confirm_callback(update: Update, context):
    query = update.callback_query
    await query.answer()
    if query.data == "confirm_yes":
        user_id = update.effective_user.id
        username = context.user_data.get('username', '')
        real_name = context.user_data.get('real_name')
        camelot_name = context.user_data.get('camelot_name')
        national_id = context.user_data.get('national_id')
        password = context.user_data.get('password')
        if not all([real_name, camelot_name, national_id, password]):
            await query.edit_message_text("❌ خطا: اطلاعات کامل نیست. لطفاً دوباره /start کنید.")
            for key in ['real_name','camelot_name','national_id','password','register_step','username']:
                context.user_data.pop(key, None)
            return
        db = get_db()
        c = db.cursor()
        c.execute('SELECT id FROM users WHERE national_id = ?', (national_id,))
        if c.fetchone():
            db.close()
            await query.edit_message_text("❌ این کد ملی قبلاً ثبت شده. لطفاً با کد دیگری ثبت‌نام کنید.")
            return
        db.close()
        try:
            acc_num, bonus = create_bank_account(
                user_id, username, real_name, camelot_name, national_id, password
            )
            real_role = get_user_role_from_telegram_id(user_id)
            if real_role != 'citizen':
                db = get_db()
                c = db.cursor()
                c.execute("UPDATE users SET role = ? WHERE telegram_id = ?", (real_role, user_id))
                db.commit()
                db.close()
                logger.info(f"نقش کاربر {user_id} به {real_role} تغییر کرد.")
            await query.edit_message_text(
                f"✅ **حساب بانکی شما با موفقیت ایجاد شد!**\n\n"
                f"🏦 **شماره حساب:** `{acc_num}`\n"
                f"💰 **موجودی اولیه:** {bonus} ART\n"
                f"⭐ **امتیاز اعتباری:** 1000\n"
                f"👑 **نقش شما:** {get_user_role_display(user_id)}\n\n"
                f"برای ورود به بانک، دوباره /start بزنید.",
                parse_mode='Markdown'
            )
            try:
                await log_to_channel(context, f"🏦 حساب جدید: {camelot_name} | شماره حساب: {acc_num} | نقش: {get_user_role_display(user_id)}")
            except:
                pass
        except Exception as e:
            logger.error(f"خطا در ساخت حساب: {e}")
            await query.edit_message_text(f"❌ خطا در ساخت حساب: {str(e)}\nلطفاً دوباره /start کنید.")
        for key in ['real_name','camelot_name','national_id','password','register_step','username']:
            context.user_data.pop(key, None)
    else:
        await query.edit_message_text("❌ ثبت‌نام لغو شد. برای شروع مجدد /start بزنید.")
        for key in ['real_name','camelot_name','national_id','password','register_step','username']:
            context.user_data.pop(key, None)

# ---------- انتقال وجه ----------
async def transfer_start(update: Update, context):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    user = get_user_by_telegram_id(user_id)
    if not user or not (acc := get_account_by_user_id(user['id'])) or acc['status'] != 'active':
        await query.edit_message_text("❌ حساب مسدود یا وجود ندارد.")
        return
    context.user_data['transfer_step'] = TRANSFER_ACCOUNT
    await query.edit_message_text("💸 شماره حساب مقصد (۶ رقم) را وارد کنید:\n(برای لغو /cancel بزنید)", parse_mode='Markdown')
    return TRANSFER_ACCOUNT

async def transfer_account_handler(update: Update, context):
    text = update.message.text.strip()
    user_id = update.effective_user.id
    if text.lower() == '/cancel':
        await update.message.reply_text("❌ لغو شد.", reply_markup=main_menu_keyboard(get_user_role_display(user_id)))
        context.user_data.pop('transfer_step', None)
        return ConversationHandler.END
    if not text.isdigit() or len(text) != 6:
        await update.message.reply_text("❌ شماره حساب باید ۶ رقم باشد.")
        return TRANSFER_ACCOUNT
    sender_user = get_user_by_telegram_id(user_id)
    sender_acc = get_account_by_user_id(sender_user['id'])
    if sender_acc['account_number'] == text:
        await update.message.reply_text("❌ نمی‌توانید به خودتان انتقال دهید.")
        return TRANSFER_ACCOUNT
    receiver_acc = get_account_by_number(text)
    if not receiver_acc:
        await update.message.reply_text("❌ حساب مقصد یافت نشد.")
        return TRANSFER_ACCOUNT
    receiver_user = get_user_by_account_number(text)
    context.user_data['transfer_receiver_account'] = text
    context.user_data['transfer_receiver_name'] = receiver_user['camelot_name']
    context.user_data['transfer_step'] = TRANSFER_AMOUNT
    await update.message.reply_text(f"✅ مقصد: {receiver_user['camelot_name']}\n💰 مبلغ را وارد کنید:", parse_mode='Markdown')
    return TRANSFER_AMOUNT

async def transfer_amount_handler(update: Update, context):
    text = update.message.text.strip()
    user_id = update.effective_user.id
    if text.lower() == '/cancel':
        await update.message.reply_text("❌ لغو شد.", reply_markup=main_menu_keyboard(get_user_role_display(user_id)))
        context.user_data.pop('transfer_step', None)
        return ConversationHandler.END
    try:
        amount = int(text)
        if amount <= 0: raise ValueError
    except:
        await update.message.reply_text("❌ عدد مثبت وارد کنید.")
        return TRANSFER_AMOUNT
    sender_user = get_user_by_telegram_id(user_id)
    sender_acc = get_account_by_user_id(sender_user['id'])
    usable = sender_acc['balance'] - sender_acc['blocked_balance']
    if amount > usable:
        await update.message.reply_text(f"❌ موجودی کافی نیست. قابل استفاده: {usable} ART")
        return TRANSFER_AMOUNT
    limit = int(get_setting('monthly_transfer_limit') or 50000)
    if sender_acc['monthly_transfer_used'] + amount > limit:
        await update.message.reply_text(f"❌ سقف ماهانه {limit} ART تکمیل است.")
        return TRANSFER_AMOUNT
    context.user_data['transfer_amount'] = amount
    context.user_data['transfer_step'] = TRANSFER_REASON
    await update.message.reply_text(f"💰 مبلغ: {amount} ART\n📝 علت (اختیاری، «ندارد» برای رد):\n(برای لغو /cancel بزنید)")
    return TRANSFER_REASON

async def transfer_reason_handler(update: Update, context):
    text = update.message.text.strip()
    user_id = update.effective_user.id
    if text.lower() == '/cancel':
        await update.message.reply_text("❌ لغو شد.", reply_markup=main_menu_keyboard(get_user_role_display(user_id)))
        context.user_data.pop('transfer_step', None)
        return ConversationHandler.END
    reason = text if text.lower() != 'ندارد' else None
    context.user_data['transfer_reason'] = reason
    context.user_data['transfer_step'] = TRANSFER_PASSWORD
    await update.message.reply_text(f"🔐 رمز ۴ رقمی خود را وارد کنید:\n(برای لغو /cancel بزنید)")
    return TRANSFER_PASSWORD

async def transfer_password_handler(update: Update, context):
    text = update.message.text.strip()
    user_id = update.effective_user.id
    if text.lower() == '/cancel':
        await update.message.reply_text("❌ لغو شد.", reply_markup=main_menu_keyboard(get_user_role_display(user_id)))
        context.user_data.pop('transfer_step', None)
        return ConversationHandler.END
    if not text.isdigit() or len(text) != 4:
        await update.message.reply_text("❌ رمز ۴ رقم باید باشد.")
        return TRANSFER_PASSWORD
    sender_user = get_user_by_telegram_id(user_id)
    sender_acc = get_account_by_user_id(sender_user['id'])
    if sender_acc['password'] != text:
        await update.message.reply_text("❌ رمز اشتباه است.")
        return TRANSFER_PASSWORD
    amount = context.user_data['transfer_amount']
    receiver_account = context.user_data['transfer_receiver_account']
    receiver_acc = get_account_by_number(receiver_account)
    receiver_user = get_user_by_account_number(receiver_account)
    fee = 0
    total = amount + fee
    if sender_acc['balance'] - sender_acc['blocked_balance'] < total:
        await update.message.reply_text("❌ موجودی کافی نیست.")
        return ConversationHandler.END
    new_sender = sender_acc['balance'] - total
    new_receiver = receiver_acc['balance'] + amount
    new_monthly = sender_acc['monthly_transfer_used'] + amount
    db = get_db()
    c = db.cursor()
    c.execute('UPDATE accounts SET balance=?, monthly_transfer_used=? WHERE id=?', (new_sender, new_monthly, sender_acc['id']))
    c.execute('UPDATE accounts SET balance=? WHERE id=?', (new_receiver, receiver_acc['id']))
    txid = generate_txid()
    c.execute('INSERT INTO transactions (txid, sender_account, receiver_account, amount, fee, reason, type) VALUES (?,?,?,?,?,?,"transfer")',
              (txid, sender_acc['account_number'], receiver_account, amount, fee, context.user_data.get('transfer_reason')))
    db.commit()
    db.close()
    log_audit(user_id, 'transfer', f'to:{receiver_account}', f'amount:{amount}')
    receipt = format_receipt(txid, 'انتقال وجه', f"{sender_user['camelot_name']} ({sender_acc['account_number']})",
                             f"{receiver_user['camelot_name']} ({receiver_account})", amount, fee, context.user_data.get('transfer_reason'))
    await update.message.reply_text(receipt, parse_mode='Markdown')
    await send_message_to_user(context, receiver_user['telegram_id'],
                               f"💸 دریافت {amount} ART از {sender_user['camelot_name']}\nموجودی جدید: {new_receiver} ART")
    await log_to_channel(context, f"💸 تراکنش: {sender_user['camelot_name']} -> {receiver_user['camelot_name']} | {amount} ART")
    context.user_data.pop('transfer_step', None)
    return ConversationHandler.END

# ---------- وام ----------
async def loan_menu_callback(update: Update, context):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    user = get_user_by_telegram_id(user_id)
    if not user:
        await query.edit_message_text("❌ حساب ندارید. لطفاً /start بزنید.")
        return
    
    acc = get_account_by_user_id(user['id'])
    if not acc:
        await query.edit_message_text("❌ حساب بانکی یافت نشد.")
        return
    
    keyboard = [
        [InlineKeyboardButton("📥 دریافت وام جدید", callback_data="loan_request")],
        [InlineKeyboardButton("💰 پرداخت اقساط", callback_data="loan_pay")],
        [InlineKeyboardButton("📋 وضعیت وام", callback_data="loan_status")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_menu")]
    ]
    await query.edit_message_text(
        "🏦 **بخش وام بانک کملوت**\n\n"
        "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def loan_request_start(update: Update, context):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    user = get_user_by_telegram_id(user_id)
    if not user:
        await query.edit_message_text("❌ حساب ندارید.")
        return
    
    acc = get_account_by_user_id(user['id'])
    if not acc:
        await query.edit_message_text("❌ حساب بانکی یافت نشد.")
        return
    
    # بررسی قفل بودن وام برای شهروندان
    if user['role'] == 'citizen':
        loan_enabled = get_loan_setting('loan_enabled_for_citizens')
        if loan_enabled == '0':
            await query.edit_message_text(
                "❌ بخش وام در حال حاضر برای شهروندان غیرفعال شده است.\n"
                "لطفاً بعداً مراجعه کنید.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="loan")]])
            )
            return
    
    # بررسی وام فعال
    if has_active_loan(acc['id']):
        await query.edit_message_text(
            "❌ شما در حال حاضر یک وام فعال دارید.\n"
            "ابتدا وام فعلی خود را تسویه کنید سپس برای وام جدید اقدام نمایید.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="loan")]])
        )
        return
    
    # محاسبه حداکثر وام
    max_loan = calculate_max_loan_amount(user_id)
    min_loan = int(get_loan_setting('loan_min_amount') or 1000)
    
    # اگر حداکثر وام کمتر از حداقل است، اجازه نده
    if max_loan < min_loan:
        await query.edit_message_text(
            f"❌ متأسفانه بر اساس سابقه مالی شما، حداکثر وام مجاز ({max_loan} ART) کمتر از حداقل وام ({min_loan} ART) است.\n"
            f"امکان دریافت وام برای شما وجود ندارد.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="loan")]])
        )
        return
    
    context.user_data['loan_step'] = LOAN_AMOUNT
    await query.edit_message_text(
        f"📥 **درخواست وام جدید**\n\n"
        f"حداقل مبلغ وام: {min_loan} ART\n"
        f"حداکثر مبلغ وام مجاز برای شما: {max_loan} ART\n\n"
        f"لطفاً مبلغ مورد نظر خود را وارد کنید:\n"
        f"(برای لغو /cancel بزنید)",
        parse_mode='Markdown'
    )
    return LOAN_AMOUNT

async def loan_amount_handler(update: Update, context):
    text = update.message.text.strip()
    user_id = update.effective_user.id
    if text.lower() == '/cancel':
        await update.message.reply_text("❌ درخواست وام لغو شد.", reply_markup=main_menu_keyboard(get_user_role_display(user_id)))
        context.user_data.pop('loan_step', None)
        return ConversationHandler.END
    
    try:
        amount = int(text)
        if amount <= 0:
            raise ValueError
    except:
        await update.message.reply_text("❌ لطفاً یک عدد مثبت وارد کنید:")
        return LOAN_AMOUNT
    
    max_loan = calculate_max_loan_amount(user_id)
    min_loan = int(get_loan_setting('loan_min_amount') or 1000)
    
    if amount < min_loan:
        await update.message.reply_text(f"❌ حداقل مبلغ وام {min_loan} ART است. لطفاً مجدداً وارد کنید:")
        return LOAN_AMOUNT
    if amount > max_loan:
        await update.message.reply_text(f"❌ حداکثر مبلغ وام مجاز برای شما {max_loan} ART است. لطفاً مجدداً وارد کنید:")
        return LOAN_AMOUNT
    
    context.user_data['loan_amount'] = amount
    context.user_data['loan_step'] = LOAN_INSTALLMENTS
    
    default_installments = int(get_loan_setting('loan_default_installments') or 6)
    await update.message.reply_text(
        f"💰 مبلغ وام: {amount} ART\n\n"
        f"لطفاً تعداد اقساط مورد نظر را وارد کنید (پیش‌فرض {default_installments} قسط):\n"
        f"(برای لغو /cancel بزنید)",
        parse_mode='Markdown'
    )
    return LOAN_INSTALLMENTS

async def loan_installments_handler(update: Update, context):
    text = update.message.text.strip()
    user_id = update.effective_user.id
    if text.lower() == '/cancel':
        await update.message.reply_text("❌ درخواست وام لغو شد.", reply_markup=main_menu_keyboard(get_user_role_display(user_id)))
        context.user_data.pop('loan_step', None)
        return ConversationHandler.END
    
    try:
        installments = int(text)
        if installments <= 0:
            raise ValueError
    except:
        await update.message.reply_text("❌ لطفاً یک عدد صحیح مثبت وارد کنید:")
        return LOAN_INSTALLMENTS
    
    context.user_data['loan_installments'] = installments
    context.user_data['loan_step'] = LOAN_CONFIRM
    
    amount = context.user_data['loan_amount']
    interest_rate = int(get_loan_setting('loan_interest_rate_percent') or 5)
    installment_amount = calculate_installments(amount, interest_rate, installments)
    
    confirm_text = f"""✅ **تأیید درخواست وام**
━━━━━━━━━━━━━━━━━━━
💰 مبلغ وام: {amount} ART
📊 نرخ سود: {interest_rate}%
📅 تعداد اقساط: {installments}
💵 مبلغ هر قسط: {installment_amount:.0f} ART
━━━━━━━━━━━━━━━━━━━

آیا اطلاعات صحیح است؟"""
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تأیید و دریافت وام", callback_data="loan_confirm_yes")],
        [InlineKeyboardButton("❌ انصراف", callback_data="loan_confirm_no")]
    ])
    await update.message.reply_text(confirm_text, reply_markup=keyboard, parse_mode='Markdown')
    return LOAN_CONFIRM

async def loan_confirm_callback(update: Update, context):
    query = update.callback_query
    await query.answer()
    
    if query.data == "loan_confirm_yes":
        user_id = update.effective_user.id
        user = get_user_by_telegram_id(user_id)
        if not user:
            await query.edit_message_text("❌ خطا: کاربر یافت نشد.")
            return ConversationHandler.END
        
        # بررسی قفل بودن وام برای شهروندان (دوباره)
        if user['role'] == 'citizen':
            loan_enabled = get_loan_setting('loan_enabled_for_citizens')
            if loan_enabled == '0':
                await query.edit_message_text("❌ بخش وام در حال حاضر برای شهروندان غیرفعال است.")
                return ConversationHandler.END
        
        acc = get_account_by_user_id(user['id'])
        if not acc:
            await query.edit_message_text("❌ خطا: حساب بانکی یافت نشد.")
            return ConversationHandler.END
        
        # بررسی مجدد وام فعال
        if has_active_loan(acc['id']):
            await query.edit_message_text("❌ شما قبلاً یک وام فعال دارید.")
            return ConversationHandler.END
        
        amount = context.user_data.get('loan_amount')
        installments = context.user_data.get('loan_installments')
        interest_rate = int(get_loan_setting('loan_interest_rate_percent') or 5)
        
        if not amount or not installments:
            await query.edit_message_text("❌ خطا: اطلاعات ناقص. لطفاً دوباره تلاش کنید.")
            return ConversationHandler.END
        
        # ایجاد وام
        loan_id = create_loan(acc['id'], amount, installments, interest_rate)
        
        # واریز مبلغ وام به حساب کاربر
        new_balance = acc['balance'] + amount
        db = get_db()
        c = db.cursor()
        c.execute('UPDATE accounts SET balance = ? WHERE id = ?', (new_balance, acc['id']))
        
        # ثبت تراکنش
        txid = generate_txid()
        c.execute('''INSERT INTO transactions (txid, receiver_account, amount, type, reason)
                     VALUES (?, ?, ?, 'loan', 'دریافت وام')''',
                  (txid, acc['account_number'], amount))
        db.commit()
        db.close()
        
        log_audit(user_id, 'loan_request', f'amount:{amount}', f'installments:{installments}')
        
        await query.edit_message_text(
            f"✅ **وام شما با موفقیت پرداخت شد!**\n\n"
            f"💰 مبلغ {amount} ART به حساب شما واریز شد.\n"
            f"📅 تعداد اقساط: {installments}\n"
            f"📋 برای مشاهده اقساط و پرداخت، به بخش وام مراجعه کنید.\n\n"
            f"موجودی جدید: {new_balance} ART",
            reply_markup=main_menu_keyboard(user['role']),
            parse_mode='Markdown'
        )
        
        # پاک کردن اطلاعات گفت‌وگو
        for key in ['loan_amount', 'loan_installments', 'loan_step']:
            context.user_data.pop(key, None)
        return ConversationHandler.END
    else:
        await query.edit_message_text("❌ درخواست وام لغو شد.", reply_markup=main_menu_keyboard(get_user_role_display(update.effective_user.id)))
        for key in ['loan_amount', 'loan_installments', 'loan_step']:
            context.user_data.pop(key, None)
        return ConversationHandler.END

async def loan_pay_start(update: Update, context):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    user = get_user_by_telegram_id(user_id)
    if not user:
        await query.edit_message_text("❌ حساب ندارید.")
        return
    
    acc = get_account_by_user_id(user['id'])
    if not acc:
        await query.edit_message_text("❌ حساب بانکی یافت نشد.")
        return
    
    loan = get_active_loan(acc['id'])
    if not loan:
        await query.edit_message_text(
            "❌ شما هیچ وام فعالی ندارید.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="loan")]])
        )
        return
    
    # اعمال جریمه‌های احتمالی قبل از نمایش
    apply_loan_penalties(loan['id'])
    
    # دریافت اقساط پرداخت نشده
    db = get_db()
    c = db.cursor()
    c.execute('SELECT * FROM loan_payments WHERE loan_id = ? AND status = "pending" ORDER BY installment_number', (loan['id'],))
    payments = c.fetchall()
    db.close()
    
    if not payments:
        await query.edit_message_text(
            "✅ همه اقساط وام شما پرداخت شده است!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="loan")]])
        )
        return
    
    payment = payments[0]
    due_date = datetime.strptime(payment['due_date'], '%Y-%m-%d %H:%M:%S.%f')
    now = datetime.now(TEHRAN_TZ)
    is_delayed = now > due_date
    delay_days = (now - due_date).days if is_delayed else 0
    
    context.user_data['loan_payment_id'] = payment['id']
    
    pay_text = f"""💰 **پرداخت قسط وام**
━━━━━━━━━━━━━━━━━━━
📌 شماره قسط: {payment['installment_number']} از {loan['installments']}
💰 مبلغ قسط: {payment['amount']} ART
💸 جریمه دیرکرد: {payment['fine']} ART
🔴 وضعیت: {'⚠️ معوق' if is_delayed else '✅ در موعد'}
⏰ تاریخ سررسید: {due_date.strftime('%Y/%m/%d')}
📅 تأخیر: {delay_days} روز
━━━━━━━━━━━━━━━━━━━
💵 **مبلغ قابل پرداخت: {payment['amount'] + payment['fine']} ART**

آیا می‌خواهید این قسط را پرداخت کنید؟"""
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ پرداخت", callback_data="loan_pay_confirm")],
        [InlineKeyboardButton("🔙 انصراف", callback_data="loan")]
    ])
    await query.edit_message_text(pay_text, reply_markup=keyboard, parse_mode='Markdown')

async def loan_pay_confirm(update: Update, context):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    user = get_user_by_telegram_id(user_id)
    if not user:
        await query.edit_message_text("❌ خطا: کاربر یافت نشد.")
        return
    
    acc = get_account_by_user_id(user['id'])
    if not acc:
        await query.edit_message_text("❌ خطا: حساب بانکی یافت نشد.")
        return
    
    payment_id = context.user_data.get('loan_payment_id')
    if not payment_id:
        await query.edit_message_text("❌ خطا: اطلاعات پرداخت یافت نشد.")
        return
    
    db = get_db()
    c = db.cursor()
    c.execute('SELECT * FROM loan_payments WHERE id = ?', (payment_id,))
    payment = c.fetchone()
    if not payment or payment['status'] == 'paid':
        db.close()
        await query.edit_message_text("❌ این قسط قبلاً پرداخت شده است.")
        return
    
    amount_to_pay = payment['amount'] + payment['fine']
    
    if acc['balance'] < amount_to_pay:
        db.close()
        await query.edit_message_text(
            f"❌ موجودی کافی نیست.\n"
            f"مورد نیاز: {amount_to_pay} ART\n"
            f"موجودی شما: {acc['balance']} ART",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="loan")]])
        )
        return
    
    # پرداخت قسط
    new_balance = acc['balance'] - amount_to_pay
    c.execute('UPDATE accounts SET balance = ? WHERE id = ?', (new_balance, acc['id']))
    c.execute('UPDATE loan_payments SET status = "paid", paid_date = ? WHERE id = ?', 
              (datetime.now(TEHRAN_TZ), payment_id))
    
    # به‌روزرسانی وام
    c.execute('UPDATE loans SET paid_installments = paid_installments + 1 WHERE id = ?', (payment['loan_id'],))
    
    # بررسی تسویه کامل وام
    c.execute('SELECT paid_installments, installments, amount FROM loans WHERE id = ?', (payment['loan_id'],))
    loan = c.fetchone()
    if loan['paid_installments'] == loan['installments']:
        c.execute('UPDATE loans SET status = "paid" WHERE id = ?', (payment['loan_id'],))
        bonus_percent = int(get_loan_setting('loan_early_payment_bonus_percent') or 20)
        bonus_score = (loan['amount'] * bonus_percent // 100)
        if bonus_score > 0:
            new_score = acc['credit_score'] + bonus_score
            c.execute('UPDATE accounts SET credit_score = ? WHERE id = ?', (new_score, acc['id']))
            c.execute('INSERT INTO credit_history (account_id, old_score, new_score, reason) VALUES (?, ?, ?, ?)',
                      (acc['id'], acc['credit_score'], new_score, f'پاداش تسویه زودهنگام وام'))
            await send_message_to_user(context, user_id, f"🎉 تبریک! شما وام خود را تسویه کردید و {bonus_score} امتیاز اعتباری پاداش گرفتید.")
    
    # ثبت تراکنش
    txid = generate_txid()
    c.execute('''INSERT INTO transactions (txid, sender_account, amount, fee, reason, type)
                 VALUES (?, ?, ?, ?, ?, 'loan_payment')''',
              (txid, acc['account_number'], amount_to_pay, payment['fine'], f'پرداخت قسط {payment["installment_number"]} وام'))
    
    db.commit()
    db.close()
    
    log_audit(user_id, 'loan_payment', f'amount:{amount_to_pay}', f'installment:{payment["installment_number"]}')
    
    # بررسی اینکه آیا قسط دیگری باقی مانده است
    db2 = get_db()
    c2 = db2.cursor()
    c2.execute('SELECT id FROM loan_payments WHERE loan_id = ? AND status = "pending" ORDER BY installment_number', (payment['loan_id'],))
    remaining = c2.fetchone()
    db2.close()
    
    if remaining:
        await query.edit_message_text(
            f"✅ **قسط شماره {payment['installment_number']} با موفقیت پرداخت شد!**\n\n"
            f"💰 مبلغ پرداختی: {amount_to_pay} ART\n"
            f"📦 موجودی جدید: {new_balance} ART\n\n"
            f"⚠️ قسط بعدی شما هنوز پرداخت نشده است. لطفاً برای پرداخت قسط بعدی دوباره به بخش وام مراجعه کنید.",
            reply_markup=main_menu_keyboard(user['role']),
            parse_mode='Markdown'
        )
    else:
        await query.edit_message_text(
            f"✅ **قسط شماره {payment['installment_number']} با موفقیت پرداخت شد!**\n\n"
            f"💰 مبلغ پرداختی: {amount_to_pay} ART\n"
            f"📦 موجودی جدید: {new_balance} ART\n\n"
            f"🎉 **تبریک! وام شما به طور کامل تسویه شد.**",
            reply_markup=main_menu_keyboard(user['role']),
            parse_mode='Markdown'
        )
    
    # بررسی بلوکه شدن حساب در صورت کاهش امتیاز
    if check_and_block_low_credit(acc['id']):
        await send_message_to_user(context, user_id, "⚠️ **هشدار**: امتیاز اعتباری شما بسیار پایین آمده است. حساب شما مسدود شد. لطفاً با پشتیبانی تماس بگیرید.")
    
    context.user_data.pop('loan_payment_id', None)

async def loan_status_callback(update: Update, context):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    user = get_user_by_telegram_id(user_id)
    if not user:
        await query.edit_message_text("❌ حساب ندارید.")
        return
    
    acc = get_account_by_user_id(user['id'])
    if not acc:
        await query.edit_message_text("❌ حساب بانکی یافت نشد.")
        return
    
    loan = get_active_loan(acc['id'])
    if not loan:
        await query.edit_message_text(
            "❌ شما هیچ وام فعالی ندارید.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="loan")]])
        )
        return
    
    # اعمال جریمه‌های احتمالی
    apply_loan_penalties(loan['id'])
    
    # دریافت اطلاعات به‌روز وام
    db = get_db()
    c = db.cursor()
    c.execute('SELECT * FROM loans WHERE id = ?', (loan['id'],))
    loan = c.fetchone()
    
    # دریافت اقساط
    c.execute('SELECT * FROM loan_payments WHERE loan_id = ? ORDER BY installment_number', (loan['id'],))
    payments = c.fetchall()
    db.close()
    
    info = format_loan_info(loan, acc)
    
    payments_text = "\n\n📋 **لیست اقساط:**\n"
    for p in payments:
        status_icon = "✅" if p['status'] == 'paid' else "⏳"
        due = datetime.strptime(p['due_date'], '%Y-%m-%d %H:%M:%S.%f')
        due_str = due.strftime('%Y/%m/%d')
        payments_text += f"{status_icon} قسط {p['installment_number']}: {p['amount']} ART - سررسید {due_str}"
        if p['fine'] > 0:
            payments_text += f" (جریمه: {p['fine']} ART)"
        payments_text += "\n"
    
    keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="loan")]]
    await query.edit_message_text(
        info + payments_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

# ---------- تنظیمات وام (پنل مدیریت) ----------
async def admin_loan_settings(update: Update, context):
    """نمایش منوی تنظیمات وام"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await query.edit_message_text("⛔ دسترسی ندارید.")
        return
    
    settings = get_all_loan_settings()
    text = "⚙️ **تنظیمات وام بانک کملوت**\n━━━━━━━━━━━━━━━━━━━\n"
    for key, value in settings.items():
        display_name = {
            'loan_min_amount': 'حداقل مبلغ وام',
            'loan_max_amount': 'حداکثر مبلغ وام',
            'loan_grace_period_days': 'مهلت هر قسط (روز)',
            'loan_daily_fine_percent': 'جریمه روزانه (درصد قسط)',
            'loan_daily_credit_penalty': 'کاهش امتیاز روزانه',
            'loan_min_credit_score_to_unblock': 'حداقل امتیاز برای عدم بلوکه',
            'loan_delay_days_to_block': 'تأخیر روز برای بلوکه حساب',
            'loan_interest_rate_percent': 'نرخ سود وام (درصد)',
            'loan_early_payment_bonus_percent': 'پاداش تسویه زودهنگام (درصد)',
            'loan_max_multiplier_turnover': 'ضریب گردش مالی',
            'loan_credit_score_divider': 'تقسیم‌کننده امتیاز اعتباری',
            'loan_default_installments': 'تعداد اقساط پیش‌فرض',
            'loan_enabled_for_citizens': 'فعال بودن وام برای شهروندان'
        }.get(key, key)
        # نمایش وضعیت فعال/غیرفعال برای کلید مربوطه
        if key == 'loan_enabled_for_citizens':
            value_display = "✅ فعال" if value == '1' else "❌ غیرفعال"
        else:
            value_display = value
        text += f"• **{display_name}**: `{value_display}`\n"
    
    text += "\nبرای تغییر هر مقدار، روی دکمه مربوطه کلیک کنید."
    
    keyboard = []
    for key in settings.keys():
        display_name = {
            'loan_min_amount': 'حداقل مبلغ',
            'loan_max_amount': 'حداکثر مبلغ',
            'loan_grace_period_days': 'مهلت هر قسط',
            'loan_daily_fine_percent': 'جریمه روزانه',
            'loan_daily_credit_penalty': 'کاهش امتیاز روزانه',
            'loan_min_credit_score_to_unblock': 'حداقل امتیاز',
            'loan_delay_days_to_block': 'تأخیر برای بلوکه',
            'loan_interest_rate_percent': 'نرخ سود',
            'loan_early_payment_bonus_percent': 'پاداش تسویه',
            'loan_max_multiplier_turnover': 'ضریب گردش مالی',
            'loan_credit_score_divider': 'تقسیم‌کننده امتیاز',
            'loan_default_installments': 'تعداد اقساط پیش‌فرض',
            'loan_enabled_for_citizens': 'فعال بودن وام برای شهروندان'
        }.get(key, key)
        keyboard.append([InlineKeyboardButton(f"✏️ {display_name}", callback_data=f"loan_setting_{key}")])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="back_to_panel")])
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def loan_setting_click(update: Update, context):
    query = update.callback_query
    await query.answer()
    key = query.data.replace("loan_setting_", "")
    context.user_data['loan_setting_key'] = key
    current_value = get_loan_setting(key)
    
    # اگر کلید فعال/غیرفعال است، توضیح جداگانه
    if key == 'loan_enabled_for_citizens':
        await query.edit_message_text(
            f"⚙️ **تغییر وضعیت وام برای شهروندان**\n\n"
            f"وضعیت فعلی: {'فعال' if current_value == '1' else 'غیرفعال'}\n\n"
            f"لطفاً مقدار جدید را وارد کنید:\n"
            f"`1` برای فعال\n"
            f"`0` برای غیرفعال\n"
            f"(برای لغو /cancel بزنید)",
            parse_mode='Markdown'
        )
    else:
        await query.edit_message_text(
            f"⚙️ **تغییر تنظیمات وام**\n\n"
            f"کلید: `{key}`\n"
            f"مقدار فعلی: `{current_value}`\n\n"
            f"لطفاً مقدار جدید (عدد صحیح) را وارد کنید:\n"
            f"(برای لغو /cancel بزنید)",
            parse_mode='Markdown'
        )
    return SETTING_VALUE

async def loan_setting_value_handler(update: Update, context):
    text = update.message.text.strip()
    user_id = update.effective_user.id
    if text.lower() == '/cancel':
        await update.message.reply_text("❌ تغییر تنظیمات لغو شد.", reply_markup=main_menu_keyboard(get_user_role_display(user_id)))
        context.user_data.pop('loan_setting_key', None)
        return ConversationHandler.END
    
    key = context.user_data.get('loan_setting_key')
    if not key:
        await update.message.reply_text("❌ خطا: کلید تنظیمات یافت نشد.")
        return ConversationHandler.END
    
    # اعتبارسنجی
    if key == 'loan_enabled_for_citizens':
        if text not in ['0', '1']:
            await update.message.reply_text("❌ مقدار باید 0 (غیرفعال) یا 1 (فعال) باشد. لطفاً دوباره وارد کنید:")
            return SETTING_VALUE
        new_value = text
    else:
        try:
            new_value = int(text)
            if new_value < 0:
                raise ValueError
        except:
            await update.message.reply_text("❌ مقدار باید یک عدد صحیح مثبت باشد. لطفاً دوباره وارد کنید:")
            return SETTING_VALUE
        new_value = str(new_value)
    
    set_loan_setting(key, new_value)
    log_audit(user_id, 'loan_setting_change', key, new_value)
    await update.message.reply_text(
        f"✅ تنظیمات وام با موفقیت به‌روز شد!\n"
        f"`{key}` = `{new_value}`",
        parse_mode='Markdown',
        reply_markup=main_menu_keyboard(get_user_role_display(user_id))
    )
    context.user_data.pop('loan_setting_key', None)
    return ConversationHandler.END

async def placeholder_handler(update: Update, context):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "⏳ این بخش در حال تکمیل است... به زودی اضافه خواهد شد.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_menu")]])
    )

def main():
    init_db()
    # اطمینان از وجود تنظیم loan_enabled_for_citizens در دیتابیس (اگر نبود ایجاد کن)
    if get_loan_setting('loan_enabled_for_citizens') is None:
        set_loan_setting('loan_enabled_for_citizens', '1')
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # ثبت‌نام
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME_REAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_handler)],
            NAME_CAMELOT: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_handler)],
            NATIONAL_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_handler)],
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_handler)],
            CONFIRM: [CallbackQueryHandler(confirm_callback)],
        },
        fallbacks=[CommandHandler("start", start), CommandHandler("cancel", cancel)],
    ))
    
    # انتقال وجه
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(transfer_start, pattern="^transfer$")],
        states={
            TRANSFER_ACCOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, transfer_account_handler)],
            TRANSFER_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, transfer_amount_handler)],
            TRANSFER_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, transfer_reason_handler)],
            TRANSFER_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, transfer_password_handler)],
        },
        fallbacks=[CommandHandler("start", start), CommandHandler("cancel", cancel)],
    ))
    
    # وام - دریافت وام
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(loan_request_start, pattern="^loan_request$")],
        states={
            LOAN_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, loan_amount_handler)],
            LOAN_INSTALLMENTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, loan_installments_handler)],
            LOAN_CONFIRM: [CallbackQueryHandler(loan_confirm_callback)],
        },
        fallbacks=[CommandHandler("start", start), CommandHandler("cancel", cancel)],
    ))
    
    # پرداخت وام
    app.add_handler(CallbackQueryHandler(loan_pay_start, pattern="^loan_pay$"))
    app.add_handler(CallbackQueryHandler(loan_pay_confirm, pattern="^loan_pay_confirm$"))
    
    # وضعیت وام
    app.add_handler(CallbackQueryHandler(loan_status_callback, pattern="^loan_status$"))
    
    # تنظیمات وام
    loan_setting_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(loan_setting_click, pattern="^loan_setting_")],
        states={
            SETTING_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, loan_setting_value_handler)],
        },
        fallbacks=[CommandHandler("start", start), CommandHandler("cancel", cancel)],
    )
    app.add_handler(loan_setting_conv)
    app.add_handler(CallbackQueryHandler(admin_loan_settings, pattern="^admin_loan_settings$"))
    
    # سایر هندلرها
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    
    app.add_handler(CallbackQueryHandler(loan_menu_callback, pattern="^loan$"))
    app.add_handler(CallbackQueryHandler(balance_callback, pattern="^balance$"))
    app.add_handler(CallbackQueryHandler(my_info_callback, pattern="^my_info$"))
    app.add_handler(CallbackQueryHandler(my_credit_callback, pattern="^my_credit$"))
    app.add_handler(CallbackQueryHandler(panel_callback, pattern="^panel$"))
    app.add_handler(CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"))
    app.add_handler(CallbackQueryHandler(back_to_panel, pattern="^back_to_panel$"))
    app.add_handler(CallbackQueryHandler(refresh_role, pattern="^refresh_role$"))
    
    # placeholder برای بخش‌های ناقص
    for p in ["my_transactions","notifications","settings","change_account","support",
              "admin_users","admin_finance","admin_treasury","admin_requests"]:
        app.add_handler(CallbackQueryHandler(placeholder_handler, pattern=f"^{p}$"))
    
    print("✅ ربات بانک کملوت روشن شد!")
    app.run_polling()

if __name__ == "__main__":
    main()