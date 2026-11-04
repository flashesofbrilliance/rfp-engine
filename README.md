# RFP answering engine (RFP-O-Matic)

Project page: [good.arcs.care/rfp-engine](https://good.arcs.care/rfp-engine) · Author: [Zach Harris](https://zach.md)

Videos: [full walkthrough, 2:52](https://youtu.be/MzTpUPgtQ88) · [the bench, 2:15](https://youtu.be/mQwATG-ZfQE) · [when the check is too strict, 0:51](https://youtu.be/LHfx5utxaP0) · [how it was built, 2:23](https://youtu.be/7IAyXTOrNh4)

Ask a question about a solicitation document and its amendments. Get back an answer with the exact clauses it rests
on, or a refusal. The engine is built so that it would rather say "not addressed" than guess.

Python 3.9 or newer, standard library only. Nothing to `pip install`.

## What it does

1. **Reads the documents with rules, not a model.** Each RFP and amendment in `data/` is split into numbered clauses.
   An amendment that says "Section 7.1 (Bid Deposit) is revised" is recorded as superseding 7.1. Amendment wording
   the rules cannot classify is flagged for a person, never guessed at.
2. **Finds the clauses for a question** by keyword search with stemming and a small glossary.
3. **Asks a model to pick clauses and write one sentence**, then checks the result in code before anyone sees it.

The documents in `data/` are a short fictional RFP and amendment written for this sample.

## The trust rules, enforced in code

| Rule | How it is enforced |
|---|---|
| No answer without a source | If the model cites a clause id that does not exist, the result is `error` with no answer. |
| Figures are quoted, never computed | Every dollar amount, date and percentage in the answer must appear word for word in a cited clause, or the summary is withheld and only the clause text is returned. |
| An amended value always wins | Citing a base clause pulls in the amendment that replaced it. Quoting the old value without the new one fails the check above. |
| Refuse rather than bluff | "Not addressed in the RFP" is a valid answer. A question about an appendix that was never provided says so. |
| No drafting, no bid verdicts | Requests to draft proposal language or decide whether to bid are refused before any model call. If the model drafts or decides anyway, its text is withheld. |
| Fail closed | No model available means status `unavailable` with the relevant clauses and no answer. |

Every result carries `status`, `answer`, `citations` (clause id, citation and full clause text), `notes` and `gate`
(the check that decided the outcome), so a reviewer can see why it answered or refused.

## Provenance: proof, not trust

Answers through MCP also carry a `receipt`, and every citation carries a `proof`, so anyone can check an answer
without trusting this tool:

- **Clause proofs.** Each document (the RFP, each amendment) is hashed into a Merkle root over its clauses. Each
  citation carries the path from its clause to that root, so a quoted clause that was edited, or never in the
  document, fails.
- **Amendment chain.** The document roots are chained in order (base, then amendments by number). The chain head names
  the exact package an answer used, so a missing, extra or edited amendment is caught.
- **Receipt.** A SHA-256 digest over the question, status, answer, gate, cited clauses, package and a hash of the
  engine's own code. Optionally signed with Ed25519: install PyNaCl (`pip install pynacl`) and set `RFP_SIGNING_KEY`
  (a 32-byte private key in hex). Without both, receipts are hashed and say `unsigned` with the reason.

Check a saved answer: `python3 tools/verify_receipt.py answer.json --data data/ [--public-key HEX]` (PASS, or each
failure by clause). Tests, including deliberate tampering: `python3 -m unittest discover -s tests`.

## How you use it

`mcp/` is a local stdio MCP server with two tools, `answer_question` and `list_questions`, for Claude Code or Claude
Desktop. It loads documents with `loader.load()` and calls `answer.answer()` unchanged. Setup is in `mcp/README.md`.

## Results, measured on 2026-10-29 in this copy

All runs below are on the sample RFP in `data/`. Commands are in `mcp/README.md`.

**Trap and golden cases through the MCP server** (`mcp/eval_via_mcp.py`, 8 cases, 6 of them traps):

| Provider | Result |
|---|---|
| `mock` (no model) | 5 of 5 deterministic cases pass: amended deposit, extended deadline, weights, drafting refused, bid verdict refused. The 3 model-dependent traps are skipped. |
| `claude` with no API key | Same 5 pass. The 3 model-dependent traps (prompt injection, currency conversion, missing Appendix G) return `unavailable` with no answer. That is the fail-closed rule working, not a pass. |
| `claude` with a key | This harness was not run with a key. A separate pre-registered real-model run was (below). |

In every run the MCP server's results were identical to calling the engine directly (`--compare-direct`).

**Injected model faults** (the `mock` provider can misbehave on purpose, `MOCK_FAULT=...`), each sent through the MCP
server:

| Fault | Outcome |
|---|---|
| Model times out | `unavailable`, no answer, relevant clauses listed |
| Model returns garbage | `error`, no answer |
| Model cites a clause that does not exist | `error`, "cited nothing that exists in the RFP" |
| Model invents figures ($80,000, 12%) | Summary withheld: verbatim check failed |
| Model changes a dollar figure | Summary withheld: verbatim check failed on `$30,000` |
| Model quotes the superseded deposit ($20,000) | Summary withheld: verbatim check failed on `$20,000` |
| Model drafts proposal text | Withheld, refusal returned |
| Model says "Yes. We should bid" | Withheld, refusal returned |

## Honest gaps

- **Real-model run missed its target.** A pre-registered run (`eval/run_prereg.py`, 24 questions, `claude-sonnet-5-5`,
  2026-10-30, $0.0547) scored **11 correct, 12 withheld, 1 wrong**. The target, set in advance, was zero wrong; it was
  missed (M1 gave the amended $35,000 but also named the superseded $20,000). A hand check found A3, A5 and I1 were
  correct answers withheld by an over-strict figure check, so 14 of 24 are right by hand; the scored result stands.
  See `eval/RESULTS.md`. The MCP trap harness above has still not been run with a key.
- **No confidence score.** Results are categorical (status, gate, notes). A calibrated score would be new work.
- **Keyword retrieval.** No embeddings. A question worded far from the document can come back "not addressed" when
  the answer is there.
- **Figures are checked, meaning is not.** A summary with only verbatim figures can still paraphrase a clause
  loosely. Full clause text is returned so the reader can check.
- **Plain-text documents in one numbering style** (`SECTION n`, clauses `n.n`, amendments `A1.n`). PDFs and other
  layouts need an ingest step first. A file in the data folder that is not `.txt` (or a subfolder) stops the load and
  is named in the error, so an amendment saved as Word or PDF is never silently left out.
- **Provenance proves consistency, not officialness.** A receipt shows the quoted clauses are in the documents that
  were loaded. That those documents are the agency's official copies needs `--data` pointed at a copy you trust, or
  the agency's signature. Receipts are not yet timestamped or anchored anywhere public (an EAS attestation on an
  Ethereum L2 is designed, not built), and signing keys are yours to manage.
- **Built for RFPs, not contracts.** Amendment handling (revise, supplement, unchanged) maps onto contract
  amendments, but clause types such as indemnity or termination have no special handling.

## Layout

| Path | What it is |
|---|---|
| `source/rfp/` | The engine: `parse.py`, `resolve.py` (amendments), `answer.py` (search, model call, checks), `store.py`, `provider.py` (claude, local Ollama, mock) |
| `source/rfp/provenance.py` | Clause Merkle proofs, the amendment hash chain, answer receipts and their check |
| `source/loader.py` | Loads the documents in `data/` |
| `tools/verify_receipt.py` | Checks a saved answer's proofs and receipt, optionally against official documents |
| `tests/` | Provenance tests, including deliberate tampering (`python3 -m unittest discover -s tests`) |
| `mcp/` | Claude MCP server, its eval runner and the sample trap cases |
| `data/` | The fictional sample RFP, its amendment and sample questions |
