"""Construction rules for the three reading altitudes on index.html. Stdlib only.

python3 tools/altitude_lint.py [index.html]   exit 0 when every panel follows its rules, 1 otherwise.

Exec (#p-exec)        at most 2 sentences; outcome and risk only: no code, no file names, no line numbers.
Operational (#p-ops)  exactly 3 steps; each opens with a bold lead; no file:line references.
Surgical (#p-surg)    an ordered list; every step names a code element and a file:line, and each cited line
                      exists in the source, so the page cannot drift from the code without failing here.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = re.compile(r"\(([\w./]+\.py):(\d+)")
SHORT = re.compile(r"\(?(?:answer\.py)?:(\d+)")


def panel(html, pid):
    m = re.search(r'<div class="d-panel" id="%s">(.*?)</div>' % pid, html, re.S)
    return m.group(1) if m else None


def text(fragment):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", fragment)).strip()


def check(html):
    fails = []
    ex, ops, surg = panel(html, "p-exec"), panel(html, "p-ops"), panel(html, "p-surg")
    if ex is None or ops is None or surg is None:
        return ["a panel is missing (need p-exec, p-ops, p-surg)"]
    if not re.search(r'id="d-exec" checked', html):
        fails.append("exec: not the default (d-exec must be checked)")
    t = text(ex)
    if len(re.findall(r"[.!?](?:\s|$)", t)) > 2:
        fails.append("exec: more than 2 sentences")
    if re.search(r"<code>|\.py|:\d+", ex):
        fails.append("exec: names code, a file or a line")
    steps = re.findall(r"<li>(.*?)</li>", ops, re.S)
    if len(steps) != 3:
        fails.append("operational: %d steps, need 3" % len(steps))
    fails += ["operational step %d: no bold lead" % (i + 1) for i, s in enumerate(steps) if not s.strip().startswith("<b>")]
    if REF.search(ops):
        fails.append("operational: carries a file:line reference")
    lines = {}
    for i, s in enumerate(re.findall(r"<li>(.*?)</li>", surg, re.S), 1):
        if "<code>" not in s and not re.search(r"<b>", s):
            fails.append("surgical step %d: names no code element" % i)
        refs = REF.findall(s) or [("source/rfp/answer.py", n) for n in SHORT.findall(s)]
        if not refs:
            fails.append("surgical step %d: no file:line" % i)
        for path, n in refs:
            full = path if path.startswith(("source/", "mcp/")) else os.path.join("source/rfp", path)
            src = lines.setdefault(full, open(os.path.join(ROOT, full)).read().split("\n") if os.path.exists(os.path.join(ROOT, full)) else [])
            if not 0 < int(n) <= len(src) or not src[int(n) - 1].strip():
                fails.append("surgical step %d: %s:%s is not a code line" % (i, full, n))
    return fails


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "index.html")
    fails = check(open(path).read())
    for f in fails:
        print("FAIL", f)
    print("altitude-lint: %s" % ("PASS" if not fails else "%d problem(s)" % len(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
