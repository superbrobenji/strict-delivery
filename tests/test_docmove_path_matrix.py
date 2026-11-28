"""The generated path matrix of Task 4d.2 (Amendment P, owner rule 2026-11-26 21:10): path role x file state x moment, run
through ``docmove`` (entry ``D``) and ``init.main`` (entry ``I``). Every cell of the table is enumerated (nothing is
sampled); the seed orders the execution and names the sentinel bytes. The oracle is written by hand from the rules of
the domain table (V0..V19) and the fixture below; nothing here reads the code under test back. This file is an exempt
site of the old-path literal (spec section 4)."""
import collections
import contextlib
import copy
import errno
import hashlib
import io
import os
import random
import shutil
import signal
import socket
import stat
import subprocess
import tempfile
import time
import unittest
from unittest import mock

from gates.lib import config, docmove, gitinfo, managed, yamlsub
from gates.lib.result import GateError
from gates.tools import init
from tests import helpers

SEED = 20261126
S1, S2, S3, S4, S5, S6, S7, S8, S9 = ("S%d" % i for i in range(1, 10))
STATES = (S1, S2, S3, S4, S5, S6, S7, S8, S9)
CFG = copy.deepcopy(config.DEFAULTS)
STATE_DIRS = [CFG["paths"][k] for k in ("decisions", "findings", "claims", "plan_state", "programs")]
KEYS = ("decisions", "findings", "claims", "plan_state", "programs")
OLD = "docs/superpowers/specs/a.md"
NEW = "docs/strict-delivery/specs/a.md"
SRC_PLAN, SRC_SPEC = "docs/superpowers/plans/x/p.md", OLD
DST_PLAN, DST_SPEC = "docs/strict-delivery/plans/x/p.md", NEW
MOVES = [(SRC_PLAN, DST_PLAN), (SRC_SPEC, DST_SPEC)]  # plan_moves lists them in src order (PM-S7)
MENTION = "see %s\n" % OLD
FILES = {  # F42: the tracked files and their texts
    SRC_PLAN: MENTION, SRC_SPEC: "# spec a\n", "README.md": MENTION, "docs/guide/g.md": MENTION,
    ".github/workflows/other.yml": MENTION, ".strict-delivery/state/decisions/D-1.yml": "id: D-1\n"}
# change order of apply_moves: sorted by path, the moved plan at its new path
CHANGES = [(".github/workflows/other.yml", MENTION.replace(OLD, NEW)), ("README.md", MENTION.replace(OLD, NEW)),
           ("docs/guide/g.md", MENTION.replace(OLD, NEW)), (DST_PLAN, MENTION.replace(OLD, NEW))]

Slot = collections.namedtuple("Slot", "id group rel is_dir")
SLOTS = [
    Slot("SRC-plan", "SRC", SRC_PLAN, False), Slot("SRC-spec", "SRC", SRC_SPEC, False),
    Slot("SP-docs", "SP", "docs", True), Slot("SP-sup", "SP", "docs/superpowers", True),
    Slot("SP-specs", "SP", "docs/superpowers/specs", True), Slot("SP-plans", "SP", "docs/superpowers/plans", True),
    Slot("SP-plansx", "SP", "docs/superpowers/plans/x", True),
    Slot("TGT-plan", "TGT", DST_PLAN, False), Slot("TGT-spec", "TGT", DST_SPEC, False),
    Slot("TP-ds", "TP", "docs/strict-delivery", True), Slot("TP-dss", "TP", "docs/strict-delivery/specs", True),
    Slot("TP-dsp", "TP", "docs/strict-delivery/plans", True), Slot("TP-dspx", "TP", "docs/strict-delivery/plans/x", True),
    Slot("H-readme", "H", "README.md", False), Slot("H-guide", "H", "docs/guide/g.md", False),
    Slot("H-wf", "H", ".github/workflows/other.yml", False),
    Slot("H-state", "H", ".strict-delivery/state/decisions/D-1.yml", False),
    Slot("HP-guide", "HP", "docs/guide", True), Slot("HP-gh", "HP", ".github", True),
    Slot("HP-ghwf", "HP", ".github/workflows", True), Slot("HP-st", "HP", ".strict-delivery", True),
    Slot("HP-stst", "HP", ".strict-delivery/state", True), Slot("HP-dec", "HP", ".strict-delivery/state/decisions", True),
]
BY_ID = {s.id: s for s in SLOTS}
STATE_SLOTS = ("H-state", "HP-st", "HP-stst", "HP-dec")
B_SLOTS = {  # the slot sets of the B moments (P3); B2 is k = 1 (the B1 set) and B2k2 (k = 2, the B0 set)
    "B0": ("SRC-spec", "SP-docs", "SP-sup", "SP-specs", "TGT-spec", "TP-ds", "TP-dss"),
    "B1": ("SRC-plan", "SP-docs", "SP-sup", "SP-plans", "SP-plansx", "TGT-plan", "TP-ds", "TP-dsp", "TP-dspx"),
    "B3": ("H-readme", "H-guide", "H-wf", "TGT-plan", "SP-docs", "HP-guide", "HP-gh", "HP-ghwf", "TP-ds", "TP-dsp", "TP-dspx"),
    "B4": ("H-readme", "H-guide", "H-wf", "H-state", "SRC-spec", "SRC-plan", "SP-docs", "SP-sup", "SP-specs", "SP-plans",
           "SP-plansx", "HP-guide", "HP-gh", "HP-ghwf", "HP-st", "HP-stst", "HP-dec"),
}
B_SLOTS["B2"] = B_SLOTS["B1"]
B_SLOTS["B2k2"] = B_SLOTS["B0"]
B_ORDER = ("B0", "B1", "B2", "B2k2", "B3", "B4")
WRITE_INDEX = {"H-wf": 1, "HP-gh": 1, "HP-ghwf": 1, "H-readme": 2, "H-guide": 3, "HP-guide": 3, "SP-docs": 3}  # B3: the k-th write
NOT_DIR = "%s: parent %s is not a directory"
NOT_REG = "%s: not a regular file; not moved"
MISSING = "%s: tracked but missing; not moved"
UTF8 = "git ls-files gave output that is not valid UTF-8"
ENC = "%s: item %d holds a path that is not encodable as UTF-8"


def cells():
    """Every cell of P4: ``(entry, slot id, state, moment)``; a state key sweep slot is ``KEY-<key>``."""
    out = []
    tracked = [s.id for s in SLOTS if s.group in ("SRC", "SP", "H", "HP")]
    moved = [s.id for s in SLOTS if s.group in ("SRC", "SP", "TGT", "TP")]
    targets = [s.id for s in SLOTS if s.group in ("TGT", "TP")]
    for s in SLOTS:
        out += [("D", s.id, st, "C1") for st in STATES]
        out += [("D", s.id, st, "C2") for st in STATES]
    out += [("D", "KEY-" + k, st, "C1") for k in KEYS for st in (S2, S5)]
    out += [("D", i, "N1", "C1") for i in tracked] + [("D", i, "N2", "C1") for i in moved]
    out += [("D", i, "N1", "C2") for i in targets] + [("D", s.id, "N2", "C2") for s in SLOTS]
    for m in B_ORDER:
        out += [("D", i, st, m) for i in B_SLOTS[m] for st in STATES]
    for m in ("C1", "C2", "C3"):
        out += [("I", s.id, st, m) for s in SLOTS for st in STATES]
        out += [("I", i, "N1", m) for i in tracked]
    return out


def cell_id(cell):
    return "%s.%s.%s.%s" % cell


def not_reached():
    """The cells of the full 23 x 11 x 5 + 60 x 11 universe that are not run (P4): 240."""
    universe = set()
    for entry, moment in (("D", "C1"), ("D", "C2"), ("I", "C1"), ("I", "C2"), ("I", "C3")):
        universe |= {(entry, s.id, st, moment) for s in SLOTS for st in STATES + ("N1", "N2")}
    for m in B_ORDER:
        universe |= {("D", i, st, m) for i in B_SLOTS[m] for st in STATES + ("N1", "N2")}
    run = {c for c in cells() if not c[1].startswith("KEY-")}
    return universe - run


# ---------------------------------------------------------------------------------------------- the model (hand-written)
BASE_DIRS = {"docs", "docs/superpowers", "docs/superpowers/specs", "docs/superpowers/plans", "docs/superpowers/plans/x",
             "docs/guide", ".github", ".github/workflows", ".strict-delivery", ".strict-delivery/state",
             ".strict-delivery/state/decisions"}
AFTER_MOVE1 = BASE_DIRS | {"docs/strict-delivery", "docs/strict-delivery/plans", "docs/strict-delivery/plans/x"}
KIND_OF_STATE = {S1: "absent", S2: "reg", S3: "dir", S4: "lnk", S5: "lnk", S6: "lnk", S7: "fifo", S8: "sock", S9: "chr"}


def kind(path, sw, dirs=BASE_DIRS, files=None):
    """The ``lstat`` kind of ``path`` in the fixture with the swap ``sw = (slot, state)`` applied: absent, dir, reg, lnk,
    fifo, sock, chr; ``unreach`` below a slot that is not a directory (a walk stops at the slot)."""
    files = files if files is not None else set(FILES)
    base = "dir" if path in dirs else "reg" if path in files else "absent"
    if sw is None:
        return base
    slot, st = sw
    p0 = slot.rel
    if path == p0:
        if st == S3 and slot.is_dir and p0 in dirs:
            return "dir"
        return KIND_OF_STATE[st]
    if path.startswith(p0 + "/"):
        if st == S1:
            return "absent"
        if st == S3:
            return base if slot.is_dir and p0 in dirs else "absent"
        return "unreach"
    if st != S1 and p0.startswith(path + "/") and base == "absent":
        return "dir"  # the missing ancestors of the swapped slot are made as real directories
    return base


def walk(path, sw, **kw):
    parts = path.split("/")
    for i in range(len(parts)):
        pre = "/".join(parts[:i + 1])
        k = kind(pre, sw, **kw)
        if k == "absent":
            return ("absent",)
        if i == len(parts) - 1:
            return ("ok",) if k == "reg" else ("notreg",)
        if k != "dir":
            return ("parent", pre)
    return ("ok",)


def src_text(src, w):
    if w[0] == "parent":
        return NOT_DIR % (src, w[1])
    return NOT_REG % src if w[0] == "notreg" else MISSING % src if w[0] == "absent" else None


def dst_conflict(dst, sw):
    """The ``plan_moves`` conflict of one target, or None (V4, V5, V6; PM-T1..T5)."""
    parts = dst.split("/")
    for i in range(len(parts)):
        pre = "/".join(parts[:i + 1])
        k = kind(pre, sw)
        if k in ("absent", "unreach"):
            return None
        if i < len(parts) - 1 and k != "dir":
            return "%s: parent %s is not a directory" % (dst, pre)
        if i == len(parts) - 1:
            return "%s: is a symlink" % dst if k == "lnk" else "%s: exists" % dst
    return None


def model_plan(sw):
    """``conflicts`` of ``plan_moves`` (sorted, de-duplicated)."""
    out = set()
    for src, dst in MOVES:
        t = src_text(src, walk(src, sw))
        if t:
            out.add(t)
        c = dst_conflict(dst, sw)
        if c:
            out.add(c)
    return sorted(out)


def model_rewrites(sw):
    """``(changes dict, notes list)`` of ``rewrites`` for the moves (V7, V8, V10)."""
    changes, notes = {}, []
    for holder in sorted(FILES):
        shown = dict(MOVES).get(holder, holder)
        w = walk(holder, sw)
        if w[0] == "absent":
            continue
        if w[0] != "ok":
            notes.append((shown, "%s: not a regular file; not read" % shown))
            continue
        text = "reg\n" if sw is not None and sw[0].rel == holder and sw[1] == S2 else FILES[holder]  # a rewritten file
        if OLD in text:
            changes[shown] = text.replace(OLD, NEW)
    return changes, [n[1] for n in sorted(notes)]


def model_apply(sw, dirs=BASE_DIRS, extra_done=()):
    """The outcome of ``apply_moves`` of the clean plan when ``sw`` is applied before it (C2): ``("ok",)`` or
    ``("err", text)``."""
    for src, _dst in MOVES:  # the sources first, in move order (no suffix)
        t = src_text(src, walk(src, sw))
        if t and not t.endswith("tracked but missing; not moved"):
            return ("err", t)
    for _src, dst in MOVES:  # _preflight in move order
        k = kind(dst, sw)
        if k not in ("absent", "unreach"):
            return ("err", "%s: exists; nothing was moved" % dst)
        parts = dst.split("/")
        for i in range(len(parts) - 1):
            pre = "/".join(parts[:i + 1])
            k = kind(pre, sw)
            if k == "absent":
                break
            if k != "dir":
                return ("err", "%s: parent %s is not a directory; nothing was moved" % (dst, pre))
    done = []
    for src, dst in MOVES:
        if walk(src, sw)[0] == "absent":
            return ("err", "git mv failed (exit 128): %s -> %s%s" % (src, dst, moved_text(done)))
        done.append((src, dst))
    written = []
    for path, _text in CHANGES:
        w = walk(path, sw if path != DST_PLAN else None, dirs=AFTER_MOVE1, files=(set(FILES) - {SRC_PLAN}) | {DST_PLAN})
        before = "; written before it: " + ", ".join(written) if written else ""
        if w[0] == "absent":
            return ("err", "%s: missing%s" % (path, before))
        if w[0] != "ok":
            return ("err", "%s: not a regular file%s" % (path, before))
        written.append(path)
    return ("ok",)


def moved_text(done):
    return "; moved before it: " + ", ".join("%s -> %s" % m for m in done) if done else ""


def model_between_moves(sw):
    """B0, V14, V15: the swap lands after move 1; the outcome of move 2, or None where no text exists (V16)."""
    slot, st = sw
    m1 = moved_text([MOVES[0]])
    src, dst = MOVES[1]
    kw = {"dirs": AFTER_MOVE1, "files": (set(FILES) - {SRC_PLAN}) | {DST_PLAN}}
    if slot.group in ("SRC", "SP"):
        w = walk(src, sw, **kw)
        if w[0] in ("parent", "notreg"):
            return ("err", (NOT_DIR % (src, w[1]) if w[0] == "parent" else NOT_REG % src) + m1)
        if st == S1:
            return ("err", "git mv failed (exit 128): %s -> %s%s" % (src, dst, m1))
        return ("ok",)
    if slot.group == "TP":
        if slot.id == "TP-ds" and st == S1:  # the swap removed the plan that move 1 had put below it
            return ("err", "%s: missing; written before it: %s" % (DST_PLAN, ", ".join(p for p, _ in CHANGES[:3])))
        if st in (S1, S3):
            return ("ok",)
        return ("err", "%s: parent %s is not a directory%s" % (dst, slot.rel, m1))
    return None


# ------------------------------------------------------------------------------------------------------------- the runner
class Boom(Exception):
    pass


class PathMatrixTest(helpers.GitIsolatedTestCase):
    results = None

    def setUp(self):
        super().setUp()
        self.dev = None
        self.root = None

    # ---- fixture
    def build_template(self):
        base = tempfile.mkdtemp(dir=self.tmp)
        root = os.path.join(base, "repo")
        os.mkdir(root)
        helpers.git(root, "init", "-q", "-b", "main")
        for k, v in (("user.email", "f@example.invalid"), ("user.name", "F"), ("commit.gpgsign", "false")):
            helpers.git(root, "config", k, v)
        for rel, text in FILES.items():
            self.write(root, rel, text)
        helpers.commit_all(root, "f42")
        outside = os.path.join(base, "outside")
        os.mkdir(outside)
        with open(os.path.join(outside, "sentinel"), "wb") as fh:
            fh.write(b"sentinel %d\n" % SEED)
        with open(os.path.join(outside, "o.md"), "w") as fh:
            fh.write(OLD + "\n")
        for s in SLOTS:
            if s.is_dir:
                src = os.path.join(root, s.rel)
                dst = os.path.join(outside, s.id)
                shutil.copytree(src, dst, symlinks=True) if os.path.isdir(src) else os.mkdir(dst)
        for key in KEYS:  # the state-key sweep: a link target that holds the record
            self.write(outside, "KEY-%s/R.yml" % key, MENTION)
        return base

    @staticmethod
    def write(root, rel, text):
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)

    def fresh(self, template):
        base = tempfile.mkdtemp(dir=self.tmp)
        os.rmdir(base)
        shutil.copytree(template, base, symlinks=True)
        return os.path.join(base, "repo"), os.path.join(base, "outside")

    # ---- states
    def set_state(self, root, outside, slot, st):
        p = os.path.join(root, slot.rel)
        if st == S9:  # a character device by a patched lstat: nothing on disk changes but the missing ancestors
            os.makedirs(os.path.dirname(p), exist_ok=True)
            self.dev = p
            return
        if st == S3 and slot.is_dir and os.path.isdir(p) and not os.path.islink(p):
            return  # the baseline directory unchanged (control)
        inside = os.path.join(root, "inside-" + slot.id)
        existed = os.path.lexists(p)
        if st == S4 and existed and not os.path.islink(p):
            os.rename(p, inside)  # the link target holds the children
        elif st == S4:
            if slot.is_dir:
                os.makedirs(inside)
            else:
                self.write(root, "inside-" + slot.id, "in\n")
        if os.path.lexists(p):
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p)
            else:
                os.unlink(p)
        if st == S1:
            return
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if st == S2:
            with open(p, "w") as fh:
                fh.write("reg\n")
        elif st == S3:
            os.makedirs(p)
        elif st == S4:
            os.symlink(inside, p)
        elif st == S5:
            os.symlink(os.path.join(outside, slot.id if slot.is_dir else "o.md"), p)
        elif st == S6:
            os.symlink("no-such-name", p)
        elif st == S7:
            os.mkfifo(p)
        elif st == S8:
            cwd = os.getcwd()
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                os.chdir(os.path.dirname(p))
                sock.bind(os.path.basename(p))
            finally:
                os.chdir(cwd)
                sock.close()

    def lstat_patch(self):
        real = os.lstat

        def fake(p, *a, **k):
            if self.dev is not None and p == self.dev:
                st = real(self.root, *a, **k)
                return os.stat_result((stat.S_IFCHR | 0o600,) + tuple(st)[1:])
            return real(p, *a, **k)
        return mock.patch("os.lstat", side_effect=fake)

    # ---- snapshots and spies
    @staticmethod
    def snap(top, git_index=True):
        out = {}
        for dp, dns, fns in os.walk(top):
            dns[:] = [d for d in dns if d != ".git"]
            for n in dns + fns:
                p = os.path.join(dp, n)
                st = os.lstat(p)
                if stat.S_ISLNK(st.st_mode):
                    body = os.readlink(p)
                elif stat.S_ISREG(st.st_mode):
                    with open(p, "rb") as fh:
                        body = fh.read()
                else:
                    body = b""
                out[os.path.relpath(p, top)] = (stat.S_IFMT(st.st_mode), stat.S_IMODE(st.st_mode), body)
        if git_index:
            out[".git/index"] = helpers.git(top, "ls-files", "-s")
        return out

    @staticmethod
    def ids(top):
        out = set()
        for dp, dns, fns in os.walk(top):
            for n in dns + fns:
                try:
                    st = os.lstat(os.path.join(dp, n))
                except OSError:
                    continue
                out.add((st.st_dev, st.st_ino))
        return out

    def open_spy(self, outside_ids, viol, extra=None):
        real = os.open

        def spy(p, flags, *a, **k):
            if extra:
                extra(p, k)
            fd = real(p, flags, *a, **k)
            try:
                st = os.fstat(fd)
            except OSError:
                return fd
            if (st.st_dev, st.st_ino) in outside_ids:
                viol.append(str(p))
            return fd
        return mock.patch("os.open", side_effect=spy)

    # ---- one cell
    def init_answers(self, base):
        path = os.path.join(base, "answers.yml")
        data = {"schema": "init-answers/1", "profile": "standard",
                "models": {"tiers": {"tier1": "haiku", "tier2": "sonnet", "tier3": "opus"}},
                "commands": {"test": "python3 -m unittest", "test_one": "python3 -m unittest {id}", "lint": "ruff check .",
                             "build": "make"},
                "git_hooks": False, "ci": False, "merge_mode": "host", "subagents": {"depth": 5, "concurrent": 30},
                "protect_base": False, "base_branch": "main", "migrate": True}
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(yamlsub.emit(data))
        return path

    def index_name(self, root, slot):
        """N1: a tracked name holding the byte 0xff next to the slot (index level: the file system cannot hold it)."""
        name = slot.rel + "\udcff" + ("/z.md" if slot.is_dir else "")
        blob = subprocess.run(["git", "-C", root, "hash-object", "-w", "--stdin"], input=b"z\n",
                              stdout=subprocess.PIPE, check=True).stdout.decode().strip()
        subprocess.run(["git", "-C", root, "update-index", "--add", "--cacheinfo", "100644,%s,%s" % (blob, name)], check=True)

    def altered(self, slot, mark):
        """The moves with ``mark`` put after the slot's last component in every path that holds the slot."""
        out = []
        for src, dst in MOVES:
            out.append(tuple(self.mark(p, slot.rel, mark) for p in (src, dst)))
        return out

    @staticmethod
    def mark(path, rel, mark):
        if path == rel:
            return path + mark
        if path.startswith(rel + "/"):
            return rel + mark + path[len(rel):]
        return path

    def run_cell(self, template, cell):
        entry, sid, st, moment = cell
        root, outside = self.fresh(template)
        self.root = root
        self.dev = None
        out = {"res": None, "viol": [], "outside_changed": False, "root_changed": None}
        outside_before = self.snap(outside, False)
        outside_ids = self.ids(outside)
        old = signal.signal(signal.SIGALRM, self.alarm)
        signal.alarm(30)
        try:
            with self.lstat_patch():
                if entry == "D":
                    out["res"] = self.run_d(root, outside, outside_ids, out, cell)
                else:
                    out["res"] = self.run_i(root, outside, outside_ids, out, cell)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old)
        out["outside_changed"] = self.snap(outside, False) != outside_before
        return out

    @staticmethod
    def alarm(*_):
        raise Boom("cell timed out (a blocked open of a FIFO?)")

    @staticmethod
    def capture(fn):
        try:
            return ("ok", fn())
        except GateError as e:
            return ("err", str(e))
        except Boom:
            raise
        except Exception as e:  # noqa: BLE001 - recorded as a finding of the cell
            return ("exc", "%s: %s" % (type(e).__name__, e))

    def run_d(self, root, outside, outside_ids, out, cell):
        _entry, sid, st, moment = cell
        slot = BY_ID.get(sid)
        viol = out["viol"]
        if sid.startswith("KEY-"):
            return self.run_key(root, outside, outside_ids, out, cell)
        if st == "N1" and moment == "C1":
            self.index_name(root, slot)
            return ("n1", self.capture(lambda: docmove.plan_moves(root, CFG)),
                    self.capture(lambda: docmove.rewrites(root, MOVES, STATE_DIRS)))
        if st in ("N1", "N2"):
            mark = "\udcff" if st == "N1" else "\ud800"
            if slot.group in ("SRC", "SP", "TGT", "TP"):
                moves, changes = self.altered(slot, mark), []
            else:
                moves = []
                changes = [(slot.rel + mark + ("/x.md" if slot.is_dir else ""), "t\n")]
            before = self.snap(root)
            if moment == "C1":
                res = self.capture(lambda: docmove.rewrites(root, moves, STATE_DIRS))
            else:
                res = self.capture(lambda: docmove.apply_moves(root, moves, changes))
            out["root_changed"] = self.snap(root) != before
            return ("n2", res, moves, changes)
        if moment == "C1":
            self.set_state(root, outside, slot, st)
            with self.open_spy(outside_ids, viol):
                plan = self.capture(lambda: docmove.plan_moves(root, CFG))
                rew = self.capture(lambda: docmove.rewrites(root, MOVES, STATE_DIRS))
            return ("c1", plan, rew)
        moves, _c, _n = docmove.plan_moves(root, CFG)
        changes, _n2, _c2 = docmove.rewrites(root, moves, STATE_DIRS)
        if moment == "C2":
            self.set_state(root, outside, slot, st)
            before = self.snap(root)
            with self.open_spy(outside_ids, viol):
                res = self.capture(lambda: docmove.apply_moves(root, moves, changes))
            out["root_changed"] = self.snap(root) != before
            return ("c2", res)
        return self.run_window(root, outside, outside_ids, out, cell, moves, changes)

    def run_key(self, root, outside, outside_ids, out, cell):
        _e, sid, st, _m = cell
        key = sid[4:]
        rel = CFG["paths"][key]
        slot = Slot(sid, "KEY", rel, True)
        self.write(root, rel + "/R.yml", MENTION)  # outside/<sid> (S5 target) holds the same record: see build_template
        helpers.commit_all(root, "record")
        self.set_state(root, outside, slot, st)
        with self.open_spy(outside_ids, out["viol"]):
            return ("key", self.capture(lambda: docmove.rewrites(root, MOVES, STATE_DIRS)), rel)

    def run_window(self, root, outside, outside_ids, out, cell, moves, changes):
        _e, sid, st, moment = cell
        slot = BY_ID[sid]
        state = {"n": 0, "swapped": False}

        def swap():
            if not state["swapped"]:
                state["swapped"] = True
                self.set_state(root, outside, slot, st)
        real_run, real_mkdir, real_write = gitinfo._run, os.mkdir, managed._write

        def run(r, name, *a, **k):
            if name == "mv":
                state["n"] += 1
                if moment == "B2" and state["n"] == 1 or moment == "B2k2" and state["n"] == 2:
                    swap()
            p = real_run(r, name, *a, **k)
            if name == "mv" and moment == "B0" and state["n"] == 1:
                swap()
            return p

        def mkdir(p, *a, **k):
            if moment == "B1":
                swap()
            return real_mkdir(p, *a, **k)

        def write(r, path, text):
            state["w"] = state.get("w", 0) + 1
            if moment == "B3" and state["w"] == WRITE_INDEX.get(sid, 4):
                swap()
            return real_write(r, path, text)

        def on_open(p, k):
            below = os.path.join(root, slot.rel)  # an open by name (the lstat walk's twin) or from a descriptor
            if moment == "B4" and (k.get("dir_fd") is not None and p == os.path.basename(slot.rel)
                                   or isinstance(p, str) and (p == below or p.startswith(below + "/"))):
                swap()
        patches = [mock.patch("gates.lib.gitinfo._run", side_effect=run), mock.patch("os.mkdir", side_effect=mkdir),
                   mock.patch("gates.lib.managed._write", side_effect=write)]
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            with self.open_spy(outside_ids, out["viol"], on_open):
                if moment == "B4":
                    res = self.capture(lambda: docmove.rewrites(root, moves, STATE_DIRS))
                else:
                    res = self.capture(lambda: docmove.apply_moves(root, moves, changes))
        return ("win", res, state["swapped"])

    def run_i(self, root, outside, outside_ids, out, cell):
        _e, sid, st, moment = cell
        slot = BY_ID[sid]
        ans = self.init_answers(os.path.dirname(root))
        argv = ["apply" if moment in ("C2", "C3") else "plan", "--root", root, "--answers", ans]
        if st == "N1":
            self.index_name(root, slot)
        elif moment != "C3":
            self.set_state(root, outside, slot, st)
        real_plan = docmove.plan_moves
        calls = []

        def plan_moves(r, cfg):
            calls.append(1)
            if moment == "C3" and len(calls) == 2 and st in STATES:  # the first call is the plan of init apply, the second Q16's recompute
                self.set_state(root, outside, slot, st)
            return real_plan(r, cfg)
        before = self.snap(root)
        sout, serr = io.StringIO(), io.StringIO()
        patches = [mock.patch("gates.lib.docmove.plan_moves", side_effect=plan_moves)]
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            with self.open_spy(outside_ids, out["viol"]), contextlib.redirect_stdout(sout), contextlib.redirect_stderr(serr):
                res = self.capture(lambda: init.main(argv))
        out["root_changed"] = self.snap(root) != before
        return ("init", res, sout.getvalue() + serr.getvalue())

    # ---- all cells, once
    @classmethod
    def all_results(cls, test):
        if cls.results is None:
            template = test.build_template()
            order = cells()
            random.Random(SEED).shuffle(order)
            res = {}
            for cell in order:
                res[cell] = test.run_cell(template, cell)
            cls.results = res
        return cls.results

    def verdicts(self, pick, check):
        """Failures of ``check(cell, record)`` over the cells ``pick`` selects: the failure message lists every cell id."""
        bad = []
        res = self.all_results(self)
        for cell in sorted(res):
            if pick(cell):
                why = check(cell, res[cell])
                if why:
                    bad.append("%s: %s" % (cell_id(cell), why))
        return bad

    # ============================================================================================ the tests
    def test_pm_matrix_count(self):
        cs = cells()
        self.assertEqual(len(cs), 1695)
        self.assertEqual(len(set(cs)), 1695)
        self.assertEqual(len(not_reached()), 240)
        cls = collections.Counter(("N1" if c[2] == "N1" else "N2" if c[2] == "N2" else "S") for c in cs)
        self.assertEqual((cls["S"], cls["N1"], cls["N2"]), (1585, 74, 36))
        groups = collections.Counter("sweep" if c[1].startswith("KEY-") else BY_ID[c[1]].group for c in cs)
        self.assertEqual(dict(groups), {"SRC": 156, "SP": 435, "TGT": 141, "TP": 309, "H": 263, "HP": 381, "sweep": 10})
        per = collections.Counter(c[1] for c in cs if not c[1].startswith("KEY-"))
        self.assertEqual(dict(per), {
            "SRC-plan": 78, "SRC-spec": 78, "SP-docs": 105, "SP-sup": 96, "SP-specs": 78, "SP-plans": 78, "SP-plansx": 78,
            "TGT-plan": 75, "TGT-spec": 66, "TP-ds": 93, "TP-dss": 66, "TP-dsp": 75, "TP-dspx": 75, "H-readme": 68,
            "H-guide": 68, "H-wf": 68, "H-state": 59, "HP-guide": 68, "HP-gh": 68, "HP-ghwf": 68, "HP-st": 59,
            "HP-stst": 59, "HP-dec": 59})
        by_moment = collections.Counter((c[0], c[3]) for c in cs)
        self.assertEqual({k: v for k, v in by_moment.items() if k[1].startswith("B")},
                         {("D", "B0"): 63, ("D", "B1"): 81, ("D", "B2"): 81, ("D", "B2k2"): 63, ("D", "B3"): 99, ("D", "B4"): 153})
        self.assertEqual((by_moment[("D", "C1")], by_moment[("D", "C2")]), (247, 236))
        self.assertEqual([by_moment[("I", m)] for m in ("C1", "C2", "C3")], [224, 224, 224])

    def test_pm_matrix_seed_printed(self):
        print("path matrix seed %d cells %d" % (SEED, len(cells())))
        self.assertEqual(SEED, 20261126)

    def test_pm_matrix_digest(self):
        lines = sorted("%s=%s" % (cell_id(c), self.outcome(r)) for c, r in self.all_results(self).items())
        digest = hashlib.sha256("\n".join(lines).encode("utf-8", "surrogatepass")).hexdigest()
        print("path matrix digest %s cells %d" % (digest, len(lines)))
        self.assertEqual(len(lines), 1695)

    @staticmethod
    def outcome(r):
        res = r["res"]
        if res[0] in ("c1",):
            body = repr((res[1], res[2]))
        elif res[0] == "init":
            body = repr((res[1][0], res[1][1] if res[1][0] != "ok" else res[1][1], res[2]))
        else:
            body = repr(res[1:])
        return "%s|out=%s|viol=%d" % (body, "changed" if r["outside_changed"] else "same", len(r["viol"]))

    # ---- V0 .. V6, V10, V11..V13: asserted classes
    def check_c1(self, cell, r):
        _e, sid, st, _m = cell
        slot = BY_ID.get(sid)
        sw = (slot, st) if st in STATES else None
        _tag, plan, rew = r["res"]
        if plan[0] != "ok" or rew[0] != "ok":
            return "plan %r rewrites %r" % (plan[:2], rew[:2])
        moves, conflicts, notes = plan[1]
        changes, rnotes, rconf = rew[1]
        want_changes, want_notes = model_rewrites(sw)
        if moves != MOVES or conflicts != model_plan(sw):
            return "moves/conflicts %r want %r" % (conflicts, model_plan(sw))
        if rconf != [] or dict(changes) != want_changes or rnotes != want_notes:
            return "rewrites changes %r notes %r want %r %r" % (sorted(dict(changes)), rnotes, sorted(want_changes), want_notes)
        if r["viol"] or r["outside_changed"]:
            return "outside reached %r changed %r" % (r["viol"], r["outside_changed"])
        return None

    def test_pm_matrix_controls(self):
        baseline = {("SRC-plan", S2), ("SRC-spec", S2), ("TGT-plan", S1), ("TGT-spec", S1), ("TP-ds", S1), ("TP-dss", S1),
                    ("TP-dsp", S1), ("TP-dspx", S1)}
        baseline |= {(s.id, S2) for s in SLOTS if s.group == "H"} | {(s.id, S3) for s in SLOTS if s.is_dir and s.group in ("SP", "HP")}

        def pick(c):
            return c[0] == "D" and c[3] in ("C1", "C2") and (c[1], c[2]) in baseline

        def check(c, r):
            if c[3] == "C1":
                why = self.check_c1(c, r)
                if why:
                    return why
                plan, rew = r["res"][1][1], r["res"][2][1]
                if plan[1] != [] or plan[2] != [] or rew[1] != []:
                    return "control has conflicts or notes: %r %r %r" % (plan[1], plan[2], rew[1])
                return None
            return None if r["res"][1][0] == "ok" else "apply refused: %r" % (r["res"][1],)
        self.assertEqual(self.verdicts(pick, check), [])

    def test_pm_matrix_source_parents(self):  # V1, V2
        def pick(c):
            return c[0] == "D" and c[3] in ("C1", "C2") and c[2] in STATES and BY_ID.get(c[1]) and BY_ID[c[1]].group == "SP"
        self.assertEqual(self.verdicts(pick, self.check_any), [])

    def test_pm_matrix_source_last(self):  # V3
        def pick(c):
            return c[0] == "D" and c[3] in ("C1", "C2") and c[2] in STATES and BY_ID.get(c[1]) and BY_ID[c[1]].group == "SRC"
        self.assertEqual(self.verdicts(pick, self.check_any), [])

    def test_pm_matrix_target_last(self):  # V4, V5
        def pick(c):
            return c[0] == "D" and c[3] in ("C1", "C2") and c[2] in STATES and BY_ID.get(c[1]) and BY_ID[c[1]].group == "TGT"
        self.assertEqual(self.verdicts(pick, self.check_any), [])

    def test_pm_matrix_target_parents(self):  # V6
        def pick(c):
            return c[0] == "D" and c[3] in ("C1", "C2") and c[2] in STATES and BY_ID.get(c[1]) and BY_ID[c[1]].group == "TP"
        self.assertEqual(self.verdicts(pick, self.check_any), [])

    def test_pm_matrix_holders(self):  # V7
        def pick(c):
            return c[0] == "D" and c[3] in ("C1", "C2") and c[2] in STATES and BY_ID.get(c[1]) and BY_ID[c[1]].group == "H"
        self.assertEqual(self.verdicts(pick, self.check_any), [])

    def test_pm_matrix_holder_parents(self):  # V8, V9 (D entry)
        def pick(c):
            return c[0] == "D" and c[3] in ("C1", "C2") and c[2] in STATES and BY_ID.get(c[1]) and BY_ID[c[1]].group == "HP"
        self.assertEqual(self.verdicts(pick, self.check_any), [])

    def check_any(self, cell, r):
        if cell[3] == "C1":
            return self.check_c1(cell, r)
        sw = (BY_ID[cell[1]], cell[2])
        want = model_apply(sw)
        got = r["res"][1]
        if got[0] == "exc":
            return "traceback %s" % got[1]
        if (got[0], got[1] if got[0] == "err" else None) != (want[0], want[1] if want[0] == "err" else None):
            return "got %r want %r" % (got, want)
        if r["viol"]:
            return "opened outside %r" % r["viol"]
        if r["outside_changed"]:
            return "outside tree changed"
        before_moves = got[0] == "err" and ("nothing was moved" in got[1] or "; not moved" in got[1]
                                            or ("parent" in got[1] and "before it" not in got[1]))
        if before_moves and r["root_changed"]:
            return "a refused apply changed the tree"
        return None

    def test_pm_matrix_state_dirs(self):  # V9 (D entry: the state directories as holder parents)
        def pick(c):
            return c[0] == "D" and c[3] in ("C1", "C2") and c[1] in STATE_SLOTS and c[2] in STATES
        self.assertEqual(self.verdicts(pick, self.check_any), [])

    def test_pm_matrix_state_keys(self):  # V10
        def check(c, r):
            _tag, got, rel = r["res"]
            if got[0] != "ok":
                return "refused %r" % (got,)
            changes, notes, conflicts = got[1]
            record = rel + "/R.yml"
            want = "%s: not a regular file; not read" % record
            if conflicts != [] or want not in notes:
                return "conflicts %r notes %r" % (conflicts, notes)
            if r["viol"] or r["outside_changed"]:
                return "outside reached"
            return None
        self.assertEqual(self.verdicts(lambda c: c[1].startswith("KEY-"), check), [])

    def test_pm_matrix_names_index(self):  # V11 (D entry)
        def check(c, r):
            _tag, plan, rew = r["res"]
            if plan != ("err", UTF8) or rew != ("err", UTF8):
                return "plan %r rewrites %r" % (plan, rew)
            return None
        self.assertEqual(self.verdicts(lambda c: c[0] == "D" and c[2] == "N1" and c[3] == "C1", check), [])

    def names_check(self, c, r):
        _tag, res, moves, changes = r["res"]
        _e, sid, st, moment = c
        if res[0] != "err":
            return "got %r" % (res,)
        kind_name, index = "moves", None
        slot = BY_ID[sid]
        if slot.group in ("SRC", "SP", "TGT", "TP"):
            index = next(i for i, m in enumerate(moves) if m != MOVES[i])
        else:
            kind_name, index = "changes", 0
        if res[1] != ENC % (kind_name, index) or r["root_changed"] or r["outside_changed"]:
            return "got %r root changed %r" % (res, r["root_changed"])
        return None

    def test_pm_matrix_names_args(self):  # V12, V13: N2 at C1 and C2, N1 at C2 (refused before any os call)
        def pick(c):
            return c[0] == "D" and c[2] in ("N1", "N2") and not (c[2] == "N1" and c[3] == "C1")
        self.assertEqual(self.verdicts(lambda c: pick(c) and not (c[3] == "C1" and BY_ID[c[1]].group in ("H", "HP")), self.names_check), [])

    # ---- the window cells
    def test_pm_matrix_between_moves(self):  # V14, V15, V16 (B0)
        def check(c, r):
            _tag, res, swapped = r["res"]
            want = model_between_moves((BY_ID[c[1]], c[2]))
            if res[0] == "exc":
                return "traceback %s" % res[1]
            if want is not None and (res[0], res[1] if res[0] == "err" else None) != (want[0], want[1] if want[0] == "err" else None):
                return "got %r want %r" % (res, want)
            if r["viol"] or (want is not None and r["outside_changed"]):
                return "reached outside %r changed %r" % (r["viol"], r["outside_changed"])
            return None
        self.assertEqual(self.verdicts(lambda c: c[3] == "B0", check), [])

    def window_invariants(self, c, r):
        _tag, res, swapped = r["res"]
        if not swapped:
            return "the hook never swapped"
        if res[0] == "exc":
            return "traceback %s" % res[1]
        if r["viol"]:
            return "os.open reached outside %r" % r["viol"]
        return None

    def test_pm_matrix_windows_recorded(self):  # V17, V19: B1, B2, B2k2, B4: invariants asserted, outcomes recorded
        def check(c, r):
            if c[3] == "B4" and c[2] == S1 and c[1] in ("H-readme", "HP-guide"):  # R2A-3: missing is skipped silently
                _tag, res, _s = r["res"]
                if res[0] != "ok" or any("not read" in n for n in res[1][1]):
                    return "R2A-3: got %r" % (res[:1],)
            return self.window_invariants(c, r)
        self.assertEqual(self.verdicts(lambda c: c[3] in ("B1", "B2", "B2k2", "B4"), check), [])
        res = self.all_results(self)
        changed = sorted(cell_id(c) for c in res if c[3] in ("B1", "B2", "B2k2") and res[c]["outside_changed"])
        print("path matrix window cells that changed the outside tree (accepted residual, OQ-1/OQ-2/DP-1): %d" % len(changed))

    def test_pm_matrix_write_window(self):  # V18 (B3)
        descriptor_walk = hasattr(managed, "_open_parents")  # main's managed.py (PR 4d); the tree before it follows a link

        def check(c, r):
            why = self.window_invariants(c, r) if r["res"][1][0] != "exc" else None
            if r["res"][1][0] == "exc" and not (descriptor_walk and r["res"][1][1].startswith("_NotDirectory")):
                return "traceback %s" % r["res"][1][1]
            if descriptor_walk and r["outside_changed"]:
                return "outside changed"
            return why
        bad = self.verdicts(lambda c: c[3] == "B3", check)
        res = self.all_results(self)
        reached = sorted(cell_id(c) for c in res if c[3] == "B3" and res[c]["outside_changed"])
        print("path matrix B3 cells that wrote outside (descriptor walk %s): %d" % (descriptor_walk, len(reached)))
        self.assertEqual(bad, [])

    # ---- init entry
    def test_pm_matrix_names_index_init(self):  # V11 (I entry)
        def check(c, r):
            _tag, res, text = r["res"]
            if res != ("ok", 1) or "FAIL init.input: %s\n" % UTF8 not in text or r["root_changed"]:
                return "got %r %r" % (res, text[:200])
            return None
        self.assertEqual(self.verdicts(lambda c: c[0] == "I" and c[2] == "N1", check), [])

    def check_init(self, c, r):
        _e, sid, st, moment = c
        _tag, res, text = r["res"]
        slot = BY_ID[sid]
        if res[0] != "ok":
            return "init.main raised %r" % (res,)
        if r["viol"] or r["outside_changed"]:
            return "outside reached %r changed %r" % (r["viol"], r["outside_changed"])
        if slot.id in STATE_SLOTS or slot.group == "TGT" and False:
            return None  # recorded: the 4d.1 verdicts of the state directories (V9) are listed per cell, not asserted
        sw = (slot, st)
        conflicts = model_plan(sw)
        want_changes, want_notes = model_rewrites(sw)
        if conflicts:
            lines = ["FAIL init.conflict: %s\n" % t for t in conflicts]
            if moment == "C3":
                lines = ["FAIL init.migrate: %s" % "; ".join(conflicts)]
            if res[1] != 1 or any(line not in text for line in lines):
                return "exit %r want 1 with %r; text %r" % (res[1], conflicts, text[:300])
            if moment != "C3" and r["root_changed"]:
                return "a refused init wrote files"
            return None
        notes_shown = [] if moment == "C3" else want_notes  # init prints the notes of its first plan, never of the recompute
        if res[1] != 0 or any(n not in text for n in notes_shown):
            return "exit %r want 0 with notes %r; text %r" % (res[1], want_notes, text[:300])
        return None

    def test_pm_matrix_init_cells(self):  # V1..V8 through init (I entry), OQ-4 for I.C3
        self.assertEqual(self.verdicts(lambda c: c[0] == "I" and c[2] in STATES, self.check_init), [])

    def test_pm_matrix_named_review2_cells(self):  # P7: the cells review 2 found failing (R2A-1, -2, -3, -5, R2B-3, RB-1..RB-3)
        res = self.all_results(self)
        named = []
        for sid in ("SRC-spec", "SRC-plan"):  # R2A-1: src name (a UnicodeEncodeError at 0971c3b)
            named.append(("D", sid, "N2", "C2"))
        named += [("D", i, "N2", "C2") for i in ("SP-docs", "SP-sup", "SP-specs", "SP-plans", "SP-plansx")]  # src parent
        named += [("D", i, "N2", "C2") for i in ("TP-ds", "TP-dss", "TP-dsp", "TP-dspx")]  # dst parent
        named += [("D", i, "N2", "C2") for i in ("H-readme", "H-guide", "H-wf", "H-state", "HP-guide", "HP-gh", "HP-ghwf",
                                                 "HP-st", "HP-stst", "HP-dec")]  # changes path
        bad = ["%s: %s" % (cell_id(c), self.names_check(c, res[c])) for c in named if self.names_check(c, res[c])]
        for c in sorted(res):  # R2A-5: every device cell at C1 and C2 of the D entry
            if c[0] == "D" and c[2] == S9 and c[3] in ("C1", "C2") and not c[1].startswith("KEY-") and BY_ID[c[1]].group != "HP":
                why = self.check_any(c, res[c])
                if why:
                    bad.append("%s: %s" % (cell_id(c), why))
        for c in (("D", "TP-dss", S5, "B0"), ("D", "TP-ds", S4, "B0"), ("D", "TP-dss", S4, "B0")):  # R2A-2 dst-between-moves
            r = res[c]
            want = model_between_moves((BY_ID[c[1]], c[2]))
            if r["res"][1] != want or r["outside_changed"] or r["viol"]:
                bad.append("%s: got %r want %r outside %r" % (cell_id(c), r["res"][1], want, r["outside_changed"]))
        r = res[("D", "TP-ds", S5, "B1")]  # R2A-2 dst-parent-after-preflight: the symlink is met by mkdir, never written through
        if r["res"][1][0] != "err" or r["outside_changed"]:
            bad.append("D.TP-ds.S5.B1: got %r outside %r" % (r["res"][1], r["outside_changed"]))
        for c in (("D", "HP-guide", S5, "B3"), ("D", "SP-plans", S5, "B2"), ("D", "HP-guide", S5, "B4")):  # recorded windows
            if self.window_invariants(c, res[c]):
                bad.append("%s: %s" % (cell_id(c), self.window_invariants(c, res[c])))
        for c in (("D", "H-readme", S1, "B4"), ("D", "HP-guide", S1, "B4")):  # R2A-3
            if res[c]["res"][1] != ("ok", res[c]["res"][1][1]) or any("not read" in n for n in res[c]["res"][1][1][1]):
                bad.append("%s: got %r" % (cell_id(c), res[c]["res"][1][0]))
        for c in sorted(res):  # R2B-3 and RB-1..RB-3
            if c[0] == "I" and c[2] in (S5,) and c[3] in ("C1", "C2") or c[0] == "I" and c[2] == S2 and c[3] == "C1":
                why = self.check_init(c, res[c])
                if why:
                    bad.append("%s: %s" % (cell_id(c), why))
            if c[0] == "D" and c[3] == "C1" and (c[1].startswith("SP-") and c[2] == S5 or c[1].startswith("SRC-") and c[2] in (S3, S7, S8)):
                if not any("is not a directory" in t or "not a regular file" in t for t in res[c]["res"][1][1][1]):
                    bad.append("%s: no conflict" % cell_id(c))
        self.assertEqual(bad, [])
