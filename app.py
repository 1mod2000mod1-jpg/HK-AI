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

# تهيئة Flask
app = Flask(__name__)
CORS(app)

# توكن البوت
BOT_TOKEN = os.environ.get('BOT_TOKEN')
bot = telebot.TeleBot(BOT_TOKEN)

# قائمة المشرفين
ADMINS = [6521966233]

# مفتاح API السري (يُنشأ تلقائياً أو تضعه يدوياً)
API_SECRET_KEY = os.environ.get('API_SECRET_KEY', secrets.token_urlsafe(32))

# تهيئة قاعدة البيانات
def init_db():
    conn = sqlite3.connect('bot_data.db', check_same_thread=False)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS banned_users
                 (user_id INTEGER PRIMARY KEY, 
                  reason TEXT, 
                  banned_at TIMESTAMP)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS subscribed_users
                 (user_id INTEGER PRIMARY KEY,
                  subscribed_at TIMESTAMP,
                  expires_at TIMESTAMP)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS web_sessions
                 (session_id TEXT PRIMARY KEY,
                  created_at TIMESTAMP,
                  message_count INTEGER DEFAULT 0,
                  last_request TIMESTAMP)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS web_messages
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  session_id TEXT,
                  message TEXT,
                  response TEXT,
                  created_at TIMESTAMP)''')
    
    # جدول لتتبع Rate Limiting
    c.execute('''CREATE TABLE IF NOT EXISTS rate_limits
                 (ip_address TEXT PRIMARY KEY,
                  request_count INTEGER DEFAULT 0,
                  window_start TIMESTAMP)''')
    
    conn.commit()
    conn.close()

init_db()

# ========== دوال الحماية ========== #
def verify_api_key(f):
    """التحقق من API Key"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if not api_key or api_key != API_SECRET_KEY:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function

def rate_limit_check(session_id, max_requests=20, window_minutes=60):
    """فحص Rate Limiting - 20 طلب في الساعة لكل جلسة"""
    conn = sqlite3.connect('bot_data.db', check_same_thread=False)
    c = conn.cursor()
    
    # التحقق من الجلسة
    c.execute("SELECT message_count, last_request FROM web_sessions WHERE session_id=?", (session_id,))
    result = c.fetchone()
    
    if result:
        count, last_req = result
        if last_req:
            last_request_time = datetime.strptime(last_req, '%Y-%m-%d %H:%M:%S.%f')
            time_diff = datetime.now() - last_request_time
            
            # إعادة تعيين العداد بعد ساعة
            if time_diff > timedelta(minutes=window_minutes):
                c.execute("UPDATE web_sessions SET message_count=0, last_request=? WHERE session_id=?",
                         (datetime.now(), session_id))
                conn.commit()
                conn.close()
                return True
            
            # التحقق من الحد الأقصى
            if count >= max_requests:
                conn.close()
                return False
    
    conn.close()
    return True

def update_rate_limit(session_id):
    """تحديث عداد الطلبات"""
    conn = sqlite3.connect('bot_data.db', check_same_thread=False)
    c = conn.cursor()
    c.execute("UPDATE web_sessions SET message_count = message_count + 1, last_request = ? WHERE session_id = ?",
              (datetime.now(), session_id))
    conn.commit()
    conn.close()

# ========== دوال الحظر ========== #
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

# ========== دوال الاشتراك ========== #
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

# ========== دوال جلسات الموقع ========== #
def create_session():
    session_id = secrets.token_urlsafe(32)
    conn = sqlite3.connect('bot_data.db', check_same_thread=False)
    c = conn.cursor()
    c.execute("INSERT INTO web_sessions VALUES (?, ?, 0, ?)", 
              (session_id, datetime.now(), datetime.now()))
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

# ========== دالة الذكاء الاصطناعي الموحدة ========== #
def get_ai_response(text):
    """دالة موحدة للحصول على رد من الذكاء الاصطناعي - محمية"""
    try:
        res = requests.get(f"https://sii3.top/api/DarkCode.php?text=", timeout=10)
        res.raise_for_status()
        data = res.json()
        return data.get("response", "❌ لا يوجد رد من الخادم")
    except Exception as e:
        print(f"AI Error: {e}")
        return "⚠️ عذراً، حدث خطأ في المعالجة"

# ========== API للموقع - محمي ========== #
@app.route('/api/chat', methods=['POST'])
@verify_api_key
def web_chat():
    """API محمي بـ API Key + Rate Limiting"""
    try:
        data = request.get_json()
        message = data.get('message', '').strip()
        session_id = data.get('session_id')
        
        if not message:
            return jsonify({"error": "الرسالة فارغة"}), 400
        
        # إنشاء جلسة جديدة إذا لم تكن موجودة
        if not session_id:
            session_id = create_session()
        
        # فحص Rate Limiting
        if not rate_limit_check(session_id):
            return jsonify({
                "error": "لقد تجاوزت الحد الأقصى للطلبات. حاول مرة أخرى بعد ساعة.",
                "session_id": session_id
            }), 429
        
        # تحديث عداد الطلبات
        update_rate_limit(session_id)
        
        # الحصول على الرد من الذكاء الاصطناعي
        ai_response = get_ai_response(message)
        
        # حفظ المحادثة
        save_web_message(session_id, message, ai_response)
        
        return jsonify({
            "response": ai_response,
            "session_id": session_id,
            "timestamp": datetime.now().isoformat()
        })
    
    except Exception as e:
        print(f"Error in web_chat: {e}")
        return jsonify({"error": "حدث خطأ في الخادم"}), 500

@app.route('/api/history/<session_id>', methods=['GET'])
@verify_api_key
def get_history(session_id):
    """الحصول على سجل المحادثات - محمي"""
    try:
        conn = sqlite3.connect('bot_data.db', check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT message, response, created_at FROM web_messages WHERE session_id = ? ORDER BY created_at", 
                  (session_id,))
        messages = c.fetchall()
        conn.close()
        
        history = [
            {
                "message": msg[0],
                "response": msg[1],
                "timestamp": msg[2]
            }
            for msg in messages
        ]
        
        return jsonify({"history": history})
    
    except Exception as e:
        print(f"Error in get_history: {e}")
        return jsonify({"error": "حدث خطأ"}), 500

# ========== أوامر البوت ========== #
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    
    if is_banned(user_id):
        bot.reply_to(message, "❌ تم حظرك من استخدام البوت.")
        return
        
    welcome_text = """
🌹 أهلاً وسهلاً بك في موبي!

أنا بوت الذكاء الشرير، يمكنك محاورتي في أي موضوع.

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
/ban - حظر مستخدم
/unban - إلغاء حظر مستخدم
/stats - إحصائيات البوت
    """
    
    bot.reply_to(message, help_text)

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

@bot.message_handler(commands=['ban'])
def ban_command(message):
    user_id = message.from_user.id
    
    if user_id not in ADMINS:
        bot.reply_to(message, "❌ ليس لديك صلاحية لهذا الأمر.")
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
    
    if user_id not in ADMINS:
        bot.reply_to(message, "❌ ليس لديك صلاحية لهذا الأمر.")
        return
        
    try:
        target_id = int(message.text.split()[1])
        unban_user(target_id)
        bot.reply_to(message, f"✅ تم إلغاء حظر المستخدم {target_id}")
    except:
        bot.reply_to(message, "❌ استخدم: /unban <user_id>")

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
    
    c.execute("SELECT COUNT(*) FROM banned_users")
    banned_users = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM web_sessions")
    web_users = c.fetchone()[0]
    
    c.execute("SELECT SUM(message_count) FROM web_sessions")
    total_web_messages = c.fetchone()[0] or 0
    
    conn.close()
    
    stats_text = f"""
📊 إحصائيات البوت:

👥 المشتركين النشطين (تليجرام): {active_subs}
🌐 مستخدمي الموقع: {web_users}
💬 إجمالي رسائل الموقع: {total_web_messages}
🚫 المستخدمين المحظورين: {banned_users}
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

# ========== Routes ========== #
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    else:
        return 'Invalid content type', 403

@app.route('/')
def home():
    return f"""
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>موبي - بوت الذكاء الشرير</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #0a0a0a;
            height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            overflow: hidden;
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
        }}

        .light {{
            position: absolute;
            border-radius: 50%;
            filter: blur(60px);
            opacity: 0.6;
            animation: float 8s infinite ease-in-out;
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

        .container {{
            width: 90%;
            max-width: 850px;
            height: 90vh;
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
            padding: 30px;
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
            font-size: 38px;
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
            font-size: 16px;
            opacity: 0.95;
            position: relative;
            z-index: 1;
        }}

        .chat-box {{
            flex: 1;
            padding: 25px;
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
            margin-bottom: 20px;
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
            max-width: 70%;
            padding: 15px 20px;
            border-radius: 20px;
            word-wrap: break-word;
            position: relative;
            box-shadow: 0 5px 15px rgba(0,0,0,0.3);
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
            padding: 25px;
            background: rgba(20, 20, 30, 0.9);
            border-top: 2px solid rgba(255, 255, 255, 0.1);
            display: flex;
            gap: 15px;
        }}

        #messageInput {{
            flex: 1;
            padding: 18px 25px;
            border: 2px solid rgba(138, 43, 226, 0.5);
            border-radius: 30px;
            font-size: 16px;
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
            padding: 18px 35px;
            background: linear-gradient(135deg, #8a2be2, #ff006e);
            color: white;
            border: none;
            border-radius: 30px;
            cursor: pointer;
            font-size: 17px;
            font-weight: bold;
            transition: all 0.3s;
            box-shadow: 0 5px 20px rgba(138, 43, 226, 0.5);
            position: relative;
            overflow: hidden;
        }}

        #sendBtn::before {{
            content: '';
            position: absolute;
            top: 50%;
            left: 50%;
            width: 0;
            height: 0;
            border-radius: 50%;
            background: rgba(255,255,255,0.3);
            transform: translate(-50%, -50%);
            transition: width 0.6s, height 0.6s;
        }}

        #sendBtn:hover::before {{
            width: 300px;
            height: 300px;
        }}

        #sendBtn:hover {{
            transform: scale(1.08);
            box-shadow: 0 8px 30px rgba(255, 0, 110, 0.7);
        }}

        #sendBtn:active {{ transform: scale(0.95); }}
        #sendBtn:disabled {{ opacity: 0.5; cursor: not-allowed; }}

        .typing-indicator {{
            display: none;
            padding: 15px 20px;
            background: linear-gradient(135deg, rgba(58, 134, 255, 0.8), rgba(6, 255, 165, 0.8));
            border-radius: 20px;
            width: fit-content;
            box-shadow: 0 5px 15px rgba(58, 134, 255, 0.5);
        }}

        .typing-indicator span {{
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: white;
            margin: 0 3px;
            animation: typing 1.4s infinite;
        }}

        .typing-indicator span:nth-child(2) {{ animation-delay: 0.2s; }}
        .typing-indicator span:nth-child(3) {{ animation-delay: 0.4s; }}

        @keyframes typing {{
            0%, 60%, 100% {{ transform: translateY(0); opacity: 1; }}
            30% {{ transform: translateY(-15px); opacity: 0.7; }}
        }}

        @media (max-width: 600px) {{
            .container {{ width: 100%; height: 100vh; border-radius: 0; }}
            .message-content {{ max-width: 85%; }}
            .header h1 {{ font-size: 28px; }}
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

    <div class="container">
        <div class="header">
            <h1>😈 موبي - الذكاء الشرير 😈</h1>
            <p>😈 مساعدك الذكي في كل وقت ومكان</p>
        </div>
        <div class="chat-box" id="chatBox">
            <div class="message bot">
                <div class="message-content">
                    مرحباً! 👋 أنا موبي، بوت الذكاء الشرير الخاص بك. كيف يمكنني القضاء عليك اليوم😈؟ ✨
                </div>
            </div>
        </div>
        <div class="input-area">
            <input type="text" id="messageInput" placeholder="اكتب رسالتك هنا..." autocomplete="off"/>
            <button id="sendBtn">  😈 إرسال</button>
        </div>
    </div>

    <script>
        const starsContainer = document.getElementById('stars');
        for (let i = 0; i < 100; i++) {{
            const star = document.createElement('div');
            star.className = 'star';
            star.style.left = Math.random() * 100 + '%';
            star.style.top = Math.random() * 100 + '%';
            star.style.animationDelay = Math.random() * 3 + 's';
            starsContainer.appendChild(star);
        }}

        const API_URL = window.location.origin + '/api/chat';
        const API_KEY = '{API_SECRET_KEY}';
        let sessionId = localStorage.getItem('sessionId') || null;
        const chatBox = document.getElementById('chatBox');
        const messageInput = document.getElementById('messageInput');
        const sendBtn = document.getElementById('sendBtn');

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
                
                const data = await response.json();
                if (data.session_id) {{
                    sessionId = data.session_id;
                    localStorage.setItem('sessionId', sessionId);
                }}
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
        messageInput.focus();
    </script>
</body>
</html>
    """

@app.route('/health')
def health_check():
    return jsonify({{"status": "healthy", "protected": True}})

if __name__ == '__main__':
    print("🚀 بدء تشغيل بوت التلغرام المحمي...")
    print(f"🔒 API Secret Key: {{API_SECRET_KEY[:10]}}...")
    
    try:
        bot.remove_webhook()
        print("✅ تم حذف الويب هوك القديم")
    except Exception as e:
        print(f"⚠️ خطأ في حذف الويب هوك: {{e}}")
    
    try:
        webhook_url = f"https://{{os.environ.get('RENDER_EXTERNAL_HOSTNAME')}}/webhook"
        bot.set_webhook(url=webhook_url, drop_pending_updates=True)
        print(f"✅ تم تعيين الويب هوك: {{webhook_url}}")
    except Exception as e:
        print(f"⚠️ خطأ في تعيين الويب هوك: {{e}}")
    
    port = int(os.environ.get('PORT', 5000))
    print(f"🌐 الخادم يعمل على المنفذ: {{port}}")
    app.run(host='0.0.0.0', port=port, debug=False)
