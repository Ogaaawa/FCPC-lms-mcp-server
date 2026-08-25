
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
    prompt = ("You can use the tools below. If a tool is needed, output the tool "
              "name and its arguments as JSON.\n\nAvailable tools:\n")

    for i, tool in enumerate(tools_resp.tools, 1):
        prompt += f"{i}. name: {tool.name}\n"
        prompt += f"   description: {tool.description.strip()}\n"

        # Read the input schema
        schema = tool.inputSchema
        properties = schema.get("properties", {})
        if properties:
            prompt += f"   parameters:\n"
            for prop, meta in properties.items():
                type_str = meta.get("type", "string")
                title_str = meta.get("title", prop)
                prompt += f"     - {prop} ({type_str}): {title_str}\n"
        else:
            prompt += "   parameters: none\n"
        prompt += "\n"

    prompt += 'If no tool is needed, reply with just "none".'
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

        # Manage the async contexts with AsyncExitStack
        self.stdio, self.write = await self.exit_stack.enter_async_context(stdio_client(server_params))
        self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))

        await self.session.initialize()

        response = await self.session.list_tools()
        tools = response.tools
        print("\nConnected to server with tools:", [tool.name for tool in tools])

    async def close(self):
        # Close everything the exit stack is holding
        await self.exit_stack.aclose()


    async def process_query(self, query: str) -> str:
        try:
            # 1. Fetch the tool list
            tools_resp = await self.session.list_tools()

            # 2. Build the prompt covering both tool use and a plain answer
            tool_prompt = build_tools_prompt_from_tools_resp(tools_resp)
            full_prompt = (
                f"{tool_prompt}\n\n"
                f"User input: {query}\n\n"
                "Reply as JSON, in one of these two shapes:\n"
                "1. using a tool: {\"tool_name\": ..., \"parameters\": {...}}\n"
                "2. no tool needed: {\"tool_name\": \"none\", \"answer\": \"...\"}"
            )
            # 3. Ask the model
            tool_decision_text = call_ollama(MODEL_NAME, full_prompt)
            tool_data = json.loads(tool_decision_text)

            tool_name = tool_data.get("tool_name")
            if tool_name == "none":
                return tool_data.get("answer", "[no tool needed, but no answer was given]")

            # 4. Run the tool
            tool_args = tool_data.get("parameters", {})
            tool_response = await self.session.call_tool(tool_name, tool_args)

            # 5. Turn the tool result into the final answer
            final_prompt = (
                f"User question: {query}\n\n"
                f"Result from the \"{tool_name}\" tool:\n{tool_response}\n\n"
                "Answer the question naturally using this information."
            )
            return call_ollama(MODEL_NAME, final_prompt)

        except Exception as e:
            return f"[error] Something went wrong while choosing a tool: {e}"


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


