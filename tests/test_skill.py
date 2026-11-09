"""Tests for skills/strict-delivery/SKILL.md (Task B2.3).
Oracle: the real file is read from the repository root and checked by the checks below; every expected value (front
matter, headings, precedence keys, owner-only slugs, section phrases and pins) is a literal from the plan, the spec or
an owner answer, typed here, never read back from SKILL.md. The only computed oracles are gates.lib.config.DEFAULTS
(the drift test, plan stream B rules) and the slug column of playbook/decisions.md and the `judgment` rows of
playbook/rules.md, both read with the production helpers of tests/prose_check.py. Bad samples are the real file with
one change each, and assert which check refuses them."""
import os
import re
import unittest

from tests import prose_check as pc
from tests.prose_check import SPEC_ROLES, forbidden_hits, section, table_rows
from tests.test_playbook import sentences

SKILL = "skills/strict-delivery/SKILL.md"
DESCRIPTION = ("Use at the start of every session, after a compaction, and before every change of any size (code, "
               "tests, tools, CI, docs, specs, plans, memory notes, pull-request bodies, issue text): precedence, roles "
               "and tiers, decision classes, owner questions, verification by direct check and contradiction, change "
               "kinds, pipeline and gates, session resume and continuation. Overrides superpowers.")   # Q-B22v2-1 (a)
HEADINGS = ["When it applies", "Precedence", "Roles and tiers", "Decision classes", "Owner questions",
            "Verification method", "Change kinds", "Pipeline and gates", "Session resume", "Continuation",
            "Document locations", "Judgment, not gated"]
OWNER_ONLY = ["triage", "spec-direction", "scope", "merge-grant", "model-policy", "issue-close", "finding-class",
              "rule-override", "program-create", "stream-ownership", "stream-merge", "request-dispute", "program-close"]
PRECEDENCE_KEYS = ["CLAUDE.md", "skill and prompt blocks", "project playbook", "base playbook", "superpowers"]  # spec 3
CLASS_LINE = "Default owner-only classes: "
SKILL_PHRASES = {   # heading -> key phrases (case-insensitive), each from the source cited on its line (plan Task B2.3)
    "Verification method": ["directly", "by contradiction", "record both commands",
                            "input-domain table", "independent expected value"],                     # spec 8; Q-SDDT-5
    "Pipeline and gates": ["`python3 -m gates run_all`", "all-green", "pull request", "owner's approval"],  # spec 8
    "Continuation": ["handoff", "80 %", "Nothing continues from inherited memory", "handoff is complete", "TaskStop"],
    "Owner questions": ["search before asking", "recommended option", "Also open", "`decisions batch --since`",
                        "`source`"],                                                                  # spec 7.1
    "Change kinds": ["superpowers:brainstorming", "superpowers:writing-plans",
                     "superpowers:subagent-driven-development", "superpowers:executing-plans"],       # spec 8
    "Session resume": ["`required_reads`", "investigator", "Resume check", "before any edit or dispatch"],  # spec 9
    "Document locations": ["`docs/strict-delivery/specs/`", "`docs/strict-delivery/plans/`",
                           "`docs/strict-delivery/reviews/`", "override", "superpowers"],             # spec 3, 5
    "Judgment, not gated": ["judgment", "playbook/rules.md"],                                         # spec 8
}
# Sentence pins (stream rule: every content sentence has an executable check): every sentence of a section holds at
# least one pin of its section, and every pin occurs in its section. Sources: spec 3, 7.1, 7.4, 8, 9, 10; session-resume
# design 3.1-3.8; playbook/roles.md, decisions.md, sessions.md, review.md.
PINS = {
    "When it applies": ["start of every session", "before every change", "`playbook/`"],
    "Precedence": ["highest first"] + PRECEDENCE_KEYS + ["the higher layer wins"],
    "Roles and tiers": ["`playbook/roles.md`", "names a tier, never a model", "workers never dispatch"],
    "Decision classes": ["always the owner's", "`decision_classes.owner_only`", CLASS_LINE.strip(),
                         "`playbook/decisions.md`", "only inside an approved plan"],
    "Owner questions": ["search before asking", "found answered", "id, class, the question, the recommended option "
                        "with its cost, every alternative with its cost, effect, topics and `applies_to`",
                        "`model-policy`", "one batch", "restarts as soon as every question with its `source`",
                        "only the session writes decision records"],
    "Verification method": ["by contradiction", "no executable check", "input-domain table", "`playbook/review.md`",
                            "Input domains"],
    "Change kinds": ["superpowers:brainstorming", "dispatches no writer"],
    "Pipeline and gates": ["register row", "final verifier", "`python3 -m gates run_all`", "owner's approval"],
    "Session resume": ["no memory of the work", "`playbook/sessions.md`", "`skills`", "`required_reads`",
                       "investigator", "Resume check", "before any edit or dispatch", "take over at once",
                       "no hook holds the session", "continued worker never dispatches"],
    "Continuation": ["Continuation is automatic", "Nothing continues from inherited memory", "`block.max_tasks`",
                     "handoff is complete", "`git status --porcelain --untracked-files=all`", "handoff field check",
                     "background-job check", "bounded timeout", "own command line", "completion record",
                     "waiting on its own background work", "Handoffs and continuation"],
    "Document locations": ["`docs/strict-delivery/specs/`", "override"],
    "Judgment, not gated": ["`judgment`", "`rule-override`"],
}
_LIST_MARK = re.compile(r"(?:[0-9]+\.|-) ")


def read_bytes(rel):
    with open(os.path.join(pc.REPO_ROOT, rel), "rb") as f:
        return f.read()


def read(rel):
    """UTF-8 text of a repository file, from the repository root whatever the working directory."""
    return read_bytes(rel).decode("utf-8")


def need(cond, message):
    """AssertionError(message) unless cond; an explicit raise, so `python -O` keeps the check."""
    if not cond:
        raise AssertionError(message)


def byte_problems(raw):
    """Q-B23v2-2 (a): ASCII only, LF only, no control byte, exactly one final newline (the prompt-block byte rules),
    and no trailing whitespace (as every B-owned markdown file)."""
    out, seen, line = [], set(), 1
    for b in raw:
        if b == 0x0a:
            line += 1
            continue
        kind = ("line-ending" if b == 0x0d else "control" if b < 0x20 or b == 0x7f else
                "encoding" if b >= 0x80 else None)
        if kind and (kind, line) not in seen:
            seen.add((kind, line))
            out.append("%s: byte 0x%02x on line %d" % (kind, b, line))
    if not raw.endswith(b"\n"):
        out.append("final-newline: missing")
    elif raw.endswith(b"\n\n"):
        out.append("final-newline: more than one")
    for n, ln in enumerate(raw.split(b"\n"), 1):
        if ln.endswith((b" ", b"\t")):
            out.append("trailing-ws: line %d" % n)
    return out


def check_front_matter(t):                       # plan test_front_matter; FM1-FM4, FM6, FM7 (Q-B22v2-1 (a))
    lines = t.split("\n")
    need(len(lines) > 4, "front matter: file too short")
    need(lines[0] == "---" and lines[1] == "name: strict-delivery" and lines[2].startswith("description: ")
         and lines[3] == "---", "front matter: lines 1-4")
    need(pc.front_matter(t) == {"name": "strict-delivery", "description": DESCRIPTION}, "front matter: values")


def check_title(t):                              # FM5; HD4: the first heading follows the title, no text before it
    lines = t.split("\n")
    need(lines[4:7] == ["# Strict delivery", "", "## " + HEADINGS[0]], "title: lines 5-7")


def check_headings(t):                           # plan test_headings_exact; HD1
    need([l[3:] for l in t.split("\n") if l.startswith("## ")] == HEADINGS, "headings")


def check_precedence(t):                         # plan test_precedence_order; PR1-PR3
    p = section(t, "Precedence")
    at = [p.index(k) for k in PRECEDENCE_KEYS]
    need(at == sorted(at), "precedence: first occurrences out of order")
    items = [l for l in p.split("\n") if re.match(r"[0-9]+\. ", l)]
    need([l.split(". ", 1)[0] for l in items] == ["1", "2", "3", "4", "5"], "precedence: not a five-item list")
    for item, key in zip(items, PRECEDENCE_KEYS):
        start = p.index(item)
        need(start <= p.index(key) < start + len(item), "precedence: %r first named outside item %r" % (key, item))
    need("the higher layer wins" in p, "precedence: the higher layer wins")


def check_roles(t):                              # plan test_roles_and_classes_named, roles half; RT1
    body = section(t, "Roles and tiers")
    for r in SPEC_ROLES:
        need("`%s`" % r in body, "roles: %s" % r)
    need("`playbook/roles.md`" in body, "roles: playbook/roles.md")


def class_list(t):
    """The slugs of the one line of section "Decision classes" that starts with CLASS_LINE; the line is exactly the
    slugs as code spans joined by ', ' and ended by '.' (DC1b: one parseable line)."""
    found = [l for l in section(t, "Decision classes").split("\n") if l.startswith(CLASS_LINE)]
    need(len(found) == 1, "classes: %d default-class lines" % len(found))
    slugs = re.findall(r"`([^`]*)`", found[0])
    need(found[0] == CLASS_LINE + ", ".join("`%s`" % s for s in slugs) + ".", "classes: line form")
    return slugs


def check_classes(t):                            # plan test_roles_and_classes_named, classes half; DC1, DC1b
    body = section(t, "Decision classes")
    for s in OWNER_ONLY:
        need("`%s`" % s in body, "classes: %s" % s)
    need("`decision_classes.owner_only`" in body, "classes: decision_classes.owner_only")
    need(class_list(t) == OWNER_ONLY, "classes: the default list")
    need("profile-override" not in body, "classes: profile-override (Task 4a.3 adds it)")


def check_search(t):                             # plan test_search_before_asking; DC3
    need("search before asking" in t.lower(), "search before asking")


def check_phrases(t):                            # plan test_skill_section_phrases
    for h, phrases in SKILL_PHRASES.items():
        body = section(t, h).lower()
        for s in phrases:
            need(s.lower() in body, "phrase: %s %r" % (h, s))


def section_sentences(body):
    """Sentences of a section body: each non-empty line, its list marker dropped, split by the rules.md splitter."""
    out = []
    for line in body.split("\n"):
        if line.strip():
            out.extend(sentences(_LIST_MARK.sub("", line, count=1) if _LIST_MARK.match(line) else line))
    return out


def check_pins(t):                               # stream rule; WA1, PR3, OQ2, OQ4, VM2, CK1, SR2, CO2, CO3
    for h in HEADINGS:
        body = section(t, h)
        low = body.lower()
        for pin in PINS[h]:
            need(pin.lower() in low, "pin: %s %r absent" % (h, pin))
        for s in section_sentences(body):
            need(any(pin.lower() in s.lower() for pin in PINS[h]), "pin: %s unpinned sentence %r" % (h, s[:50]))


def check_forbidden(t):                          # plan test_no_forbidden_strings_in_skill; HD3, FM4, RT2, DL2
    need(forbidden_hits(t) == [], "forbidden: %r" % (forbidden_hits(t),))


def check_placeholders(t):                       # PH1 (Q-B23v2-1 (a))
    need(pc.placeholder_hits(t) == [], "placeholder: %r" % (pc.placeholder_hits(t),))


def check_links(t):                              # DL3: no inline link and no anchor cite (fail closed)
    masked = "\n".join(pc._mask_spans(l) for l in t.split("\n"))
    need("](" not in masked, "links: an inline link")
    need(not re.search(r"`[^`\s]*\.md#[^`]*`", t), "links: an anchor cite")


def judgment_ids():
    return {r["id"] for r in table_rows(read("playbook/rules.md")) if r["enforced by"] == "judgment"}


def check_judgment(t):                           # JG2: rule ids named, if any, are exactly the judgment rows
    ids = set(re.findall(r"SD-R[0-9]+", section(t, "Judgment, not gated")))
    need(ids in (set(), judgment_ids()), "judgment: ids %r" % sorted(ids))


CHECKS = (("front-matter", check_front_matter), ("title", check_title), ("headings", check_headings),
          ("precedence", check_precedence), ("roles", check_roles), ("classes", check_classes),
          ("search", check_search), ("phrases", check_phrases), ("pins", check_pins),
          ("forbidden", check_forbidden), ("placeholders", check_placeholders), ("links", check_links),
          ("judgment", check_judgment))


def failed(raw):
    """Names of the checks the bytes fail; 'bytes' for byte_problems."""
    out = ["bytes"] if byte_problems(raw) else []
    t = raw.decode("utf-8", "replace")
    for name, fn in CHECKS:
        try:
            fn(t)
        except (AssertionError, ValueError, IndexError):
            out.append(name)
    return out


def changed(text, old, new):
    need(old in text, "sample: %r not in the text" % old)
    return text.replace(old, new, 1)


def in_section(text, heading, fn):
    body = section(text, heading)
    new = fn(body)
    need(new != body, "sample: change to %r changed nothing" % heading)
    return text.replace(body, new, 1)


class SkillFileTest(unittest.TestCase):
    """The plan's tests, on the real file."""

    def test_front_matter(self):                                  # FM1-FM4, FM6, FM7
        check_front_matter(read(SKILL))

    def test_title(self):                                         # FM5, HD4
        check_title(read(SKILL))

    def test_headings_exact(self):                                # HD1
        check_headings(read(SKILL))

    def test_precedence_order(self):                              # PR1-PR3
        check_precedence(read(SKILL))

    def test_roles_and_classes_named(self):                       # RT1, DC1, DC1b
        check_roles(read(SKILL))
        check_classes(read(SKILL))

    def test_search_before_asking(self):                          # DC3
        check_search(read(SKILL))

    def test_skill_section_phrases(self):                         # OQ1, OQ3, VM1, CK1, PG1, SR1, CO1, CO4, DL1, JG1
        check_phrases(read(SKILL))

    def test_every_sentence_pinned(self):                         # WA1, PR3, OQ2, OQ4, VM2, SR2, CO2, CO3
        check_pins(read(SKILL))

    def test_no_forbidden_strings_in_skill(self):                 # HD3, FM4, RT2, DL2
        check_forbidden(read(SKILL))

    def test_no_angle_placeholder_outside_code(self):             # PH1
        check_placeholders(read(SKILL))

    def test_no_links_or_anchor_cites(self):                      # DL3
        check_links(read(SKILL))

    def test_judgment_ids(self):                                  # JG2
        check_judgment(read(SKILL))

    def test_bytes(self):                                         # HD2 (Q-B23v2-2 (a))
        self.assertEqual(byte_problems(read_bytes(SKILL)), [])

    def test_all_checks_pass(self):
        self.assertEqual(failed(read_bytes(SKILL)), [])

    def test_owner_only_matches_config_defaults(self):            # DC2 (Q-B23-1 (a), Q-B22v2-5 (a))
        from gates.lib.config import DEFAULTS
        table = [r["slug"] for r in table_rows(section(read("playbook/decisions.md"), "Owner-only classes"))]
        self.assertEqual(DEFAULTS["decision_classes"]["owner_only"], OWNER_ONLY)
        self.assertEqual(class_list(read(SKILL)), OWNER_ONLY)
        self.assertEqual(table, OWNER_ONLY)

    def test_read_from_another_cwd(self):
        cwd = os.getcwd()
        try:
            os.chdir(os.path.dirname(pc.REPO_ROOT))
            self.assertEqual(failed(read_bytes(SKILL)), [])
        finally:
            os.chdir(cwd)


DESC_LINE = 'description: "%s"' % DESCRIPTION
TEXT_MUTANTS = (   # (row, old, new, check that refuses it); each applied once to the real file
    ("FM1", "---\nname", "--- \nname", "front-matter"), ("FM1", "---\nname", "name", "front-matter"),
    ("FM2", "name: strict-delivery", "name: Strict-Delivery", "front-matter"),
    ("FM2", "name: strict-delivery", "name:strict-delivery", "front-matter"),
    ("FM2", "name: strict-delivery\n", "", "front-matter"),
    ("FM2", "name: strict-delivery", 'name: "strict-delivery"', "front-matter"),
    ("FM3", DESC_LINE, DESC_LINE + "\n" + DESC_LINE, "front-matter"),
    ("FM3", DESC_LINE, "description: ", "front-matter"),
    ("FM3", DESC_LINE, "description: >\n  " + DESCRIPTION, "front-matter"),
    ("FM3", DESC_LINE, "description: |\n  " + DESCRIPTION, "front-matter"),
    ("FM4", "Overrides superpowers.", "Overrides opus.", "forbidden"),
    ("FM4", "Overrides superpowers.", "Ask benji.", "forbidden"),
    ("FM5", "# Strict delivery\n", "# Strict Delivery\n", "title"),
    ("FM5", "# Strict delivery\n", "", "title"),
    ("FM6", DESC_LINE, "description: Use it: always", "front-matter"),
    ("FM6", DESC_LINE, "description: - Use it", "front-matter"),
    ("FM6", DESC_LINE, "description: `Use` it", "front-matter"),
    ("FM7", DESC_LINE, "description: [a, b]", "front-matter"),
    ("FM7", DESC_LINE, "description: x # note", "front-matter"),
    ("PH1", "in order.\n", "in <n> order.\n", "placeholders"),
    ("PH1", "in order.\n", "in SD-R<n> order.\n", "placeholders"),
    ("PH1", "in order.\n", "in <sha>\norder.\n", "placeholders"),
    ("HD1", "## Change kinds\n", "", "headings"),
    ("HD1", "## Change kinds\n", "## Extra\n\n## Change kinds\n", "headings"),
    ("HD1", "## Document locations", "## Document Locations", "headings"),
    ("HD3", "`docs/strict-delivery/plans/`", "`docs/superpowers/plans/`", "forbidden"),
    ("HD3", "and workers never dispatch", "and workers never dispatch (lap-timer)", "forbidden"),
    ("HD3", "and workers never dispatch", "and workers never dispatch (A1-REQ-2)", "forbidden"),
    ("HD3", "and workers never dispatch", "and workers never dispatch (D12)", "forbidden"),
    ("HD3", "and workers never dispatch", "and workers never dispatch (/Users/alice/x)", "forbidden"),
    ("HD4", "# Strict delivery\n\n", "# Strict delivery\n\nIntro text.\n\n", "title"),
    ("PR1", "4. The base playbook", "4. The project playbook", "precedence"),
    ("PR2", "Precedence, highest first:", "Unlike superpowers, precedence, highest first:", "precedence"),
    ("PR2", "Precedence, highest first:", "Our `CLAUDE.md` and precedence, highest first:", "precedence"),
    ("PR3", "the higher layer wins", "the lower layer wins", "precedence"),
    ("RT1", "`implementer_transcription`, ", "", "roles"),
    ("RT1", "`playbook/roles.md`", "`playbook/role.md`", "roles"),
    ("RT2", "names a tier, never a model", "names a tier, never a model such as sonnet", "forbidden"),
    ("DC1", "`finding-class`, ", "", "classes"),
    ("DC1", "config `decision_classes.owner_only`", "config `decision_classes`", "classes"),
    ("DC1b", "`program-close`.", "`program-close`, `profile-override`.", "classes"),
    ("DC1b", "`triage`, `spec-direction`", "`spec-direction`, `triage`", "classes"),
    ("DC1b", "`program-close`.", "`program-close`", "classes"),
    ("OQ2", "the recommended option with its cost, every alternative", "every alternative with its cost, the "
     "recommended option", "pins"),
    ("OQ3", "`decisions batch --since`", "`python3 -m gates decisions batch --since <sha>`", "phrases"),
    ("CO4", "80 %", "80%", "phrases"), ("CO4", "80 %", "80 %", "phrases"),
    ("DL2", "`docs/strict-delivery/specs/`", "`docs/superpowers/specs/`", "forbidden"),
    ("DL3", "Specs live in `docs/strict-delivery/specs/`", "Specs live in [specs](docs/strict-delivery/specs/), "
     "`docs/strict-delivery/specs/`", "links"),
    ("DL3", "`playbook/review.md`", "`playbook/review.md#input-domains`", "links"),
    ("JG2", "`judgment` have no gate", "`judgment` (SD-R5) have no gate", "judgment"),
    ("JG2", "`judgment` have no gate", "`judgment` (SD-R12) have no gate", "judgment"),
)
BYTE_MUTANTS = (   # HD2 (Q-B23v2-2 (a)): (old, new); each refused by byte_problems
    (b"section", "§".encode("utf-8")), (b"never a model", "never — a model".encode("utf-8")),
    (b"\"do not", "“do not".encode("utf-8")), (b"\n", b"\r\n"), (b"## Precedence\n", b"## Precedence \n"),
    (b"## Precedence\n", b"## Precedence\t\n"), (b"## Precedence\n", b"## Precedence\x07\n"),
)
ACCEPTED = (   # (row, old, new, check that accepts it)
    ("PH1", "in order.\n", "in `<n>` order.\n", "placeholders"),
    ("PH1", "in order.\n", "in order.\n\n```\n<n>\n```\n", "placeholders"),
    ("HD1", "## Change kinds\n", "## Change kinds\n### Sub\n", "headings"),
    ("JG2", "`judgment` have no gate", "`judgment` (SD-R5, SD-R6, SD-R7, SD-R8, SD-R9, SD-R14, SD-R15, SD-R16, "
     "SD-R19) have no gate", "judgment"),
    ("DL3", "Specs live in `docs/strict-delivery/specs/`", "Specs live in `docs/strict-delivery/specs/` (`a](b`)",
     "links"),
)
HARMLESS = (   # unpinned rewordings: every check passes (stream rule: a harmless rewording never fails the suite)
    ("within the configured depth and concurrency limits", "inside the configured depth and concurrency limits"),
    ("A question found answered is cited, not asked.", "A question found answered is cited and not asked."),
)


class SkillMutantTest(unittest.TestCase):
    def test_text_mutants_refused(self):
        t = read(SKILL)
        for row, old, new, check in TEXT_MUTANTS:
            with self.subTest(row=row, new=new[:40]):
                self.assertIn(check, failed(changed(t, old, new).encode("utf-8")))

    def test_byte_mutants_refused(self):                          # HD2
        raw = read_bytes(SKILL)
        for old, new in BYTE_MUTANTS:
            with self.subTest(new=new):
                self.assertIn(old, raw)
                self.assertTrue(byte_problems(raw.replace(old, new, 1)))
        for bad in (raw[:-1], raw + b"\n", b"\xef\xbb\xbf" + raw, raw.replace(b"\n", b"\r\n")):
            self.assertTrue(byte_problems(bad))

    def test_accepted_changes(self):
        t = read(SKILL)
        for row, old, new, check in ACCEPTED:
            with self.subTest(row=row, new=new[:40]):
                self.assertNotIn(check, failed(changed(t, old, new).encode("utf-8")))

    def test_harmless_rewordings_pass(self):
        t = read(SKILL)
        for old, new in HARMLESS:
            with self.subTest(new=new):
                self.assertEqual(failed(changed(t, old, new).encode("utf-8")), [])

    def test_each_phrase_absent_or_in_another_section(self):     # plan dimension SKILL_PHRASES; OQ1 VM1 PG1 SR1 CO1 DL1
        t = read(SKILL)
        for h, phrases in SKILL_PHRASES.items():
            other = HEADINGS[0] if h != HEADINGS[0] else HEADINGS[1]
            for s in phrases:
                gone = in_section(t, h, lambda b: re.sub(re.escape(s), "zzz", b, flags=re.I))
                moved = in_section(gone, other, lambda b: b.rstrip("\n") + " " + s + "\n" + b[len(b.rstrip("\n")) + 1:])
                for name, bad in (("absent", gone), ("moved", moved)):
                    with self.subTest(heading=h, phrase=s, case=name):
                        self.assertIn("phrases", failed(bad.encode("utf-8")))

    def test_each_pin_absent(self):                               # WA1 and every pinned sentence
        t = read(SKILL)
        for h in HEADINGS:
            for pin in PINS[h]:
                with self.subTest(heading=h, pin=pin):
                    bad = in_section(t, h, lambda b: re.sub(re.escape(pin), "zzz", b, flags=re.I))
                    self.assertIn("pins", failed(bad.encode("utf-8")))

    def test_unpinned_sentence_refused(self):                     # WA1: a new sentence with no pin, in every section
        t = read(SKILL)
        for h in HEADINGS:
            with self.subTest(heading=h):
                bad = in_section(t, h, lambda b: b.rstrip("\n") + " Also do the opposite.\n" + b[len(b.rstrip("\n")) + 1:])
                self.assertIn("pins", failed(bad.encode("utf-8")))
                empty = in_section(t, h, lambda b: "\n")
                self.assertTrue(failed(empty.encode("utf-8")))

    def test_each_role_and_slug_missing(self):                    # RT1, DC1: every member of the dimension
        t = read(SKILL)
        for r in SPEC_ROLES:
            with self.subTest(role=r):
                self.assertIn("roles", failed(in_section(t, "Roles and tiers",
                                                         lambda b: b.replace("`%s`" % r, "zzz")).encode("utf-8")))
        for s in OWNER_ONLY:
            with self.subTest(slug=s):
                self.assertIn("classes", failed(in_section(t, "Decision classes",
                                                           lambda b: b.replace("`%s`" % s, "zzz")).encode("utf-8")))

    def test_precedence_each_pair_swapped_and_each_missing(self):    # PR1
        t = read(SKILL)
        p = section(t, "Precedence")
        items = [l for l in p.split("\n") if re.match(r"[0-9]+\. ", l)]
        self.assertEqual(len(items), 5)
        for i in range(5):
            with self.subTest(missing=i + 1):
                self.assertIn("precedence", failed(changed(t, items[i] + "\n", "").encode("utf-8")))
            for j in range(i + 1, 5):
                with self.subTest(swap=(i + 1, j + 1)):
                    a, b = items[i].split(". ", 1)[1], items[j].split(". ", 1)[1]
                    bad = in_section(t, "Precedence", lambda q: q.replace(a, "@@").replace(b, a).replace("@@", b))
                    self.assertIn("precedence", failed(bad.encode("utf-8")))

    def test_headings_reordered(self):                            # HD1
        t = read(SKILL)
        for i in range(len(HEADINGS) - 1):
            a, b = "## %s\n" % HEADINGS[i], "## %s\n" % HEADINGS[i + 1]
            with self.subTest(swap=HEADINGS[i]):
                bad = t.replace(a, "@@").replace(b, a).replace("@@", b)
                self.assertIn("headings", failed(bad.encode("utf-8")))
        fenced = changed(t, "## Change kinds\n", "```\n## Fenced\n```\n\n## Change kinds\n")
        self.assertIn("headings", failed(fenced.encode("utf-8")))

    def test_drift_lists_refuse_subset_and_order(self):           # DC2: strict list equality, not a subset test
        t = read(SKILL)
        for bad in (changed(t, ", `program-close`.", "."), changed(t, "`stream-merge`, `request-dispute`",
                                                                     "`request-dispute`, `stream-merge`")):
            with self.subTest(bad=bad.count("\n")):
                self.assertNotEqual(class_list(bad), OWNER_ONLY)
        d = read("playbook/decisions.md")
        rows = [r["slug"] for r in table_rows(section(changed(d, "| program-close | closing a program |\n", ""),
                                                      "Owner-only classes"))]
        self.assertNotEqual(rows, OWNER_ONLY)

    def test_failed_reports_short_file(self):
        self.assertIn("front-matter", failed(b"---\n"))
        self.assertIn("bytes", failed(b"---"))


if __name__ == "__main__":
    unittest.main()
