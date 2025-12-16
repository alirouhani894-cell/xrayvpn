import telebot as tbot
import sqlite3
import json
import re
import os
import threading
from datetime import datetime, timedelta
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# توکن جدید - باید از BotFather بگیرید
TOKEN = "8218257426:AAF2DWZ_eHQ1PWDZTT93EJqGR4TNU2NXcUg"  # جایگزین کنید با توکن واقعی
bot = tbot.TeleBot(TOKEN)

# تنظیمات کانال اجباری
REQUIRED_CHANNELS = ["@XrayVPNpro", "@il_timore"]  # لیست کانال‌های اجباری
CHANNEL_LINKS = {
    "@XrayVPNpro": "https://t.me/XrayVPNpro",
    "@il_timore": "https://t.me/il_timore"
}

# گروه ادمین (ربات باید در این گروه ادمین باشد)
ADMIN_GROUP_ID = -1003133478539  # آیدی عددی گروه ادمین (منفی)

# لیست آیدی‌های عددی ادمین‌ها
ADMIN_USER_IDS = [6796495518, 6565734282]  # دو ادمین مختلف

# تنظیمات لاگ (به طور پیش‌فرض روشن)
LOG_ENABLED = True

# قفل برای دیتابیس
db_lock = threading.Lock()


# تبدیل datetime به string برای SQLite
def adapt_datetime(ts):
    return ts.isoformat()

def convert_datetime(ts):
    return datetime.fromisoformat(ts.decode())

sqlite3.register_adapter(datetime, adapt_datetime)
sqlite3.register_converter("timestamp", convert_datetime)

# تابع برای به‌روزرسانی ساختار دیتابیس (بدون قفل جداگانه)
def upgrade_database(conn):
    """به‌روزرسانی ساختار دیتابیس - باید داخل قفل اصلی فراخوانی شود"""
    c = conn.cursor()
    
    # بررسی و اضافه کردن ستون‌های جدید به جدول purchases
    c.execute("PRAGMA table_info(purchases)")
    columns = [col[1] for col in c.fetchall()]
    
    if 'receipt_photo_id' not in columns:
        c.execute("ALTER TABLE purchases ADD COLUMN receipt_photo_id TEXT")
        print("✅ ستون receipt_photo_id اضافه شد")
    
    if 'admin_group_msg_id' not in columns:
        c.execute("ALTER TABLE purchases ADD COLUMN admin_group_msg_id INTEGER")
        print("✅ ستون admin_group_msg_id اضافه شد")
    
    # بررسی و اضافه کردن ستون‌های جدید به جدول users
    c.execute("PRAGMA table_info(users)")
    columns = [col[1] for col in c.fetchall()]
    
    if 'current_plan' not in columns:
        c.execute("ALTER TABLE users ADD COLUMN current_plan TEXT")
        print("✅ ستون current_plan اضافه شد")
    
    if 'plan_expiry' not in columns:
        c.execute("ALTER TABLE users ADD COLUMN plan_expiry timestamp")
        print("✅ ستون plan_expiry اضافه شد")
    
    if 'free_test_used' not in columns:
        c.execute("ALTER TABLE users ADD COLUMN free_test_used BOOLEAN DEFAULT 0")
        print("✅ ستون free_test_used اضافه شد")
    
    if 'free_test_expiry' not in columns:
        c.execute("ALTER TABLE users ADD COLUMN free_test_expiry timestamp")
        print("✅ ستون free_test_expiry اضافه شد")
    
    # ایجاد جدول تنظیمات سیستم
    c.execute('''CREATE TABLE IF NOT EXISTS system_settings
                 (id INTEGER PRIMARY KEY,
                  setting_name TEXT UNIQUE,
                  setting_value TEXT,
                  last_updated timestamp)''')
    
    # اضافه کردن تنظیمات پیش‌فرض
    current_time = datetime.now()
    default_settings = [
        ('log_enabled', '1', current_time),
        ('bot_started', '0', current_time)
    ]
    
    for setting in default_settings:
        c.execute('''INSERT OR IGNORE INTO system_settings 
                    (setting_name, setting_value, last_updated) 
                    VALUES (?, ?, ?)''', setting)
    
    conn.commit()

# دیتابیس برای ذخیره کاربران - با یک قفل و یک اتصال
def init_db():
    with db_lock:
        conn = sqlite3.connect('database.db', detect_types=sqlite3.PARSE_DECLTYPES, timeout=30.0)
        c = conn.cursor()
        
        # جدول کاربران
        c.execute('''CREATE TABLE IF NOT EXISTS users
                     (user_id INTEGER PRIMARY KEY, 
                      username TEXT,
                      first_name TEXT,
                      last_name TEXT,
                      current_plan TEXT,
                      plan_expiry timestamp,
                      free_test_used BOOLEAN DEFAULT 0,
                      free_test_expiry timestamp,
                      join_date timestamp,
                      last_active timestamp,
                      is_active BOOLEAN DEFAULT 1)''')
        
        # جدول خریدها
        c.execute('''CREATE TABLE IF NOT EXISTS purchases
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER,
                      plan_type TEXT,
                      amount INTEGER,
                      payment_date timestamp,
                      receipt_sent BOOLEAN DEFAULT 0,
                      config_sent BOOLEAN DEFAULT 0,
                      receipt_photo_id TEXT,
                      admin_group_msg_id INTEGER,
                      FOREIGN KEY(user_id) REFERENCES users(user_id))''')
        
        # جدول لاگ فعالیت‌ها
        c.execute('''CREATE TABLE IF NOT EXISTS activity_logs
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER,
                      activity_type TEXT,
                      activity_details TEXT,
                      activity_date timestamp,
                      FOREIGN KEY(user_id) REFERENCES users(user_id))''')
        
        # جدول تنظیمات سیستم
        c.execute('''CREATE TABLE IF NOT EXISTS system_settings
                     (id INTEGER PRIMARY KEY,
                      setting_name TEXT UNIQUE,
                      setting_value TEXT,
                      last_updated timestamp)''')
        
        conn.commit()
        
        # به‌روزرسانی ساختار دیتابیس (با همان اتصال)
        upgrade_database(conn)
        
        conn.close()

init_db()

# تابع برای دریافت تنظیمات سیستم
def get_system_setting(setting_name, default_value=None):
    with db_lock:
        conn = sqlite3.connect('database.db', detect_types=sqlite3.PARSE_DECLTYPES, timeout=10)
        c = conn.cursor()
        c.execute("SELECT setting_value FROM system_settings WHERE setting_name = ?", (setting_name,))
        result = c.fetchone()
        conn.close()
        
        if result:
            return result[0]
        return default_value

# تابع برای ذخیره تنظیمات سیستم
def set_system_setting(setting_name, setting_value):
    with db_lock:
        conn = sqlite3.connect('database.db', detect_types=sqlite3.PARSE_DECLTYPES, timeout=10)
        c = conn.cursor()
        c.execute('''INSERT OR REPLACE INTO system_settings 
                    (setting_name, setting_value, last_updated) 
                    VALUES (?, ?, ?)''', 
                 (setting_name, setting_value, datetime.now()))
        conn.commit()
        conn.close()

# تابع برای بررسی وضعیت لاگ
def is_log_enabled():
    log_setting = get_system_setting('log_enabled', '1')
    return log_setting == '1'

# تابع برای خاموش/روشن کردن لاگ
def toggle_log_status():
    current_status = is_log_enabled()
    new_status = '0' if current_status else '1'
    set_system_setting('log_enabled', new_status)
    return not current_status

# تابع برای ذخیره لاگ فعالیت
def log_activity(user_id, activity_type, activity_details=""):
    global LOG_ENABLED
    
    # چک کردن وضعیت لاگ از دیتابیس
    if not is_log_enabled():
        return
    
    try:
        with db_lock:
            conn = sqlite3.connect('database.db', detect_types=sqlite3.PARSE_DECLTYPES, timeout=10)
            c = conn.cursor()
            c.execute("INSERT INTO activity_logs (user_id, activity_type, activity_details, activity_date) VALUES (?, ?, ?, ?)",
                      (user_id, activity_type, activity_details, datetime.now()))
            conn.commit()
            conn.close()
        
        # ارسال لاگ به گروه ادمین (فقط اگر لاگ فعال باشد)
        if is_log_enabled():
            try:
                user_info = bot.get_chat(user_id)
                username = f"@{user_info.username}" if user_info.username else "بدون یوزرنیم"
                log_message = f"""📊 <b>لاگ فعالیت کاربر</b>

👤 <b>کاربر:</b> {user_info.first_name} {user_info.last_name or ''}
🆔 <b>یوزرنیم:</b> {username}
🔢 <b>آیدی:</b> <code>{user_id}</code>

📝 <b>نوع فعالیت:</b> {activity_type}
📋 <b>جزئیات:</b> {activity_details}
⏰ <b>زمان:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
                
                bot.send_message(ADMIN_GROUP_ID, log_message, parse_mode='HTML')
            except Exception as e:
                print(f"⚠️ خطا در ارسال لاگ به گروه: {e}")
                
    except Exception as e:
        print(f"⚠️ خطا در ذخیره لاگ: {e}")

# تابع برای ذخیره کاربر در دیتابیس
def save_user_to_db(user_id, username, first_name, last_name):
    with db_lock:
        conn = sqlite3.connect('database.db', detect_types=sqlite3.PARSE_DECLTYPES, timeout=10)
        c = conn.cursor()
        
        # چک کردن وجود کاربر
        c.execute("SELECT COUNT(*) FROM users WHERE user_id = ?", (user_id,))
        user_exists = c.fetchone()[0] > 0
        
        if not user_exists:
            c.execute('''INSERT INTO users 
                         (user_id, username, first_name, last_name, join_date, last_active) 
                         VALUES (?, ?, ?, ?, ?, ?)''',
                      (user_id, username, first_name, last_name, datetime.now(), datetime.now()))
            log_activity(user_id, "عضویت جدید در ربات", f"{first_name} {last_name} - {username}")
        else:
            c.execute("UPDATE users SET last_active = ? WHERE user_id = ?", (datetime.now(), user_id))
        
        conn.commit()
        conn.close()

# تابع برای دریافت اطلاعات کاربر
def get_user_info(user_id):
    with db_lock:
        conn = sqlite3.connect('database.db', detect_types=sqlite3.PARSE_DECLTYPES, timeout=10)
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = c.fetchone()
        conn.close()
        return user

# تابع برای چک کردن وضعیت پلن کاربر
def check_user_plan_status(user_id):
    user = get_user_info(user_id)
    if not user:
        return {"has_plan": False, "has_free_test": False}
    
    current_plan = user[4]  # current_plan
    plan_expiry = user[5]   # plan_expiry
    free_test_used = user[6]  # free_test_used
    free_test_expiry = user[7]  # free_test_expiry
    
    has_plan = False
    has_free_test = False
    
    # چک کردن پلن عادی
    if current_plan and plan_expiry:
        if isinstance(plan_expiry, str):
            try:
                plan_expiry = datetime.fromisoformat(plan_expiry)
            except:
                plan_expiry = None
        
        if plan_expiry and plan_expiry > datetime.now():
            has_plan = True
    
    # چک کردن تست رایگان
    if free_test_used and free_test_expiry:
        if isinstance(free_test_expiry, str):
            try:
                free_test_expiry = datetime.fromisoformat(free_test_expiry)
            except:
                free_test_expiry = None
        
        if free_test_expiry and free_test_expiry > datetime.now():
            has_free_test = True
    
    return {
        "has_plan": has_plan,
        "has_free_test": has_free_test,
        "current_plan": current_plan,
        "plan_expiry": plan_expiry,
        "free_test_expiry": free_test_expiry
    }

# تابع برای تنظیم تست رایگان کاربر
def set_free_test_used(user_id):
    with db_lock:
        conn = sqlite3.connect('database.db', detect_types=sqlite3.PARSE_DECLTYPES, timeout=10)
        c = conn.cursor()
        
        # تنظیم تاریخ انقضای تست رایگان (24 ساعت بعد)
        expiry_date = datetime.now() + timedelta(hours=24)
        
        c.execute("UPDATE users SET free_test_used = 1, free_test_expiry = ? WHERE user_id = ?",
                  (expiry_date, user_id))
        
        conn.commit()
        conn.close()
    
    log_activity(user_id, "استفاده از تست رایگان", "تست 24 ساعته فعال شد")

# تابع برای چک کردن عضویت در کانال‌ها
def check_channel_membership(user_id):
    results = {}
    for channel in REQUIRED_CHANNELS:
        try:
            member = bot.get_chat_member(channel, user_id)
            results[channel] = member.status in ['member', 'administrator', 'creator']
        except Exception as e:
            print(f"⚠️ خطا در بررسی عضویت در {channel}: {e}")
            results[channel] = False
    return results

# تابع برای ارسال پیام به گروه ادمین
def send_to_admin_group(message_text, photo_file_id=None, reply_markup=None):
    try:
        if photo_file_id:
            msg = bot.send_photo(
                ADMIN_GROUP_ID,
                photo_file_id,
                caption=message_text,
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
        else:
            msg = bot.send_message(
                ADMIN_GROUP_ID,
                message_text,
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
        return msg.message_id
    except Exception as e:
        print(f"⚠️ خطا در ارسال به گروه ادمین: {e}")
        # ارسال به ادمین‌ها به صورت فردی
        for admin_id in ADMIN_USER_IDS:
            try:
                if photo_file_id:
                    bot.send_photo(admin_id, photo_file_id, caption=message_text, parse_mode='HTML')
                else:
                    bot.send_message(admin_id, message_text, parse_mode='HTML')
            except Exception as e2:
                print(f"⚠️ خطا در ارسال به ادمین {admin_id}: {e2}")
        return None

# تابع برای ارسال پیام شروع کار به گروه ادمین
def send_startup_message():
    try:
        start_message = """🤖 <b>ربات XrayVPN شروع به کار کرد!</b> 🚀

👑 <b>گوش به فرمانم ارباب!</b> 👑
⏰ <b>زمان:</b> {time}
📊 <b>وضعیت لاگ:</b> {log_status}
🛠 <b>آماده خدمت‌رسانی</b> ✅""".format(
            time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            log_status="✅ فعال" if is_log_enabled() else "❌ غیرفعال"
        )
        
        bot.send_message(
            ADMIN_GROUP_ID,
            start_message,
            parse_mode='HTML'
        )
        print("✅ پیام شروع کار به گروه ادمین ارسال شد.")
    except Exception as e:
        print(f"⚠️ خطا در ارسال پیام شروع کار: {e}")

# کیبورد اصلی با طراحی شیشه‌ای
def create_main_keyboard():
    markup = tbot.types.ReplyKeyboardMarkup(
        row_width=2,
        resize_keyboard=True,
        one_time_keyboard=False
    )
    
    # دکمه‌های اصلی برای همه کاربران
    btn_buy = tbot.types.KeyboardButton("🛍️ خرید اشتراک")
    btn_test = tbot.types.KeyboardButton("🎁 تست ۲۴ ساعته")
    btn_account = tbot.types.KeyboardButton("👤 حساب کاربری")
    btn_support = tbot.types.KeyboardButton("📞 پشتیبانی")
    
    markup.add(btn_buy, btn_test, btn_account, btn_support)
    return markup

# کیبورد فقط با دکمه برگشت
def create_back_only_keyboard():
    markup = tbot.types.ReplyKeyboardMarkup(
        resize_keyboard=True,
        one_time_keyboard=False
    )
    btn_back = tbot.types.KeyboardButton("🔙 بازگشت")
    markup.add(btn_back)
    return markup

# کیبورد انتخاب پلن (اینلاین - شیشه‌ای)
def create_plans_inline_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    
    # ردیف اول
    btn1 = InlineKeyboardButton("✨ پلن ۱ ماهه - یک کاربر", callback_data="plan_1")
    btn2 = InlineKeyboardButton("✨ پلن ۱ ماهه - دو کاربر", callback_data="plan_2")
    
    # ردیف دوم
    btn3 = InlineKeyboardButton("🚀 پلن ۲ ماهه - یک کاربر", callback_data="plan_3")
    btn4 = InlineKeyboardButton("🚀 پلن ۲ ماهه - دو کاربر", callback_data="plan_4")
    
    markup.add(btn1, btn2, btn3, btn4)
    return markup

# کیبورد تمدید/ارتقاء (برای کاربرانی که پلن دارند)
def create_renew_upgrade_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    
    btn_renew = InlineKeyboardButton("🔄 تمدید اشتراک", callback_data="renew_plan")
    btn_upgrade = InlineKeyboardButton("⬆️ ارتقاء پلن", callback_data="upgrade_plan")
    btn_extend = InlineKeyboardButton("➕ اضافه کردن کاربر", callback_data="add_user")
    btn_back = InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_account")
    
    markup.add(btn_renew, btn_upgrade, btn_extend, btn_back)
    return markup

# کیبورد عضویت در کانال‌ها (اینلاین - شیشه‌ای)
def create_channel_join_keyboard():
    markup = InlineKeyboardMarkup(row_width=1)
    
    for channel in REQUIRED_CHANNELS:
        btn = InlineKeyboardButton(
            f"📢 عضویت در {channel}",
            url=CHANNEL_LINKS.get(channel, f"https://t.me/{channel[1:]}")
        )
        markup.add(btn)
    
    btn_check = InlineKeyboardButton("✅ بررسی عضویت مجدد", callback_data="check_membership")
    markup.add(btn_check)
    return markup

# کیبورد تأیید خرید (اینلاین - شیشه‌ای)
def create_confirm_purchase_keyboard(plan_id, is_renew=False):
    markup = InlineKeyboardMarkup(row_width=2)
    
    if is_renew:
        btn_confirm = InlineKeyboardButton("✅ تأیید تمدید", callback_data=f"renew_confirm_{plan_id}")
    else:
        btn_confirm = InlineKeyboardButton("✅ تأیید خرید", callback_data=f"confirm_{plan_id}")
    
    btn_cancel = InlineKeyboardButton("❌ انصراف", callback_data="cancel_purchase")
    
    markup.add(btn_confirm, btn_cancel)
    return markup

# کیبورد ادمین برای رسیدها
def create_receipt_admin_keyboard(purchase_id):
    markup = InlineKeyboardMarkup(row_width=2)
    
    btn_confirm = InlineKeyboardButton("✅ تأیید و ارسال کانفیگ", callback_data=f"admin_confirm_{purchase_id}")
    btn_reject = InlineKeyboardButton("❌ رد درخواست", callback_data=f"admin_reject_{purchase_id}")
    
    markup.add(btn_confirm, btn_reject)
    return markup

# کیبورد پنل ادمین با دکمه کنترل لاگ
def create_admin_panel_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    
    btn_users = InlineKeyboardButton("👥 لیست کاربران", callback_data="admin_users")
    btn_receipts = InlineKeyboardButton("📋 رسیدهای در انتظار", callback_data="admin_pending")
    btn_stats = InlineKeyboardButton("📊 آمار ربات", callback_data="admin_stats")
    btn_logs = InlineKeyboardButton("📝 لاگ فعالیت‌ها", callback_data="admin_logs")
    
    # دکمه کنترل وضعیت لاگ
    log_status = "خاموش" if is_log_enabled() else "روشن"
    btn_log_toggle = InlineKeyboardButton(f"🚫 لاگ: {log_status}", callback_data="admin_toggle_log")
    
    markup.add(btn_users, btn_receipts, btn_stats, btn_logs, btn_log_toggle)
    return markup

# هندلر برای دستور /start
@bot.message_handler(commands=['start'])
def send_welcome(message):
    try:
        user_id = message.from_user.id
        first_name = message.from_user.first_name or ''
        last_name = message.from_user.last_name or ''
        username = message.from_user.username or ''

        # ذخیره کاربر در دیتابیس
        with db_lock:
            conn = sqlite3.connect('database.db', detect_types=sqlite3.PARSE_DECLTYPES, timeout=10)
            c = conn.cursor()

            # بررسی وجود کاربر
            c.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
            exists = c.fetchone()

            if not exists:
                c.execute("""
                    INSERT INTO users (user_id, username, first_name, last_name, join_date, last_active, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (user_id, username, first_name, last_name, datetime.now(), datetime.now(), 1))
            else:
                c.execute("UPDATE users SET last_active = ? WHERE user_id = ?", (datetime.now(), user_id))

            conn.commit()
            conn.close()

        # ارسال پیام خوش‌آمد
        welcome_text = """🎉 <b>به ربات XrayVPN خوش آمدید!</b>

📋 از منوی زیر می‌توانید:
• تست رایگان دریافت کنید 🎁
• پلن دلخواه خود را خریداری کنید 🛍
• وضعیت حساب خود را ببینید 👤
• با پشتیبانی تماس بگیرید 📞

👇 لطفاً یکی از گزینه‌ها را انتخاب کنید:"""

        bot.send_message(
            message.chat.id,
            welcome_text,
            parse_mode='HTML',
            reply_markup=create_main_keyboard()
        )

        log_activity(user_id, "شروع /start", "ورود کاربر جدید")

    except Exception as e:
        print(f"❌ خطا در هندلر /start: {e}")
        bot.send_message(
            message.chat.id,
            "❌ مشکلی در شروع ربات پیش آمد. لطفاً دوباره تلاش کنید.",
            parse_mode='HTML'
        )
# هندلر برای دستور /panel (پنل ادمین)
@bot.message_handler(commands=['panel'])
def admin_panel(message):
    user_id = message.from_user.id
    
    # چک کردن آیا کاربر ادمین است
    if user_id in ADMIN_USER_IDS:
        # دریافت آمار
        with db_lock:
            conn = sqlite3.connect('database.db', detect_types=sqlite3.PARSE_DECLTYPES, timeout=10)
            c = conn.cursor()
            
            c.execute("SELECT COUNT(*) FROM users")
            total_users = c.fetchone()[0]
            
            c.execute("SELECT COUNT(*) FROM purchases WHERE receipt_sent = 1 AND config_sent = 0")
            pending_receipts = c.fetchone()[0]
            
            c.execute("SELECT COUNT(*) FROM users WHERE current_plan IS NOT NULL")
            active_plans = c.fetchone()[0]
            
            c.execute("SELECT COUNT(*) FROM users WHERE free_test_used = 1")
            free_tests = c.fetchone()[0]
            
            conn.close()
        
        # وضعیت لاگ
        log_status = "✅ فعال" if is_log_enabled() else "❌ غیرفعال"
        
        admin_text = f"""👨‍💼 <b>پنل مدیریت ربات XrayVPN</b>

📊 <b>آمار فعلی ربات:</b>
├─ 👥 <b>تعداد کاربران:</b> <code>{total_users}</code>
├─ 📋 <b>درخواست‌های در انتظار:</b> <code>{pending_receipts}</code>
├─ 🎫 <b>پلن‌های فعال:</b> <code>{active_plans}</code>
├─ 🎁 <b>تست‌های رایگان:</b> <code>{free_tests}</code>
├─ 📝 <b>وضعیت لاگ:</b> {log_status}
└─ 📅 <b>امروز:</b> {datetime.now().strftime('%Y-%m-%d')}

🔧 <b>گزینه‌های مدیریت:</b>

👇 <b>لطفاً یکی از گزینه‌های زیر را انتخاب کنید:</b>"""
        
        bot.send_message(
            message.chat.id,
            admin_text,
            reply_markup=create_admin_panel_keyboard(),
            parse_mode='HTML'
        )
        
        log_activity(user_id, "ورود به پنل ادمین", "دسترسی به بخش مدیریت")
    else:
        bot.send_message(
            message.chat.id,
            "⛔ <b>دسترسی غیرمجاز! شما ادمین نیستید.</b>",
            parse_mode='HTML'
        )

# هندلر برای دکمه خرید اشتراک
@bot.message_handler(func=lambda message: message.text == "🛍️ خرید اشتراک")
def show_plans(message):
    user_id = message.from_user.id
    plan_status = check_user_plan_status(user_id)
    
    # اگر کاربر پلن فعال دارد
    if plan_status["has_plan"] or plan_status["has_free_test"]:
        bot.send_message(
            message.chat.id,
            "🔄 <b>شما در حال حاضر یک پلن فعال دارید!</b>\n\n"
            "✅ <b>می‌توانید:</b>\n"
            "• پلن فعلی خود را تمدید کنید\n"
            "• به پلن بالاتر ارتقاء دهید\n"
            "• کاربر اضافه کنید\n\n"
            "👇 <b>لطفاً گزینه مورد نظر خود را انتخاب کنید:</b>",
            reply_markup=create_back_only_keyboard(),
            parse_mode='HTML'
        )
        
        bot.send_message(
            message.chat.id,
            "🎯 <b>با استفاده از دکمه‌های زیر اقدام کنید:</b>",
            reply_markup=create_renew_upgrade_keyboard(),
            parse_mode='HTML'
        )
        
        log_activity(user_id, "ورود به بخش تمدید/ارتقاء", "کاربر پلن فعال دارد")
        return
    
    # اگر کاربر پلن ندارد، منوی خرید عادی
    plans_text = """🤖 <b>پلن‌های موجود ما</b> 🌟

💎 <b>پلن ۱ ماهه:</b>
├─ 📅 مدت: ۳۰ روز
├─ 📊 حجم: نامحدود 🌐
├─ 👤 کاربران: ۱ نفر
└─ 💰 قیمت: ۱۲۰,۰۰۰ تومان

💎 <b>پلن ۱ ماهه (دو کاربره):</b>
├─ 📅 مدت: ۳۰ روز
├─ 📊 حجم: نامحدود 🌐
├─ 👤👤 کاربران: ۲ نفر
└─ 💰 قیمت: ۲۰۰,۰۰۰ تومان

💎 <b>پلن ۲ ماهه:</b>
├─ 📅 مدت: ۶۰ روز
├─ 📊 حجم: نامحدود 🌐
├─ 👤 کاربران: ۱ نفر
└─ 💰 قیمت: ۲۲۰,۰۰۰ تومان

💎 <b>پلن ۲ ماهه (دو کاربره):</b>
├─ 📅 مدت: ۶۰ روز
├─ 📊 حجم: نامحدود 🌐
├─ 👤👤 کاربران: ۲ نفر
└─ 💰 قیمت: ۳۵۰,۰۰۰ تومان

👇 <b>لطفاً یکی از پلن‌های زیر را انتخاب کنید</b> 👇"""
    
    bot.send_message(
        message.chat.id,
        plans_text,
        reply_markup=create_back_only_keyboard(),
        parse_mode='HTML'
    )
    
    # ارسال کیبورد اینلاین برای انتخاب پلن
    bot.send_message(
        message.chat.id,
        "🎯 <b>با استفاده از دکمه‌های زیر، پلن مورد نظر خود را انتخاب کنید:</b>",
        reply_markup=create_plans_inline_keyboard(),
        parse_mode='HTML'
    )
    
    log_activity(user_id, "ورود به بخش خرید", "مشاهده پلن‌ها")

# هندلر برای دکمه تست ۲۴ ساعته
@bot.message_handler(func=lambda message: message.text == "🎁 تست ۲۴ ساعته")
def handle_free_test(message):
    user_id = message.from_user.id
    
    # چک کردن وضعیت کاربر
    plan_status = check_user_plan_status(user_id)
    
    # اگر کاربر قبلاً از تست رایگان استفاده کرده
    if plan_status.get("free_test_expiry") and plan_status["free_test_expiry"] > datetime.now():
        expiry_str = plan_status["free_test_expiry"].strftime('%Y-%m-%d %H:%M')
        bot.send_message(
            message.chat.id,
            f"""⚠️ <b>شما قبلاً از تست رایگان استفاده کرده‌اید!</b>

🎫 <b>تست رایگان شما:</b>
⏳ <b>انقضا:</b> {expiry_str}

🛍️ <b>برای استفاده از سرویس دائمی، لطفاً یک پلن خریداری کنید.</b>""",
            parse_mode='HTML',
            reply_markup=create_main_keyboard()
        )
        return
    
    # چک کردن عضویت در کانال‌ها
    membership_results = check_channel_membership(user_id)
    
    # اگر در همه کانال‌ها عضو نیست
    if not all(membership_results.values()):
        # لیست کانال‌هایی که کاربر عضو نیست
        missing_channels = REQUIRED_CHANNELS
        channels_text = "\n".join([f"• {channel}" for channel in missing_channels])
        
        join_message = f"""🎯 <b>برای استفاده از تست رایگان ۲۴ ساعته، لازم است در کانال‌های زیر عضو باشید:</b> 

{channels_text}

👇 <b>لطفاً با استفاده از دکمه‌های زیر در کانال‌ها عضو شوید، سپس روی «بررسی عضویت مجدد» کلیک کنید:</b>"""
        
        bot.send_message(
            message.chat.id,
            join_message,
            reply_markup=create_channel_join_keyboard(),
            parse_mode='HTML'
        )
        
        log_activity(user_id, "تلاش برای دریافت تست رایگان", "عضو کانال‌ها نیست")
    else:
        # فعال‌سازی تست رایگان
        set_free_test_used(user_id)
        
        # تولید کانفیگ تست
        test_config = f"""🎉 <b>تبریک! تست رایگان ۲۴ ساعته برای شما فعال شد!</b> ⚡

🔗 <b>کانفیگ تست شما:</b>
<code>vless://test_{user_id}@vpn.xray.com:443?type=tcp&security=reality&sni=google.com&fp=chrome&pbk=public_key&sid={user_id}#XrayVPN-Free-Test</code>

📋 <b>مشخصات:</b>
├─ ⏰ مدت: ۲۴ ساعت
├─ 📊 حجم: ۵۰ گیگابایت
├─ 👤 کاربران: ۱ نفر
├─ 🚀 سرعت: نامحدود
└─ 🔒 پروتکل: V2Ray + Reality

💡 <b>نکات مهم:</b>
• بعد از اتمام تست، می‌توانید از منوی اصلی پلن دائمی خریداری کنید
• این تست فقط یک بار برای هر کاربر قابل استفاده است
• در صورت بروز مشکل با پشتیبانی تماس بگیرید

🌟 <b>از همراهی شما متشکریم!</b>"""
        
        bot.send_message(
            message.chat.id,
            test_config,
            parse_mode='HTML',
            reply_markup=create_main_keyboard()
        )
        
        log_activity(user_id, "فعال‌سازی تست رایگان", "کانفیگ ارسال شد")

# هندلر برای سایر دکمه‌های اصلی
@bot.message_handler(func=lambda message: message.text in ["👤 حساب کاربری", "📞 پشتیبانی", "🔙 بازگشت"])
def handle_main_buttons(message):
    user_id = message.from_user.id
    
    if message.text == "👤 حساب کاربری":
        plan_status = check_user_plan_status(user_id)
        user = get_user_info(user_id)
        
        if user:
            # ایندکس‌های ستون‌ها
            # 0: user_id, 1: username, 2: first_name, 3: last_name, 
            # 4: current_plan, 5: plan_expiry, 6: free_test_used, 7: free_test_expiry
            # 8: join_date, 9: last_active, 10: is_active
            
            join_date = user[8] if user[8] else "نامشخص"
            if isinstance(join_date, datetime):
                join_date = join_date.strftime('%Y-%m-%d')
            
            # ساختن متن حساب کاربری
            user_info_text = f"""📊 <b>حساب کاربری شما</b> 👤

👤 <b>نام:</b> {user[2]} {user[3] or ''}
🆔 <b>یوزرنیم:</b> @{user[1] or 'ندارد'}
📅 <b>تاریخ عضویت:</b> {join_date}

"""
            
            # اضافه کردن اطلاعات پلن
            if plan_status["has_plan"]:
                expiry = plan_status["plan_expiry"]
                if expiry:
                    days_left = (expiry - datetime.now()).days
                    days_left = max(0, days_left)
                    
                    user_info_text += f"""✅ <b>پلن فعال:</b> {plan_status['current_plan']}
⏳ <b>مدت باقی‌مانده:</b> {days_left} روز
📅 <b>تاریخ انقضا:</b> {expiry.strftime('%Y-%m-%d %H:%M')}

🌟 <b>ویژگی‌های پلن شما:</b>
├─ 📊 حجم مصرفی: نامحدود
├─ 👥 کاربران مجاز: {'۲ نفر' if 'دو' in plan_status['current_plan'] else '۱ نفر'}
└─ 🚀 سرعت: پرسرعت

"""
            elif plan_status["free_test_expiry"] and plan_status["free_test_expiry"] > datetime.now():
                expiry = plan_status["free_test_expiry"]
                hours_left = int((expiry - datetime.now()).total_seconds() / 3600)
                hours_left = max(0, hours_left)
                
                user_info_text += f"""🎁 <b>پلن فعال:</b> تست رایگان ۲۴ ساعته
⏳ <b>زمان باقی‌مانده:</b> {hours_left} ساعت
📅 <b>تاریخ انقضا:</b> {expiry.strftime('%Y-%m-%d %H:%M')}

🌟 <b>ویژگی‌های پلن شما:</b>
├─ 📊 حجم مصرفی: ۵۰ گیگابایت
├─ 👥 کاربران مجاز: ۱ نفر
└─ 🚀 سرعت: پرسرعت

"""
            else:
                user_info_text += """🔍 <b>شما هنوز هیچ اشتراک فعالی ندارید.</b>

🎁 <b>می‌توانید از تست رایگان ۲۴ ساعته استفاده کنید:</b>
🎁 تست ۲۴ ساعته

🛍️ <b>یا پلن دلخواه خود را خریداری کنید:</b>
🛍️ خرید اشتراک

"""
            
            user_info_text += "💖 <b>منتظر حضور گرم شما هستیم!</b>"
            
            bot.send_message(
                message.chat.id,
                user_info_text,
                parse_mode='HTML',
                reply_markup=create_main_keyboard()
            )
            log_activity(user_id, "مشاهده حساب کاربری", "اطلاعات نمایش داده شد")
        else:
            bot.send_message(
                message.chat.id,
                "❌ <b>خطا در دریافت اطلاعات!</b>\nلطفاً دوباره تلاش کنید.",
                parse_mode='HTML',
                reply_markup=create_main_keyboard()
            )
        
    elif message.text == "📞 پشتیبانی":
        support_info = """📞 <b>راه‌های ارتباط با پشتیبانی:</b>

🔹 <b>پشتیبانی تلگرام:</b>
   👨‍💼 @XrayVPN_Support
   ⏰ ۲۴ ساعته - ۷ روز هفته

🔹 <b>کانال اطلاع‌رسانی:</b>
   📢 @XrayVPNpro

🔹 <b>گروه پشتیبانی:</b>
   👥 @il_timore

⏳ <b>زمان پاسخگویی:</b> کمتر از ۱۵ دقیقه
🤝 <b>تیم پشتیبانی ما آماده پاسخگویی به شماست!</b>"""
        
        bot.send_message(
            message.chat.id,
            support_info,
            reply_markup=create_main_keyboard(),
            parse_mode='HTML'
        )
        log_activity(user_id, "درخواست پشتیبانی", "مشاهده اطلاعات تماس")
        
    elif message.text == "🔙 بازگشت":
        bot.send_message(
            message.chat.id,
            "🏠 <b>به منوی اصلی بازگشتید!</b>",
            reply_markup=create_main_keyboard(),
            parse_mode='HTML'
        )
        log_activity(user_id, "بازگشت به منوی اصلی", "از بخش فعلی خارج شد")

# هندلر برای کلیک روی دکمه‌های اینلاین
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    user_id = call.from_user.id
    
    # بررسی عضویت در کانال
    if call.data == "check_membership":
        try:
            membership_results = check_channel_membership(user_id)
            
            if all(membership_results.values()):
                bot.answer_callback_query(call.id, "✅ شما در همه کانال‌ها عضو هستید!")
                
                # فعال‌سازی تست رایگان
                set_free_test_used(user_id)
                
                # ارسال تست رایگان
                test_config = f"""🎉 <b>تبریک! تست رایگان ۲۴ ساعته برای شما فعال شد!</b> ⚡

🔗 <b>کانفیگ تست شما:</b>
<code>vless://test_{user_id}@vpn.xray.com:443?type=tcp&security=reality&sni=google.com&fp=chrome&pbk=public_key&sid={user_id}#XrayVPN-Free-Test</code>

📋 <b>مشخصات تست:</b>
├─ ⏰ مدت: ۲۴ ساعت
├─ 📊 حجم: ۵۰ گیگابایت
└─ 👤 کاربران: ۱ نفر

💖 <b>از همراهی شما متشکریم!</b>"""
                
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text=test_config,
                    parse_mode='HTML'
                )
                log_activity(user_id, "تست رایگان فعال شد", "پس از عضویت در کانال‌ها")
            else:
                bot.answer_callback_query(call.id, "❌ هنوز در برخی کانال‌ها عضو نشدید!")
                
        except Exception as e:
            print(f"خطا در بررسی عضویت: {e}")
            bot.answer_callback_query(call.id, "❌ خطا در بررسی عضویت!")
    
    # انتخاب پلن
    elif call.data.startswith("plan_"):
        plan_id = call.data.split("_")[1]
        
        plans_info = {
            "1": {
                "name": "پلن ۱ ماهه - یک کاربر",
                "duration": "۳۰ روز",
                "users": "۱ نفر",
                "price": "۱۲۰,۰۰۰ تومان"
            },
            "2": {
                "name": "پلن ۱ ماهه - دو کاربر",
                "duration": "۳۰ روز",
                "users": "۲ نفر",
                "price": "۲۰۰,۰۰۰ تومان"
            },
            "3": {
                "name": "پلن ۲ ماهه - یک کاربر",
                "duration": "۶۰ روز",
                "users": "۱ نفر",
                "price": "۲۲۰,۰۰۰ تومان"
            },
            "4": {
                "name": "پلن ۲ ماهه - دو کاربر",
                "duration": "۶۰ روز",
                "users": "۲ نفر",
                "price": "۳۵۰,۰۰۰ تومان"
            }
        }
        
        plan = plans_info[plan_id]
        
        plan_details = f"""🎯 <b>{plan['name']}</b>

📋 <b>مشخصات پلن:</b>
├─ 📅 مدت زمان: {plan['duration']}
├─ 📊 حجم مصرف: نامحدود 🌐
├─ 👥 کاربران: {plan['users']}
├─ 🚀 سرعت: پرسرعت
├─ 🔒 پروتکل: V2Ray + Reality
└─ 💰 قیمت: <b>{plan['price']}</b>

⚡ <b>ویژگی‌های خاص:</b>
• آی‌پی ثابت ایران 🇮🇷
• پشتیبانی از کلیه پروتکل‌ها
• اتصال همزمان چند دستگاه
• پینگ پایین و پایدار

👇 <b>برای ادامه خرید، دکمه زیر را انتخاب کنید</b> 👇"""
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=plan_details,
            parse_mode='HTML',
            reply_markup=create_confirm_purchase_keyboard(plan_id)
        )
        
        log_activity(user_id, "انتخاب پلن", f"پلن {plan_id} انتخاب شد")
    
    # تأیید خرید
    elif call.data.startswith("confirm_"):
        plan_id = call.data.split("_")[1]
        
        # ذخیره اطلاعات خرید در دیتابیس
        with db_lock:
            conn = sqlite3.connect('database.db', detect_types=sqlite3.PARSE_DECLTYPES, timeout=10)
            c = conn.cursor()
            
            # دریافت قیمت پلن
            prices = {"1": 120000, "2": 200000, "3": 220000, "4": 350000}
            plan_types = {
                "1": "پلن ۱ ماهه - یک کاربر",
                "2": "پلن ۱ ماهه - دو کاربر",
                "3": "پلن ۲ ماهه - یک کاربر",
                "4": "پلن ۲ ماهه - دو کاربر"
            }
            
            plan_type = plan_types[plan_id]
            amount = prices[plan_id]
            
            c.execute("INSERT INTO purchases (user_id, plan_type, amount, payment_date) VALUES (?, ?, ?, ?)",
                      (user_id, plan_type, amount, datetime.now()))
            purchase_id = c.lastrowid
            conn.commit()
            conn.close()
        
        payment_info = f"""💳 <b>مرحله پرداخت</b>

🎯 <b>پلن انتخاب شده:</b> {plan_type}
💰 <b>مبلغ قابل پرداخت:</b> {amount:,} تومان

<b>لطفاً مبلغ خرید را به شماره کارت زیر واریز کنید:</b>
<code>۶۲۱۹ ۸۶۱۰ ۰۵۱۲ ۳۴۵۶</code>
🏦 <b>بانک ملت - به نام علی رضایی</b>

📌 <b>نکات مهم:</b>
• پس از واریز، <b>حتماً عکس رسید بانکی</b> را ارسال کنید 📸
• لطفاً پیام اضافه‌ای ارسال نکنید، <b>فقط عکس رسید</b> را بفرستید 🤐
• پس از تأیید رسید، کانفیگ شما در <b>کمتر از ۵ دقیقه</b> ارسال خواهد شد ⚡
• در صورت بروز مشکل، با پشتیبانی تماس بگیرید 📞

🛍️ <b>شماره سفارش:</b> <code>#{purchase_id}</code>

🙏 <b>با تشکر از اعتماد و انتخاب شما</b> 🌟
💖 <b>کیفیت خدمات، اولویت ماست!</b>"""
        
        bot.delete_message(call.message.chat.id, call.message.message_id)
        
        bot.send_message(
            call.message.chat.id,
            payment_info,
            parse_mode='HTML',
            reply_markup=create_back_only_keyboard()
        )
        
        log_activity(user_id, "شروع فرآیند خرید", f"پلن {plan_id} - سفارش #{purchase_id}")
    
    # لغو خرید
    elif call.data == "cancel_purchase":
        bot.answer_callback_query(call.id, "❌ خرید لغو شد")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        
        bot.send_message(
            call.message.chat.id,
            "🛍️ <b>خرید لغو شد. برای مشاهده مجدد پلن‌ها، دکمه «خرید اشتراک» را انتخاب کنید.</b>",
            reply_markup=create_main_keyboard(),
            parse_mode='HTML'
        )
        
        log_activity(user_id, "لغو خرید", "کاربر خرید را لغو کرد")
    
    # بازگشت به حساب کاربری
    elif call.data == "back_to_account":
        bot.answer_callback_query(call.id, "🔙 بازگشت به حساب کاربری")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        
        # شبیه‌سازی کلیک روی دکمه حساب کاربری
        mock_message = type('obj', (object,), {'chat': type('obj', (object,), {'id': call.message.chat.id})(), 
                                              'from_user': type('obj', (object,), {'id': user_id})(),
                                              'text': "👤 حساب کاربری"})()
        handle_main_buttons(mock_message)
    
    # تمدید پلن
    elif call.data == "renew_plan":
        plan_status = check_user_plan_status(user_id)
        
        if plan_status["has_plan"]:
            current_plan = plan_status["current_plan"]
            
            renew_message = f"""🔄 <b>تمدید پلن فعلی</b>

📋 <b>پلن فعلی شما:</b> {current_plan}

💰 <b>هزینه تمدید:</b>
• پلن ۱ ماهه: ۱۲۰,۰۰۰ تومان
• پلن ۲ ماهه: ۲۲۰,۰۰۰ تومان

👇 <b>لطفاً پلن مورد نظر برای تمدید را انتخاب کنید:</b>"""
            
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=renew_message,
                parse_mode='HTML',
                reply_markup=create_plans_inline_keyboard()
            )
        else:
            bot.answer_callback_query(call.id, "❌ شما پلن فعالی ندارید!")
    
    # ارتقاء پلن
    elif call.data == "upgrade_plan":
        plan_status = check_user_plan_status(user_id)
        
        if plan_status["has_plan"]:
            current_plan = plan_status["current_plan"]
            
            upgrade_message = f"""⬆️ <b>ارتقاء پلن</b>

📋 <b>پلن فعلی شما:</b> {current_plan}

🎯 <b>گزینه‌های ارتقاء:</b>
• از یک کاربره به دو کاربره: +۸۰,۰۰۰ تومان
• از ۱ ماهه به ۲ ماهه: +۱۰۰,۰۰۰ تومان
• از یک کاربره ۱ ماهه به دو کاربره ۲ ماهه: +۲۳۰,۰۰۰ تومان

👇 <b>لطفاً پلن جدید مورد نظر را انتخاب کنید:</b>"""
            
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=upgrade_message,
                parse_mode='HTML',
                reply_markup=create_plans_inline_keyboard()
            )
        else:
            bot.answer_callback_query(call.id, "❌ شما پلن فعالی ندارید!")
    
    # اضافه کردن کاربر
    elif call.data == "add_user":
        plan_status = check_user_plan_status(user_id)
        
        if plan_status["has_plan"] and "یک کاربر" in plan_status["current_plan"]:
            add_user_message = f"""➕ <b>اضافه کردن کاربر</b>

📋 <b>پلن فعلی شما:</b> {plan_status['current_plan']}

💰 <b>هزینه اضافه کردن کاربر:</b> ۸۰,۰۰۰ تومان

✅ <b>پس از پرداخت:</b>
• پلن شما از یک کاربره به دو کاربره تبدیل می‌شود
• مدت زمان پلن تغییر نمی‌کند
• امکان اتصال همزمان ۲ دستگاه فراهم می‌شود

👇 <b>برای ادامه، تأیید کنید:</b>"""
            
            markup = InlineKeyboardMarkup(row_width=2)
            btn_confirm = InlineKeyboardButton("✅ تأیید و پرداخت", callback_data="add_user_confirm")
            btn_cancel = InlineKeyboardButton("❌ انصراف", callback_data="back_to_account")
            markup.add(btn_confirm, btn_cancel)
            
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=add_user_message,
                parse_mode='HTML',
                reply_markup=markup
            )
        else:
            if not plan_status["has_plan"]:
                bot.answer_callback_query(call.id, "❌ شما پلن فعالی ندارید!")
            else:
                bot.answer_callback_query(call.id, "❌ پلن شما از قبل دو کاربره است!")
    
    # تأیید اضافه کردن کاربر
    elif call.data == "add_user_confirm":
        bot.answer_callback_query(call.id, "✅ درخواست شما ثبت شد!")
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="➕ <b>اضافه کردن کاربر</b>\n\n"
                 "💰 <b>مبلغ قابل پرداخت:</b> ۸۰,۰۰۰ تومان\n\n"
                 "💳 <b>لطفاً مبلغ را به شماره کارت زیر واریز کنید:</b>\n"
                 "<code>۶۲۱۹ ۸۶۱۰ ۰۵۱۲ ۳۴۵۶</code>\n"
                 "🏦 بانک ملت - به نام علی رضایی\n\n"
                 "📸 پس از واریز، عکس رسید را ارسال کنید.",
            parse_mode='HTML'
        )
    
    # خاموش/روشن کردن لاگ
    elif call.data == "admin_toggle_log":
        if call.from_user.id in ADMIN_USER_IDS:
            try:
                new_status = toggle_log_status()
                status_text = "✅ فعال" if new_status else "❌ غیرفعال"
                
                bot.answer_callback_query(call.id, f"✅ وضعیت لاگ به {status_text} تغییر یافت")
                
                # آپدیت کیبورد
                bot.edit_message_reply_markup(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    reply_markup=create_admin_panel_keyboard()
                )
                
                # ارسال پیام تأیید
                log_message = f"""⚙️ <b>تغییر تنظیمات سیستم</b>

👨‍💼 <b>ادمین:</b> {call.from_user.first_name}
📝 <b>تنظیمات:</b> وضعیت لاگ
🔄 <b>تغییر:</b> {status_text}
⏰ <b>زمان:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
                
                bot.send_message(
                    ADMIN_GROUP_ID,
                    log_message,
                    parse_mode='HTML'
                )
                
            except Exception as e:
                print(f"خطا در تغییر وضعیت لاگ: {e}")
                bot.answer_callback_query(call.id, "❌ خطا در تغییر وضعیت لاگ!")
        else:
            bot.answer_callback_query(call.id, "❌ دسترسی غیرمجاز!")
    
    # عملیات ادمین - لیست کاربران
    elif call.data == "admin_users":
        if call.from_user.id in ADMIN_USER_IDS:
            with db_lock:
                conn = sqlite3.connect('database.db', detect_types=sqlite3.PARSE_DECLTYPES, timeout=10)
                c = conn.cursor()
                c.execute("SELECT COUNT(*) FROM users")
                total_users = c.fetchone()[0]
                
                c.execute("SELECT user_id, username, first_name, last_name, join_date, current_plan FROM users ORDER BY join_date DESC LIMIT 15")
                recent_users = c.fetchall()
                
                conn.close()
            
            users_info = f"""📊 <b>آمار کاربران ربات</b>

👥 <b>مجموع کاربران:</b> <code>{total_users}</code>

📋 <b>۱۵ کاربر آخر:</b>\n"""
            
            for i, user in enumerate(recent_users, 1):
                plan_status = (
    f"✅ {user[5]}" if len(user) > 5 and user[5]
    else "🎁 تست" if len(user) > 6 and user[6]
    else "❌ بدون پلن"
)
                join_date = user[4].strftime('%Y-%m-%d') if isinstance(user[4], datetime) else str(user[4])
                users_info += f"\n{i}. 👤 <b>آیدی:</b> <code>{user[0]}</code> | <b>نام:</b> {user[2]} {user[3]} | <b>وضعیت:</b> {plan_status} | <b>عضویت:</b> {join_date}"
            
            bot.send_message(
                call.message.chat.id,
                users_info,
                parse_mode='HTML',
                reply_to_message_id=call.message.message_id
            )
            
            bot.answer_callback_query(call.id, "✅ لیست کاربران نمایش داده شد")
            log_activity(call.from_user.id, "مشاهده لیست کاربران", "در پنل ادمین")
    
    # عملیات ادمین - رسیدهای در انتظار
    elif call.data == "admin_pending":
        if call.from_user.id in ADMIN_USER_IDS:
            with db_lock:
                conn = sqlite3.connect('database.db', detect_types=sqlite3.PARSE_DECLTYPES, timeout=10)
                c = conn.cursor()
                c.execute("SELECT COUNT(*) FROM purchases WHERE receipt_sent = 1 AND config_sent = 0")
                pending_count = c.fetchone()[0]
                
                if pending_count > 0:
                    c.execute("SELECT p.id, p.user_id, p.plan_type, p.payment_date, u.first_name, u.last_name, u.username FROM purchases p LEFT JOIN users u ON p.user_id = u.user_id WHERE p.receipt_sent = 1 AND p.config_sent = 0 ORDER BY p.payment_date DESC LIMIT 10")
                    pending_orders = c.fetchall()
                    
                    pending_info = f"""📋 <b>رسیدهای در انتظار تأیید</b>

⏳ <b>تعداد درخواست‌های در انتظار:</b> <code>{pending_count}</code>\n"""
                    
                    for order in pending_orders:
                        pending_info += f"\n🆔 <b>شماره سفارش:</b> <code>{order[0]}</code>"
                        pending_info += f"\n👤 <b>کاربر:</b> {order[4]} {order[5]} (@{order[6] or 'ندارد'})"
                        pending_info += f"\n📦 <b>پلن:</b> {order[2]}"
                        payment_date = order[3].strftime('%Y-%m-%d %H:%M') if isinstance(order[3], datetime) else str(order[3])
                        pending_info += f"\n📅 <b>تاریخ:</b> {payment_date}"
                        pending_info += "\n" + "─" * 30 + "\n"
                    
                    bot.send_message(
                        call.message.chat.id,
                        pending_info,
                        parse_mode='HTML',
                        reply_to_message_id=call.message.message_id
                    )
                else:
                    bot.answer_callback_query(call.id, "✅ هیچ رسید در انتظاری وجود ندارد")
                
                conn.close()
    
    # عملیات ادمین - لاگ فعالیت‌ها
    elif call.data == "admin_logs":
        if call.from_user.id in ADMIN_USER_IDS:
            with db_lock:
                conn = sqlite3.connect('database.db', detect_types=sqlite3.PARSE_DECLTYPES, timeout=10)
                c = conn.cursor()
                c.execute("SELECT COUNT(*) FROM activity_logs")
                total_logs = c.fetchone()[0]
                
                c.execute("SELECT * FROM activity_logs ORDER BY activity_date DESC LIMIT 10")
                recent_logs = c.fetchall()
                
                conn.close()
            
            logs_info = f"""📝 <b>لاگ فعالیت‌های ربات</b>

📊 <b>تعداد کل لاگ‌ها:</b> <code>{total_logs}</code>

📋 <b>۱۰ فعالیت آخر:</b>\n"""
            
            for i, log in enumerate(recent_logs, 1):
                # 0: id, 1: user_id, 2: activity_type, 3: activity_details, 4: activity_date
                log_time = log[4].strftime('%H:%M') if isinstance(log[4], datetime) else str(log[4])
                logs_info += f"\n{i}. ⏰ <b>{log_time}</b> | 👤 <code>{log[1]}</code> | 📝 {log[2]} | {log[3]}"
            
            bot.send_message(
                call.message.chat.id,
                logs_info,
                parse_mode='HTML',
                reply_to_message_id=call.message.message_id
            )
            
            bot.answer_callback_query(call.id, "✅ لاگ فعالیت‌ها نمایش داده شد")
            log_activity(call.from_user.id, "مشاهده لاگ فعالیت‌ها", "در پنل ادمین")
    
    # عملیات ادمین - آمار
    elif call.data == "admin_stats":
        if call.from_user.id in ADMIN_USER_IDS:
            with db_lock:
                conn = sqlite3.connect('database.db', detect_types=sqlite3.PARSE_DECLTYPES, timeout=10)
                c = conn.cursor()
                
                c.execute("SELECT COUNT(*) FROM users")
                total_users = c.fetchone()[0]
                
                c.execute("SELECT COUNT(*) FROM purchases")
                total_purchases = c.fetchone()[0]
                
                c.execute("SELECT COUNT(*) FROM purchases WHERE config_sent = 1")
                completed_purchases = c.fetchone()[0]
                
                c.execute("SELECT COUNT(*) FROM purchases WHERE receipt_sent = 1 AND config_sent = 0")
                pending_purchases = c.fetchone()[0]
                
                c.execute("SELECT COUNT(*) FROM users WHERE current_plan IS NOT NULL")
                active_plans = c.fetchone()[0]
                
                c.execute("SELECT COUNT(*) FROM users WHERE free_test_used = 1")
                free_tests = c.fetchone()[0]
                
                # محاسبه درآمد تخمینی
                c.execute("SELECT SUM(amount) FROM purchases WHERE config_sent = 1")
                total_income = c.fetchone()[0] or 0
                
                conn.close()
            
            stats_info = f"""📊 <b>آمار کامل ربات</b>

👥 <b>کاربران:</b>
├─ کل کاربران: <code>{total_users}</code>
├─ پلن‌های فعال: <code>{active_plans}</code>
└─ تست‌های رایگان: <code>{free_tests}</code>

💰 <b>فروش:</b>
├─ کل خریدها: <code>{total_purchases}</code>
├─ تکمیل شده: <code>{completed_purchases}</code>
├─ در انتظار: <code>{pending_purchases}</code>
└─ درآمد تخمینی: <code>{total_income:,}</code> تومان

📈 <b>نرخ تبدیل:</b>
• خرید به کاربر: {round((completed_purchases/total_users)*100, 2) if total_users > 0 else 0}%
• تکمیل خرید: {round((completed_purchases/total_purchases)*100, 2) if total_purchases > 0 else 0}%

⏰ <b>آخرین بروزرسانی:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
            
            bot.send_message(
                call.message.chat.id,
                stats_info,
                parse_mode='HTML',
                reply_to_message_id=call.message.message_id
            )
            
            bot.answer_callback_query(call.id, "✅ آمار ربات نمایش داده شد")
            log_activity(call.from_user.id, "مشاهده آمار ربات", "در پنل ادمین")
    
    # تأیید رسید توسط ادمین
    elif call.data.startswith("admin_confirm_"):
        purchase_id = call.data.split("_")[2]
        
        if call.from_user.id in ADMIN_USER_IDS:
            try:
                # دریافت اطلاعات خرید
                with db_lock:
                    conn = sqlite3.connect('database.db', detect_types=sqlite3.PARSE_DECLTYPES, timeout=10)
                    c = conn.cursor()
                    c.execute("SELECT user_id, plan_type FROM purchases WHERE id = ?", (purchase_id,))
                    result = c.fetchone()
                    
                    if result:
                        user_id = result[0]
                        plan_type = result[1]
                        
                        # به‌روزرسانی پلن کاربر
                        expiry_date = datetime.now() + timedelta(days=60 if "۲ ماهه" in plan_type else 30)
                        c.execute("UPDATE users SET current_plan = ?, plan_expiry = ? WHERE user_id = ?",
                                  (plan_type, expiry_date, user_id))
                        
                        # آپدیت وضعیت خرید
                        c.execute("UPDATE purchases SET config_sent = 1 WHERE id = ?", (purchase_id,))
                        conn.commit()
                        conn.close()
                        
                        # ارسال کانفیگ به کاربر
                        config_message = f"""🎉 <b>تبریک! پرداخت شما تأیید شد!</b> ✅

🔗 <b>کانفیگ اختصاصی شما:</b>
<code>vless://user_{user_id}@server.xrayvpn.com:443?type=tcp&security=reality&sni=google.com&fp=chrome&pbk=public_key&sid={purchase_id}#XrayVPN-{purchase_id}</code>

📋 <b>مشخصات پلن شما:</b>
├─ 📅 مدت: {'۶۰ روز' if '۲ ماهه' in plan_type else '۳۰ روز'}
├─ 📊 حجم: نامحدود
├─ 👥 کاربران: {'۲ نفر' if 'دو' in plan_type else '۱ نفر'}
├─ 🚀 سرعت: پرسرعت
└─ 🔒 پروتکل: V2Ray + Reality

💡 <b>راهنمای اتصال:</b>
1. اپلیکیشن V2Ray را نصب کنید
2. کانفیگ بالا را وارد کنید
3. روی Connect کلیک کنید
4. از اینترنت پرسرعت لذت ببرید! 🚀

📞 <b>برای پشتیبانی:</b> @XrayVPN_Support"""
                        
                        try:
                            bot.send_message(user_id, config_message, parse_mode='HTML')
                            
                            # آپدیت پیام در گروه ادمین
                            bot.edit_message_caption(
                                chat_id=call.message.chat.id,
                                message_id=call.message.message_id,
                                caption=f"✅ <b>رسید شماره {purchase_id} تأیید و کانفیگ ارسال شد.</b>",
                                parse_mode='HTML'
                            )
                            
                            bot.answer_callback_query(call.id, "✅ کانفیگ ارسال شد!")
                            log_activity(user_id, "پرداخت تأیید شد", f"سفارش #{purchase_id} - {plan_type}")
                            log_activity(call.from_user.id, "تأیید پرداخت کاربر", f"کاربر {user_id} - سفارش #{purchase_id}")
                            
                        except Exception as e:
                            print(f"خطا در ارسال کانفیگ: {e}")
                            bot.answer_callback_query(call.id, "❌ کاربر پیام‌ها را بلاک کرده است!")
                    else:
                        bot.answer_callback_query(call.id, "❌ سفارش یافت نشد!")
                    
            except Exception as e:
                print(f"خطا در تأیید رسید: {e}")
                bot.answer_callback_query(call.id, "❌ خطا در تأیید رسید!")
    
    # رد رسید توسط ادمین
    elif call.data.startswith("admin_reject_"):
        purchase_id = call.data.split("_")[2]
        
        if call.from_user.id in ADMIN_USER_IDS:
            try:
                # دریافت اطلاعات خرید
                with db_lock:
                    conn = sqlite3.connect('database.db', detect_types=sqlite3.PARSE_DECLTYPES, timeout=10)
                    c = conn.cursor()
                    c.execute("SELECT user_id FROM purchases WHERE id = ?", (purchase_id,))
                    result = c.fetchone()
                    
                    if result:
                        user_id = result[0]
                        
                        # آپدیت پیام در گروه ادمین
                        bot.edit_message_caption(
                            chat_id=call.message.chat.id,
                            message_id=call.message.message_id,
                            caption=f"❌ <b>رسید شماره {purchase_id} رد شد.</b>",
                            parse_mode='HTML'
                        )
                        
                        # اطلاع به کاربر
                        try:
                            bot.send_message(
                                user_id,
                                "❌ <b>متأسفانه پرداخت شما تأیید نشد!</b>\n\n"
                                "📞 <b>لطفاً با پشتیبانی تماس بگیرید:</b> @XrayVPN_Support",
                                parse_mode='HTML'
                            )
                        except:
                            pass
                        
                        bot.answer_callback_query(call.id, "❌ رسید رد شد!")
                        log_activity(user_id, "پرداخت رد شد", f"سفارش #{purchase_id}")
                        log_activity(call.from_user.id, "رد پرداخت کاربر", f"کاربر {user_id} - سفارش #{purchase_id}")
                    else:
                        bot.answer_callback_query(call.id, "❌ سفارش یافت نشد!")
                    
                    conn.close()
            except Exception as e:
                print(f"خطا در رد رسید: {e}")
                bot.answer_callback_query(call.id, "❌ خطا در رد رسید!")

# هندلر برای دریافت عکس (رسید بانکی)
@bot.message_handler(content_types=['photo'])
def handle_receipt_photo(message):
    try:
        user_id = message.from_user.id
        
        # دریافت اطلاعات عکس
        file_id = message.photo[-1].file_id
        
        # دریافت آخرین خرید کاربر
        with db_lock:
            conn = sqlite3.connect('database.db', detect_types=sqlite3.PARSE_DECLTYPES, timeout=10)
            c = conn.cursor()
            c.execute("SELECT id, plan_type, amount FROM purchases WHERE user_id = ? AND receipt_sent = 0 ORDER BY id DESC LIMIT 1", 
                      (user_id,))
            result = c.fetchone()
            
            if not result:
                bot.reply_to(
                    message,
                    "❌ <b>شما هیچ خرید در حال انتظاری ندارید. لطفاً ابتدا پلن مورد نظر خود را انتخاب کنید.</b>",
                    parse_mode='HTML'
                )
                conn.close()
                return
            
            purchase_id, plan_type, amount = result
            
            # آپدیت اطلاعات خرید
            c.execute("UPDATE purchases SET receipt_sent = 1, receipt_photo_id = ? WHERE id = ?",
                      (file_id, purchase_id))
            conn.commit()
            conn.close()
        
        # ارسال به گروه ادمین
        user_info = f"""📨 <b>رسید جدید دریافت شد!</b> 📸

👤 <b>اطلاعات کاربر:</b>
├─ 🔢 <b>آیدی:</b> <code>{message.from_user.id}</code>
├─ 👤 <b>نام:</b> {message.from_user.first_name or 'نامشخص'}
├─ 📛 <b>نام خانوادگی:</b> {message.from_user.last_name or 'نامشخص'}
├─ 🆔 <b>یوزرنیم:</b> @{message.from_user.username or 'ندارد'}
└─ 📅 <b>زمان:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🛍️ <b>اطلاعات سفارش:</b>
├─ 🆔 <b>شماره سفارش:</b> <code>#{purchase_id}</code>
├─ 📦 <b>پلن:</b> {plan_type}
└─ 💰 <b>مبلغ:</b> {amount:,} تومان

👇 <b>لطفاً اقدام مناسب را انتخاب کنید:</b>"""
        
        # ارسال به گروه ادمین
        admin_msg_id = send_to_admin_group(
            user_info,
            photo_file_id=file_id,
            reply_markup=create_receipt_admin_keyboard(purchase_id)
        )
        
        # ذخیره آیدی پیام در دیتابیس
        if admin_msg_id:
            with db_lock:
                conn = sqlite3.connect('database.db', detect_types=sqlite3.PARSE_DECLTYPES, timeout=10)
                c = conn.cursor()
                c.execute("UPDATE purchases SET admin_group_msg_id = ? WHERE id = ?",
                          (admin_msg_id, purchase_id))
                conn.commit()
                conn.close()
        
        # پاسخ به کاربر
        bot.reply_to(
            message,
            "✅ <b>رسید بانکی شما با موفقیت دریافت شد!</b> 🙏\n\n"
            "🔄 <b>در حال بررسی و تأیید پرداخت شما هستیم...</b>\n"
            "⏳ <b>لطفاً کمی صبر کنید، کانفیگ شما به زودی ارسال خواهد شد.</b> ⚡\n\n"
            "💖 <b>از صبر و شکیبایی شما متشکریم</b> 🌟",
            parse_mode='HTML',
            reply_markup=create_back_only_keyboard()
        )
        
        log_activity(user_id, "ارسال رسید بانکی", f"سفارش #{purchase_id} - {plan_type}")
        
    except Exception as e:
        print(f"خطا در دریافت رسید: {e}")
        bot.reply_to(
            message,
            "❌ <b>متأسفانه در دریافت رسید مشکلی پیش آمد. لطفاً دوباره تلاش کنید.</b>",
            parse_mode='HTML'
        )

# هندلر برای پیام‌های متنی دیگر
@bot.message_handler(func=lambda message: True)
def handle_other_messages(message):
    if message.text and message.text not in ["🛍️ خرید اشتراک", "🎁 تست ۲۴ ساعته", 
                                           "👤 حساب کاربری", "📞 پشتیبانی", "🔙 بازگشت"]:
        bot.send_message(
            message.chat.id,
            "🤔 <b>متوجه نشدم! لطفاً از دکمه‌های موجود استفاده کنید.</b> 🙏\n\n"
            "<b>اگر نیاز به کمک دارید، از دکمه «📞 پشتیبانی» استفاده کنید.</b>",
            reply_markup=create_main_keyboard(),
            parse_mode='HTML'
        )
        log_activity(message.from_user.id, "پیام نامفهوم", f"پیام: {message.text[:50]}")

def main():
    print("🤖 ربات XrayVPN در حال اجراست...")
    print(f"📢 کانال‌های اجباری: {REQUIRED_CHANNELS}")
    print(f"👨‍💼 آیدی ادمین‌ها: {ADMIN_USER_IDS}")
    print(f"📁 گروه ادمین: {ADMIN_GROUP_ID}")
    print(f"📝 وضعیت لاگ: {'✅ فعال' if is_log_enabled() else '❌ غیرفعال'}")
    
    # بررسی وجود پوشه receipts
    if not os.path.exists('receipts'):
        os.makedirs('receipts')
        print("✅ پوشه receipts ایجاد شد.")
    
    try:
        # تست اتصال به تلگرام
        bot_info = bot.get_me()
        print(f"✅ ربات با موفقیت راه‌اندازی شد: @{bot_info.username}")
        
        # ارسال پیام شروع کار به گروه ادمین
        send_startup_message()
        
        bot.infinity_polling(timeout=30, long_polling_timeout=30)
    except Exception as e:
        print(f"❌ خطا در اجرای ربات: {e}")
        print("⚠️ لطفاً موارد زیر را بررسی کنید:")
        print("1. توکن ربات درست باشد")
        print("2. ربات در گروه ادمین عضو و ادمین باشد")
        print("3. اینترنت متصل باشد")

if __name__ == "__main__":
    main()