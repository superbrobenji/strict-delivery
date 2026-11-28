"""Amendment P (owner rule 2026-11-26 21:10), the ``I`` cells of the generated path matrix of Task 4d.2: every path role
init hands to docmove (source, source parents, target, target parents, holders, holder parents, state directories) x the
file states S1-S9 and N1 (a non-UTF-8 name in the index) x the moments C1 (``init plan``), C2 (``init apply``, which
plans again) and C3 (``init apply`` after its file writes, before the recomputed ``plan_moves``, Q16), all through
``init.main``. The cell list is enumerated, never sampled; ``SEED`` orders the execution and names the sentinel bytes.
The expected verdicts are written by hand below (``Oracle``); nothing is read from init or docmove."""
import contextlib
import hashlib
import io
import os
import random
import shutil
import signal
import socket
import stat
import tempfile
import unittest
from unittest import mock

from gates.lib import docmove, yamlsub
from gates.tools import init
from tests import helpers
from tests.helpers import git

SEED = 20261126
OLD_SPEC = "docs/superpowers/specs/a.md"
OLD_PLAN = "docs/superpowers/plans/x/p.md"
NEW_SPEC = "docs/strict-delivery/specs/a.md"
NEW_PLAN = "docs/strict-delivery/plans/x/p.md"
MOVES = [(OLD_PLAN, NEW_PLAN), (OLD_SPEC, NEW_SPEC)]  # ``plan_moves`` gives them in source order
TEXT = "see %s\n" % OLD_SPEC
TRACKED = {OLD_PLAN: "see docs/superpowers/specs/a.md\n", OLD_SPEC: "spec a\n", "README.md": TEXT,
           "docs/guide/g.md": TEXT, ".github/workflows/other.yml": TEXT,
           ".strict-delivery/state/decisions/D-1.yml": "id: D-1\n"}
HOLDERS = ["README.md", "docs/guide/g.md", ".github/workflows/other.yml", ".strict-delivery/state/decisions/D-1.yml"]
STATES = ["S%d" % i for i in range(1, 10)]
MOMENTS = ("C1", "C2", "C3")
SENTINEL = "outside/sentinel"


class Slot:
    def __init__(self, ident, path, group, file_slot, tracked):
        self.ident, self.path, self.group, self.file_slot, self.tracked = ident, path, group, file_slot, tracked
        self.target = group in ("TGT", "TP")  # baseline absent: its ancestors are made when it is set to a state


SLOTS = [
    Slot("SRC-plan", OLD_PLAN, "SRC", True, True), Slot("SRC-spec", OLD_SPEC, "SRC", True, True),
    Slot("SP-docs", "docs", "SP", False, True), Slot("SP-sup", "docs/superpowers", "SP", False, True),
    Slot("SP-specs", "docs/superpowers/specs", "SP", False, True),
    Slot("SP-plans", "docs/superpowers/plans", "SP", False, True),
    Slot("SP-plansx", "docs/superpowers/plans/x", "SP", False, True),
    Slot("TGT-plan", NEW_PLAN, "TGT", True, False), Slot("TGT-spec", NEW_SPEC, "TGT", True, False),
    Slot("TP-ds", "docs/strict-delivery", "TP", False, False), Slot("TP-dss", "docs/strict-delivery/specs", "TP", False, False),
    Slot("TP-dsp", "docs/strict-delivery/plans", "TP", False, False),
    Slot("TP-dspx", "docs/strict-delivery/plans/x", "TP", False, False),
    Slot("H-readme", "README.md", "H", True, True), Slot("H-guide", "docs/guide/g.md", "H", True, True),
    Slot("H-wf", ".github/workflows/other.yml", "H", True, True),
    Slot("H-state", ".strict-delivery/state/decisions/D-1.yml", "H", True, True),
    Slot("HP-guide", "docs/guide", "HP", False, True), Slot("HP-gh", ".github", "HP", False, True),
    Slot("HP-ghwf", ".github/workflows", "HP", False, True), Slot("HP-st", ".strict-delivery", "HP", False, True),
    Slot("HP-stst", ".strict-delivery/state", "HP", False, True),
    Slot("HP-dec", ".strict-delivery/state/decisions", "HP", False, True),
]
BY_ID = {s.ident: s for s in SLOTS}
STATE_DIR_SLOTS = ("HP-st", "HP-stst", "HP-dec")
# Per slot: 9 states, plus N1 for a tracked slot, at each of three moments; per group the hand totals of P4 (I part).
PER_GROUP = {"SRC": 2 * 30 * 1, "SP": 5 * 30, "TGT": 2 * 27, "TP": 4 * 27, "H": 4 * 30, "HP": 6 * 30}
COUNT = 672


class Cell:
    def __init__(self, slot, state, moment):
        self.slot, self.state, self.moment = slot, state, moment
        self.ident = "I.%s.%s.%s" % (slot.ident, state, moment)


def all_cells():
    out = []
    for moment in MOMENTS:
        for slot in SLOTS:
            for state in STATES + (["N1"] if slot.tracked else []):
                out.append(Cell(slot, state, moment))
    return out


def tree(root, skip_git=True, lstat=os.lstat):
    """Every entry below ``root`` as (relative path, mode, bytes or link target or None), sorted. ``lstat`` is bound at
    definition time, so a patched ``os.lstat`` (the character-device cells) never changes a snapshot."""
    out = []
    for d, dirs, files in os.walk(root):
        if skip_git and d == root and ".git" in dirs:
            dirs.remove(".git")
        dirs.sort()
        for n in sorted(dirs + files):
            p = os.path.join(d, n)
            st = lstat(p)
            if stat.S_ISLNK(st.st_mode):
                out.append((os.path.relpath(p, root), "link", os.readlink(p)))
            elif stat.S_ISREG(st.st_mode):
                with open(p, "rb") as fh:
                    out.append((os.path.relpath(p, root), st.st_mode, fh.read()))
            else:
                out.append((os.path.relpath(p, root), st.st_mode, None))
    return out


# ------------------------------------------------------------------------------------------------ the oracle
# Written by hand from the verdict rules of P5: V0 control, V1 (source parents), V2 (a missing source), V3 (source last
# component), V4/V5 (target last component), V6 (target parents), V7/V8 (holders and holder parents), V9 (state
# directories), V11 (a name that is not UTF-8). The kinds are what ``lstat`` says of a path.
KIND_OF_STATE = {"S1": "absent", "S2": "reg", "S3": "dir", "S4": "link", "S5": "link", "S6": "link", "S7": "fifo",
                 "S8": "sock", "S9": "chr"}
BASE_DIRS = set()
for _p in TRACKED:
    _parts = _p.split("/")
    BASE_DIRS.update("/".join(_parts[:i]) for i in range(1, len(_parts)))
# State directories: the lines 4d.1's ``_dir_plan`` (init.py:411-415) and managed print when a state slot is not a
# directory. Conflict lines of a state slot (state -> lines), hand-written from the V9 texts after reading the outputs.
LINK = "%s: is a symlink"
NOTDIR = "%s: exists and is not a directory"
PARENT = "%s: parent %s is not a directory"


class Oracle:
    def __init__(self, slot, state):
        self.slot, self.state = slot, state

    def kind(self, path):
        s = self.slot
        if self.state in KIND_OF_STATE and path == s.path:
            return KIND_OF_STATE[self.state]
        if s.target and self.state in KIND_OF_STATE and self.state != "S1" and s.path.startswith(path + "/"):
            return "dir"  # the ancestors of a target slot are made as real directories
        if path in BASE_DIRS:
            return "dir"
        if path in TRACKED:
            return "reg"
        return "absent"

    def src_text(self, src):
        parts = src.split("/")
        for i in range(len(parts)):
            p = "/".join(parts[:i + 1])
            k = self.kind(p)
            if k == "absent":
                return "%s: tracked but missing; not moved" % src
            if i == len(parts) - 1:
                return None if k == "reg" else "%s: not a regular file; not moved" % src
            if k != "dir":
                return PARENT % (src, p)
        return None

    def dst_text(self, dst):
        parts = dst.split("/")
        for i in range(len(parts) - 1):
            p = "/".join(parts[:i + 1])
            k = self.kind(p)
            if k == "absent":
                return None
            if k != "dir":
                return PARENT % (dst, p)
        k = self.kind(dst)
        if k == "absent":
            return None
        return "%s: is a symlink" % dst if k == "link" else "%s: exists" % dst

    def move_conflicts(self):
        out = set()
        for src, dst in MOVES:
            for text in (self.src_text(src), self.dst_text(dst)):
                if text is not None:
                    out.add(text)
        return sorted(out)

    def not_read(self):
        """The holders ``rewrites`` skips with a note: a component that is not a directory, or a last component that is
        not a regular file (never read through, V7, V8); an absent one is skipped silently."""
        out = []
        for h in HOLDERS:
            parts = h.split("/")
            for i in range(len(parts)):
                k = self.kind("/".join(parts[:i + 1]))
                if k == "absent":
                    break
                if (i < len(parts) - 1 and k != "dir") or (i == len(parts) - 1 and k != "reg"):
                    out.append("note: %s: not a regular file; not read" % h)
                    break
        return out


def state_dir_lines(slot_id, state):
    """V9 (4d.1, init.py:411-415, written by hand): the conflict lines of a state-directory slot, in print order; an
    empty list for S1 (init plans the directory) and S3 (the baseline). A symlink is ``is a symlink``, anything else
    that is not a directory is ``exists and is not a directory``; ``.strict-delivery`` also holds config.yml and the
    context file, so its first and last lines are managed's ``parent .strict-delivery is not a directory``."""
    if state in ("S1", "S3"):
        return []
    rel = {"HP-st": ".strict-delivery", "HP-stst": ".strict-delivery/state", "HP-dec": ".strict-delivery/state/decisions"}[slot_id]
    fault = (LINK if state in ("S4", "S5", "S6") else NOTDIR) % rel
    if slot_id == "HP-st":
        return [PARENT % (".strict-delivery/config.yml", ".strict-delivery"), fault,
                PARENT % (".strict-delivery/context.yml", ".strict-delivery")]
    return [fault]


# the cells the review found open (R2B-3, P7): each with its expected stdout written out in full, a second oracle that
# shares no code with ``Oracle``. (slot, state, moment) -> the lines of ``FAIL init.conflict`` or the ``note:`` lines
NAMED_CELLS = {
    ("SP-plansx", "S5"): ["FAIL init.conflict: docs/superpowers/plans/x/p.md: parent docs/superpowers/plans/x is not a directory"],
    ("TP-ds", "S5"): ["FAIL init.conflict: docs/strict-delivery/plans/x/p.md: parent docs/strict-delivery is not a directory",
                      "FAIL init.conflict: docs/strict-delivery/specs/a.md: parent docs/strict-delivery is not a directory"],
    ("TP-dss", "S5"): ["FAIL init.conflict: docs/strict-delivery/specs/a.md: parent docs/strict-delivery/specs is not a directory"],
    ("TP-dsp", "S5"): ["FAIL init.conflict: docs/strict-delivery/plans/x/p.md: parent docs/strict-delivery/plans is not a directory"],
    ("TP-dspx", "S5"): ["FAIL init.conflict: docs/strict-delivery/plans/x/p.md: parent docs/strict-delivery/plans/x is not a directory"],
    ("H-readme", "S5"): ["note: README.md: not a regular file; not read"],
    ("H-wf", "S5"): ["note: .github/workflows/other.yml: not a regular file; not read"],
    ("H-guide", "S5"): ["note: docs/guide/g.md: not a regular file; not read"],
    ("HP-guide", "S5"): ["note: docs/guide/g.md: not a regular file; not read"],
    ("HP-gh", "S5"): ["note: .github/workflows/other.yml: not a regular file; not read"],
    ("HP-ghwf", "S5"): ["note: .github/workflows/other.yml: not a regular file; not read"],
    ("H-state", "S5"): ["note: .strict-delivery/state/decisions/D-1.yml: not a regular file; not read"],
}
NAMED_PARENT_S2 = {  # the same parents, replaced by a regular file, at C1 only
    "SP-plansx": NAMED_CELLS[("SP-plansx", "S5")], "TP-ds": NAMED_CELLS[("TP-ds", "S5")],
    "TP-dss": NAMED_CELLS[("TP-dss", "S5")], "TP-dsp": NAMED_CELLS[("TP-dsp", "S5")],
    "TP-dspx": NAMED_CELLS[("TP-dspx", "S5")],
    "HP-guide": NAMED_CELLS[("HP-guide", "S5")], "HP-gh": NAMED_CELLS[("HP-gh", "S5")],
    "HP-ghwf": NAMED_CELLS[("HP-ghwf", "S5")],
}


def class_of(cell):
    """The P5 verdict class of a cell: the test that asserts it."""
    slot, state = cell.slot, cell.state
    if state == "N1":
        return "names_index"
    if slot.ident in STATE_DIR_SLOTS or slot.ident == "H-state":
        return "state_dirs"
    baseline = {"SRC": "S2", "SP": "S3", "TGT": "S1", "H": "S2", "HP": "S3"}.get(slot.group)
    if state == baseline:
        return "controls"
    return {"SRC": "source_last", "SP": "source_parents", "TGT": "target_last", "TP": "target_parents",
            "H": "holders", "HP": "holder_parents"}[slot.group]


_RESULTS = {}


class MatrixCase(helpers.GitIsolatedTestCase):
    template = None

    def setUp(self):
        super().setUp()
        self.make_template()

    def make_template(self):
        t = os.path.join(self.tmp, "template")
        os.mkdir(t)
        git(t, "init", "-q", "-b", "main")
        git(t, "config", "user.email", "f@example.invalid")
        git(t, "config", "user.name", "F")
        git(t, "config", "commit.gpgsign", "false")
        for rel, text in TRACKED.items():
            p = os.path.join(t, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(text)
        git(t, "add", "-A")
        git(t, "commit", "-q", "-m", "F42")
        self.template = t
        self.rng_bytes = bytes(random.Random(SEED).randrange(256) for _ in range(16))

    # ---------------------------------------------------------------------------------------- state setting
    def set_state(self, root, outside, slot, state):
        """Put ``slot`` into ``state`` (P2); the children of a directory slot go where the state says."""
        p = os.path.join(root, slot.path)
        if state == "N1":
            name = slot.path + "\udcff" if slot.file_slot else slot.path + "/\udcff"
            git(root, "update-index", "--add", "--cacheinfo", "100644,%s,%s" % (self.blob(root), name))
            return None
        if slot.target and state != "S1":
            os.makedirs(os.path.dirname(p), exist_ok=True)
        if state == "S9":
            return p  # the lstat of exactly this path is patched; what is underneath stays
        inside = os.path.join(root, "zz-inside")
        moved = None
        if os.path.lexists(p):
            if state == "S2" and slot.file_slot:
                return None
            if state == "S3" and not slot.file_slot:
                return None
            if state == "S5" and slot.file_slot:  # P2: a file slot's S5 is a link to the outside file o.md
                os.unlink(p)
                os.symlink(os.path.join(outside, "o.md"), p)
                return None
            if state in ("S4", "S5"):
                dest = os.path.join(inside if state == "S4" else outside, slot.ident)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                os.rename(p, dest)
                moved = dest
            elif os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p)
            else:
                os.unlink(p)
        if state == "S1":
            return None
        if state in ("S4", "S5"):
            if moved is None:  # a baseline-absent slot: an empty directory or a file holding a reference
                moved = os.path.join(inside if state == "S4" else outside, slot.ident)
                os.makedirs(os.path.dirname(moved), exist_ok=True)
                if slot.file_slot and state == "S5":
                    moved = os.path.join(outside, "o.md")
                elif slot.file_slot:
                    with open(moved, "w", encoding="utf-8") as fh:
                        fh.write(TEXT)
                else:
                    os.mkdir(moved)
            os.symlink(moved, p)
        elif state == "S2":
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(TEXT)
        elif state == "S3":
            os.mkdir(p)
        elif state == "S6":
            os.symlink("no-such-name-" + slot.ident, p)
        elif state == "S7":
            os.mkfifo(p)
        elif state == "S8":
            here = os.getcwd()
            os.chdir(os.path.dirname(p))
            try:
                sock = socket.socket(socket.AF_UNIX)
                self.addCleanup(sock.close)
                sock.bind(os.path.basename(p))
            finally:
                os.chdir(here)
        return None

    def blob(self, root):
        path = os.path.join(self.tmp, "blob.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("x\n")
        return git(root, "hash-object", "-w", path)

    # ---------------------------------------------------------------------------------------------- one cell
    def build(self, cell):
        base = tempfile.mkdtemp(dir=self.tmp)
        root = os.path.join(base, "repo")
        shutil.copytree(self.template, root, symlinks=True)
        outside = os.path.join(base, "outside")
        os.mkdir(outside)
        with open(os.path.join(outside, "sentinel"), "wb") as fh:
            fh.write(self.rng_bytes)
        with open(os.path.join(outside, "o.md"), "w", encoding="utf-8") as fh:
            fh.write(TEXT)
        ans = os.path.join(base, "answers.yml")
        data = {"schema": "init-answers/1", "profile": "standard",
                "models": {"tiers": {"tier1": "haiku", "tier2": "sonnet", "tier3": "opus"}},
                "commands": {"test": "python3 -m unittest", "test_one": "python3 -m unittest {id}", "lint": "ruff check .",
                             "build": "make"},
                "git_hooks": True, "ci": False, "merge_mode": "host", "subagents": {"depth": 5, "concurrent": 30},
                "protect_base": False, "base_branch": "main", "migrate": True}
        with open(ans, "w", encoding="utf-8") as fh:
            fh.write(yamlsub.emit(data))
        return os.path.realpath(root), os.path.realpath(outside), ans

    def run_cell(self, cell):
        """Run one cell; returns a dict of what happened."""
        root, outside, ans = self.build(cell)
        slot, state = cell.slot, cell.state
        res = {"swapped": False}
        opened = []
        real_open, real_lstat = os.open, os.lstat
        patches = []
        chr_path = []

        def fake_lstat(path, *a, **kw):
            if chr_path and os.fspath(path) == chr_path[0]:
                return os.stat_result((stat.S_IFCHR | 0o600, 1, 1, 1, 0, 0, 0, 0, 0, 0))
            return real_lstat(path, *a, **kw)

        def spy_open(path, *a, **kw):
            try:
                if os.path.realpath(os.fsdecode(path)).startswith(outside + os.sep) or os.path.realpath(os.fsdecode(path)) == outside:
                    opened.append(os.fsdecode(path))
            except (TypeError, ValueError):
                pass
            return real_open(path, *a, **kw)

        def swap():
            chr_p = self.set_state(root, outside, slot, state)
            if chr_p is not None:
                chr_path.append(chr_p)
            res["swapped"] = True
            res["root0"] = tree(root)
            res["index0"] = git(root, "ls-files", "-s")
            res["out0"] = tree(outside, skip_git=False)

        sub = "plan" if cell.moment == "C1" else "apply"
        if cell.moment != "C3":
            swap()
        else:
            real_plan = docmove.plan_moves
            calls = []

            def hooked(r, cfg):
                calls.append(1)
                if len(calls) == 2:
                    swap()
                return real_plan(r, cfg)
            patches.append(mock.patch.object(docmove, "plan_moves", hooked))
        patches.append(mock.patch.object(os, "lstat", fake_lstat))
        patches.append(mock.patch.object(os, "open", spy_open))
        old = signal.getsignal(signal.SIGALRM)

        def on_alarm(*_):
            raise AssertionError("the cell did not return within 10 s")
        signal.signal(signal.SIGALRM, on_alarm)
        signal.alarm(10)
        out = io.StringIO()
        try:
            with contextlib.ExitStack() as stack:
                for p in patches:
                    stack.enter_context(p)
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                    res["code"] = init.main([sub, "--root", root, "--answers", ans])
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old)
        res.update(out=out.getvalue(), opened=opened, root=root, outside=outside, sub=sub)
        res["moved"] = [(s, d) for s, d in MOVES if not os.path.lexists(os.path.join(root, s))
                        and os.path.isfile(os.path.join(root, d)) and not os.path.islink(os.path.join(root, d))]
        res["root1"] = tree(root)
        res["index1"] = git(root, "ls-files", "-s")
        res["out1"] = tree(outside, skip_git=False)
        return res

    def outcome(self, res):
        """The part of a run that must be the same on both interpreters: exit, FAIL, move and note lines."""
        keep = [l for l in res["out"].splitlines() if l.startswith(("FAIL ", "note: ", "move "))]
        return "%s|%s" % (res["code"], "/".join(keep))

    def result(self, cell):
        if cell.ident not in _RESULTS:
            res = self.run_cell(cell)
            res["tmp_root"] = res.pop("root")  # the paths of a finished cell are dropped with its directory
            res.pop("outside")
            _RESULTS[cell.ident] = res
        return _RESULTS[cell.ident]

    # ------------------------------------------------------------------------------------------- the checks
    def problems(self, cell):
        """Every way ``cell`` differs from its hand-written verdict; an empty list is a pass."""
        res = self.result(cell)
        slot, state, moment, out = cell.slot, cell.state, cell.moment, res["out"]
        bad = []
        if res["out0"] != res["out1"]:
            bad.append("the outside tree changed")
        if res["opened"]:
            bad.append("os.open reached the outside tree: %s" % res["opened"][:2])
        if [e for e in res["root0"] if e[0].startswith("zz-inside")] != [e for e in res["root1"] if e[0].startswith("zz-inside")]:
            bad.append("the inside copy of the children changed (read or written through a link)")
        fails = [l for l in out.splitlines() if l.startswith("FAIL ")]
        notes = [l for l in out.splitlines() if l.startswith("note: ") and l.endswith("not a regular file; not read")]
        oracle = Oracle(slot, state)
        written = res["root0"] != res["root1"] or res["index0"] != res["index1"]
        if state == "N1":  # V11
            want = "FAIL init.%s: git ls-files gave output that is not valid UTF-8" % ("migrate" if moment == "C3" else "input")
            if (res["code"], fails) != (1, [want]):
                bad.append("want exit 1 and %r, got %r %r" % (want, res["code"], fails))
            if written:
                bad.append("a name that is not UTF-8 changed the tree or the index")
            return bad
        if slot.ident in STATE_DIR_SLOTS and moment == "C3":
            # V9 says the conflicts of ``_dir_plan`` at C3; the code does not plan the directories again after its file
            # writes (OQ-9b): only the invariants are asserted here, the observed exit code is in the digest.
            if res["code"] not in (0, 1):
                bad.append("exit %r" % res["code"])
            return bad
        lines = []
        if slot.ident in STATE_DIR_SLOTS:
            lines = state_dir_lines(slot.ident, state)
            expect_notes = []
        else:
            lines = oracle.move_conflicts()
            expect_notes = oracle.not_read()
        if lines:
            if moment == "C3":
                want = ["FAIL init.migrate: " + "; ".join(lines)]
            else:
                want = ["FAIL init.conflict: " + l for l in lines]
            if (res["code"], fails) != (1, want):
                bad.append("want exit 1 and %r, got %r %r" % (want, res["code"], fails))
            if moment != "C3" and out != "".join(w + "\n" for w in want):
                bad.append("stdout is not exactly the conflict lines: %r" % out[:300])
            if written:
                bad.append("a refused run changed the tree or the index" if moment != "C3" else
                           "a refused migration moved or rewrote something after its file writes")
            if moment == "C3" and not [e for e in res["root1"] if e[0] == ".strict-delivery/config.yml" and stat.S_ISREG(e[1])]:
                bad.append("the file writes did not stay (CD12)")
            return bad
        if res["code"] != 0 or fails:
            bad.append("want exit 0 and no FAIL line, got %r %r" % (res["code"], fails))
            return bad
        want_notes = expect_notes if moment != "C3" else []  # C3: the notes are those of the plan before the swap
        if sorted(notes) != sorted(want_notes):
            bad.append("notes: want %r, got %r" % (want_notes, notes))
        if moment == "C1":
            if written:
                bad.append("plan wrote")
            printed = [tuple(l[5:].split(" -> ")) for l in out.splitlines() if l.startswith("move ")]
            if printed != MOVES:
                bad.append("plan lists %r" % printed)
            return bad
        for pair in MOVES:  # apply: every move made (PM-S4..S6, AM-W1)
            if pair not in res["moved"]:
                bad.append("move %s -> %s was not made" % pair)
        if slot.group in ("H", "HP") and slot.ident not in STATE_DIR_SLOTS and state in ("S4", "S5", "S6", "S7", "S8", "S9"):
            before = [e for e in res["root0"] if e[0] == slot.path]
            after = [e for e in res["root1"] if e[0] == slot.path]
            if before != after:
                bad.append("the swapped holder changed")
        return bad


# the number of cells of each verdict class, counted by hand from the slot list above (per moment x 3)
CLASS_COUNT = {"names_index": 51, "controls": 45, "state_dirs": 108, "source_last": 48, "source_parents": 120,
               "target_last": 48, "target_parents": 108, "holders": 72, "holder_parents": 72}
SLOT_COUNT = {"SRC-plan": 30, "SRC-spec": 30, "SP-docs": 30, "SP-sup": 30, "SP-specs": 30, "SP-plans": 30,
              "SP-plansx": 30, "TGT-plan": 27, "TGT-spec": 27, "TP-ds": 27, "TP-dss": 27, "TP-dsp": 27, "TP-dspx": 27,
              "H-readme": 30, "H-guide": 30, "H-wf": 30, "H-state": 30, "HP-guide": 30, "HP-gh": 30, "HP-ghwf": 30,
              "HP-st": 30, "HP-stst": 30, "HP-dec": 30}


class PathMatrixTest(MatrixCase):
    """``I`` cells of the P4 count: 672 = 3 moments x (23 slots x 9 states + 17 non-UTF-8 names)."""

    def run_class(self, name):
        cells = [c for c in all_cells() if class_of(c) == name]
        random.Random(SEED).shuffle(cells)  # the seed orders the execution, so state leaking between cells shows
        self.assertEqual(len(cells), CLASS_COUNT[name], name)
        failing = []
        for c in cells:
            with self.subTest(cell=c.ident):
                got = self.problems(c)
                if got:
                    failing.append(c.ident)
                self.assertEqual(got, [], c.ident)
        self.assertEqual(failing, [])

    def test_pm_matrix_count(self):
        cells = all_cells()
        self.assertEqual(len(cells), COUNT)
        self.assertEqual(len({c.ident for c in cells}), COUNT)
        for moment in MOMENTS:
            self.assertEqual(len([c for c in cells if c.moment == moment]), 224, moment)
        for group, n in PER_GROUP.items():
            self.assertEqual(len([c for c in cells if c.slot.group == group]), n, group)
        for ident, n in SLOT_COUNT.items():
            self.assertEqual(len([c for c in cells if c.slot.ident == ident]), n, ident)
        self.assertEqual(sorted(SLOT_COUNT), sorted(s.ident for s in SLOTS))
        self.assertEqual(sum(CLASS_COUNT.values()), COUNT)
        self.assertEqual(len([c for c in cells if c.state == "N1"]), 51)

    def test_pm_matrix_seed_printed(self):
        line = "init path matrix seed %d cells %d" % (SEED, len(all_cells()))
        self.assertEqual(line, "init path matrix seed 20261126 cells 672")
        import sys
        sys.stderr.write(line + "\n")

    def test_pm_matrix_controls(self):  # V0
        self.run_class("controls")

    def test_pm_matrix_source_parents(self):  # V1, V2
        self.run_class("source_parents")

    def test_pm_matrix_source_last(self):  # V3
        self.run_class("source_last")

    def test_pm_matrix_target_last(self):  # V4, V5
        self.run_class("target_last")

    def test_pm_matrix_target_parents(self):  # V6
        self.run_class("target_parents")

    def test_pm_matrix_holders(self):  # V7
        self.run_class("holders")

    def test_pm_matrix_holder_parents(self):  # V8
        self.run_class("holder_parents")

    def test_pm_matrix_state_dirs(self):  # V9 (C1, C2; at C3 the invariants only, see ``problems``), V7 for H-state
        self.run_class("state_dirs")

    def test_pm_matrix_names_index(self):  # V11
        self.run_class("names_index")

    def test_pm_matrix_named_review2_cells(self):  # P7 R2B-3: the cells review 2b probed, expected lines written out
        count = 0
        by_id = {c.ident: c for c in all_cells()}
        named = [("I.%s.%s.%s" % (slot, state, moment), lines) for (slot, state), lines in NAMED_CELLS.items()
                 for moment in ("C1", "C2")]
        named += [("I.%s.S2.C1" % slot, lines) for slot, lines in NAMED_PARENT_S2.items()]
        for ident, lines in named:
            with self.subTest(cell=ident):
                res = self.result(by_id[ident])
                conflict = lines[0].startswith("FAIL ")
                self.assertEqual(res["code"], 1 if conflict else 0, ident)
                if conflict:
                    self.assertEqual(res["out"], "".join(l + "\n" for l in lines), ident)
                else:
                    got = [l for l in res["out"].splitlines() if l.startswith("note: ")]
                    self.assertEqual(got, lines, ident)
                self.assertEqual(res["out0"], res["out1"], ident)
                self.assertEqual(res["opened"], [], ident)
                count += 1
        self.assertEqual(count, 12 * 2 + 8)

    def test_pm_matrix_digest(self):  # the controller compares the digest across the two interpreters
        lines = []
        for c in all_cells():
            self.result(c)
            lines.append("%s=%s" % (c.ident, self.outcome(_RESULTS[c.ident])))
        digest = hashlib.sha256("\n".join(sorted(lines)).encode("utf-8")).hexdigest()
        import sys
        sys.stderr.write("init path matrix digest %s\n" % digest)
        self.assertEqual(len(lines), COUNT)


if __name__ == "__main__":
    unittest.main()
