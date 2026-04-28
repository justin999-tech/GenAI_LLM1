"""
MCP Client wrapper.

Bridges Flask's synchronous request handlers with the MCP package's
asyncio API. A dedicated event loop runs in a daemon thread; sync code
dispatches into it via `run_coroutine_threadsafe`.

Lifecycle:
    client = MCPClient()
    client.start()                # spawns mcp_server.py subprocess
    client.call_tool(name, args)  # synchronous, thread-safe
    client.stop()                 # on shutdown
"""
import asyncio
import os
import sys
import threading
from contextlib import AsyncExitStack
from typing import Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPClient:
    def __init__(self, server_script: Optional[str] = None):
        # Use the same Python interpreter the Flask app is running under.
        self.server_script = server_script or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "mcp_server.py"
        )
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._session: Optional[ClientSession] = None
        self._ready = threading.Event()
        self._stop_event: Optional[asyncio.Event] = None
        self._exit_stack: Optional[AsyncExitStack] = None
        self._error: Optional[str] = None
        self._tools_cache: list[str] = []

    @property
    def connected(self) -> bool:
        return self._session is not None and self._error is None

    @property
    def tools(self) -> list[str]:
        return list(self._tools_cache)

    @property
    def status(self) -> dict:
        return {
            "connected": self.connected,
            "tools": self.tools,
            "error": self._error,
            "server_script": self.server_script,
        }

    # ---- Lifecycle ----------------------------------------------------

    def start(self, timeout: float = 15.0) -> bool:
        if self._thread is not None:
            return self.connected
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        ok = self._ready.wait(timeout=timeout)
        return ok and self.connected

    def _run_loop(self):
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._connect_and_serve())
        except Exception as e:
            self._error = f"MCP client loop crashed: {e}"
            self._ready.set()

    async def _connect_and_serve(self):
        self._stop_event = asyncio.Event()
        self._exit_stack = AsyncExitStack()
        try:
            params = StdioServerParameters(
                command=sys.executable,
                args=[self.server_script],
                env=os.environ.copy(),
            )
            read, write = await self._exit_stack.enter_async_context(stdio_client(params))
            session = await self._exit_stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self._session = session
            tools_resp = await session.list_tools()
            self._tools_cache = [t.name for t in tools_resp.tools]
            self._ready.set()
            await self._stop_event.wait()
        except Exception as e:
            self._error = f"MCP connection failed: {e}"
            self._ready.set()
        finally:
            try:
                if self._exit_stack is not None:
                    await self._exit_stack.aclose()
            except Exception:
                pass

    def stop(self):
        if self._loop and self._stop_event:
            self._loop.call_soon_threadsafe(self._stop_event.set)

    # ---- Tool invocation (sync API) -----------------------------------

    def call_tool(self, name: str, args: dict, timeout: float = 150.0) -> str:
        if not self.connected or self._loop is None:
            raise RuntimeError(f"MCP client not connected: {self._error}")
        future = asyncio.run_coroutine_threadsafe(
            self._call_tool_async(name, args), self._loop
        )
        return future.result(timeout=timeout)

    async def _call_tool_async(self, name: str, args: dict) -> str:
        result = await self._session.call_tool(name, args)
        # Concatenate any text content blocks the server returned.
        out = []
        for block in result.content:
            text = getattr(block, "text", None)
            if text:
                out.append(text)
        return "\n".join(out) if out else ""
