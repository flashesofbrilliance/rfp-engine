"""Parse RFP and amendment text into citable clauses.

Deterministic on purpose: section headers carry page ranges, clauses carry numbers, and amendment
clauses carry their own target and operation. No model touches this layer.
"""
import hashlib
import re
from dataclasses import dataclass, field
from typing import List, Optional

SECTION_RE = re.compile(r"^SECTION (\d+) [—–\-\ufffd] (.+?) \(pp\. (\d+)[–\-\ufffd](\d+)\)$")
APPENDIX_RE = re.compile(r"^APPENDICES \(pp\. (\d+)[–\-\ufffd](\d+)\)$")
CLAUSE_RE = re.compile(r"^(\d+\.\d+) (.*)$")
AMEND_HEAD_RE = re.compile(r"AMENDMENT NO\. (\d+) [—–\-\ufffd] Issued (.+)$", re.M)  # any dash: a hyphen must not hide an amendment
AMEND_CLAUSE_RE = re.compile(r"^(A\d+\.\d+) (.*)$")
RULE_RE = re.compile(r"^=+$")


@dataclass
class Clause:
    clause_id: str               # "7.1" or "A1.2"
    section: str                 # "7" or "A1"
    section_title: str
    pages: Optional[str]         # "pp. 42–51" (section-level; the RFP gives no clause-level pages)
    text: str                    # verbatim, line breaks joined with spaces


@dataclass
class Document:
    sha256: str
    kind: str                    # "base" | "amendment"
    title: str
    amendment_no: Optional[int] = None
    issued: Optional[str] = None
    clauses: List[Clause] = field(default_factory=list)


def content_hash(raw: str) -> str:
    """Hash normalized text, so a re-saved copy with different whitespace is still a duplicate."""
    norm = re.sub(r"\s+", " ", raw).strip()
    return hashlib.sha256(norm.encode()).hexdigest()


def _flush(buf, out, section, title, pages):
    if buf and any(l.strip() for l in buf[1]):
        cid, lines = buf
        out.append(Clause(cid, section, title, pages, " ".join(l.strip() for l in lines).strip()))
    return None


def read_document(path):
    """A document file as text: UTF-8 (with or without a byte-order mark), else Windows-1252, the other encoding
    office tools save in. Decoding a Windows-1252 file as UTF-8 turned every long dash into a replacement character
    and lost every section heading."""
    data = open(path, "rb").read()
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", "replace")


def parse(raw: str) -> Document:
    # A byte-order mark is not text; a dash that was decoded wrongly (U+FFFD) still separates a heading.
    raw = raw.lstrip("\ufeff")
    lines = raw.splitlines() or [""]   # an empty file parses to no clauses instead of crashing the sync
    head = AMEND_HEAD_RE.search(raw)
    kind = "amendment" if head else "base"
    title = next((l.strip() for l in lines if "PROJECT" in l), lines[0].strip())
    doc = Document(content_hash(raw), kind, title)
    if head:
        doc.amendment_no, doc.issued = int(head.group(1)), head.group(2).strip()

    section, sec_title, pages, buf = None, None, None, None
    pattern = AMEND_CLAUSE_RE if kind == "amendment" else CLAUSE_RE
    if kind == "amendment":
        section, sec_title = "A%d" % doc.amendment_no, "Amendment No. %d" % doc.amendment_no
    for line in lines:
        s = line.strip()
        if not s or RULE_RE.match(s):
            continue
        m = SECTION_RE.match(s)
        if m:
            buf = _flush(buf, doc.clauses, section, sec_title, pages)
            section, sec_title, pages = m.group(1), m.group(2).title(), "pp. %s–%s" % (m.group(3), m.group(4))
            buf = (section, [])  # section preamble (e.g. Section 2 has no numbered clauses)
            continue
        m = APPENDIX_RE.match(s)
        if m:
            buf = _flush(buf, doc.clauses, section, sec_title, pages)
            section, sec_title, pages = "App", "Appendices", "pp. %s–%s" % (m.group(1), m.group(2))
            buf = ("Appendices", [])
            continue
        m = pattern.match(s)
        if m and section:
            buf = _flush(buf, doc.clauses, section, sec_title, pages)
            buf = (m.group(1), [m.group(2)])
            continue
        if buf:
            buf[1].append(s)
    _flush(buf, doc.clauses, section, sec_title, pages)
    return doc
