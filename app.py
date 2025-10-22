from flask import Flask, request, jsonify
from flask_cors import CORS
import telebot
import requests
import sqlite3
import os
import logging
from datetime import datetime, timedelta
import secrets
from functools import wraps

# إعداد نظام التسجيل لتتبع الأخطاء
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# التحقق من وجود توكن البوت
BOT_TOKEN = os.environ.get('BOT_TOKEN')
if not BOT_TOKEN:
    logger.error("BOT_TOKEN not found in environment variables!")
    exit(1)

bot = telebot.TeleBot(BOT_TOKEN)

ADMINS = [6521966233]  # <--- ضع هنا معرفك كأدمن
API_SECRET_KEY = os.environ.get('API_SECRET_KEY', secrets.token_urlsafe(32))

# --- دوال قاعدة البيانات (لم تتغير، ولكن تم تحسينها بالتعامل مع الأخطاء) ---
def init_db():
    try:
        conn = sqlite3.connect('bot_data.db', check_same_thread=False)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS banned_users (user_id INTEGER PRIMARY KEY, reason TEXT, banned_at TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS subscribed_users (user_id INTEGER PRIMARY KEY, subscribed_at TIMESTAMP, expires_at TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS web_sessions (session_id TEXT PRIMARY KEY, created_at TIMESTAMP, message_count INTEGER DEFAULT 0, last_request TIMESTAMP, access_code TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS web_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, message TEXT, response TEXT, created_at TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS access_codes (code TEXT PRIMARY KEY, created_by INTEGER, created_at TIMESTAMP, used_count INTEGER DEFAULT 0, max_uses INTEGER DEFAULT 1, active INTEGER DEFAULT 1)''')
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Error initializing database: {e}")

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
    try:
        conn = sqlite3.connect('bot_data.db', check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT used_count, max_uses, active FROM access_codes WHERE code=?", (code,))
        result = c.fetchone()
        conn.close()
        if not result: return False
        used_count, max_uses, active = result
        return active == 1 and (max_uses == -1 or used_count < max_uses)
    except Exception as e: logger.error(f"Error verifying access code: {e}"); return False

def use_access_code(code):
    try:
        conn = sqlite3.connect('bot_data.db', check_same_thread=False)
        c = conn.cursor()
        c.execute("UPDATE access_codes SET used_count = used_count + 1 WHERE code=?", (code,))
        conn.commit()
        conn.close()
    except Exception as e: logger.error(f"Error using access code: {e}")

def create_access_code(admin_id, max_uses=1):
    try:
        code = secrets.token_urlsafe(16)
        conn = sqlite3.connect('bot_data.db', check_same_thread=False)
        c = conn.cursor()
        c.execute("INSERT INTO access_codes VALUES (?, ?, ?, 0, ?, 1)", (code, admin_id, datetime.now(), max_uses))
        conn.commit()
        conn.close()
        return code
    except Exception as e: logger.error(f"Error creating access code: {e}"); return None

def is_banned(user_id):
    try:
        conn = sqlite3.connect('bot_data.db', check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT * FROM banned_users WHERE user_id=?", (user_id,))
        result = c.fetchone()
        conn.close()
        return result is not None
    except Exception as e: logger.error(f"Error checking if user is banned: {e}"); return False

# --- مسارات الـ API (لم تتغير) ---
@app.route('/api/verify-code', methods=['POST'])
@verify_api_key
def verify_code():
    try:
        data = request.get_json()
        code = data.get('code', '').strip()
        if verify_access_code(code):
            session_id = secrets.token_urlsafe(32)
            # حفظ الجلسة في قاعدة البيانات
            conn = sqlite3.connect('bot_data.db', check_same_thread=False)
            c = conn.cursor()
            c.execute("INSERT INTO web_sessions VALUES (?, ?, 0, ?, ?)", (session_id, datetime.now(), datetime.now(), code))
            conn.commit()
            conn.close()
            use_access_code(code)
            return jsonify({"valid": True, "session_id": session_id})
        return jsonify({"valid": False, "error": "رمز غير صالح أو منتهي"}), 403
    except Exception as e: logger.error(f"Error in verify_code: {e}"); return jsonify({"valid": False, "error": "حدث خطأ في الخادم"}), 500

@app.route('/api/chat', methods=['POST'])
@verify_api_key
def web_chat():
    try:
        data = request.get_json()
        message = data.get('message', '').strip()
        session_id = data.get('session_id')
        if not message: return jsonify({"error": "الرسالة فارغة"}), 400
        if not session_id: return jsonify({"error": "يجب تسجيل الدخول أولاً"}), 401
        
        # هنا يمكنك إضافة المزيد من المنطق مثل التحقق من الجلسة وحدود الطلب
        ai_response = "هذا رد تجريبي من البوت." # استبدل هذا باستدعاء الـ API الحقيقي
        return jsonify({"response": ai_response, "session_id": session_id, "timestamp": datetime.now().isoformat()})
    except Exception as e: logger.error(f"Error in web_chat: {e}"); return jsonify({"error": "حدث خطأ في الخادم"}), 500

# --- أوامر بوت تيليجرام ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    if is_banned(user_id): bot.reply_to(message, "❌ تم حظرك."); return
    bot.reply_to(message, "🕷️ أهلاً بك في موبي! استخدم /gencode لإنشاء رموز دخول للموقع.")

@bot.message_handler(commands=['gencode'])
def generate_code(message):
    user_id = message.from_user.id
    if user_id not in ADMINS:
        bot.reply_to(message, "❌ هذا الأمر للأدمن فقط.")
        return
    try:
        parts = message.text.split()
        max_uses = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
        if max_uses == 0: max_uses = -1 # غير محدود
        
        code = create_access_code(user_id, max_uses)
        if code:
            uses_text = "غير محدود" if max_uses == -1 else str(max_uses)
            bot.reply_to(message, f"✅ تم إنشاء رمز جديد:\n\n`{code}`\n\nعدد الاستخدامات: {uses_text}", parse_mode='Markdown')
        else:
            bot.reply_to(message, "❌ فشل إنشاء الرمز.")
    except Exception as e:
        logger.error(f"Error in gencode: {e}")
        bot.reply_to(message, "❌ حدث خطأ.")

# --- مسار الويب الرئيسي مع الواجهة المخصصة ---
@app.route('/')
def home():
    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>موبي - الذكاء الاصطناعي</title>
<style>
    /* --- إعدادات عامة --- */
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        background: #0a0a0a;
        color: white;
        height: 100vh;
        overflow: hidden;
        position: relative;
    }}

    /* --- الخلفية المتحركة --- */
    .bg-animation {{
        position: fixed;
        width: 100%;
        height: 100%;
        top: 0;
        left: 0;
        z-index: 1;
    }}
    .light {{
        position: absolute;
        border-radius: 50%;
        filter: blur(80px);
        opacity: 0.7;
        animation: float 15s infinite ease-in-out;
    }}
    .light:nth-child(1) {{ width: 400px; height: 400px; background: linear-gradient(45deg, #ff006e, #8338ec); top: -150px; left: -150px; animation-delay: 0s; }}
    .light:nth-child(2) {{ width: 450px; height: 450px; background: linear-gradient(45deg, #3a86ff, #06ffa5); bottom: -150px; right: -150px; animation-delay: 3s; }}
    .light:nth-child(3) {{ width: 350px; height: 350px; background: linear-gradient(45deg, #fb5607, #ffbe0b); top: 50%; right: -150px; animation-delay: 6s; }}
    .light:nth-child(4) {{ width: 380px; height: 380px; background: linear-gradient(45deg, #06ffa5, #3a86ff); bottom: 20%; left: 10%; animation-delay: 2s; }}
    .light:nth-child(5) {{ width: 420px; height: 420px; background: linear-gradient(45deg, #8338ec, #ff006e); top: 20%; left: 50%; animation-delay: 5s; }}
    @keyframes float {{
        0%, 100% {{ transform: translate(0, 0) scale(1); }}
        33% {{ transform: translate(80px, -80px) scale(1.1); }}
        66% {{ transform: translate(-60px, 60px) scale(0.9); }}
    }}

    /* --- العنكبوت المتحرك --- */
    #spider {{
        position: fixed;
        width: 50px;
        height: 50px;
        z-index: 100; /* تحت الواجهة، فوق الخلفية */
        pointer-events: none;
        transition: transform 0.1s linear;
    }}
    .spider-body {{
        width: 25px;
        height: 25px;
        background: radial-gradient(circle, #444, #000);
        border-radius: 50%;
        position: absolute;
        top: 12.5px;
        left: 12.5px;
        box-shadow: 0 0 15px rgba(138, 43, 226, 0.8);
    }}
    .spider-leg {{
        position: absolute;
        width: 20px;
        height: 2px;
        background: #222;
        transform-origin: left center;
    }}
    .spider-leg:nth-child(1) {{ top: 5px; left: 12px; transform: rotate(-45deg); }}
    .spider-leg:nth-child(2) {{ top: 15px; left: 12px; transform: rotate(-20deg); }}
    .spider-leg:nth-child(3) {{ top: 25px; left: 12px; transform: rotate(20deg); }}
    .spider-leg:nth-child(4) {{ top: 35px; left: 12px; transform: rotate(45deg); }}
    .spider-leg:nth-child(5) {{ top: 5px; right: 12px; transform: rotate(45deg) scaleX(-1); }}
    .spider-leg:nth-child(6) {{ top: 15px; right: 12px; transform: rotate(20deg) scaleX(-1); }}
    .spider-leg:nth-child(7) {{ top: 25px; right: 12px; transform: rotate(-20deg) scaleX(-1); }}
    .spider-leg:nth-child(8) {{ top: 35px; right: 12px; transform: rotate(-45deg) scaleX(-1); }}

    /* --- واجهة تسجيل الدخول --- */
    #loginModal {{
        display: flex;
        position: fixed;
        top: 0; left: 0;
        width: 100%; height: 100%;
        background: rgba(0,0,0,0.8);
        z-index: 1000;
        justify-content: center;
        align-items: center;
        backdrop-filter: blur(5px);
    }}
    .login-box {{
        background: rgba(20, 20, 30, 0.95);
        padding: 50px;
        border-radius: 20px;
        box-shadow: 0 20px 60px rgba(138, 43, 226, 0.5);
        border: 2px solid rgba(138, 43, 226, 0.3);
        text-align: center;
        width: 90%;
        max-width: 450px;
        z-index: 1001;
    }}
    .login-box h2 {{ font-size: 36px; margin-bottom: 10px; background: linear-gradient(45deg, #8a2be2, #ff006e); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
    .login-box p {{ color: rgba(255,255,255,0.7); margin-bottom: 30px; }}
    #accessCodeInput {{
        width: 100%;
        padding: 15px;
        border: 2px solid rgba(138, 43, 226, 0.5);
        border-radius: 15px;
        background: rgba(255,255,255,0.05);
        color: white;
        font-size: 16px;
        text-align: center;
        margin-bottom: 20px;
        outline: none;
    }}
    #accessCodeInput:focus {{ border-color: #8a2be2; box-shadow: 0 0 20px rgba(138, 43, 226, 0.6); }}
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
    }}
    #loginBtn:hover {{ transform: scale(1.05); box-shadow: 0 8px 30px rgba(255, 0, 110, 0.7); }}
    .error-message {{ color: #ff006e; margin-top: 15px; font-size: 14px; }}

    /* --- واجهة الدردشة --- */
    .container {{
        display: none; /* مخفي افتراضياً */
        position: fixed;
        top: 0; left: 0;
        width: 100%; height: 100%;
        background: rgba(20, 20, 30, 0.85);
        backdrop-filter: blur(20px);
        z-index: 200;
        flex-direction: column;
    }}
    .header {{
        background: linear-gradient(135deg, rgba(138, 43, 226, 0.9), rgba(255, 0, 110, 0.9));
        padding: 20px;
        text-align: center;
        z-index: 201;
    }}
    .header h1 {{ font-size: 28px; }}
    .chat-box {{
        flex: 1;
        padding: 20px;
        overflow-y: auto;
        z-index: 201;
    }}
    .input-area {{
        padding: 20px;
        display: flex;
        gap: 10px;
        background: rgba(20, 20, 30, 0.9);
        z-index: 201;
    }}
    #messageInput {{
        flex: 1;
        padding: 12px;
        border: 2px solid rgba(138, 43, 226, 0.5);
        border-radius: 25px;
        background: rgba(255,255,255,0.05);
        color: white;
        outline: none;
    }}
    #sendBtn {{
        padding: 12px 25px;
        background: linear-gradient(135deg, #8a2be2, #ff006e);
        color: white;
        border: none;
        border-radius: 25px;
        cursor: pointer;
        font-weight: bold;
    }}

    /* --- جعل التصميم متجاوب (يبدو نفس الشكل على الموبايل) --- */
    @media (max-width: 768px) {{
        .container, .login-box {{
            /* لا نغير العرض والارتفاع ليبقى كما هو على الكمبيوتر */
            border-radius: 0; /* إزالة الاستدارة لتملأ الشاشة */
        }}
        .header h1 {{ font-size: 24px; }}
        .login-box {{ padding: 40px 25px; }}
    }}
</style>
</head>
<body>

    <!-- الخلفية المتحركة -->
    <div class="bg-animation">
        <div class="light"></div>
        <div class="light"></div>
        <div class="light"></div>
        <div class="light"></div>
        <div class="light"></div>
    </div>

    <!-- العنكبوت المتحرك -->
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

    <!-- واجهة تسجيل الدخول -->
    <div id="loginModal">
        <div class="login-box">
            <h2>🕷️ موبي</h2>
            <p>أدخل رمز الدخول للمتابعة</p>
            <input type="text" id="accessCodeInput" placeholder="أدخل رمز الدخول..." autocomplete="off">
            <button id="loginBtn">🚀 دخول</button>
            <div id="loginError" class="error-message"></div>
        </div>
    </div>

    <!-- واجهة الدردشة -->
    <div class="container" id="chatContainer">
        <div class="header">
            <h1>✨ موبي - الذكاء الاصطناعي ✨</h1>
        </div>
        <div class="chat-box" id="chatBox">
            <div class="message bot">
                <div class="message-content">مرحباً! 👋 أنا موبي، كيف يمكنني مساعدتك؟</div>
            </div>
        </div>
        <div class="input-area">
            <input type="text" id="messageInput" placeholder="اكتب رسالتك هنا..." autocomplete="off"/>
            <button id="sendBtn">✈️ إرسال</button>
        </div>
    </div>

<script>
    // --- منطق العنكبوت المتحرك ---
    const spider = document.getElementById('spider');
    let spiderX = window.innerWidth / 2, spiderY = window.innerHeight / 2;
    let targetLightIndex = 0;

    function moveSpider() {{
        const lights = document.querySelectorAll('.light');
        if (lights.length === 0) return;
        
        const targetLight = lights[targetLightIndex];
        const rect = targetLight.getBoundingClientRect();
        const targetX = rect.left + rect.width / 2;
        const targetY = rect.top + rect.height / 2;
        
        const dx = targetX - spiderX;
        const dy = targetY - spiderY;
        const distance = Math.sqrt(dx * dx + dy * dy);
        
        if (distance < 100) {{
            targetLightIndex = (targetLightIndex + 1) % lights.length;
        }}
        
        const speed = 2;
        spiderX += (dx / distance) * speed;
        spiderY += (dy / distance) * speed;
        
        spider.style.left = spiderX + 'px';
        spider.style.top = spiderY + 'px';
        
        const angle = Math.atan2(dy, dx) * 180 / Math.PI + 90;
        spider.style.transform = `rotate(${{angle}}deg)`;
        
        requestAnimationFrame(moveSpider);
    }}
    moveSpider();

    // --- منطق تسجيل الدخول والدردشة ---
    const API_URL = '{{ request.url_root }}api/chat';
    const VERIFY_URL = '{{ request.url_root }}api/verify-code';
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

    if (sessionId) {{
        loginModal.style.display = 'none';
        chatContainer.style.display = 'flex';
    }}

    loginBtn.addEventListener('click', verifyCode);
    accessCodeInput.addEventListener('keypress', (e) => {{ if (e.key === 'Enter') verifyCode(); }});

    async function verifyCode() {{
        const code = accessCodeInput.value.trim();
        if (!code) {{ loginError.textContent = 'يرجى إدخال رمز الدخول'; return; }}
        
        loginBtn.disabled = true;
        loginError.textContent = '';
        
        try {{
            const response = await fetch(VERIFY_URL, {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json', 'X-API-Key': API_KEY }},
                body: JSON.stringify({{ code: code }})
            }});
            
            const data = await response.json();
            
            if (response.ok && data.valid) {{
                sessionId = data.session_id;
                localStorage.setItem('sessionId', sessionId);
                loginModal.style.display = 'none';
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

    sendBtn.addEventListener('click', sendMessage);
    messageInput.addEventListener('keypress', (e) => {{ if (e.key === 'Enter') sendMessage(); }});

    async function sendMessage() {{
        const message = messageInput.value.trim();
        if (!message) return;

        addMessage(message, 'user');
        messageInput.value = '';
        
        try {{
            const response = await fetch(API_URL, {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json', 'X-API-Key': API_KEY }},
                body: JSON.stringify({{ message: message, session_id: sessionId }})
            }});
            
            const data = await response.json();
            addMessage(data.response, 'bot');
        }} catch (error) {{
            console.error('Error:', error);
            addMessage('عذراً، حدث خطأ في الاتصال.', 'bot');
        }}
    }}
    
    function addMessage(text, type) {{
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${{type}}`;
        messageDiv.style.cssText = 'margin-bottom: 15px; display: flex; justify-content: ' + (type === 'user' ? 'flex-end' : 'flex-start') + ';';
        
        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        contentDiv.style.cssText = 'max-width: 70%; padding: 12px 18px; border-radius: 18px; word-wrap: break-word;';
        if (type === 'user') {{
            contentDiv.style.background = 'linear-gradient(135deg, #8a2be2, #ff006e)';
        }} else {{
            contentDiv.style.background = 'rgba(58, 134, 255, 0.8)';
        }}
        contentDiv.textContent = text;
        
        messageDiv.appendChild(contentDiv);
        chatBox.appendChild(messageDiv);
        chatBox.scrollTop = chatBox.scrollHeight;
    }}
</script>
</body>
</html>"""

# --- تشغيل التطبيق ---
if __name__ == '__main__':
    logger.info("🚀 بدء تشغيل موبي...")
    # يمكنك إعداد الويب هوك هنا إذا أردت
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
