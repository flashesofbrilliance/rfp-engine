# CLAUDE.md

@AGENTS.md

## Claude Code
Register the engine as an MCP server (absolute path to this folder):

    claude mcp add rfp-intelligence -e MODEL_PROVIDER=mock -- python3 /ABSOLUTE/PATH/mcp/server.py

Then ask: "Using rfp-intelligence, what is the bid deposit, and has an amendment changed it?"
Use `MODEL_PROVIDER=claude` with `ANTHROPIC_API_KEY` for real answers, or `local` with Ollama.
