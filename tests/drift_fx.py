"""Fixture repositories for the Task 5c.2 tests (``tests/test_gate_drift.py``, ``tests/test_drift_cli.py``): programs built
with real git commands and literal program files; no ``drift`` or ``programs`` helper decides an expected value."""
import contextlib
import io
import os
import hashlib

from gates.lib import yamlsub
from tests.helpers import GitIsolatedTestCase, commit_all, git, make_repo, minimal_config

P = "20261101-x"
P2 = "20261102-y"
PD = ".strict-delivery/state/programs"
PS = ".strict-delivery/state/plans"
HEADERS = ["stream", "block", "branch", "worktree", "next task", "estimate", "used", "status", "blockers",
           "pending decisions", "delivers"]
MERGED_HEAD = "<!-- schema: merged-log/1 -->\n"
SYNC_HEAD = "<!-- schema: sync-log/1 -->\n"
RID = "R-20261101-aaaa"


def mkrow(p, s, status="running", **kw):
    r = {"stream": s, "block": "5c", "branch": "%s/%s/main" % (p, s), "worktree": "../w/%s/%s/main" % (p, s),
         "next task": "5c.1", "estimate": "10", "used": "1", "status": status, "blockers": "none",
         "pending decisions": "none", "delivers": "x"}
    if status == "ready":
        r["block"] = r["next task"] = "none"
    r.update(kw)
    return r


def page(rows):
    lines = ["<!-- schema: status/1 -->", "", "| " + " | ".join(HEADERS) + " |", "|" + "---|" * len(HEADERS)]
    lines += ["| " + " | ".join(r[h] for h in HEADERS) + " |" for r in rows]
    return "\n".join(lines) + "\n"


def streams_text(p, sids, stacked=None, program=None):
    sts = []
    for n, s in enumerate(sids, 1):
        d = {"id": s, "purpose": "p", "plan": "docs/strict-delivery/plans/%s-plan.md" % s, "estimate": 5, "depends_on": [],
             "merge_order": n, "owns": [s + "-owned.py"]}
        if stacked and s in stacked:
            d["stacked_on"] = stacked[s]
        sts.append(d)
    return yamlsub.emit({"schema": "streams/1", "program": program or p, "plan": "docs/strict-delivery/plans/program-plan.md",
                         "specs": [], "worktrees": "../w", "streams": sts, "shared": []})


def handoff_text(p, sid, head, **over):
    f = {"schema": "handoff/1", "plan": "docs/strict-delivery/plans/%s-plan.md" % sid, "spec": "[]",
         "branch": "%s/%s/main" % (p, sid), "ledger": ".strict-delivery/state/plans/%s-plan/ledger.md" % sid,
         "block": "5c", "next_task": "5c.1", "head": head, "open_decisions": "[]", "questions": "[]"}
    f.update(over)
    f["resume"] = "'Resume strict-delivery plan %s at %s; branch %s; head %s; open questions: none.'" % (
        f["plan"], f["next_task"], f["branch"], f["head"])
    return "---\n" + "".join("%s: %s\n" % (k, v) for k, v in f.items()) + "---\nbody\n"


def request_text(rid=RID, status="open", **kw):
    r = {"schema": "request/1", "id": rid, "from_stream": "a", "to_stream": "b", "files": ["b-owned.py"],
         "interface": "docs/x.md#y", "need": "n", "status": status, "raised_at": {"sha": "a" * 7, "by": "a"}}
    if status == "done":
        r["resolution"] = {"commits": ["b" * 7], "at": "b" * 7, "by": "b"}
    r.update(kw)
    return yamlsub.emit(r)


def snapshot(root):
    """Every path under ``root`` (the ``.git`` directory included) with the sha256 of its bytes."""
    out = {}
    for d, dirs, files in os.walk(root):
        for n in dirs + files:
            path = os.path.join(d, n)
            if os.path.isfile(path) and not os.path.islink(path):
                with open(path, "rb") as fh:
                    out[path] = hashlib.sha256(fh.read()).hexdigest()
            else:
                out[path] = "-"
    return out


class Fx(GitIsolatedTestCase):
    """``self.root``: a repository on ``main`` with the config committed. ``prog`` and ``sbranch`` add programs and streams."""

    def setUp(self):
        super().setUp()
        self.root = make_repo(self.work, minimal_config())

    def put(self, rel, text, root=None):
        path = os.path.join(root or self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)

    def rev(self, ref):
        return git(self.root, "rev-parse", ref)

    def prog(self, p=P, sids=("a",), rows=None, status_text=None, streams=None, requests=None, stacked=None, files=None,
             start="main"):
        """The program ``p`` on ``<p>/integration`` cut from ``start``: files written and committed there; HEAD back on main."""
        git(self.root, "checkout", "-q", "-B", p + "/integration", start)
        d = "%s/%s" % (PD, p)
        self.put(d + "/streams.yml", streams if streams is not None else streams_text(p, sids, stacked))
        self.put(d + "/status.md", status_text if status_text is not None else page(
            rows if rows is not None else [mkrow(p, s) for s in sids]))
        self.put(d + "/sync-log.md", SYNC_HEAD)
        self.put(d + "/merged.md", MERGED_HEAD)
        for rid, text in (requests or {}).items():
            self.put("%s/requests/%s.yml" % (d, rid), text)
        for rel, text in (files or {}).items():
            self.put(rel, text)
        tip = commit_all(self.root, "program " + p)
        git(self.root, "checkout", "-q", "main")
        return tip

    def sbranch(self, p, s, start="main", head=None, extra=True, **over):
        """The stream branch ``<p>/<s>/main``: one work commit and the handoff naming it (or ``head``). Returns the tip."""
        git(self.root, "checkout", "-q", "-B", "%s/%s/main" % (p, s), start)
        self.put("%s-%s-work.txt" % (p, s), "w\n")
        work = commit_all(self.root, "work %s %s" % (p, s))
        self.put("%s/%s-plan/handoff.md" % (PS, s), handoff_text(p, s, head or work, **over))
        tip = commit_all(self.root, "handoff %s %s" % (p, s))
        git(self.root, "checkout", "-q", "main")
        return tip

    def commit_on(self, branch, files, msg="c"):
        git(self.root, "checkout", "-q", branch)
        for rel, text in files.items():
            self.put(rel, text)
        sha = commit_all(self.root, msg)
        git(self.root, "checkout", "-q", "main")
        return sha

    def merge_main_into(self, *branches):
        for b in branches:
            git(self.root, "checkout", "-q", b)
            git(self.root, "merge", "-q", "--no-ff", "-m", "sync", "main")
        git(self.root, "checkout", "-q", "main")

    def insync(self, p=P, sid="a", **over):
        """Program ``p`` with one running stream branch ``sid`` in sync with main."""
        self.sbranch(p, sid)
        self.prog(p, (sid,), rows=[mkrow(p, sid, **over)])

    def worktree(self, name, ref):
        path = os.path.join(self.tmp, "wt-" + name)
        git(self.root, "worktree", "add", "-q", path, ref)
        return path

    def remote(self):
        """A bare remote ``origin`` holding main; ``main`` tracks it. Returns the bare path."""
        bare = os.path.join(self.tmp, "remote.git")
        git(self.tmp, "init", "-q", "--bare", "-b", "main", bare)
        git(self.root, "remote", "add", "origin", bare)
        git(self.root, "push", "-q", "-u", "origin", "main")
        return bare

    def advance_remote(self, bare):
        other = os.path.join(self.tmp, "other")
        git(self.tmp, "clone", "-q", bare, other)
        git(other, "config", "user.email", "o@example.invalid")
        git(other, "config", "user.name", "O")
        self.put("remote-only.txt", "r\n", root=other)
        commit_all(other, "remote advance")
        git(other, "push", "-q", "origin", "main")

    def run_main(self, module_main, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = module_main(list(argv))
        return out.getvalue(), err.getvalue(), code
