"""RFP answering engine as a local MCP server (stdio, JSON-RPC 2.0, one message per line).

Standard library only, like the engine: no MCP SDK. The engine is called as-is (rfp.answer.answer); this file
only loads the documents, forwards the question and reshapes the result. Trust rules live in the engine and are
not re-implemented or relaxed here: no answer without a cited clause, figures verbatim or withheld, refuse
rather than guess.

Settings (environment): MODEL_PROVIDER claude|local|mock (default claude), ANTHROPIC_API_KEY or the repo .env,
RFP_DATA_DIR (default: ../data; every RFP and amendment .txt in it is loaded), MODEL_CALL_LOG (default: the engine's flightlog/model_calls.jsonl).
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "source"))

from rfp import answer as engine  # noqa: E402
from rfp import provenance  # noqa: E402
from loader import documents, load  # noqa: E402

DATA = os.environ.get("RFP_DATA_DIR", os.path.join(HERE, "..", "data"))
VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

TOOLS = [
    {"name": "answer_question",
     "description": "Answer one question about the loaded RFP and its amendments. Returns the answer with the exact "
                    "clauses it rests on, or a refusal. status is 'answered' only when every figure in the answer "
                    "appears word for word in a cited clause; otherwise the summary is withheld and only the cited "
                    "text is returned. 'not_addressed' means the RFP does not say; do not fill the gap. "
                    "'needs_review' means an amendment the rules could not classify may change the answer. "
                    "Quote the citations to the user; never restate a figure that is not in them.",
     "inputSchema": {"type": "object", "properties": {"question": {"type": "string", "maxLength": engine.QUESTION_MAX}},
                     "required": ["question"]}},
    {"name": "list_questions",
     "description": "The sample staff questions shipped with the RFP package, and the documents loaded.",
     "inputSchema": {"type": "object", "properties": {}}},
]

_db = None


def db():
    global _db
    if _db is None:
        _db = load(DATA)  # every RFP and amendment .txt in the folder, base first, amendments in order
    return _db


def answer_question(question):
    r = provenance.with_receipt(db(), engine.answer(db(), question))  # adds clause proofs and a receipt; answer unchanged
    return {"status": r["status"],
            "refused": r["status"] != "answered",
            "answer": r["answer"],
            "citations": r.get("citations", []),
            "notes": r.get("notes", []),
            "gate": r.get("gate"),
            "receipt": r["receipt"]}


def list_questions():
    text = open(os.path.join(DATA, "sample_questions.txt"), encoding="utf-8").read()
    qs = [" ".join(m.group(2).split()) for m in re.finditer(r"^(Q\d+)\.\s+(.*?)(?=^Q\d+\.|\Z)", text, re.M | re.S)]
    return {"documents": [f for f, _ in documents(DATA)], "questions": qs}


def call(name, args):
    if name == "answer_question":
        q = args.get("question")
        if not isinstance(q, str) or not q.strip():
            raise ValueError("question must be a non-empty string")
        return answer_question(q)
    if name == "list_questions":
        return list_questions()
    raise KeyError(name)


def handle(msg):
    method, params = msg.get("method"), msg.get("params") or {}
    if method == "initialize":
        v = params.get("protocolVersion")
        return {"protocolVersion": v if v in VERSIONS else VERSIONS[0],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "rfp-intelligence", "version": "0.1.0"}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        try:
            out = call(params.get("name"), params.get("arguments") or {})
        except KeyError as e:
            raise LookupError("unknown tool %s" % e)
        except Exception as e:
            # Degrade, never crash: the client sees an error result, not a guessed answer.
            return {"content": [{"type": "text", "text": "Error: %s" % e}], "isError": True}
        return {"content": [{"type": "text", "text": json.dumps(out, indent=1)}],
                "structuredContent": out, "isError": False}
    raise NotImplementedError(method)


def main():
    out, sys.stdout = sys.stdout, sys.stderr  # stray prints from the engine must not corrupt the protocol stream
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            if "id" not in msg:
                continue  # notification (e.g. notifications/initialized): no reply
            try:
                reply = {"jsonrpc": "2.0", "id": msg["id"], "result": handle(msg)}
            except LookupError as e:
                reply = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32602, "message": str(e)}}
            except NotImplementedError as e:
                reply = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "method not found: %s" % e}}
        out.write(json.dumps(reply) + "\n")
        out.flush()


if __name__ == "__main__":
    main()
