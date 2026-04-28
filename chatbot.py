import os
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

AVAILABLE_MODELS = [
    {"id": "auto",                          "name": "⚡ 自動路由",     "desc": "根據訊息類型自動選擇"},
    {"id": "llama-3.3-70b-versatile",       "name": "Llama 3.3 70B",  "desc": "最強大・推薦"},
    {"id": "llama-3.1-8b-instant",          "name": "Llama 3.1 8B",   "desc": "最快速"},
    {"id": "meta-llama/llama-4-scout-17b-16e-instruct", "name": "Llama 4 Scout (Vision)", "desc": "圖像分析"},
    {"id": "mixtral-8x7b-32768",            "name": "Mixtral 8x7B",   "desc": "長上下文"},
    {"id": "gemma2-9b-it",                  "name": "Gemma 2 9B",     "desc": "Google"},
]

def create_client():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("找不到 GROQ_API_KEY，請確認 .env 檔案設定正確")
    return Groq(api_key=api_key)

def chat(client, conversation_history, user_message,
         model="llama-3.3-70b-versatile", system_prompt=None):
    conversation_history.append({"role": "user", "content": user_message})

    messages = conversation_history
    if system_prompt and system_prompt.strip():
        messages = [{"role": "system", "content": system_prompt}] + conversation_history

    response = client.chat.completions.create(model=model, messages=messages)
    assistant_message = response.choices[0].message.content

    conversation_history.append({"role": "assistant", "content": assistant_message})
    return assistant_message
