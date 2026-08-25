"""Print the tools this MCP server exposes.

Shows exactly what an AI assistant receives when it asks what tools are
available. Useful for demos and for checking a configuration change.

Usage:
    python list_tools.py
"""
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = os.path.dirname(os.path.abspath(__file__))


def python_executable() -> str:
    for candidate in (
        os.path.join(ROOT, "venv", "bin", "python"),
        os.path.join(ROOT, "venv", "Scripts", "python.exe"),
    ):
        if os.path.exists(candidate):
            return candidate
    return sys.executable


async def main() -> None:
    params = StdioServerParameters(
        command=python_executable(),
        args=[os.path.join(ROOT, "server.py")],
        cwd=ROOT,
        env=dict(os.environ),
    )
    # Discard the server log so the output stays readable.
    devnull = open(os.devnull, "w")
    try:
        async with stdio_client(params, errlog=devnull) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = (await session.list_tools()).tools
    finally:
        devnull.close()

    print(f"\n{len(tools)} tools registered\n")
    for i, tool in enumerate(tools, 1):
        print("=" * 68)
        print(f"{i}. {tool.name}")
        print("=" * 68)

        description = (tool.description or "").strip()
        print("  Description the AI reads:")
        for line in description.splitlines() or ["(no description)"]:
            print(f"  {line}")

        props = (tool.inputSchema or {}).get("properties") or {}
        required = set((tool.inputSchema or {}).get("required") or [])
        print("  Arguments:")
        if not props:
            print("    (none)")
        for name, spec in props.items():
            mark = "required" if name in required else "optional"
            print(f"  - {name} ({mark}): {json.dumps(spec, ensure_ascii=False)}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
