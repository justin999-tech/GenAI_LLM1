"""
Auto model router.

Picks the best Groq model for a given message + context. Rule-based,
no extra API calls — keeps response latency low.
"""
import re
from typing import Dict, List, Optional


VISION_MODEL    = "meta-llama/llama-4-scout-17b-16e-instruct"
LONG_CTX_MODEL  = "llama-3.3-70b-versatile"  # Groq Mixtral was retired; 70B handles long ctx
FAST_MODEL      = "llama-3.1-8b-instant"
DEFAULT_MODEL   = "llama-3.3-70b-versatile"

# Patterns hint at the message complexity / domain.
_FAST_PATTERNS = [
    r"^(hi|hello|hey|你好|哈囉|嗨|安安)\b",
    r"^(ok|okay|好|是|對|不|沒有|謝謝|thanks)\b",
    r"^(yes|no|yep|nope)$",
]

# Keywords that strongly imply a tool call. We do NOT route these to 8B
# because 8B's 6000 TPM cap can't fit the full 23-tool schema (~12 KB)
# plus the system prompt, so the tools-enabled request gets rejected
# and the slim fallback strips tools — the user then sees "工具不可用".
# Sending tool-likely queries to 70B (12000 TPM) gives much more headroom.
_TOOL_PATTERNS = [
    # Web / search
    r"(查詢|查|查一下|搜尋|搜|google|search|找|找一下|看看)",
    # Weather
    r"(天氣|weather|溫度|下雨|預報)",
    # Stock / crypto / finance
    r"(股價|股票|stock|crypto|比特幣|bitcoin|加密|匯率)",
    # Image generation
    r"(畫一(個|張|幅)|生成.{0,8}(圖|圖片|image)|產生.{0,8}圖|draw|generate.*image)",
    # Code execution / matplotlib
    r"(matplotlib|畫圖|plot|繪製|執行|run.*code|計算)",
    # Notion / files
    r"(notion|notion 頁面|append|append.*page|寫入.*notion)",
    # Academic
    r"(arxiv|wikipedia|wiki|論文|paper)",
    # GitHub / web
    r"(github|repo|repository|youtube|抓取網頁|爬|fetch)",
    # Time / date
    r"(現在(幾點|時間)|今天.*日期|目前時間|today.*date)",
]
_CODE_PATTERNS = [
    r"```",
    r"\bdef\s+\w+\(",
    r"\bclass\s+\w+",
    r"\bfunction\s+\w+",
    r"\bimport\s+\w+",
    r"\b(SELECT|INSERT|UPDATE|DELETE)\s+",
    r"(寫|debug|修|實作|implement|write|create|build|fix)(.{0,30})(程式|code|function|api|script|bug)",
    r"\b(python|javascript|java|c\+\+|rust|golang|sql|html|css)\b",
]
_MATH_PATTERNS = [
    r"\$.+?\$",
    r"\b(integral|derivative|積分|微分|矩陣|matrix)\b",
    r"\\frac|\\int|\\sum",
]


def _approx_tokens(messages: List[Dict]) -> int:
    """Rough token estimate (1 token ~ 3 chars CJK / 4 chars EN)."""
    total = 0
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            total += len(c) // 3
        elif isinstance(c, list):
            for part in c:
                if isinstance(part, dict) and part.get("type") == "text":
                    total += len(part.get("text", "")) // 3
    return total


def route(message: str,
          history: Optional[List[Dict]] = None,
          has_image: bool = False,
          force_tools: bool = False) -> Dict[str, str]:
    """Return {"model": ..., "reason": ...} for the given input."""
    history = history or []
    msg = (message or "").strip()
    lower = msg.lower()

    if has_image:
        return {"model": VISION_MODEL, "reason": "圖像輸入 → Vision 模型"}

    # Force a tool-capable model when caller signals tool use is required.
    if force_tools:
        return {"model": DEFAULT_MODEL, "reason": "需要工具呼叫 → 70B"}

    history_tokens = _approx_tokens(history) + len(msg) // 3
    if history_tokens > 6000:
        return {"model": LONG_CTX_MODEL, "reason": f"長上下文 ({history_tokens} tokens)"}

    for pat in _FAST_PATTERNS:
        if re.search(pat, lower, re.IGNORECASE):
            return {"model": FAST_MODEL, "reason": "簡短問候 → 快速模型 8B"}

    # Tool-likely queries always go to 70B — 8B's TPM can't fit tool schemas.
    for pat in _TOOL_PATTERNS:
        if re.search(pat, msg, re.IGNORECASE):
            return {"model": DEFAULT_MODEL, "reason": "需要工具呼叫 → 70B"}

    if len(msg) < 25 and "?" not in msg and "？" not in msg:
        return {"model": FAST_MODEL, "reason": "短訊息 → 快速模型 8B"}

    for pat in _CODE_PATTERNS:
        if re.search(pat, msg, re.IGNORECASE):
            return {"model": DEFAULT_MODEL, "reason": "程式碼相關 → 70B"}

    for pat in _MATH_PATTERNS:
        if re.search(pat, msg, re.IGNORECASE):
            return {"model": DEFAULT_MODEL, "reason": "數學相關 → 70B"}

    return {"model": DEFAULT_MODEL, "reason": "一般查詢 → 預設 70B"}
