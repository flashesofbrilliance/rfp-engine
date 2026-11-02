# Using the engine from Hermes

## Instructions
Hermes loads one project context file per session, first match wins: `.hermes.md`, `AGENTS.override.md`,
`AGENTS.md`, `CLAUDE.md`, `.cursorrules`. This repo ships `AGENTS.md`, so Hermes reads the same rules as every other
agent. There is deliberately no `.hermes.md`: it would replace `AGENTS.md` for Hermes instead of adding to it.

## MCP server
Add to `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  rfp-intelligence:
    command: python3
    args: ["/ABSOLUTE/PATH/mcp/server.py"]
    env:
      MODEL_PROVIDER: mock
```

Hermes passes only the listed `env` plus safe defaults to the subprocess, so set `ANTHROPIC_API_KEY` there too if you
switch to `MODEL_PROVIDER: claude`. If the server is already in Claude Code, `hermes import-agent claude-code` migrates it.

Not run in this package: the config was written from Hermes' own docs, not tested in a Hermes session.
