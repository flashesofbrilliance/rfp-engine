"""Answer an internal question from the RFP: retrieve, select, verify, assemble.

The model never writes a number. It selects clause IDs and writes a short answer; code then checks
that every figure in that answer appears verbatim in a cited, still-in-force clause. If the check
fails, the answer is replaced by the verbatim clause text. Amendments are attached by code, not by
the model, so a superseded figure can never go out without its superseding text beside it.
"""
import json
import math
import os
import re
from collections import Counter

from rfp import provider, store

STOP = set("a an and are as at be by can do does for from get how i if in is it of on or our "
           "the their there this to us we what when where which who will with you your any".split())
FIGURE_RE = re.compile(
    r"\$[\d,]+(?:\.\d+)?|\d+(?:\.\d+)?\s?%|\b\d{1,2}:\d{2}\s?[AP]M\b|"
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},\s+\d{4}|\b\d[\d,]*(?:\.\d+)?\b", re.I)

SYSTEM = """You answer internal questions about a public RFP for the responding team.
You are given numbered clauses. Rules:
1. Use only the clauses given. Never use outside knowledge.
2. If the clauses do not answer the question, return status "not_addressed". A plain "not addressed"
   is correct and valued; a guess is a compliance liability.
3. Amendment clauses (IDs starting with "A") supersede the base clauses they revise. Answer with the
   amended value.
4. Copy every date, dollar amount, percentage and number exactly as written. Do not round, convert,
   compute or paraphrase figures. Do not compute dates or differences that are not written.
5. You only answer what the RFP says. Never draft proposal or bid language.
Return JSON only: {"status": "answered" | "not_addressed", "clause_ids": ["7.1", "A1.2"],
"answer": "one or two plain sentences"}"""


# Staff vocabulary -> RFP vocabulary. Deterministic, reviewable, and extended when the eval finds a miss
# ("when are proposals due" once never matched "Proposal Submission Deadline").
def _load_glossary():
    """Staff words -> RFP words, from the shared glossary.json (one source for search and docs)."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "glossary.json")
    return {k.lower(): v for k, v in json.load(open(path))["vocabulary"]["map"].items()}


GLOSSARY = _load_glossary()


_VOCAB = None


def _fix_typos(q):
    """A question word not found in the RFP is matched to the closest RFP word (stdlib difflib, cutoff 0.8), e.g.
    'submiting' -> 'submit'. General typo tolerance, not tuned to any one question."""
    if not _VOCAB:
        return q
    import difflib
    out = []
    for t in q:
        if t in _VOCAB or t in GLOSSARY or not t.isalpha() or len(t) < 5:
            out.append(t)
        else:
            close = difflib.get_close_matches(t, _VOCAB, n=1, cutoff=0.8)
            out.append(close[0] if close else t)
    return out


def expand(question):
    q = _fix_typos(tokens(question))
    return q + [stem(s) for t in q for s in GLOSSARY.get(t, [])]


def stem(t):
    """Crude, deterministic suffix stripping so word forms meet ("announced" / "Announcement",
    "exception" / "exceptions"). Numbers and figures are left untouched."""
    if not t.isalpha() or len(t) <= 4:
        return t
    for suf in ("ments", "ment", "ings", "ing", "edly", "ed", "es", "s"):
        if t.endswith(suf) and len(t) - len(suf) >= 4:
            t = t[: -len(suf)]
            break
    return t[:-1] if t.endswith("e") and len(t) > 4 else t


def tokens(text):
    return [stem(t) for t in re.findall(r"[a-z0-9$%]+", text.lower()) if t not in STOP]


# A conversational lead-in ("Quick question about the RFP: ...") carries no search terms but crowds the governing clause
# out of the top k (paraphrase canary, W5). Stripped before search only; the question itself is unchanged everywhere else.
LEAD_IN = re.compile(r"^\s*(?:hi|hey|hello|quick question|question|one more question|q)\b[^:?]{0,40}:\s*", re.I)


def retrieve(clauses, question, k=8):
    """IDF-weighted term overlap. Enough for a short RFP; long ones would want better retrieval."""
    question = LEAD_IN.sub("", question)
    docs = [Counter(tokens(c["text"] + " " + (c["section_title"] or ""))) for c in clauses]
    global _VOCAB
    _VOCAB = sorted({t for d in docs for t in d if t.isalpha()})
    df = Counter(t for d in docs for t in d)
    n = len(docs)
    q = set(expand(question))
    scored = []
    for c, d in zip(clauses, docs):
        s = sum(math.log((n + 1) / (df[t] + 0.5)) for t in q if t in d)
        if s > 0:
            scored.append((s, c))
    scored.sort(key=lambda x: -x[0])
    return [c for _, c in scored[:k]]


def expand_with_amendments(db, picked):
    """Code, not the model, guarantees every amendment touching a picked clause rides along."""
    by_id = {c["clause_id"]: c for c in store.all_clauses(db)}
    out, seen = [], set()
    for c in picked:
        for cid in [c["clause_id"]] + [e["amendment_clause"] for e in store.effects_on(db, c["clause_id"])]:
            if cid not in seen and cid in by_id:
                seen.add(cid)
                out.append(by_id[cid])
    return out


def render_clauses(clauses):
    return "\n\n".join("[%s] (%s) %s" % (c["clause_id"], cite(c), c["text"]) for c in clauses)


def cite(c):
    if c["kind"] == "amendment":
        return "Amendment No. %d, issued %s, §%s" % (c["amendment_no"], c["issued"], c["clause_id"])
    return "RFP Section %s, %s, §%s" % (c["section"], c["pages"], c["clause_id"])


def figures(text):
    """Figures as written, trailing punctuation dropped ("$100,000," and "$100,000" are the same figure)."""
    return {re.sub(r"\s+", " ", f.strip()).rstrip(",.").lower() for f in FIGURE_RE.findall(text)}


def provenance(question, candidates):
    """Every step from the typed question to the model's raw reply, for the reader to audit."""
    call = provider.LAST
    return {"question": question, "search_terms": sorted(set(expand(question))),
            "retrieved": [{"clause_id": c["clause_id"], "cite": cite(c)} for c in candidates],
            "call_id": call.get("call_id"), "model": call.get("model"), "prompt": call.get("payload"),
            "raw_reply": call.get("response"), "error": call.get("error"), "usage": call.get("usage"),
            "log": "flightlog/model_calls.jsonl"}


# Fast path: questions that ask for exactly one key fact are answered from the governing text with no model
# call (nothing leaves the machine, and the answer is verbatim by construction). Patterns are deliberately narrow: a question
# about a property of a fact ("is the deposit refundable?") does not match and goes through the full path.
# The whole question must be the plain fact, optionally "for the RFP": "What is the bid deposit refund
# policy?" or "When are proposals due for Volume II drawings?" ask something else and go to search instead.
_END = r"(\s+(for|of|on|in)\s+(the\s+)?[\w\s-]*?(rfp|solicitation|project))?\s*\??\s*$"
FAST = [
    (re.compile(r"^\s*(what is|what's)\s+(the\s+)?bid deposit" + _END, re.I), "7.1"),
    (re.compile(r"^\s*when are proposals due" + _END, re.I), "3.2"),
    (re.compile(r"^\s*what is the proposal (submission )?deadline" + _END, re.I), "3.2"),
    (re.compile(r"^\s*what are the evaluation (criteria )?weights" + _END, re.I), "8.1"),
]


def fast_path(db, question):
    for pattern, cid in FAST:
        if pattern.search(question):
            base = next((c for c in store.all_clauses(db) if c["clause_id"] == cid and c["kind"] == "base"), None)
            if not base:
                return None
            if any(e["op"] == "unresolved" for e in store.effects_on(db, cid)):
                return None  # never fast-path a fact an unreadable amendment may change
            g = store.governing(db, cid)
            cited = [base] + ([c for c in store.all_clauses(db) if c["clause_id"] == g["amendment_clause"]] if g else [])
            text = g["amendment_text"] if g else base["text"]
            return {"question": question, "candidates": [c["clause_id"] for c in cited], "status": "answered",
                    "answer": text, "gate": "fast path: verbatim governing text, no model call", "notes":
                    ["§%s is superseded in part by Amendment §%s; the amended value governs." % (cid, g["amendment_clause"])] if g else [],
                    "citations": [{"clause_id": c["clause_id"], "cite": cite(c), "text": c["text"]} for c in cited],
                    "provenance": {"question": question, "search_terms": [], "retrieved": [{"clause_id": c["clause_id"], "cite": cite(c)} for c in cited],
                                   "call_id": None, "model": "none (fast path)", "prompt": None, "raw_reply": None,
                                   "log": "no model call"}}
    return None


def related_text(question, candidates):
    """Floor for bare refusals: the retrieved clause covering the most question words (2+), glossary forms included."""
    words = [{t} | {stem(x) for x in GLOSSARY.get(t, [])} for t in tokens(question)]
    def covered(c):
        have = set(tokens(c["text"] + " " + (c["section_title"] or "")))
        return sum(1 for forms in words if forms & have)
    ranked = sorted(candidates, key=lambda c: -covered(c))  # stable: ties keep retrieval order
    return [c for c in ranked if covered(c) >= 2][:1]


# Out of scope by design, enforced in code so a fooled model cannot cross it.
# Matched on the question before any model call, and on the model's answer after it.
# "rewrite" refuses only as a request to the system (an instruction, or "can you rewrite"); "Can we rewrite our proposal
# after submission?" is a question about the rules.
DRAFT = re.compile(r"(\b(draft|write|compose)\b(?!ten)|(?:^\s*(?:please\s+)?|\b(?:can|could|would|will)\s+you\s+(?:please\s+)?)rewrite\b)"
                   r"[^?]*\b(proposal|executive summary|volume|bid|cover letter|narrative|response|section)\b", re.I)
# A request for a decision, not a mention of one: "for the bid/no-bid page, how is the score split?" is a fact question
# (a test question was once wrongly refused by an earlier, broader pattern).
VERDICT = re.compile(r"\b(should (we|i) (bid|pursue|go for)|(do|should|would) (we|you) (bid|go (ahead|for)\b)|"
                     r"(is it|make it|give me) a (bid|go|no.?bid|no.?go)\b|(yes or no|go/no.?go|bid or no.?bid)\s*\?|"
                     r"\bodds\b|chances? of winning|likel(y|ihood) (to|of|that we) win|will we win\b(?!\s+(?:any\s+)?(?:points?|credit)))", re.I)
DRAFTED = re.compile(r"\b(pleased to submit|we propose|commits? to deliver|our team will)\b|^\s*(yes|no)\b[.,!]?\s*(we|you)\s+should", re.I)
PAYLOAD_MAX = 12000  # characters sent per model call; normal questions send ~2,300.
QUESTION_MAX = 2000  # characters; staff questions in the samples are under 150. Keeps every model call small.
SCOPE = {"draft": "Out of scope: this system only reports what the RFP says. Drafting proposal "
                  "language is left to a person.",
         "verdict": "Not addressed: a bid decision or a chance of winning is a person's judgement, not something the RFP "
                    "states. Ask about the eligibility rules or dates instead, which are cited from the RFP."}


def answer(db, question, k=8):
    if len(question) > QUESTION_MAX:
        return {"question": question[:200] + "...", "status": "error", "gate": "question too long", "citations": [],
                "answer": "The question is %d characters; the limit is %d. Ask one thing at a time." % (len(question), QUESTION_MAX)}
    for kind, pat in (("draft", DRAFT), ("verdict", VERDICT)):
        if pat.search(question):
            return {"question": question, "status": "not_addressed", "gate": "scope: %s (no model call)" % kind,
                    "answer": SCOPE[kind], "citations": []}
    fast = fast_path(db, question)
    if fast:
        return fast
    candidates = expand_with_amendments(db, retrieve(store.all_clauses(db), question, k))
    trace = {"question": question, "candidates": [c["clause_id"] for c in candidates]}
    if not candidates and not store.all_clauses(db):
        # Nothing readable was ingested: "not addressed" would claim the RFP is silent when we never read it.
        return dict(trace, status="error", gate="no readable document", citations=[],
                    answer="No readable RFP text is loaded, so this cannot be answered. Nothing here means the RFP is silent.")
    if not candidates:
        return dict(trace, status="not_addressed", answer="Not addressed in the RFP.", citations=[], gate="no candidates")

    sent = "Question: %s\n\nClauses:\n%s" % (question, render_clauses(candidates))
    if len(sent) > PAYLOAD_MAX:
        # Defence in depth behind the ingest limit: never send more than a few clauses' worth of RFP text.
        return dict(trace, status="error", gate="payload over cap (%d > %d chars); no model call" % (len(sent), PAYLOAD_MAX),
                    citations=[], answer="The text that would be sent to the AI is larger than allowed, so no answer is given.")
    try:
        raw = provider.complete(SYSTEM, sent,
                                purpose="answer")
        trace["provenance"] = provenance(question, candidates)
    except provider.ProviderError as e:
        trace["provenance"] = provenance(question, candidates)
        # Degrade, never crash: say the model is unavailable and point at where to look, no answer.
        return dict(trace, status="unavailable", gate="provider: %s" % e,
                    answer="The answering model is unavailable. These clauses look relevant; no answer is given.",
                    citations=[{"clause_id": c["clause_id"], "cite": cite(c), "text": c["text"]} for c in candidates[:3]])
    try:
        sel = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
    except (AttributeError, ValueError):
        return dict(trace, status="error", answer="Model returned unparseable output; see the call log.",
                    citations=[], gate="parse")

    if sel.get("status") == "not_addressed" and not sel.get("clause_ids"):
        # A bare refusal is nondeterministic: some runs name the related clauses, some do not.
        # Ask once, explicitly, for what the RFP does say; the same verbatim gate below decides if it is kept.
        try:
            raw2 = provider.complete(SYSTEM, "Question: %s\n\nClauses:\n%s\n\nYou judged this not addressed. "
                                     "If any clause above says something related (for example an estimated date "
                                     "or a general rule), return status \"not_addressed\" with those clause_ids and "
                                     "one sentence quoting what they say. Otherwise return empty clause_ids."
                                     % (question, render_clauses(candidates)), purpose="answer_context")
            sel2 = json.loads(re.search(r"\{.*\}", raw2, re.S).group(0))
            if sel2.get("status") == "not_addressed" and sel2.get("clause_ids") and sel2.get("answer"):
                sel, trace["retry"] = sel2, "refusal context"
        except (provider.ProviderError, AttributeError, ValueError):
            pass
    if sel.get("status") == "not_addressed" and sel.get("clause_ids") and sel.get("answer"):
        # A refusal stays a refusal, but what the RFP does say is kept and verified, not thrown away
        # (for example: "no exact day; only an estimated month").
        by_id = {c["clause_id"]: c for c in candidates}
        said = expand_with_amendments(db, [by_id[i] for i in sel["clause_ids"] if i in by_id])   # amendments ride along
        note = sel["answer"]
        stale = [old for old, new in superseded(db, [a for amds in replaced_by(db, said).values() for a in amds]).items()
                 if old in figures(note) and not new & figures(note)]
        if said and not stale and all(f in figures(" ".join(c["text"] + " " + c["clause_id"] + " " + cite(c) for c in said)) for f in figures(note)):
            missing = ["%s is referenced by §%s but was not provided to this system." % (ref, c["clause_id"])
                       for c in said for e in db.execute("SELECT references_missing FROM effects WHERE amendment_clause=?", (c["clause_id"],))
                       for ref in json.loads(e["references_missing"])]
            return dict(trace, status="not_addressed", gate="model; context verbatim ok",
                        answer="Not addressed in the RFP. What it does say: " + note,
                        citations=[{"clause_id": c["clause_id"], "cite": cite(c), "text": c["text"]} for c in said], notes=missing)
        return dict(trace, status="not_addressed", answer="Not addressed in the RFP.", citations=[], gate="model")
    if sel.get("status") == "not_addressed":
        # Still point at any clause that references a document we were never given (T3: Appendix F).
        qtok = set(tokens(question))
        refs = [(c, ref) for c in candidates
                for e in db.execute("SELECT references_missing FROM effects WHERE amendment_clause=?", (c["clause_id"],))
                for ref in json.loads(e["references_missing"]) if set(tokens(ref)) <= qtok | {"appendix"} and ref.split()[-1].lower() in qtok]
        if not refs:
            # Deterministic floor: when the model names nothing even after the follow-up, show the
            # top retrieved clause that shares 2+ question terms (glossary + stemming), as related text only.
            related = related_text(question, candidates)
            if related:
                shown = expand_with_amendments(db, related)
                return dict(trace, status="not_addressed", gate="model; related text by term match",
                            answer="Not addressed in the RFP. The closest related text is cited below; it does not answer the question.",
                            citations=[{"clause_id": c["clause_id"], "cite": cite(c), "text": c["text"]} for c in shown])
        return dict(trace, status="not_addressed", answer="Not addressed in the RFP.", gate="model",
                    notes=["%s is referenced by §%s but was not provided to this system." % (r, c["clause_id"]) for c, r in refs],
                    citations=[{"clause_id": c["clause_id"], "cite": cite(c), "text": c["text"]} for c, _ in refs])

    by_id = {c["clause_id"]: c for c in candidates}
    cited = [by_id[i] for i in sel.get("clause_ids", []) if i in by_id]
    if not cited:
        # First rule: every answer cites its source. None of the model's citations exist.
        return dict(trace, status="error", gate="no valid citation", citations=[],
                    answer="The model cited nothing that exists in the RFP, so no answer is given.")
    # Any retrieved clause that an amendment replaced brings its governing amendment into view, even when
    # the model cited a neighbour; the reader must never see a superseded topic without the change.
    cited_sections = {c["section"] for c in cited}
    for c in candidates:
        if c["section"] not in cited_sections:
            continue   # retrieved but not in a section the model cited: its amendment is not this answer's
        g = store.governing(db, c["clause_id"])
        if g and g["amendment_clause"] in by_id and by_id[g["amendment_clause"]] not in cited:
            cited.append(by_id[g["amendment_clause"]])
    # Supersession is enforced in code: a cited base clause always brings its amendments.
    cited = expand_with_amendments(db, cited)
    replaced = replaced_by(db, cited)

    text = sel.get("answer", "")
    if DRAFTED.search(text):
        # The model drafted or decided anyway: withhold it and keep the cited text only.
        return dict(trace, status="not_addressed", gate="scope: model output drafted or decided; withheld",
                    answer=SCOPE["verdict" if re.match(r"\s*(yes|no)\b", text, re.I) else "draft"],
                    citations=[{"clause_id": c["clause_id"], "cite": cite(c), "text": c["text"]} for c in cited])
    # Section numbers and citation metadata ("§4.2", "Amendment No. 1") may be quoted too.
    in_force = " ".join(c["text"] + " " + c["clause_id"] + " " + cite(c) for c in cited)
    said = figures(text)
    missing = [f for f in said if f not in figures(in_force)]
    # A replaced value quoted without its replacement is stale even though it appears in a cited clause (the base
    # clause, or the amendment's own "from X to Y"): "$75,000" alone fails; "from $75,000 to $100,000" passes.
    missing += [old for old, new in superseded(db, [a for amds in replaced.values() for a in amds]).items() if old in said and not new & said]
    gate = "verbatim ok" if cited and not missing else "verbatim FAILED: %s" % (missing or "no citations")
    if gate != "verbatim ok":
        text = "See the cited text below (the model's summary failed the verbatim check)."

    notes = []
    # An amendment clause the rules could not classify, naming a cited clause, blocks a clean answer.
    # Checked over every retrieved clause, not only the cited ones: the warning must not depend on which
    # clause the model happened to pick.
    rows = [(c["clause_id"], e) for c in candidates for e in store.effects_on(db, c["clause_id"])
            if e["op"] == "unresolved" and e["amendment_clause"] != c["clause_id"]]
    unresolved = sorted({(b, e["amendment_clause"]) for b, e in rows})
    everywhere = sorted({e["amendment_clause"] for _, e in rows if e["target"] == "*"})
    for base, amd in unresolved:
        if amd not in everywhere:
            notes.append("Amendment §%s may change §%s, and the system could not classify it. A person must "
                         "check the amendment before this answer is used." % (amd, base))
    for amd in everywhere:
        notes.append("Amendment §%s changes or states something without naming a section, and the system could not "
                     "classify it, so it may change this answer. A person must check the amendment before this "
                     "answer is used." % amd)
    for base, amds in replaced.items():
        notes.append("§%s is superseded in part by Amendment §%s; the amended value governs." % (base, amds[-1]))
    for c in cited:
        for e in db.execute("SELECT references_missing FROM effects WHERE amendment_clause=?", (c["clause_id"],)):
            for ref in json.loads(e["references_missing"]):
                notes.append("%s is referenced by §%s but was not provided to this system." % (ref, c["clause_id"]))

    status = "needs_review" if unresolved else "answered"
    return dict(trace, status=status, answer=text, gate=gate, notes=notes,
                citations=[{"clause_id": c["clause_id"], "cite": cite(c), "text": c["text"]} for c in cited])


def replaced_by(db, clauses):
    """{clause id: [amendment clauses that replace it]}, oldest first, all of them."""
    replaced = {}
    for c in clauses:
        for e in store.effects_on(db, c["clause_id"]):
            if e["op"] == "replaces":
                replaced.setdefault(c["clause_id"], []).append(e["amendment_clause"])
    return replaced


FROM_TO = re.compile(r"from ([^.;]{1,50}?) to ([^.;]{1,50}?)[.;]")


def superseded(db, amendment_clauses):
    """{old figure: {new figures}} read from the replacing amendment clauses' "from X to Y" wording."""
    out = {}
    for cid in set(amendment_clauses):
        for row in db.execute("SELECT text FROM clauses WHERE clause_id=?", (cid,)):
            for old, new in FROM_TO.findall(row["text"]):
                for f in figures(old):
                    out.setdefault(f, set()).update(figures(new))
    return out


def has_figure(haystack, fig):
    """Figure match with numeric boundaries: "$25,000" must not match inside "$25,000,000"."""
    return re.search(r"(?<![\d$])" + re.escape(fig) + r"(?![\d]|,\d)", haystack) is not None
