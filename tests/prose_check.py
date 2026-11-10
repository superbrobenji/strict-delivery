"""Prompt-block checks for the strict-delivery prose (stream B). A helper module, not a test module: it holds the role
and label tables, the forbidden-string list and the format checker that tests/test_prompt_blocks.py runs on the real
files and on bad samples. Python 3.9+, standard library only."""
import os
import re
import stat
import unicodedata

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
    # owner Q-RB-1 (a), Q-B22v2-4 (a): /Users/ or /home/, a name segment with no <, >, whitespace or quote, then /,
    # not preceded by a word character, '.', '~' or '-'; and the four test-file globs with a concrete extension
    ("absolute-path", re.compile(r"(?<![\w.~-])/(?:Users|home)/[^\s<>\"'`/]+/")),
    ("test-filename", re.compile(r"(?:test_\*|\*_test|\*\.spec|\*\.test)\.\w+")),
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
    """Label of each paragraph after the intro; "" for a paragraph whose first line holds no '. '. ValueError naming
    the line and code point when the text holds a character outside the whitelist (Q-B2FX2-1 (a))."""
    _refuse_chars(text, "labels", ValueError)
    return [_label(ls[0]) for ls in _paragraphs(text)]


def paragraph(text, label):
    _refuse_chars(text, "paragraph", ValueError)
    found =["\n".join(ls) for ls in _paragraphs(text) if _label(ls[0]) == label]
    if len(found) != 1:
        raise ValueError("label %r found %d times" % (label, len(found)))
    return found[0]


def forbidden_hits(text):
    """(name, line_no, match) for each forbidden match, ordered by line then column. Each line is scanned, and each
    paragraph with line breaks read as spaces, so a phrase split by a wrap is found at the line where it starts.
    Fail closed (Q-B2FX2-1 (a)): when the text holds a character outside the whitelist, only
    (CHAR_KIND, line_no, "U+XXXX") for each line holding one, in line order, and no scan."""
    bad = char_refusals(text)
    if bad:
        return [(CHAR_KIND, n, "U+%04X" % cp) for n, cp in bad]
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
    elif [_label(ls[0]) for ls in _paragraphs(text)] != list(LABELS[role]):    # not labels(): the byte check above
        got = [_label(ls[0]) for ls in _paragraphs(text)]                       # already refuses each such byte
        problems.append("labels: expected %r, got %r" % (list(LABELS[role]), got))
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


# playbook/rules.md (Task B2.1): line 1, one intro paragraph, one table, nothing after it.
RULES_TITLE = "# Base playbook: rules"
RULES_HEADER = "| id | rule | why | enforced by | profiles | fixed | source |"
RULES_SEPARATOR = "|---|---|---|---|---|---|---|"
RULES_COLUMNS = ("id", "rule", "why", "enforced by", "profiles", "fixed", "source")
RULES_ENFORCERS = frozenset((
    "gate_schema", "gate_register", "gate_claims", "gate_decisions", "gate_dispatch", "gate_streams", "gate_context",
    "gate_cites", "gate_drift", "gate_index", "gate_checkpoint", "gate_cleanup", "gate_evidence", "run_all", "hook",
    "judgment"))
SD_R4_ENFORCER = "program create (programs); judgment"
PROFILE_NAMES = ("light", "standard", "strict")
# The rules.md and sentence-splitter character set (owner Q-B2FX2-1 (a), narrowing Q-B21-2 (a)): LF, U+0020-U+007E
# and U+00A7, nothing else (no tab).
RULES_CHARS = frozenset("\n" + "".join(chr(c) for c in range(0x20, 0x7f)) + "§")
CHAR_KIND = "character outside whitelist"


def char_refusals(text):
    """(line_no, code point) of the first character outside RULES_CHARS on each LF-counted line, in line order (owner
    Q-B2FX2-1 (a), fix round 5). One pass over the text, counting LF, before any split or parse; RULES_CHARS is
    written by hand, so no Unicode database decides it. [] when every character is in the set."""
    out, line = [], 1
    for ch in text:
        if ch == "\n":
            line += 1
        elif ch not in RULES_CHARS and (not out or out[-1][0] != line):
            out.append((line, ord(ch)))
    return out


def _refuse_chars(text, name, exc):
    """exc naming the first line and code point outside the character whitelist, before the caller splits text."""
    bad = char_refusals(text)
    if bad:
        raise exc("%s: line %d: U+%04X, %s" % (name, bad[0][0], bad[0][1], CHAR_KIND))
_RULE_ID = re.compile(r"SD-R[1-9][0-9]*")
_RULE_ID_TOKEN = re.compile(r"SD-R[0-9]")
_SOURCE = re.compile(r"spec §[0-9]+[a-z]?")


def _need_str(text, name):
    if not isinstance(text, str):
        raise TypeError("%s takes str, not %s" % (name, type(text).__name__))


def _is_table_line(line):
    return line.lstrip(" ").startswith("|")


def _split_cells(line):
    s = line.strip(" ")
    if len(s) < 2 or not (s.startswith("|") and s.endswith("|")):
        raise ValueError("not a table row: %r" % line)
    return [c.strip(" ") for c in s[1:-1].split("|")]


def first_table_header(text):
    """The first line of the first table, as written, or None when the text holds no table line."""
    _need_str(text, "first_table_header")
    _refuse_chars(text, "first_table_header", ValueError)
    for line in text.split("\n"):
        if _is_table_line(line):
            return line
    return None


_SEPARATOR_CELL = re.compile(r":?-+:?")


def table_rows(text):
    """One dict per body row of the one table, keyed by that table's own header cells (padding stripped). The line
    after the header is a separator with one `:?-+:?` cell per header cell; the table ends at the first line that is
    not a table line, and no table line may follow it. Header names are unique."""
    _need_str(text, "table_rows")
    _refuse_chars(text, "table_rows", ValueError)
    lines = text.split("\n")
    h = next((i for i, line in enumerate(lines) if _is_table_line(line)), None)
    if h is None:
        raise ValueError("the text holds no table")
    header = _split_cells(lines[h])
    if len(set(header)) != len(header):
        raise ValueError("duplicate header cell names: %r" % lines[h])
    if h + 1 >= len(lines):
        raise ValueError("separator: no separator line after the header %r" % lines[h])
    try:
        sep = _split_cells(lines[h + 1])
    except ValueError:
        raise ValueError("separator: not a table row: %r" % lines[h + 1])
    if len(sep) != len(header) or not all(_SEPARATOR_CELL.fullmatch(c) for c in sep):
        raise ValueError("separator: %r does not match the header's %d cells" % (lines[h + 1], len(header)))
    rows = []
    end = len(lines)
    for i in range(h + 2, len(lines)):
        if not _is_table_line(lines[i]):
            end = i
            break
        cells = _split_cells(lines[i])
        if len(cells) != len(header):
            raise ValueError("%d cells, the header has %d: %r" % (len(cells), len(header), lines[i]))
        rows.append(dict(zip(header, cells)))
    later = next((i for i in range(end, len(lines)) if _is_table_line(lines[i])), None)
    if later is not None:
        raise ValueError("a table line after the table, line %d: %r" % (later + 1, lines[later]))
    return rows


def rules_problems(text):
    """Problem strings, each 'kind: detail', for the text of playbook/rules.md; [] when it is well formed."""
    _need_str(text, "rules_problems")
    problems = []
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as e:
        problems.append("encoding: not valid UTF-8 at character %d" % e.start)
    seen = set()
    for n, line in enumerate(text.split("\n"), 1):
        for ch in line:
            if ch == "\r":
                kind = "line-ending"
            elif unicodedata.category(ch) in ("Cc", "Zl", "Zp"):
                kind = "control"
            else:
                continue
            if (kind, n) not in seen:
                seen.add((kind, n))
                problems.append("%s: character 0x%02x on line %d" % (kind, ord(ch), n))
    for n, line in enumerate(text.split("\n"), 1):      # owner Q-B2FX2-1 (a): the rules.md character set
        for ch in line:
            if ch not in RULES_CHARS:
                problems.append("char: line %d, U+%04X outside the rules.md character set" % (n, ord(ch)))
    if not text.endswith("\n"):
        problems.append("final-newline: the file does not end with a newline")
    elif text.endswith("\n\n"):
        problems.append("final-newline: the file ends with more than one newline")
    lines = text.replace("\r", "").split("\n")
    if lines[-1] == "":
        lines.pop()
    for n, line in enumerate(lines, 1):
        if line.endswith((" ", "\t")):
            problems.append("trailing-ws: line %d" % n)
    if not lines or lines[0] != RULES_TITLE:
        problems.append("first-line: expected %r" % RULES_TITLE)
    h = next((i for i, line in enumerate(lines) if _is_table_line(line)), None)
    if h is None:
        problems.append("table: the file holds no table")
        return problems
    pre = lines[1:h]
    if not pre or pre[0] != "":
        problems.append("layout: line 2 must be empty")
    if not pre or pre[-1] != "":
        problems.append("layout: the table must follow one empty line")
    start = 1 if pre and pre[0] == "" else 0
    stop = len(pre) - 1 if len(pre) > start and pre[-1] == "" else len(pre)
    inner = pre[start:stop]
    if inner and (inner[0] == "" or inner[-1] == ""):
        problems.append("layout: more than one empty line around the intro")
    paragraphs = sum(1 for i, line in enumerate(inner) if line != "" and (i == 0 or inner[i - 1] == ""))
    if paragraphs != 1:
        problems.append("intro: %d paragraphs between line 1 and the table, expected 1" % paragraphs)
    if lines[h] != RULES_HEADER:
        problems.append("header: line %d, expected %r" % (h + 1, RULES_HEADER))
    if h + 1 >= len(lines) or lines[h + 1] != RULES_SEPARATOR:
        problems.append("separator: line %d, expected %r" % (h + 2, RULES_SEPARATOR))
    end = h + 2
    while end < len(lines) and _is_table_line(lines[end]):
        end += 1
    if end < len(lines):
        problems.append("trailing: line %d follows the table" % (end + 1))
    second = next((n for n in range(end, len(lines)) if _is_table_line(lines[n])), None)
    if second is not None:
        problems.append("tables: a second table at line %d" % (second + 1))
    if end <= h + 2:
        problems.append("rows: the table has no rows")
    for n in list(range(0, h + 2)) + list(range(end, len(lines))):
        if n < len(lines) and _RULE_ID_TOKEN.search(lines[n]):
            problems.append("stray-id: line %d holds a rule id outside the id column" % (n + 1))
    expected = 1
    for i in range(h + 2, end):
        line = lines[i]
        n = i + 1
        if line == RULES_HEADER:
            problems.append("tables: a second header at line %d" % n)
            continue
        if len(line) < 2 or not (line.startswith("|") and line.endswith("|")):
            problems.append("row: line %d is not a table row" % n)
            expected += 1
            continue
        raw = line[1:-1].split("|")
        if any(c.endswith("\\") for c in raw) or any(c.count("`") % 2 for c in raw):
            problems.append("pipe: line %d has a pipe inside a cell" % n)
        if len(raw) != len(RULES_COLUMNS):
            problems.append("cells: line %d has %d cells, expected %d" % (n, len(raw), len(RULES_COLUMNS)))
            expected += 1
            continue
        cells = dict(zip(RULES_COLUMNS, (c.strip(" ") for c in raw)))
        for col in RULES_COLUMNS:
            if cells[col] == "":
                problems.append("empty: line %d, column %r" % (n, col))
            elif col != "id" and _RULE_ID_TOKEN.search(cells[col]):
                problems.append("stray-id: line %d, column %r holds a rule id" % (n, col))
        rid = cells["id"]
        if _RULE_ID.fullmatch(rid) and len(rid) > 12:     # F-B2V3-2: no int() on an unbounded digit string
            problems.append("id: line %d, %s... is out of range (more than 8 digits)" % (n, rid[:12]))
            expected += 1
        elif _RULE_ID.fullmatch(rid):
            if rid != "SD-R%d" % expected:
                problems.append("id-sequence: line %d, expected SD-R%d, got %s" % (n, expected, rid))
            expected = int(rid[4:]) + 1
        else:
            problems.append("id: line %d, %r is not SD-R<n>" % (n, rid))
            expected += 1
        enf = cells["enforced by"]
        if enf == SD_R4_ENFORCER:
            if rid != "SD-R4":
                problems.append("enforced-by: line %d, %r is SD-R4's only" % (n, enf))
        elif enf not in RULES_ENFORCERS:
            problems.append("enforced-by: line %d, %r" % (n, enf))
        ps = cells["profiles"].split(", ")
        if ps != [p for p in PROFILE_NAMES if p in ps]:
            problems.append("profiles: line %d, %r" % (n, cells["profiles"]))
        if cells["fixed"] not in ("yes", "no"):
            problems.append("fixed: line %d, %r" % (n, cells["fixed"]))
        if not _SOURCE.fullmatch(cells["source"]):
            problems.append("source: line %d, %r" % (n, cells["source"]))
    return problems


def _require(cond, message):
    """AssertionError(message) unless cond; an explicit raise, so `python -O` keeps the check."""
    if not cond:
        raise AssertionError(message)


def section(text, heading):
    """The lines after the one line equal to '## <heading>', up to the next line starting with '## ' or the end
    (Task B2.2). Lines split on LF only. AssertionError naming the heading when that line is absent or repeated, and
    naming the heading, line and code point when the text holds a character outside the whitelist (Q-B2FX2-1 (a))."""
    _need_str(text, "section")
    _refuse_chars(text, "section %r" % (heading,), AssertionError)
    lines = text.split("\n")
    at = [i for i, line in enumerate(lines) if line == "## " + heading]
    _require(len(at) == 1, "section %r: the heading line occurs %d times" % (heading, len(at)))
    end = next((j for j in range(at[0] + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
    return "\n".join(lines[at[0] + 1:end]) + ("\n" if end < len(lines) else "")


# Angle-bracket placeholders (finding F-RDV2-1; owner Q-B22v2-3 (a)). CommonMark raw HTML a rendered view hides: an
# open tag (with attributes, optionally self-closing), a closing tag, a comment (refused from its '<!--' even when
# unterminated). A tag may span a line break, so the scan runs over the whole text with code spans and fences masked.
_ATTR = r"(?:\s+[A-Za-z_:][\w.:-]*(?:\s*=\s*(?:[^\s\"'=<>`]+|'[^']*'|\"[^\"]*\"))?)"
_HTML = re.compile(r"<[A-Za-z][A-Za-z0-9-]*%s*\s*/?>|</[A-Za-z][A-Za-z0-9-]*\s*>|<!--(?:.*?-->)?" % _ATTR, re.S)
_FENCE_OPEN = re.compile(r" {0,3}(`{3,}|~{3,})(.*)")
_ASCII_PUNCT = frozenset("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
_MASK = "\0"


def _span_ranges(s):
    """(start, end) of each code span in s. A backtick run opens a span only when a later run of the same length
    follows in s; a backslash escape outside a span is kept as text. s may hold line breaks (a paragraph)."""
    out = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n and s[i + 1] in _ASCII_PUNCT:
            i += 2
            continue
        if c != "`":
            i += 1
            continue
        j = i
        while j < n and s[j] == "`":
            j += 1
        k = j
        close = -1
        while k < n:
            if s[k] != "`":
                k += 1
                continue
            m = k
            while m < n and s[m] == "`":
                m += 1
            if m - k == j - i:
                close = m
                break
            k = m
        if close < 0:
            i = j
        else:
            out.append((i, close))
            i = close
    return out


def _masked(s, ranges):
    """s with every character inside the ranges, line breaks excepted, replaced by a NUL."""
    chars = list(s)
    for a, b in ranges:
        for p in range(a, b):
            if chars[p] != "\n":
                chars[p] = _MASK
    return "".join(chars)


def _mask_spans(line):
    """The line with each code span replaced by NULs; spans are found within the line (_span_ranges)."""
    return _masked(line, _span_ranges(line))


REFUSED_KINDS = ("multi-line code span", "angle bracket outside code span", "backslash outside code span",
                 "link syntax", "indented line", "block quote", "pipe in table-row code span", CHAR_KIND,
                 "extended autolink", "block start in list item")
_DELIMITER_ROW = re.compile(r"[ \t|:-]*")
_DELIMITER_ROW_NO_PIPE = re.compile(r"[ :-]*")          # fix round 6 (U-v7-1, D2): a pipe-less delimiter-shaped line
_TABLE_START = re.compile(r" {0,3}\|")
_LIST_MARKER = re.compile(r"(?:[-*+]|[0-9]+[.)])(?= |\Z)")   # fix round 7 (Q-B2Z1-1 (a), D2): ASCII digits, no int()
_ITEM_BLOCK_STARTS = ("```", "~~~", "#", ">", "|", "<")


def _list_block_start(line):
    """True when line is a list item line whose content starts a block (fix round 7, owner Q-B2Z1-1 (a), Z-1). A list
    item line starts at column 0 with a marker, '-', '*', '+' or one or more ASCII digits then '.' or ')', followed by
    a space or the end of the line. Its content, the text after the marker and all the spaces after it, starts a
    block when it begins with a backtick or tilde run of 3 or more, '#', '>', '|', '<' or another such marker; when 5
    or more spaces stand before non-blank content (indented code); or when it is a thematic break: 3 or more of one
    of '-', '*', '_', with only spaces between."""
    m = _LIST_MARKER.match(line)
    if not m:
        return False
    content = line[m.end():].lstrip(" ")
    if not content:
        return False
    if len(line) - m.end() - len(content) >= 5:
        return True
    if content.startswith(_ITEM_BLOCK_STARTS) or _LIST_MARKER.match(content):
        return True
    return content[0] in "-*_" and not content.replace(content[0], "").strip(" ") and content.count(content[0]) >= 3


def _bracket_start(line):
    """True when the line's content starts with '[' (fix round 8, owner Q-B2F1-1 (a), F-1, U-1). The content is the
    text after every column-0 list marker (_LIST_MARKER, the marker reading of _list_block_start) and all the spaces
    after each, or the whole line when it has no marker."""
    content = line
    m = _LIST_MARKER.match(content)
    while m:
        content = content[m.end():].lstrip(" ")
        m = _LIST_MARKER.match(content)
    return content[:1] == "["


def _info_refusals(info, tilde):
    """REFUSED_KINDS indexes for a fence opener's info string (fix round 6, D-v8-1, D1), checked RAW: an info string
    parses no code spans, so nothing is masked. '<', '\\', '](' or ']:', and 'www.' (any case) or '://' are refused
    for every fence; in a tilde fence (whose info string may hold backticks) an unpaired backtick run and a code span
    holding '|' are refused too."""
    out = []
    if tilde and _unpaired_runs(info):
        out.append(0)
    if "<" in info:
        out.append(1)
    if "\\" in info:
        out.append(2)
    if "](" in info or "]:" in info:
        out.append(3)
    if tilde and any("|" in info[a:b] for a, b in _span_ranges(info)):
        out.append(6)
    if "www." in info.lower() or "://" in info:
        out.append(8)
    return out


def _unpaired_runs(line):
    """Start offsets of the backtick runs the per-line pairing leaves unpaired (an escaped backtick outside a span
    is text, as in _span_ranges)."""
    spans = _span_ranges(line)
    out, i, n = [], 0, len(line)
    while i < n:
        inside = next((b for a, b in spans if a <= i < b), None)
        if inside is not None:
            i = inside
            continue
        if line[i] == "\\" and i + 1 < n and line[i + 1] in _ASCII_PUNCT:
            i += 2
            continue
        if line[i] == "`":
            j = i
            while j < n and line[j] == "`":
                j += 1
            out.append(i)
            i = j
            continue
        i += 1
    return out


def _table_row_lines(base):
    """Indexes of the lines read as table rows, fail closed: a line starting (after at most 3 spaces) with '|', and
    every line of a blank-line-delimited run that holds a delimiter-shaped line: only '|', '-', ':', space and tab,
    with at least one '-' and one '|'; or (fix round 6, U-v7-1, D2) only space, '-' and ':', with at least one '-'
    and one ':' (so no '|'). Other GFM table forms are not modeled (owner 2026-11-10)."""
    rows = {i for i, line in enumerate(base) if _TABLE_START.match(line)}
    run = []
    for i, line in enumerate(base + [""]):
        if line.strip():
            run.append(i)
            continue
        if any((_DELIMITER_ROW.fullmatch(base[p]) and "-" in base[p] and "|" in base[p])
               or (_DELIMITER_ROW_NO_PIPE.fullmatch(base[p]) and "-" in base[p] and ":" in base[p]) for p in run):
            rows.update(run)
        run = []
    return rows


def placeholder_hits(text):
    """(line_no, match) for each raw-HTML open tag, closing tag or comment outside code spans and fenced blocks, and
    (line_no, "refused: <kind>") for each input the check refuses instead of parsing (owner Q-B2FX2-1 (a), which
    narrows Q-B22v2-3 (a)), merged in line order (on one line: hits, then refusals in REFUSED_KINDS order).
    The rule is a whitelist (Q-B2FX2-1 (a), fix rounds 4 and 5). First, before any split or parse, the text is held to
    the character whitelist (RULES_CHARS: LF, U+0020-U+007E, U+00A7): when any character is outside it, the result is
    only (line_no, "refused: character outside whitelist") for each LF-counted line holding one, in line order, and
    no hit. So LF is the one line ending and space the one whitespace character inside a line. Then every line
    outside a fenced block (front matter included) is refused when it holds, outside every per-line code span, a '<'
    ("angle bracket outside code span"), a '\\' ("backslash outside code span"), or 'www.' (any case) or '://'
    ("extended autolink": a GFM www or URL autolink runs on to the next space or '<' and can take a span's
    backtick); fix round 8 (owner Q-B2F1-1 (a), F-1, U-1): every line outside a fenced block is refused as "link
    syntax" when it holds the sequence '](' or ']:' anywhere, code spans included (checked on the raw line), or when
    its content, the text after every list marker and the spaces after each or the whole line without one, starts
    with '[' (_bracket_start), reported once per line; a line outside a fenced block or opening or closing one is
    refused when it is non-blank and starts with a space ("indented line") or starts with '>' ("block quote"); R1 "multi-line code
    span", a backtick run its own line leaves unpaired; R3 "pipe in table-row code span", a code span holding '|' on
    a table-row line (_table_row_lines). A fence opener's info string (the text after its fence marker) is checked RAW,
    with no span masking, on the opener's line (_info_refusals; fix round 6, D-v8-1): '<', '\\', '](' or ']:', and
    'www.' or '://' by the kinds above, and in a tilde fence an unpaired backtick run (R1) and a code span holding '|'
    (R3); the fence still opens and its content stays masked. Fix round 7 (owner Q-B2Z1-1 (a), Z-1): a list item
    line outside a fenced block (column 0: '-', '*', '+' or ASCII digits then '.' or ')', then a space or the end of
    the line) is refused as "block start in list item" when its content, after the marker and all the spaces that
    follow it, starts a block: a backtick or tilde run of 3 or more, '#', '>', '|', '<', another list marker, 5 or
    more spaces before non-blank content, or a thematic break (_list_block_start). The line keeps its other
    refusals, and no fence opens on it. A block quote is refused as a line start, and footnote and reference
    definitions by "link syntax", because '](' and ']:' are checked on the raw line and a '[' content start is
    refused (before round 8 a backtick in the label could mask the ']:'), so a list item is the one container left.
    The dimension closed is the block-level constructs whose marker a per-line code span could mask: the fence info
    string (round 6), the table row (R3, raw spans), the list item (round 7) and the definition (round 8). With these
    refused, a line holds only text, code spans, emphasis, entities, email autolinks (no backtick can be part of one)
    and inert brackets, and the block forms left are column-0 paragraphs, headings, thematic breaks, column-0 list
    items whose content holds no block start, tables and column-0 fences, none whose content starts with '[', so no
    construct can take a backtick from a per-line span or hide text the per-line masking keeps. A hit is an _HTML
    match on the masked text, so its line always carries an "angle bracket outside code span" refusal too."""
    _need_str(text, "placeholder_hits")
    bad = char_refusals(text)
    if bad:
        return [(n, "refused: " + CHAR_KIND) for n, _ in bad]
    base, outside, refused = [], [], []
    fence = None
    for n, line in enumerate(text.split("\n"), 1):
        if fence is not None:
            m = re.match(r" {0,3}(`{3,}|~{3,})[ \t]*$", line)
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
                outside.append(line)
            else:
                outside.append("")
            base.append("")
            continue
        outside.append(line)
        m = _FENCE_OPEN.match(line)
        if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
            fence = m.group(1)
            refused += [(n, k) for k in _info_refusals(m.group(2), fence[0] == "~")]
            base.append("")
            continue
        base.append(line)
    lines = [_mask_spans(line) for line in base]
    masked = "\n".join(lines)
    out = [(masked.count("\n", 0, m.start()) + 1, m.group(0)) for m in _HTML.finditer(masked)]
    for n, (line, low, raw) in enumerate(zip(base, lines, outside), 1):
        if _unpaired_runs(line):
            refused.append((n, 0))
        if "<" in low:
            refused.append((n, 1))
        if "\\" in low:
            refused.append((n, 2))
        if "](" in line or "]:" in line or _bracket_start(line):    # fix round 8: raw line, spans included
            refused.append((n, 3))
        if raw[:1] == " " and raw.strip(" "):       # in the whitelist, space is the one whitespace character
            refused.append((n, 4))
        if raw[:1] == ">":
            refused.append((n, 5))
        if "www." in low.lower() or "://" in low:
            refused.append((n, 8))
        if _list_block_start(line):                  # fix round 7: base is "" inside a fence and on its fence lines
            refused.append((n, 9))
    for i in sorted(_table_row_lines(base)):
        if any("|" in base[i][a:b] for a, b in _span_ranges(base[i])):
            refused.append((i + 1, 6))
    out += sorted(set((n, "refused: " + REFUSED_KINDS[k]) for n, k in refused),
                  key=lambda r: (r[0], REFUSED_KINDS.index(r[1][len("refused: "):])))
    return sorted(out, key=lambda r: (r[0], r[1].startswith("refused: ")))


# Front matter (owner Q-B22v2-1 (a)): a fail-closed whitelist, standard library only.
_FM_KEY = re.compile(r"[a-z][a-z0-9_-]*")
_FM_QUOTED = re.compile(r"\"((?:[^\"\\]|\\[\"\\])*)\"")
_YAML_INDICATORS = frozenset("-?:,[]{}#&*!|>'\"%@`")


def front_matter(text):
    """The key: value lines between an exact '---' line 1 and the next exact '---' line, as a dict in file order. A
    value is plain (no YAML indicator first, no ': ', no ' #', no trailing ':', not empty, no surrounding whitespace)
    or double-quoted with only the escapes \\" and \\\\. Anything else raises AssertionError naming the line. The
    whole text is held to the character whitelist first (Q-B2FX2-1 (a)), which refuses every control character, so
    no Unicode database lookup is left."""
    _need_str(text, "front_matter")
    _refuse_chars(text, "front matter", AssertionError)
    lines = text.split("\n")
    _require(lines[0] == "---", "front matter: line 1: expected exactly '---', got %r" % lines[0])
    end = next((i for i in range(1, len(lines)) if lines[i] == "---"), None)
    _require(end is not None, "front matter: line 1: no exact '---' line closes it")
    out = {}
    for i in range(1, end):
        n, line = i + 1, lines[i]
        key, sep, value = line.partition(": ")
        _require(sep and _FM_KEY.fullmatch(key),
                 "front matter: line %d: not 'key: value' with a key [a-z][a-z0-9_-]*" % n)
        _require(key not in out, "front matter: line %d: duplicate key %r" % (n, key))
        if value.startswith("\""):
            m = _FM_QUOTED.fullmatch(value)
            _require(m, "front matter: line %d: a double-quoted value takes only the escapes \\\" and \\\\" % n)
            out[key] = re.sub(r"\\([\"\\])", r"\1", m.group(1))
            continue
        _require(value != "", "front matter: line %d: empty value" % n)
        _require(value[0] not in _YAML_INDICATORS, "front matter: line %d: plain value starts with %r" % (n, value[0]))
        _require(value == value.strip(), "front matter: line %d: whitespace around the value" % n)
        _require(": " not in value and " #" not in value and not value.endswith(":"), (
            "front matter: line %d: a plain value holds ': ', ' #' or a trailing ':'" % n))
        out[key] = value
    return out
