"""Tests of the SessionStart and UserPromptSubmit handlers (Task 3a.2 rows S1-S20, U1-U4 and version row V2). Every run
goes through ``tests/hookrun.py``, the production entry ``python3 -m gates hook <Event>``, on ``make_repo`` repositories.
Expected lines are written by hand from the plan (P:3474-3486), the domain table and the session-resume design 3.1; the
whole stdout is compared as a list of lines wherever the table gives the lines. Failures that cannot be made with real
files (a raising library function, another framework directory) are injected by a ``sitecustomize`` on the PYTHONPATH of
the subprocess, never by editing the tree."""
import json
import os
import re
import stat
import sys
import tempfile
import unittest

from gates.lib import session, yamlsub
from tests.helpers import GitIsolatedTestCase, commit_all, git, make_repo, minimal_config, write_record
from tests.hookrun import FW, payload, run_hook

SITE = ("import json, os\n"
        "spec = os.environ.get('HOOKTEST_PATCH')\n"
        "if spec:\n"
        "    import importlib\n"
        "    import gates.lib.result as r\n"
        "    kinds = {'GateError': r.GateError, 'OSError': OSError, 'ValueError': ValueError}\n"
        "    for target, (kind, msg) in json.loads(spec).items():\n"
        "        modname, attr = target.rsplit('.', 1)\n"
        "        def raiser(*a, _c=kinds[kind], _m=msg, **kw):\n"
        "            raise _c(_m)\n"
        "        setattr(importlib.import_module(modname), attr, raiser)\n"
        "fw = os.environ.get('HOOKTEST_FW')\n"
        "if fw:\n"
        "    import gates.hook as h\n"
        "    h.framework_dir = lambda: fw\n")

PS = ".strict-delivery/state/plans"
DEC = ".strict-delivery/state/decisions"
IN_FORCE = DEC + "/in-force.md"
SKILL_REL = "skills/strict-delivery/SKILL.md"
SKILL_LINE = "Invoke the strict-delivery skill before any change."
DOCTOR = "; run /strict-delivery:doctor"
OPTS = [{"label": "yes", "cost": "none"}, {"label": "no", "cost": "some"}]
SHA = "a1b2c3d"
D1, D2, D3, D4 = "DEC-20261031-a2b3", "DEC-20261031-c4d5", "DEC-20261031-e6f7", "DEC-20261031-g8h9"
D5, D6, D7, D8 = "DEC-20261031-j2k3", "DEC-20261031-m4n5", "DEC-20261031-p6q7", "DEC-20261031-r8s9"
P1, P2 = "20261101-p1", "20261101-p2"   # a program name is <YYYYMMDD>-<slug> (programs.program_problem), so not the table's "p1"
SOURCES = ("startup", "resume", "fork", "clear", "compact", None, "x-unknown")   # RESUME_SOURCES: every source


def header(profile="strict", branch="main", base="main", programs="none"):
    return "strict-delivery: profile %s; branch %s; base %s; live programs: %s" % (profile, branch, base, programs)


def load_line(decisions=DEC):
    return "load: %s/in-force.md and the open decisions above" % decisions


def resume_expected(rel, skills, n, ledger_from):
    return ("resume %s: before any edit or dispatch, invoke the skills %s; read the default load and the context list, "
            "the %d required reads and the ledger from line %d; dispatch the read-only investigator check; ledger the "
            "Resume check line; report, and stop on any difference (session-resume design §3.1)"
            % (rel, skills, n, ledger_from))


def program_expected(p):
    return ("resume program %s: before any edit or dispatch, re-read the overview and the status page on %s/integration "
            "and dispatch the read-only investigator check of the program facts" % (p, p))


def resume_text(plan, nxt, branch, head, open_ids="none"):
    """The resume field spelled out from the Process text (not by ``resume_line``)."""
    return "Resume strict-delivery plan %s at %s; branch %s; head %s; open questions: %s." % (plan, nxt, branch, head, open_ids)


def _tag(kind):
    from gates.lib import schema
    s = schema.load_schema(os.path.join(schema.SCHEMAS_DIR, kind + ".yml"))
    return "%s/%d" % (s.kind, s.version)


def dec(id_, status="answered", **over):
    r = {"schema": _tag("decision"), "id": id_, "status": status, "class": "scope", "question": "Keep X?",
         "options": OPTS, "asked_at": SHA, "asked_by": "agent", "topics": ["ids"], "applies_to": [],
         "checked_against": [], "effect": "one-off"}
    if status == "answered":
        r.update(answer="Yes", answered_at={"at": SHA, "by": "who@example.invalid"})
    if status == "withdrawn":
        r["withdrawn"] = {"at": SHA, "by": "who@example.invalid", "reason": "asked twice"}
    r.update(over)
    return {k: v for k, v in r.items() if v is not None}


def lasting(id_, **over):
    return dec(id_, **{**dict(effect="lasting", rule="rule text", landed_in=["CLAUDE.md"]), **over})


def out_lines(p):
    if p.stdout == "":
        return []
    assert p.stdout.endswith("\n"), p.stdout
    return p.stdout[:-1].split("\n")


class Base(GitIsolatedTestCase):
    """A fixture repository, a plugin-data directory and a patch package per test."""
    CFG = None

    def setUp(self):
        super().setUp()
        self.repo = os.path.join(self.work, "repo")
        os.makedirs(self.repo)
        make_repo(self.repo, self.CFG)
        self.fx = os.path.join(self.tmp, "fx")
        os.makedirs(self.fx)
        with open(os.path.join(self.fx, "sitecustomize.py"), "w", encoding="utf-8") as fh:
            fh.write(SITE)
        self.data = os.path.join(self.tmp, "plugin-data")
        os.makedirs(self.data)

    def penv(self):
        return {"CLAUDE_PLUGIN_DATA": self.data}

    def env(self, patch=None, fw=None, data=""):
        e = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "GIT_CONFIG_NOSYSTEM": "1",
             "GIT_CONFIG_GLOBAL": "/dev/null", "LC_ALL": "C"}
        if data == "":
            e["CLAUDE_PLUGIN_DATA"] = self.data
        elif data is not None:
            e["CLAUDE_PLUGIN_DATA"] = data
        if patch or fw:
            e["PYTHONPATH"] = self.fx + os.pathsep + FW
        if patch:
            e["HOOKTEST_PATCH"] = json.dumps(patch)
        if fw:
            e["HOOKTEST_FW"] = fw
        return e

    def go(self, event="SessionStart", patch=None, fw=None, data="", fields=None, drop=(), root=None):
        """Run the hook; S20 and U4: exit 0 and empty stderr on every run. Returns ``(stdout lines, process)``."""
        pl = payload(event, root or self.repo, **(fields or {}))
        for k in drop:
            pl.pop(k)
        p = run_hook(event, pl, self.env(patch, fw, data), FW)
        self.assertEqual((p.returncode, p.stderr), (0, ""), p.stdout)
        return out_lines(p), p

    def put(self, rel, data, root=None):
        path = os.path.join(root or self.repo, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data if isinstance(data, bytes) else data.encode("utf-8"))
        return path

    def seed(self, sid="sess-1", n=1):
        with session.locked(self.penv(), sid) as st:
            st["dispatches"] = []
            for i in range(n):
                session.add_dispatch(st, "%064x" % (i + 1), "implementer", 1, "root")

    def live(self, sid="sess-1"):
        with session.locked(self.penv(), sid) as st:
            return session.live_total(st)

    def session_file(self, sid="sess-1"):
        return os.path.join(session.session_dir(self.penv()), sid + ".yml")

    def handoff(self, slug, ps=PS, text=None, **over):
        """Write ``<ps>/<slug>/handoff.md`` (a valid handoff/1 row unless ``text``); returns ``(rel, row)``."""
        head = git(self.repo, "rev-parse", "--short", "HEAD")
        base = git(self.repo, "rev-list", "--max-parents=0", "HEAD")
        plan = "docs/strict-delivery/plans/%s.md" % slug
        row = {"schema": "handoff/1", "plan": plan, "spec": ["docs/strict-delivery/specs/s.md"], "branch": "block/p1",
               "head": head, "base": base, "ledger": "%s/%s/ledger.md" % (ps, slug),
               "resume": resume_text(plan, "P1.2", "block/p1", head), "block": "P1", "next_task": "P1.2",
               "findings_in_flight": [], "open_decisions": [], "rulings": 0, "grant": None, "live_subagents": [],
               "role": "controller", "budget": {"tokens": 300000, "minutes": 150},
               "worktrees": [{"path": ".", "branch": "block/p1", "head": head, "porcelain": ""}],
               "skills": ["strict-delivery"], "ledger_from": 4, "batch_cut": None, "questions": []}
        row.update(over)
        rel = "%s/%s/handoff.md" % (ps, slug)
        self.put(rel, text if text is not None else "---\n" + yamlsub.emit(row) + "---\nbody\n")
        return rel, row

    def program(self, name):
        git(self.repo, "checkout", "-q", "-b", name + "/integration")
        base = ".strict-delivery/state/programs/%s/" % name
        rels = [base + "streams.yml", base + "status.md", base + "sync-log.md", base + "merged.md"]
        self.put(rels[0], "x: 1\n")
        for r in rels[1:]:   # a well-formed program folder (programs design :186): load_program needs all four
            self.put(r, "")
        git(self.repo, "add", *rels)   # only these files: other fixture files stay untracked in the work tree
        git(self.repo, "commit", "-q", "-m", "program " + name)
        git(self.repo, "checkout", "-q", "main")

    def decision(self, row):
        write_record(self.repo, "%s/%s.yml" % (DEC, row["id"]), row)

    def baseline(self, **kw):
        return [header(**kw), "regenerate: PASS", load_line(), SKILL_LINE]


class HeaderTest(Base):
    def test_header_line(self):   # S1
        self.program(P1)
        self.program(P2)
        git(self.repo, "branch", "feature")
        both = P1 + ", " + P2
        cases = [("main", header(programs=both)), ("feature", header(branch="feature", programs=both)),
                 ("detached", header(branch="detached", programs=both))]
        for name, want in cases:
            with self.subTest(branch=name):
                if name == "detached":
                    git(self.repo, "checkout", "-q", "--detach")
                else:
                    git(self.repo, "checkout", "-q", name)
                lines, _p = self.go()
                self.assertEqual(lines[0], want)

    def test_header_programs_none_one_two(self):   # S1: live programs none, one, two
        lines, _ = self.go()
        self.assertEqual(lines[0], header(programs="none"))
        self.program(P1)
        lines, _ = self.go()
        self.assertEqual(lines[0], header(programs=P1))
        self.program(P2)
        lines, _ = self.go()
        self.assertEqual(lines[0], header(programs=P1 + ", " + P2))

    def test_header_failures(self):   # S2
        self.program(P1)
        with self.subTest(r="programs"):
            lines, _ = self.go(patch={"gates.lib.programs.live_programs": ["GateError", "boom"]})
            self.assertEqual(lines, [header(programs="unknown"), "FAIL hook.session-start.programs: boom",
                                     "FAIL hook.session-start.index: boom", load_line(), SKILL_LINE])
        with self.subTest(r="branch"):
            git(self.repo, "symbolic-ref", "HEAD", "refs/tags/zz")
            lines, _ = self.go()
            self.assertEqual(lines, [header(branch="unknown", programs=P1),
                                     "FAIL hook.session-start.branch: git symbolic-ref: HEAD does not name a branch under refs/heads/",
                                     "regenerate: PASS", program_expected(P1), load_line(), SKILL_LINE])


class ProfileBaseTest(Base):
    CFG = {**minimal_config(), "profile": "standard", "base_branch": "develop"}

    def test_header_profile_and_base_from_cfg(self):   # S1: profile and base come from the config
        lines, _ = self.go()
        self.assertEqual(lines, self.baseline(profile="standard", base="develop"))


class ResetTest(Base):
    def test_startup_resets_live_counts(self):   # S3
        self.seed()
        self.go(fields={"source": "startup"})
        self.assertEqual(self.live(), 0)

    def test_fork_resets_live_counts(self):   # S3 (F-B3p-12 (i))
        self.seed()
        self.go(fields={"source": "fork"})
        self.assertEqual(self.live(), 0)

    def test_reset_by_source(self):   # S3, S4 (M4 limit: this reset is the only recovery for an interrupted subagent)
        cases = [("startup", 0), ("resume", 0), ("fork", 0), (None, 0), ("x-unknown", 0), (1, 0), ("", 0),
                 ("clear", 1), ("compact", 1)]
        for source, want in cases:
            with self.subTest(source=source):
                self.seed()
                if source is None:
                    self.go(drop=("source",))
                else:
                    self.go(fields={"source": source})
                self.assertEqual(self.live(), want)

    def test_compact_keeps_live_counts(self):   # S4
        for source in ("compact", "clear"):
            with self.subTest(source=source):
                self.seed()
                lines, _ = self.go(fields={"source": source})
                self.assertEqual(self.live(), 1)
                self.assertEqual(lines, self.baseline())

    def test_second_session_start_other_id(self):   # S3b (M2): never assume one SessionStart per process
        self.seed("sess-a")
        self.seed("sess-b")
        with open(self.session_file("sess-a"), "rb") as fh:
            before = fh.read()
        lines, _ = self.go(fields={"source": "startup", "session_id": "sess-b"})
        self.assertEqual(lines, self.baseline())
        with open(self.session_file("sess-a"), "rb") as fh:
            self.assertEqual(fh.read(), before)
        self.assertEqual((self.live("sess-a"), self.live("sess-b")), (1, 0))
        lines, _ = self.go(fields={"source": "startup", "session_id": "sess-a"})
        self.assertEqual(lines, self.baseline())
        self.assertEqual((self.live("sess-a"), self.live("sess-b")), (0, 0))

    def test_corrupt_state_at_startup_reported_and_recovered(self):   # S5
        self.seed()
        os.makedirs(os.path.dirname(self.session_file()), exist_ok=True)
        with open(self.session_file(), "wb") as fh:
            fh.write(b"garbage: [\n")
        lines, _ = self.go(fields={"source": "startup"})
        path = self.session_file()
        pat = re.compile(r"FAIL hook\.session-start\.session: %s was unreadable and was moved to %s\.corrupt-\d{8}T\d{6}(-\d+)?; "
                         r"live subagent counts restart at zero\Z" % (re.escape(path), re.escape(path)))
        self.assertRegex(lines[0], pat)
        self.assertEqual(lines[1:], self.baseline())
        self.assertEqual(self.live(), 0)
        moved = [n for n in os.listdir(os.path.dirname(path)) if ".corrupt-" in n]
        self.assertEqual(len(moved), 1)
        with open(os.path.join(os.path.dirname(path), moved[0]), "rb") as fh:
            self.assertEqual(fh.read(), b"garbage: [\n")

    def test_corrupt_state_at_compact_kept(self):   # S6
        for source in ("compact", "clear"):
            with self.subTest(source=source):
                path = self.session_file()
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as fh:
                    fh.write(b"garbage: [\n")
                lines, _ = self.go(fields={"source": source})
                self.assertTrue(lines[0].startswith("FAIL hook.session-start.session: the session state file %s is unreadable (" % path), lines[0])
                self.assertTrue(lines[0].endswith("; start a new session (SessionStart moves it aside), or as the human delete it: rm '%s'" % path), lines[0])
                self.assertEqual(lines[1:], self.baseline())
                with open(path, "rb") as fh:
                    self.assertEqual(fh.read(), b"garbage: [\n")
                self.assertEqual([n for n in os.listdir(os.path.dirname(path)) if ".corrupt-" in n], [])
                os.unlink(path)

    def test_store_unavailable_named(self):   # S7
        for data, reason in ((None, "CLAUDE_PLUGIN_DATA is not set"),
                             ("rel/data", "CLAUDE_PLUGIN_DATA must be an absolute path: 'rel/data'")):
            for source in ("startup", "compact"):
                with self.subTest(data=data, source=source):
                    lines, _ = self.go(data=data, fields={"source": source})
                    self.assertEqual(lines, ["FAIL hook.session-start.session: " + reason] + self.baseline())


class IndexTest(Base):
    def test_regenerates_in_force(self):   # S8
        lines, _ = self.go()
        self.assertEqual(lines[1], "regenerate: PASS")
        self.assertTrue(os.path.isfile(os.path.join(self.repo, *IN_FORCE.split("/"))))

    def test_regenerate_failure(self):   # S8: any Exception
        for kind, msg, want in (("GateError", "boom", "boom"), ("OSError", "disk", "OSError: disk"),
                                ("ValueError", "bad", "ValueError: bad")):
            with self.subTest(kind=kind):
                lines, _ = self.go(patch={"gates.tools.index.regenerate": [kind, msg]})
                self.assertEqual(lines, [header(), "FAIL hook.session-start.index: " + want, load_line(), SKILL_LINE])


class HandoffTest(Base):
    def test_handoff_lines(self):   # S9
        with self.subTest(n="none"):
            lines, _ = self.go()
            self.assertEqual(lines, self.baseline())
        with self.subTest(n="one"):
            rel, row = self.handoff("2026-10-31-x")
            lines, _ = self.go()
            self.assertEqual(lines, [header(), "regenerate: PASS", "handoff %s: %s" % (rel, row["resume"]),
                                     resume_expected(rel, "strict-delivery", 0, 4), load_line(), SKILL_LINE])
        with self.subTest(n="two sorted by path"):
            rel2, row2 = self.handoff("2026-10-30-a")
            lines, _ = self.go()
            self.assertEqual(lines, [header(), "regenerate: PASS", "handoff %s: %s" % (rel2, row2["resume"]),
                                     "handoff %s: %s" % (rel, row["resume"]),
                                     resume_expected(rel2, "strict-delivery", 0, 4), resume_expected(rel, "strict-delivery", 0, 4),
                                     load_line(), SKILL_LINE])

    def test_handoff_lines_changed_plan_state(self):   # S9: paths.plan_state changed in the config
        cfg = {**minimal_config(), "paths": {"plan_state": "ps2"}}
        write_record(self.repo, ".strict-delivery/config.yml", cfg)
        rel, row = self.handoff("2026-10-31-x", ps="ps2")
        lines, _ = self.go()
        self.assertEqual(lines, [header(), "regenerate: PASS", "handoff ps2/2026-10-31-x/handoff.md: " + row["resume"],
                                 resume_expected(rel, "strict-delivery", 0, 4), load_line(), SKILL_LINE])
        self.assertEqual(rel, "ps2/2026-10-31-x/handoff.md")

    def test_handoff_stray_entries_ignored(self):   # S9: a file or a directory without handoff.md is not a handoff
        self.put(PS + "/stray.txt", "x")
        os.makedirs(os.path.join(self.repo, *(PS + "/2026-10-31-empty").split("/")))
        lines, _ = self.go()
        self.assertEqual(lines, self.baseline())

    def test_malformed_handoff(self):   # S10
        slug = "2026-10-31-x"
        rel = "%s/%s/handoff.md" % (PS, slug)
        good_rel, good_row = self.handoff(slug)
        good = open(os.path.join(self.repo, *rel.split("/")), "rb").read()
        d = os.path.join(self.repo, *(PS + "/" + slug).split("/"))
        other = os.path.join(self.tmp, "other-handoff.md")
        with open(other, "wb") as fh:
            fh.write(good)

        def mk_text(drop=(), **over):
            row = dict(good_row)
            row.update(over)
            for k in drop:
                del row[k]
            return ("---\n" + yamlsub.emit(row) + "---\nbody\n").encode("utf-8")

        def replace_with(kind):
            p = os.path.join(d, "handoff.md")
            if os.path.isdir(p) and not os.path.islink(p):
                os.rmdir(p)
            elif os.path.lexists(p):
                os.unlink(p)
            if kind == "dir":
                os.mkdir(p)
            elif kind == "symlink":
                os.symlink(other, p)
            elif kind == "fifo":
                os.mkfifo(p)
            else:
                with open(p, "wb") as fh:
                    fh.write(kind)

        # Task 5b.1 index.render raises GateError naming the file for a handoff that does not load (plan :5352;
        # table rows PL29, RN11), so the structural cases give the index FAIL line, not "regenerate: PASS" (plan :3476).
        ixf = "FAIL hook.session-start.index: " + rel + ": "
        notreg = ixf + "cannot be read as a UTF-8 regular file (not a regular file)"
        ok = "regenerate: PASS"
        values = [("no front matter", b"just text\n", ixf + "front matter: first line must be '---'"),
                  ("yaml error", b"---\na: [\n---\nbody\n", ixf + "front matter: line 2: unterminated flow sequence"),
                  ("schema: skills missing", mk_text(drop=("skills",)), ok),
                  ("schema: empty skills (S12 empty list)", mk_text(skills=[]), ok),
                  ("schema: bad head", mk_text(head="zz"), ok),
                  ("rule: resume mismatch", mk_text(resume="Resume wrong."), ok),
                  ("not utf-8", b"\xff\xfe\n", ixf + "cannot be read as a UTF-8 regular file (not valid UTF-8)"),
                  ("directory", "dir", notreg), ("symlink", "symlink", notreg), ("fifo", "fifo", notreg)]
        for name, value, second in values:
            with self.subTest(case=name):
                replace_with(value)
                lines, _ = self.go()
                self.assertEqual(len(lines), 5, lines)
                self.assertEqual(lines[:2], [header(), second])
                self.assertTrue(lines[2].startswith("FAIL hook.session-start.handoff.%s: " % rel), lines[2])
                self.assertEqual(lines[3:], [load_line(), SKILL_LINE])

    def test_malformed_beside_good_handoff(self):   # S10: a malformed one never costs the good one its lines
        good_rel, good_row = self.handoff("2026-10-31-b")
        self.handoff("2026-10-31-a", text="just text\n")
        lines, _ = self.go()
        self.assertEqual(len(lines), 7, lines)
        self.assertTrue(lines[2].startswith("FAIL hook.session-start.handoff.%s/2026-10-31-a/handoff.md: " % PS), lines[2])
        self.assertEqual(lines[3:], ["handoff %s: %s" % (good_rel, good_row["resume"]),
                                     resume_expected(good_rel, "strict-delivery", 0, 4), load_line(), SKILL_LINE])

    def test_resume_line_by_source(self):   # S11: every source gets the line
        rel, row = self.handoff("2026-10-31-x")
        for source in SOURCES:
            with self.subTest(source=source):
                if source is None:
                    lines, _ = self.go(drop=("source",))
                else:
                    lines, _ = self.go(fields={"source": source})
                self.assertEqual(lines, [header(), "regenerate: PASS", "handoff %s: %s" % (rel, row["resume"]),
                                         resume_expected(rel, "strict-delivery", 0, 4), load_line(), SKILL_LINE])

    def test_resume_line_names_skills_reads_and_ledger_from(self):   # S12
        reads = [{"path": "a.md", "why": "w"}, {"path": "b.md", "lines": "1-5", "why": "w"}, {"path": "c.md", "why": "w"}]
        cases = [(["strict-delivery", "strict-delivery-repo"], None, 41, "strict-delivery, strict-delivery-repo", 0),
                 (["strict-delivery"], [], 2, "strict-delivery", 0),
                 (["a"], reads, 7, "a", 3)]
        for skills, rr, lf, text, n in cases:
            with self.subTest(skills=skills, reads=n, ledger_from=lf):
                over = {"skills": skills, "ledger_from": lf}
                if rr is not None:
                    over["required_reads"] = rr
                rel, row = self.handoff("2026-10-31-x", **over)
                lines, _ = self.go()
                self.assertEqual(lines[3], resume_expected(rel, text, n, lf))

    def test_program_resume_line(self):   # S13
        rel, row = self.handoff("2026-10-31-x")
        lines, _ = self.go()
        self.assertFalse([l for l in lines if l.startswith("resume program")])
        self.program(P1)
        lines, _ = self.go()
        self.assertEqual(lines, [header(programs=P1), "regenerate: PASS", "handoff %s: %s" % (rel, row["resume"]),
                                 resume_expected(rel, "strict-delivery", 0, 4), program_expected(P1), load_line(), SKILL_LINE])
        self.program(P2)
        lines, _ = self.go(fields={"source": "compact"})
        self.assertEqual(lines[3:6], [resume_expected(rel, "strict-delivery", 0, 4), program_expected(P1), program_expected(P2)])


class DecisionTest(Base):
    def test_open_decision_lines(self):   # S14
        with self.subTest(n="none"):
            self.assertEqual(self.go()[0], self.baseline())
        self.decision(dec(D2, "open", question="Second?\nmore"))
        self.decision(dec(D1, "open", question="First?"))
        self.decision(dec(D3, "answered"))
        with self.subTest(n="open sorted, answered skipped"):
            lines, _ = self.go()
            self.assertEqual(lines, [header(), "regenerate: PASS", "open decision %s: First?" % D1,
                                     "open decision %s: Second?" % D2, load_line(), SKILL_LINE])

    def test_open_decision_store_failing(self):   # S14: the decision store fails to load
        self.put(DEC + "/junk.txt", "x")
        why = "%s/junk.txt: not a regular file named <id>.yml (only index.yml and in-force.md are allowed besides records)" % DEC
        lines, _ = self.go()
        self.assertEqual(lines, [header(), "FAIL hook.session-start.index: " + why,
                                 "FAIL hook.session-start.decisions: " + why, load_line(), SKILL_LINE])

    def test_lists_active_overrides_only(self):   # S15
        ov = {"class": "rule-override"}
        self.decision(lasting(D1, **ov, overrides="SD-R7"))                                  # active
        self.decision(lasting(D2, **ov, overrides="SD-R8"))                                  # superseded by D4
        self.decision(dec(D3, "withdrawn", **ov, overrides="SD-R9"))                         # withdrawn
        self.decision(lasting(D5, **ov))                                                     # no overrides field
        self.decision(dec(D6, "open", **ov, overrides="SD-R10"))                             # open
        self.decision(dec(D4, "answered", supersedes=D2))                                    # the superseder
        self.decision(dec(D7, "answered", **ov, overrides="SD-R11", question="Waive R11?\nbecause"))   # one-off: no rule
        lines, _ = self.go()
        self.assertEqual([l for l in lines if l.startswith("override ")],
                         ["override SD-R7 by %s: rule text" % D1, "override SD-R11 by %s: Waive R11?" % D7])

    def test_load_line(self):   # S16
        self.assertEqual(self.go()[0][-2], load_line())
        write_record(self.repo, ".strict-delivery/config.yml", {**minimal_config(), "paths": {"decisions": "dec"}})
        lines, _ = self.go()
        self.assertEqual(lines[-2], "load: dec/in-force.md and the open decisions above")

    def test_session_start_lines_escaped(self):   # S19, V2
        q = "a\x07b\U0001fae0cⰯ\rd\nsecond"
        self.decision(dec(D1, "open", question=q))
        lines, p = self.go()
        self.assertEqual(lines[2], "open decision %s: a\\x07b\\U0001fae0c\\u2c2f\\rd" % D1)
        self.assertEqual(len(lines), 5)
        self.assertEqual(p.stdout.count("\n"), 5)


class SkillTest(Base):
    def fw(self, content):
        d = os.path.join(self.tmp, "fw")
        os.makedirs(os.path.join(d, "skills", "strict-delivery"), exist_ok=True)
        if content is not None:
            with open(os.path.join(d, *SKILL_REL.split("/")), "wb") as fh:
                fh.write(content)
        return d

    def test_names_the_skill(self):   # S17: the real SKILL.md, then a fixture with another name
        self.assertEqual(self.go()[0][-1], SKILL_LINE)
        lines, _ = self.go(fw=self.fw(b"---\nname: other-skill1\ndescription: x\n---\n"))
        self.assertEqual(lines[-1], "Invoke the other-skill1 skill before any change.")

    def test_skill_line_malformed(self):   # S17
        cases = [("absent", None, "%s is missing" % SKILL_REL),
                 ("line 2 not name", b"---\ntitle: x\n", "line 2 of %s does not start with 'name: '" % SKILL_REL),
                 ("empty name", b"---\nname: \n", "the skill name in %s is empty" % SKILL_REL),
                 ("space in name", b"---\nname: a b\n", "the skill name 'a b' in %s does not match [a-z0-9][a-z0-9-]*" % SKILL_REL),
                 ("upper case", b"---\nname: Abc\n", "the skill name 'Abc' in %s does not match [a-z0-9][a-z0-9-]*" % SKILL_REL),
                 ("leading dash", b"---\nname: -a\n", "the skill name '-a' in %s does not match [a-z0-9][a-z0-9-]*" % SKILL_REL),
                 ("not utf-8", b"---\nname: \xff\n", "%s is not valid UTF-8" % SKILL_REL),
                 ("one line only", b"---", "%s has no line 2" % SKILL_REL)]
        for name, content, why in cases:
            with self.subTest(case=name):
                lines, _ = self.go(fw=self.fw(content) if content is not None else self.fw(None))
                self.assertEqual(lines, [header(), "regenerate: PASS", load_line(), "FAIL hook.session-start.skill: " + why])
                os.path.exists(os.path.join(self.tmp, "fw", *SKILL_REL.split("/"))) and os.unlink(os.path.join(self.tmp, "fw", *SKILL_REL.split("/")))

    def test_skill_is_a_directory(self):   # S17: a directory (or other non-regular file) is never opened
        d = self.fw(None)
        os.makedirs(os.path.join(d, *SKILL_REL.split("/")))
        lines, _ = self.go(fw=d)
        self.assertEqual(lines[-1], "FAIL hook.session-start.skill: %s is not a regular file" % SKILL_REL)


class ConfigErrorTest(Base):
    def broken(self):
        self.put(".strict-delivery/config.yml", "profile: [\n")

    def test_config_error_named(self):   # S18
        self.broken()
        lines, _ = self.go()
        self.assertEqual(len(lines), 2, lines)
        self.assertTrue(lines[0].startswith("FAIL hook.session-start.config: "), lines[0])
        self.assertTrue(lines[0].endswith(DOCTOR), lines[0])
        self.assertEqual(lines[1], SKILL_LINE)

    def test_config_error_with_reset_fail_first(self):   # S18: reset needs no config; its FAIL line comes first
        self.broken()
        lines, _ = self.go(data=None)
        self.assertEqual(len(lines), 3, lines)
        self.assertEqual(lines[0], "FAIL hook.session-start.session: CLAUDE_PLUGIN_DATA is not set")
        self.assertTrue(lines[1].startswith("FAIL hook.session-start.config: "), lines[1])
        self.assertEqual(lines[2], SKILL_LINE)

    def test_config_error_still_resets(self):   # S18, S3
        self.broken()
        self.seed()
        self.go()
        self.assertEqual(self.live(), 0)


class ExitTest(Base):
    def test_refuses_nothing(self):   # S20: exit 0 and empty stderr in every degraded situation (go() checks both)
        os.makedirs(os.path.dirname(self.session_file()), exist_ok=True)
        with open(self.session_file(), "wb") as fh:
            fh.write(b"garbage: [\n")
        self.handoff("2026-10-31-x", text="just text\n")
        self.put(DEC + "/junk.txt", "x")
        for source in SOURCES:
            with self.subTest(source=source):
                self.go(fields={"source": source} if source is not None else {}, drop=() if source is not None else ("source",))
        with self.subTest(case="no data dir"):
            self.go(data=None)
        with self.subTest(case="outside a repository"):
            outside = os.path.join(self.tmp, "outside")
            os.makedirs(outside)
            lines, p = self.go(root=outside)
            self.assertEqual((lines, p.stdout), ([], ""))


class PromptSubmitTest(Base):
    def cfg(self, profile):
        write_record(self.repo, ".strict-delivery/config.yml", {**minimal_config(), "profile": profile})

    def test_prompt_submit_by_profile(self):   # U1, U4
        for profile in ("light", "standard", "strict"):
            with self.subTest(profile=profile):
                self.cfg(profile)
                lines, p = self.go("UserPromptSubmit")
                if profile == "light":
                    self.assertEqual(p.stdout, "")
                else:
                    self.assertEqual(lines, ["strict-delivery (%s): follow the strict-delivery skill; decisions are asked, never assumed" % profile])

    def test_prompt_submit_writes_no_session_state(self):   # UserPromptSubmit touches no state
        self.go("UserPromptSubmit")
        self.assertEqual(os.listdir(self.data), [])

    def test_prompt_submit_config_error(self):   # U2
        self.put(".strict-delivery/config.yml", "profile: [\n")
        lines, _ = self.go("UserPromptSubmit")
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].startswith("FAIL hook.prompt-submit.config: "), lines[0])
        self.assertTrue(lines[0].endswith(DOCTOR), lines[0])

    def test_prompt_submit_skill_missing(self):   # U3
        d = os.path.join(self.tmp, "fw")
        os.makedirs(os.path.join(d, "skills", "strict-delivery"))
        cases = [("absent", None, "%s is missing" % SKILL_REL), ("not name", b"---\ntitle: x\n", "line 2 of %s does not start with 'name: '" % SKILL_REL),
                 ("empty", b"---\nname: \n", "the skill name in %s is empty" % SKILL_REL),
                 ("space", b"---\nname: a b\n", "the skill name 'a b' in %s does not match [a-z0-9][a-z0-9-]*" % SKILL_REL),
                 ("not utf-8", b"---\nname: \xff\n", "%s is not valid UTF-8" % SKILL_REL), ("one line", b"---", "%s has no line 2" % SKILL_REL)]
        self.cfg("standard")
        for name, content, why in cases:
            with self.subTest(case=name):
                path = os.path.join(d, *SKILL_REL.split("/"))
                if os.path.exists(path):
                    os.unlink(path)
                if content is not None:
                    with open(path, "wb") as fh:
                        fh.write(content)
                lines, _ = self.go("UserPromptSubmit", fw=d)
                self.assertEqual(lines, ["FAIL hook.prompt-submit.skill: " + why])

    def test_prompt_submit_light_ignores_skill(self):   # U1: light prints nothing even when the skill file is missing
        self.cfg("light")
        d = os.path.join(self.tmp, "fw")
        os.makedirs(os.path.join(d, "skills", "strict-delivery"))
        lines, p = self.go("UserPromptSubmit", fw=d)
        self.assertEqual(p.stdout, "")

    def test_prompt_submit_unicode_name_line(self):   # V2: the prompt line is the same on both interpreters (hand-written)
        self.cfg("strict")
        lines, _ = self.go("UserPromptSubmit")
        self.assertEqual(lines[0].encode("utf-8"), b"strict-delivery (strict): follow the strict-delivery skill; decisions are asked, never assumed")


if __name__ == "__main__":
    unittest.main()
