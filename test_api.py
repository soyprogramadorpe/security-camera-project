import os
from dotenv import load_dotenv
import urllib.request
import urllib.parse
import json

load_dotenv()

bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
chat_id = os.getenv("TELEGRAM_CHAT_ID")
gemini_key = os.getenv("GEMINI_API_KEY")

print("--- TELEGRAM TEST ---")
try:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = urllib.parse.urlencode({'chat_id': chat_id, 'text': 'test'}).encode()
    req = urllib.request.Request(url, data=data)
    urllib.request.urlopen(req, timeout=10)
    print("Telegram Success!")
except urllib.error.HTTPError as e:
    print(f"Telegram HTTP Error: {e.code}")
    print(e.read().decode('utf-8'))
except Exception as e:
    print(f"Telegram Error: {e}")

print("\n--- GEMINI TEST ---")
try:
    import google.generativeai as genai
    genai.configure(api_key=gemini_key)
    print("Available GenAI Models:")
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(m.name)
except Exception as e:
    print(f"Gemini Error: {e}")
