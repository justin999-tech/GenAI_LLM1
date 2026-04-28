# System Architecture

GenAI LLM Chatbot v2 — the 5 HW02 required features (⚡ Auto Routing, 👁 Multimodal,
🧠 Long-term Memory, 🔧 Tool Use + MCP, ✦ Other) shown as labeled subsystems.

```
┌─────────────────────────────────────────────────────────────────────┐
│                          USER  (Browser)                            │
└──────────────┬───────────────────────────────────┬──────────────────┘
               │                                   │
          Chat / Drag-drop                    Analytics
               │                                   │
               ▼                                   ▼
┌─────────────────────────────────┐   ┌──────────────────────────┐
│   index.html  (SSE streaming)   │   │     dashboard.html       │
│   Glass UI · Artifact preview   │   │     9 real-time charts   │
└──────────────┬──────────────────┘   └─────────────┬─────────────┘
               │                                    │
               ▼                                    │
   ┌═══════════════════════════════════════════════ │═══════════════┐
   ║         FLASK BACKEND  (app.py · /chat/stream) │               ║
   ║                                                ▼               ║
   ║   ╭─────────────╮ ╭─────────────╮ ╭──────────────────────╮     ║
   ║   │  AUTO       │ │  MULTI-     │ │  LONG-TERM MEMORY    │     ║
   ║   │   ROUTING   │ │   MODAL     │ │   memory.py + SQLite │     ║
   ║   │ router.py   │ │  vision msg │ │  auto extract/inject │     ║
   ║   ╰─────┬───────╯ ╰─────┬───────╯ ╰──────────┬───────────╯     ║
   ║         │               │                    │                 ║
   ║   ╭─────┴───────────────┴────────────────────┴───────────╮     ║
   ║   │  TOOL USE + MCP   (tools.agentic_stream)             │     ║
   ║   ╰─────┬────────────────────────────────────────────────╯     ║
   ║         │                                                      ║
   ║   ╭─────┴───────────────────────────────────────────────╮      ║
   ║   │  OTHER:  Code-exec · Image-gen · Notion ·           │      ║
   ║   │           Multi-provider · Dashboard · Artifacts    │      ║
   ║   ╰─────────────────────────────────────────────────────╯      ║
   ║                                                                ║
   ║   providers.py  →  9 OpenAI-compatible backends                ║
   ╚════════╤═══════════════════════════════════════════════════════╝
            │                  ╱│╲ JSON-RPC over stdio             │
            │                   │                                  │
            ▼                   ▼                                  │
   ┌──────────────┐   ┌───────────────────────────────────────┐    │
   │  Groq LPU    │   │   MCP SERVER (mcp_server.py)          │    │
   │  OpenAI      │   │   ┌──────────┬──────────┬──────────┐  │    │
   │  Claude      │   │   │ basic(4) │ web(4)   │ notion(5)│  │    │
   │  OpenRouter  │   │   │ image    │ academic │ finance  │  │    │
   │  …           │   │   │ filesys  │ code-exec(Python)   │  │    │
   │              │   │   └──────────┴──────────┴──────────┘  │    │
   │              │   │            (23 MCP tools)             │    │
   └──────────────┘   └─────────────────┬─────────────────────┘    │
                                        │                          │
   ┌────────────────────────────────────┴────────────────────────┐ │
   │  EXTERNAL APIs                                              │ │
   │  Notion · DuckDuckGo · GitHub · arXiv · Wikipedia ·         │ │
   │  Yahoo Finance · CoinGecko · Open-Meteo · Pollinations.ai   │ │
   └─────────────────────────────────────────────────────────────┘ │
                                                                   │
   ┌────────────────────────────────────┐                          │
   │ STORAGE                            │ ◄────────────────────────┘
   │ lab2.db (memories)                 │
   │ conversations.json (chat history)  │
   │ static/uploads/ (user + AI images) │
   └────────────────────────────────────┘
```
