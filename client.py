import asyncio
from typing import Optional
from contextlib import AsyncExitStack
import sys
import json
import os
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from openai import AsyncOpenAI
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL_NAME = os.getenv("LLM_MODEL")

class MCPClient:
    def __init__(self):
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.stdio = None
        self.write = None

    async def connect_to_server(self, server_script_path: str):
        is_python = server_script_path.endswith('.py')
        is_js = server_script_path.endswith('.js')
        if not (is_python or is_js):
            raise ValueError("Server script must be a .py or .js file")

        command = "python" if is_python else "node"
        server_params = StdioServerParameters(
            command=command,
            args=[server_script_path],
            env=None
        )

        # AsyncExitStackで非同期コンテキスト管理
        self.stdio, self.write = await self.exit_stack.enter_async_context(stdio_client(server_params))
        self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))

        await self.session.initialize()

        response = await self.session.list_tools()
        tools = response.tools
        print("\nConnected to server with tools:", [tool.name for tool in tools])

    async def close(self):
        # exit_stackが管理しているすべてを閉じる
        await self.exit_stack.aclose()


    async def process_query(self, query: str) -> str:
        messages = [
            {"role": "user", "content": query}
        ]

        # MCPサーバのツール情報取得
        tools_resp = await self.session.list_tools()
        openai_tools = []
        for tool in tools_resp.tools:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.inputSchema or {"type": "object"}
                }
            })

        # 1回目のChatCompletion（Tool Calling auto）
        response = await openai_client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            tools=openai_tools,
            tool_choice="auto"
        )

        message = response.choices[0].message

        if not message.tool_calls:
            # ツール呼び出しなしはそのまま回答を返す
            return message.content or ""

        # メッセージ履歴にアシスタントのツール呼び出しを追加
        messages.append(message.model_dump(exclude_none=True))

        for tool_call in message.tool_calls:
            tool_name = tool_call.function.name

            try:
                tool_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                tool_args = {}

            # ツール呼び出し
            tool_result = await self.session.call_tool(tool_name, tool_args)

            # tool_result.content は List[TextContent] なのでテキストを連結
            texts = [c.text for c in tool_result.content if hasattr(c, "text")]
            content_str = "\n".join(texts)

            # メッセージ履歴にツール呼び出し結果を追加
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": content_str
            })

        # 2回目のChatCompletion（結果を踏まえた応答生成）
        second_response = await openai_client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages
        )
        return second_response.choices[0].message.content or ""

    async def chat_loop(self):
        print("MCP Client started")
        while True:
            query = input("Query> ").strip()
            if query.lower() in ("quit", "exit"):
                break
            response = await self.process_query(query)
            print(response)

async def main():
    if len(sys.argv) < 2:
        print("Usage: python client.py <server_path.py>")
        return
    client = MCPClient()
    await client.connect_to_server(sys.argv[1])
    try:
        await client.chat_loop()
    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(main())
