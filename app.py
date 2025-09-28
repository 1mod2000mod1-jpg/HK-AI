import os
import requests
from flask import Flask, request
import json

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
DEEPSEEK_API_KEY = os.getenv('aimlapi_API_KEY')

def send_telegram_message(chat_id, text):
    """إرسال رسالة عبر تليجرام API مباشرة"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": text
    }
    try:
        response = requests.post(url, json=data, timeout=10)
        return response.json()
    except Exception as e:
        print(f"Telegram API error: {e}")
        return None

def send_typing_action(chat_id):
    """إظهار حالة الكتابة"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendChatAction"
    data = {
        "chat_id": chat_id,
        "action": "typing"
    }
    try:
        requests.post(url, json=data, timeout=5)
    except:
        pass

def get_ai_response(message_text):
    """الحصول على رد من aimlapi"""
    try:
        headers = {
            "Authorization": f"Bearer {aimlapi_API_KEY}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": "aimlapi-chat",
            "messages": [
                {
                    "role": "system", 
                    "content": "أنت مساعد مفيد ومهذب. ارد باللغة العربية ما لم يطلب منك غير ذلك."
                },
                {
                    "role": "user",
                    "content": message_text
                }
            ],
            "stream": False,
            "max_tokens": 2000,
            "temperature": 0.7
        }
        
        response = requests.post(
            "https://api.aimlapi.com/app/keys",
            headers=headers,
            json=data,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            return result["choices"][0]["message"]["content"]
        else:
            return f"❌ خطأ في API: {response.status_code}"
            
    except Exception as e:
        return f"❌ خطأ في الاتصال: {str(e)}"

@app.route('/')
def home():
    return '''
    <h1>🤖 بوت DeepSeek يعمل!</h1>
    <p>✅ البوت جاهز للاستخدام</p>
    <p><a href="/setwebhook">🔗 تعيين الويبهوك</a></p>
    '''

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.method == 'POST':
        try:
            data = request.get_json()
            
            if 'message' in data and 'text' in data['message']:
                chat_id = data['message']['chat']['id']
                message_text = data['message']['text']
                
                print(f"💬 رسالة من {chat_id}: {message_text}")
                
                if message_text == '/start':
                    send_telegram_message(
                        chat_id, 
                        '🌐 **مرحبا! أنا بوت DeepSeek**\n\n'
                        '💬 يمكنك سؤالي عن أي موضوع:\n'
                        '• معلومات عامة\n• برمجة\n• كتابة نصوص\n• ترجمة\n• وغيرها!\n\n'
                        '✍️ **جرب الآن:** اكتب سؤالك الأول'
                    )
                elif message_text == '/help':
                    send_telegram_message(
                        chat_id, 
                        '🆘 **كيفية الاستخدام:**\n'
                        '/start - بدء التشغيل\n'
                        '/help - المساعدة\n'
                        '💬 اكتب أي سؤال للحصول على إجابة ذكية'
                    )
                elif message_text == '/status':
                    send_telegram_message(chat_id, '✅ البوت يعمل بشكل مثالي!')
                else:
                    send_typing_action(chat_id)
                    response = get_ai_response(message_text)
                    
                    # إذا كان الرد طويلاً، نقسمه
                    if len(response) > 4000:
                        for i in range(0, len(response), 4000):
                            send_telegram_message(chat_id, response[i:i+4000])
                    else:
                        send_telegram_message(chat_id, response)
            
            return 'OK'
            
        except Exception as e:
            print(f"❌ خطأ في الويبهوك: {e}")
            return 'Error', 500

@app.route('/setwebhook', methods=['GET'])
def set_webhook():
    """تعيين الويبهوك"""
    try:
        webhook_url = f"https://{request.host}/webhook"
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook"
        data = {"url": webhook_url}
        
        response = requests.post(url, json=data)
        result = response.json()
        
        return f'''
        <h1>✅ تم تعيين الويبهوك بنجاح!</h1>
        <p><strong>الرابط:</strong> {webhook_url}</p>
        <p><strong>الحالة:</strong> {result}</p>
        <p>🎉 البوت جاهز للاستخدام في تليجرام!</p>
        '''
    except Exception as e:
        return f'<h1>❌ خطأ:</h1><p>{e}</p>'

if __name__ == '__main__':
    print("🚀 بدء تشغيل البوت...")
    print("✅ مفتاح DeepSeek صحيح!")
    
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
