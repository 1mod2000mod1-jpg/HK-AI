import threading
import requests
import time

# وظيفة إبقاء البوت نشطاً
def keep_alive():
    while True:
        try:
            # أرسل طلباً إلى الرابط الخاص بك على Render
            requests.get("https://mobi-kbdx.onrender.com/", timeout=5)
            print("✅ تم إرسال نبض حياة إلى Render")
        except:
            print("⚠️ فشل إرسال نبض حياة")
        time.sleep(300)  # كل 5 دقائق

# بدء وظيفة إبقاء البوت نشطاً
heartbeat_thread = threading.Thread(target=keep_alive)
heartbeat_thread.daemon = True
heartbeat_thread.start()
from flask import Flask
import threading

# إنشاء تطبيق Flask بسيط
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 البوت يعمل بشكل صحيح! ✅"

# تشغيل Flask في thread منفصل
def run_flask():
    app.run(host='0.0.0.0', port=8000)

# بدء Flask عندما يبدأ البوت
flask_thread = threading.Thread(target=run_flask)
flask_thread.daemon = True
flask_thread.start()

# باقي كود البوت يبقى كما هو...
import telebot
import requests
import sqlite3
import os
from datetime import datetime, timedelta

# توكن البوت - سيتم تعيينه من متغير البيئة
BOT_TOKEN = os.environ.get('BOT_TOKEN', '8389962293:AAHrLNDdcvL9M1jvTuv4n2pUKwa8F2deBYY')
bot = telebot.TeleBot(BOT_TOKEN)

# قائمة المشرفين - أنت المشرف الرئيسي
ADMINS = [6521966233]  # تم إضافة أيديك الخاص كمشرف

# تهيئة قاعدة البيانات
def init_db():
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    
    # جدول الأعضاء المحظورين
    c.execute('''CREATE TABLE IF NOT EXISTS banned_users
                 (user_id INTEGER PRIMARY KEY, 
                  reason TEXT, 
                  banned_at TIMESTAMP)''')
    
    # جدول المشتركين
    c.execute('''CREATE TABLE IF NOT EXISTS subscribed_users
                 (user_id INTEGER PRIMARY KEY,
                  subscribed_at TIMESTAMP,
                  expires_at TIMESTAMP)''')
    
    # جدول المشرفين الإضافيين
    c.execute('''CREATE TABLE IF NOT EXISTS admins 
                 (user_id INTEGER PRIMARY KEY)''')
    
    # إضافة الأيدي الخاص بك كمشرف إذا لم يكن مضافاً
    c.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (6521966233,))
    
    conn.commit()
    conn.close()

# استدعاء التهيئة عند البدء
init_db()

# ========== دوال التحقق من الصلاحيات ========== #
def is_admin(user_id):
    """التحقق إذا كان المستخدم مشرفاً"""
    if user_id in ADMINS:
        return True
    
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT * FROM admins WHERE user_id=?", (user_id,))
    result = c.fetchone()
    conn.close()
    
    return result is not None

# ========== دوال الحظر ========== #
def ban_user(user_id, reason="إساءة استخدام"):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO banned_users VALUES (?, ?, ?)",
              (user_id, reason, datetime.now()))
    conn.commit()
    conn.close()

def unban_user(user_id):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("DELETE FROM banned_users WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def is_banned(user_id):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT * FROM banned_users WHERE user_id=?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result is not None

# ========== دوال الاشتراك ========== #
def add_subscription(user_id, days=30):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    subscribed_at = datetime.now()
    expires_at = subscribed_at + timedelta(days=days)
    c.execute("INSERT OR REPLACE INTO subscribed_users VALUES (?, ?, ?)",
              (user_id, subscribed_at, expires_at))
    conn.commit()
    conn.close()

def is_subscribed(user_id):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT expires_at FROM subscribed_users WHERE user_id=?", (user_id,))
    result = c.fetchone()
    conn.close()
    
    if result:
        expires_at = datetime.strptime(result[0], '%Y-%m-%d %H:%M:%S.%f')
        return datetime.now() < expires_at
    return False

# ========== أوامر البوت الأساسية ========== #
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    
    if is_banned(user_id):
        bot.reply_to(message, "❌ تم حظرك من استخدام البوت.")
        return
        
    welcome_text = """
    🌹 أهلاً وسهلاً بك!
    
    أنا بوت الذكاء الاصطناعي، يمكنك محاورتي في أي موضوع.
    
    📋 الأوامر المتاحة:
    /help - عرض المساعدة
    /mysub - التحقق من حالة الاشتراك
    /subscribe - الاشتراك في البوت
    """
    
    bot.reply_to(message, welcome_text)

@bot.message_handler(commands=['help'])
def show_help(message):
    help_text = """
    🆘 أوامر المساعدة:
    
    /start - بدء استخدام البوت
    /help - عرض هذه المساعدة
    /mysub - التحقق من حالة الاشتراك
    /subscribe - الاشتراك في البوت
    
    للمشرفين فقط:
    /ban - حظر مستخدم (بالرد على رسالته)
    /unban - إلغاء حظر مستخدم
    /addadmin - إضافة مشرف جديد
    """
    
    bot.reply_to(message, help_text)

@bot.message_handler(commands=['subscribe'])
def subscribe_cmd(message):
    user_id = message.from_user.id
    add_subscription(user_id, 30)  # 30 يوم اشتراك
    bot.reply_to(message, "✅ تم تفعيل اشتراكك لمدة 30 يوم!")

@bot.message_handler(commands=['mysub'])
def check_subscription(message):
    user_id = message.from_user.id
    
    if is_subscribed(user_id):
        bot.reply_to(message, "✅ اشتراكك مفعل ومازال صالحاً")
    else:
        bot.reply_to(message, "❌ ليس لديك اشتراك فعال. /subscribe")

# ========== أوامر المشرفين ========== #
@bot.message_handler(commands=['ban'])
def ban_command(message):
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        bot.reply_to(message, f"❌ ليس لديك صلاحية. رقمك: {user_id}")
        return
        
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        reason = message.text.split(' ', 1)[1] if len(message.text.split()) > 1 else "إساءة استخدام"
        
        ban_user(target_id, reason)
        bot.reply_to(message, f"✅ تم حظر المستخدم {target_id}")
    else:
        bot.reply_to(message, "❌ يجب الرد على رسالة المستخدم لحظره.")

@bot.message_handler(commands=['unban'])
def unban_command(message):
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        bot.reply_to(message, "❌ ليس لديك صلاحية لهذا الأمر.")
        return
        
    try:
        target_id = int(message.text.split()[1])
        unban_user(target_id)
        bot.reply_to(message, f"✅ تم إلغاء حظر المستخدم {target_id}")
    except:
        bot.reply_to(message, "❌ استخدم: /unban <user_id>")

@bot.message_handler(commands=['addadmin'])
def add_admin_command(message):
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        bot.reply_to(message, "❌ ليس لديك صلاحية لهذا الأمر.")
        return
        
    try:
        new_admin_id = int(message.text.split()[1])
        
        conn = sqlite3.connect('bot_data.db')
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (new_admin_id,))
        conn.commit()
        conn.close()
        
        bot.reply_to(message, f"✅ تم إضافة المشرف الجديد: {new_admin_id}")
    except:
        bot.reply_to(message, "❌ استخدم: /addadmin <user_id>")

# ========== معالجة الرسائل العادية ========== #
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    
    # التحقق من الحظر
    if is_banned(user_id):
        bot.reply_to(message, "❌ تم حظرك من استخدام البوت.")
        return
        
    # التحقق من الاشتراك
    if not is_subscribed(user_id):
        bot.reply_to(message, f"⚠️ عذراً {user_name},\nيجب الاشتراك لاستخدام البوت.\n\nاستخدم /subscribe للاشتراك")
        return
    
    # إظهار حالة "يكتب..." للمستخدم
    bot.send_chat_action(message.chat.id, 'typing')
    
    # معالجة الرسالة باستخدام الذكاء الاصطناعي
    try:
        txt = message.text
        res = requests.get(f"https://api.se7eneyes.org/v1/chat/completions{txt}", timeout=10)
        res.raise_for_status()
        data = res.json()
        response = data.get("response", "❌ لا يوجد رد من الخادم")
        bot.reply_to(message, response)
    except Exception as e:
        print(f"Error: {e}")
        bot.reply_to(message, "⚠️ عذراً، حدث خطأ في المعالجة")

# ========== تشغيل البوت ========== #
if __name__ == "__main__":
    print("✅ البوت يعمل بنجاح!")
    print("🤖 نظام الحظر والاشتراك مفعل")
    print(f"👑 أنت المشرف الرئيسي: 6521966233")
    bot.infinity_polling()
