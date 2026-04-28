from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from chatbot import create_client, chat, AVAILABLE_MODELS
from memory import MemoryManager
from router import route as route_message
from tools import agentic_stream, TOOL_DEFINITIONS, LOCAL_TOOLS
from mcp_client import MCPClient
import providers as provider_mgr
import os
import json
import uuid
import threading
from datetime import datetime

app = Flask(__name__)
client = create_client()
memory_mgr = MemoryManager("lab2.db")

# MCP client: spawned lazily so the main process starts fast even if
# mcp_server.py has issues. Tool execution falls back to LOCAL_TOOLS
# when the MCP client is unavailable.
mcp_client = MCPClient()
_mcp_started = threading.Event()


def _ensure_mcp_started():
    if _mcp_started.is_set():
        return
    try:
        mcp_client.start(timeout=15)
    except Exception as e:
        print(f"[mcp] start failed: {e}")
    _mcp_started.set()


# Kick off MCP startup in a background thread so it doesn't block app boot.
threading.Thread(target=_ensure_mcp_started, daemon=True).start()


def mcp_executor(name, args, _conv_id_holder=None):
    """Route tool calls through MCP if connected; fall back to local.
    Records analytics for every call (latency, args, result)."""
    import time as _time
    start = _time.time()
    try:
        if mcp_client.connected:
            try:
                result = mcp_client.call_tool(name, args)
            except Exception as e:
                handler = LOCAL_TOOLS.get(name)
                result = (f"[MCP fallback] {e}; "
                          + (str(handler(args)) if handler else "no local fallback"))
        else:
            handler = LOCAL_TOOLS.get(name)
            result = handler(args) if handler else f"Unknown tool: {name}"
    finally:
        ms = int((_time.time() - start) * 1000)
        try:
            import analytics as _a
            _a.record_tool_call(name, args, str(result)[:500],
                                conv_id=_conv_id_holder, latency_ms=ms)
        except Exception:
            pass
    return result


CONVERSATIONS_FILE = "conversations.json"

def load_conversations():
    if not os.path.exists(CONVERSATIONS_FILE):
        return {}
    with open(CONVERSATIONS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_conversations(conversations):
    with open(CONVERSATIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(conversations, f, ensure_ascii=False, indent=2)

def _extract_memory_bg(conv_id, recent_messages):
    """Background helper: extract user facts from recent dialogue."""
    try:
        memory_mgr.extract_and_store(client, conv_id, recent_messages)
    except Exception as e:
        print(f"[memory extract] failed: {e}")

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/models", methods=["GET"])
def get_models():
    return jsonify(provider_mgr.list_all_models())

# ---- Custom API Providers --------------------------------------------

@app.route("/providers/templates", methods=["GET"])
def providers_templates():
    return jsonify(provider_mgr.PROVIDER_TEMPLATES)

@app.route("/providers", methods=["GET"])
def providers_list():
    return jsonify(provider_mgr.list_providers(safe=True))

@app.route("/providers", methods=["POST"])
def providers_add():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    p_type = (data.get("type") or "openai").strip()
    base_url = (data.get("base_url") or "").strip()
    api_key = (data.get("api_key") or "").strip()
    models = data.get("models") or []
    if not name or not base_url or not api_key:
        return jsonify({"error": "name / base_url / api_key 必填"}), 400
    if isinstance(models, str):
        models = [m.strip() for m in models.split(",") if m.strip()]
    pid = provider_mgr.add_provider(name, p_type, base_url, api_key, models)
    return jsonify({"id": pid, "status": "ok"})

@app.route("/providers/<pid>", methods=["DELETE"])
def providers_delete(pid):
    ok = provider_mgr.delete_provider(pid)
    return jsonify({"status": "ok" if ok else "not_found"})

@app.route("/providers/<pid>/test", methods=["POST"])
def providers_test(pid):
    ok, msg = provider_mgr.test_connection(pid)
    provider_mgr.update_test_result(pid, ok, msg)
    return jsonify({"ok": ok, "message": msg})

# ---- Long-term Memory ------------------------------------------------

@app.route("/memory", methods=["GET"])
def memory_list():
    return jsonify(memory_mgr.list_all())

@app.route("/memory", methods=["POST"])
def memory_add():
    data = request.get_json() or {}
    content = (data.get("content") or "").strip()
    category = data.get("category", "fact")
    if not content:
        return jsonify({"error": "內容不能為空"}), 400
    try:
        mid = memory_mgr.add(content, category=category)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"id": mid, "status": "ok" if mid else "duplicate"})

@app.route("/memory/<memory_id>", methods=["DELETE"])
def memory_delete(memory_id):
    ok = memory_mgr.delete(memory_id)
    return jsonify({"status": "ok" if ok else "not_found"})

@app.route("/memory/clear", methods=["POST"])
def memory_clear():
    n = memory_mgr.clear_all()
    return jsonify({"deleted": n})

@app.route("/memory/extract/<conv_id>", methods=["POST"])
def memory_extract(conv_id):
    conversations = load_conversations()
    if conv_id not in conversations:
        return jsonify({"error": "找不到對話"}), 404
    msgs = conversations[conv_id].get("messages", [])[-6:]
    added = memory_mgr.extract_and_store(client, conv_id, msgs)
    return jsonify({"extracted": len(added), "ids": added})

# ---- Auto Routing ----------------------------------------------------

@app.route("/route", methods=["POST"])
def route_endpoint():
    data = request.get_json() or {}
    msg = data.get("message", "")
    has_image = bool(data.get("has_image"))
    history = data.get("history", [])
    return jsonify(route_message(msg, history=history, has_image=has_image))

# ---- Tools (direct invocation + listing) -----------------------------

@app.route("/tools", methods=["GET"])
def tools_list():
    from mcp_tools import ALL_TOOLS
    return jsonify([
        {
            "name": name,
            "description": info["description"],
            "parameters": info["input_schema"],
        } for name, info in ALL_TOOLS.items()
    ])

@app.route("/tools/execute", methods=["POST"])
def tools_execute():
    from mcp_tools import ALL_TOOLS
    data = request.get_json() or {}
    name = data.get("tool")
    args = data.get("args") or {}
    if name not in ALL_TOOLS:
        return jsonify({"error": f"Unknown tool: {name}"}), 400
    try:
        result = mcp_executor(name, args)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({
        "tool": name,
        "result": result,
        "via_mcp": mcp_client.connected,
    })

@app.route("/mcp/status", methods=["GET"])
def mcp_status():
    return jsonify(mcp_client.status)

# ---- Notion page picker ----------------------------------------------

@app.route("/notion/pages", methods=["GET"])
def notion_pages():
    """Return a flat list of pages the integration can see, for the
    frontend page-picker. Groups sub-pages under their parent client-side."""
    try:
        from mcp_tools.notion_tools import notion_list_pages_structured
        pages = notion_list_pages_structured(limit=100)
        return jsonify({"pages": pages})
    except Exception as e:
        return jsonify({"error": str(e), "pages": []}), 500

# ---- Analytics Dashboard ---------------------------------------------

import analytics

@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")

@app.route("/api/analytics/overview", methods=["GET"])
def analytics_overview():
    return jsonify(analytics.overview())

@app.route("/api/analytics/tokens", methods=["GET"])
def analytics_tokens():
    days = int(request.args.get("days", 14))
    return jsonify(analytics.token_trend(days))

@app.route("/api/analytics/models", methods=["GET"])
def analytics_models():
    return jsonify(analytics.model_distribution())

@app.route("/api/analytics/heatmap", methods=["GET"])
def analytics_heatmap():
    days = int(request.args.get("days", 365))
    return jsonify(analytics.heatmap(days))

@app.route("/api/analytics/tools", methods=["GET"])
def analytics_tools():
    return jsonify(analytics.tool_ranking())

@app.route("/api/analytics/topics", methods=["GET"])
def analytics_topics():
    return jsonify(analytics.topic_clusters())

@app.route("/api/analytics/similarity", methods=["GET"])
def analytics_similarity():
    return jsonify(analytics.similarity_top())

@app.route("/api/analytics/wordcloud", methods=["GET"])
def analytics_wordcloud():
    return jsonify(analytics.word_frequency())

@app.route("/api/analytics/latency", methods=["GET"])
def analytics_latency():
    return jsonify(analytics.latency_stats())

@app.route("/api/analytics/memory_stats", methods=["GET"])
def analytics_memory_stats():
    return jsonify(analytics.memory_stats())

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

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _save_uploaded_image(image_data: str, image_type: str, conv_id: str) -> str:
    """Decode a base64 data URL or raw base64 string, save it to disk,
    and return the public path (e.g. /static/uploads/<conv>_<ts>.jpg)."""
    import base64
    raw = image_data
    if raw.startswith("data:"):
        # data:image/png;base64,XXXX
        raw = raw.split(",", 1)[-1]
    try:
        img_bytes = base64.b64decode(raw)
    except Exception as e:
        raise ValueError(f"Invalid base64 image: {e}")
    ext = (image_type or "image/png").split("/")[-1] or "png"
    if ext not in {"png", "jpeg", "jpg", "gif", "webp"}:
        ext = "png"
    fname = f"{conv_id}_{int(datetime.now().timestamp() * 1000)}.{ext}"
    path = os.path.join(UPLOAD_DIR, fname)
    with open(path, "wb") as f:
        f.write(img_bytes)
    return f"/static/uploads/{fname}"


@app.route("/chat/stream", methods=["POST"])
def chat_stream():
    data = request.get_json()
    user_message = data.get("message", "").strip()
    conv_id = data.get("conversation_id")
    model = data.get("model", "llama-3.3-70b-versatile")
    system_prompt = data.get("system_prompt", "")
    image_data = data.get("image_data")
    image_type = data.get("image_type", "image/png")

    if not user_message and not image_data:
        return jsonify({"error": "訊息不能為空"}), 400

    conversations = load_conversations()

    if not conv_id or conv_id not in conversations:
        conv_id = str(uuid.uuid4())
        conversations[conv_id] = {
            "title": (user_message or "圖片分析")[:40] + ("..." if len(user_message) > 40 else ""),
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

    has_image = bool(image_data)
    image_url = None
    if has_image:
        try:
            image_url = _save_uploaded_image(image_data, image_type, conv_id)
        except Exception as e:
            return jsonify({"error": f"圖片儲存失敗: {e}"}), 400

    # Auto routing: when client sends model="auto" OR an image was uploaded,
    # let router pick (router auto-selects vision model when image is present).
    routed_info = None
    if has_image or stored_model == "auto" or model == "auto":
        routed_info = route_message(user_message, history=history, has_image=has_image)
        stored_model = routed_info["model"]
        if model == "auto":
            conversations[conv_id]["model"] = "auto"

    # Build the user message — multimodal format when image is attached.
    if has_image:
        user_msg_for_history = {
            "role": "user",
            "content": user_message or "請描述這張圖片。",
            "image_url": image_url,  # custom field; chat API uses different format
        }
    else:
        user_msg_for_history = {"role": "user", "content": user_message}
    history.append(user_msg_for_history)

    # Always-on behavioral guidance — taught to every model regardless of
    # the user's chosen mode/system_prompt. Fixes recurring failure modes
    # like "AI promises to build HTML then doesn't deliver it inline".
    base_behavior = (
        "## 行為準則\n"
        "1. **HTML / web app / 遊戲 / widget / 計分板 / 儀表板 / 互動頁**："
        "請直接在這一輪回覆裡，把**完整可運作**的 HTML 寫在 ```html``` "
        "code block 內（含內嵌 CSS 和 JavaScript，single-file，不要外部依賴）。"
        "前端會自動在這個 code block 旁邊顯示「▶ 預覽」按鈕，"
        "點下去會在右側 artifact panel 即時渲染 — 所以你只要寫 inline 就好，"
        "**不要呼叫工具、不要說『讓我先用 Python 生成』、不要切多個訊息**。\n\n"
        "**HTML/遊戲品質要求 — 像 Anthropic claude.ai 的 artifact 那樣**：\n"
        "  - **完整可運作**：所有功能、所有狀態、所有事件處理都要實作，"
        "    絕對不要寫 `// TODO`、`// implement later`、`// rest of the logic`、"
        "    `// ... more code` 這種佔位符。\n"
        "  - **遊戲類**（Pacman / 貪食蛇 / 俄羅斯方塊 / 計分板 / 桌遊…）必須包含："
        "完整地圖/棋盤、所有 entity 的 AI / 移動邏輯、碰撞偵測、計分、生命/回合、"
        "開始/暫停/結束狀態、鍵盤/觸控操作、音效或視覺回饋（用 Web Audio API 即可）。\n"
        "  - **視覺**：用現代 CSS（漸層、陰影、霓虹、CRT 效果、動畫）做出有質感的 UI，"
        "不要陽春白底黑字。配色協調、有 hover/active 狀態、有過場動畫。\n"
        "  - **長度沒上限**：max_tokens 已設到 16384，請盡情寫到完整為止。"
        "與其給半成品，不如把功能稍微減一點但每個都做到位。\n"
        "  - **直接給最終版**，不要先給簡化版說「之後可以加上 X」。\n"
        "2. **SVG 圖形 / CSS 動畫**：同樣寫在 ```svg``` 或 ```css``` block，會自動預覽。\n"
        "3. **Mermaid 圖表**：寫在 ```mermaid``` block。\n"
        "4. **不要承諾後失蹤** — 如果你說「現在開始做」「讓我來」「我馬上生成」，"
        "請務必在**同一個回覆**就把成品給出來，不要寫一句話就停。\n"
        "5. **多步驟工具任務**（例如建 Notion 頁 + 三個資料庫 + 塞 row）："
        "獨立的 tool call 請在同一輪 tool_calls 陣列一次塞全部，不要 serial。"
    )

    # Inject long-term memory into system prompt.
    memory_context = memory_mgr.build_context(user_message or "image", limit=5)
    effective_system = base_behavior
    if (stored_system_prompt or "").strip():
        effective_system = effective_system + "\n\n" + stored_system_prompt.strip()
    if memory_context:
        effective_system = (effective_system + "\n\n" + memory_context).strip()

    # Inject Notion working-page context if the user picked one in the UI.
    notion_page_id = (data.get("notion_page_id") or "").strip()
    notion_page_title = (data.get("notion_page_title") or "").strip()
    if notion_page_id:
        notion_ctx = (
            f"[Notion 工作頁面已選定] 使用者目前綁定的 Notion 頁面：\n"
            f"  title: {notion_page_title or '(unknown)'}\n"
            f"  page_id: {notion_page_id}\n"
            "當使用者要在 Notion 新增 / append / 修改內容但沒明確指定頁面時，"
            "**直接用上面的 page_id 呼叫對應工具**（notion_append_to_page、"
            "notion_create_page 的 parent_id 等），不要再反問是哪個頁面。"
        )
        effective_system = (effective_system + "\n\n" + notion_ctx).strip()

    # Build the messages payload sent to Groq. For vision, the last user
    # message becomes a content array with text + image_url parts.
    full_messages = []
    if effective_system:
        full_messages.append({"role": "system", "content": effective_system})
    for m in history[:-1]:
        # Strip our custom image_url field for past turns (use plain text).
        full_messages.append({"role": m["role"], "content": m.get("content", "")})

    if has_image:
        # Embed the image as a data URL so Groq's vision model can read it.
        data_url = image_data if image_data.startswith("data:") else \
                   f"data:{image_type};base64,{image_data}"
        full_messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": user_message or "Describe this image."},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        })
    else:
        full_messages.append({"role": "user", "content": user_message})

    save_conversations(conversations)

    use_tools = bool(data.get("use_tools", True))
    is_vision_model = "vision" in stored_model or "scout" in stored_model.lower() \
                      or has_image

    # Pick the right SDK client for the chosen model (Groq built-in or
    # a user-added provider via OpenAI-compatible endpoint).
    try:
        chat_client, provider_type = provider_mgr.get_client_for_model(stored_model)
    except Exception as e:
        return jsonify({"error": f"無法取得 provider client: {e}"}), 500

    def generate():
        full_response = ""
        # Track image URLs surfaced by tool results (e.g. generate_image)
        # so we can persist them on the assistant message and re-render
        # them when the conversation is reloaded.
        tool_image_urls: list[str] = []
        import re as _re
        _img_marker = _re.compile(r"\[IMAGE\](/static/uploads/[^\[\]]+)\[/IMAGE\]")

        meta = {
            "conv_id": conv_id,
            "title": conversations[conv_id]["title"],
            "memory_used": bool(memory_context),
            "tools_enabled": use_tools and not is_vision_model,
            "provider": provider_type,
        }
        if routed_info:
            meta["routed_model"] = routed_info["model"]
            meta["route_reason"] = routed_info["reason"]
        if image_url:
            meta["image_url"] = image_url
        yield f"data: {json.dumps(meta, ensure_ascii=False)}\n\n"

        try:
            if use_tools and not is_vision_model:
                # Drive the agentic tool-calling loop. Tools are routed
                # through MCP when connected, otherwise local fallback.
                for sse in agentic_stream(chat_client, full_messages, model=stored_model,
                                          tool_executor=mcp_executor):
                    # Capture content chunks and harvest image URLs.
                    try:
                        payload = json.loads(sse[6:])  # strip "data: "
                        if isinstance(payload, dict):
                            if payload.get("content"):
                                full_response += payload["content"]
                            if payload.get("type") == "tool_result":
                                for u in _img_marker.findall(str(payload.get("result", ""))):
                                    if u not in tool_image_urls:
                                        tool_image_urls.append(u)
                    except Exception:
                        pass
                    yield sse
            else:
                # Plain streaming (vision model or tools disabled).
                stream = chat_client.chat.completions.create(
                    model=stored_model,
                    messages=full_messages,
                    stream=True,
                    max_tokens=16384,
                )
                for chunk in stream:
                    content = chunk.choices[0].delta.content
                    if content:
                        full_response += content
                        yield f"data: {json.dumps({'content': content}, ensure_ascii=False)}\n\n"
        finally:
            assistant_msg = {"role": "assistant", "content": full_response}
            if tool_image_urls:
                assistant_msg["images"] = tool_image_urls
            history.append(assistant_msg)
            if len(history) == 2:
                conversations[conv_id]["title"] = user_message[:40] + ("..." if len(user_message) > 40 else "")
            conversations[conv_id]["messages"] = history
            save_conversations(conversations)
            yield f"data: {json.dumps({'done': True, 'title': conversations[conv_id]['title']}, ensure_ascii=False)}\n\n"
            # Auto-extract user facts on every user turn (background, non-blocking).
            # Previously fired only on even-numbered turns (2,4,6…), which
            # silently skipped extraction for one-shot conversations like
            # "我喜歡吃西瓜" → AI reply → user starts a new chat. The extractor
            # is cheap (8B model) and idempotent (dedupe on content), so we
            # can safely run it every turn.
            threading.Thread(
                target=_extract_memory_bg,
                args=(conv_id, list(history[-6:])),
                daemon=True,
            ).start()

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    app.run(debug=True)
