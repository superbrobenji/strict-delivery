"""Fixture helper of the 5b.3 class "non-regular entry at a branch tip read as absent": commit one entry of a given kind
at a path on a branch, through a throwaway index, so the working tree and the real index are never touched."""
import os
import posixpath
import tempfile

from tests.helpers import git

# the three non-regular kinds (name, git mode) every member test runs, as the table section F states
BAD_KINDS = (("symlink", "120000"), ("tree", "040000"), ("gitlink", "160000"))


def refusal(ref: str, path: str) -> str:
    """The text of gitinfo.show_file for a non-regular entry (table section F, written by hand, not read from code)."""
    return "%s:%s: cannot be read as a UTF-8 regular file (not a regular file)" % (ref, path)


def set_entry(root: str, ref: str, path: str, kind: str, text: str = "x\n", message: str = "entry") -> str:
    """Commit onto ``ref`` (a full ref name, e.g. ``refs/heads/main``; created from HEAD when absent) the entry
    ``path`` as ``kind``: ``regular``, ``executable``, ``non-utf8``, ``absent``, ``symlink`` (to a regular file holding
    ``text``, so a follower would read it), ``tree`` (a directory holding a file with ``text``) or ``gitlink``.
    Returns the new commit id."""
    with tempfile.TemporaryDirectory() as td:
        env = {"GIT_INDEX_FILE": os.path.join(td, "index")}

        def blob(data: bytes) -> str:
            f = os.path.join(td, "blob")
            with open(f, "wb") as fh:
                fh.write(data)
            return git(root, "hash-object", "-w", f, env=env)

        def put(mode: str, sha: str, name: str) -> None:
            git(root, "update-index", "--add", "--cacheinfo", "%s,%s,%s" % (mode, sha, name), env=env)

        parent = git(root, "rev-parse", "--verify", "-q", ref, check=False) or git(root, "rev-parse", "HEAD")
        git(root, "read-tree", parent, env=env)
        git(root, "rm", "--cached", "-q", "-r", "-f", "--ignore-unmatch", "--", path, env=env)
        data = text.encode("utf-8")
        if kind in ("regular", "executable"):
            put("100755" if kind == "executable" else "100644", blob(data), path)
        elif kind == "non-utf8":
            put("100644", blob(b"\xff\xfe\n"), path)
        elif kind == "symlink":
            target = "_tip_target/" + path.replace("/", "__")
            put("100644", blob(data), target)
            put("120000", blob(posixpath.relpath(target, posixpath.dirname(path) or ".").encode("utf-8")), path)
        elif kind == "tree":
            put("100644", blob(data), path + "/inner")
        elif kind == "gitlink":
            put("160000", "a" * 40, path)
        elif kind != "absent":
            raise AssertionError("unknown kind " + kind)
        tree = git(root, "write-tree", env=env)
        new = git(root, "commit-tree", tree, "-p", parent, "-m", message)
        git(root, "update-ref", ref, new)
        return new
