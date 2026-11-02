# Using the engine from OpenAI tools

Codex reads `AGENTS.md` in the repo root; nothing else is needed for it.

## Agents SDK (Python)
The server speaks MCP over stdio, so the SDK can launch it directly:

```python
import asyncio
from agents import Agent, Runner
from agents.mcp import MCPServerStdio

async def main():
    async with MCPServerStdio(params={"command": "python3", "args": ["/ABSOLUTE/PATH/mcp/server.py"],
                                      "env": {"MODEL_PROVIDER": "mock"}}) as rfp:
        agent = Agent(name="RFP reader", instructions="Answer only from the rfp-intelligence tools. Quote figures exactly.",
                      mcp_servers=[rfp])
        result = await Runner.run(agent, "What is the bid deposit, and has an amendment changed it?")
        print(result.final_output)

asyncio.run(main())
```

## Responses API
The hosted MCP tool (`{"type": "mcp", "server_url": ...}`) needs a remote HTTPS endpoint. This server is stdio only,
so either use the Agents SDK above, or put an MCP stdio-to-HTTP bridge in front of it on a host you control.
Exposing it publicly is not covered here and has no auth.

Not run in this package: neither snippet was executed against OpenAI (no OpenAI key where it was packaged).
