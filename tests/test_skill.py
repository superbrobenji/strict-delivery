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
                            "input-domain table", "independent expected value",
                            "version differences"],                                                  # spec 8; Q-SDDT-5; G3
    "Decision classes": ["small point", "owner delegation", "when unsure"],                          # spec 7.1; G1, F-2
    "Roles and tiers": ["explicitly", "never inherits"],                                             # spec 10; G2
    "Pipeline and gates": ["`python3 -m gates run_all`", "all-green", "pull request", "owner's approval"],  # spec 8
    "Continuation": ["handoff", "80 %", "Nothing continues from inherited memory", "handoff is complete", "TaskStop",
                     "never ends its turn", "handback"],                                             # spec 10; G4
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
    "Roles and tiers": ["`playbook/roles.md`", "names tiers, never a model", "workers never dispatch",
                        "never inherits its dispatcher's model",                                   # G2
                        "its `## Model` names the model config `models.tiers` maps that tier to"],  # U-2 (B4)
    "Decision classes": ["always the owner's", "`decision_classes.owner_only`", CLASS_LINE.strip(),
                         "`playbook/decisions.md`", "only inside an approved plan",
                         "The one exception is a small point", "The owner keeps work added or removed"],  # G1, F-2
    "Owner questions": ["search before asking", "found answered", "id, class, the question, the recommended option "
                        "with its cost, every alternative with its cost, effect, topics and `applies_to`",
                        "`model-policy`", "one batch", "restarts as soon as every question with its `source`",
                        "only the session writes decision records"],
    "Verification method": ["by contradiction", "no executable check", "input-domain table", "`playbook/review.md`",
                            "Input domains", "known version differences",                           # G3
                            "never samples an open grammar"],                                       # U-4 (B4)
    "Change kinds": ["superpowers:brainstorming", "dispatches no writer"],
    "Pipeline and gates": ["register row", "final verifier", "`python3 -m gates run_all`", "owner's approval",
                           "where the profile enables it (strict), a top-tier final verifier"],   # F-B23R-1; spec 12
    "Session resume": ["no memory of the work", "`playbook/sessions.md`", "`skills`", "`required_reads`",
                       "investigator", "Resume check", "before any edit or dispatch", "take over at once",
                       "no hook holds the session", "continued worker never dispatches"],
    "Continuation": ["Continuation is automatic", "Nothing continues from inherited memory", "`block.max_tasks`",
                     "handoff is complete", "`git status --porcelain --untracked-files=all`", "handoff field check",
                     "background-job check", "bounded timeout", "own command line", "completion record",
                     "waiting on its own background work", "Handoffs and continuation",
                     "never ends its turn while a child", "its handback arrives",                    # G4
                     "dispatches nothing new and waits"],                                           # U-5 (B4)
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
    # U-6 (B4): a pin is a whole token (pc.whole_token, case-insensitive), never a substring of a longer word
    for h in HEADINGS:
        body = section(t, h)
        low = body.lower()
        for pin in PINS[h]:
            need(pc.whole_token(pin.lower(), low), "pin: %s %r absent" % (h, pin))
        for s in section_sentences(body):
            need(any(pc.whole_token(pin.lower(), s.lower()) for pin in PINS[h]),
                 "pin: %s unpinned sentence %r" % (h, s[:50]))


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


SMALL_POINT = ("The one exception is a small point inside the plan's intent: a question of format, syntax, bytes or "
               "whitespace, wording, layout, naming, test detail, a test-helper contract or an error-return shape is "
               "not asked; the controller decides it, taking the option it would recommend, and ledgers it as "
               "`Decision (owner delegation): what -- why -- cost if wrong`, outside `rulings.max_per_block`.")
OWNER_KEEPS = ("The owner keeps work added or removed, plan and spec changes, architecture choices, framework or "
               "process changes, agent models and costs, merge-blocking risk, and anything irreversible or otherwise "
               "important; when unsure, the controller asks.")
EXPLICIT_MODEL = "The dispatch call passes that model explicitly; a dispatch never inherits its dispatcher's model."
VERSION_ROWS = ("Every input-domain table carries rows for the known version differences of the project's own stack "
                "and runtime, each run on every runtime the project supports.")
NO_LIVE_CHILD = ("A controller never ends its turn while a child or a background job it started still runs: it waits "
                 "inside its turn, in the foreground, and returns only after every child has handed back.")
FINISHED = ("A child has finished only when its handback arrives, never because its report file already holds a "
            "status line.")
DIRECTIVES = (   # (id, section, the line they follow (its start), the lines that follow it, one line each)
    ("G1", "Decision classes", "A controller rules only inside an approved plan,", (SMALL_POINT, OWNER_KEEPS)),
    ("G2", "Roles and tiers", "Every dispatch carries its role's prompt block", (EXPLICIT_MODEL,)),
    ("G3", "Verification method", "The input-domain method, stated in full", (VERSION_ROWS,)),
    ("G4", "Continuation", "Before a controller ledgers a child's result", (NO_LIVE_CHILD, FINISHED)),
)
DIRECTIVE_TOKENS = (("Decision classes", "owner delegation"), ("Decision classes", "when unsure"),
                    ("Roles and tiers", "never inherits"), ("Verification method", "version differences"),
                    ("Continuation", "handed back"), ("Continuation", "handback"))


U2_LINE = ("Every dispatch carries its role's prompt block byte for byte and chooses a tier; its `## Model` names the "
           "model config `models.tiers` maps that tier to, and every other line of a brief or report names tiers, "
           "never a model.")
OPEN_GRAMMAR = ("Every input-domain table enumerates the full input class or restricts the input, so the code refuses "
                "what lies outside the enumerated class, and never samples an open grammar.")
LIVE_CHILDREN = ("Before it writes that handoff, a controller dispatches nothing new and waits, inside its turn, for the "
                 "handback of every child still running; a child that a usage-limit stop cuts off before its handback "
                 "is listed in the handoff's `live_subagents`.")
B4_LINES = (   # Task B4 (id, section, the line before it (its start), the line, the line after it (its start) or None)
    ("U-2", "Roles and tiers", "The roles, with their prompt blocks", U2_LINE, EXPLICIT_MODEL),
    ("U-4", "Verification method", VERSION_ROWS, OPEN_GRAMMAR, None),
    ("U-5", "Continuation", "Continuation is automatic: an agent", LIVE_CHILDREN, "Nothing continues from inherited memory"),
)


def check_b4(t):                                 # Task B4 U-2, U-4, U-5 (FV-1: counted over the whole file)
    for ident, h, before, line, after in B4_LINES:
        body = section(t, h)
        found = [l for l in body.split("\n") if l.startswith(before)]
        need(len(found) == 1, "b4: %s anchor lines: %d" % (ident, len(found)))
        chain = found[0] + "\n\n" + line
        need(chain in body, "b4: %s not directly after its anchor, on its own line" % ident)
        tail = body.split(chain, 1)[1]
        need(tail.startswith("\n\n" + after) if after else tail.strip("\n") == "", "b4: %s what follows" % ident)
        need(t.count(line) == 1, "b4: %s occurs %d times" % (ident, t.count(line)))


def check_directives(t):                         # Task B3 G1-G4: each sentence once, on its own line, after its anchor
    check_b4(t)
    for ident, h, start, lines in DIRECTIVES:
        body = section(t, h)
        found = [l for l in body.split("\n") if l.startswith(start)]
        need(len(found) == 1, "directives: %s anchor lines: %d" % (ident, len(found)))
        need("\n\n".join((found[0],) + lines) in body, "directives: %s not after its anchor, one line each" % ident)
        for s in lines:
            need(t.count(s) == 1, "directives: %s %r occurs %d times" % (ident, s[:40], t.count(s)))
    for h, token in DIRECTIVE_TOKENS:
        need(pc.whole_token(token, section(t, h)), "directives: %s lacks token %r" % (h, token))


CHECKS = (("front-matter", check_front_matter), ("title", check_title), ("headings", check_headings),
          ("precedence", check_precedence), ("roles", check_roles), ("classes", check_classes),
          ("search", check_search), ("phrases", check_phrases), ("pins", check_pins),
          ("forbidden", check_forbidden), ("placeholders", check_placeholders), ("links", check_links),
          ("judgment", check_judgment), ("directives", check_directives))


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
    ("RT2", "names tiers, never a model", "names tiers, never a model such as sonnet", "forbidden"),     # U-2 (B4)
    ("U-2", "; its `## Model` names the model config `models.tiers` maps that tier to,", "", "pins"),      # the `## Model` clause
    ("U-2", "chooses a tier;", "names a tier;", "directives"),
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
    ("G1", "a small point inside", "a minor point inside", "pins"),                    # F-2: the threshold sentence
    ("G1", "The owner keeps work added or removed", "The owner keeps work", "pins"),
    ("G2", "never inherits its dispatcher's model", "may inherit its dispatcher's model", "pins"),
    ("G3", "known version differences", "known differences", "pins"),
    ("G4", "its handback arrives", "its report arrives", "pins"),
    ("G4", "never ends its turn while a child", "may end its turn while a child", "pins"),
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
    ("ledgers each ruling as", "records each ruling as"),                      # the anchor lines of G1-G4, an unpinned word
    ("minimum tiers and finding states", "minimum tiers and the finding states"),   # B4: line 29 is now pinned whole (U-2)
    ("an implementer lists every unstated behaviour", "an implementer lists each unstated behaviour"),
    ("it lists the child's background job ids", "it reads the child's background job ids"),
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

    def skill_text(self):
        """The text the harmless rows run on; the row-2 test replaces it with a reworded copy (FR-1, U-3)."""
        return read(SKILL)

    def test_harmless_rewordings_pass(self):                      # spec section 14; FR-1, U-3 (B4): absent = visible skip
        t = self.skill_text()
        self.harmless_ran = []
        for old, new in HARMLESS:
            with self.subTest(new=new):
                if old not in t:
                    self.skipTest("FR-1/U-3: %r is reworded on disk; unpinned, so never a failure" % old)
                self.assertEqual(failed(changed(t, old, new).encode("utf-8")), [])
                self.harmless_ran.append(old)

    def test_harmless_row_absent_on_disk_is_skipped_not_failed(self):   # B4 rows 2, 3 (FR-1, U-3)
        t = read(SKILL)
        absent = [old for old, new in HARMLESS if old not in t]
        for i, (old, new) in enumerate(HARMLESS):
            with self.subTest(reworded=old):
                case = SkillMutantTest("test_harmless_rewordings_pass")
                reworded = t.replace(old, new, 1) if old in t else t
                case.skill_text = lambda text=reworded: text
                result = unittest.TestResult()
                case.run(result)
                gone = absent + ([old] if old in t else [])
                self.assertEqual((result.failures, result.errors), ([], []))
                self.assertTrue(result.wasSuccessful())
                self.assertEqual(len(result.skipped), len(gone), result.skipped)
                self.assertEqual(case.harmless_ran, [o for o, _ in HARMLESS if o not in gone])
        case = SkillMutantTest("test_harmless_rewordings_pass")      # every row reworded at once: all skipped, none fails
        every = t
        for old, new in HARMLESS:
            every = every.replace(old, new, 1)
        case.skill_text = lambda: every
        result = unittest.TestResult()
        case.run(result)
        self.assertEqual((result.failures, result.errors), ([], []))
        self.assertEqual(len(result.skipped), len(HARMLESS), result.skipped)

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


class SkillDirectiveTest(unittest.TestCase):
    """Task B3 G1-G4 (G1 closes F-2): the new lines, in place, once, whole tokens, and the input-domain rows 1-14."""

    def test_new_lines_in_place_on_disk(self):                    # rows 1, 3, 4, 5, 10
        check_directives(read(SKILL))
        self.assertEqual(failed(read_bytes(SKILL)), [])

    def test_deleted_line_refused_by_the_pin_and_the_placement(self):   # row 1; F-2 for G1
        t = read(SKILL)
        for ident, h, start, lines in DIRECTIVES:
            for s in lines:
                with self.subTest(id=ident, line=s[:30]):
                    got = failed(changed(t, "\n\n" + s, "").encode("utf-8"))
                    self.assertIn("directives", got)
                    self.assertIn("pins", got)

    def test_moved_to_another_section_refused(self):              # row 2
        t = read(SKILL)
        for ident, h, start, lines in DIRECTIVES:
            for s in lines:
                with self.subTest(id=ident, line=s[:30]):
                    gone = changed(t, "\n\n" + s, "")
                    moved = in_section(gone, "Document locations", lambda b: b.rstrip("\n") + "\n\n" + s + "\n")
                    self.assertIn("directives", failed(moved.encode("utf-8")))

    def test_misplaced_refused(self):                             # row 3: first, glued to a line, reordered
        t = read(SKILL)
        for ident, h, start, lines in DIRECTIVES:
            anchor = [l for l in section(t, h).split("\n") if l.startswith(start)][0]
            chain = "\n\n".join(lines)
            with self.subTest(id=ident, case="before the anchor"):
                bad = changed(t, anchor + "\n\n" + chain, chain + "\n\n" + anchor)
                self.assertIn("directives", failed(bad.encode("utf-8")))
            with self.subTest(id=ident, case="glued to the anchor line"):
                bad = changed(t, anchor + "\n\n" + lines[0], anchor + " " + lines[0])
                self.assertIn("directives", failed(bad.encode("utf-8")))
            if len(lines) == 2:
                with self.subTest(id=ident, case="reordered"):
                    bad = changed(t, chain, lines[1] + "\n\n" + lines[0])
                    self.assertIn("directives", failed(bad.encode("utf-8")))
                with self.subTest(id=ident, case="glued between"):
                    bad = changed(t, chain, lines[0] + " " + lines[1])
                    self.assertIn("directives", failed(bad.encode("utf-8")))

    def test_twice_refused(self):                                 # row 4
        t = read(SKILL)
        for ident, h, start, lines in DIRECTIVES:
            for s in lines:
                with self.subTest(id=ident, line=s[:30]):
                    bad = changed(t, s, s + "\n\n" + s)
                    self.assertIn("directives", failed(bad.encode("utf-8")))

    def test_whole_tokens_joined_or_recased_refused(self):        # row 5
        t = read(SKILL)
        for h, token in DIRECTIVE_TOKENS:
            for name, new in (("joined before", "x" + token), ("joined after", token + "x"), ("case", token.upper())):
                with self.subTest(heading=h, token=token, case=name):
                    bad = in_section(t, h, lambda b: b.replace(token, new))
                    self.assertIn("directives", failed(bad.encode("utf-8")))

    def test_unpinned_line_after_a_new_line_refused(self):        # row 10
        t = read(SKILL)
        for ident, h, start, lines in DIRECTIVES:
            with self.subTest(id=ident):
                bad = changed(t, lines[-1], lines[-1] + "\n\nAlso do the opposite.")
                self.assertIn("pins", failed(bad.encode("utf-8")))

    def test_phrase_table_names_the_new_phrases(self):            # row 1: the key phrases of G1-G4 are in SKILL_PHRASES
        for h, want in (("Decision classes", ["small point", "owner delegation", "when unsure"]),
                        ("Roles and tiers", ["explicitly", "never inherits"]),
                        ("Verification method", ["version differences"]),
                        ("Continuation", ["never ends its turn", "handback"])):
            for s in want:
                with self.subTest(heading=h, phrase=s):
                    self.assertIn(s, SKILL_PHRASES[h])
                    self.assertIn(s.lower(), section(read(SKILL), h).lower())

    def test_new_lines_join_no_class(self):                       # row 10: no verifier-step or deferral member
        from tests.test_playbook import _DEFERRAL, _VERIFIER, verifier_step_problems
        for ident, h, start, lines in DIRECTIVES:
            for s in lines:
                s.encode("ascii")
                self.assertIsNone(_VERIFIER.search(s), s)
                self.assertIsNone(_DEFERRAL.search(s), s)
        self.assertEqual(verifier_step_problems(read(SKILL), SKILL), [])

    def test_forbidden_string_in_a_new_line_refused(self):        # row 9
        t = read(SKILL)
        for name, sample in (("model-name", "use Opus"), ("owner-handle", "ask superbrobenji"),
                             ("row-id", "row X9-ABC-1")):
            for ident, h, start, lines in DIRECTIVES:
                with self.subTest(id=ident, sample=sample):
                    bad = changed(t, lines[0], lines[0] + " " + sample)
                    self.assertIn("forbidden", failed(bad.encode("utf-8")))
                    self.assertIn(name, [x[0] for x in forbidden_hits(bad)])

    def test_control_and_non_ascii_bytes_in_a_new_line_refused(self):   # row 8
        raw = read_bytes(SKILL)
        for ident, h, start, lines in DIRECTIVES:
            s = lines[0].encode("ascii")
            for name, new in (("cr", s + b"\r"), ("tab", s + b"\t"), ("non-ascii", s.replace(b"e", "é".encode("utf-8"), 1))):
                with self.subTest(id=ident, case=name):
                    self.assertTrue(byte_problems(raw.replace(s, new, 1)))

    def test_digit_runs_refused_the_same(self):                   # row 13 (no int() on text)
        t = read(SKILL)
        for n in (4300, 4301):
            with self.subTest(digits=n):
                bad = in_section(t, "Decision classes", lambda b: b.rstrip("\n") + "\n\n" + "9" * n + "\n" + b[len(b.rstrip("\n")) + 1:])
                self.assertIn("pins", failed(bad.encode("utf-8")))
                glued = changed(t, SMALL_POINT, SMALL_POINT + " " + "9" * n)
                self.assertIn("directives", failed(glued.encode("utf-8")))

    def test_version_dependent_code_point_refused_by_the_character_check(self):   # row 14 (U+2C2F: Cn on 3.9, Lu on 3.13)
        t = read(SKILL)                                           # FV-2 (B4): the name is true on both interpreters
        c = chr(0x2C2F)
        for ident, h, start, lines in DIRECTIVES:
            with self.subTest(id=ident):
                bad = changed(t, lines[0], lines[0].replace("e", c, 1)).encode("utf-8")
                got = failed(bad)
                self.assertIn("bytes", got)
                self.assertIn("directives", got)
        for ident, h, before, line, after in B4_LINES:
            with self.subTest(id=ident, kind="b4"):
                got = failed(changed(t, line, line.replace("e", c, 1)).encode("utf-8"))
                self.assertIn("bytes", got)
                self.assertIn("directives", got)


class SkillB4Test(unittest.TestCase):
    """Task B4 (U-2, U-4, U-5 lines; FV-1 file-wide count; U-6 whole-token pins), input-domain rows 4-6, 8-14."""

    def test_new_lines_in_place_on_disk(self):                    # rows 8, 10, 11, 16
        check_b4(read(SKILL))
        self.assertEqual(failed(read_bytes(SKILL)), [])
        for ident, h, before, line, after in B4_LINES:
            self.assertEqual(read(SKILL).count(line), 1)
            line.encode("ascii")

    def test_old_unqualified_phrase_gone(self):                   # row 9
        self.assertNotRegex(read(SKILL), r"names a tier, never a model[;.:]")

    def test_deleted_line_refused_by_the_pin_and_the_placement(self):   # rows 8, 10, 11
        t = read(SKILL)
        for ident, h, before, line, after in B4_LINES:
            with self.subTest(id=ident):
                got = failed(changed(t, "\n\n" + line, "").encode("utf-8"))
                self.assertIn("directives", got)
                self.assertIn("pins", got)

    def test_moved_copied_or_doubled_refused(self):               # rows 4, 5, 10, 11: file-wide count
        t = read(SKILL)
        for ident, h, before, line, after in B4_LINES:
            gone = changed(t, "\n\n" + line, "")
            for name, bad in (
                    ("moved", in_section(gone, "Document locations", lambda b: b.rstrip("\n") + "\n\n" + line + "\n")),
                    ("copied", in_section(t, "Document locations", lambda b: b.rstrip("\n") + "\n\n" + line + "\n")),
                    ("copied into its own section", in_section(t, h, lambda b: b.rstrip("\n") + "\n\n" + line + "\n")),
                    ("doubled", changed(t, line, line + "\n\n" + line)),
                    ("doubled in a line", changed(t, line, line + " " + line))):
                with self.subTest(id=ident, case=name):
                    self.assertIn("directives", failed(bad.encode("utf-8")))
        for ident, h, start, lines in DIRECTIVES:                  # row 4: every earlier new line likewise
            for s in lines:
                with self.subTest(id=ident, line=s[:30], case="copied"):
                    bad = in_section(t, "Document locations", lambda b: b.rstrip("\n") + "\n\n" + s + "\n")
                    self.assertIn("directives", failed(bad.encode("utf-8")))

    def test_misplaced_refused(self):                             # rows 8, 10, 11
        t = read(SKILL)
        for ident, h, before, line, after in B4_LINES:
            anchor = [l for l in section(t, h).split("\n") if l.startswith(before)][0]
            with self.subTest(id=ident, case="before the anchor"):
                bad = changed(t, anchor + "\n\n" + line, line + "\n\n" + anchor)
                self.assertIn("directives", failed(bad.encode("utf-8")))
            with self.subTest(id=ident, case="glued to the anchor line"):
                bad = changed(t, anchor + "\n\n" + line, anchor + " " + line)
                self.assertIn("directives", failed(bad.encode("utf-8")))
            with self.subTest(id=ident, case="unpinned line after it"):
                bad = changed(t, line, line + "\n\nAlso do the opposite.")
                self.assertIn("pins", failed(bad.encode("utf-8")))

    def test_each_new_line_pin_dropped_refused(self):             # rows 8, 10, 11: the `## Model` clause and the others
        t = read(SKILL)
        for h, pin in (("Roles and tiers", "its `## Model` names the model config `models.tiers` maps that tier to"),
                       ("Roles and tiers", "names tiers, never a model"),
                       ("Verification method", "never samples an open grammar"),
                       ("Continuation", "dispatches nothing new and waits")):
            with self.subTest(heading=h, pin=pin):
                bad = in_section(t, h, lambda b: b.replace(pin, "zzz"))
                self.assertIn("pins", failed(bad.encode("utf-8")))

    def test_digit_runs_refused_the_same(self):                   # row 13 (no int() on text)
        t = read(SKILL)
        for ident, h, before, line, after in B4_LINES:
            got = []
            for n in (4300, 4301):
                with self.subTest(id=ident, digits=n):
                    bad = changed(t, line, line + " " + "9" * n).encode("utf-8")
                    self.assertEqual(byte_problems(bad), [])
                    got.append(failed(bad))
                    self.assertIn("directives", got[-1])
            self.assertEqual(got[0], got[1])

    def test_control_and_non_ascii_bytes_in_a_new_line_refused(self):   # row 8
        raw = read_bytes(SKILL)
        for ident, h, before, line, after in B4_LINES:
            s = line.encode("ascii")
            for name, new in (("cr", s + b"\r"), ("tab", s + b"\t"), ("non-ascii", s.replace(b"e", "é".encode("utf-8"), 1))):
                with self.subTest(id=ident, case=name):
                    self.assertTrue(byte_problems(raw.replace(s, new, 1)))

    def test_pins_are_whole_tokens(self):                         # U-6 (B4), row 12: through check_pins on the real file
        t = read(SKILL)
        pin = "never inherits its dispatcher's model"
        check_pins(t)

        def with_line(sentence):
            return in_section(t, "Roles and tiers", lambda b: b.rstrip("\n") + "\n\n" + sentence + "\n" +
                              b[len(b.rstrip("\n")) + 1:])
        for name, sentence in (("joined before", "x" + pin + "."), ("joined after", pin + "x."),
                               ("plural", pin + "s."), ("both", "x" + pin + "x."), ("digit after", pin + "9."),
                               ("hyphen after", pin + "-x."), ("underscore before", "_" + pin + ".")):
            with self.subTest(case=name):
                with self.assertRaises(AssertionError):
                    check_pins(with_line(sentence))
        for name, sentence in (("sentence start", pin + " always."), ("before a full stop", "A dispatch " + pin + "."),
                               ("before a comma", "A dispatch " + pin + ", always."),
                               ("before a semicolon", "A dispatch " + pin + "; always."),
                               ("before a backtick", "A dispatch " + pin + "`x`."),
                               ("before a closing parenthesis", "(A dispatch " + pin + ") always."),
                               ("upper case", "A dispatch " + pin.upper() + ".")):
            with self.subTest(case=name):
                check_pins(with_line(sentence))
        with self.subTest(case="handbacks"):                      # the plural of a pin word is not the pin
            bad = in_section(t, "Continuation", lambda b: b.replace("its handback arrives", "its handbacks arrive"))
            with self.assertRaises(AssertionError):
                check_pins(bad)
        with self.subTest(case="absent pin"):
            bad = in_section(t, "Roles and tiers", lambda b: b.replace(pin, "x" + pin))
            with self.assertRaises(AssertionError):
                check_pins(bad)
        with self.subTest(case="section-level check alone"):       # its sentence still holds another pin ("names tiers, ...")
            bad = in_section(t, "Roles and tiers", lambda b: b.replace("; its `## Model`", "; xits `## Model`"))
            self.assertIn("names tiers, never a model", bad)
            with self.assertRaises(AssertionError) as ctx:
                check_pins(bad)
            self.assertIn("absent", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
