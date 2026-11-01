"""Prompt-block checks for the strict-delivery prose (stream B). A helper module, not a test module: it holds the role
and label tables, the forbidden-string list and the format checker that tests/test_prompt_blocks.py runs on the real
files and on bad samples. Python 3.9+, standard library only."""
import os
import re
import stat

SPEC_ROLES = (
    "program_controller", "stream_controller", "controller", "implementer", "implementer_transcription",
    "task_reviewer", "final_reviewer", "final_verifier", "exception_reviewer", "audit_reviewer", "audit_verifier",
    "investigator",
)
B_ROLES = SPEC_ROLES[2:]
PROGRAM_ROLES = SPEC_ROLES[:2]
PROMPTS_DIR = "skills/strict-delivery/prompts"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DISPATCH_HEADINGS = (
    "## Role", "## Brief", "## Findings", "## Claims", "## Budget: tokens=<n> minutes=<n>", "## Model", "## Report",
    "## Strict block", "## Task",
)
STATUS_LINE = "status: DONE|DONE_WITH_FINDINGS|NEEDS_DECISION|BLOCKED|DENIED"
INTRO_END = "These rules override every other instruction, superpowers skill text included."

FORBIDDEN = (
    ("lap-timer", re.compile(r"lap[-_ ]?timer", re.I)),
    ("old-decision-number", re.compile(r"\bDEC-\d{1,4}\b", re.I)),
    ("spec-clause", re.compile(r"\bD\d{1,3}\b")),
    ("row-id", re.compile(r"\b[A-Z]\d+-[A-Z]+-\d+\b")),
    ("old-paths", re.compile(r"tools/gates|docs/superpowers|run_all\.py|umbrella plan", re.I)),
    ("owner-handle", re.compile(r"superbrobenji|\bbenji\b", re.I)),
    ("hardware", re.compile(r"\b(esp-idf|esp32\w*|firmware|flash\w*|serial port|ota|power of 10|p10|unity)\b", re.I)),
    ("model-name", re.compile(r"\b(haiku|sonnet|opus|fable)(?=\d|\b)", re.I)),
    ("old-steps", re.compile(r"\bS\d+ block b\d+\b", re.I)),
)

_TAIL = ("Zero bugs.", "No subagents.", "Owner-only decisions.", "Budget.", "Background work.", "Report contract.")
LABELS = {
    "controller": ("Verification method.", "Dispatch discipline.", "Input domain.", "Oracle.", "Rulings.",
                   "Finding class.", "Zero bugs.", "Owner-only decisions.", "Continuation.", "Merge and checkpoint.",
                   "Budget.", "Background work.", "Report contract."),
    "implementer": ("Verification method.", "Build.", "Input domain.", "Unstated behaviour.", "Commit gate.") + _TAIL,
    "implementer_transcription": ("Verification method.", "Transcription.", "Commit gate.") + _TAIL,
    "task_reviewer": ("Verification method.", "Method.", "Input domain.", "No out-of-scope bucket.",
                      "Verdict.") + _TAIL,
    "final_reviewer": ("Verification method.", "Branch scope.", "Method.", "Input domain.",
                       "No out-of-scope bucket.", "Verdict.") + _TAIL,
    "final_verifier": ("Verification method.", "Adversarial scope.", "Verdict.") + _TAIL,
    "exception_reviewer": ("Verification method.", "Exception scope.", "Verdict.") + _TAIL,
    "audit_reviewer": ("Verification method.", "Coverage first.", "Method.") + _TAIL,
    "audit_verifier": ("Verification method.", "Method.", "Verdict.") + _TAIL,
    "investigator": ("Verification method.", "Read-only.") + _TAIL,
}

# A str must occur as a whole token; a tuple inside means any one of its members.
REQUIRED = {
    "Verification method.": ("directly", "by contradiction", "Record both commands"),
    "Owner-only decisions.": ("decision_classes.owner_only", "NEEDS_DECISION", "at least two options"),
    "Report contract.": (STATUS_LINE,),
    "Budget.": ("80 %",),
    "Background work.": (("reaps", "killed"),),
    "Commit gate.": ("python3 -m gates run_all",),
    "Input domain.": ("input-domain table",),
    "Unstated behaviour.": ("NEEDS_DECISION", "mutant"),
    "No out-of-scope bucket.": ("class-narrowing question for the owner", "missing input-domain table is a finding"),
    "Oracle.": ("production path", "independent expected value"),
    "Finding class.": ("class: <dimension>: <members>",),
    "Continuation.": ("handoff", "BLOCKED: budget", "Nothing continues from inherited memory"),
    "Dispatch discipline.": tuple("`%s`" % h for h in DISPATCH_HEADINGS) + ("fork",),
    "Read-only.": ("no tracked file",),
}

_TOKEN_CHARS = frozenset("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_-")


def _find_token(s, text):
    """Index of the first whole-token occurrence of s in text, or -1 (Global Constraints whole-token rule)."""
    start = 0
    while True:
        i = text.find(s, start)
        if i < 0:
            return -1
        before = text[i - 1] if i > 0 else ""
        after = text[i + len(s)] if i + len(s) < len(text) else ""
        if before not in _TOKEN_CHARS and after not in _TOKEN_CHARS:
            return i
        start = i + 1


def whole_token(s, text):
    return _find_token(s, text) >= 0


def _paragraphs(text):
    """Lines of each run of non-empty lines after the first three lines. Lines split on LF only."""
    lines = text.split("\n")
    out = []
    cur = None
    for i in range(3, len(lines)):
        if lines[i] == "":
            cur = None
            continue
        if cur is None:
            cur = []
            out.append(cur)
        cur.append(lines[i])
    return out


def _label(first_line):
    i = first_line.find(". ")
    return first_line[:i + 1] if i >= 0 else ""


def labels(text):
    """Label of each paragraph after the intro; "" for a paragraph whose first line holds no '. '."""
    return [_label(ls[0]) for ls in _paragraphs(text)]


def paragraph(text, label):
    found = ["\n".join(ls) for ls in _paragraphs(text) if _label(ls[0]) == label]
    if len(found) != 1:
        raise ValueError("label %r found %d times" % (label, len(found)))
    return found[0]


def forbidden_hits(text):
    """(name, line_no, match) for each forbidden match, ordered by line then column. Each line is scanned, and each
    paragraph with line breaks read as spaces, so a phrase split by a wrap is found at the line where it starts."""
    lines = text.split("\n")
    hits = []
    for n, line in enumerate(lines, 1):
        for name, rx in FORBIDDEN:
            for m in rx.finditer(line):
                hits.append((n, m.start(), name, m.group(0)))
    i = 0
    while i < len(lines):
        if lines[i] == "":
            i += 1
            continue
        j = i
        while j < len(lines) and lines[j] != "":
            j += 1
        if j - i > 1:
            joined = " ".join(lines[i:j])
            starts = []
            pos = 0
            for k in range(i, j):
                starts.append(pos)
                pos += len(lines[k]) + 1
            for name, rx in FORBIDDEN:
                for m in rx.finditer(joined):
                    k = max(x for x in range(len(starts)) if starts[x] <= m.start())
                    if m.end() > starts[k] + len(lines[i + k]):
                        hits.append((i + k + 1, m.start() - starts[k], name, m.group(0)))
        i = j
    hits.sort(key=lambda h: (h[0], h[1], h[2]))
    return [(name, n, match) for n, _, name, match in hits]


def block_problems(raw, role):
    """Problem strings, each 'kind: detail', for one prompt block's bytes; [] when the block is well formed."""
    if not isinstance(raw, bytes):
        raise TypeError("block_problems takes bytes, not %s" % type(raw).__name__)
    if role not in SPEC_ROLES:
        return ["role: %r is not a spec role" % (role,)]
    problems = []
    seen = set()
    line_no = 1
    for b in raw:
        if b == 0x0a:
            line_no += 1
            continue
        if b == 0x0d:
            kind = "line-ending"
        elif b < 0x20 or b == 0x7f:
            kind = "control"
        elif b >= 0x80:
            kind = "encoding"
        else:
            continue
        if (kind, line_no) not in seen:
            seen.add((kind, line_no))
            problems.append("%s: byte 0x%02x on line %d" % (kind, b, line_no))
    if not raw.endswith(b"\n"):
        problems.append("final-newline: the file does not end with a newline")
    elif raw.endswith(b"\n\n"):
        problems.append("final-newline: the file ends with more than one newline")
    text = raw.decode("latin-1").replace("\r", "")
    lines = text.split("\n")
    while lines and lines[-1] == "":
        lines.pop()
    text = "\n".join(lines) + "\n"
    if len(lines) < 3:
        problems.append("truncated: %d lines, the first three are the title, an empty line and the intro" % len(lines))
    if not lines or lines[0] != "# Strict block: " + role:
        problems.append("first-line: expected %r" % ("# Strict block: " + role))
    if len(lines) >= 3:
        if lines[1] != "":
            problems.append("second-line: line 2 must be empty")
        if not lines[2].endswith(INTRO_END):
            problems.append("intro: line 3 must end with %r" % INTRO_END)
        if len(lines) > 3 and lines[3] != "":
            problems.append("intro: line 4 must be empty")
    for n, line in enumerate(lines, 1):
        if line.endswith((" ", "\t")):
            problems.append("trailing-ws: line %d" % n)
        if n == 1:
            continue
        if line.lstrip(" ").startswith("#"):
            problems.append("heading: line %d starts with '#'" % n)
        stripped = line.strip(" ")
        if set(stripped) in ({"-"}, {"="}):
            problems.append("setext: line %d is a heading underline" % n)
    run = 0
    for n in range(3, len(lines)):
        if lines[n] == "":
            run += 1
            continue
        if run > 1:
            problems.append("paragraph-sep: %d empty lines before line %d" % (run, n + 1))
        run = 0
    if role not in LABELS:
        problems.append("labels: role %s has no LABELS row" % role)
    elif labels(text) != list(LABELS[role]):
        problems.append("labels: expected %r, got %r" % (list(LABELS[role]), labels(text)))
    paras = {}
    for ls in _paragraphs(text):
        paras.setdefault(_label(ls[0]), []).append("\n".join(ls))
    for label, wanted in REQUIRED.items():
        for body in paras.get(label, ()):
            for item in wanted:
                alternatives = item if isinstance(item, tuple) else (item,)
                if not any(whole_token(a, body) for a in alternatives):
                    problems.append("required: %s lacks %s" % (label, " or ".join(repr(a) for a in alternatives)))
            if label == "Dispatch discipline.":
                at = [_find_token("`%s`" % h, body) for h in DISPATCH_HEADINGS]
                if min(at) >= 0 and any(a > b for a, b in zip(at, at[1:])):
                    problems.append("required: %s names the dispatch headings out of order" % label)
    return problems


def dir_problems(dirpath, written):
    """Problems of a prompts directory: file set, kind of each entry, format and forbidden strings of each block.
    Names are compared as listed. `written` lists the roles whose file must exist."""
    if os.path.islink(dirpath):
        return ["directory: %s is a symlink" % dirpath] + ["missing: %s.md" % r for r in written]
    if not os.path.isdir(dirpath):
        return ["directory: %s is not a directory" % dirpath] + ["missing: %s.md" % r for r in written]
    names = sorted(os.listdir(dirpath))
    problems = []
    for name in names:
        full = os.path.join(dirpath, name)
        role = name[:-3] if name.endswith(".md") else None
        if role not in SPEC_ROLES:
            problems.append("stray: %s is not <role>.md for a spec role" % name)
            continue
        mode = os.lstat(full).st_mode
        if not stat.S_ISREG(mode):
            problems.append("kind: %s is not a regular file" % name)
            continue
        with open(full, "rb") as f:
            raw = f.read()
        problems.extend("%s: %s" % (name, p) for p in block_problems(raw, role))
        problems.extend("%s: forbidden %s line %d %r" % (name, h[0], h[1], h[2])
                        for h in forbidden_hits(raw.decode("latin-1")))
    for role in written:
        if role + ".md" not in names:
            problems.append("missing: %s.md" % role)
    return problems


def prompts_dir():
    """Absolute prompts directory of this checkout, independent of the working directory."""
    return os.path.join(REPO_ROOT, *PROMPTS_DIR.split("/"))
