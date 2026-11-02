"""Verify a saved answer: every quoted clause is in the solicitation, and the receipt is intact (and signed, if asked).

python3 tools/verify_receipt.py answer.json [--data data/] [--public-key HEX]

answer.json is the answer_question result as returned (MCP structuredContent). Exit 0 on PASS, 1 on any failure.
--data: recompute the package from the official documents and require the answer to match it, so a missing,
        extra or edited amendment is caught. Without it, proofs are checked against the receipt's own package.
--public-key: require an Ed25519 signature from this key (needs the optional PyNaCl extra).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "source"))

from rfp import provenance  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("answer", help="answer JSON file, or - for stdin")
    ap.add_argument("--data", help="folder with the official RFP and amendments")
    ap.add_argument("--public-key", help="trusted Ed25519 public key, hex")
    args = ap.parse_args()
    result = json.load(sys.stdin if args.answer == "-" else open(args.answer, encoding="utf-8"))
    expected = None
    if args.data:
        from loader import load
        expected = provenance.package(load(args.data))[0]["chain_head"]
    fails = provenance.verify(result, expected_chain_head=expected, trusted_public_key=args.public_key)
    r = result.get("receipt") or {}
    print("receipt %s · %s · %d citation(s) · package %s" % (
        (r.get("digest") or "none")[:16], r.get("signing", "no receipt"), len(result.get("citations", [])),
        "checked against " + args.data if args.data else "self-consistent only (pass --data to check the official documents)"))
    for f in fails:
        print("FAIL", f)
    print("PASS" if not fails else "%d failure(s)" % len(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
