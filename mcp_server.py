"""
Lab 2 v2 MCP Server.

Stdio MCP server that exposes 20+ tools across 8 categories:
- basic       (calculator, datetime, web search, weather)
- image_gen   (Pollinations.ai image generation)
- filesystem  (read/write/list/search in sandbox)
- web         (fetch_url, github, youtube transcript)
- academic    (arxiv, wikipedia)
- finance     (stock, crypto)
- code_exec   (sandboxed Python execution with matplotlib)
- notion_tools (search/list/create/append/query)
"""
import asyncio
import json
import os
import sys

from dotenv import load_dotenv

# Ensure .env (NOTION_TOKEN, GROQ_API_KEY, ...) is loaded even when the
# server is spawned as a fresh subprocess by the MCP client.
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from mcp_tools import ALL_TOOLS

# Log to a file since stderr is captured by the MCP client.
_LOG = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "mcp_server.log"), "a", encoding="utf-8")


def _log(msg):
    print(msg, file=_LOG, flush=True)


server = Server("lab2-tools")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name=name,
            description=info["description"],
            inputSchema=info["input_schema"],
        )
        for name, info in ALL_TOOLS.items()
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
    args = arguments or {}
    _log(f"[call_tool] name={name} args={list(args.keys())}")
    tool = ALL_TOOLS.get(name)
    if tool is None:
        return [types.TextContent(type="text", text=f"Unknown tool: {name}")]
    try:
        # Run sync handler in a thread so subprocess.run / blocking I/O
        # doesn't block the asyncio event loop.
        result = await asyncio.to_thread(tool["handler"], args)
        _log(f"[call_tool] {name} OK ({len(str(result))} chars)")
    except Exception as e:
        import traceback
        _log(f"[call_tool] {name} FAILED: {e}\n{traceback.format_exc()}")
        result = f"Tool execution error: {e}"
    if not isinstance(result, str):
        try:
            result = json.dumps(result, ensure_ascii=False)
        except Exception:
            result = str(result)
    return [types.TextContent(type="text", text=result)]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
