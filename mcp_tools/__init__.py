"""
Lab 2 MCP tool implementations.

Each module exposes a registry of (name -> {description, input_schema, handler}).
mcp_server.py imports `ALL_TOOLS` from this package for the unified MCP server.
"""
from . import basic, image_gen, filesystem, web, academic, finance, code_exec, notion_tools

# Combine all tool registries.
ALL_TOOLS = {}
for mod in (basic, image_gen, filesystem, web, academic, finance, code_exec, notion_tools):
    ALL_TOOLS.update(getattr(mod, "TOOLS", {}))
