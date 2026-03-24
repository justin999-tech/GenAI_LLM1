from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from chatbot import create_client, chat, AVAILABLE_MODELS
import os
import json
import uuid
from datetime import datetime

app = Flask(__name__)
client = create_client()

CONVERSATIONS_FILE = "conversations.json"

def load_conversations():
    if not os.path.exists(CONVERSATIONS_FILE):
        return {}
    with open(CONVERSATIONS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_conversations(conversations):
    with open(CONVERSATIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(conversations, f, ensure_ascii=False, indent=2)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/models", methods=["GET"])
def get_models():
    return jsonify(AVAILABLE_MODELS)

@app.route("/conversations", methods=["GET"])
def get_conversations():
    conversations = load_conversations()
    result = [
        {"id": cid, "title": c["title"], "created_at": c["created_at"]}
        for cid, c in conversations.items()
    ]
    result.sort(key=lambda x: x["created_at"], reverse=True)
    return jsonify(result)

@app.route("/conversations/<conv_id>", methods=["GET"])
def get_conversation(conv_id):
    conversations = load_conversations()
    if conv_id not in conversations:
        return jsonify({"error": "找不到對話"}), 404
    return jsonify(conversations[conv_id])

@app.route("/conversations/<conv_id>", methods=["DELETE"])
def delete_conversation(conv_id):
    conversations = load_conversations()
    if conv_id in conversations:
        del conversations[conv_id]
        save_conversations(conversations)
    return jsonify({"status": "ok"})

@app.route("/conversations/<conv_id>/title", methods=["PUT"])
def update_title(conv_id):
    conversations = load_conversations()
    if conv_id not in conversations:
        return jsonify({"error": "找不到對話"}), 404
    data = request.get_json()
    new_title = (data.get("title") or "新對話")[:60].strip() or "新對話"
    conversations[conv_id]["title"] = new_title
    save_conversations(conversations)
    return jsonify({"status": "ok"})

@app.route("/conversations/<conv_id>/regenerate", methods=["POST"])
def regenerate(conv_id):
    conversations = load_conversations()
    if conv_id not in conversations:
        return jsonify({"error": "找不到對話"}), 404

    history = conversations[conv_id]["messages"]

    # Remove last assistant message
    if history and history[-1]["role"] == "assistant":
        history.pop()

    # Find last user message content
    last_user = None
    for msg in reversed(history):
        if msg["role"] == "user":
            last_user = msg["content"]
            break

    if not last_user:
        return jsonify({"error": "沒有可重新生成的訊息"}), 400

    # Remove last user message (chat() will re-add it)
    if history and history[-1]["role"] == "user":
        history.pop()

    model = conversations[conv_id].get("model", "llama-3.3-70b-versatile")
    system_prompt = conversations[conv_id].get("system_prompt", "")

    response = chat(client, history, last_user, model=model, system_prompt=system_prompt)
    conversations[conv_id]["messages"] = history
    save_conversations(conversations)

    return jsonify({"response": response})

@app.route("/chat", methods=["POST"])
def chat_endpoint():
    data = request.get_json()
    user_message = data.get("message", "").strip()
    conv_id = data.get("conversation_id")
    model = data.get("model", "llama-3.3-70b-versatile")
    system_prompt = data.get("system_prompt", "")

    if not user_message:
        return jsonify({"error": "訊息不能為空"}), 400

    conversations = load_conversations()

    if not conv_id or conv_id not in conversations:
        conv_id = str(uuid.uuid4())
        conversations[conv_id] = {
            "title": "新對話",
            "messages": [],
            "created_at": datetime.now().isoformat(),
            "model": model,
            "system_prompt": system_prompt,
        }
    else:
        if model:
            conversations[conv_id]["model"] = model
        if system_prompt is not None:
            conversations[conv_id]["system_prompt"] = system_prompt

    history = conversations[conv_id]["messages"]
    stored_model = conversations[conv_id].get("model", model)
    stored_system_prompt = conversations[conv_id].get("system_prompt", system_prompt)

    response = chat(client, history, user_message,
                    model=stored_model, system_prompt=stored_system_prompt)

    if len(history) == 2:
        title = user_message[:40] + ("..." if len(user_message) > 40 else "")
        conversations[conv_id]["title"] = title

    conversations[conv_id]["messages"] = history
    save_conversations(conversations)

    return jsonify({
        "response": response,
        "conversation_id": conv_id,
        "title": conversations[conv_id]["title"],
    })

@app.route("/chat/stream", methods=["POST"])
def chat_stream():
    data = request.get_json()
    user_message = data.get("message", "").strip()
    conv_id = data.get("conversation_id")
    model = data.get("model", "llama-3.3-70b-versatile")
    system_prompt = data.get("system_prompt", "")

    if not user_message:
        return jsonify({"error": "訊息不能為空"}), 400

    conversations = load_conversations()

    if not conv_id or conv_id not in conversations:
        conv_id = str(uuid.uuid4())
        conversations[conv_id] = {
            "title": user_message[:40] + ("..." if len(user_message) > 40 else ""),
            "messages": [],
            "created_at": datetime.now().isoformat(),
            "model": model,
            "system_prompt": system_prompt,
        }
    else:
        if model:
            conversations[conv_id]["model"] = model
        if system_prompt is not None:
            conversations[conv_id]["system_prompt"] = system_prompt

    history = conversations[conv_id]["messages"]
    stored_model = conversations[conv_id].get("model", model)
    stored_system_prompt = conversations[conv_id].get("system_prompt", system_prompt)

    history.append({"role": "user", "content": user_message})

    full_messages = history
    if stored_system_prompt and stored_system_prompt.strip():
        full_messages = [{"role": "system", "content": stored_system_prompt}] + history

    save_conversations(conversations)

    def generate():
        full_response = ""
        yield f"data: {json.dumps({'conv_id': conv_id, 'title': conversations[conv_id]['title']})}\n\n"
        try:
            stream = client.chat.completions.create(
                model=stored_model,
                messages=full_messages,
                stream=True,
                max_tokens=4096,
            )
            for chunk in stream:
                content = chunk.choices[0].delta.content
                if content:
                    full_response += content
                    yield f"data: {json.dumps({'content': content})}\n\n"
        finally:
            history.append({"role": "assistant", "content": full_response})
            if len(history) == 2:
                conversations[conv_id]["title"] = user_message[:40] + ("..." if len(user_message) > 40 else "")
            conversations[conv_id]["messages"] = history
            save_conversations(conversations)
            yield f"data: {json.dumps({'done': True, 'title': conversations[conv_id]['title']})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    app.run(debug=True)
