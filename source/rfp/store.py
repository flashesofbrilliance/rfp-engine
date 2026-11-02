"""SQLite store: documents, clauses, amendment effects. Idempotent by content hash.

Stdlib sqlite3, one file, so there is nothing extra to run.
"""
import json
import os
import sqlite3

from rfp import parse as P
from rfp import resolve as R

DB = os.environ.get("RFP_DB", os.path.join(os.path.dirname(__file__), "..", "..", "rfp.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
  sha256 TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL,
  amendment_no INTEGER, issued TEXT, filename TEXT, ingested_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (kind, amendment_no)
);
CREATE TABLE IF NOT EXISTS clauses (
  clause_id TEXT NOT NULL, doc_sha TEXT NOT NULL REFERENCES documents(sha256),
  section TEXT, section_title TEXT, pages TEXT, text TEXT NOT NULL,
  PRIMARY KEY (doc_sha, clause_id)
);
CREATE TABLE IF NOT EXISTS effects (
  amendment_clause TEXT NOT NULL, doc_sha TEXT NOT NULL, op TEXT NOT NULL,
  target TEXT, references_missing TEXT NOT NULL,
  PRIMARY KEY (doc_sha, amendment_clause)
);
"""


def connect(path=None):
    db = sqlite3.connect(path or DB)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


class DuplicateDocument(Exception):
    pass


class UnreadableDocument(Exception):
    """The document has real text but the parser found no clauses in it. Refused, never stored: an empty
    document would make every later question come back "not addressed in the RFP", a confident false negative."""


NON_DOCUMENT_FILES = {"sample_questions.txt"}  # the only text files in data/ that are not solicitation documents


def may_have_no_clauses(filename):
    """A document with zero clauses is refused, whatever its length: a short amendment-shaped notice in a layout the
    parser does not know once parsed as an empty base RFP and was stored or skipped without a word."""
    return os.path.basename(filename or "") in NON_DOCUMENT_FILES


MAX_CLAUSE_WORDS = 400       # the sample's longest real clause is 76 words; a longer one is unrecognised text the
                             # parser swallowed into the previous clause (80 federal pages became one 31,047-word clause)


def ingest(db, raw, filename):
    """Returns (doc, created). A byte-different copy of the same text is still a duplicate."""
    doc = P.parse(raw)
    words = len(raw.split())
    if not doc.clauses and not may_have_no_clauses(filename):
        raise UnreadableDocument("%s: %s words but no clauses this parser recognises (the sample RFP's '7.1 Title.' layout; "
                                 "an amendment needs the heading 'AMENDMENT NO. n - Issued <date>' and clauses numbered "
                                 "'A<n>.<m>'). Nothing was ingested; a person must review it, and no answer may say "
                                 "'not addressed' about this document." % (filename, f"{words:,}"))
    huge = [c for c in doc.clauses if len(c.text.split()) > MAX_CLAUSE_WORDS]
    if huge:
        raise UnreadableDocument("%s: clause %s runs %s words (limit %d); part of this document is in a layout the parser "
                                 "does not recognise and was swallowed into one clause. Nothing was ingested; a person must "
                                 "review it." % (filename, huge[0].clause_id, f"{len(huge[0].text.split()):,}", MAX_CLAUSE_WORDS))
    if db.execute("SELECT 1 FROM documents WHERE sha256=?", (doc.sha256,)).fetchone():
        return doc, False
    if doc.kind == "amendment" and db.execute(
            "SELECT 1 FROM documents WHERE kind='amendment' AND amendment_no=?", (doc.amendment_no,)).fetchone():
        raise DuplicateDocument("Amendment No. %d is already ingested with different text; "
                                "a human must decide which one is authoritative" % doc.amendment_no)
    with db:
        db.execute("INSERT INTO documents (sha256, kind, title, amendment_no, issued, filename) VALUES (?,?,?,?,?,?)",
                   (doc.sha256, doc.kind, doc.title, doc.amendment_no, doc.issued, filename))
        db.executemany("INSERT INTO clauses VALUES (?,?,?,?,?,?)",
                       [(c.clause_id, doc.sha256, c.section, c.section_title, c.pages, c.text) for c in doc.clauses])
        if doc.kind == "amendment":
            db.executemany("INSERT INTO effects VALUES (?,?,?,?,?)",
                           [(e.amendment_clause, doc.sha256, e.op, e.target, json.dumps(e.references_missing))
                            for e in R.effects(doc)])
    return doc, True


def all_clauses(db):
    return db.execute("""SELECT c.*, d.kind, d.amendment_no, d.issued FROM clauses c
                         JOIN documents d ON d.sha256=c.doc_sha
                         ORDER BY d.kind DESC, d.amendment_no, c.rowid""").fetchall()


def effects_on(db, clause_id):
    """Amendment effects that touch a base clause, oldest amendment first. Later amendments win."""
    section = clause_id.split(".")[0]
    return db.execute("""SELECT e.*, d.amendment_no, d.issued, c.text AS amendment_text FROM effects e
                         JOIN documents d ON d.sha256=e.doc_sha
                         JOIN clauses c ON c.doc_sha=e.doc_sha AND c.clause_id=e.amendment_clause
                         WHERE e.target=? OR (e.op='adds' AND e.target LIKE ?)
                            OR (e.op='unresolved' AND (e.target='*' OR instr(',' || e.target || ',', ',' || ? || ',') > 0
                                                       OR instr(',' || e.target || ',', ',' || ? || ',') > 0))
                         ORDER BY d.amendment_no""", (clause_id, section + ".%", clause_id, section)).fetchall()


def governing(db, clause_id):
    """The amendment clause whose text governs a base clause now: the latest one that replaces it."""
    rows = [e for e in effects_on(db, clause_id) if e["op"] == "replaces" and e["target"] == clause_id]
    return rows[-1] if rows else None
