import logging
import requests
import json
import setuplogging
from runenv import TESTER_SERVER_URL, MCP_API_TOKEN
from mcp.server import Server
from mcp import types
from mcp.types import CallToolResult, TextContent

import asyncio
from mcp.server.stdio import stdio_server


logger = logging.getLogger(__name__)

server = Server("tester")
HEADERS = {"Authorization": f"Bearer {MCP_API_TOKEN}"}
VERIFY = "/app/certs/ca.crt"


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="run_tests",
            description="Starts an async test run against the current workspace. Returns immediately with status 'started'. Poll get_test_results to check outcome.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        types.Tool(
            name="get_test_results",
            description="Returns the result of the most recent test run as JSON with fields: status (pass/fail/running/pending), exit_code, timestamp, output.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> CallToolResult:
    try:
        result = await _dispatch(name, arguments)
        return CallToolResult(
            content=[TextContent(type="text", text=result)],
            isError=False
        )
    except Exception as e:
        logger.error(f"Tool {name} error: {e}")
        return CallToolResult(
            content=[TextContent(type="text", text=str(e))],
            isError=True
        )


async def _dispatch(name: str, arguments: dict) -> str:
    if name == "run_tests":
        response = requests.post(
            f"{TESTER_SERVER_URL}/run",
            headers=HEADERS, verify=VERIFY, timeout=10
        )
        if response.status_code == 200:
            return json.dumps(response.json())
        elif response.status_code == 401:
            raise PermissionError("Unauthorized. Token mismatch.")
        elif response.status_code == 409:
            raise RuntimeError("A test run is already in progress. Poll get_test_results to wait for completion.")
        else:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text}")

    elif name == "get_test_results":
        response = requests.get(
            f"{TESTER_SERVER_URL}/results",
            headers=HEADERS, verify=VERIFY, timeout=10
        )
        if response.status_code == 200:
            return json.dumps(response.json())
        elif response.status_code == 401:
            raise PermissionError("Unauthorized. Token mismatch.")
        else:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text}")

    else:
        raise ValueError(f"Unknown tool {name}")


if __name__ == "__main__":
    async def main():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options()
            )

    asyncio.run(main())
