<div align="center">

# ✦ GenAI LLM Chatbot

**A sleek, feature-rich AI chatbot powered by Groq & Flask**

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.x-000000?style=for-the-badge&logo=flask&logoColor=white)
![Groq](https://img.shields.io/badge/Groq-API-F55036?style=for-the-badge&logo=groq&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-22c55e?style=for-the-badge)

</div>

---

## 🤖 Available Models

| Model | Speed | Context | Best For |
|-------|-------|---------|----------|
| 🥇 Llama 3.3 70B | ⚡⚡ | 128k | General use — most capable |
| 🚀 Llama 3.1 8B  | ⚡⚡⚡⚡ | 128k | Quick answers, low latency |
| 📖 Mixtral 8x7B  | ⚡⚡⚡ | 32k | Long documents |
| 🔵 Gemma 2 9B    | ⚡⚡⚡ | 8k | Google's model |

---

## ✨ Features

### 💬 Chat
- **Real-time streaming** — responses appear word by word
- **Conversation history** — saved locally, resume any time
- **Rename / delete** conversations from the sidebar
- **Regenerate** the last AI reply with one click
- **Custom system prompt** — give the AI a persona or instructions
- **Voice input** — speak your message (Chinese supported)

### 🛠️ Productivity
- **5 Chat modes** — 💬 Chat / 💻 Code / 📝 Write / 🔍 Analyze / 🌐 Translate
- **Prompt Library** — built-in collection of useful prompts `Ctrl+P`
- **Diagram generator** — AI-generated Mermaid diagrams

  > Flowchart · Sequence · ER · Class · State · Gantt

- **HTML preview** — live render AI-generated webpages in a side panel
- **Notes workspace** — take notes while chatting `Ctrl+E`
- **Export conversation** — download your chat history

### 🎨 UI / UX
- 🌙 **Dark / Light mode** toggle
- 🔍 **Conversation search** `Ctrl+/`
- **Markdown rendering** — bold, italic, tables, code blocks
- **Syntax highlighting** via highlight.js
- **Math equations** via KaTeX (`$E=mc^2$` just works)
- **Keyboard shortcuts** throughout the app

<details>
<summary>⌨️ Keyboard Shortcuts</summary>

| Shortcut | Action |
|----------|--------|
| `Ctrl + N` | New conversation |
| `Ctrl + E` | Open notes workspace |
| `Ctrl + P` | Open prompt library |
| `Ctrl + ,` | Open settings |
| `Ctrl + /` | Search conversations |
| `Enter` | Send message |
| `Shift + Enter` | New line |

</details>

---

## 🚀 Quick Start

### 1. Clone

```bash
git clone https://github.com/justin999-tech/GenAI_LLM1.git
cd GenAI_LLM1
```

### 2. Install dependencies

```bash
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

### 3. Set your API key

Create a `.env` file:

```env
GROQ_API_KEY=your_api_key_here
```

> Get a **free** API key at [console.groq.com](https://console.groq.com/) — no credit card required.

### 4. Run

```bash
python app.py
```

Open `http://127.0.0.1:5000` in your browser.

---

## 🗂️ Project Structure

```
GenAI_LLM1/
├── app.py              # Flask routes & API endpoints
├── chatbot.py          # Groq client & chat logic
├── requirements.txt    # Python dependencies
├── .env                # API key (not committed)
├── templates/
│   └── index.html      # Frontend UI
└── static/
    └── style.css       # Styles
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python · Flask |
| AI | Groq API (LPU inference) |
| Frontend | HTML · CSS · Vanilla JS |
| Markdown | marked.js |
| Syntax highlight | highlight.js |
| Math | KaTeX |
| Diagrams | Mermaid.js |

---

<div align="center">

Made with ❤️ · MIT License

</div>
