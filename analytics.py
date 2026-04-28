"""
Conversation analytics — token trends, model usage, heatmap, topic
clustering, similarity matrix, word frequency, latency stats.

Reads from `conversations.json` (chat history) and `lab2.db` (memory,
tool_calls table).
"""
import json
import math
import re
import os
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta


CONVERSATIONS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "conversations.json")
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lab2.db")


_STOPWORDS = {
    "the", "is", "are", "a", "an", "of", "to", "in", "and", "or", "for",
    "on", "with", "i", "you", "me", "my", "your", "we", "us", "it", "that",
    "this", "what", "how", "do", "does", "from", "by", "at", "as", "be",
    "been", "have", "has", "had", "will", "would", "should", "can", "could",
    "了", "嗎", "呢", "的", "在", "是", "我", "你", "他", "和", "與", "或",
    "也", "還", "但", "因為", "所以", "可以", "請", "讓", "把", "給", "個",
    "一", "下", "這", "那", "什麼", "為什麼", "怎麼", "嗎", "呢", "用", "做",
    "幫我", "可以", "需要", "想要",
}


def _load_conversations() -> dict:
    if not os.path.exists(CONVERSATIONS_FILE):
        return {}
    try:
        with open(CONVERSATIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 3)


def _msg_text(m) -> str:
    c = m.get("content", "") if isinstance(m, dict) else ""
    if isinstance(c, list):
        return " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    return str(c)


def overview() -> dict:
    convs = _load_conversations()
    total_convs = len(convs)
    total_msgs = sum(len(c.get("messages", [])) for c in convs.values())
    in_tokens = 0
    out_tokens = 0
    for c in convs.values():
        for m in c.get("messages", []):
            tok = _approx_tokens(_msg_text(m))
            if m.get("role") == "user":
                in_tokens += tok
            elif m.get("role") == "assistant":
                out_tokens += tok
    total_tokens = in_tokens + out_tokens

    tool_calls = 0
    if os.path.exists(DB_PATH):
        try:
            c = sqlite3.connect(DB_PATH)
            cur = c.execute("SELECT COUNT(*) FROM tool_calls").fetchone()
            tool_calls = cur[0] if cur else 0
            c.close()
        except Exception:
            tool_calls = 0

    return {
        "total_conversations": total_convs,
        "total_messages": total_msgs,
        "total_tokens": total_tokens,
        "input_tokens": in_tokens,
        "output_tokens": out_tokens,
        "tool_calls": tool_calls,
    }


def token_trend(days: int = 14) -> dict:
    """Daily token in/out over the last N days."""
    convs = _load_conversations()
    today = datetime.now().date()
    bins = {(today - timedelta(days=i)).isoformat(): {"in": 0, "out": 0}
            for i in range(days - 1, -1, -1)}

    for c in convs.values():
        try:
            d = datetime.fromisoformat(c.get("created_at", "")).date()
        except Exception:
            continue
        if (today - d).days >= days:
            continue
        key = d.isoformat()
        if key not in bins:
            continue
        for m in c.get("messages", []):
            tok = _approx_tokens(_msg_text(m))
            if m.get("role") == "user":
                bins[key]["in"] += tok
            elif m.get("role") == "assistant":
                bins[key]["out"] += tok

    return {
        "labels": list(bins.keys()),
        "input": [v["in"] for v in bins.values()],
        "output": [v["out"] for v in bins.values()],
    }


def model_distribution() -> dict:
    convs = _load_conversations()
    counter = Counter()
    for c in convs.values():
        m = c.get("model", "unknown") or "unknown"
        counter[m] += 1
    pairs = counter.most_common()
    return {
        "labels": [p[0] for p in pairs],
        "values": [p[1] for p in pairs],
    }


def heatmap(days: int = 365) -> dict:
    """365-day calendar heatmap of conversation activity."""
    convs = _load_conversations()
    today = datetime.now().date()
    counts = defaultdict(int)
    for c in convs.values():
        try:
            d = datetime.fromisoformat(c.get("created_at", "")).date()
        except Exception:
            continue
        delta = (today - d).days
        if 0 <= delta < days:
            counts[d.isoformat()] += 1
    series = []
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        series.append({"date": d, "count": counts.get(d, 0)})
    return {"days": series, "max": max((s["count"] for s in series), default=0)}


def tool_ranking() -> dict:
    """Tool call frequency from lab2.db.tool_calls (created on demand)."""
    if not os.path.exists(DB_PATH):
        return {"labels": [], "values": []}
    try:
        c = sqlite3.connect(DB_PATH)
        c.execute("""
            CREATE TABLE IF NOT EXISTS tool_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_name TEXT,
                args_json TEXT,
                result_excerpt TEXT,
                conv_id TEXT,
                timestamp TEXT,
                latency_ms INTEGER
            )
        """)
        rows = c.execute(
            "SELECT tool_name, COUNT(*) FROM tool_calls GROUP BY tool_name ORDER BY 2 DESC"
        ).fetchall()
        c.close()
        return {
            "labels": [r[0] for r in rows],
            "values": [r[1] for r in rows],
        }
    except Exception:
        return {"labels": [], "values": []}


def _tokenize(text: str) -> list[str]:
    text = re.sub(r"[^\w一-鿿]+", " ", text.lower())
    return [t for t in text.split() if t and t not in _STOPWORDS and len(t) > 1]


def word_frequency(top_n: int = 30) -> list[dict]:
    convs = _load_conversations()
    counter = Counter()
    for c in convs.values():
        for m in c.get("messages", []):
            if m.get("role") == "user":
                counter.update(_tokenize(_msg_text(m)))
    return [{"word": w, "count": n} for w, n in counter.most_common(top_n)]


def topic_clusters(top_k: int = 8) -> list[dict]:
    """Lightweight TF-IDF + greedy clustering. Returns N topic groups."""
    convs = _load_conversations()
    docs = []
    for cid, c in convs.items():
        text = " ".join(_msg_text(m) for m in c.get("messages", [])
                        if m.get("role") == "user")
        if text.strip():
            docs.append({"id": cid, "title": c.get("title", "")[:30],
                         "tokens": _tokenize(text)})
    if not docs:
        return []

    # Document frequency
    df = Counter()
    for d in docs:
        df.update(set(d["tokens"]))
    N = len(docs)

    # TF-IDF vectors
    for d in docs:
        tf = Counter(d["tokens"])
        d["vec"] = {t: (count / max(1, len(d["tokens"])))
                       * math.log((N + 1) / (df[t] + 1))
                       for t, count in tf.items()}

    # Simple greedy: pick top keyword for each doc as cluster label.
    cluster_map = defaultdict(list)
    for d in docs:
        if not d["vec"]:
            label = "其他"
        else:
            top = max(d["vec"].items(), key=lambda x: x[1])
            label = top[0]
        cluster_map[label].append(d["title"])

    # Sort clusters by size, take top_k
    sorted_clusters = sorted(cluster_map.items(),
                              key=lambda x: -len(x[1]))[:top_k]
    return [
        {"label": label, "count": len(titles), "samples": titles[:3]}
        for label, titles in sorted_clusters
    ]


def _cosine(a: dict, b: dict) -> float:
    keys = set(a) & set(b)
    if not keys:
        return 0.0
    num = sum(a[k] * b[k] for k in keys)
    da = math.sqrt(sum(v * v for v in a.values()))
    db = math.sqrt(sum(v * v for v in b.values()))
    return num / (da * db) if da and db else 0.0


def similarity_top(top_n: int = 5) -> list[dict]:
    """Top-N most similar conversation pairs by TF-IDF cosine."""
    convs = _load_conversations()
    docs = []
    for cid, c in convs.items():
        text = " ".join(_msg_text(m) for m in c.get("messages", [])
                        if m.get("role") == "user")
        toks = _tokenize(text)
        if toks:
            docs.append({"id": cid, "title": c.get("title", "")[:25] or cid[:6], "toks": toks})
    if len(docs) < 2:
        return []

    df = Counter()
    for d in docs:
        df.update(set(d["toks"]))
    N = len(docs)
    for d in docs:
        tf = Counter(d["toks"])
        d["vec"] = {t: (count / max(1, len(d["toks"])))
                       * math.log((N + 1) / (df[t] + 1))
                       for t, count in tf.items()}

    pairs = []
    for i in range(len(docs)):
        for j in range(i + 1, len(docs)):
            sim = _cosine(docs[i]["vec"], docs[j]["vec"])
            if sim > 0.05:
                pairs.append({
                    "a": docs[i]["title"], "b": docs[j]["title"],
                    "score": round(sim, 3),
                })
    pairs.sort(key=lambda x: -x["score"])
    return pairs[:top_n]


def latency_stats() -> dict:
    """Average response time per model (estimated from message count)."""
    if not os.path.exists(DB_PATH):
        return {"labels": [], "values": []}
    try:
        c = sqlite3.connect(DB_PATH)
        c.execute("""
            CREATE TABLE IF NOT EXISTS tool_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_name TEXT,
                args_json TEXT,
                result_excerpt TEXT,
                conv_id TEXT,
                timestamp TEXT,
                latency_ms INTEGER
            )
        """)
        # If we have latency_ms recorded, avg by tool (proxy for "response speed")
        rows = c.execute(
            "SELECT tool_name, AVG(latency_ms) FROM tool_calls "
            "WHERE latency_ms IS NOT NULL GROUP BY tool_name "
            "ORDER BY 2 DESC LIMIT 10"
        ).fetchall()
        c.close()
        return {
            "labels": [r[0] for r in rows],
            "values": [int(r[1] or 0) for r in rows],
        }
    except Exception:
        return {"labels": [], "values": []}


def memory_stats() -> dict:
    """Stats about long-term memory."""
    if not os.path.exists(DB_PATH):
        return {"total": 0, "by_category": {}}
    try:
        c = sqlite3.connect(DB_PATH)
        rows = c.execute(
            "SELECT category, COUNT(*) FROM memories GROUP BY category"
        ).fetchall()
        total = sum(r[1] for r in rows)
        c.close()
        return {"total": total, "by_category": {r[0]: r[1] for r in rows}}
    except Exception:
        return {"total": 0, "by_category": {}}


def record_tool_call(tool_name: str, args: dict, result: str,
                     conv_id: str = None, latency_ms: int = None):
    """Insert a tool call record into the analytics DB."""
    try:
        c = sqlite3.connect(DB_PATH)
        c.execute("""
            CREATE TABLE IF NOT EXISTS tool_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_name TEXT,
                args_json TEXT,
                result_excerpt TEXT,
                conv_id TEXT,
                timestamp TEXT,
                latency_ms INTEGER
            )
        """)
        c.execute(
            "INSERT INTO tool_calls(tool_name, args_json, result_excerpt, "
            "conv_id, timestamp, latency_ms) VALUES (?,?,?,?,?,?)",
            (
                tool_name,
                json.dumps(args, ensure_ascii=False)[:500],
                str(result)[:500],
                conv_id,
                datetime.now().isoformat(),
                latency_ms,
            ),
        )
        c.commit()
        c.close()
    except Exception as e:
        print(f"[analytics] record failed: {e}")
