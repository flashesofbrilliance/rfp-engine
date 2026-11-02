"""Model providers behind one function. Every call's exact payload and usage is logged, so
anyone can see exactly what left the machine.

MODEL_PROVIDER=claude (default) calls the Anthropic Messages API over HTTPS.
MODEL_PROVIDER=local calls Ollama on localhost; nothing leaves the machine.
Stdlib urllib only: one fewer SDK to patch.
"""
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
CALL_LOG = os.environ.get("MODEL_CALL_LOG", os.path.join(ROOT, "flightlog", "model_calls.jsonl"))
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")
LOCAL_MODEL = os.environ.get("LOCAL_MODEL", "qwen2.5:7b-instruct")
# USD per million tokens (input, output). Source: Anthropic model/pricing table as cached in the
# claude-api skill, 2026-10-06. Re-verify on
# the live pricing page before quoting externally. Before 2026-10-10 this held $3/$15 from memory.
PRICES = {"claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50), "claude-haiku-4-5": (1.0, 5.0)}


class ProviderError(Exception):
    pass


# The most recent call's log entry, so callers can attach the exact prompt and reply to their result.
LAST = {}



def claude_key(root=None):
    """The Claude key from the environment or .env (rfp/config.py)."""
    from rfp.config import ConfigError, env
    try:
        key = env("ANTHROPIC_API_KEY", root)
    except ConfigError as e:
        raise ProviderError(str(e))
    if not key:
        raise ProviderError("ANTHROPIC_API_KEY is not set, in the environment or in .env; or answer on this machine with --provider local (needs Ollama and: ollama pull qwen2.5:7b-instruct), or try the pipeline with --provider mock")
    return key


def _post(url, body, headers, timeout=120, retries=2):
    data = json.dumps(body).encode()
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, headers={"content-type": "application/json", **headers})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode()[:300]
            if e.code in (429, 500, 502, 503, 529) and attempt < retries:
                time.sleep(2 ** attempt * 2)
                continue
            raise ProviderError("HTTP %d from %s: %s" % (e.code, url, detail))
        except urllib.error.URLError as e:
            if attempt < retries:
                time.sleep(2)
                continue
            raise ProviderError("cannot reach %s: %s" % (url, e.reason))


def _log(entry):
    os.makedirs(os.path.dirname(CALL_LOG), exist_ok=True)
    with open(CALL_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _mock(user):
    """Deterministic stand-in model for the test harness ($0). Picks the first candidate clause and
    quotes its first sentence verbatim, then applies MOCK_FAULT to test the guardrails downstream:
    none | timeout | garbage | wrong_figure | fake_citation | refuse, and the fooled-model
    modes invent | draft | verdict."""
    import re
    fault = os.environ.get("MOCK_FAULT", "none")
    if fault == "timeout":
        raise ProviderError("mock timeout: provider did not respond")
    if fault == "garbage":
        return "Sure! The answer is probably around seventy-five thousand."
    if fault == "refuse":
        return json.dumps({"status": "not_addressed", "clause_ids": [], "answer": ""})
    # A fooled model: it obeys the attacker but can only cite clauses it was shown.
    first = re.search(r"^\[([^\]]+)\]", user, re.M)
    real = first.group(1) if first else "1.1"
    if fault == "invent":
        return json.dumps({"status": "answered", "clause_ids": [real], "answer": "The issuer will likely accept $80,000 or 12% less."})
    if fault == "draft":
        return json.dumps({"status": "answered", "clause_ids": [real],
                           "answer": "Our company is pleased to submit this proposal and commits to deliver the project on time."})
    if fault == "verdict":
        return json.dumps({"status": "answered", "clause_ids": [real], "answer": "Yes. We should bid on this RFP."})
    m = re.search(r"^\[([^\]]+)\] \([^)]*\) (.+)$", user, re.M)
    if not m:
        return json.dumps({"status": "not_addressed", "clause_ids": [], "answer": ""})
    cid = m.group(1)
    sentences = re.split(r"(?<=\.)\s+(?=[A-Z])", m.group(2))
    # Quote the first sentence that carries a figure, so figure faults have something to corrupt.
    sentence = next((s for s in sentences if re.search(r"\$\d|\d%|\d{2,}", s)), sentences[0])
    if fault == "wrong_figure":
        sentence = re.sub(r"\$(\d)", lambda x: "$" + str((int(x.group(1)) + 1) % 10), sentence, count=1)
    if fault == "fake_citation":
        cid = "99.9"
    return json.dumps({"status": "answered", "clause_ids": [cid], "answer": sentence})


def complete(system, user, purpose, max_tokens=800):
    """Returns the model's text. Logs payload, usage, cost and latency, success or failure."""
    provider = os.environ.get("MODEL_PROVIDER", "claude")
    t0 = time.time()
    import uuid
    entry = {"call_id": uuid.uuid4().hex[:10], "t": datetime.now(timezone.utc).isoformat(), "provider": provider,
             "purpose": purpose, "payload": {"system": system, "user": user}}
    LAST.clear()
    LAST.update(entry)
    try:
        if provider == "mock":
            entry["model"] = "mock:" + os.environ.get("MOCK_FAULT", "none")
            text, usage, usd = _mock(user), {"input_tokens": 0, "output_tokens": 0}, 0.0
        elif provider == "local":
            entry["model"] = LOCAL_MODEL
            r = _post("http://localhost:11434/api/chat", {
                "model": LOCAL_MODEL, "stream": False, "format": "json",
                "options": {"temperature": 0},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}, {})
            text = r["message"]["content"]
            usage = {"input_tokens": r.get("prompt_eval_count"), "output_tokens": r.get("eval_count")}
            usd = 0.0
        else:
            key = claude_key()
            entry["model"] = CLAUDE_MODEL
            r = _post("https://api.anthropic.com/v1/messages", {
                "model": CLAUDE_MODEL, "max_tokens": max_tokens, "system": system,
                "messages": [{"role": "user", "content": user}]},
                {"x-api-key": key, "anthropic-version": "2023-06-01"})
            text = "".join(b.get("text", "") for b in r["content"])
            usage = {k: r["usage"].get(k) for k in ("input_tokens", "output_tokens")}
            pin, pout = PRICES.get(CLAUDE_MODEL, (None, None))
            usd = None if pin is None else round(
                (usage["input_tokens"] * pin + usage["output_tokens"] * pout) / 1e6, 6)
        entry.update(ok=True, response=text, usage=usage, usd=usd, latency_s=round(time.time() - t0, 2))
        return text
    except Exception as e:
        entry.update(ok=False, error=str(e), latency_s=round(time.time() - t0, 2))
        if isinstance(e, ProviderError):
            raise
        # A read timeout, an unreadable body or a reply missing a field must not crash the caller:
        # every failure reaches answer.py as ProviderError, which marks the question "AI unavailable".
        raise ProviderError("%s: %s" % (type(e).__name__, e)) from e
    finally:
        LAST.update(entry)
        _log(entry)
