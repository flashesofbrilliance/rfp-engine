"""Provenance: proof that every cited clause is in the loaded solicitation, and a receipt for every answer.

Standard library only. Signing is an optional extra: with PyNaCl installed and RFP_SIGNING_KEY set (Ed25519 private
key, hex), receipts are signed; otherwise they are hashed and say plainly that they are unsigned.

Construction (verifiable by anyone with the receipt, no trust in this tool):
- Each clause is a Merkle leaf: H(0x00 || canonical JSON {doc, id, text}). Leaves and inner nodes are domain-separated
  (0x00 / 0x01, as in RFC 6962), so a leaf can never be passed off as a node.
- Each document (base RFP, each amendment) gets a Merkle root over its clauses, in document order. An odd node is
  carried up unpaired, never duplicated, so two different clause lists cannot share a root.
- The package is a hash chain over the document roots, base first, amendments in number order:
  head_0 = H(0x02 || base_root), head_n = H(0x02 || head_n-1 || amendment_n_root). Dropping, reordering or editing
  any amendment changes the head, so "latest wins" is checkable: the receipt names the exact amendment set it used.
- A receipt commits to the question, status, answer, gate, each citation's leaf, the package and the engine code hash.
  Its digest is SHA-256 over canonical JSON (sorted keys, no spaces).
"""
import glob
import hashlib
import json
import os

SCHEMA = "rfp-engine/answer-receipt/v1"
LEAF, NODE, CHAIN = b"\x00", b"\x01", b"\x02"
HERE = os.path.dirname(os.path.abspath(__file__))


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha(*parts):
    h = hashlib.sha256()
    for p in parts:
        h.update(p)
    return h.hexdigest()


def leaf_hash(doc_sha, clause_id, text):
    return sha(LEAF, canonical({"doc": doc_sha, "id": clause_id, "text": text}))


def _node(a, b):
    return sha(NODE, bytes.fromhex(a), bytes.fromhex(b))


def merkle_root(leaves):
    if not leaves:
        return sha(NODE)  # the empty document: a fixed value, never confused with a real root
    level = list(leaves)
    while len(level) > 1:
        nxt = [_node(level[i], level[i + 1]) for i in range(0, len(level) - 1, 2)]
        if len(level) % 2:
            nxt.append(level[-1])  # carried up, not duplicated
        level = nxt
    return level[0]


def merkle_path(leaves, index):
    """Sibling hashes from leaf to root; each step says which side the sibling is on."""
    path, level, i = [], list(leaves), index
    while len(level) > 1:
        sib = i ^ 1
        if sib < len(level):
            path.append({"side": "left" if sib < i else "right", "hash": level[sib]})
        nxt = [_node(level[j], level[j + 1]) for j in range(0, len(level) - 1, 2)]
        if len(level) % 2:
            nxt.append(level[-1])
        level, i = nxt, i // 2
    return path


def walk(leaf, path):
    h = leaf
    for step in path:
        h = _node(step["hash"], h) if step["side"] == "left" else _node(h, step["hash"])
    return h


def chain_head(document_roots):
    head = None
    for root in document_roots:
        head = sha(CHAIN, bytes.fromhex(root)) if head is None else sha(CHAIN, bytes.fromhex(head), bytes.fromhex(root))
    return head


def package(db):
    """Per-document Merkle roots and the chain head over them, plus where every clause sits. Deterministic."""
    docs = db.execute("""SELECT sha256, kind, amendment_no, issued FROM documents
                         ORDER BY CASE kind WHEN 'base' THEN 0 ELSE 1 END, amendment_no""").fetchall()
    out, index = [], {}
    for d in docs:
        rows = db.execute("SELECT clause_id, text FROM clauses WHERE doc_sha=? ORDER BY rowid", (d["sha256"],)).fetchall()
        leaves = [leaf_hash(d["sha256"], r["clause_id"], r["text"]) for r in rows]
        for i, r in enumerate(rows):
            index[r["clause_id"]] = (d["sha256"], leaves, i)
        out.append({"sha256": d["sha256"], "kind": d["kind"], "amendment_no": d["amendment_no"],
                    "issued": d["issued"], "clauses": len(rows), "merkle_root": merkle_root(leaves)})
    return {"documents": out, "chain_head": chain_head([d["merkle_root"] for d in out])}, index


def code_hash():
    """SHA-256 over the engine's own source files, so a receipt names the code that produced it."""
    h = hashlib.sha256()
    for path in sorted(glob.glob(os.path.join(HERE, "*.py"))):
        h.update(os.path.basename(path).encode() + b"\x00")
        h.update(open(path, "rb").read())
    return h.hexdigest()


def _signer():
    key = os.environ.get("RFP_SIGNING_KEY", "").strip()
    if not key:
        return None, "unsigned: no RFP_SIGNING_KEY set"
    try:
        import nacl.signing  # optional extra: pip install pynacl
    except ImportError:
        return None, "unsigned: PyNaCl not installed (pip install pynacl)"
    try:
        return nacl.signing.SigningKey(bytes.fromhex(key)), None
    except Exception:
        return None, "unsigned: RFP_SIGNING_KEY is not a 32-byte hex Ed25519 key"


def with_receipt(db, result):
    """Add a Merkle proof to every citation and a receipt to the result. The answer itself is not changed."""
    pkg, index = package(db)
    cites = []
    for c in result.get("citations", []):
        loc = index.get(c["clause_id"])
        if loc is None:  # cannot happen for a cited clause that exists; recorded, never hidden
            c["proof"] = None
        else:
            doc, leaves, i = loc
            c["proof"] = {"doc_sha": doc, "leaf": leaves[i], "path": merkle_path(leaves, i)}
        cites.append({"clause_id": c["clause_id"], "leaf": c["proof"] and c["proof"]["leaf"]})
    payload = {"schema": SCHEMA, "question": result.get("question"), "status": result.get("status"),
               "answer": result.get("answer"), "gate": result.get("gate"), "citations": cites,
               "package": pkg, "engine_code_sha256": code_hash()}
    digest = sha(canonical(payload))
    key, why = _signer()
    receipt = {"payload": payload, "digest": digest, "signature": None, "public_key": None, "signing": why or "ed25519"}
    if key:
        receipt["signature"] = key.sign(bytes.fromhex(digest)).signature.hex()
        receipt["public_key"] = key.verify_key.encode().hex()
    result["receipt"] = receipt
    return result


def verify(result, expected_chain_head=None, trusted_public_key=None):
    """Check a result end to end. Returns a list of failures; empty means every check passed.

    expected_chain_head: the package head you trust (e.g. recomputed from the official documents). Without it, the
    proofs show the clauses are consistent with the receipt's own package, not that the package is the official one.
    """
    fails = []
    r = result.get("receipt")
    if not r:
        return ["no receipt"]
    p = r["payload"]
    if sha(canonical(p)) != r["digest"]:
        fails.append("receipt digest does not match its payload")
    docs = {d["sha256"]: d for d in p["package"]["documents"]}
    if chain_head([d["merkle_root"] for d in p["package"]["documents"]]) != p["package"]["chain_head"]:
        fails.append("package chain head does not match its document roots")
    if expected_chain_head and p["package"]["chain_head"] != expected_chain_head:
        fails.append("package is not the expected one (chain head differs): an amendment is missing, extra or edited")
    receipt_leaves = {c["clause_id"]: c["leaf"] for c in p["citations"]}
    for c in result.get("citations", []):
        pr = c.get("proof")
        if not pr:
            fails.append("%s: no proof" % c["clause_id"])
            continue
        leaf = leaf_hash(pr["doc_sha"], c["clause_id"], c["text"])
        if leaf != pr["leaf"] or receipt_leaves.get(c["clause_id"]) != leaf:
            fails.append("%s: quoted text does not match the committed clause" % c["clause_id"])
        doc = docs.get(pr["doc_sha"])
        if not doc or walk(leaf, pr["path"]) != doc["merkle_root"]:
            fails.append("%s: clause is not in the document it claims" % c["clause_id"])
    if p.get("status") != result.get("status") or p.get("answer") != result.get("answer"):
        fails.append("status or answer differs from what the receipt committed to")
    if r.get("signature"):
        try:
            import nacl.signing
            key = r["public_key"]
            if trusted_public_key and key != trusted_public_key:
                fails.append("signed by an untrusted key")
            nacl.signing.VerifyKey(bytes.fromhex(key)).verify(bytes.fromhex(r["digest"]), bytes.fromhex(r["signature"]))
        except ImportError:
            fails.append("receipt is signed but PyNaCl is not installed to check it")
        except Exception:
            fails.append("signature does not verify")
    elif trusted_public_key:
        fails.append("unsigned receipt, but a signature from a trusted key was required")
    return fails
