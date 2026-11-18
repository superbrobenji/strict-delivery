"""Merge-policy checks of one ``MERGED`` line against git (Task P2.1 part i; specified under Task P3.1).

``merged_errors`` is the only public name here: Task P3.1 adds ``MODES`` and ``agent_may_merge`` beside it. Standard
library only, and no Unicode property or case method is read.
"""
from __future__ import annotations

import re
from typing import List

from gates.lib import gitinfo
from gates.lib.result import GateError, GitNotFound

_SLUG = re.compile(r"[a-z0-9][a-z0-9-]*")
_HEX40 = re.compile(r"[0-9a-f]{40}")
_MODES = ("host", "controller")
_APPROVALS = ("host", "chat")
_MAX_PR = 10 ** 600  # a pr is at most 600 digits (Task P1.2, decision D-Q26); no str() of a longer number is made


def _cfg_text(cfg: dict, *keys: str) -> str:
    node: object = cfg
    for k in keys:
        if type(node) is not dict or k not in node:
            raise GateError("cfg: %s is missing" % ".".join(keys))
        node = node[k]
    if type(node) is not str or node == "":
        raise GateError("cfg: %s must be a non-empty string" % ".".join(keys))
    return node


def _positive_int(v: object) -> bool:
    return type(v) is int and 1 <= v < _MAX_PR


def _need_line(line: object) -> None:
    """``ValueError`` naming the first thing wrong with ``line`` (decision D-A17; the keys of
    ``checkpoints.merged_lines``)."""
    if type(line) is not dict:
        raise ValueError("merged_errors: line must be a mapping")
    for key in ("pr", "head", "merge", "approval"):
        if key not in line:
            raise ValueError("merged_errors: line has no '%s'" % key)
    if not _positive_int(line["pr"]):
        raise ValueError("merged_errors: line pr must be an integer of 1 to 600 digits")
    for key in ("head", "merge"):
        v = line[key]
        if type(v) is not str or not _HEX40.fullmatch(v):
            raise ValueError("merged_errors: line %s must be 40 lowercase hex digits" % key)
    if type(line["approval"]) is not str or line["approval"] not in _APPROVALS:
        raise ValueError("merged_errors: line approval must be host or chat")
    if line["approval"] == "chat":
        if "approval_pr" not in line or not _positive_int(line["approval_pr"]):
            raise ValueError("merged_errors: a chat line needs approval_pr, an integer of 1 to 600 digits")
        if "approval_head" not in line or type(line["approval_head"]) is not str:
            raise ValueError("merged_errors: a chat line needs approval_head, a string")


def _merge_problem(root: str, base: str, merge: str) -> tuple:
    """``(reason, parents)``: ``reason`` is ``""`` when ``merge`` is a commit with exactly two parents on the
    first-parent history of the local branch ``base``."""
    hint = "update %s from the remote" % base
    if base not in gitinfo.local_branches(root):
        return "%s is not a local branch; %s" % (base, hint), []
    ref = "refs/heads/" + base  # the full name: a tag called like the branch is never read (decision D-A23)
    try:
        if not gitinfo.commit_exists(root, merge):
            return "%s is not a commit in this repository; %s" % (merge, hint), []
        parents = gitinfo.parents(root, merge)
        if len(parents) == 0:
            return "%s has no parents (a root commit, or the clone is shallow); %s" % (merge, hint), parents
        if len(parents) != 2:
            return ("%s has %d parent(s), and a pull request merge commit has exactly two (a squash, a rebase or an "
                    "octopus merge is refused)" % (merge, len(parents))), parents
        history = gitinfo.rev_list(root, parents[0], ref, first_parent=True)
    except GitNotFound:
        raise
    except GateError:
        return "git cannot read the history of %s (a shallow or incomplete clone?); %s" % (base, hint), []
    if merge not in history:
        return "%s is not on the first-parent history of %s; %s" % (merge, base, hint), parents
    return "", parents


def merged_errors(root: str, cfg: dict, plan: str, line: dict) -> List[tuple]:
    """``(suffix, reason)`` for one ``MERGED`` line of plan slug ``plan`` (Task P3.1's specification, built by Task
    P2.1; decisions D-A17, D-A18, D-A23). The suffix is ``<rule>.<pr>``; the rules run in this order:

    * ``merge``: ``line["merge"]`` is a commit with exactly two parents on the first-parent history of the local
      ``base_branch``; a commit or branch not found locally says ``update <base_branch> from the remote``;
    * ``head``: the merge commit's second parent is ``line["head"]``;
    * ``plan``: the merge's own diff from its first parent changes at least one path under
      ``<paths.plan_state>/<plan>/`` (the paths of a rename count on both sides);
    * ``approval``: ``chat`` in ``controller`` mode and ``host`` in ``host`` mode; for ``chat`` the named pr and head
      equal the line's.

    A failing ``merge`` rule returns it with the ``approval`` result only, since the merge commit is then not reliable
    (``head`` and ``plan`` read it). A wrong argument type is a ``ValueError``; a bad ``root`` or ``cfg`` a GateError.
    All compares are exact (no prefix of a sha, no case folding); the ``plan`` prefix is compared byte-wise at a ``/``.

    What the checks prove: that a merge commit for the recorded head exists on the base branch and touched this plan's
    workspace, and, in controller mode, that the recorded approval named that pull request and head. They cannot prove
    the owner said the words. Stated limit (D-A17): a merge of the base branch into a topic branch, fast-forwarded into
    the base branch, is a merge commit on its first-parent line whose second parent is an old base commit; a line
    naming it passes."""
    if type(root) is not str or root == "":
        raise GateError("root must be a string")
    base = _cfg_text(cfg, "base_branch")
    mode = _cfg_text(cfg, "merge", "mode")
    plan_state = _cfg_text(cfg, "paths", "plan_state")
    if mode not in _MODES:
        raise GateError("cfg: merge.mode must be one of host, controller")
    if type(plan) is not str or not _SLUG.fullmatch(plan):
        raise ValueError("merged_errors: plan must be a plan slug of a-z, 0-9 and '-'")
    _need_line(line)
    pr = line["pr"]
    out: List[tuple] = []
    problem, parents = _merge_problem(root, base, line["merge"])
    if problem:
        out.append(("merge.%d" % pr, problem))
    else:
        if parents[1] != line["head"]:
            out.append(("head.%d" % pr, "the second parent of %s is %s, not the recorded head %s"
                        % (line["merge"], parents[1], line["head"])))
        prefix = plan_state + "/" + plan + "/"
        if not any(p.startswith(prefix) for p in gitinfo.changed_paths(root, line["merge"] + "^1", line["merge"])):
            out.append(("plan.%d" % pr, "the merge %s changes no path under %s: it is not a pull request of plan %s"
                        % (line["merge"], prefix, plan)))
    want = "chat" if mode == "controller" else "host"
    if line["approval"] != want:
        out.append(("approval.%d" % pr, "approval is %s, and merge.mode %s needs %s" % (line["approval"], mode, want)))
    elif want == "chat":
        wrong = [what for what, got, rec in (("pr", line["approval_pr"], pr), ("head", line["approval_head"], line["head"]))
                 if got != rec]
        if wrong:
            out.append(("approval.%d" % pr, "the chat approval names another %s than the line's pr and head"
                        % " and ".join(wrong)))
    return out
