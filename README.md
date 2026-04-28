<div align="center">

# ✦ GenAI LLM Chatbot v2

**An agentic AI chatbot — MCP tools · multimodal vision · code execution · long-term memory · 9-chart analytics dashboard.**

![Version](https://img.shields.io/badge/version-2.0.0-6366f1?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.x-000000?style=for-the-badge&logo=flask&logoColor=white)
![Groq](https://img.shields.io/badge/Groq-API-F55036?style=for-the-badge&logo=groq&logoColor=white)
![MCP](https://img.shields.io/badge/MCP-23_tools-22c55e?style=for-the-badge)
![License](https://img.shields.io/badge/License-MIT-22c55e?style=for-the-badge)

</div>

---

## ★ HW02 Required Features (Deep Dive)

### 1. ⚡ Auto Routing Between Models — [`router.py`](router.py)

The chatbot ships with 5 Groq models plus any user-added providers. When the user picks **`⚡ 自動路由`** or uploads an image, the request goes through `router.route()`, which inspects the payload to decide which model fits best:

| Signal in request | Chosen model | Why |
|---|---|---|
| `has_image=True` | `meta-llama/llama-4-scout-17b-16e-instruct` | Vision-capable; the only Groq model that accepts `image_url` content |
| Message contains "快速 / fast / quick / 簡短" or < 30 chars | `llama-3.1-8b-instant` | Lower latency, free-tier TPM is higher |
| Message > 2000 chars or `history > 6 turns` | `mixtral-8x7b-32768` | 32K context window |
| Maths-heavy (regex `\d+[+\-*/^=]`) | `llama-3.3-70b-versatile` | Strongest reasoning |
| Default | `llama-3.3-70b-versatile` | Best general performance |

The chosen model is returned with a `route_reason` string that the frontend renders as a small badge so the user can see *why* a model was picked.

### 2. 👁 Multimodal Vision

End-to-end image flow:

1. **Drag-drop in browser** — `index.html` listens for `drop` / `paste` events, reads the file as a base64 data URL.
2. **POST to `/chat/stream`** — frontend sends `{message, image_data, image_type}`.
3. **Backend persists** — [`app.py:_save_uploaded_image()`](app.py) decodes base64, writes to `static/uploads/<conv-id>_<ts>.<ext>`, returns the public path.
4. **Auto-routing fires** — `router.route(has_image=True)` always selects Llama 4 Scout regardless of other signals.
5. **OpenAI vision-format payload** — the backend constructs a content array:
   ```python
   [{"type": "text", "text": prompt},
    {"type": "image_url", "image_url": {"url": data_url}}]
   ```
6. **Re-rendering** — when reopening the conversation, the saved image path is preserved on the user message and re-rendered, so the chat stays multimodal across reloads.

Image size cap: 10 MB; supported formats: PNG, JPEG, GIF, WebP.

### 3. 🧠 Long-term Memory — [`memory.py`](memory.py) + SQLite

A persistent `lab2.db` stores user-specific facts across conversations. The system has four moving parts:

**a. Auto-extraction (every user turn).** After each `/chat/stream` call, a daemon thread runs [`extract_and_store()`](memory.py). It:
- Filters `recent_messages` to **only `role=='user'`** turns (assistant suggestions like "比如：香蕉、橙子" used to leak in as fake preferences — fixed).
- Sends them to `llama-3.1-8b-instant` with a strict prompt that enforces:
  - Only explicit user statements ("我喜歡 X / 我用 Y") count.
  - Reflective questions and enumerations don't count.
  - Output must be a JSON array of `{content, category}` where category ∈ `{fact, preference, instruction}`.
- Deduplicates on lowercased `content` before insert.

**b. Retrieval (every new turn).** Before sending a request to the LLM, [`build_context()`](memory.py) calls `search()` which:
- Tokenises the query with a hybrid CJK-bigram + ASCII tokeniser. For "我喜歡吃什麼食物" it emits `["我喜","喜歡","歡吃","吃什","什麼","麼食","食物"]`. Without bigrams, Chinese queries (no whitespace) would never match stored memories.
- Scores every memory by token-overlap hits, then sorts: `(hits ↓, access_count ↓, created_at ↓)` — newest wins ties so fresh memories always surface.
- Returns top-5; their `access_count` is bumped so frequently-relevant memories stay sticky.

**c. Injection.** The retrieved memories are formatted as a `[已知使用者資訊 / Known User Context]` block prepended to the system prompt every turn.

**d. Manageability.** Press `Ctrl+M` to open the memory panel — list, add, delete, or clear all memories. The categories are colour-coded.

**Robustness against rate-limit fallback:** when Groq returns 429 / "Request too large", the slim retry path (8B without tool schemas) **also re-extracts and re-injects the memory block** so memory recall survives even degraded paths.

### 4. 🔧 Tool Use + MCP — [`tools.py`](tools.py) + [`mcp_server.py`](mcp_server.py)

A real **Model Context Protocol** server runs as a subprocess and speaks JSON-RPC over stdio using the official [`mcp` Python SDK](https://github.com/modelcontextprotocol/python-sdk). The chat backend talks to it via `mcp_client.call_tool()`.

**Why a real subprocess (not inline functions)?**

| Property | Subprocess MCP | Inline tool functions |
|---|---|---|
| Process isolation | ✅ a crashing tool can't take down the chat server | ❌ |
| Drop-in compatibility with Claude Desktop / Cline | ✅ same JSON-RPC API | ❌ |
| Hot-reloadable tools | ✅ restart MCP, keep streaming | ❌ |
| Cross-tool result sharing | ✅ MCP context | inline |

**Agentic loop.** [`tools.agentic_stream()`](tools.py) runs a multi-round loop:

```
while finish_reason == "tool_calls":
    1. Stream completion from LLM (with `tools=` schema in payload)
    2. Accumulate partial tool_call JSON across chunks
    3. For each tool_call, send to mcp_client.call_tool() in parallel
    4. Append tool_results to message history
    5. Loop back — model may chain tools or write final answer
```

Empty-reply detection nudges the model to write a final answer if it stops without one.

**Local fallback.** If MCP is offline (subprocess crashed, port busy), `LOCAL_TOOLS` provides a 4-tool baseline (calc / datetime / web search / weather) so the system degrades gracefully rather than failing closed.

### 5. ✦ Other Useful Functions

The remaining features layer on top of the four above:

- **Multi-provider** ([`providers.py`](providers.py)) — A unified manager for any OpenAI-compatible endpoint. Click 🔑 API in the toolbar to plug in OpenAI, Anthropic Claude, OpenRouter, DeepSeek, Together AI, Mistral, Ollama, LM Studio. Keys are stored server-side in `providers.json` (gitignored) and never exposed to the client.

- **Sandboxed Python interpreter** ([`mcp_tools/code_exec.py`](mcp_tools/code_exec.py)) — `execute_python` runs in a `safe_workspace/` directory with a restricted globals dict, captures stdout, and **auto-captures matplotlib figures** to PNG → returned to the model as inline image markers that the frontend renders directly in chat.

- **Free image generation** ([`mcp_tools/image_gen.py`](mcp_tools/image_gen.py)) — Wraps Pollinations.ai (no API key needed). 8 styles: photorealistic, anime, watercolor, oil-painting, pixel-art, 3D-render, sketch, fantasy. Generated images are saved to `static/uploads/` and shown inline.

- **Notion integration** ([`mcp_tools/notion_tools.py`](mcp_tools/notion_tools.py)) — 5 tools: `notion_search`, `notion_list_pages`, `notion_create_page`, `notion_append_to_page`, `notion_query_database`. Page picker (📓 Notion) lets the user pin a "current working page" so the agent doesn't have to ask which page each time.

- **Inline artifact preview** — Code blocks in `html`, `svg`, `mermaid`, or that contain `<canvas>` get a `▶ 預覽` button that opens a side panel with the artifact rendered live. Pac-Man, sine waves, dashboards — all playable in-chat without leaving the page.

- **Analytics dashboard** ([`analytics.py`](analytics.py) + `dashboard.html`) — see [Analytics Dashboard](#-analytics-dashboard) below.

- **Conversation features** — pinned conversations, full-text search (Ctrl+/), regenerate last reply, edit titles, export to Markdown.

- **Mode presets** — chat / code / write / analyze / translate (top-left mode switcher) — each preloads a different system prompt template.

---

## 🚀 Quick Start

### 1. Clone & install

```bash
git clone https://github.com/justin999-tech/GenAI_LLM1.git
cd GenAI_LLM1
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
```

### 2. Set your Groq key

```bash
echo "GROQ_API_KEY=gsk_your_key_here" > .env
```

> Get a **free** key at [console.groq.com](https://console.groq.com/) — no credit card required.

### 3. (Optional) Add more providers

Click **🔑 API** in the bottom toolbar to add OpenAI / Claude / OpenRouter / DeepSeek / Together / Mistral / Ollama / LM Studio. Keys are stored in `providers.json` (gitignored).

### 4. (Optional) Notion integration

```bash
echo "NOTION_TOKEN=secret_your_token" >> .env
```

Get a token at [notion.so/my-integrations](https://www.notion.so/my-integrations) and share your pages with the integration.

### 5. Run

```bash
python app.py
```

Open <http://127.0.0.1:5000>.

---

## 📊 Analytics Dashboard

The `/dashboard` page renders 9 real-time charts driven by your conversation history:

| Chart | What it shows | Implementation |
|---|---|---|
| **Token usage trend** | Daily input/output tokens (line chart) | Sums `usage` field across `conversations.json` per day |
| **Model distribution** | Which model you used most (donut) | `Counter` over `conv['model']` |
| **365-day activity heatmap** | GitHub-style calendar | Daily message count grouped by ISO date |
| **Tool call ranking** | Most-invoked MCP tools (bar chart) | Counts from analytics SQLite log |
| **Topic clusters** | TF-IDF auto-categorisation | Scikit-learn `TfidfVectorizer` + `KMeans(n=5)` |
| **Conversation similarity** | Cosine similarity Top 5 (heatmap) | TF-IDF vectors → `cosine_similarity` |
| **Word frequency cloud** | Most-used words | Token frequency with CJK splitting |
| **Tool latency** | Average ms per tool | Avg `latency_ms` per tool name |
| **Live overview** | Totals & 24h trend | Live counters refreshed every 60s |

Auto-refreshes every 60 seconds; survives across runs because the analytics SQLite is separate from `lab2.db`.

---

## 🤖 Available Models

Built-in (Groq, free tier):

| Model | Speed | Best For |
|-------|-------|----------|
| ⚡ **Auto Routing** | — | Picks the right model per message |
| 🥇 Llama 3.3 70B | ⚡⚡ | General use — most capable |
| 🚀 Llama 3.1 8B | ⚡⚡⚡⚡ | Quick answers |
| 👁️ Llama 4 Scout | ⚡⚡ | Image analysis (vision) |
| 📖 Mixtral 8x7B | ⚡⚡⚡ | Long documents (32K ctx) |
| 🔵 Gemma 2 9B | ⚡⚡⚡ | Google's model |

Add your own via 🔑 API: OpenAI · Anthropic Claude · OpenRouter · DeepSeek · Together AI · Mistral · Ollama · LM Studio · any OpenAI-compatible endpoint.

---

## 🔧 23 MCP Tools (Detailed Catalog)

Every tool is exposed as a real MCP tool (JSON-RPC over stdio) and the chatbot can invoke them mid-conversation. They are grouped into 8 modules under `mcp_tools/`:

| Category | Tool | Description |
|----------|------|-------------|
| 🧮 Basic | `calculator` | Evaluates math expressions with `+ − × ÷ ^ ( )` plus `sqrt`, `sin`, `cos`, `log`. Restricted globals — no `eval` of arbitrary code. |
| | `get_datetime` | Current date/time, optional `timezone` (e.g. `Asia/Taipei`). |
| | `web_search` | DuckDuckGo HTML scraping; returns title + snippet + URL × N. |
| | `get_weather` | Open-Meteo (no key); returns temp / humidity / wind for a city. |
| 🎨 Generation | `generate_image` | Pollinations.ai — 8 styles, returns image saved to `static/uploads/`. |
| 📁 Filesystem | `read_file` | Reads any file under `safe_workspace/`. Path traversal blocked. |
| | `write_file` | Writes file under `safe_workspace/`. |
| | `list_directory` | Lists entries with size / mtime. |
| | `search_files` | Glob-pattern file search. |
| 🌐 Web | `fetch_url` | Fetches HTML, strips tags, returns first 5000 chars. |
| | `github_search_repos` | GitHub Search API — top repos for a query. |
| | `github_read_file` | Reads a file from a public GitHub repo. |
| | `youtube_transcript` | Pulls auto-caption transcript for a YouTube video ID. |
| 📚 Academic | `arxiv_search` | arXiv abstract API — title / authors / abstract × N. |
| | `wikipedia_search` | Wikipedia REST summary endpoint. |
| 💹 Finance | `stock_price` | Yahoo Finance — current price, change %, volume. |
| | `crypto_price` | CoinGecko — current price + 24h change. |
| 💻 Code | `execute_python` | Sandboxed Python with auto matplotlib capture. |
| 📝 Notion | `notion_search` | Full-text search across the integration's accessible pages. |
| | `notion_list_pages` | Returns hierarchical list of pages with parent IDs. |
| | `notion_create_page` | Creates a page under a parent. |
| | `notion_append_to_page` | Appends markdown content to an existing page. |
| | `notion_query_database` | Filters/sorts a Notion database. |

You can also test any tool standalone via the **🔧 工具** button in the bottom toolbar — it shows the JSON schema and lets you fill arguments directly.

---

## 🧬 Architecture

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full diagram. High-level flow:

```
Browser → Flask /chat/stream
            ├─→ memory.MemoryManager      (SQLite, auto-injected per turn)
            ├─→ router.route              (vision/fast/long-ctx/default)
            ├─→ providers.get_client      (Groq built-in OR user-added)
            └─→ tools.agentic_stream      (multi-round Groq function calling)
                      │
                      ▼
                mcp_client.call_tool      (sync ↔ async bridge)
                      │  JSON-RPC over stdio
                      ▼
                mcp_server.py             (subprocess, 23 tools / 8 modules)
```

---

## 🗂️ Project Structure

```
GenAI_LLM1/
├── app.py                  # Flask routes & API endpoints
├── chatbot.py              # Built-in Groq model list
├── memory.py               # 🧠 Long-term memory (SQLite + extractor)
├── router.py               # ⚡ Auto model routing
├── tools.py                # 🔧 Tool defs + agentic loop + slim fallback
├── providers.py            # 🔑 Multi-provider client manager
├── analytics.py            # 📊 Dashboard data computations
├── mcp_server.py           # 🔌 MCP server (stdio JSON-RPC)
├── mcp_client.py           # 🔌 MCP client (sync/async bridge)
├── mcp_tools/              # 8 tool modules · 23 tools
│   ├── basic.py            (calc / datetime / search / weather)
│   ├── image_gen.py        (Pollinations.ai · 8 styles)
│   ├── filesystem.py       (sandboxed read/write/list/search)
│   ├── web.py              (fetch / GitHub / YouTube)
│   ├── academic.py         (arXiv / Wikipedia)
│   ├── finance.py          (Yahoo stocks / CoinGecko)
│   ├── code_exec.py        (sandboxed Python · matplotlib)
│   └── notion_tools.py     (search · list · create · append · query DB)
├── templates/
│   ├── index.html          # Main chat UI (~2900 lines)
│   └── dashboard.html      # Analytics dashboard
├── static/
│   ├── style.css           # Glassmorphism theme
│   └── uploads/            # User images + AI-generated images
└── docs/
    ├── ARCHITECTURE.md     # System architecture diagram
    ├── ARCHITECTURE.pdf    # Same, A4 export
    └── SYSTEM_INTRODUCTION.txt # 1-page system intro for assignment
```

Excluded from git: `.env` · `providers.json` · `lab2.db` · `conversations*.json` · `static/uploads/*` · `*.log` · `*.exe`

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
| Backend | Python 3.10 · Flask · SQLite · threading (background extractor) |
| AI | Groq API (LPU inference) · OpenAI-compatible providers |
| MCP | Official `mcp` Python SDK · stdio transport · JSON-RPC |
| Frontend | Vanilla JS · Server-Sent Events · Chart.js · marked.js · highlight.js · KaTeX · Mermaid.js |
| Image | Pollinations.ai (free, no key) |
| Web data | DuckDuckGo · GitHub Search · arXiv · Wikipedia · Open-Meteo · CoinGecko · Yahoo Finance |
| Analytics ML | Scikit-learn (TF-IDF · KMeans · cosine similarity) |

---

## 🛡️ Robustness Engineering

Notable failure modes the system handles gracefully:

- **Groq free-tier TPM limits.** When a 17K-token request hits 12K TPM, [`tools.agentic_stream()`](tools.py) builds a **slim retry**: drops the tool schemas + base behaviour, but **preserves the memory block**, then routes to `llama-3.1-8b-instant`. Memory recall still works under rate-limit conditions.
- **Malformed tool calls from Llama.** Groq sometimes returns "Failed to call a function" when 70B emits invalid tool-call JSON. Same slim-retry path handles this — user gets an answer, never a hard error.
- **MCP subprocess crash.** `LOCAL_TOOLS` provides a 4-tool fallback so chat keeps working.
- **Mid-stream errors.** Both pre-stream and mid-stream paths are guarded — we don't lose the conversation if Groq sends an error chunk halfway through.
- **CJK-blind tokeniser.** The memory tokeniser uses bigrams for CJK and word-split for ASCII, so Chinese queries match stored Chinese memories.
- **AI suggestion poisoning.** Memory extraction sees only `role=='user'` turns, so the model never confuses its own enumerations ("比如：香蕉、橙子…") with user preferences.

---

## 🐛 Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Model dropdown shows just `v` chevron | JS error blocking init | Check browser DevTools → Console for red errors |
| Modal text invisible (white-on-white) | Missing CSS variables | Pull latest — fixed in commit defining `--bg-primary` |
| `GROQ_API_KEY not set` | `.env` missing | Create `.env` with `GROQ_API_KEY=gsk_...` |
| MCP tools return "fallback" | MCP server not started | Check `mcp_server.log` for errors |
| Notion tools fail | `NOTION_TOKEN` missing OR page not shared with integration | Share the target page from Notion's `...` → Connections menu |
| Image upload fails | File over 10 MB | Compress or use a smaller image |
| 70B "no response" with tools enabled | TPM rate-limit + tool-call failure | Pull latest — slim fallback to 8B handles it |

---

<div align="center">

Made with ❤️ · MIT License · Lab 2 v2.0.0

</div>
