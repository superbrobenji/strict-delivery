"""One read of a file at a ref that never takes a non-regular entry for an absent one (Task 5b.3, class "non-regular
entry at a branch tip read as absent", owner answer Q-RC9-1 (a)). ``gitinfo.show`` returns ``None`` for a symlink, a
tree and a gitlink as it does for a missing path; a caller that treats ``None`` as "no file" then skips the entry."""
from typing import Optional

from gates.lib import gitinfo
from gates.lib.result import GateError


def show_file(root: str, ref: str, path: str) -> Optional[str]:
    """The UTF-8 text of the regular entry (``100644`` or ``100755``) at ``path`` in ``ref``; ``None`` when no entry
    is at ``path`` (a missing path, or a path below a symlink: git does not follow one); any other entry (symlink
    ``120000``, tree ``040000``, gitlink ``160000``) is a ``GateError`` naming ``<ref>:<path>``, as the working tree
    refuses it. The entry kind comes from the listing of the parent folder (``gitinfo.ls_tree_entries``, which never
    follows a symlink); only a regular entry is then read, through ``gitinfo.show``."""
    gitinfo._check_norm(path, "ls-tree: path", allow_empty=True)
    mode = None
    for entry_mode, _, name in gitinfo.ls_tree_entries(root, ref, path.rpartition("/")[0]):
        if name == path:
            mode = entry_mode
    if mode is None:
        return None
    if mode not in gitinfo._REGULAR:
        raise GateError("%s:%s: cannot be read as a UTF-8 regular file (not a regular file)" % (ref, path))
    text = gitinfo.show(root, ref, path)
    if text is None:
        raise GateError("%s:%s: changed while it was being read" % (ref, path))
    return text
