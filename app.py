from flask import Flask, request, jsonify
from flask_cors import CORS
import telebot
import requests
import sqlite3
import os
from datetime import datetime, timedelta
import hashlib
import secrets
from functools import wraps
import threading # <--- تم استيراد هذه المكتبة

app = Flask(__name__)
CORS(app)

BOT_TOKEN = os.environ.get('BOT_TOKEN')
bot = telebot.TeleBot(BOT_TOKEN)

ADMINS = [6521966233]
API_SECRET_KEY = os.environ.get('API_SECRET_KEY', secrets.token_urlsafe(32))

def init_db():
    conn = sqlite3.connect('bot_data.db', check_same_thread=False)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS banned_users
                 (user_id INTEGER PRIMARY KEY, reason TEXT, banned_at TIMESTAMP)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS subscribed_users
                 (user_id INTEGER PRIMARY KEY, subscribed_at TIMESTAMP, expires_at TIMESTAMP)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS web_sessions
                 (session_id TEXT PRIMARY KEY, created_at TIMESTAMP, message_count INTEGER DEFAULT 0,
                  last_request TIMESTAMP, access_code TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS web_messages
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, message TEXT,
                  response TEXT, created_at TIMESTAMP)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS access_codes
                 (code TEXT PRIMARY KEY, created_by INTEGER, created_at TIMESTAMP,
                  used_count INTEGER DEFAULT 0, max_uses INTEGER DEFAULT 1, active INTEGER DEFAULT 1)''')
    
    conn.commit()
    conn.close()

init_db()

def verify_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if not api_key or api_key != API_SECRET_KEY:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function

def verify_access_code(code):
    """التحقق من صحة رمز الدخول"""
    conn = sqlite3.connect('bot_data.db', check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT used_count, max_uses, active FROM access_codes WHERE code=?", (code,))
    result = c.fetchone()
    conn.close()
    
    if not result:
        return False
    
    used_count, max_uses, active = result
    return active == 1 and (max_uses == -1 or used_count < max_uses)

def use_access_code(code):
    """استخدام رمز الدخول"""
    conn = sqlite3.connect('bot_data.db', check_same_thread=False)
    c = conn.cursor()
    c.execute("UPDATE access_codes SET used_count = used_count + 1 WHERE code=?", (code,))
    conn.commit()
    conn.close()

def create_access_code(admin_id, max_uses=1):
    """إنشاء رمز دخول جديد"""
    code = secrets.token_urlsafe(16)
    conn = sqlite3.connect('bot_data.db', check_same_thread=False)
    c = conn.cursor()
    c.execute("INSERT INTO access_codes VALUES (?, ?, ?, 0, ?, 1)",
              (code, admin_id, datetime.now(), max_uses))
    conn.commit()
    conn.close()
    return code

def rate_limit_check(session_id, max_requests=20, window_minutes=60):
    conn = sqlite3.connect('bot_data.db', check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT message_count, last_request FROM web_sessions WHERE session_id=?", (session_id,))
    result = c.fetchone()
    
    if result:
        count, last_req = result
        if last_req:
            last_request_time = datetime.strptime(last_req, '%Y-%m-%d %H:%M:%S.%f')
            time_diff = datetime.now() - last_request_time
            
            if time_diff > timedelta(minutes=window_minutes):
                c.execute("UPDATE web_sessions SET message_count=0, last_request=? WHERE session_id=?",
                         (datetime.now(), session_id))
                conn.commit()
                conn.close()
                return True
            
            if count >= max_requests:
                conn.close()
                return False
    
    conn.close()
    return True

def update_rate_limit(session_id):
    conn = sqlite3.connect('bot_data.db', check_same_thread=False)
    c = conn.cursor()
    c.execute("UPDATE web_sessions SET message_count = message_count + 1, last_request = ? WHERE session_id = ?",
              (datetime.now(), session_id))
    conn.commit()
    conn.close()

def ban_user(user_id, reason="إساءة استخدام"):
    conn = sqlite3.connect('bot_data.db', check_same_thread=False)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO banned_users VALUES (?, ?, ?)",
              (user_id, reason, datetime.now()))
    conn.commit()
    conn.close()

def unban_user(user_id):
    conn = sqlite3.connect('bot_data.db', check_same_thread=False)
    c = conn.cursor()
    c.execute("DELETE FROM banned_users WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def is_banned(user_id):
    conn = sqlite3.connect('bot_data.db', check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT * FROM banned_users WHERE user_id=?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result is not None

def add_subscription(user_id, days=30):
    conn = sqlite3.connect('bot_data.db', check_same_thread=False)
    c = conn.cursor()
    subscribed_at = datetime.now()
    expires_at = subscribed_at + timedelta(days=days)
    c.execute("INSERT OR REPLACE INTO subscribed_users VALUES (?, ?, ?)",
              (user_id, subscribed_at, expires_at))
    conn.commit()
    conn.close()

def is_subscribed(user_id):
    conn = sqlite3.connect('bot_data.db', check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT expires_at FROM subscribed_users WHERE user_id=?", (user_id,))
    result = c.fetchone()
    conn.close()
    
    if result:
        expires_at = datetime.strptime(result[0], '%Y-%m-%d %H:%M:%S.%f')
        return datetime.now() < expires_at
    return False

def create_session(access_code):
    session_id = secrets.token_urlsafe(32)
    conn = sqlite3.connect('bot_data.db', check_same_thread=False)
    c = conn.cursor()
    c.execute("INSERT INTO web_sessions VALUES (?, ?, 0, ?, ?)", 
              (session_id, datetime.now(), datetime.now(), access_code))
    conn.commit()
    conn.close()
    return session_id

def save_web_message(session_id, message, response):
    conn = sqlite3.connect('bot_data.db', check_same_thread=False)
    c = conn.cursor()
    c.execute("INSERT INTO web_messages (session_id, message, response, created_at) VALUES (?, ?, ?, ?)",
              (session_id, message, response, datetime.now()))
    conn.commit()
    conn.close()

def get_ai_response(text):
    try:
        res = requests.get(f"https://sii3.top/api/deepseek.php?v3={text}", timeout=10)
        res.raise_for_status()
        data = res.json()
        return data.get("response", "❌ لا يوجد رد من الخادم")
    except Exception as e:
        print(f"AI Error: {e}")
        return "⚠️ عذراً، حدث خطأ في المعالجة"

@app.route('/api/verify-code', methods=['POST'])
@verify_api_key
def verify_code():
    """التحقق من رمز الدخول"""
    data = request.get_json()
    code = data.get('code', '').strip()
    
    if verify_access_code(code):
        session_id = create_session(code)
        use_access_code(code)
        return jsonify({"valid": True, "session_id": session_id})
    
    return jsonify({"valid": False, "error": "رمز غير صالح أو منتهي"}), 403

@app.route('/api/chat', methods=['POST'])
@verify_api_key
def web_chat():
    try:
        data = request.get_json()
        message = data.get('message', '').strip()
        session_id = data.get('session_id')
        
        if not message:
            return jsonify({"error": "الرسالة فارغة"}), 400
        
        if not session_id:
            return jsonify({"error": "يجب تسجيل الدخول أولاً"}), 401
        
        if not rate_limit_check(session_id):
            return jsonify({
                "error": "لقد تجاوزت الحد الأقصى للطلبات. حاول مرة أخرى بعد ساعة.",
                "session_id": session_id
            }), 429
        
        update_rate_limit(session_id)
        ai_response = get_ai_response(message)
        save_web_message(session_id, message, ai_response)
        
        return jsonify({
            "response": ai_response,
            "session_id": session_id,
            "timestamp": datetime.now().isoformat()
        })
    
    except Exception as e:
        print(f"Error in web_chat: {e}")
        return jsonify({"error": "حدث خطأ في الخادم"}), 500

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    
    if is_banned(user_id):
        bot.reply_to(message, "❌ تم حظرك من استخدام البوت.")
        return
        
    welcome_text = """
🌹 أهلاً وسهلاً بك في موبي!

أنا بوت الذكاء الاصطناعي، يمكنك محاورتي في أي موضوع.

📋 الأوامر المتاحة:
/help - عرض المساعدة
/mysub - التحقق من حالة الاشتراك
/subscribe - الاشتراك في البوت
    """
    
    bot.reply_to(message, welcome_text)

@bot.message_handler(commands=['help'])
def show_help(message):
    user_id = message.from_user.id
    
    if user_id in ADMINS:
        help_text = """
🆘 أوامر المساعدة:

للمستخدمين:
/start - بدء استخدام البوت
/help - عرض هذه المساعدة
/mysub - التحقق من حالة الاشتراك
/subscribe - الاشتراك في البوت

للمشرفين:
/gencode - إنشاء رمز دخول جديد
/gencode <عدد> - رمز بعدد استخدامات محدد
/listcodes - عرض جميع الرموز
/ban - حظر مستخدم
/unban - إلغاء حظر مستخدم
/stats - إحصائيات البوت
        """
    else:
        help_text = """
🆘 أوامر المساعدة:

/start - بدء استخدام البوت
/help - عرض هذه المساعدة
/mysub - التحقق من حالة الاشتراك
/subscribe - الاشتراك في البوت
        """
    
    bot.reply_to(message, help_text)

@bot.message_handler(commands=['gencode'])
def generate_code(message):
    user_id = message.from_user.id
    
    if user_id not in ADMINS:
        bot.reply_to(message, "❌ ليس لديك صلاحية لهذا الأمر.")
        return
    
    try:
        parts = message.text.split()
        max_uses = int(parts[1]) if len(parts) > 1 else 1
        
        if max_uses == 0:
            max_uses = -1  # استخدام غير محدود
        
        code = create_access_code(user_id, max_uses)
        uses_text = "غير محدود" if max_uses == -1 else str(max_uses)
        
        bot.reply_to(message, f"""
✅ تم إنشاء رمز دخول جديد!

🔑 الرمز: `{code}`
📊 عدد الاستخدامات: {uses_text}

شارك هذا الرمز مع المستخدمين للدخول إلى الموقع.
        """, parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, f"❌ خطأ: {str(e)}")

@bot.message_handler(commands=['listcodes'])
def list_codes(message):
    user_id = message.from_user.id
    
    if user_id not in ADMINS:
        bot.reply_to(message, "❌ ليس لديك صلاحية لهذا الأمر.")
        return
    
    conn = sqlite3.connect('bot_data.db', check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT code, used_count, max_uses, active FROM access_codes ORDER BY created_at DESC LIMIT 10")
    codes = c.fetchall()
    conn.close()
    
    if not codes:
        bot.reply_to(message, "لا توجد رموز متاحة.")
        return
    
    codes_text = "📋 آخر 10 رموز:\n\n"
    for code, used, max_uses, active in codes:
        status = "🟢 نشط" if active else "🔴 معطل"
        uses_text = "غير محدود" if max_uses == -1 else f"{used}/{max_uses}"
        codes_text += f"`{code[:8]}...` - {uses_text} {status}\n"
    
    bot.reply_to(message, codes_text, parse_mode='Markdown')

@bot.message_handler(commands=['subscribe'])
def subscribe_cmd(message):
    user_id = message.from_user.id
    
    if is_banned(user_id):
        bot.reply_to(message, "❌ تم حظرك من استخدام البوت.")
        return
    
    add_subscription(user_id, 30)
    bot.reply_to(message, "✅ تم تفعيل اشتراكك لمدة 30 يوم!")

@bot.message_handler(commands=['mysub'])
def check_subscription(message):
    user_id = message.from_user.id
    
    if is_banned(user_id):
        bot.reply_to(message, "❌ تم حظرك من استخدام البوت.")
        return
    
    if is_subscribed(user_id):
        bot.reply_to(message, "✅ اشتراكك مفعل ومازال صالحاً")
    else:
        bot.reply_to(message, "❌ ليس لديك اشتراك فعال. استخدم /subscribe للاشتراك")

@bot.message_handler(commands=['stats'])
def stats_command(message):
    user_id = message.from_user.id
    
    if user_id not in ADMINS:
        bot.reply_to(message, "❌ ليس لديك صلاحية لهذا الأمر.")
        return
    
    conn = sqlite3.connect('bot_data.db', check_same_thread=False)
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM subscribed_users WHERE expires_at > ?", (datetime.now(),))
    active_subs = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM web_sessions")
    web_users = c.fetchone()[0]
    
    c.execute("SELECT SUM(message_count) FROM web_sessions")
    total_web_messages = c.fetchone()[0] or 0
    
    c.execute("SELECT COUNT(*) FROM access_codes WHERE active=1")
    active_codes = c.fetchone()[0]
    
    conn.close()
    
    stats_text = f"""
📊 إحصائيات موبي:

👥 المشتركين (تليجرام): {active_subs}
🌐 مستخدمي الموقع: {web_users}
💬 إجمالي رسائل الموقع: {total_web_messages}
🔑 رموز الدخول النشطة: {active_codes}
🚀 حالة البوت: نشط ✅
    """
    
    bot.reply_to(message, stats_text)

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    
    if is_banned(user_id):
        bot.reply_to(message, "❌ تم حظرك من استخدام البوت.")
        return
        
    if not is_subscribed(user_id):
        bot.reply_to(message, f"⚠️ عذراً {user_name},\nيجب الاشتراك لاستخدام البوت.\n\nاستخدم /subscribe للاشتراك")
        return
    
    bot.send_chat_action(message.chat.id, 'typing')
    response = get_ai_response(message.text)
    bot.reply_to(message, response)

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    else:
        return 'Invalid content type', 403

# هنا أضع كود الـ HTML الأصلي الخاص بك
@app.route('/')
def home():
    return """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>موبي - بوت الذكاء الاصطناعي</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}

body {{
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    background: #0a0a0a;
    min-height: 100vh;
    display: flex;
    justify-content: center;
    align-items: center;
    overflow-x: hidden;
    position: relative;
}}

.bg-animation {{
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    overflow: hidden;
    z-index: 0;
    pointer-events: none;
}}

.light {{
    position: absolute;
    border-radius: 50%;
    filter: blur(60px);
    opacity: 0.6;
    animation: float 8s infinite ease-in-out;
    pointer-events: none;
}}

.light:nth-child(1) {{
    width: 300px;
    height: 300px;
    background: linear-gradient(45deg, #ff006e, #8338ec);
    top: -100px;
    left: -100px;
    animation-delay: 0s;
}}

.light:nth-child(2) {{
    width: 350px;
    height: 350px;
    background: linear-gradient(45deg, #3a86ff, #06ffa5);
    bottom: -100px;
    right: -100px;
    animation-delay: 2s;
}}

.light:nth-child(3) {{
    width: 250px;
    height: 250px;
    background: linear-gradient(45deg, #fb5607, #ffbe0b);
    top: 50%;
    right: -100px;
    animation-delay: 4s;
}}

.light:nth-child(4) {{
    width: 280px;
    height: 280px;
    background: linear-gradient(45deg, #06ffa5, #3a86ff);
    bottom: 20%;
    left: 10%;
    animation-delay: 1s;
}}

.light:nth-child(5) {{
    width: 320px;
    height: 320px;
    background: linear-gradient(45deg, #8338ec, #ff006e);
    top: 20%;
    left: 50%;
    animation-delay: 3s;
}}

@keyframes float {{
    0%, 100% {{ transform: translate(0, 0) scale(1); opacity: 0.6; }}
    25% {{ transform: translate(50px, -50px) scale(1.1); opacity: 0.8; }}
    50% {{ transform: translate(-30px, 30px) scale(0.9); opacity: 0.5; }}
    75% {{ transform: translate(40px, 60px) scale(1.05); opacity: 0.7; }}
}}

.stars {{
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    z-index: 1;
    pointer-events: none;
}}

.star {{
    position: absolute;
    width: 2px;
    height: 2px;
    background: white;
    border-radius: 50%;
    animation: twinkle 3s infinite;
}}

@keyframes twinkle {{
    0%, 100% {{ opacity: 0.3; transform: scale(1); }}
    50% {{ opacity: 1; transform: scale(1.5); }}
}}

#spider {{
    position: fixed;
    width: 40px;
    height: 40px;
    z-index: 999;
    pointer-events: none;
    transition: transform 0.1s;
}}

.spider-body {{
    width: 20px;
    height: 20px;
    background: linear-gradient(135deg, #333, #000);
    border-radius: 50%;
    position: absolute;
    top: 10px;
    left: 10px;
    box-shadow: 0 0 10px rgba(138, 43, 226, 0.6);
}}

.spider-leg {{
    position: absolute;
    width: 15px;
    height: 2px;
    background: #222;
    transform-origin: left center;
}}

.spider-leg:nth-child(1) {{ top: 5px; left: 10px; transform: rotate(-45deg); }}
.spider-leg:nth-child(2) {{ top: 15px; left: 10px; transform: rotate(-20deg); }}
.spider-leg:nth-child(3) {{ top: 25px; left: 10px; transform: rotate(20deg); }}
.spider-leg:nth-child(4) {{ top: 35px; left: 10px; transform: rotate(45deg); }}
.spider-leg:nth-child(5) {{ top: 5px; right: 10px; transform: rotate(45deg) scaleX(-1); }}
.spider-leg:nth-child(6) {{ top: 15px; right: 10px; transform: rotate(20deg) scaleX(-1); }}
.spider-leg:nth-child(7) {{ top: 25px; right: 10px; transform: rotate(-20deg) scaleX(-1); }}
.spider-leg:nth-child(8) {{ top: 35px; right: 10px; transform: rotate(-45deg) scaleX(-1); }}

#loginModal {{
    display: flex;
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(0,0,0,0.95);
    z-index: 1000;
    justify-content: center;
    align-items: center;
}}

#loginModal.hidden {{
    display: none;
}}

.login-box {{
    background: rgba(20, 20, 30, 0.95);
    padding: 40px;
    border-radius: 25px;
    box-shadow: 0 20px 60px rgba(138, 43, 226, 0.5);
    border: 2px solid rgba(138, 43, 226, 0.3);
    text-align: center;
    max-width: 400px;
    width: 90%;
    animation: slideUp 0.5s ease;
}}

@keyframes slideUp {{
    from {{ opacity: 0; transform: translateY(50px); }}
    to {{ opacity: 1; transform: translateY(0); }}
}}

.login-box h2 {{
    color: white;
    font-size: 32px;
    margin-bottom: 10px;
    text-shadow: 0 0 20px rgba(138, 43, 226, 0.8);
}}

.login-box p {{
    color: rgba(255,255,255,0.7);
    margin-bottom: 30px;
}}

#accessCodeInput {{
    width: 100%;
    padding: 15px 20px;
    border: 2px solid rgba(138, 43, 226, 0.5);
    border-radius: 15px;
    background: rgba(255,255,255,0.05);
    color: white;
    font-size: 16px;
    text-align: center;
    margin-bottom: 20px;
    outline: none;
    transition: all 0.3s;
}}

#accessCodeInput:focus {{
    border-color: #8a2be2;
    box-shadow: 0 0 20px rgba(138, 43, 226, 0.6);
    background: rgba(255,255,255,0.08);
}}

#loginBtn {{
    width: 100%;
    padding: 15px;
    background: linear-gradient(135deg, #8a2be2, #ff006e);
    color: white;
    border: none;
    border-radius: 15px;
    font-size: 18px;
    font-weight: bold;
    cursor: pointer;
    transition: all 0.3s;
    box-shadow: 0 5px 20px rgba(138, 43, 226, 0.5);
}}

#loginBtn:hover {{
    transform: scale(1.05);
    box-shadow: 0 8px 30px rgba(255, 0, 110, 0.7);
}}

#loginBtn:disabled {{
    opacity: 0.5;
    cursor: not-allowed;
}}

.error-message {{
    color: #ff006e;
    margin-top: 15px;
    font-size: 14px;
}}

.container {{
    width: 90%;
    max-width: 900px;
    height: 85vh;
    background: rgba(20, 20, 30, 0.85);
    backdrop-filter: blur(20px);
    border-radius: 30px;
    box-shadow: 0 25px 80px rgba(138, 43, 226, 0.4),
                0 0 100px rgba(0, 191, 255, 0.3),
                inset 0 0 60px rgba(255, 255, 255, 0.05);
    border: 2px solid rgba(255, 255, 255, 0.1);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    position: relative;
    z-index: 10;
    animation: containerGlow 4s infinite alternate;
}}

@keyframes containerGlow {{
    0% {{ box-shadow: 0 25px 80px rgba(138, 43, 226, 0.4), 0 0 100px rgba(0, 191, 255, 0.3); }}
    50% {{ box-shadow: 0 25px 80px rgba(255, 0, 110, 0.5), 0 0 120px rgba(6, 255, 165, 0.4); }}
    100% {{ box-shadow: 0 25px 80px rgba(251, 86, 7, 0.4), 0 0 100px rgba(138, 43, 226, 0.3); }}
}}

.header {{
    background: linear-gradient(135deg, rgba(138, 43, 226, 0.9), rgba(255, 0, 110, 0.9));
    color: white;
    padding: 25px;
    text-align: center;
    position: relative;
    overflow: hidden;
}}

.header::before {{
    content: '';
    position: absolute;
    top: -50%;
    left: -50%;
    width: 200%;
    height: 200%;
    background: linear-gradient(45deg, transparent, rgba(255,255,255,0.1), transparent);
    animation: shine 3s infinite;
}}

@keyframes shine {{
    0% {{ transform: translateX(-100%) translateY(-100%) rotate(45deg); }}
    100% {{ transform: translateX(100%) translateY(100%) rotate(45deg); }}
}}

.header h1 {{
    font-size: 32px;
    margin-bottom: 8px;
    text-shadow: 0 0 20px rgba(255, 255, 255, 0.8),
                 0 0 40px rgba(138, 43, 226, 0.6);
    animation: pulse 2s infinite;
    position: relative;
    z-index: 1;
}}

@keyframes pulse {{
    0%, 100% {{ transform: scale(1); }}
    50% {{ transform: scale(1.03); }}
}}

.header p {{
    font-size: 15px;
    opacity: 0.95;
    position: relative;
    z-index: 1;
}}

.chat-box {{
    flex: 1;
    padding: 20px;
    overflow-y: auto;
    background: rgba(10, 10, 20, 0.6);
    position: relative;
}}

.chat-box::-webkit-scrollbar {{ width: 8px; }}
.chat-box::-webkit-scrollbar-track {{ background: rgba(255,255,255,0.05); }}
.chat-box::-webkit-scrollbar-thumb {{ 
    background: linear-gradient(180deg, #8a2be2, #ff006e);
    border-radius: 10px;
}}

.message {{
    margin-bottom: 15px;
    display: flex;
    align-items: flex-start;
    animation: slideIn 0.5s ease;
}}

@keyframes slideIn {{
    from {{ opacity: 0; transform: translateY(20px); }}
    to {{ opacity: 1; transform: translateY(0); }}
}}

.message.user {{ justify-content: flex-end; }}

.message-content {{
    max-width: 75%;
    padding: 12px 18px;
    border-radius: 18px;
    word-wrap: break-word;
    position: relative;
    box-shadow: 0 5px 15px rgba(0,0,0,0.3);
    font-size: 15px;
}}

.message.user .message-content {{
    background: linear-gradient(135deg, #8a2be2, #ff006e);
    color: white;
    border-bottom-right-radius: 5px;
    animation: messageGlow 2s infinite alternate;
}}

@keyframes messageGlow {{
    0% {{ box-shadow: 0 5px 15px rgba(138, 43, 226, 0.5); }}
    100% {{ box-shadow: 0 5px 25px rgba(255, 0, 110, 0.7); }}
}}

.message.bot .message-content {{
    background: linear-gradient(135deg, rgba(58, 134, 255, 0.9), rgba(6, 255, 165, 0.9));
    color: white;
    border-bottom-left-radius: 5px;
    animation: botGlow 2s infinite alternate;
}}

@keyframes botGlow {{
    0% {{ box-shadow: 0 5px 15px rgba(58, 134, 255, 0.5); }}
    100% {{ box-shadow: 0 5px 25px rgba(6, 255, 165, 0.7); }}
}}

.input-area {{
    padding: 20px;
    background: rgba(20, 20, 30, 0.9);
    border-top: 2px solid rgba(255, 255, 255, 0.1);
    display: flex;
    gap: 12px;
}}

#messageInput {{
    flex: 1;
    padding: 15px 20px;
    border: 2px solid rgba(138, 43, 226, 0.5);
    border-radius: 25px;
    font-size: 15px;
    outline: none;
    transition: all 0.3s;
    background: rgba(255, 255, 255, 0.05);
    color: white;
    box-shadow: 0 5px 15px rgba(0,0,0,0.3);
}}

#messageInput::placeholder {{ color: rgba(255,255,255,0.5); }}

#messageInput:focus {{
    border-color: #8a2be2;
    box-shadow: 0 0 20px rgba(138, 43, 226, 0.6);
    background: rgba(255, 255, 255, 0.08);
}}

#sendBtn {{
    padding: 15px 30px;
    background: linear-gradient(135deg, #8a2be2, #ff006e);
    color: white;
    border: none;
    border-radius: 25px;
    cursor: pointer;
    font-size: 16px;
    font-weight: bold;
    transition: all 0.3s;
    box-shadow: 0 5px 20px rgba(138, 43, 226, 0.5);
    position: relative;
    overflow: hidden;
}}

#sendBtn:hover {{
    transform: scale(1.05);
    box-shadow: 0 8px 30px rgba(255, 0, 110, 0.7);
}}

#sendBtn:active {{ transform: scale(0.95); }}
#sendBtn:disabled {{ opacity: 0.5; cursor: not-allowed; }}

.typing-indicator {{
    display: none;
    padding: 12px 18px;
    background: linear-gradient(135deg, rgba(58, 134, 255, 0.8), rgba(6, 255, 165, 0.8));
    border-radius: 18px;
    width: fit-content;
    box-shadow: 0 5px 15px rgba(58, 134, 255, 0.5);
}}

.typing-indicator span {{
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: white;
    margin: 0 2px;
    animation: typing 1.4s infinite;
}}

.typing-indicator span:nth-child(2) {{ animation-delay: 0.2s; }}
.typing-indicator span:nth-child(3) {{ animation-delay: 0.4s; }}

@keyframes typing {{
    0%, 60%, 100% {{ transform: translateY(0); opacity: 1; }}
    30% {{ transform: translateY(-12px); opacity: 0.7; }}
}}

@media (max-width: 768px) {{
    .container {{ 
        width: 100%; 
        height: 100vh; 
        border-radius: 0; 
        max-width: 100%;
    }}
    .message-content {{ max-width: 85%; font-size: 14px; }}
    .header h1 {{ font-size: 24px; }}
    .header p {{ font-size: 13px; }}
    .login-box {{ width: 85%; padding: 30px 20px; }}
}}
</style>
</head>
<body>
<div class="bg-animation">
    <div class="light"></div>
    <div class="light"></div>
    <div class="light"></div>
    <div class="light"></div>
    <div class="light"></div>
</div>

<div class="stars" id="stars"></div>

<div id="spider">
    <div class="spider-leg"></div>
    <div class="spider-leg"></div>
    <div class="spider-leg"></div>
    <div class="spider-leg"></div>
    <div class="spider-leg"></div>
    <div class="spider-leg"></div>
    <div class="spider-leg"></div>
    <div class="spider-leg"></div>
    <div class="spider-body"></div>
</div>

<div id="loginModal">
    <div class="login-box">
        <h2>🕷️ موبي</h2>
        <p>أدخل رمز الدخول للمتابعة</p>
        <input type="text" id="accessCodeInput" placeholder="أدخل رمز الدخول..." autocomplete="off">
        <button id="loginBtn">🚀 دخول</button>
        <div id="loginError" class="error-message"></div>
    </div>
</div>

<div class="container" id="chatContainer" style="display: none;">
    <div class="header">
        <h1>✨ موبي - الذكاء الاصطناعي ✨</h1>
        <p>🚀 مساعدك الذكي في كل وقت ومكان</p>
    </div>
    <div class="chat-box" id="chatBox">
        <div class="message bot">
            <div class="message-content">
                مرحباً! 👋 أنا موبي، بوت الذكاء الاصطناعي الخاص بك. كيف يمكنني مساعدتك اليوم؟ ✨
            </div>
        </div>
    </div>
    <div class="input-area">
        <input type="text" id="messageInput" placeholder="اكتب رسالتك هنا..." autocomplete="off"/>
        <button id="sendBtn">✈️ إرسال</button>
    </div>
</div>

<script>
// إنشاء النجوم
const starsContainer = document.getElementById('stars');
for (let i = 0; i < 100; i++) {{
    const star = document.createElement('div');
    star.className = 'star';
    star.style.left = Math.random() * 100 + '%';
    star.style.top = Math.random() * 100 + '%';
    star.style.animationDelay = Math.random() * 3 + 's';
    starsContainer.appendChild(star);
}}

// العنكبوت المتحرك
const spider = document.getElementById('spider');
let spiderX = Math.random() * window.innerWidth;
let spiderY = Math.random() * window.innerHeight;
let targetLight = 0;

function moveSpider() {{
    const lights = document.querySelectorAll('.light');
    if (lights.length === 0) return;
    
    const target = lights[targetLight];
    const rect = target.getBoundingClientRect();
    const targetX = rect.left + rect.width / 2;
    const targetY = rect.top + rect.height / 2;
    
    const dx = targetX - spiderX;
    const dy = targetY - spiderY;
    const distance = Math.sqrt(dx * dx + dy * dy);
    
    if (distance < 100) {{
        targetLight = (targetLight + 1) % lights.length;
    }}
    
    const speed = 2;
    spiderX += (dx / distance) * speed;
    spiderY += (dy / distance) * speed;
    
    spider.style.left = spiderX + 'px';
    spider.style.top = spiderY + 'px';
    
    const angle = Math.atan2(dy, dx) * 180 / Math.PI;
    spider.style.transform = `rotate(${{angle}}deg)`;
    
    requestAnimationFrame(moveSpider);
}}
moveSpider();

// نظام تسجيل الدخول
const API_URL = window.location.origin + '/api/chat';
const VERIFY_URL = window.location.origin + '/api/verify-code';
const API_KEY = '{API_SECRET_KEY}';
let sessionId = localStorage.getItem('sessionId') || null;
const loginModal = document.getElementById('loginModal');
const chatContainer = document.getElementById('chatContainer');
const accessCodeInput = document.getElementById('accessCodeInput');
const loginBtn = document.getElementById('loginBtn');
const loginError = document.getElementById('loginError');
const chatBox = document.getElementById('chatBox');
const messageInput = document.getElementById('messageInput');
const sendBtn = document.getElementById('sendBtn');

// التحقق من الجلسة الموجودة
if (sessionId) {{
    loginModal.classList.add('hidden');
    chatContainer.style.display = 'flex';
}}

// تسجيل الدخول
loginBtn.addEventListener('click', verifyCode);
accessCodeInput.addEventListener('keypress', (e) => {{
    if (e.key === 'Enter') verifyCode();
}});

async function verifyCode() {{
    const code = accessCodeInput.value.trim();
    if (!code) {{
        loginError.textContent = 'يرجى إدخال رمز الدخول';
        return;
    }}
    
    loginBtn.disabled = true;
    loginError.textContent = '';
    
    try {{
        const response = await fetch(VERIFY_URL, {{
            method: 'POST',
            headers: {{ 
                'Content-Type': 'application/json',
                'X-API-Key': API_KEY
            }},
            body: JSON.stringify({{ code: code }})
        }});
        
        const data = await response.json();
        
        if (response.ok && data.valid) {{
            sessionId = data.session_id;
            localStorage.setItem('sessionId', sessionId);
            loginModal.classList.add('hidden');
            chatContainer.style.display = 'flex';
            messageInput.focus();
        }} else {{
            loginError.textContent = data.error || 'رمز غير صالح';
            accessCodeInput.value = '';
        }}
    }} catch (error) {{
        console.error('Error:', error);
        loginError.textContent = 'حدث خطأ في الاتصال';
    }}
    
    loginBtn.disabled = false;
}}

// إرسال الرسائل
messageInput.addEventListener('keypress', (e) => {{
    if (e.key === 'Enter' && !e.shiftKey) {{
        e.preventDefault();
        sendMessage();
    }}
}});
sendBtn.addEventListener('click', sendMessage);

async function sendMessage() {{
    const message = messageInput.value.trim();
    if (!message) return;

    messageInput.disabled = true;
    sendBtn.disabled = true;
    addMessage(message, 'user');
    messageInput.value = '';
    const typingIndicator = showTypingIndicator();

    try {{
        const response = await fetch(API_URL, {{
            method: 'POST',
            headers: {{ 
                'Content-Type': 'application/json',
                'X-API-Key': API_KEY
            }},
            body: JSON.stringify({{ message: message, session_id: sessionId }})
        }});
        
        if (response.status === 429) {{
            const data = await response.json();
            typingIndicator.remove();
            addMessage(data.error, 'bot');
            messageInput.disabled = false;
            sendBtn.disabled = false;
            return;
        }}
        
        if (response.status === 401) {{
            localStorage.removeItem('sessionId');
            location.reload();
            return;
        }}
        
        const data = await response.json();
        typingIndicator.remove();
        addMessage(data.response, 'bot');
    }} catch (error) {{
        console.error('Error:', error);
        typingIndicator.remove();
        addMessage('عذراً، حدث خطأ في الاتصال. حاول مرة أخرى. 😔', 'bot');
    }}
    
    messageInput.disabled = false;
    sendBtn.disabled = false;
    messageInput.focus();
}}

function addMessage(text, type) {{
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${{type}}`;
    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    contentDiv.textContent = text;
    messageDiv.appendChild(contentDiv);
    chatBox.appendChild(messageDiv);
    chatBox.scrollTop = chatBox.scrollHeight;
}}

function showTypingIndicator() {{
    const indicator = document.createElement('div');
    indicator.className = 'message bot';
    indicator.innerHTML = `<div class="typing-indicator" style="display: block;"><span></span><span></span><span></span></div>`;
    chatBox.appendChild(indicator);
    chatBox.scrollTop = chatBox.scrollHeight;
    return indicator;
}}
</script>
</body>
</html>"""

@app.route('/health')
def health_check():
    return jsonify({"status": "healthy", "protected": True})

# =================================================================
# === الإصلاح الوحيد المطلوب هو هنا في الأسفل ===
# =================================================================

def run_bot():
    """دالة لتشغيل البوت في الخلفية"""
    print("🤖 بدء تشغيل بوت تيليجرام...")
    bot.polling(none_stop=True)

if __name__ == '__main__':
    print("🚀 بدء تشغيل موبي...")
    
    # تشغيل البوت في خيط منفصل
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    # تشغيل خادم الويب
    port = int(os.environ.get('PORT', 5000))
    print(f"🌐 الخادم يعمل على المنفذ: {port}")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
