import logging
from datetime import datetime, timedelta
import pytz
import jdatetime
import asyncio
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
    generate_txid, log_audit, get_user_transactions, get_transaction_details,
    send_notification
)
from utils import (
    create_bank_account, format_balance, format_receipt,
    format_transaction_summary, format_transaction_detail
)

TEHRAN_TZ = pytz.timezone('Asia/Tehran')
TRANSACTIONS_PER_PAGE = 10

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

NAME_REAL, NAME_CAMELOT, NATIONAL_ID, PASSWORD, CONFIRM = range(5)
TRANSFER_ACCOUNT, TRANSFER_AMOUNT, TRANSFER_REASON, TRANSFER_PASSWORD = range(10, 14)
BROADCAST_MESSAGE, BROADCAST_CONFIRM = range(30, 32)
SUPPORT_MESSAGE = 40

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
        [InlineKeyboardButton("📜 تراکنش‌های من", callback_data="my_transactions")],
        [InlineKeyboardButton("👤 اطلاعات حساب", callback_data="my_info")],
        [InlineKeyboardButton("📬 صندوق پیام", callback_data="notifications")],
        [InlineKeyboardButton("🔄 تغییر شماره حساب", callback_data="change_account")],
        [InlineKeyboardButton("📈 اعتبار بانکی من", callback_data="my_credit")],
        [InlineKeyboardButton("🆘 پشتیبانی", callback_data="support")],
    ]
    if user_role in ['king', 'owner', 'employee']:
        keyboard.append([InlineKeyboardButton("👑 پنل مدیریت", callback_data="panel")])
    return InlineKeyboardMarkup(keyboard)

# ---------- شروع و لغو ----------
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

# ---------- بخش‌های عادی ----------
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
        [InlineKeyboardButton("📣 ارسال پیام همگانی", callback_data="admin_broadcast")],
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

# ---------- بخش وام (غیرفعال) ----------
async def loan_disabled_handler(update: Update, context):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "⏳ **بخش وام در حال به‌روزرسانی است**\n\n"
        "این بخش به زودی با امکانات کامل‌تر فعال خواهد شد.\n"
        "از صبر شما متشکریم.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_menu")]]),
        parse_mode='Markdown'
    )

# ---------- بخش تراکنش‌های من ----------
async def my_transactions_menu(update: Update, context):
    """نمایش مستقیم لیست تراکنش‌ها (بدون فیلتر)"""
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
    
    context.user_data['trans_type'] = 'all'
    context.user_data['trans_page'] = 0
    await show_transactions(update, context, tx_type=None, page=0)

async def show_transactions(update: Update, context, tx_type=None, page=0):
    """نمایش لیست تراکنش‌ها با صفحه‌بندی و علامت +/- و طرف مقابل"""
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
    
    offset = page * TRANSACTIONS_PER_PAGE
    transactions, total = get_user_transactions(user['id'], TRANSACTIONS_PER_PAGE, offset, tx_type)
    
    if not transactions:
        await query.edit_message_text(
            "📭 شما هیچ تراکنشی ندارید.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_menu")]])
        )
        return
    
    text = f"📊 **لیست تراکنش‌ها** (صفحه {page+1})\n━━━━━━━━━━━━━━━━━━━\n\n"
    
    for tx in transactions:
        text += format_transaction_summary(tx, acc['account_number']) + "\n━━━━━━━━━━━━━━━━━━━\n"
    
    total_pages = (total + TRANSACTIONS_PER_PAGE - 1) // TRANSACTIONS_PER_PAGE
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"trans_page_{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("➡️ بعدی", callback_data=f"trans_page_{page+1}"))
    
    keyboard = []
    if nav_buttons:
        keyboard.append(nav_buttons)
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به منو", callback_data="back_to_menu")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def transactions_page_handler(update: Update, context):
    """هندلر صفحه‌بندی تراکنش‌ها"""
    query = update.callback_query
    data = query.data
    parts = data.split('_')
    page = int(parts[2])  # trans_page_{page}
    context.user_data['trans_page'] = page
    await show_transactions(update, context, tx_type=None, page=page)

# ---------- ارسال پیام همگانی (فقط مدیران) ----------
async def admin_broadcast_start(update: Update, context):
    """شروع فرآیند ارسال پیام همگانی"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await query.edit_message_text("⛔ دسترسی ندارید.")
        return
    
    await query.edit_message_text(
        "📣 **ارسال پیام همگانی**\n\n"
        "لطفاً متن پیام خود را وارد کنید:\n"
        "(برای لغو /cancel بزنید)",
        parse_mode='Markdown'
    )
    return BROADCAST_MESSAGE

async def admin_broadcast_receive(update: Update, context):
    """دریافت متن پیام از مدیر"""
    text = update.message.text
    if text.lower() == '/cancel':
        await update.message.reply_text("❌ ارسال پیام لغو شد.", reply_markup=main_menu_keyboard(get_user_role_display(update.effective_user.id)))
        return ConversationHandler.END
    
    context.user_data['broadcast_text'] = text
    context.user_data['broadcast_step'] = BROADCAST_CONFIRM
    
    # دریافت تعداد کاربران
    db = get_db()
    c = db.cursor()
    c.execute('SELECT COUNT(DISTINCT user_id) FROM accounts')
    count = c.fetchone()[0]
    db.close()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ بله، ارسال کن", callback_data="broadcast_yes")],
        [InlineKeyboardButton("❌ لغو", callback_data="broadcast_no")]
    ])
    
    await update.message.reply_text(
        f"📣 **تأیید ارسال پیام همگانی**\n\n"
        f"📝 متن پیام:\n```\n{text}\n```\n\n"
        f"👥 تعداد گیرندگان: {count} کاربر\n\n"
        f"آیا از ارسال این پیام مطمئن هستید؟",
        reply_markup=keyboard,
        parse_mode='Markdown'
    )
    return BROADCAST_CONFIRM

async def admin_broadcast_confirm(update: Update, context):
    """تأیید نهایی و ارسال پیام"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    if query.data == "broadcast_yes":
        text = context.user_data.get('broadcast_text')
        if not text:
            await query.edit_message_text("❌ خطا: متن پیام یافت نشد.")
            return ConversationHandler.END
        
        # دریافت همه کاربران دارای حساب (با telegram_id)
        db = get_db()
        c = db.cursor()
        c.execute('''
            SELECT DISTINCT users.id as user_id, users.telegram_id 
            FROM accounts 
            JOIN users ON accounts.user_id = users.id
        ''')
        users = c.fetchall()
        db.close()
        
        if not users:
            await query.edit_message_text("❌ هیچ کاربری برای ارسال پیام وجود ندارد.")
            return ConversationHandler.END
        
        await query.edit_message_text(
            f"📣 در حال ارسال پیام به {len(users)} کاربر...\nلطفاً صبر کنید.",
            parse_mode='Markdown'
        )
        
        success_count = 0
        fail_count = 0
        
        for u in users:
            try:
                await context.bot.send_message(
                    u['telegram_id'],
                    f"📣 **پیام همگانی بانک کملوت**\n\n{text}",
                    parse_mode='Markdown'
                )
                send_notification(u['user_id'], 'پیام همگانی', text)
                success_count += 1
            except Exception as e:
                logger.error(f"خطا در ارسال به {u['telegram_id']}: {e}")
                fail_count += 1
            
            await asyncio.sleep(0.05)
        
        await log_to_channel(
            context,
            f"📣 **پیام همگانی ارسال شد**\n"
            f"تعداد موفق: {success_count}\n"
            f"تعداد ناموفق: {fail_count}\n"
            f"ارسال‌کننده: {get_user_role_display(user_id)}"
        )
        
        await query.edit_message_text(
            f"✅ **پیام همگانی با موفقیت ارسال شد!**\n\n"
            f"✅ موفق: {success_count}\n"
            f"❌ ناموفق: {fail_count}",
            reply_markup=main_menu_keyboard(get_user_role_display(user_id))
        )
        
    else:  # broadcast_no
        await query.edit_message_text(
            "❌ ارسال پیام لغو شد.",
            reply_markup=main_menu_keyboard(get_user_role_display(user_id))
        )
    
    context.user_data.pop('broadcast_text', None)
    context.user_data.pop('broadcast_step', None)
    return ConversationHandler.END

# ---------- پشتیبانی ----------
async def support_start(update: Update, context):
    """ورود به بخش پشتیبانی"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    user = get_user_by_telegram_id(user_id)
    if not user:
        await query.edit_message_text("❌ حساب ندارید. لطفاً /start بزنید.")
        return
    
    await query.edit_message_text(
        "🆘 **پشتیبانی بانک کملوت**\n\n"
        "لطفاً پیام خود را بنویسید.\n"
        "پیام شما مستقیماً برای مدیریت ارسال می‌شود.\n\n"
        "(برای لغو /cancel بزنید)",
        parse_mode='Markdown'
    )
    return SUPPORT_MESSAGE

async def support_receive(update: Update, context):
    """دریافت پیام پشتیبانی از کاربر و ارسال به مالک و شاه"""
    text = update.message.text
    user_id = update.effective_user.id
    user = get_user_by_telegram_id(user_id)
    
    if text.lower() == '/cancel':
        await update.message.reply_text("❌ ارسال پیام پشتیبانی لغو شد.", reply_markup=main_menu_keyboard(user['role'] if user else 'citizen'))
        return ConversationHandler.END
    
    if not user:
        await update.message.reply_text("❌ شما حساب ندارید. لطفاً /start کنید.")
        return ConversationHandler.END
    
    # دریافت اطلاعات کاربر
    acc = get_account_by_user_id(user['id'])
    account_number = acc['account_number'] if acc else 'ندارد'
    
    # ساخت پیام برای ارسال به مدیران
    admin_message = f"""🆘 **پیام جدید پشتیبانی**

👤 کاربر: {user['real_name']} ({user['camelot_name']})
🆔 کد ملی: {user['national_id']}
🏦 شماره حساب: {account_number}
📱 آیدی تلگرام: {user['telegram_id']}

📝 **متن پیام:**
{text}

🕐 زمان: {get_jalali_date()}
"""
    
    # ارسال به مالک و شاه
    sent_to = []
    for admin_id in [OWNER_ID, KING_ID]:
        try:
            await context.bot.send_message(admin_id, admin_message, parse_mode='Markdown')
            sent_to.append(admin_id)
        except Exception as e:
            logger.error(f"خطا در ارسال پیام پشتیبانی به {admin_id}: {e}")
    
    if sent_to:
        await update.message.reply_text(
            "✅ **پیام شما با موفقیت ارسال شد.**\n\n"
            "کارشناسان ما در اسرع وقت با شما تماس خواهند گرفت.",
            reply_markup=main_menu_keyboard(user['role']),
            parse_mode='Markdown'
        )
        
        # لاگ در کانال
        await log_to_channel(
            context,
            f"🆘 **درخواست پشتیبانی جدید**\n"
            f"از: {user['camelot_name']} ({user['telegram_id']})"
        )
    else:
        await update.message.reply_text(
            "❌ متأسفانه ارسال پیام با مشکل مواجه شد.\n"
            "لطفاً بعداً دوباره تلاش کنید.",
            reply_markup=main_menu_keyboard(user['role'])
        )
    
    return ConversationHandler.END

# ---------- صندوق پیام برای کاربران عادی ----------
async def notifications_menu(update: Update, context):
    """نمایش صندوق پیام کاربر"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    user = get_user_by_telegram_id(user_id)
    if not user:
        await query.edit_message_text("❌ حساب ندارید.")
        return
    
    db = get_db()
    c = db.cursor()
    c.execute('''
        SELECT * FROM notifications 
        WHERE user_id = ? 
        ORDER BY created_at DESC 
        LIMIT 20
    ''', (user['id'],))
    notifications = c.fetchall()
    db.close()
    
    if not notifications:
        await query.edit_message_text(
            "📭 **صندوق پیام شما خالی است.**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_menu")]]),
            parse_mode='Markdown'
        )
        return
    
    text = "📬 **صندوق پیام شما**\n━━━━━━━━━━━━━━━━━━━\n\n"
    for n in notifications:
        created = datetime.strptime(n['created_at'], '%Y-%m-%d %H:%M:%S')
        jcreated = jdatetime.datetime.fromgregorian(datetime=created)
        date_str = jcreated.strftime('%Y/%m/%d - %H:%M')
        
        status_icon = "✅" if n['is_read'] else "🔵"
        text += f"{status_icon} **{n['title']}**\n"
        text += f"📝 {n['message']}\n"
        text += f"🕐 {date_str}\n━━━━━━━━━━━━━━━━━━━\n"
        
        if not n['is_read']:
            db2 = get_db()
            c2 = db2.cursor()
            c2.execute('UPDATE notifications SET is_read = 1 WHERE id = ?', (n['id'],))
            db2.commit()
            db2.close()
    
    keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_menu")]]
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

# ---------- placeholder ----------
async def placeholder_handler(update: Update, context):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "⏳ این بخش در حال تکمیل است... به زودی اضافه خواهد شد.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_menu")]])
    )

# ---------- main ----------
def main():
    init_db()
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
    
    # ارسال پیام همگانی
    broadcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_broadcast_start, pattern="^admin_broadcast$")],
        states={
            BROADCAST_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_broadcast_receive)],
            BROADCAST_CONFIRM: [CallbackQueryHandler(admin_broadcast_confirm)],
        },
        fallbacks=[CommandHandler("start", start), CommandHandler("cancel", cancel)],
    )
    app.add_handler(broadcast_conv)
    
    # پشتیبانی
    support_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(support_start, pattern="^support$")],
        states={
            SUPPORT_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, support_receive)],
        },
        fallbacks=[CommandHandler("start", start), CommandHandler("cancel", cancel)],
    )
    app.add_handler(support_conv)
    
    # دستورات اصلی
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    
    # کالبک‌های اصلی
    app.add_handler(CallbackQueryHandler(balance_callback, pattern="^balance$"))
    app.add_handler(CallbackQueryHandler(my_info_callback, pattern="^my_info$"))
    app.add_handler(CallbackQueryHandler(my_credit_callback, pattern="^my_credit$"))
    app.add_handler(CallbackQueryHandler(panel_callback, pattern="^panel$"))
    app.add_handler(CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"))
    app.add_handler(CallbackQueryHandler(back_to_panel, pattern="^back_to_panel$"))
    app.add_handler(CallbackQueryHandler(refresh_role, pattern="^refresh_role$"))
    
    # تراکنش‌های من
    app.add_handler(CallbackQueryHandler(my_transactions_menu, pattern="^my_transactions$"))
    app.add_handler(CallbackQueryHandler(transactions_page_handler, pattern="^trans_page_"))
    
    # صندوق پیام
    app.add_handler(CallbackQueryHandler(notifications_menu, pattern="^notifications$"))
    
    # وام غیرفعال
    app.add_handler(CallbackQueryHandler(loan_disabled_handler, pattern="^loan$"))
    app.add_handler(CallbackQueryHandler(loan_disabled_handler, pattern="^loan_request$"))
    app.add_handler(CallbackQueryHandler(loan_disabled_handler, pattern="^loan_pay$"))
    app.add_handler(CallbackQueryHandler(loan_disabled_handler, pattern="^loan_status$"))
    
    # placeholder برای بخش‌های ناقص
    for p in ["change_account",
              "admin_users","admin_finance","admin_treasury","admin_requests"]:
        app.add_handler(CallbackQueryHandler(placeholder_handler, pattern=f"^{p}$"))
    
    print("✅ ربات بانک کملوت روشن شد! (بخش وام غیرفعال)")
    app.run_polling()

if __name__ == "__main__":
    main()