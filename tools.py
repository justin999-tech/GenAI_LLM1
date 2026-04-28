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
    """Open-Meteo: free weather API, no key needed. Geocodes city first."""
    try:
        geo_url = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode(
            {"name": city, "count": 1}
        )
        with urllib.request.urlopen(geo_url, timeout=10) as r:
            geo = json.loads(r.read().decode("utf-8"))
        results = geo.get("results") or []
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


# ---- Agentic streaming loop ------------------------------------------

def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def agentic_stream(client, messages: List[Dict], model: str,
                   max_rounds: int = 4,
                   tool_executor: Optional[Callable[[str, dict], str]] = None,
                   ) -> Generator[str, None, None]:
    """Drive a multi-round tool-calling loop, yielding SSE strings.

    Each round either streams the model's text response (terminal round)
    or executes tool calls and feeds their results back into the model.

    `tool_executor(tool_name, args) -> str` lets the caller route execution
    through MCP. Defaults to LOCAL_TOOLS.
    """
    if tool_executor is None:
        tool_executor = lambda name, args: LOCAL_TOOLS.get(
            name, lambda a: f"Unknown tool: {name}"
        )(args)

    msgs = list(messages)
    tools_consumed = False  # once tools have been used, don't expose them again

    # Emit a reasoning event for the right panel.
    yield _sse({"type": "reasoning", "step": "🤔 分析使用者需求…"})

    for round_idx in range(max_rounds):
        # First round offers tools; after any tool execution we drop tools=
        # so the model produces a textual final answer (avoids Groq's
        # tool-loop format errors).
        offering_tools = (round_idx == 0 and not tools_consumed)

        if offering_tools:
            # Non-streaming probe to detect tool_calls. If the model
            # produces an invalid tool-call format (Groq Llama quirk),
            # fall back to a plain streamed answer without tools.
            tool_defs = get_tool_definitions(extended=True)
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=msgs,
                    tools=tool_defs,
                    tool_choice="auto",
                    max_tokens=4096,
                )
            except Exception as e:
                err_text = str(e)
                if "tool_use_failed" in err_text or "Failed to call a function" in err_text:
                    yield _sse({"type": "tool_call_failed",
                                "message": "模型未能正確產生工具呼叫，改用直接回答。"})
                    try:
                        stream = client.chat.completions.create(
                            model=model, messages=msgs,
                            max_tokens=4096, stream=True,
                        )
                        for chunk in stream:
                            delta = chunk.choices[0].delta.content
                            if delta:
                                yield _sse({"content": delta})
                    except Exception as e2:
                        yield _sse({"type": "error",
                                    "message": f"Fallback failed: {e2}"})
                    return
                yield _sse({"type": "error", "message": f"LLM error: {e}"})
                return

            choice = resp.choices[0]
            msg = choice.message

            if choice.finish_reason == "tool_calls" and msg.tool_calls:
                tool_names = [tc.function.name for tc in msg.tool_calls]
                yield _sse({"type": "reasoning",
                            "step": f"🔧 決定使用工具：{', '.join(tool_names)}"})
                msgs.append({
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                })
                for tc in msg.tool_calls:
                    tool_name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except Exception:
                        args = {}
                    yield _sse({"type": "tool_call", "tool": tool_name,
                                "args": args, "id": tc.id})
                    try:
                        result = tool_executor(tool_name, args)
                    except Exception as e:
                        result = f"Tool execution error: {e}"
                    if not isinstance(result, str):
                        result = json.dumps(result, ensure_ascii=False)
                    yield _sse({"type": "tool_result", "tool": tool_name,
                                "result": result, "id": tc.id})
                    msgs.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    })
                tools_consumed = True
                yield _sse({"type": "reasoning",
                            "step": "✅ 工具執行完成，整合結果中…"})
                continue
            else:
                # Model answered directly without tools — stream it now.
                yield _sse({"type": "reasoning", "step": "💬 直接回答（不需工具）"})
                if msg.content:
                    yield _sse({"content": msg.content})
                return

        # Tool results are in messages; ask for a streamed final answer
        # without tools so the model writes prose.
        yield _sse({"type": "reasoning", "step": "📝 根據工具結果撰寫回覆…"})
        try:
            stream = client.chat.completions.create(
                model=model,
                messages=msgs,
                max_tokens=4096,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield _sse({"content": delta})
        except Exception as e:
            yield _sse({"type": "error", "message": f"Stream error: {e}"})
        return

    yield _sse({"content": "（已達到工具呼叫回合上限）"})
