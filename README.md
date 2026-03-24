# GenAI LLM Chatbot

A web-based AI chatbot built with Flask and the Groq API, featuring a clean chat interface with real-time streaming responses and multiple productivity tools.

## Features

### Core Chat
- **Real-time streaming** — AI responses appear word by word, no waiting
- **Multiple AI models** — Switch between 4 models mid-conversation:
  - Llama 3.3 70B (most powerful)
  - Llama 3.1 8B (fastest)
  - Mixtral 8x7B (long context)
  - Gemma 2 9B (Google)
- **Conversation history** — All chats saved locally; resume any time
- **Rename / delete conversations** — Manage your chat history from the sidebar
- **Regenerate response** — Re-generate the last AI reply with one click
- **Custom system prompt** — Set a persona or instructions for the AI

### Productivity Tools
- **5 chat modes** — Chat / Code / Write / Analyze / Translate, each with a preset system prompt
- **Prompt Library** — Built-in collection of useful prompts (Ctrl+P)
- **Diagram generator** — Ask AI to generate Mermaid diagrams (flowchart, sequence, ER, class, state, Gantt)
- **HTML preview** — Live render AI-generated HTML/CSS/JS in a side panel
- **Notes workspace** — Side panel for taking notes while chatting (Ctrl+E)
- **Export conversation** — Download chat history as a file
- **Voice input** — Speak your message (Chinese supported)

### UI / UX
- **Dark / Light mode** toggle
- **Conversation search** — Filter sidebar history by keyword (Ctrl+/)
- **Markdown rendering** — Bold, italic, lists, tables, code blocks
- **Syntax highlighting** — Code blocks highlighted via highlight.js
- **Math rendering** — LaTeX equations rendered via KaTeX
- **Character counter** — Live count of input length
- **Keyboard shortcuts** — Ctrl+N (new chat), Ctrl+E (notes), Ctrl+P (prompt library), Ctrl+, (settings)

## Tech Stack

- **Backend**: Python, Flask
- **AI API**: [Groq](https://groq.com/) (free tier)
- **Frontend**: HTML, CSS, Vanilla JavaScript
- **Libraries**: marked.js (Markdown), highlight.js (syntax), KaTeX (math), Mermaid (diagrams)

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/justin999-tech/GenAI_LLM1.git
cd GenAI_LLM1
```

### 2. Create a virtual environment and install dependencies

```bash
python -m venv venv
venv\Scripts\activate      # Windows
pip install -r requirements.txt
```

### 3. Set up your API key

Create a `.env` file in the project root:

```
GROQ_API_KEY=your_api_key_here
```

Get a free API key at [console.groq.com](https://console.groq.com/)

### 4. Run the app

```bash
python app.py
```

Open your browser and go to `http://127.0.0.1:5000`
