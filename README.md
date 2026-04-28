<div align="center">

# ✦ GenAI LLM Chatbot v2

**An agentic AI chatbot platform with MCP, multimodal vision, code execution, analytics dashboard, and 23 built-in tools.**

![Version](https://img.shields.io/badge/version-2.0.0-6366f1?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.x-000000?style=for-the-badge&logo=flask&logoColor=white)
![Groq](https://img.shields.io/badge/Groq-API-F55036?style=for-the-badge&logo=groq&logoColor=white)
![MCP](https://img.shields.io/badge/MCP-23_tools-22c55e?style=for-the-badge)
![License](https://img.shields.io/badge/License-MIT-22c55e?style=for-the-badge)

</div>

---

## 🚀 What's new in v2

| Capability | Description |
|------------|-------------|
| 🧠 **Long-term Memory** | SQLite-backed user facts. Auto-extracted from dialogue. Auto-injected before each turn. |
| 👁️ **Multimodal Vision** | Drag-drop image upload. Routed to Llama 4 Scout vision model. |
| ⚡ **Auto Routing** | Picks the best Groq model per message (fast/long-ctx/vision/general). |
| 🔧 **23 MCP Tools** | Calculator · datetime · web search · weather · image gen · filesystem · GitHub · arXiv · Wikipedia · YouTube · stocks · crypto · code execution · 5 Notion tools · more |
| 🔌 **Real MCP Server** | Standalone server using the official `mcp` Python package over stdio. |
| 🔑 **Custom API Providers** | Plug in OpenAI · Claude · OpenRouter · DeepSeek · Together · Mistral · Ollama · LM Studio. |
| 🎨 **Image Generation** | Pollinations.ai integration (free, no key). 8 styles. |
| 💻 **Code Interpreter** | Sandboxed Python execution. Auto-captures matplotlib plots. |
| 📊 **Analytics Dashboard** | 9 charts: token trend · model dist · 365-day heatmap · TF-IDF topic clusters · cosine similarity · word cloud · tool ranking · latency · activity. |
| 📝 **Notion Integration** | Search, create, append pages from chat (requires Notion Integration Token). |
| 🧠 **Reasoning Panel** | Live agent thinking steps (OpenManus-style). |
| 🌐 **Citations** | Web search results auto-cite sources. |

---

## 📊 Dashboard

The `/dashboard` page renders 9 real-time charts driven by your conversation history:

- **Token usage trend** — daily input/output (line chart)
- **Model distribution** — which model you used most (donut)
- **365-day activity heatmap** — GitHub-style calendar
- **Tool call ranking** — most-invoked MCP tools (bar chart)
- **Topic clusters** — TF-IDF auto-categorisation
- **Conversation similarity** — cosine similarity Top 5 (heatmap)
- **Word frequency cloud** — your most-used words
- **Tool latency** — average ms per tool
- **Live overview** — totals & 24h trend

Auto-refreshes every 60 seconds.

---

## 🤖 Available Models

Built-in (Groq, free tier):

| Model | Speed | Best For |
|-------|-------|----------|
| ⚡ **Auto Routing** | — | Picks the right model per message |
| 🥇 Llama 3.3 70B | ⚡⚡ | General use — most capable |
| 🚀 Llama 3.1 8B | ⚡⚡⚡⚡ | Quick answers |
| 👁️ Llama 4 Scout | ⚡⚡ | Image analysis (vision) |
| 📖 Mixtral 8x7B | ⚡⚡⚡ | Long documents |
| 🔵 Gemma 2 9B | ⚡⚡⚡ | Google's model |

Add your own (UI: 🔑 API button):

- OpenAI · Anthropic Claude · OpenRouter · DeepSeek · Together AI · Mistral · Ollama · LM Studio · any OpenAI-compatible endpoint

---

## 🔧 23 MCP Tools

Every tool is exposed as a real MCP tool (JSON-RPC over stdio) and the chatbot can invoke them mid-conversation.

| Category | Tools |
|----------|-------|
| 🧮 Basic | `calculator` · `get_datetime` · `web_search` · `get_weather` |
| 🎨 Generation | `generate_image` (Pollinations.ai, 8 styles) |
| 📁 Filesystem | `read_file` · `write_file` · `list_directory` · `search_files` (sandboxed) |
| 🌐 Web | `fetch_url` · `github_search_repos` · `github_read_file` · `youtube_transcript` |
| 📚 Academic | `arxiv_search` · `wikipedia_search` |
| 💹 Finance | `stock_price` (Yahoo) · `crypto_price` (CoinGecko) |
| 💻 Code | `execute_python` (sandboxed, matplotlib auto-capture) |
| 📝 Notion | `notion_search` · `notion_list_pages` · `notion_create_page` · `notion_append_to_page` · `notion_query_database` |

---

## 🧬 Architecture

```
[Browser]
    │
    ▼
[Flask /chat/stream]
    ├─→ memory.MemoryManager      (SQLite, auto-injected per turn)
    ├─→ router.route              (vision/fast/long-ctx/default model)
    ├─→ providers.get_client      (Groq built-in OR user-added provider)
    └─→ tools.agentic_stream      (multi-round Groq function calling)
              │
              ▼
        mcp_client.call_tool      (sync ↔ async bridge)
              │  JSON-RPC over stdio
              ▼
        mcp_server.py             (subprocess)
              │
              └─→ mcp_tools/      (8 modules · 23 tools)
                    ├─ basic       (calc/datetime/search/weather)
                    ├─ image_gen   (Pollinations.ai)
                    ├─ filesystem  (sandboxed read/write)
                    ├─ web         (fetch/github/youtube)
                    ├─ academic    (arxiv/wikipedia)
                    ├─ finance     (stock/crypto)
                    ├─ code_exec   (sandboxed Python)
                    └─ notion_tools (5 Notion API tools)
```

---

## 🚀 Quick Start

### 1. Install

```bash
git clone https://github.com/justin999-tech/GenAI_LLM1.git
cd GenAI_LLM1
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

### 2. Set your Groq key

```bash
echo "GROQ_API_KEY=gsk_your_key_here" > .env
```

> Get a **free** key at [console.groq.com](https://console.groq.com/) — no credit card required.

### 3. Run

```bash
python app.py
```

Open http://127.0.0.1:5000

---

## 🗂️ Project Structure

```
GenAI_LLM1/
├── app.py                  # Flask routes & API endpoints
├── chatbot.py              # Built-in Groq model list
├── memory.py               # Long-term memory (SQLite)
├── router.py               # Auto model routing
├── tools.py                # Tool defs + agentic loop
├── providers.py            # Multi-provider client manager
├── analytics.py            # Dashboard data computations
├── mcp_server.py           # MCP server (stdio)
├── mcp_client.py           # MCP client (sync/async bridge)
├── mcp_tools/              # 8 tool modules · 23 tools
│   ├── __init__.py
│   ├── basic.py
│   ├── image_gen.py
│   ├── filesystem.py
│   ├── web.py
│   ├── academic.py
│   ├── finance.py
│   ├── code_exec.py
│   └── notion_tools.py
├── templates/
│   ├── index.html          # Main chat UI
│   └── dashboard.html      # Analytics dashboard
└── static/
    ├── style.css
    └── uploads/            # User images + AI-generated images
```

Excluded from git: `.env` · `providers.json` · `lab2.db` · `conversations.json` · `static/uploads/*`

---

## ⌨️ Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl + N` | New conversation |
| `Ctrl + M` | Open memory manager |
| `Ctrl + E` | Open notes workspace |
| `Ctrl + P` | Open prompt library |
| `Ctrl + ,` | Open settings |
| `Ctrl + /` | Search conversations |
| `Enter` | Send message |
| `Shift + Enter` | New line |

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python · Flask · SQLite |
| AI | Groq API (LPU inference) · OpenAI-compatible providers |
| MCP | Official `mcp` Python SDK · stdio transport |
| Frontend | Vanilla JS · Chart.js · marked.js · highlight.js · KaTeX · Mermaid.js |
| Image | Pollinations.ai (free, no key) |
| Web data | DuckDuckGo · GitHub Search · arXiv · Wikipedia · Open-Meteo · CoinGecko · Yahoo Finance |

---

<div align="center">

Made with ❤️ · MIT License · Lab 2 v2.0.0

</div>
