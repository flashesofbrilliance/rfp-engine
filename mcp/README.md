# RFP answering engine as an MCP server

A local MCP server (stdio) that lets Claude Code or Claude Desktop ask questions about the loaded RFP and its
amendment, and get back either an answer with the exact clauses it rests on, or a refusal.

It is a thin wrapper. `server.py` loads the documents in `../data/`, calls the engine's `rfp.answer.answer()`
unchanged and reshapes the result. The trust rules all stay in the engine:

- No answer without a cited clause. If the model cites a clause that does not exist, nothing is answered.
- Every figure in an answer must appear word for word in a cited clause, or the summary is withheld and only the
  cited text comes back.
- "Not addressed in the RFP" beats a guess. Questions asking it to draft bid language or make a bid/no-bid call are
  refused before any model call.
- When the model is unreachable, the status is `unavailable` with the clauses that look relevant, not an answer.

Standard library only, like the engine: the MCP protocol (JSON-RPC 2.0 over stdio) is implemented in about 100
lines, so there is no MCP SDK and nothing to `pip install`. Python 3.9 or newer.

## Tools

| Tool | Input | Returns |
|---|---|---|
| `answer_question` | `question` (string, at most 2,000 characters) | `status` (`answered`, `not_addressed`, `needs_review`, `unavailable`, `error`), `refused` (true unless `answered`), `answer`, `citations` (clause id, citation, full clause text), `notes` (for example "Appendix F is referenced but was not provided"), `gate` (which check decided the outcome) |
| `list_questions` | none | the sample staff questions and the documents loaded |

## Install

1. Pick how it answers:
   - `MODEL_PROVIDER=claude` (default): needs `ANTHROPIC_API_KEY`, in the environment or in `.env` at the repo root.
   - `MODEL_PROVIDER=local`: needs Ollama with `qwen2.5:7b-instruct`; nothing leaves the machine.
   - `MODEL_PROVIDER=mock`: no keys; a stand-in model for trying the plumbing and the safety checks, not real answers.
2. Register the server.

Claude Code:

```bash
claude mcp add rfp-intelligence -e MODEL_PROVIDER=claude -- python3 /ABSOLUTE/PATH/TO/rfp-engine/mcp/server.py
```

Claude Desktop (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "rfp-intelligence": {
      "command": "python3",
      "args": ["/ABSOLUTE/PATH/TO/rfp-engine/mcp/server.py"],
      "env": { "MODEL_PROVIDER": "claude" }
    }
  }
}
```

Optional: `RFP_DATA_DIR` points at another folder holding the two RFP files; `MODEL_CALL_LOG` moves the log of every
model call (default `../flightlog/model_calls.jsonl`).

Then ask Claude, for example: "Using rfp-intelligence, what is the bid deposit, and has an amendment changed it?"

## Check it

```bash
python3 mcp/eval_via_mcp.py --provider claude --compare-direct
```

This starts the server as a subprocess, sends every case in `mcp/sample_golden.json` (8 cases on the sample RFP in
`data/`, 6 of them traps) through `tools/call`, and scores each with the engine's own `eval.run_eval.check`.
`--compare-direct` also calls the engine in-process and requires the same status, answer and citations, so any
difference between the wrapper and the engine fails the run. Model calls from this check go to a temporary log.

See `../README.md` for the results measured so far.

## Gaps, honestly

- **The three model-dependent traps have not been run through this wrapper with a real model.** A separate
  pre-registered real-model run of the engine (24 questions) scored 11 correct, 12 withheld, 1 wrong, missing its
  zero-wrong target; by hand 14 of 24 are right. See `../eval/RESULTS.md`. The wrapper adds no logic to the answer
  path and matches the engine exactly.
- **No confidence score.** The engine does not produce one and the wrapper does not invent one. What it gives
  instead is categorical: `status`, the `gate` that decided it, and `notes`. A calibrated score would be new engine
  work.
- **Documents load at start-up only.** Every RFP and amendment `.txt` in `data/` (or `RFP_DATA_DIR`) is read when
  the server starts. There is no tool to add a document mid-session; restart the server instead.
- **Retrieval is keyword-based** (stemming and a glossary, no embeddings). Questions phrased far from the RFP's wording
  can come back `not_addressed` when the answer is there.
- **The model's sentence is checked for figures, not for meaning.** A summary with only verbatim figures can still
  paraphrase a clause loosely; the citations carry the full clause text so the reader can check.
- **stdio only**, one client at a time, no auth. Fine for a local Claude Code or Desktop install; not a hosted
  service.
