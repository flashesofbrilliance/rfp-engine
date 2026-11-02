"""Amendment resolution: which base clauses each amendment clause touches, and how.

Rules live in code (known legal phrasing), not in a prompt. An amendment clause whose phrasing
no rule recognizes is marked UNRESOLVED and surfaced to a human; it is never guessed.
"""
import re
from dataclasses import dataclass
from typing import List, Optional

REPLACE = "replaces"            # "Section 7.1 (...) is revised"
SUPPLEMENT = "adds"             # "Section 5 (...) is supplemented by new Section 5.5"
NO_CHANGE = "confirms_unchanged"  # "confirms that ... Section 8.1 are unchanged"
UNRESOLVED = "unresolved"

REVISED_RE = re.compile(r"^Section (\d+\.\d+) \([^)]*\) is revised")
SUPPLEMENT_RE = re.compile(r"^Section (\d+) \([^)]*\) is supplemented by new Section (\d+\.\d+)")
UNCHANGED_RE = re.compile(r"Section (\d+\.\d+) (?:is|are) unchanged")
# Every "Section N.N (...) is (also) revised|increased|..." in a clause: a clause that revises two sections is not
# a single-target revision.
REVISION_TARGETS_RE = re.compile(r"Section (\d+\.\d+)\s*(?:\([^)]*\))?\s+is\s+(?:also\s+)?"
                                 r"(?:revised|replaced|amended|modified|extended|increased|decreased|deleted|struck)\b", re.I)
MISSING_REF_RE = re.compile(r"(Appendix [A-Z]) \(issued with this Amendment\)")


@dataclass
class Effect:
    amendment_clause: str        # "A1.2"
    op: str
    target: Optional[str]        # base clause id, or the new clause id for SUPPLEMENT
    references_missing: List[str]


CHANGE_WORDS_RE = re.compile(r"\b(revised|replaced|struck|deleted|amended|modified|supplemented|extended|increased|decreased)\b", re.I)
# "Section 7.1", "Sections 3.2 and 3.4", "Sections 3.2, 3.4 or 5": every number in the list is a reference.
SECTION_REF_RE = re.compile(r"\bSections?\s+(\d+(?:\.\d+)?(?:(?:\s*,\s*(?:(?:and|or)\s+)?|\s+(?:and|or)\s+|\s*&\s*)"
                            r"(?:Sections?\s+)?\d+(?:\.\d+)?)*)", re.I)
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
# A clause that changes something, or states a figure, is operative; a purely informational note is not.
OPERATIVE_RE = re.compile(r"\d|\b(?:revis(?:e|es|ed)|replac(?:e|es|ed)|increas(?:e|es|ed)|decreas(?:e|es|ed)|mov(?:e|es|ed)|"
                          r"extend(?:s|ed)?|delet(?:e|es|ed)|amend(?:s|ed)?|struck|modif(?:y|ies|ied)|supplement(?:s|ed)?|"
                          r"changed|reduc(?:e|es|ed)|postpon(?:e|es|ed)|withdr(?:aw|aws|awn))\b", re.I)
EVERYTHING = "*"   # target of an unresolved clause that is operative but names no section: it may touch any answer


def classify(clause_id: str, text: str) -> Effect:
    missing = MISSING_REF_RE.findall(text)
    targets = list(dict.fromkeys(REVISION_TARGETS_RE.findall(text)))
    if len(targets) > 1:
        return Effect(clause_id, UNRESOLVED, ",".join(targets), missing)
    m = REVISED_RE.match(text)
    if m:
        return Effect(clause_id, REPLACE, m.group(1), missing)
    m = SUPPLEMENT_RE.match(text)
    if m:
        return Effect(clause_id, SUPPLEMENT, m.group(2), missing)
    # "Unchanged" counts only if nothing in the clause says it changes anything. A revision that ends
    # with "all other dates are unchanged" was once read as no-change.
    m = UNCHANGED_RE.search(text)
    if m and not CHANGE_WORDS_RE.search(text):
        return Effect(clause_id, NO_CHANGE, m.group(1), missing)
    # Unrecognized: keep every section it names (comma-joined when several) so answers citing any are flagged.
    # Naming none, an operative clause is flagged against everything; an informational one flags nothing.
    refs = []
    for m in SECTION_REF_RE.finditer(text):
        refs += [n for n in NUMBER_RE.findall(m.group(1)) if n not in refs]
    if refs:
        return Effect(clause_id, UNRESOLVED, ",".join(refs), missing)
    return Effect(clause_id, UNRESOLVED, EVERYTHING if OPERATIVE_RE.search(text) else None, missing)


def effects(amendment_doc) -> List[Effect]:
    return [classify(c.clause_id, c.text) for c in amendment_doc.clauses]
