"""Pass/fail check for one golden case. Used by mcp/eval_via_mcp.py.

A case passes only if status, required citations, required figures, forbidden figures and required notes all hold.
"""
from rfp.answer import has_figure


def check(case, r):
    fails = []
    # A carve-out the RFP only partly settles may honestly come back either way; such a case lists both statuses
    # and still has to cite the clause and say the carve-out (the other checks below).
    allowed = case.get("accept_status") or [case["status"]]
    if r["status"] not in allowed:
        fails.append("status %s != %s" % (r["status"], "/".join(allowed)))
    cited = {c["clause_id"] for c in r.get("citations", [])}
    fails += ["missing cite %s" % c for c in case["must_cite"] if c not in cited]
    said = r["answer"] + " " + " ".join(c["text"] for c in r.get("citations", []))
    fails += ["missing figure %s" % f for f in case["must_say"] if not has_figure(said, f)]
    fails += ["forbidden %s" % f for f in case["must_not_say"] if has_figure(r["answer"], f)]
    if case.get("must_note") and not any(case["must_note"] in n for n in r.get("notes", [])):
        fails.append("missing note on %s" % case["must_note"])
    if case.get("must_prove"):
        from rfp import provenance
        if not r.get("citations"):
            fails.append("must_prove: no citations to prove")
        fails += ["provenance: %s" % f for f in provenance.verify(r)]
    return fails
