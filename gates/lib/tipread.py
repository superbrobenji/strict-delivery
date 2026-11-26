"""One read of a file at a ref that never takes a non-regular entry for an absent one (Task 5b.3, class "non-regular
entry at a branch tip read as absent", owner answer Q-RC9-1 (a)). ``gitinfo.show`` returns ``None`` for a symlink, a
tree and a gitlink as it does for a missing path; a caller that treats ``None`` as "no file" then skips the entry.

Every read here is in ONE view, the one ``gitinfo.show``, ``gitinfo.blob_exists`` and ``gitinfo.ls_tree`` read on main:
a ``refs/replace`` ref is honoured (no ``--no-replace-objects``; D-A16 confines that option to the merge-policy history
readers). Task 5b.3 fix round 4, F-20261126-a826."""
import os
from typing import Optional

from gates.lib import gitinfo
from gates.lib.result import GateError


def show_file(root: str, ref: str, path: str) -> Optional[str]:
    """The UTF-8 text of the regular entry (``100644`` or ``100755``) at ``path`` in ``ref``; ``None`` when no entry
    is at ``path`` (a missing path, or a path below a symlink: git does not follow one); any other entry (symlink
    ``120000``, tree ``040000``, gitlink ``160000``) is a ``GateError`` naming ``<ref>:<path>``, as the working tree
    refuses it. The entry kind comes from a listing of the entry itself (``_mode``); only a regular entry is then
    read, through ``gitinfo.show``, in the same view."""
    if _mode(root, ref, path) is None:
        return None
    text = gitinfo.show(root, ref, path)
    if text is None:
        raise GateError("%s:%s: changed while it was being read" % (ref, path))
    return text


def is_file(root: str, ref: str, path: str) -> bool:
    """True for a regular entry at ``path`` in ``ref``, False when no entry is there; a symlink, tree or gitlink is the
    ``GateError`` of ``show_file``. A probe of the mode only: the blob is never read or decoded, as
    ``gitinfo.blob_exists`` on main (F28, F29; F-20261126-swwg)."""
    return _mode(root, ref, path) is not None


def _mode(root: str, ref: str, path: str) -> Optional[str]:
    """The mode of the regular entry at ``path`` in ``ref``, ``None`` when no entry is there; any other entry kind is
    refused by name. ``path`` is an exact ``str`` (owner Q-RS4-1 (A), F-20261126-yyqv). The kind comes from the listing
    of ``path`` itself (a literal pathspec, as ``gitinfo.show`` lists it on main), matched by its raw name against the
    bytes git was given (``os.fsencode``), so the verdict depends only on the entry's own kind and bytes: no other name
    is decoded, and the entry's own name is decoded as ``gitinfo.show`` decodes it (F-20261126-g6un)."""
    if type(path) is not str:
        raise GateError("path must be a string")
    gitinfo._check_norm(path, "ls-tree: path", allow_empty=True)
    gitinfo._need_root(root)
    gitinfo._need_revision(ref, "ref")
    gitinfo._require_toplevel(root)
    mode = None
    for entry_mode, _, name in _listing(root, ref, path):
        if name == os.fsencode(path):
            gitinfo._text(name, "ls-tree")
            mode = entry_mode
    if mode is not None and mode not in gitinfo._REGULAR:
        raise GateError("%s:%s: cannot be read as a UTF-8 regular file (not a regular file)" % (ref, path))
    return mode


def entries(root: str, ref: str, directory: str) -> list:
    """Every entry directly under ``directory`` at ``ref`` as ``(mode, type, path)``, with the checks and the parse of
    ``gitinfo.ls_tree_entries`` (D-A9), but in the replace-honoured view of the module docstring (that function passes
    ``--no-replace-objects``). A ``directory`` that is no folder at ``ref`` gives ``[]``; ``""`` is the root."""
    gitinfo._need_root(root)
    gitinfo._need_revision(ref, "ref")
    if type(directory) is not str:
        raise GateError("directory must be a string")
    gitinfo._require_toplevel(root)
    gitinfo._check_norm(directory, "ls-tree: directory", allow_empty=True)
    return [(mode, kind, gitinfo._text(name, "ls-tree"))
            for mode, kind, name in _listing(root, ref, directory + "/" if directory else "")]


def _listing(root: str, ref: str, spec: str) -> list:
    """``git ls-tree -z --full-tree <ref> [-- <spec>]`` (a literal pathspec; none for ``""``) in the replace-honoured
    view, parsed as ``gitinfo.ls_tree_entries`` parses it, as ``(mode, type, name)`` with each name left as git's
    bytes. The caller has checked ``root``, ``ref`` and ``spec``."""
    args = ["ls-tree", "-z", "--full-tree", ref] + (["--", spec] if spec else [])
    p = gitinfo._run(root, "ls-tree", args, literal=True)
    out = []
    for raw in p.stdout.split(b"\0"):
        if not raw:
            continue
        head, _, name = raw.partition(b"\t")
        fields = head.split(b" ")
        if len(fields) != 3:
            raise GateError("git ls-tree gave an entry that cannot be read")
        out.append((fields[0].decode("ascii"), fields[1].decode("ascii"), name))
    return out
