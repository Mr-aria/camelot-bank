import logging
from datetime import datetime
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
    generate_txid, log_audit
)
from utils import (
    create_bank_account, format_balance, format_receipt
)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
                    level=logging.INFO)
logger = logging.getLogger(__name__)

# مراحل
NAME_REAL, NAME_CAMELOT, NATIONAL_ID, PASSWORD, CONFIRM = range(5)
TRANSFER_ACCOUNT, TRANSFER_AMOUNT, TRANSFER_REASON, TRANSFER_PASSWORD = range(10, 14)

def is_admin(user_id: int) -> bool:
    user = get_user_by_telegram_id(user_id)
    return user and user['role'] in ['king', 'owner', 'employee']

def get_user_role_display(user_id: int) -> str:
    user = get_user_by_telegram_id(user_id)
    if not user:
        return "شهروند"
    roles = {'citizen':'شهروند','employee':'کارمند','king':'شاه','owner':'مالک'}
    return roles.get(user['role'], 'شهروند')

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
        context.user_data['register_step'] = NAME_REAL
        context.user_data['username'] = username
        await update.message.reply_text(
            "🏦 **به بانک کملوت خوش آمدید!**\n\n"
            "برای افتتاح حساب، نام واقعی خود را وارد کنید:",
            parse_mode='Markdown'
        )
        return NAME_REAL
    
    acc = get_account_by_user_id(user['id'])
    if not acc:
        await update.message.reply_text("❌ خطا در سیستم.")
        return
    
    welcome = get_setting('welcome_message') or "درود👋\nخوش اومدین به بانک کملوت💰"
    await update.message.reply_text(welcome, reply_markup=main_menu_keyboard(user['role']))
    return ConversationHandler.END

async def balance_callback(update: Update, context):
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
    info_text = f"""👤 **اطلاعات حساب شما**
━━━━━━━━━━━━━━━━━━━
📛 نام واقعی: {user['real_name']}
⚔️ نام کملوتی: {user['camelot_name']}
🆔 کد ملی: {user['national_id']}
🏦 شماره حساب: `{acc['account_number']}`
⭐ امتیاز اعتباری: {acc['credit_score']}
👑 نقش: {get_user_role_display(user_id)}
📊 وضعیت: {status_persian}
━━━━━━━━━━━━━━━━━━━"""
    await query.edit_message_text(info_text, reply_markup=main_menu_keyboard(user['role']), parse_mode='Markdown')

async def my_credit_callback(update: Update, context):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    user = get_user_by_telegram_id(user_id)
    if not user or not (acc := get_account_by_user_id(user['id'])):
        await query.edit_message_text("❌ اطلاعاتی یافت نشد.")
        return
    score = acc['credit_score']
    rating = "🟢 عالی" if score >= 900 else "🟡 خوب" if score >= 700 else "🟠 متوسط" if score >= 500 else "🔴 ضعیف" if score >= 300 else "⚫ بدحساب"
    await query.edit_message_text(f"📈 **اعتبار بانکی شما**\n━━━━━━━━━━━━━━━━━━━\n⭐ امتیاز: {score}\n🏷 رتبه: {rating}", reply_markup=main_menu_keyboard(user['role']), parse_mode='Markdown')

async def panel_callback(update: Update, context):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await query.edit_message_text("⛔ دسترسی ندارید.")
        return
    user = get_user_by_telegram_id(user_id)
    panel_text = f"👑 **پنل مدیریت**\n👤 نقش: {get_user_role_display(user_id)}\n🕐 {datetime.now().strftime('%Y/%m/%d %H:%M')}"
    keyboard = [[InlineKeyboardButton("👥 مدیریت کاربران", callback_data="admin_users")],
                [InlineKeyboardButton("💰 مدیریت مالی", callback_data="admin_finance")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_menu")]]
    await query.edit_message_text(panel_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def back_to_menu(update: Update, context):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    user = get_user_by_telegram_id(user_id)
    role = user['role'] if user else 'citizen'
    await query.edit_message_text(get_setting('welcome_message') or "منوی اصلی", reply_markup=main_menu_keyboard(role))

# ---------- ثبت‌نام ----------
async def register_handler(update: Update, context):
    step = context.user_data.get('register_step')
    text = update.message.text
    if step == NAME_REAL:
        context.user_data['real_name'] = text
        context.user_data['register_step'] = NAME_CAMELOT
        await update.message.reply_text("⚔️ نام خود در کملوت را وارد کنید:", parse_mode='Markdown')
        return NAME_CAMELOT
    elif step == NAME_CAMELOT:
        context.user_data['camelot_name'] = text
        context.user_data['register_step'] = NATIONAL_ID
        await update.message.reply_text("🆔 کد ملی ۶ رقمی را وارد کنید:", parse_mode='Markdown')
        return NATIONAL_ID
    elif step == NATIONAL_ID:
        if not text.isdigit() or len(text) != 6:
            await update.message.reply_text("❌ کد ملی ۶ رقم باید باشد.")
            return NATIONAL_ID
        db = get_db()
        c = db.cursor()
        c.execute('SELECT id FROM users WHERE national_id = ?', (text,))
        if c.fetchone():
            db.close()
            await update.message.reply_text("❌ این کد ملی قبلاً ثبت شده.")
            return NATIONAL_ID
        db.close()
        context.user_data['national_id'] = text
        context.user_data['register_step'] = PASSWORD
        await update.message.reply_text("🔐 رمز ۴ رقمی برای حساب خود وارد کنید:", parse_mode='Markdown')
        return PASSWORD
    elif step == PASSWORD:
        if not text.isdigit() or len(text) != 4:
            await update.message.reply_text("❌ رمز ۴ رقم باید باشد.")
            return PASSWORD
        context.user_data['password'] = text
        context.user_data['register_step'] = CONFIRM
        confirm_text = f"""✅ اطلاعات را تأیید کنید:
📛 نام واقعی: {context.user_data['real_name']}
⚔️ نام کملوتی: {context.user_data['camelot_name']}
🆔 کد ملی: {context.user_data['national_id']}
🔐 رمز: ****
آیا صحیح است؟"""
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("✅ بله", callback_data="confirm_yes")],
                                         [InlineKeyboardButton("❌ خیر", callback_data="confirm_no")]])
        await update.message.reply_text(confirm_text, reply_markup=keyboard, parse_mode='Markdown')
        return CONFIRM
    return ConversationHandler.END

async def confirm_callback(update: Update, context):
    query = update.callback_query
    await query.answer()
    if query.data == "confirm_yes":
        user_id = update.effective_user.id
        acc_num, bonus = create_bank_account(
            user_id,
            context.user_data.get('username', ''),
            context.user_data['real_name'],
            context.user_data['camelot_name'],
            context.user_data['national_id'],
            context.user_data['password']
        )
        await query.edit_message_text(
            f"✅ حساب شما ایجاد شد!\n🏦 شماره حساب: `{acc_num}`\n💰 موجودی اولیه: {bonus} ART\nبرای ادامه /start بزنید.",
            parse_mode='Markdown'
        )
        await log_to_channel(context, f"🏦 حساب جدید: {context.user_data['camelot_name']} - {acc_num}")
    else:
        await query.edit_message_text("❌ ثبت‌نام لغو شد.")
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
    await query.edit_message_text("💸 شماره حساب مقصد (۶ رقم) را وارد کنید:", parse_mode='Markdown')
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
    await update.message.reply_text(f"💰 مبلغ: {amount} ART\n📝 علت (اختیاری، «ندارد» برای رد):")
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
    await update.message.reply_text(f"🔐 رمز ۴ رقمی خود را وارد کنید:")
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
    fee = 0  # در صورت نیاز از تنظیمات بخوان
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

async def placeholder_handler(update: Update, context):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    user = get_user_by_telegram_id(user_id)
    role = user['role'] if user else 'citizen'
    await query.edit_message_text("⏳ در حال تکمیل...", reply_markup=main_menu_keyboard(role))

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={NAME_REAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_handler)],
                NAME_CAMELOT: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_handler)],
                NATIONAL_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_handler)],
                PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_handler)],
                CONFIRM: [CallbackQueryHandler(confirm_callback)]},
        fallbacks=[CommandHandler("start", start)]))
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(transfer_start, pattern="^transfer$")],
        states={TRANSFER_ACCOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, transfer_account_handler)],
                TRANSFER_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, transfer_amount_handler)],
                TRANSFER_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, transfer_reason_handler)],
                TRANSFER_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, transfer_password_handler)]},
        fallbacks=[CommandHandler("start", start), CommandHandler("cancel", start)]))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(balance_callback, pattern="^balance$"))
    app.add_handler(CallbackQueryHandler(my_info_callback, pattern="^my_info$"))
    app.add_handler(CallbackQueryHandler(my_credit_callback, pattern="^my_credit$"))
    app.add_handler(CallbackQueryHandler(panel_callback, pattern="^panel$"))
    app.add_handler(CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"))
    for p in ["loan","my_transactions","notifications","settings","change_account","support","admin_users","admin_finance"]:
        app.add_handler(CallbackQueryHandler(placeholder_handler, pattern=f"^{p}$"))
    print("✅ ربات بانک کملوت روشن شد!")
    app.run_polling()

if __name__ == "__main__":
    main()
