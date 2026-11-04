"""Load the solicitation documents in data/ into an in-memory store."""
import os

from rfp import store

DATA = os.path.join(os.path.dirname(__file__), "..", "data")


def documents(folder=None):
    """Every solicitation document in data/: the base RFP first, then amendments in number order, so a new
    Amendment No. 2 dropped into the folder applies on top of No. 1 with no code change. Only a named non-document
    file (the sample questions) is skipped; any other file with no clauses is refused as unreadable by store.ingest.
    Any file that is not .txt, or any folder (an amendment saved as Word or PDF), stops the load: skipping it once
    answered a superseded figure as current with no warning. Hidden files (.DS_Store) are not documents."""
    from rfp import parse as P
    folder = folder or DATA
    unread = sorted(f for f in os.listdir(folder) if not f.startswith(".") and
                    (not f.endswith(".txt") or os.path.isdir(os.path.join(folder, f))))
    if unread:
        raise store.UnreadableDocument("%s: this engine reads only .txt files at the top of the folder and cannot read %s. "
                                       "Convert each to text in the sample RFP's layout, or move it out of the folder. "
                                       "Nothing was loaded: an unread amendment would let a superseded value pass as current."
                                       % (folder, ", ".join(unread)))
    found = []
    for f in sorted(os.listdir(folder)):
        if not f.endswith(".txt"):
            continue
        raw = P.read_document(os.path.join(folder, f))
        d = P.parse(raw)
        if not d.clauses and store.may_have_no_clauses(f):
            continue
        found.append(((0, 0) if d.kind != "amendment" else (1, d.amendment_no or 0), f, raw))
    return [(f, raw) for _, f, raw in sorted(found)]


def load(folder=None):
    db = store.connect(":memory:")
    for f, raw in documents(folder):
        try:
            store.ingest(db, raw, f)
        except store.DuplicateDocument as e:
            raise store.DuplicateDocument("%s: %s" % (f, e)) from None   # name the file
    return db
