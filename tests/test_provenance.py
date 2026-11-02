"""Provenance checks: every proof verifies, and every kind of tampering is caught.

python3 -m unittest discover -s tests   (standard library only; the signing tests skip without PyNaCl)
"""
import copy
import os
import sys
import tempfile
import shutil
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "source"))
os.environ.setdefault("MODEL_PROVIDER", "mock")

from loader import load  # noqa: E402
from rfp import answer as engine  # noqa: E402
from rfp import provenance as P  # noqa: E402
from eval.run_eval import check  # noqa: E402

try:
    import nacl.signing
    HAVE_NACL = True
except ImportError:
    HAVE_NACL = False


def ask(q, db=None):
    db = db or load()
    return P.with_receipt(db, engine.answer(db, q)), db


class MerkleTree(unittest.TestCase):
    def test_every_leaf_proves_for_every_tree_size(self):
        for n in range(1, 12):  # odd sizes exercise the carried-up node
            leaves = [P.sha(bytes([i])) for i in range(n)]
            root = P.merkle_root(leaves)
            for i in range(n):
                self.assertEqual(P.walk(leaves[i], P.merkle_path(leaves, i)), root, (n, i))

    def test_no_duplicate_node_collision(self):
        a, b, c = (P.sha(bytes([i])) for i in range(3))
        self.assertNotEqual(P.merkle_root([a, b, c]), P.merkle_root([a, b, c, c]))

    def test_leaf_and_node_are_domain_separated(self):
        a, b = P.sha(b"a"), P.sha(b"b")
        self.assertNotEqual(P.merkle_root([a, b]), P.leaf_hash("x", "y", a + b))


class Receipts(unittest.TestCase):
    def setUp(self):
        self.r, self.db = ask("What is the bid deposit?")

    def test_answered_result_verifies(self):
        self.assertEqual(self.r["status"], "answered")
        self.assertTrue(self.r["citations"])
        self.assertEqual(P.verify(self.r), [])

    def test_receipts_are_deterministic(self):
        r2, _ = ask("What is the bid deposit?", self.db)
        self.assertEqual(self.r["receipt"]["digest"], r2["receipt"]["digest"])

    def test_edited_clause_text_is_caught(self):
        bad = copy.deepcopy(self.r)
        bad["citations"][0]["text"] = bad["citations"][0]["text"].replace("$", "$1")
        self.assertTrue(any("does not match" in f for f in P.verify(bad)))

    def test_edited_answer_is_caught(self):
        bad = copy.deepcopy(self.r)
        bad["answer"] = "The bid deposit is $1."
        self.assertTrue(P.verify(bad))

    def test_edited_receipt_payload_is_caught(self):
        bad = copy.deepcopy(self.r)
        bad["receipt"]["payload"]["status"] = "not_addressed"
        self.assertTrue(any("digest" in f for f in P.verify(bad)))

    def test_forged_path_is_caught(self):
        bad = copy.deepcopy(self.r)
        bad["citations"][0]["proof"]["path"][0]["hash"] = "00" * 32
        self.assertTrue(any("not in the document" in f for f in P.verify(bad)))

    def test_missing_amendment_changes_the_package(self):
        tmp = tempfile.mkdtemp()
        try:
            data = os.path.join(ROOT, "data")
            for f in os.listdir(data):
                if "amendment" not in f:
                    shutil.copy(os.path.join(data, f), tmp)
            stale, _ = ask("What is the bid deposit?", load(tmp))
        finally:
            shutil.rmtree(tmp)
        official = self.r["receipt"]["payload"]["package"]["chain_head"]
        self.assertEqual(P.verify(stale), [])  # consistent with itself...
        self.assertTrue(any("not the expected one" in f for f in P.verify(stale, expected_chain_head=official)))  # ...but not official

    def test_golden_must_prove_fails_without_receipt(self):
        case = {"status": "answered", "must_cite": [], "must_say": [], "must_not_say": [], "must_prove": True}
        r = dict(self.r)
        r.pop("receipt")
        self.assertIn("provenance: no receipt", check(case, r))

    def test_unsigned_receipt_says_why(self):
        if os.environ.get("RFP_SIGNING_KEY"):
            self.skipTest("signing key set in environment")
        self.assertIsNone(self.r["receipt"]["signature"])
        self.assertTrue(self.r["receipt"]["signing"].startswith("unsigned:"))
        self.assertTrue(any("trusted key" in f for f in P.verify(self.r, trusted_public_key="ab" * 32)))


@unittest.skipUnless(HAVE_NACL, "PyNaCl not installed (optional signing extra)")
class Signing(unittest.TestCase):
    def setUp(self):
        self.key = nacl.signing.SigningKey.generate()
        os.environ["RFP_SIGNING_KEY"] = self.key.encode().hex()
        self.r, _ = ask("When are proposals due?")
        self.pub = self.key.verify_key.encode().hex()

    def tearDown(self):
        os.environ.pop("RFP_SIGNING_KEY", None)

    def test_signed_receipt_verifies_with_trusted_key(self):
        self.assertEqual(self.r["receipt"]["signing"], "ed25519")
        self.assertEqual(P.verify(self.r, trusted_public_key=self.pub), [])

    def test_untrusted_key_is_caught(self):
        other = nacl.signing.SigningKey.generate().verify_key.encode().hex()
        self.assertTrue(any("untrusted" in f for f in P.verify(self.r, trusted_public_key=other)))

    def test_forged_signature_is_caught(self):
        bad = copy.deepcopy(self.r)
        bad["receipt"]["signature"] = "00" * 64
        self.assertTrue(any("signature" in f for f in P.verify(bad)))


if __name__ == "__main__":
    unittest.main()
