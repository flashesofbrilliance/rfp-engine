# AGENTS.md

Instructions for coding agents working in this repository. Humans start at `README.md`; language models at `llms.txt`.

## What this is
An RFP answering engine: questions about a solicitation and its amendments get an answer with the exact clauses it rests on, or a refusal. Python 3.9+, standard library only.

## Run
- Ask a question through MCP: `claude mcp add rfp-intelligence -e MODEL_PROVIDER=mock -- python3 /ABSOLUTE/PATH/mcp/server.py`
- Check everything: `python3 mcp/eval_via_mcp.py --provider mock --compare-direct` (no keys, $0). It must end with `5/5 passed` and `identical on every case run`.
- Provenance tests (including deliberate tampering): `python3 -m unittest discover -s tests`. Must end `OK`.
- Check a saved answer: `python3 tools/verify_receipt.py answer.json --data data/`.
- With a real model: set `ANTHROPIC_API_KEY` and use `--provider claude`, or `--provider local` with Ollama.

## Layout
- `source/rfp/parse.py`: documents into numbered clauses
- `source/rfp/resolve.py`: which text governs after amendments
- `source/rfp/answer.py`: retrieval, model call, and every check
- `source/rfp/provider.py`: claude, local (Ollama), mock (with `MOCK_FAULT` to inject failures)
- `source/rfp/provenance.py`: clause Merkle proofs, amendment hash chain, answer receipts, `verify()`
- `source/loader.py`: loads `data/`
- `mcp/server.py`: stdio MCP server (`answer_question`, `list_questions`)
- `data/`: a short fictional RFP and amendment

## Rules that must not regress
- No answer without a citation to a clause that exists.
- Every $, date and % in an answer appears word for word in a cited clause, or the summary is withheld.
- An amended value always wins; quoting the superseded value alone fails.
- Drafting proposal language and bid/no-bid verdicts are refused in code, before and after the model call.
- No model reachable means status `unavailable` and no answer.
- Every citation returned through MCP carries a Merkle proof that verifies, and the receipt commits to the question,
  status, answer, cited clauses and the amendment chain. A change that breaks `provenance.verify` on an honest
  answer, or lets a tampered one pass, is a regression.

## Agent harnesses
This file is the shared base (Codex and Hermes read it directly). Harness-specific notes:
- Claude Code: `CLAUDE.md` (imports this file, adds the `claude mcp add` line)
- OpenAI Agents SDK and Responses API: `agents/openai.md`
- Hermes: `agents/hermes.md`

## Conventions
- Standard library only. Do not add a dependency without asking the maintainer. One approved optional extra: PyNaCl,
  used only for Ed25519 receipt signing; everything works without it.
- Every behaviour change adds or updates a case in `mcp/sample_golden.json`; a guardrail change also gets a `MOCK_FAULT` check.
- Keep `mcp/server.py` a thin wrapper: engine logic belongs in `source/rfp/`.
- Never commit `.env`, API keys or `flightlog/` call logs.
