"""
Long-term memory manager backed by SQLite.

Stores user facts/preferences/instructions across conversations and
provides keyword-based retrieval for system-prompt injection.
"""
import sqlite3
import uuid
import json
import re
import threading
from datetime import datetime
from typing import List, Dict, Optional


class MemoryManager:
    def __init__(self, db_path: str = "lab2.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _init_db(self):
        with self._lock, self._conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS memories (
                    id           TEXT PRIMARY KEY,
                    content      TEXT NOT NULL,
                    category     TEXT DEFAULT 'fact',
                    source_conv  TEXT,
                    created_at   TEXT NOT NULL,
                    updated_at   TEXT NOT NULL,
                    access_count INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS conversation_meta (
                    conv_id    TEXT PRIMARY KEY,
                    summary    TEXT,
                    tags       TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_mem_category ON memories(category);
                CREATE INDEX IF NOT EXISTS idx_mem_created  ON memories(created_at);
            """)

    # ---- CRUD ---------------------------------------------------------

    def add(self, content: str, category: str = "fact",
            source_conv: Optional[str] = None) -> str:
        content = (content or "").strip()
        if not content:
            raise ValueError("memory content cannot be empty")
        if self._duplicate_exists(content):
            return ""
        mid = str(uuid.uuid4())
        now = datetime.now().isoformat()
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO memories(id,content,category,source_conv,created_at,updated_at)"
                " VALUES(?,?,?,?,?,?)",
                (mid, content, category, source_conv, now, now),
            )
        return mid

    def _duplicate_exists(self, content: str) -> bool:
        norm = content.strip().lower()
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT 1 FROM memories WHERE LOWER(content)=? LIMIT 1", (norm,)
            ).fetchone()
            return row is not None

    def list_all(self) -> List[Dict]:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT * FROM memories ORDER BY created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def delete(self, memory_id: str) -> bool:
        with self._lock, self._conn() as c:
            cur = c.execute("DELETE FROM memories WHERE id=?", (memory_id,))
            return cur.rowcount > 0

    def clear_all(self) -> int:
        with self._lock, self._conn() as c:
            cur = c.execute("DELETE FROM memories")
            return cur.rowcount

    # ---- Retrieval ----------------------------------------------------

    _STOPWORDS = {
        "the", "is", "are", "a", "an", "of", "to", "in", "and", "or", "for",
        "on", "with", "i", "you", "me", "my", "your", "we", "us", "it",
        "this", "that", "what", "how", "do", "does", "了", "嗎", "呢",
    }

    def _tokenize(self, text: str) -> List[str]:
        """Hybrid tokenizer for mixed CJK + Latin text.

        - ASCII words split on whitespace/punctuation as before.
        - CJK characters are emitted as 2-char sliding bigrams (and singles),
          so Chinese queries like "我喜歡吃什麼食物" can match stored
          memories like "喜歡吃香菜" via the shared bigrams 喜歡/歡吃/吃...
        """
        text = (text or "").lower()
        ascii_text = re.sub(r"[^a-z0-9_\s]+", " ", text)
        ascii_toks = [t for t in ascii_text.split()
                      if t and t not in self._STOPWORDS and len(t) > 1]

        cjk_chars = re.findall(r"[一-鿿]", text)
        cjk_toks = []
        for ch in cjk_chars:
            if ch not in self._STOPWORDS:
                cjk_toks.append(ch)
        # Bigrams catch most Chinese phrases without a real segmenter.
        bigrams = []
        cjk_run = re.findall(r"[一-鿿]+", text)
        for run in cjk_run:
            for i in range(len(run) - 1):
                bg = run[i:i+2]
                if bg not in self._STOPWORDS:
                    bigrams.append(bg)

        return ascii_toks + bigrams + cjk_toks

    def search(self, query: str, limit: int = 5) -> List[Dict]:
        """Return memories most relevant to the query.

        Falls back to recent + frequently-accessed memories when the query
        has no token overlap, so the chatbot keeps baseline awareness.
        """
        tokens = self._tokenize(query)
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT * FROM memories").fetchall()
            if not rows:
                return []

            scored = []
            for r in rows:
                txt = r["content"].lower()
                hits = sum(1 for t in tokens if t in txt) if tokens else 0
                scored.append((hits, dict(r)))

            # Highest hits first, then most-accessed, then newest.
            scored.sort(
                key=lambda x: (
                    x[0],
                    x[1].get("access_count") or 0,
                    x[1]["created_at"],
                ),
                reverse=True,
            )
            top = [m for _, m in scored[:limit]]

            for m in top:
                c.execute(
                    "UPDATE memories SET access_count=access_count+1 WHERE id=?",
                    (m["id"],),
                )
            return top

    def build_context(self, query: str, limit: int = 5) -> str:
        """Return a formatted memory block for system-prompt injection."""
        memories = self.search(query, limit=limit)
        if not memories:
            return ""
        lines = ["[已知使用者資訊 / Known User Context]"]
        for m in memories:
            cat = m.get("category", "fact")
            lines.append(f"- ({cat}) {m['content']}")
        return "\n".join(lines)

    # ---- Auto-extraction ----------------------------------------------

    def extract_and_store(self, client, conv_id: str,
                          recent_messages: List[Dict]) -> List[str]:
        """Use a fast LLM call to extract user facts from recent dialogue.

        Only the USER's own turns are forwarded to the extractor — earlier
        revisions also passed assistant replies, and the small extractor
        model would mistake the assistant's suggestions ("比如：香蕉、橙子…")
        for user preferences, polluting memory with fruits the user never
        mentioned.
        """
        if not recent_messages:
            return []
        user_turns = [
            m["content"] for m in recent_messages
            if m.get("role") == "user" and isinstance(m.get("content"), str)
            and m["content"].strip()
        ]
        if not user_turns:
            return []
        dialogue = "\n".join(f"- {t}" for t in user_turns)[:4000]

        sys = (
            "你是一個記憶提取器。輸入是『使用者本人』寫的訊息（已過濾掉助理回覆）。"
            "請從這些訊息中抽出值得長期記住的個人事實、偏好、指令。\n\n"
            "嚴格規則：\n"
            "1. 只記錄使用者**明確、肯定**陳述的事 — "
            "「我喜歡 X」「我是 Y」「我用 Z」這種句型才算。\n"
            "2. 反問、假設、列舉選項都不算。\n"
            "   反例：「我應該喜歡哪個？」「比如香蕉、橙子」→ 不要抽。\n"
            "3. 一次性問題不算（例如「2+2=?」不要記成事實）。\n"
            "4. 抽出的 content 用第三人稱簡述，例如：\n"
            "   輸入「我喜歡吃西瓜」→ content「喜歡吃西瓜」, category「preference」。\n"
            "   輸入「我用 PyTorch」→ content「使用 PyTorch」, category「fact」。\n"
            "5. 沒有值得記的就回傳 []。\n\n"
            "回應**只能**是 JSON 陣列，每項 "
            "{\"content\": \"...\", \"category\": \"fact|preference|instruction\"}。"
            "不要輸出任何說明文字。"
        )
        try:
            resp = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": sys},
                    {"role": "user",
                     "content": f"使用者本人的訊息：\n{dialogue}"},
                ],
                max_tokens=400,
                temperature=0.0,
            )
            raw = resp.choices[0].message.content.strip()
        except Exception:
            return []

        # Extract first JSON array from the response.
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            return []
        try:
            items = json.loads(match.group(0))
        except Exception:
            return []

        added = []
        for it in items:
            if not isinstance(it, dict):
                continue
            content = (it.get("content") or "").strip()
            cat = (it.get("category") or "fact").strip().lower()
            if cat not in {"fact", "preference", "instruction"}:
                cat = "fact"
            if content:
                try:
                    mid = self.add(content, category=cat, source_conv=conv_id)
                    if mid:
                        added.append(mid)
                except Exception:
                    pass
        return added
