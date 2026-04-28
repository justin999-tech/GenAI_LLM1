"""Basic tools (calculator, datetime, web_search, weather) — moved here from tools.py."""
from tools import (tool_calculator, tool_get_datetime,
                   tool_web_search, tool_get_weather)


TOOLS = {
    "calculator": {
        "description": "Evaluate a math expression. Supports +-*/, parentheses, sqrt, sin, cos, log.",
        "input_schema": {
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
        },
        "handler": lambda args: tool_calculator(args.get("expression", "")),
    },
    "get_datetime": {
        "description": "Get current date and time. Optionally for a timezone like 'Asia/Taipei'.",
        "input_schema": {
            "type": "object",
            "properties": {"timezone": {"type": "string"}},
            "required": [],
        },
        "handler": lambda args: tool_get_datetime(args.get("timezone")),
    },
    "web_search": {
        "description": "Search the web (DuckDuckGo) for up-to-date information. Returns titles, snippets, URLs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "num_results": {"type": "integer", "default": 3},
            },
            "required": ["query"],
        },
        "handler": lambda args: tool_web_search(args.get("query", ""),
                                                  args.get("num_results", 3)),
    },
    "get_weather": {
        "description": "Current weather for a city via Open-Meteo (free, no key needed).",
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "units": {"type": "string", "enum": ["metric", "imperial"]},
            },
            "required": ["city"],
        },
        "handler": lambda args: tool_get_weather(args.get("city", ""),
                                                   args.get("units", "metric")),
    },
}
