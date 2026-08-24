
import asyncio
from typing import Optional
from contextlib import AsyncExitStack
import sys
import json
import os
import requests
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

MODEL_NAME = os.getenv("LLM_MODEL")


def call_ollama(model: str, prompt: str) -> str:
    response = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False
        }
    )
    response.raise_for_status()
    return response.json()["response"]

def build_tools_prompt_from_tools_resp(tools_resp) -> str:
    prompt = "以下のツールを使うことができます．ツールが必要な場合はツール名と引数をJSON形式で出力してください。\n\nツール一覧:\n"

    for i, tool in enumerate(tools_resp.tools, 1):
        prompt += f"{i}. name: {tool.name}\n"
        prompt += f"   description: {tool.description.strip()}\n"

        # 入力スキーマの解析
        schema = tool.inputSchema
        properties = schema.get("properties", {})
        if properties:
            prompt += f"   parameters:\n"
            for prop, meta in properties.items():
                type_str = meta.get("type", "string")
                title_str = meta.get("title", prop)
                prompt += f"     - {prop} ({type_str}): {title_str}\n"
        else:
            prompt += "   parameters: なし\n"
        prompt += "\n"

    prompt += "ツールが不要な場合は \"none\" とだけ返してください。"
    return prompt



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
        try:
            # 1. ツール一覧を取得
            tools_resp = await self.session.list_tools()

            # 2. ツールと通常回答を含めた出力プロンプトを構築
            tool_prompt = build_tools_prompt_from_tools_resp(tools_resp)
            full_prompt = (
                f"{tool_prompt}\n\n"
                f"ユーザーの入力: {query}\n\n"
                "出力は JSON 形式で返してください。以下のいずれかの形式とします：\n"
                "1. ツール使用時: {\"tool_name\": ..., \"parameters\": {...}}\n"
                "2. ツール不要時: {\"tool_name\": \"none\", \"answer\": \"...\"}"
            )
            # 3. LLM へ問い合わせ
            tool_decision_text = call_ollama(MODEL_NAME, full_prompt)
            tool_data = json.loads(tool_decision_text)

            tool_name = tool_data.get("tool_name")
            if tool_name == "none":
                return tool_data.get("answer", "[ツール不要だが返答がありません]")

            # 4. ツール呼び出し
            tool_args = tool_data.get("parameters", {})
            tool_response = await self.session.call_tool(tool_name, tool_args)

            # 5. ツール結果をもとに最終回答を生成
            final_prompt = f"ユーザーの質問: {query}\n\nツール「{tool_name}」の結果:\n{tool_response}\n\nこの情報をもとに自然な日本語で返答してください。"
            return call_ollama(MODEL_NAME, final_prompt)

        except Exception as e:
            return f"[エラー] ツール判定処理中に問題が発生しました: {e}"


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


