# GenAI LLM Chatbot v2 — System Introduction

**Author:** Justin · **Course:** GenAI Lab 2 · **GitHub:** <https://github.com/justin999-tech/GenAI_LLM1>

---

## Overview

An agentic web chatbot that extends HW01 with the five v2 features required by
the assignment, plus a set of user-facing extras. The system is a Python Flask
backend serving a vanilla-JS glassmorphism frontend, paired with an isolated
**MCP (Model Context Protocol) server** subprocess that exposes 23 real tools
to the model. All five HW02 requirements are implemented as first-class
subsystems, not surface-level demos.

## HW02 Required Features

| # | Feature | Implementation |
|---|---------|---------------|
| 1 | **Auto Routing between models** | [`router.py`](../router.py) inspects every request (image attached? "fast"/short? long context? math?) and picks one of 5 Groq models — Llama 3.3 70B (default), Llama 3.1 8B (fast), Llama 4 Scout (vision), Mixtral 8×7B (long ctx), Gemma 2 9B. Auto Routing fires when the user picks `⚡ 自動路由` or uploads an image. |
| 2 | **Multimodal** | Drag-and-drop image upload in the chat box → file is base64-encoded and sent inside an OpenAI-format `image_url` content array → routed to **Llama 4 Scout** vision model. The image is also persisted to `static/uploads/` so re-opening the conversation re-renders it. |
| 3 | **Long-term Memory** | [`memory.py`](../memory.py) backs an SQLite store of facts, preferences, and instructions. After every user turn, an 8B background thread runs `extract_and_store()` to harvest new facts (USER turns only — assistant suggestions are filtered out). Before every new turn, `build_context()` searches with hybrid CJK-bigram + ASCII tokenization and injects the top-5 relevant memories into the system prompt. Manageable via Ctrl+M. |
| 4 | **Tool Use + MCP** | A standalone `mcp_server.py` subprocess speaks **JSON-RPC over stdio** using the official `mcp` Python SDK. It exposes 23 tools across 8 modules. The backend's `tools.agentic_stream()` runs a multi-round function-calling loop, routing every tool invocation through `mcp_client.call_tool()`. If MCP is offline, it falls back to local Python implementations. |
| 5 | **Other Useful Functions** | (a) Multi-provider — OpenAI/Claude/OpenRouter/etc via `providers.py`; (b) Sandboxed Python interpreter with auto matplotlib capture; (c) Free image generation via Pollinations.ai (8 styles); (d) Notion API integration (search, create, append, query DB); (e) Inline artifact preview for HTML/SVG/Mermaid; (f) Analytics dashboard — 9 real-time charts on `/dashboard`. |

## 23 MCP Tools

| Category | Tools |
|----------|-------|
| Basic | `calculator` · `get_datetime` · `web_search` · `get_weather` |
| Generation | `generate_image` (8 styles) |
| Filesystem | `read_file` · `write_file` · `list_directory` · `search_files` (sandboxed) |
| Web | `fetch_url` · `github_search_repos` · `github_read_file` · `youtube_transcript` |
| Academic | `arxiv_search` · `wikipedia_search` |
| Finance | `stock_price` (Yahoo) · `crypto_price` (CoinGecko) |
| Code | `execute_python` (sandboxed, captures matplotlib) |
| Notion | `notion_search` · `notion_list_pages` · `notion_create_page` · `notion_append_to_page` · `notion_query_database` |

## Robustness Highlights

- **Rate-limit fallback** — Groq free-tier TPM is 12000. When a 17000-token
  request hits a tool-call failure or 429, the loop drops the giant tool
  schemas + base behaviour but **preserves the memory block**, then retries
  on `llama-3.1-8b-instant`.
- **CJK memory search** — Custom hybrid tokenizer emits bigrams for Chinese,
  enabling matches that would fail under whitespace splitting.
- **Memory hygiene** — Extractor sees only `role=='user'` turns, so the model
  never mistakes an AI-listed example ("比如：香蕉、橙子…") for a user
  preference. Dedupe on content prevents duplicates from repeated turns.

## Tech Stack

Python 3.10 · Flask · SQLite · official `mcp` SDK (stdio transport) · Groq API ·
Vanilla JS · Chart.js · marked.js · highlight.js · KaTeX · Mermaid.js · Pollinations.ai
