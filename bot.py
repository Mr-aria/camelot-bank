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
USERS_PER_PAGE = 10

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

NAME_REAL, NAME_CAMELOT, NATIONAL_ID, PASSWORD, CONFIRM = range(5)
TRANSFER_ACCOUNT, TRANSFER_AMOUNT, TRANSFER_REASON, TRANSFER_PASSWORD = range(10, 14)
BROADCAST_MESSAGE, BROADCAST_CONFIRM = range(30, 32)
SUPPORT_MESSAGE = 40
ADMIN_SUPPORT_REPLY = 50

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
        [InlineKeyboardButton("📣 ارسال پیام همگانی", callback_data="admin_broadcast")],
        [InlineKeyboardButton("📨 پیام‌های پشتیبانی", callback_data="admin_support")],
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
    query = update.callback_query
    data = query.data
    parts = data.split('_')
    page = int(parts[2])
    context.user_data['trans_page'] = page
    await show_transactions(update, context, tx_type=None, page=page)

# ---------- ارسال پیام همگانی ----------
async def admin_broadcast_start(update: Update, context):
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
    text = update.message.text
    if text.lower() == '/cancel':
        await update.message.reply_text("❌ ارسال پیام لغو شد.", reply_markup=main_menu_keyboard(get_user_role_display(update.effective_user.id)))
        return ConversationHandler.END
    
    context.user_data['broadcast_text'] = text
    context.user_data['broadcast_step'] = BROADCAST_CONFIRM
    
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
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    if query.data == "broadcast_yes":
        text = context.user_data.get('broadcast_text')
        if not text:
            await query.edit_message_text("❌ خطا: متن پیام یافت نشد.")
            return ConversationHandler.END
        
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
        
    else:
        await query.edit_message_text(
            "❌ ارسال پیام لغو شد.",
            reply_markup=main_menu_keyboard(get_user_role_display(user_id))
        )
    
    context.user_data.pop('broadcast_text', None)
    context.user_data.pop('broadcast_step', None)
    return ConversationHandler.END

# ---------- پشتیبانی (برای کاربران) ----------
async def support_start(update: Update, context):
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
        "(برای لغو /cancel بزنید)",
        parse_mode='Markdown'
    )
    return SUPPORT_MESSAGE

async def support_receive(update: Update, context):
    text = update.message.text
    user_id = update.effective_user.id
    user = get_user_by_telegram_id(user_id)
    
    if text.lower() == '/cancel':
        await update.message.reply_text("❌ ارسال پیام پشتیبانی لغو شد.", reply_markup=main_menu_keyboard(user['role'] if user else 'citizen'))
        return ConversationHandler.END
    
    if not user:
        await update.message.reply_text("❌ شما حساب ندارید. لطفاً /start کنید.")
        return ConversationHandler.END
    
    acc = get_account_by_user_id(user['id'])
    account_number = acc['account_number'] if acc else 'ندارد'
    
    db = get_db()
    c = db.cursor()
    c.execute('''
        INSERT INTO support_tickets (user_id, message, status)
        VALUES (?, ?, 'pending')
    ''', (user['id'], text))
    ticket_id = c.lastrowid
    db.commit()
    db.close()
    
    admin_message = f"""🆘 **پیام جدید پشتیبانی** (تیکت #{ticket_id})

👤 کاربر: {user['real_name']} ({user['camelot_name']})
🆔 کد ملی: {user['national_id']}
🏦 شماره حساب: {account_number}
📱 آیدی تلگرام: {user['telegram_id']}

📝 **متن پیام:**
{text}

🕐 زمان: {get_jalali_date()}
"""
    
    try:
        await context.bot.send_message(OWNER_ID, admin_message, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"خطا در ارسال پیام پشتیبانی به مالک: {e}")
    
    await update.message.reply_text(
        "✅ پیام شما ارسال شد.",
        reply_markup=main_menu_keyboard(user['role'])
    )
    
    await log_to_channel(
        context,
        f"🆘 **درخواست پشتیبانی جدید** #{ticket_id}\n"
        f"از: {user['camelot_name']} ({user['telegram_id']})"
    )
    
    return ConversationHandler.END

# ---------- مدیریت پشتیبانی ----------
async def admin_support_list(update: Update, context):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await query.edit_message_text("⛔ دسترسی ندارید.")
        return
    
    db = get_db()
    c = db.cursor()
    c.execute('''
        SELECT st.*, u.camelot_name, u.real_name 
        FROM support_tickets st
        JOIN users u ON st.user_id = u.id
        WHERE st.status = 'pending'
        ORDER BY st.created_at DESC
    ''')
    tickets = c.fetchall()
    db.close()
    
    if not tickets:
        await query.edit_message_text(
            "📭 **هیچ پیام پشتیبانی جدیدی وجود ندارد.**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_panel")]])
        )
        return
    
    text = "📨 **لیست پیام‌های پشتیبانی (در انتظار پاسخ)**\n━━━━━━━━━━━━━━━━━━━\n\n"
    keyboard = []
    
    for t in tickets:
        created = datetime.strptime(t['created_at'], '%Y-%m-%d %H:%M:%S')
        jcreated = jdatetime.datetime.fromgregorian(datetime=created)
        date_str = jcreated.strftime('%Y/%m/%d %H:%M')
        
        text += f"🆔 #{t['id']} - {t['camelot_name']}\n"
        text += f"📝 {t['message'][:50]}{'...' if len(t['message']) > 50 else ''}\n"
        text += f"🕐 {date_str}\n━━━━━━━━━━━━━━━━━━━\n"
        keyboard.append([InlineKeyboardButton(f"📩 پاسخ به #{t['id']}", callback_data=f"support_reply_{t['id']}")])
    
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_panel")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def admin_support_reply_start(update: Update, context):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await query.edit_message_text("⛔ دسترسی ندارید.")
        return
    
    ticket_id = int(query.data.split('_')[2])
    context.user_data['support_ticket_id'] = ticket_id
    
    db = get_db()
    c = db.cursor()
    c.execute('''
        SELECT st.*, u.camelot_name, u.real_name, u.telegram_id 
        FROM support_tickets st
        JOIN users u ON st.user_id = u.id
        WHERE st.id = ?
    ''', (ticket_id,))
    ticket = c.fetchone()
    db.close()
    
    if not ticket:
        await query.edit_message_text("❌ تیکت یافت نشد.")
        return
    
    created = datetime.strptime(ticket['created_at'], '%Y-%m-%d %H:%M:%S')
    jcreated = jdatetime.datetime.fromgregorian(datetime=created)
    date_str = jcreated.strftime('%Y/%m/%d - %H:%M')
    
    await query.edit_message_text(
        f"📩 **پاسخ به تیکت #{ticket_id}**\n━━━━━━━━━━━━━━━━━━━\n"
        f"👤 کاربر: {ticket['camelot_name']} ({ticket['real_name']})\n"
        f"🆔 آیدی تلگرام: {ticket['telegram_id']}\n"
        f"🕐 زمان ارسال: {date_str}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📝 **پیام کاربر:**\n{ticket['message']}\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"لطفاً پاسخ خود را وارد کنید:\n"
        f"(برای لغو /cancel بزنید)",
        parse_mode='Markdown'
    )
    return ADMIN_SUPPORT_REPLY

async def admin_support_reply_receive(update: Update, context):
    text = update.message.text
    user_id = update.effective_user.id
    ticket_id = context.user_data.get('support_ticket_id')
    
    if text.lower() == '/cancel':
        await update.message.reply_text("❌ ارسال پاسخ لغو شد.", reply_markup=main_menu_keyboard(get_user_role_display(user_id)))
        context.user_data.pop('support_ticket_id', None)
        return ConversationHandler.END
    
    if not ticket_id:
        await update.message.reply_text("❌ خطا: شناسه تیکت یافت نشد.")
        return ConversationHandler.END
    
    db = get_db()
    c = db.cursor()
    c.execute('''
        SELECT st.*, u.telegram_id, u.camelot_name 
        FROM support_tickets st
        JOIN users u ON st.user_id = u.id
        WHERE st.id = ?
    ''', (ticket_id,))
    ticket = c.fetchone()
    
    if not ticket:
        db.close()
        await update.message.reply_text("❌ تیکت یافت نشد.")
        return ConversationHandler.END
    
    try:
        await context.bot.send_message(
            ticket['telegram_id'],
            f"📩 **پاسخ به پیام شما** (تیکت #{ticket_id})\n━━━━━━━━━━━━━━━━━━━\n\n"
            f"📝 **پاسخ:**\n{text}\n\n"
            f"🕐 زمان: {get_jalali_date()}",
            parse_mode='Markdown'
        )
        user_received = True
    except Exception as e:
        logger.error(f"خطا در ارسال پاسخ به کاربر {ticket['telegram_id']}: {e}")
        user_received = False
    
    c.execute('''
        UPDATE support_tickets 
        SET reply = ?, status = 'replied', replied_at = CURRENT_TIMESTAMP 
        WHERE id = ?
    ''', (text, ticket_id))
    db.commit()
    db.close()
    
    log_audit(user_id, 'support_reply', f'ticket:{ticket_id}', f'user:{ticket["telegram_id"]}')
    
    if user_received:
        await update.message.reply_text(
            f"✅ **پاسخ شما با موفقیت ارسال شد.**\n\n"
            f"تیکت #{ticket_id} - کاربر: {ticket['camelot_name']}",
            reply_markup=main_menu_keyboard(get_user_role_display(user_id))
        )
    else:
        await update.message.reply_text(
            f"⚠️ **پاسخ در دیتابیس ذخیره شد ولی ارسال به کاربر با خطا مواجه شد.**\n"
            f"تیکت #{ticket_id}",
            reply_markup=main_menu_keyboard(get_user_role_display(user_id))
        )
    
    context.user_data.pop('support_ticket_id', None)
    return ConversationHandler.END

# ---------- مدیریت کاربران (جدید) ----------
async def admin_users_list(update: Update, context, page=0):
    """نمایش لیست کاربران با صفحه‌بندی"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await query.edit_message_text("⛔ دسترسی ندارید.")
        return
    
    db = get_db()
    c = db.cursor()
    
    c.execute('SELECT COUNT(*) FROM users')
    total_users = c.fetchone()[0]
    
    if total_users == 0:
        db.close()
        await query.edit_message_text(
            "📭 **هیچ کاربری در بانک ثبت‌نام نکرده است.**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_panel")]])
        )
        return
    
    offset = page * USERS_PER_PAGE
    c.execute('''
        SELECT u.id, u.telegram_id, u.real_name, u.camelot_name, u.national_id, u.role, u.created_at,
               a.account_number, a.balance, a.blocked_balance, a.credit_score, a.status
        FROM users u
        JOIN accounts a ON u.id = a.user_id
        ORDER BY u.created_at DESC
        LIMIT ? OFFSET ?
    ''', (USERS_PER_PAGE, offset))
    users = c.fetchall()
    db.close()
    
    text = f"👥 **لیست کاربران بانک کملوت**\n━━━━━━━━━━━━━━━━━━━\n"
    text += f"تعداد کل: {total_users} کاربر | صفحه {page+1}\n━━━━━━━━━━━━━━━━━━━\n\n"
    
    for idx, u in enumerate(users, start=offset+1):
        role_names = {'citizen':'شهروند', 'employee':'کارمند', 'king':'شاه', 'owner':'مالک'}
        role_persian = role_names.get(u['role'], 'نامشخص')
        status_persian = "✅ فعال" if u['status'] == 'active' else "🚫 مسدود"
        
        text += f"**{idx}. {u['real_name']}** ({u['camelot_name']})\n"
        text += f"🆔 کدملی: {u['national_id']}\n"
        text += f"🏦 شماره حساب: {u['account_number']}\n"
        text += f"💰 موجودی: {u['balance']} ART\n"
        text += f"🔒 موجودی بلوکه: {u['blocked_balance']} ART\n"
        text += f"⭐ امتیاز اعتباری: {u['credit_score']}\n"
        text += f"👑 نقش: {role_persian}\n"
        text += f"📊 وضعیت: {status_persian}\n"
        text += f"📱 آیدی تلگرام: {u['telegram_id']}\n"
        created = datetime.strptime(u['created_at'], '%Y-%m-%d %H:%M:%S')
        jcreated = jdatetime.datetime.fromgregorian(datetime=created)
        text += f"📅 تاریخ افتتاح: {jcreated.strftime('%Y/%m/%d')}\n"
        text += f"━━━━━━━━━━━━━━━━━━━\n"
    
    keyboard = []
    nav_buttons = []
    total_pages = (total_users + USERS_PER_PAGE - 1) // USERS_PER_PAGE
    
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"admin_users_page_{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("➡️ بعدی", callback_data=f"admin_users_page_{page+1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    keyboard.append([InlineKeyboardButton("🔍 مدیریت کاربر", callback_data="admin_user_manage")])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="back_to_panel")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def admin_users_page_handler(update: Update, context):
    query = update.callback_query
    data = query.data
    page = int(data.split('_')[3])
    await admin_users_list(update, context, page)

async def admin_user_manage_start(update: Update, context):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await query.edit_message_text("⛔ دسترسی ندارید.")
        return
    
    await query.edit_message_text(
        "🔍 **مدیریت کاربر**\n\n"
        "لطفاً کد ملی کملوت کاربر مورد نظر را وارد کنید:\n"
        "(برای لغو /cancel بزنید)",
        parse_mode='Markdown'
    )
    return 'admin_user_search'

async def admin_user_search(update: Update, context):
    text = update.message.text.strip()
    user_id = update.effective_user.id
    
    if text.lower() == '/cancel':
        await update.message.reply_text("❌ مدیریت کاربر لغو شد.", reply_markup=main_menu_keyboard(get_user_role_display(user_id)))
        return ConversationHandler.END
    
    if len(text) != 6 or not text.isdigit():
        await update.message.reply_text("❌ کد ملی باید ۶ رقم باشد. دوباره وارد کنید:")
        return 'admin_user_search'
    
    db = get_db()
    c = db.cursor()
    c.execute('''
        SELECT u.id, u.telegram_id, u.real_name, u.camelot_name, u.national_id, u.role, u.created_at,
               a.id as account_id, a.account_number, a.balance, a.blocked_balance, a.credit_score, 
               a.status, a.password, a.notes
        FROM users u
        JOIN accounts a ON u.id = a.user_id
        WHERE u.national_id = ?
    ''', (text,))
    user = c.fetchone()
    db.close()
    
    if not user:
        await update.message.reply_text("❌ کاربری با این کد ملی یافت نشد. دوباره وارد کنید:")
        return 'admin_user_search'
    
    context.user_data['admin_target_user_id'] = user['id']
    context.user_data['admin_target_account_id'] = user['account_id']
    
    role_names = {'citizen':'شهروند', 'employee':'کارمند', 'king':'شاه', 'owner':'مالک'}
    role_persian = role_names.get(user['role'], 'نامشخص')
    status_persian = "✅ فعال" if user['status'] == 'active' else "🚫 مسدود"
    
    created = datetime.strptime(user['created_at'], '%Y-%m-%d %H:%M:%S')
    jcreated = jdatetime.datetime.fromgregorian(datetime=created)
    date_str = jcreated.strftime('%Y/%m/%d')
    
    info_text = f"""👤 **اطلاعات کاربر**
━━━━━━━━━━━━━━━━━━━
📛 **نام واقعی:** {user['real_name']}
⚔️ **نام کملوتی:** {user['camelot_name']}
🆔 **کد ملی:** {user['national_id']}
🏦 **شماره حساب:** `{user['account_number']}`
🔐 **رمز حساب:** `{user['password']}`
💰 **موجودی:** {user['balance']} ART
🔒 **موجودی بلوکه:** {user['blocked_balance']} ART
⭐ **امتیاز اعتباری:** {user['credit_score']}
👑 **نقش:** {role_persian}
📊 **وضعیت:** {status_persian}
📱 **آیدی تلگرام:** `{user['telegram_id']}`
📅 **تاریخ افتتاح:** {date_str}
📝 **یادداشت:** {user['notes'] or 'ندارد'}
━━━━━━━━━━━━━━━━━━━
"""
    
    keyboard = [
        [InlineKeyboardButton("✏️ تغییر نام کملوتی", callback_data=f"admin_edit_camelot_{user['id']}")],
        [InlineKeyboardButton("📱 تغییر آیدی تلگرام", callback_data=f"admin_edit_telegram_{user['id']}")],
        [InlineKeyboardButton("🆔 تغییر کد ملی", callback_data=f"admin_edit_national_{user['id']}")],
        [InlineKeyboardButton("🔢 تغییر شماره حساب", callback_data=f"admin_edit_account_{user['account_id']}")],
        [InlineKeyboardButton("💰 واریز وجه", callback_data=f"admin_add_balance_{user['account_id']}")],
        [InlineKeyboardButton("🧊 بلوکه کردن موجودی", callback_data=f"admin_freeze_balance_{user['account_id']}")],
        [InlineKeyboardButton("📊 تغییر وضعیت حساب", callback_data=f"admin_change_status_{user['account_id']}")],
        [InlineKeyboardButton("⭐ تغییر امتیاز اعتباری", callback_data=f"admin_change_score_{user['account_id']}")],
        [InlineKeyboardButton("👑 تغییر نقش کاربر", callback_data=f"admin_change_role_{user['id']}")],
        [InlineKeyboardButton("🔙 بازگشت به لیست کاربران", callback_data="admin_users")]
    ]
    await update.message.reply_text(
        info_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    
    context.user_data.pop('admin_target_user_id', None)
    context.user_data.pop('admin_target_account_id', None)
    return ConversationHandler.END

# ---------- توابع مدیریت کاربر ----------
async def admin_edit_field_start(update: Update, context, field_name, target_id):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await query.edit_message_text("⛔ دسترسی ندارید.")
        return
    
    context.user_data['admin_edit_field'] = field_name
    context.user_data['admin_edit_target'] = target_id
    
    field_names = {
        'camelot': 'نام کملوتی',
        'telegram': 'آیدی تلگرام',
        'national': 'کد ملی',
        'account': 'شماره حساب جدید'
    }
    
    await query.edit_message_text(
        f"✏️ **تغییر {field_names.get(field_name, field_name)}**\n\n"
        f"لطفاً مقدار جدید را وارد کنید:\n"
        f"(برای لغو /cancel بزنید)",
        parse_mode='Markdown'
    )
    return 'admin_edit_value'

async def admin_edit_value(update: Update, context):
    text = update.message.text.strip()
    user_id = update.effective_user.id
    
    if text.lower() == '/cancel':
        await update.message.reply_text("❌ تغییر لغو شد.", reply_markup=main_menu_keyboard(get_user_role_display(user_id)))
        context.user_data.pop('admin_edit_field', None)
        context.user_data.pop('admin_edit_target', None)
        return ConversationHandler.END
    
    field = context.user_data.get('admin_edit_field')
    target = context.user_data.get('admin_edit_target')
    
    if not field or not target:
        await update.message.reply_text("❌ خطا: اطلاعات ناقص.")
        return ConversationHandler.END
    
    db = get_db()
    c = db.cursor()
    
    if field == 'camelot':
        c.execute('UPDATE users SET camelot_name = ? WHERE id = ?', (text, target))
        db.commit()
        db.close()
        await update.message.reply_text(f"✅ نام کملوتی با موفقیت به `{text}` تغییر یافت.", parse_mode='Markdown')
    
    elif field == 'telegram':
        if not text.isdigit():
            await update.message.reply_text("❌ آیدی تلگرام باید عدد باشد. دوباره وارد کنید:")
            return 'admin_edit_value'
        c.execute('UPDATE users SET telegram_id = ? WHERE id = ?', (int(text), target))
        db.commit()
        db.close()
        await update.message.reply_text(f"✅ آیدی تلگرام با موفقیت به `{text}` تغییر یافت.", parse_mode='Markdown')
    
    elif field == 'national':
        if len(text) != 6 or not text.isdigit():
            await update.message.reply_text("❌ کد ملی باید ۶ رقم باشد. دوباره وارد کنید:")
            return 'admin_edit_value'
        c.execute('SELECT id FROM users WHERE national_id = ? AND id != ?', (text, target))
        if c.fetchone():
            db.close()
            await update.message.reply_text("❌ این کد ملی قبلاً ثبت شده. لطفاً کد دیگری وارد کنید:")
            return 'admin_edit_value'
        c.execute('UPDATE users SET national_id = ? WHERE id = ?', (text, target))
        db.commit()
        db.close()
        await update.message.reply_text(f"✅ کد ملی با موفقیت به `{text}` تغییر یافت.", parse_mode='Markdown')
    
    elif field == 'account':
        if len(text) != 6 or not text.isdigit():
            await update.message.reply_text("❌ شماره حساب باید ۶ رقم باشد. دوباره وارد کنید:")
            return 'admin_edit_value'
        c.execute('SELECT id FROM accounts WHERE account_number = ? AND id != ?', (text, target))
        if c.fetchone():
            db.close()
            await update.message.reply_text("❌ این شماره حساب قبلاً ثبت شده. لطفاً شماره دیگری وارد کنید:")
            return 'admin_edit_value'
        c.execute('UPDATE accounts SET account_number = ? WHERE id = ?', (text, target))
        db.commit()
        db.close()
        await update.message.reply_text(f"✅ شماره حساب با موفقیت به `{text}` تغییر یافت.", parse_mode='Markdown')
    
    context.user_data.pop('admin_edit_field', None)
    context.user_data.pop('admin_edit_target', None)
    return ConversationHandler.END

async def admin_add_balance_start(update: Update, context, account_id):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await query.edit_message_text("⛔ دسترسی ندارید.")
        return
    
    context.user_data['admin_add_balance_account'] = account_id
    await query.edit_message_text(
        "💰 **واریز وجه به حساب کاربر**\n\n"
        "لطفاً مبلغ مورد نظر را به ART وارد کنید:\n"
        "(برای لغو /cancel بزنید)",
        parse_mode='Markdown'
    )
    return 'admin_add_balance_amount'

async def admin_add_balance_amount(update: Update, context):
    text = update.message.text.strip()
    user_id = update.effective_user.id
    
    if text.lower() == '/cancel':
        await update.message.reply_text("❌ واریز لغو شد.", reply_markup=main_menu_keyboard(get_user_role_display(user_id)))
        context.user_data.pop('admin_add_balance_account', None)
        return ConversationHandler.END
    
    try:
        amount = int(text)
        if amount <= 0:
            raise ValueError
    except:
        await update.message.reply_text("❌ لطفاً یک عدد مثبت وارد کنید:")
        return 'admin_add_balance_amount'
    
    account_id = context.user_data.get('admin_add_balance_account')
    if not account_id:
        await update.message.reply_text("❌ خطا: شناسه حساب یافت نشد.")
        return ConversationHandler.END
    
    db = get_db()
    c = db.cursor()
    c.execute('SELECT balance, user_id, account_number FROM accounts WHERE id = ?', (account_id,))
    acc = c.fetchone()
    if not acc:
        db.close()
        await update.message.reply_text("❌ حساب یافت نشد.")
        return ConversationHandler.END
    
    new_balance = acc['balance'] + amount
    c.execute('UPDATE accounts SET balance = ? WHERE id = ?', (new_balance, account_id))
    
    txid = generate_txid()
    c.execute('''
        INSERT INTO transactions (txid, receiver_account, amount, type, reason)
        VALUES (?, ?, ?, 'manual_deposit', 'واریز مدیریتی')
    ''', (txid, acc['account_number'], amount))
    
    db.commit()
    db.close()
    
    log_audit(user_id, 'manual_deposit', f'account:{account_id}', f'amount:{amount}')
    
    await update.message.reply_text(
        f"✅ مبلغ {amount} ART با موفقیت به حساب واریز شد.\n"
        f"موجودی جدید: {new_balance} ART",
        reply_markup=main_menu_keyboard(get_user_role_display(user_id))
    )
    context.user_data.pop('admin_add_balance_account', None)
    return ConversationHandler.END

async def admin_freeze_balance_start(update: Update, context, account_id):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await query.edit_message_text("⛔ دسترسی ندارید.")
        return
    
    context.user_data['admin_freeze_account'] = account_id
    await query.edit_message_text(
        "🧊 **بلوکه کردن موجودی کاربر**\n\n"
        "لطفاً مبلغی که می‌خواهید بلوکه کنید را وارد کنید:\n"
        "(برای لغو /cancel بزنید)",
        parse_mode='Markdown'
    )
    return 'admin_freeze_amount'

async def admin_freeze_amount(update: Update, context):
    text = update.message.text.strip()
    user_id = update.effective_user.id
    
    if text.lower() == '/cancel':
        await update.message.reply_text("❌ بلوکه لغو شد.", reply_markup=main_menu_keyboard(get_user_role_display(user_id)))
        context.user_data.pop('admin_freeze_account', None)
        return ConversationHandler.END
    
    try:
        amount = int(text)
        if amount <= 0:
            raise ValueError
    except:
        await update.message.reply_text("❌ لطفاً یک عدد مثبت وارد کنید:")
        return 'admin_freeze_amount'
    
    account_id = context.user_data.get('admin_freeze_account')
    if not account_id:
        await update.message.reply_text("❌ خطا: شناسه حساب یافت نشد.")
        return ConversationHandler.END
    
    db = get_db()
    c = db.cursor()
    c.execute('SELECT balance, blocked_balance, user_id FROM accounts WHERE id = ?', (account_id,))
    acc = c.fetchone()
    if not acc:
        db.close()
        await update.message.reply_text("❌ حساب یافت نشد.")
        return ConversationHandler.END
    
    if amount > acc['balance'] - acc['blocked_balance']:
        await update.message.reply_text(f"❌ موجودی قابل استفاده کافی نیست.\nموجودی قابل استفاده: {acc['balance'] - acc['blocked_balance']} ART")
        return 'admin_freeze_amount'
    
    new_blocked = acc['blocked_balance'] + amount
    c.execute('UPDATE accounts SET blocked_balance = ? WHERE id = ?', (new_blocked, account_id))
    db.commit()
    db.close()
    
    log_audit(user_id, 'freeze_balance', f'account:{account_id}', f'amount:{amount}')
    
    await update.message.reply_text(
        f"✅ مبلغ {amount} ART با موفقیت بلوکه شد.\n"
        f"موجودی بلوکه شده جدید: {new_blocked} ART",
        reply_markup=main_menu_keyboard(get_user_role_display(user_id))
    )
    context.user_data.pop('admin_freeze_account', None)
    return ConversationHandler.END

async def admin_change_status(update: Update, context, account_id):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await query.edit_message_text("⛔ دسترسی ندارید.")
        return
    
    db = get_db()
    c = db.cursor()
    c.execute('SELECT status FROM accounts WHERE id = ?', (account_id,))
    acc = c.fetchone()
    if not acc:
        db.close()
        await query.edit_message_text("❌ حساب یافت نشد.")
        return
    
    new_status = 'blocked' if acc['status'] == 'active' else 'active'
    c.execute('UPDATE accounts SET status = ? WHERE id = ?', (new_status, account_id))
    db.commit()
    db.close()
    
    status_names = {'active': 'فعال', 'blocked': 'مسدود'}
    log_audit(user_id, 'change_status', f'account:{account_id}', f'new:{new_status}')
    
    await query.edit_message_text(
        f"✅ وضعیت حساب با موفقیت به **{status_names[new_status]}** تغییر یافت.",
        reply_markup=main_menu_keyboard(get_user_role_display(user_id)),
        parse_mode='Markdown'
    )

async def admin_change_score_start(update: Update, context, account_id):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await query.edit_message_text("⛔ دسترسی ندارید.")
        return
    
    context.user_data['admin_score_account'] = account_id
    await query.edit_message_text(
        "⭐ **تغییر امتیاز اعتباری**\n\n"
        "لطفاً امتیاز جدید را وارد کنید (۰ تا ۱۰۰۰):\n"
        "(برای لغو /cancel بزنید)",
        parse_mode='Markdown'
    )
    return 'admin_change_score_value'

async def admin_change_score_value(update: Update, context):
    text = update.message.text.strip()
    user_id = update.effective_user.id
    
    if text.lower() == '/cancel':
        await update.message.reply_text("❌ تغییر امتیاز لغو شد.", reply_markup=main_menu_keyboard(get_user_role_display(user_id)))
        context.user_data.pop('admin_score_account', None)
        return ConversationHandler.END
    
    try:
        new_score = int(text)
        if new_score < 0 or new_score > 1000:
            raise ValueError
    except:
        await update.message.reply_text("❌ امتیاز باید عددی بین 0 تا 1000 باشد. دوباره وارد کنید:")
        return 'admin_change_score_value'
    
    account_id = context.user_data.get('admin_score_account')
    if not account_id:
        await update.message.reply_text("❌ خطا: شناسه حساب یافت نشد.")
        return ConversationHandler.END
    
    db = get_db()
    c = db.cursor()
    c.execute('SELECT credit_score FROM accounts WHERE id = ?', (account_id,))
    acc = c.fetchone()
    if not acc:
        db.close()
        await update.message.reply_text("❌ حساب یافت نشد.")
        return ConversationHandler.END
    
    c.execute('UPDATE accounts SET credit_score = ? WHERE id = ?', (new_score, account_id))
    c.execute('INSERT INTO credit_history (account_id, old_score, new_score, reason) VALUES (?, ?, ?, ?)',
              (account_id, acc['credit_score'], new_score, 'تغییر توسط مدیریت'))
    db.commit()
    db.close()
    
    log_audit(user_id, 'change_score', f'account:{account_id}', f'old:{acc["credit_score"]},new:{new_score}')
    
    await update.message.reply_text(
        f"✅ امتیاز اعتباری با موفقیت به **{new_score}** تغییر یافت.",
        reply_markup=main_menu_keyboard(get_user_role_display(user_id)),
        parse_mode='Markdown'
    )
    context.user_data.pop('admin_score_account', None)
    return ConversationHandler.END

async def admin_change_role(update: Update, context, user_id):
    query = update.callback_query
    await query.answer()
    admin_user_id = update.effective_user.id
    
    if not is_admin(admin_user_id):
        await query.edit_message_text("⛔ دسترسی ندارید.")
        return
    
    db = get_db()
    c = db.cursor()
    c.execute('SELECT role FROM users WHERE id = ?', (user_id,))
    user = c.fetchone()
    if not user:
        db.close()
        await query.edit_message_text("❌ کاربر یافت نشد.")
        return
    
    roles = ['citizen', 'employee', 'king']
    current_role = user['role']
    
    try:
        idx = roles.index(current_role)
        new_role = roles[(idx + 1) % len(roles)]
    except:
        new_role = 'citizen'
    
    c.execute('UPDATE users SET role = ? WHERE id = ?', (new_role, user_id))
    db.commit()
    db.close()
    
    role_names = {'citizen':'شهروند', 'employee':'کارمند', 'king':'شاه', 'owner':'مالک'}
    
    await query.edit_message_text(
        f"✅ نقش کاربر با موفقیت به **{role_names[new_role]}** تغییر یافت.",
        reply_markup=main_menu_keyboard(get_user_role_display(admin_user_id)),
        parse_mode='Markdown'
    )

# ---------- صندوق پیام ----------
async def notifications_menu(update: Update, context):
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
    
    # پشتیبانی کاربران
    support_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(support_start, pattern="^support$")],
        states={
            SUPPORT_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, support_receive)],
        },
        fallbacks=[CommandHandler("start", start), CommandHandler("cancel", cancel)],
    )
    app.add_handler(support_conv)
    
    # مدیریت پشتیبانی
    app.add_handler(CallbackQueryHandler(admin_support_list, pattern="^admin_support$"))
    support_reply_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_support_reply_start, pattern="^support_reply_")],
        states={
            ADMIN_SUPPORT_REPLY: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_support_reply_receive)],
        },
        fallbacks=[CommandHandler("start", start), CommandHandler("cancel", cancel)],
    )
    app.add_handler(support_reply_conv)
    
    # مدیریت کاربران
    app.add_handler(CallbackQueryHandler(admin_users_list, pattern="^admin_users$"))
    app.add_handler(CallbackQueryHandler(admin_users_page_handler, pattern="^admin_users_page_"))
    
    admin_user_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_user_manage_start, pattern="^admin_user_manage$")],
        states={
            'admin_user_search': [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_user_search)],
        },
        fallbacks=[CommandHandler("start", start), CommandHandler("cancel", cancel)],
    )
    app.add_handler(admin_user_conv)
    
    # تغییر فیلدها
    admin_edit_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(lambda u,c: admin_edit_field_start(u,c, 'camelot', int(u.callback_query.data.split('_')[3])), pattern="^admin_edit_camelot_"),
            CallbackQueryHandler(lambda u,c: admin_edit_field_start(u,c, 'telegram', int(u.callback_query.data.split('_')[3])), pattern="^admin_edit_telegram_"),
            CallbackQueryHandler(lambda u,c: admin_edit_field_start(u,c, 'national', int(u.callback_query.data.split('_')[3])), pattern="^admin_edit_national_"),
            CallbackQueryHandler(lambda u,c: admin_edit_field_start(u,c, 'account', int(u.callback_query.data.split('_')[3])), pattern="^admin_edit_account_"),
        ],
        states={
            'admin_edit_value': [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_edit_value)],
        },
        fallbacks=[CommandHandler("start", start), CommandHandler("cancel", cancel)],
    )
    app.add_handler(admin_edit_conv)
    
    # واریز وجه
    admin_add_balance_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(lambda u,c: admin_add_balance_start(u,c, int(u.callback_query.data.split('_')[3])), pattern="^admin_add_balance_")],
        states={
            'admin_add_balance_amount': [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_balance_amount)],
        },
        fallbacks=[CommandHandler("start", start), CommandHandler("cancel", cancel)],
    )
    app.add_handler(admin_add_balance_conv)
    
    # بلوکه موجودی
    admin_freeze_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(lambda u,c: admin_freeze_balance_start(u,c, int(u.callback_query.data.split('_')[3])), pattern="^admin_freeze_balance_")],
        states={
            'admin_freeze_amount': [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_freeze_amount)],
        },
        fallbacks=[CommandHandler("start", start), CommandHandler("cancel", cancel)],
    )
    app.add_handler(admin_freeze_conv)
    
    # تغییر وضعیت حساب
    app.add_handler(CallbackQueryHandler(lambda u,c: admin_change_status(u,c, int(u.callback_query.data.split('_')[3])), pattern="^admin_change_status_"))
    
    # تغییر امتیاز اعتباری
    admin_score_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(lambda u,c: admin_change_score_start(u,c, int(u.callback_query.data.split('_')[3])), pattern="^admin_change_score_")],
        states={
            'admin_change_score_value': [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_change_score_value)],
        },
        fallbacks=[CommandHandler("start", start), CommandHandler("cancel", cancel)],
    )
    app.add_handler(admin_score_conv)
    
    # تغییر نقش
    app.add_handler(CallbackQueryHandler(lambda u,c: admin_change_role(u,c, int(u.callback_query.data.split('_')[3])), pattern="^admin_change_role_"))
    
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
    for p in ["change_account"]:
        app.add_handler(CallbackQueryHandler(placeholder_handler, pattern=f"^{p}$"))
    
    print("✅ ربات بانک کملوت روشن شد!")
    app.run_polling()

if __name__ == "__main__":
    main()