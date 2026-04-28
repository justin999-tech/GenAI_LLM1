"""
Tool definitions and agentic execution loop.

Defines four tools (calculator, datetime, web_search, weather) and an
`agentic_stream` generator that drives a multi-round Groq function-calling
loop and yields SSE-formatted events for the chat endpoint.

Tool execution can be routed through an MCP client when available; if not,
it falls back to local implementations.
"""
import json
import math
import re
import urllib.parse
import urllib.request
from datetime import datetime
from typing import List, Dict, Optional, Callable, Generator


# ---- Tool schemas (OpenAI / Groq function-calling format) ------------

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "Evaluate a mathematical expression. Supports +, -, *, /, **, parentheses, and math functions like sqrt, sin, cos, log.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "The math expression to evaluate, e.g. '2 * (3 + 4)' or 'sqrt(144)'.",
                    }
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_datetime",
            "description": "Get the current date and time, optionally for a specific timezone.",
            "parameters": {
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "Timezone name like 'Asia/Taipei'. Defaults to local time.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for up-to-date information. Use this when the user asks about news, current events, or anything you don't already know.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query.",
                    },
                    "num_results": {
                        "type": "integer",
                        "description": "Number of results to return (1-5).",
                        "default": 3,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the current weather for a city.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "City name, e.g. 'Taipei' or '台北'.",
                    },
                    "units": {
                        "type": "string",
                        "enum": ["metric", "imperial"],
                        "default": "metric",
                    },
                },
                "required": ["city"],
            },
        },
    },
]


# ---- Local tool implementations (used as MCP fallback) ---------------

_SAFE_MATH_NAMES = {
    name: getattr(math, name)
    for name in ("sqrt", "sin", "cos", "tan", "log", "log2", "log10",
                 "exp", "pi", "e", "floor", "ceil", "fabs", "pow")
}
_SAFE_MATH_NAMES["abs"] = abs


def tool_calculator(expression: str) -> str:
    expr = (expression or "").strip()
    if not expr or not re.match(r"^[\d\s+\-*/().,a-z_]+$", expr, re.IGNORECASE):
        return f"Error: invalid expression: {expr!r}"
    try:
        result = eval(expr, {"__builtins__": {}}, _SAFE_MATH_NAMES)
        return f"{expression} = {result}"
    except Exception as e:
        return f"Error evaluating {expr!r}: {e}"


def tool_get_datetime(timezone: Optional[str] = None) -> str:
    try:
        if timezone:
            try:
                from zoneinfo import ZoneInfo
                now = datetime.now(ZoneInfo(timezone))
            except Exception:
                now = datetime.now()
                return f"Could not load timezone {timezone!r}; local time is {now.isoformat(timespec='seconds')}"
        else:
            now = datetime.now()
        return now.strftime("%Y-%m-%d %H:%M:%S %Z").strip()
    except Exception as e:
        return f"Error: {e}"


def tool_web_search(query: str, num_results: int = 3) -> str:
    """DuckDuckGo HTML scraping fallback (no API key needed)."""
    num_results = max(1, min(int(num_results or 3), 5))
    try:
        url = "https://duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        return f"Search failed: {e}"

    pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?'
        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
        re.DOTALL,
    )
    results = []
    for m in pattern.finditer(html):
        href, title, snippet = m.group(1), m.group(2), m.group(3)
        title = re.sub(r"<[^>]+>", "", title).strip()
        snippet = re.sub(r"<[^>]+>", "", snippet).strip()
        if href.startswith("//duckduckgo.com/l/?uddg="):
            try:
                qs = urllib.parse.parse_qs(href.split("?", 1)[1])
                href = urllib.parse.unquote(qs.get("uddg", [href])[0])
            except Exception:
                pass
        results.append(f"{len(results)+1}. {title}\n   {snippet}\n   {href}")
        if len(results) >= num_results:
            break
    if not results:
        return f"No results for {query!r}"
    return "\n".join(results)


def tool_get_weather(city: str, units: str = "metric") -> str:
    """Open-Meteo: free weather API, no key needed. Geocodes city first.

    Tries CJK-aware lookup first (language=zh) so Chinese/Japanese city names
    like "東京" or "台北" resolve, then falls back to language-agnostic
    lookup for English names.
    """
    try:
        results = []
        for lang in ("zh", None):
            params = {"name": city, "count": 1}
            if lang:
                params["language"] = lang
            geo_url = ("https://geocoding-api.open-meteo.com/v1/search?"
                       + urllib.parse.urlencode(params))
            with urllib.request.urlopen(geo_url, timeout=10) as r:
                geo = json.loads(r.read().decode("utf-8"))
            results = geo.get("results") or []
            if results:
                break
        if not results:
            return f"City not found: {city!r}"
        loc = results[0]
        lat, lon = loc["latitude"], loc["longitude"]
        place = f"{loc.get('name')}, {loc.get('country', '')}"

        unit_param = "celsius" if units == "metric" else "fahrenheit"
        wx_url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,wind_speed_10m,relative_humidity_2m,weather_code",
            "temperature_unit": unit_param,
        })
        with urllib.request.urlopen(wx_url, timeout=10) as r:
            wx = json.loads(r.read().decode("utf-8"))
        cur = wx.get("current", {})
        temp = cur.get("temperature_2m")
        wind = cur.get("wind_speed_10m")
        hum = cur.get("relative_humidity_2m")
        unit_sym = "°C" if units == "metric" else "°F"
        return (f"{place}: 溫度 {temp}{unit_sym}, "
                f"濕度 {hum}%, 風速 {wind} km/h")
    except Exception as e:
        return f"Weather lookup failed: {e}"


LOCAL_TOOLS = {
    "calculator":   lambda args: tool_calculator(args.get("expression", "")),
    "get_datetime": lambda args: tool_get_datetime(args.get("timezone")),
    "web_search":   lambda args: tool_web_search(args.get("query", ""),
                                                  args.get("num_results", 3)),
    "get_weather":  lambda args: tool_get_weather(args.get("city", ""),
                                                   args.get("units", "metric")),
}


def _merge_mcp_handlers_into_local():
    """Pull every handler from mcp_tools into LOCAL_TOOLS so that if the
    MCP subprocess is down/slow/timed-out, mcp_executor's fallback path
    still has a real implementation for tools like generate_image,
    execute_python, etc. — not just the original four."""
    try:
        from mcp_tools import ALL_TOOLS
    except Exception:
        return
    for name, info in ALL_TOOLS.items():
        handler = info.get("handler")
        if handler and name not in LOCAL_TOOLS:
            LOCAL_TOOLS[name] = handler


_merge_mcp_handlers_into_local()


def _build_full_tool_definitions():
    """Build OpenAI-format tool definitions from the mcp_tools registry.
    Imported lazily so tools.py doesn't depend on mcp_tools at module load."""
    try:
        from mcp_tools import ALL_TOOLS
    except Exception:
        return TOOL_DEFINITIONS  # fall back to the basic 4
    out = []
    for name, info in ALL_TOOLS.items():
        out.append({
            "type": "function",
            "function": {
                "name": name,
                "description": info["description"],
                "parameters": info["input_schema"],
            },
        })
    return out


def get_tool_definitions(extended: bool = True):
    return _build_full_tool_definitions() if extended else TOOL_DEFINITIONS


# Keyword → tool-name mapping used by the slim fallback to keep only the
# tools that look relevant to the user's query. Sending 1-3 tool schemas
# instead of all 23 keeps the request under Groq's 6000 TPM cap on 8B.
_TOOL_KEYWORDS = {
    "get_weather":     ["天氣", "weather", "溫度", "下雨", "預報", "氣溫"],
    "web_search":      ["查詢", "搜尋", "搜", "查", "search", "google", "找",
                        "天氣", "weather", "新聞", "news"],
    "calculator":      ["計算", "算", "calculate", "math", "+", "-", "×", "÷",
                        "*", "/", "²", "立方", "平方", "解", "等於"],
    "get_datetime":    ["現在", "now", "今天", "today", "幾點", "時間", "date",
                        "禮拜", "星期"],
    "stock_price":     ["股價", "股票", "stock", "shares"],
    "crypto_price":    ["加密", "crypto", "bitcoin", "比特幣", "eth", "btc"],
    "execute_python":  ["畫", "matplotlib", "plot", "繪製", "計算", "python",
                        "執行", "run", "正弦", "sin", "cos"],
    "generate_image":  ["生成", "畫一", "draw", "image", "圖片", "繪圖", "產生圖"],
    "fetch_url":       ["fetch", "抓", "爬", "網頁", "url", "http"],
    "github_search_repos": ["github", "repo"],
    "youtube_transcript":  ["youtube", "字幕", "transcript"],
    "arxiv_search":    ["arxiv", "論文", "paper"],
    "wikipedia_search": ["wikipedia", "wiki", "百科"],
    "notion_search":   ["notion", "搜尋 notion"],
    "notion_list_pages":   ["notion", "頁面"],
    "notion_create_page":  ["notion", "建立", "新增頁面"],
    "notion_append_to_page": ["notion", "append", "附加", "加到"],
    "notion_query_database": ["notion", "database", "資料庫"],
}


def _pick_relevant_tools(user_text: str, all_tool_defs: list) -> list:
    """Return the subset of `all_tool_defs` whose name appears relevant to
    `user_text`. Always returns at most ~5 tools — enough for the model to
    chain a couple of calls, small enough to fit the TPM budget."""
    if not user_text:
        return []
    txt = user_text.lower()
    relevant_names = []
    for name, keywords in _TOOL_KEYWORDS.items():
        if any(kw in txt for kw in keywords):
            relevant_names.append(name)
    if not relevant_names:
        return []
    seen = set()
    out = []
    for td in all_tool_defs:
        n = td.get("function", {}).get("name") if isinstance(td, dict) else None
        if n in relevant_names and n not in seen:
            seen.add(n)
            out.append(td)
        if len(out) >= 5:
            break
    return out


# ---- Agentic streaming loop ------------------------------------------

def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _build_post_tool_nudge(msgs: List[Dict], force_final: bool = False) -> Dict:
    """A system reminder that pins down trust in tool results — used both
    between rounds and on the final-answer round.

    When `force_final=True`, the model is told the tool budget is exhausted
    and MUST write a user-facing summary."""
    image_was_generated = any(
        isinstance(m.get("content"), str) and "[IMAGE]" in m["content"]
        and m.get("role") == "tool"
        for m in msgs
    )
    lines = [
        "你剛剛已經透過函式呼叫（tool calls）執行了工具，"
        "上面 role=tool 的訊息是真實的執行結果，請完全採信並據此回覆。",
        "絕對不要說『我沒有 X 能力』、『我無法執行 X』、『我只是文字模型』之類的話，"
        "因為你確實已經完成了該動作。",
    ]
    if force_final:
        lines.append(
            "**你的工具呼叫額度已用盡，這一輪不能再呼叫任何工具，必須寫文字回覆給使用者。**\n"
            "請：\n"
            "1) 簡短列出你『已經完成』的事項（每件一行，附上 tool result 裡的 URL 或 id 給使用者）\n"
            "2) 如果還有未完成的部分，明確告訴使用者：『剩下 X / Y / Z 還沒做完，要的話請說「繼續」』\n"
            "3) 不要寫 markdown 表頭 #；用簡單條列就好\n"
            "**絕對不要回覆空白或只回「好的」「已完成」這種沒資訊的話。**"
        )
    else:
        lines.extend([
            "如果使用者要求多步驟任務（例如：先生圖、再建 Notion 頁面、再加資料庫、再塞 row），"
            "**繼續呼叫工具直到全部做完**，不要在中途只用文字回應假裝完成。",
            "**效率提示：當你需要呼叫多個彼此獨立的工具時（例如同時建三個資料庫、"
            "或一次塞五個 row），請在同一輪的 tool_calls 陣列裡一次回傳全部，"
            "不要分多輪一次只 call 一個 — 工具呼叫額度有限，serial 會跑不完。**",
        ])
    if image_was_generated:
        lines.append(
            "特別注意：generate_image 工具已經成功幫使用者產生了圖片，"
            "圖片已顯示在使用者畫面上。如果接下來使用者還要把圖片放進 Notion，"
            "請呼叫 notion_add_image，**並用工具回傳的 Pollinations URL（image.pollinations.ai 那個）**，"
            "不要用本機 /static/uploads 路徑（Notion 看不到本機檔）。"
        )
    return {"role": "system", "content": "\n".join(lines)}


def _stream_final_answer(client, model, msgs, force_final: bool = False):
    """Stream a final text answer with the trust-your-tools nudge prepended.
    Returns the total characters streamed so the caller can detect empty
    replies and emit a fallback."""
    nudge = _build_post_tool_nudge(msgs, force_final=force_final)
    msgs_for_final = [nudge] + msgs
    stream = client.chat.completions.create(
        model=model, messages=msgs_for_final,
        max_tokens=16384, stream=True,
    )
    chars = 0
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            chars += len(delta)
            yield _sse({"content": delta})
    # Signal to caller via a marker on the generator. Generators can't
    # cleanly return values from a yield-from in Python without a wrapper,
    # so emit a sentinel SSE event the agentic loop can swallow.
    yield _sse({"_final_chars": chars})


def _summarize_completed_tools(msgs: List[Dict]) -> str:
    """Build a concise human-readable summary of tool results so we can
    show *something* if the model produces an empty final reply."""
    lines = []
    for m in msgs:
        if m.get("role") != "tool":
            continue
        content = m.get("content") or ""
        first_line = content.splitlines()[0] if content else ""
        url_match = re.search(r"https?://\S+", content)
        if url_match:
            lines.append(f"• {first_line[:80]}  →  {url_match.group(0)}")
        else:
            lines.append(f"• {first_line[:120]}")
    return "\n".join(lines[:30])


def agentic_stream(client, messages: List[Dict], model: str,
                   max_rounds: int = 25,
                   tool_executor: Optional[Callable[[str, dict], str]] = None,
                   ) -> Generator[str, None, None]:
    """Drive a multi-round tool-calling loop, yielding SSE strings.

    Each round, the model is offered the full tool catalog. It either
    requests more tool calls (we execute, append results, loop) or finishes
    with a text reply. On the LAST round we strip tools so the model is
    forced to produce its final prose.

    `tool_executor(tool_name, args) -> str` lets the caller route execution
    through MCP. Defaults to LOCAL_TOOLS.
    """
    if tool_executor is None:
        tool_executor = lambda name, args: LOCAL_TOOLS.get(
            name, lambda a: f"Unknown tool: {name}"
        )(args)

    msgs = list(messages)
    tool_defs = get_tool_definitions(extended=True)

    yield _sse({"type": "reasoning", "step": "🤔 分析使用者需求…"})

    for round_idx in range(max_rounds):
        is_last_round = (round_idx == max_rounds - 1)

        # Last round: force a final text answer (no more tools).
        if is_last_round:
            yield _sse({"type": "reasoning",
                        "step": "📝 已達工具上限，整合結果撰寫回覆…"})
            final_chars = 0
            try:
                for sse in _stream_final_answer(client, model, msgs, force_final=True):
                    # Swallow the sentinel; pass everything else through.
                    if '"_final_chars"' in sse:
                        try:
                            final_chars = json.loads(sse[6:]).get("_final_chars", 0)
                        except Exception:
                            pass
                        continue
                    yield sse
            except Exception as e:
                yield _sse({"type": "error", "message": f"Stream error: {e}"})
                return
            # Fallback: if the model wrote nothing, synthesize a summary
            # from the tool results so the user always sees feedback.
            if final_chars == 0:
                summary = _summarize_completed_tools(msgs)
                fallback = ("已達工具呼叫上限，這是目前完成的事項：\n\n"
                            + (summary or "(沒有任何工具成功完成)")
                            + "\n\n要繼續做剩下的部分請說「繼續」。")
                yield _sse({"content": fallback})
            return

        # Streaming probe with tools available. Pass content chunks straight
        # through to the user (so a long inline answer doesn't look frozen),
        # while also accumulating any tool_call deltas. After the stream
        # ends we know whether to execute tools or to exit.
        probe_msgs = msgs if round_idx == 0 else [_build_post_tool_nudge(msgs)] + msgs
        try:
            stream = client.chat.completions.create(
                model=model,
                messages=probe_msgs,
                tools=tool_defs,
                tool_choice="auto",
                max_tokens=16384,
                stream=True,
            )
        except Exception as e:
            err_text = str(e)
            # Llama on Groq occasionally emits malformed tool_calls JSON.
            # Fall back to a streamed plain answer so the user still sees
            # something rather than a hard failure.
            if "tool_use_failed" in err_text or "Failed to call a function" in err_text \
                    or "rate_limit_exceeded" in err_text or "Request too large" in err_text:
                # Slim retry: drop base_behavior + most tool schemas. Keep the
                # memory block, and KEEP a small subset of tools that look
                # relevant to the user's query (e.g. weather query → keep
                # get_weather + web_search). Filtering 23 tools down to 1-3
                # drops ~10000 tokens, so the request fits under 6000 TPM
                # AND the model can still call the tool the user actually
                # needs — instead of "工具不可用".
                last_user = next((m for m in reversed(msgs)
                                  if m.get("role") == "user"), None)
                user_text = (last_user.get("content", "") if last_user else "").lower()

                mem_block = ""
                orig_system = next((m.get("content", "") for m in msgs
                                    if m.get("role") == "system"), "")
                if orig_system:
                    marker_idx = orig_system.find("[已知使用者資訊")
                    if marker_idx == -1:
                        marker_idx = orig_system.find("Known User Context")
                    if marker_idx != -1:
                        mem_block = orig_system[marker_idx:].strip()

                # Pick tools relevant to the user's message.
                slim_tools = _pick_relevant_tools(user_text, tool_defs)

                slim_system = ("You are a concise assistant. Respond in the "
                               "user's language. Use tools if helpful.")
                if mem_block:
                    slim_system += "\n\n" + mem_block

                slim_msgs = [{"role": "system", "content": slim_system}]
                if last_user:
                    slim_msgs.append({"role": "user",
                                      "content": last_user.get("content", "")})
                # Stay on 70B (better at structured tool calls than 8B) but
                # with only the relevant tools — total request now ~3000 tokens,
                # well under 70B's 12000 TPM cap. 8B is unreliable for tools.
                fallback_model = "llama-3.3-70b-versatile" if slim_tools \
                                 else "llama-3.1-8b-instant"
                reason = "Groq 免費 tier 速率限制" \
                    if "rate_limit" in err_text or "too large" in err_text \
                    else "工具呼叫失敗"
                tool_note = (f"保留 {len(slim_tools)} 個相關工具"
                             if slim_tools else "無工具")
                yield _sse({"type": "tool_call_failed",
                            "message": f"{reason}，改用 {fallback_model} 精簡回答（{tool_note}）。"})
                try:
                    if slim_tools:
                        # One round of tool-aware retry.
                        kwargs = dict(model=fallback_model, messages=slim_msgs,
                                      tools=slim_tools, tool_choice="auto",
                                      max_tokens=2048)
                        resp = client.chat.completions.create(**kwargs)
                        choice = resp.choices[0]
                        msg = choice.message

                        if getattr(msg, "tool_calls", None):
                            slim_msgs.append({
                                "role": "assistant",
                                "content": msg.content or "",
                                "tool_calls": [{
                                    "id": tc.id, "type": "function",
                                    "function": {
                                        "name": tc.function.name,
                                        "arguments": tc.function.arguments,
                                    },
                                } for tc in msg.tool_calls],
                            })
                            for tc in msg.tool_calls:
                                name = tc.function.name
                                try:
                                    args = json.loads(tc.function.arguments or "{}")
                                except Exception:
                                    args = {}
                                yield _sse({"type": "tool_call", "tool": name,
                                            "args": args, "id": tc.id})
                                try:
                                    result = tool_executor(name, args)
                                except Exception as ex:
                                    result = f"Tool error: {ex}"
                                if not isinstance(result, str):
                                    result = json.dumps(result, ensure_ascii=False)
                                yield _sse({"type": "tool_result", "tool": name,
                                            "result": result, "id": tc.id})
                                slim_msgs.append({
                                    "role": "tool", "tool_call_id": tc.id,
                                    "content": result[:2000],
                                })
                            # Final answer using tool results.
                            final_stream = client.chat.completions.create(
                                model=fallback_model, messages=slim_msgs,
                                max_tokens=2048, stream=True,
                            )
                            for chunk in final_stream:
                                if not chunk.choices:
                                    continue
                                delta = chunk.choices[0].delta.content
                                if delta:
                                    yield _sse({"content": delta})
                        elif msg.content:
                            # Model answered without calling any tool.
                            yield _sse({"content": msg.content})
                    else:
                        # No relevant tools — plain reply.
                        slim_stream = client.chat.completions.create(
                            model=fallback_model, messages=slim_msgs,
                            max_tokens=2048, stream=True,
                        )
                        for chunk in slim_stream:
                            if not chunk.choices:
                                continue
                            delta = chunk.choices[0].delta.content
                            if delta:
                                yield _sse({"content": delta})
                except Exception as e2:
                    yield _sse({"type": "error",
                                "message": f"Fallback failed: {e2}"})
                return
            yield _sse({"type": "error", "message": f"LLM error: {e}"})
            return

        # Drain the stream: pass content chunks through live, accumulate
        # tool_call deltas (they arrive as partial JSON across chunks).
        streamed_content = ""
        tc_acc: dict = {}  # index → {"id", "name", "arguments"}
        finish_reason = None
        try:
            for chunk in stream:
                if not chunk.choices:
                    continue
                ch = chunk.choices[0]
                delta = ch.delta
                if getattr(delta, "content", None):
                    streamed_content += delta.content
                    yield _sse({"content": delta.content})
                if getattr(delta, "tool_calls", None):
                    for tc in delta.tool_calls:
                        idx = getattr(tc, "index", 0) or 0
                        slot = tc_acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                        if getattr(tc, "id", None):
                            slot["id"] = tc.id
                        fn = getattr(tc, "function", None)
                        if fn:
                            if getattr(fn, "name", None):
                                slot["name"] = fn.name
                            if getattr(fn, "arguments", None):
                                slot["arguments"] += fn.arguments
                if ch.finish_reason:
                    finish_reason = ch.finish_reason
        except Exception as e:
            err_text = str(e)
            # Same Groq malformed-tool-call failure as above, but raised
            # mid-stream. Retry without tools so the user still gets a reply.
            if "tool_use_failed" in err_text or "Failed to call a function" in err_text \
                    or "rate_limit_exceeded" in err_text or "Request too large" in err_text:
                # Slim retry: drop base_behavior + most tool schemas. Keep the
                # memory block, and KEEP a small subset of tools that look
                # relevant to the user's query (e.g. weather query → keep
                # get_weather + web_search). Filtering 23 tools down to 1-3
                # drops ~10000 tokens, so the request fits under 6000 TPM
                # AND the model can still call the tool the user actually
                # needs — instead of "工具不可用".
                last_user = next((m for m in reversed(msgs)
                                  if m.get("role") == "user"), None)
                user_text = (last_user.get("content", "") if last_user else "").lower()

                mem_block = ""
                orig_system = next((m.get("content", "") for m in msgs
                                    if m.get("role") == "system"), "")
                if orig_system:
                    marker_idx = orig_system.find("[已知使用者資訊")
                    if marker_idx == -1:
                        marker_idx = orig_system.find("Known User Context")
                    if marker_idx != -1:
                        mem_block = orig_system[marker_idx:].strip()

                # Pick tools relevant to the user's message.
                slim_tools = _pick_relevant_tools(user_text, tool_defs)

                slim_system = ("You are a concise assistant. Respond in the "
                               "user's language. Use tools if helpful.")
                if mem_block:
                    slim_system += "\n\n" + mem_block

                slim_msgs = [{"role": "system", "content": slim_system}]
                if last_user:
                    slim_msgs.append({"role": "user",
                                      "content": last_user.get("content", "")})
                # Stay on 70B (better at structured tool calls than 8B) but
                # with only the relevant tools — total request now ~3000 tokens,
                # well under 70B's 12000 TPM cap. 8B is unreliable for tools.
                fallback_model = "llama-3.3-70b-versatile" if slim_tools \
                                 else "llama-3.1-8b-instant"
                reason = "Groq 免費 tier 速率限制" \
                    if "rate_limit" in err_text or "too large" in err_text \
                    else "工具呼叫失敗"
                tool_note = (f"保留 {len(slim_tools)} 個相關工具"
                             if slim_tools else "無工具")
                yield _sse({"type": "tool_call_failed",
                            "message": f"{reason}，改用 {fallback_model} 精簡回答（{tool_note}）。"})
                try:
                    if slim_tools:
                        # One round of tool-aware retry.
                        kwargs = dict(model=fallback_model, messages=slim_msgs,
                                      tools=slim_tools, tool_choice="auto",
                                      max_tokens=2048)
                        resp = client.chat.completions.create(**kwargs)
                        choice = resp.choices[0]
                        msg = choice.message

                        if getattr(msg, "tool_calls", None):
                            slim_msgs.append({
                                "role": "assistant",
                                "content": msg.content or "",
                                "tool_calls": [{
                                    "id": tc.id, "type": "function",
                                    "function": {
                                        "name": tc.function.name,
                                        "arguments": tc.function.arguments,
                                    },
                                } for tc in msg.tool_calls],
                            })
                            for tc in msg.tool_calls:
                                name = tc.function.name
                                try:
                                    args = json.loads(tc.function.arguments or "{}")
                                except Exception:
                                    args = {}
                                yield _sse({"type": "tool_call", "tool": name,
                                            "args": args, "id": tc.id})
                                try:
                                    result = tool_executor(name, args)
                                except Exception as ex:
                                    result = f"Tool error: {ex}"
                                if not isinstance(result, str):
                                    result = json.dumps(result, ensure_ascii=False)
                                yield _sse({"type": "tool_result", "tool": name,
                                            "result": result, "id": tc.id})
                                slim_msgs.append({
                                    "role": "tool", "tool_call_id": tc.id,
                                    "content": result[:2000],
                                })
                            # Final answer using tool results.
                            final_stream = client.chat.completions.create(
                                model=fallback_model, messages=slim_msgs,
                                max_tokens=2048, stream=True,
                            )
                            for chunk in final_stream:
                                if not chunk.choices:
                                    continue
                                delta = chunk.choices[0].delta.content
                                if delta:
                                    yield _sse({"content": delta})
                        elif msg.content:
                            # Model answered without calling any tool.
                            yield _sse({"content": msg.content})
                    else:
                        # No relevant tools — plain reply.
                        slim_stream = client.chat.completions.create(
                            model=fallback_model, messages=slim_msgs,
                            max_tokens=2048, stream=True,
                        )
                        for chunk in slim_stream:
                            if not chunk.choices:
                                continue
                            delta = chunk.choices[0].delta.content
                            if delta:
                                yield _sse({"content": delta})
                except Exception as e2:
                    yield _sse({"type": "error",
                                "message": f"Fallback failed: {e2}"})
                return
            yield _sse({"type": "error", "message": f"Stream read error: {e}"})
            return

        tool_calls_list = [v for _, v in sorted(tc_acc.items())]

        # No tool calls → model is done. Content already streamed; exit.
        if finish_reason != "tool_calls" or not tool_calls_list:
            if round_idx == 0 and not streamed_content.strip():
                # Edge case: model returned nothing at all
                yield _sse({"content": "(模型沒有回覆內容)"})
            elif round_idx == 0:
                yield _sse({"type": "reasoning", "step": "💬 直接回答（不需工具）"})
            else:
                yield _sse({"type": "reasoning", "step": "✅ 工作完成"})
            return

        # Otherwise: execute the requested tools, then loop back.
        tool_names = [tc["name"] for tc in tool_calls_list]
        yield _sse({"type": "reasoning",
                    "step": f"🔧 第 {round_idx + 1} 輪工具：{', '.join(tool_names)}"})

        msgs.append({
            "role": "assistant",
            "content": streamed_content,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": tc["arguments"],
                    },
                }
                for tc in tool_calls_list
            ],
        })
        for tc in tool_calls_list:
            tool_name = tc["name"]
            try:
                args = json.loads(tc["arguments"] or "{}")
            except Exception:
                args = {}
            yield _sse({"type": "tool_call", "tool": tool_name,
                        "args": args, "id": tc["id"]})
            try:
                result = tool_executor(tool_name, args)
            except Exception as e:
                result = f"Tool execution error: {e}"
            if not isinstance(result, str):
                result = json.dumps(result, ensure_ascii=False)
            yield _sse({"type": "tool_result", "tool": tool_name,
                        "result": result, "id": tc["id"]})
            msgs.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result,
            })
        # Loop continues — model gets to call more tools or finalize next round.
