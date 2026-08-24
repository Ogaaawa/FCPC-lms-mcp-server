"""この MCP サーバが公開しているツールを一覧表示する（デモ・確認用）。

Gemini や Claude などの AI が「どんな道具が使えるか」を知るために
受け取っている情報そのものを表示する。

使い方:
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
    # サーバのログ出力はデモの邪魔になるので捨てる
    devnull = open(os.devnull, "w")
    try:
        async with stdio_client(params, errlog=devnull) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = (await session.list_tools()).tools
    finally:
        devnull.close()

    print(f"\n登録されているツール: {len(tools)} 個\n")
    for i, tool in enumerate(tools, 1):
        print("=" * 68)
        print(f"{i}. {tool.name}")
        print("=" * 68)

        description = (tool.description or "").strip()
        print("【AI が読む説明】")
        for line in description.splitlines() or ["(説明なし)"]:
            print(f"  {line}")

        props = (tool.inputSchema or {}).get("properties") or {}
        required = set((tool.inputSchema or {}).get("required") or [])
        print("【引数】")
        if not props:
            print("  なし")
        for name, spec in props.items():
            mark = "必須" if name in required else "任意"
            print(f"  - {name} ({mark}): {json.dumps(spec, ensure_ascii=False)}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
