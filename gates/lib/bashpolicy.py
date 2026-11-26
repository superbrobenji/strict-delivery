"""Policy of the Bash hook (Task 3b.2, standard library only): the text refusals that run first on every command, the
alias-aware git words, the git writes and their target check, and the refusals of a git commit.

Every text check folds ASCII letters only and reads the raw text AND the space-joined quote-removed words of
``shellscan.scan`` (controller ruling R1), so ``--no""-verify`` and ``deci""de`` do not hide a word. No ``str.lower``,
``casefold``, ``isprintable`` or any Unicode database call is made here, so the verdicts do not depend on the interpreter's
Unicode database (decision CD6). The reasons are fixed texts that state the way out (ruling R2) and never echo the
command. ``commit_refusals`` takes a ``Policy`` already built for the TARGET root (``pre_bash`` calls ``target_root``
first and builds that policy from the root it returns, decision CD2); ``git_call`` reads the git words once for both.
"""
from __future__ import annotations

import dataclasses
import os
from typing import Callable, Mapping, Optional

from gates.lib import gitinfo, shellscan
from gates.lib.result import GateError, Result, safe_text

COMMIT_WORDS = ("commit",)
PUSH_WORDS = ("push",)
MERGE_WORDS = ("merge", "pull")
# The git subcommands that write by name (ruling (3b)); branch, checkout and switch write by option (WRITE_OPTIONS).
GIT_WRITES = ("commit", "push", "merge", "pull", "rebase", "cherry-pick", "revert", "am", "reset", "update-ref",
              "tag", "stash", "worktree")
# Per subcommand: short option letters and long option names that create, move, copy, delete or force a ref (plan
# :3336, decision Q4: plus track, orphan and detach; a short cluster holding a letter and a unique long prefix count).
WRITE_OPTIONS = {
    "branch": ("cCmMdDft", ("copy", "move", "delete", "force", "track")),
    "checkout": ("bBft", ("force", "track", "orphan", "detach")),
    "switch": ("cCftd", ("create", "force-create", "force", "discard-changes", "track", "orphan", "detach")),
}
INHERITED_GIT_ENV = ("GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE")
HOME_NAMES = ("home", "xdg_config_home")
_BINDERS = ("export", "unset", "declare", "typeset", "readonly", "local", "read", "mapfile", "readarray", "getopts",
            "for", "select")
_ASSIGN_TARGET = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY")
_ENV_NAMES = tuple(sorted(shellscan._ALLOW))
_OK_OPTIONS = ("--no-pager", "-P")
_VALUE_OPTIONS = ("-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--config-env", "--attr-source")
_N_SHORT_VALUES = "mFcCt"
_N_LONG_VALUES = ("message", "file", "author", "date", "template", "reuse-message", "reedit-message", "fixup",
                  "squash", "cleanup", "pathspec-from-file", "trailer")
_LOWER = shellscan._LOWER
_TOKEN = shellscan._TOKEN_CLASS
_SEPARATORS = frozenset(";&|\n()")
_WAY = "run it with the ! prefix if you must, or ask the owner"
_BANG = "the human can run the command with the ! prefix"
_ASCII_ALNUM = frozenset("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
_NOT_UTF8 = "git diff --name-only gave output that is not valid UTF-8"  # gitinfo._text's error for the unstaged paths
UNSTAGED_REASON = "tracked file has unstaged changes; stage it or stash it, so the gates read the tree being committed"


@dataclasses.dataclass
class Policy:
    root: str
    cfg: Optional[dict]
    cfg_error: Optional[str]
    env: Mapping
    aliases: dict
    branch: Optional[str]
    base: str
    agent_key: str
    cwd: str
    state_access: Callable


def _fold(text: str) -> str:
    return text.translate(_LOWER)


def _views(text: str) -> list:
    """The raw text and the space-joined quote-removed words (ruling R1), each ASCII-folded."""
    return [_fold(text), _fold(" ".join(shellscan.scan(text).words))]


def _runs(text: str) -> list:
    """The tokens of ``text``: maximal runs of ``[0-9A-Za-z_-]``."""
    out = []
    cur = []
    for ch in text:
        if ch in _TOKEN:
            cur.append(ch)
        elif cur:
            out.append("".join(cur))
            cur = []
    if cur:
        out.append("".join(cur))
    return out


def _segments(view: str) -> list:
    """The token lists of the simple commands of one folded view (cut at ``; & | newline ( )``)."""
    out = []
    cur = []
    for ch in view:
        if ch in _SEPARATORS:
            out.append(_runs("".join(cur)))
            cur = []
        else:
            cur.append(ch)
    out.append(_runs("".join(cur)))
    return out


def _home_moved(view: str) -> bool:
    """Whether the folded ``view`` moves ``HOME`` or ``XDG_CONFIG_HOME``. Linear in the length of ``view`` (rows TX53,
    PB5, F-20261126-mqie): no slice of the text or of the tokens after the current one is made per occurrence or token."""
    for name in HOME_NAMES:
        at = view.find(name)
        while at >= 0:
            before = view[at - 1] if at > 0 else ""
            end = at + len(name)
            if before not in _TOKEN and (view.startswith("=", end) or view.startswith("+=", end)) and before != "$":
                return True
            at = view.find(name, at + 1)
    for seg in _segments(view):
        # One pass from the right: what the tokens after the current one hold (a name of HOME_NAMES; for ``env`` also a
        # ``-uNAME`` of it; for ``printf`` whether the first ``-v`` after it is followed by a name of HOME_NAMES).
        name_after = env_after = printf_after = False
        for n in range(len(seg) - 1, -1, -1):
            tok = seg[n]
            if (tok in _BINDERS and name_after) or (tok == "printf" and printf_after) or (tok == "env" and env_after):
                return True
            if tok in HOME_NAMES:
                name_after = env_after = True
            elif tok.startswith("-u") and tok[2:] in HOME_NAMES:
                env_after = True
            if tok == "-v":
                printf_after = n + 1 < len(seg) and seg[n + 1] in HOME_NAMES
    return False


def text_refusals(text: str, agent_id: Optional[str] = None) -> list:
    """The FAIL lines of the text checks (no config needed), in the order no-verify, hooks-path, git-config-env, home,
    decide; each id at most once."""
    shellscan._check_str(text, "text")
    views = _views(text)
    out = []
    if any(t.startswith("--no-v") for v in views for t in _runs(v)):
        out.append("FAIL hook.bash.bypass.no-verify: --no-verify and its abbreviations are refused; "
                   "the human can run the command with the ! prefix")
    if any("hookspath" in v for v in views):
        out.append("FAIL hook.bash.bypass.hooks-path: core.hooksPath is refused; the human can run the command with "
                   "the ! prefix")
    if any("git_config_" in v or "--config-env" in v for v in views):
        out.append("FAIL hook.bash.bypass.git-config-env: GIT_CONFIG_* and --config-env are refused; the human can "
                   "run the command with the ! prefix")
    if any(_home_moved(v) for v in views):
        out.append("FAIL hook.bash.bypass.home: moving HOME or XDG_CONFIG_HOME is refused; the human can run the "
                   "command with the ! prefix")
    if agent_id is not None and any("decision" in v and any(t in ("decide", "withdraw") for t in _runs(v))
                                    for v in views):
        out.append("FAIL hook.bash.decide: decisions decide and withdraw come only from the human, who runs them with "
                   "the ! prefix, or from the main session recording the owner's exact words (spec §7.1)")
    return out


def _check_aliases(aliases: object) -> dict:
    if type(aliases) is not dict:
        raise TypeError("aliases must be a dict")
    for k, v in aliases.items():
        if type(k) is not str or type(v) is not str:
            raise TypeError("aliases must map str to str")
    return aliases


def _words_of(text: str) -> set:
    return {w for w in COMMIT_WORDS + PUSH_WORDS + MERGE_WORDS if shellscan.token_in(text, w)}


def effective_words(text: str, aliases: dict) -> set:
    """The whole-token ``commit``, ``push``, ``merge`` and ``pull`` words of ``text`` that count (decisions Q2, R1): only
    when ``text`` also holds a ``git`` token (ASCII-folded); an alias name after it adds the words of its expansion
    (chains followed, cycles end), and an alias that starts with ``!`` adds ``commit``, ``push`` and ``merge``."""
    shellscan._check_str(text, "text")
    _check_aliases(aliases)
    found: set = set()
    for raw, view in zip((text, " ".join(shellscan.scan(text).words)), _views(text)):
        toks = _runs(view)
        if "git" not in toks:
            continue
        found |= _words_of(raw)
        seen: set = set()
        todo = [t for t in toks[toks.index("git") + 1:] if t in aliases]
        while todo:
            name = todo.pop()
            if name in seen:
                continue
            seen.add(name)
            expansion = aliases[name]
            if expansion.startswith("!"):
                found |= set(COMMIT_WORDS + PUSH_WORDS + MERGE_WORDS[:1])
                continue
            # R2-3: an expansion is read through both views as the command text is (ruling R1): `com""mit` holds `commit`
            for seen_view in (expansion, " ".join(shellscan.scan(expansion).words)):
                found |= _words_of(seen_view)
                todo.extend(t for t in _runs(_fold(seen_view)) if t in aliases)
    return found


def _basename(word: str) -> str:
    return word.rsplit("/", 1)[-1]


def _option_word(word: str) -> str:
    return word.split("=", 1)[0]


def is_git_write(sub: str, args) -> bool:
    """Whether the git subcommand ``sub`` (exact, case-sensitive; already alias-resolved) with ``args`` is a write.
    A ``sub`` that is not a ``str``, or ``args`` holding a non-``str`` word, raises ``TypeError``; an empty ``sub``
    raises ``GateError`` (the table's row GW13: a callable never receives them, the refusal is the fail-closed reading)."""
    if type(sub) is not str:
        raise TypeError("subcommand must be a str")
    if sub == "":
        raise GateError("an empty git subcommand")
    args = list(args)
    if any(type(word) is not str for word in args):
        raise TypeError("git words must be str")
    if sub in GIT_WRITES:
        return True
    if sub not in WRITE_OPTIONS:
        return False
    letters, longs = WRITE_OPTIONS[sub]
    for word in args:
        if word.startswith("--"):
            name = _option_word(word)[2:]
            if name and any(long.startswith(name) for long in longs):
                return True
        elif word.startswith("-") and len(word) > 1 and any(ch in letters for ch in word[1:]):
            return True
    return False


def write_option_in_text(views) -> bool:
    """Whether a text that is not one plain command (``views``: its raw text and its quote-removed words, ruling R1) holds
    ``branch``, ``checkout`` or ``switch`` followed, in the same simple command (cut at ``; & | newline ( )``), by one of that
    subcommand's create, move, copy, delete or force options: ``is_git_write`` over the words after it (R2-7, F-20261126-te2b;
    plan :3336 puts those forms in the git writes, :3659 'plain or not'). One pass over the words, linear in the text."""
    return any(_segment_writes(seg) for view in views for seg in _simple_commands(view))


def _simple_commands(view: str) -> list:
    """The word lists of the simple commands of ``view`` (cut at ``; & | newline ( )``, words split at a space or tab)."""
    out = []
    cur = []
    word = []
    for ch in view:
        if ch in _SEPARATORS:
            if word:
                cur.append("".join(word))
                word = []
            out.append(cur)
            cur = []
        elif ch in " \t":
            if word:
                cur.append("".join(word))
                word = []
        else:
            word.append(ch)
    if word:
        cur.append("".join(word))
    out.append(cur)
    return out


def _segment_writes(words: list) -> bool:
    """Whether one simple command's words hold a ``WRITE_OPTIONS`` subcommand word and, after it, a write option of it."""
    seen: set = set()
    for word in words:
        if word in WRITE_OPTIONS:
            seen.add(word)
        elif seen and word.startswith("-") and any(is_git_write(sub, [word]) for sub in seen):
            return True
    return False


@dataclasses.dataclass
class GitCall:
    """What the words of one plain command say about git: ``lines`` of steps 2-4 (not-git, index, target, global
    options), the ``-C`` directory, the alias-resolved subcommand and its words."""
    lines: list
    argv_C: Optional[str]
    sub: Optional[str]
    args: list
    expansion_words: list
    expansions: list = dataclasses.field(default_factory=list)  # the alias values followed, in order (R1-3)
    env_refused: bool = False  # the ``env`` wrapper was refused: an option, an operand off the allow-list, or a name that is
    #                            not ASCII (U1, F-20261126-ej5r); its not-git line stands for a git write too


def _env_unwrap(argv: tuple, lines: list) -> tuple:
    """``(argv after env, operands, refused)``: ``-i``, ``-u NAME`` and ``NAME=V`` only; other options and other names are
    refused (one level); ``refused`` is true for an option, an operand off the allow-list and an operand-shaped word
    (``NAME=V``, ``NAME`` not an ASCII identifier) that is not accepted."""
    n = 1
    operands = []
    while n < len(argv):
        word = argv[n]
        if word == "-i":
            n += 1
        elif word == "-u" and n + 1 < len(argv) and not operands:
            n += 2
        elif word.startswith("-"):
            lines.append("FAIL hook.bash.not-git: env option %s is refused; %s" % (safe_text(_option_word(word)), _WAY))
            return (), operands, True
        elif "=" in word and word[0] != "=" and all(ch in _ASCII_ALNUM or ch == "_" for ch in word.split("=", 1)[0]):
            name = word.split("=", 1)[0]  # ASCII only: no Unicode-database call (CD6, V2d)
            if name not in _ENV_NAMES:
                lines.append("FAIL hook.bash.not-git: env operand %s is refused; %s" % (safe_text(name), _WAY))
                return (), operands, True
            operands.append(name)
            n += 1
        else:
            return argv[n:], operands, "=" in word and word[0] != "="
    return argv[n:], operands, False


def _resolve(sub: str, rest: list, aliases: dict) -> tuple:
    """The alias-resolved ``(subcommand, words, expansions)``; the words of an expansion come first and ``expansions``
    holds each alias value followed, in order. A ``!`` alias gives ``None`` for the subcommand."""
    seen = set()
    extra: list = []
    followed: list = []
    while sub != "commit" and _fold(sub) in aliases and _fold(sub) not in seen:
        seen.add(_fold(sub))
        expansion = aliases[_fold(sub)]
        followed.append(expansion)
        if expansion.startswith("!"):
            return None, extra + rest, followed
        words = list(shellscan.scan(expansion).words)
        n = 0
        while n < len(words) and words[n].startswith("-"):
            n += 2 if words[n] in _VALUE_OPTIONS else 1
        if n >= len(words):
            return None, extra + rest, followed
        sub = words[n]
        extra = words[n + 1:] + extra
    return sub, extra + rest, followed


def git_call(scan, aliases: dict) -> Optional[GitCall]:
    """The reading of a plain command; ``None`` when it has no program word."""
    lines: list = []
    for name, _value in scan.assignments:
        if name == "GIT_INDEX_FILE":
            lines.append("FAIL hook.bash.index: GIT_INDEX_FILE is refused for a commit; %s" % _WAY)
        elif name in _ASSIGN_TARGET:
            lines.append("FAIL hook.bash.target: %s is refused; %s" % (name, _WAY))
    argv = scan.argv
    if not argv:
        return None
    program = argv
    operands: list = []
    env_refused = False
    if _basename(argv[0]) == "env":
        program, operands, env_refused = _env_unwrap(argv, lines)
        for name in operands:
            if name == "GIT_INDEX_FILE":
                lines.append("FAIL hook.bash.index: GIT_INDEX_FILE is refused for a commit; %s" % _WAY)
            elif name in _ASSIGN_TARGET:
                lines.append("FAIL hook.bash.target: %s is refused; %s" % (name, _WAY))
        if not program:
            return GitCall(lines, None, None, [], [], env_refused=env_refused)
    if _basename(program[0]) != "git":
        lines.append("FAIL hook.bash.not-git: the program is not git; %s" % _WAY)
        return GitCall(lines, None, None, [], [], env_refused=env_refused)
    words = list(program[1:])
    argv_C = None
    seen_option = False
    n = 0
    while n < len(words) and words[n].startswith("-"):
        word = words[n]
        if word == "-C":
            if n + 1 >= len(words) or seen_option or argv_C is not None:
                lines.append("FAIL hook.bash.global-option.-C: -C must be the first git option and take one "
                             "directory; %s" % _WAY)
                if argv_C is not None or seen_option:
                    lines.append("FAIL hook.bash.target: -C names more than one directory; %s" % _WAY)
            if n + 1 < len(words) and argv_C is None and not seen_option:
                argv_C = words[n + 1]
            n += 2
            continue
        if word not in _OK_OPTIONS:
            lines.append("FAIL hook.bash.global-option.%s: git option %s before the subcommand is refused; %s"
                         % (safe_text(_option_word(word)), safe_text(_option_word(word)), _WAY))
            if word in _VALUE_OPTIONS:
                n += 1
        seen_option = True
        n += 1
    if n >= len(words):
        return GitCall(lines, argv_C, None, [], [])
    sub, args, followed = _resolve(words[n], words[n + 1:], aliases)
    expansion = args[:len(args) - len(words[n + 1:])] if sub is not None else []
    return GitCall(lines, argv_C, sub, args, expansion, followed)


def n_flag(args) -> bool:
    """Whether the words of a ``commit`` hold ``-n`` as a short cluster (read left to right; the letters of
    ``_N_SHORT_VALUES`` take the rest of the cluster or the next word as a value, which is skipped; decision CD9: after
    ``--`` the words are still read)."""
    n = 0
    while n < len(args):
        word = args[n]
        n += 1
        if word.startswith("--"):
            name = _option_word(word)[2:]
            if "=" not in word and name and any(v.startswith(name) for v in _N_LONG_VALUES):
                n += 1
        elif word.startswith("-") and len(word) > 1:
            for k, ch in enumerate(word[1:]):
                if ch == "n":
                    return True
                if ch in _N_SHORT_VALUES:
                    if k == len(word) - 2:
                        n += 1
                    break
    return False


def target_root(scan, argv_C: Optional[str], p: Policy) -> tuple:
    """``(root, fails)``: the git top level of the named directory (``-C`` or the scanner's ``cd``, joined to
    ``cwd`` and ``realpath``ed), or of ``cwd``; ``root`` is ``None`` when ``fails`` is not empty. The top level must be one
    of the worktrees ``p.state_access()`` (the caller's ``worktrees.allowed`` pair plus its dispatch record) names; a
    ``-C`` together with ``cd`` is refused."""
    if argv_C is not None and scan.cd is not None:
        return None, ["FAIL hook.bash.target: -C and cd both name a directory; use one; %s" % _WAY]
    named = argv_C if argv_C is not None else scan.cd
    if named == "":
        return None, ["FAIL hook.bash.target: an empty directory has no git top level; %s" % _WAY]
    where = p.cwd if named is None else os.path.join(p.cwd, named)
    try:
        top = os.path.realpath(gitinfo.toplevel(os.path.realpath(where)))
    except GateError:
        return None, ["FAIL hook.bash.target: %s has no git top level; %s" % (safe_text(where), _WAY)]
    tops, why, _record = p.state_access()
    if top in tops:
        return top, []
    fails = ["FAIL hook.bash.target: %s is not a worktree this caller may write in (allowed: %s); %s"
             % (safe_text(top), ", ".join(safe_text(t) for t in sorted(tops)) or "none", _WAY)]
    return None, fails + ["FAIL hook.bash.target: %s; %s" % (safe_text(w), _WAY) for w in why]


def _has_word(text: str, word: str) -> bool:
    return any(word in _runs(view) for view in _views(text))


def _alias_names_after_git(text: str, aliases: dict) -> list:
    """The alias names held after the first ``git`` token of either view of ``text``, in order."""
    out = []
    for view in _views(text):
        toks = _runs(view)
        if "git" in toks:
            out.extend(t for t in toks[toks.index("git") + 1:] if t in aliases)
    return out


def _reached_texts(body: str, aliases: dict) -> list:
    """The texts of the alias values a ``!`` alias ``body`` names (the git alias names after its ``git`` token, R2-2), chains
    followed through plain values (every alias name they hold) and ``!`` values (the names after their ``git`` token);
    cycles end. A leading ``!`` is cut from each text."""
    out: list = []
    seen: set = set()
    todo = _alias_names_after_git(body, aliases)[::-1]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        value = aliases[name]
        if value.startswith("!"):
            out.append(value[1:])
            todo.extend(reversed(_alias_names_after_git(value[1:], aliases)))
        else:
            out.append(value)
            for view in _views(value):
                todo.extend(t for t in reversed(_runs(view)) if t in aliases)
    return out


def _alias_lines(call: GitCall, p: Policy, out: list) -> list:
    """The lines for the alias values ``call`` followed (R1-3, plan :3697, table CD7): each value, plain or ``!``, is read
    by every ``text_refusals`` member as the command text is; a ``!`` value that reaches a ``commit`` word, in its own text
    or in the value of a git alias it names (R2-2, chains followed, cycles end; both views), is refused, since the shell
    command it runs cannot be checked, and its ``-n`` is read as the command's is. ``out`` holds the lines of the earlier
    steps: an alias ``--no-verify`` line is not added beside a ``no-verify`` line of ``out``."""
    agent = None if p.agent_key == "session" else p.agent_key
    lines: list = []

    def add(line: str) -> None:
        if line not in lines:
            lines.append(line)
    for value in call.expansions:
        shell = value.startswith("!")
        body = value[1:] if shell else value
        texts = [body] + (_reached_texts(body, p.aliases) if shell else [])
        for text in texts:
            for line in text_refusals(text, agent):
                if line.split(":", 1)[0].endswith(".no-verify"):
                    if not any("no-verify" in ln for ln in out):
                        add("FAIL hook.bash.bypass.no-verify: an alias holds --no-verify; " + _BANG)
                else:
                    add(line)
        if shell and any(_has_word(text, "commit") for text in texts):
            if any(n_flag(list(shellscan.scan(text).words)) for text in texts):
                add("FAIL hook.bash.bypass.n-flag: git commit -n skips the hooks; " + _BANG)
            add("FAIL hook.bash.alias: a git alias that runs a shell command holding commit is refused, its commit "
                "cannot be checked; " + _BANG)
    return lines


def _unstaged_paths(root: str) -> list:
    """``gitinfo.unstaged_paths(root)``; when that raises (a tracked path whose name is not UTF-8, row HR6, is the only
    cause git's own success hides), the same ``git diff --name-only -z`` is read as bytes and each name decoded with
    ``surrogateescape``, so ``safe_text`` shows it as ``\\udcXX`` and the other paths stay listed (R1-6). A second
    failure raises the first error. Any other first error (a root that is not the top level, a git failure) is raised as it
    is (R2-1)."""
    try:
        return gitinfo.unstaged_paths(root)
    except GateError as first:
        if str(first) != _NOT_UTF8:
            raise
        try:
            p = gitinfo._run(root, "diff --name-only", ["diff", "--no-color", "--name-only", "-z", "--no-ext-diff",
                                                        "--no-textconv", "--ignore-submodules=none"],
                             opts=gitinfo.FSMONITOR_OFF)
        except GateError:
            raise first from None
        return [raw.decode("utf-8", "surrogateescape") for raw in p.stdout.split(b"\0") if raw]


def commit_refusals(text: str, p: Policy, run_gates: Callable, stop: bool = False) -> list:
    """The FAIL lines for a text whose ``effective_words`` hold ``commit``, in the plan's order (steps 1 to 8). A text
    that is not plain gives the ``compound`` line alone; steps 7 and 8 run only when no earlier step refused, the gates
    only when the unstaged check found nothing; ``run_gates`` is never called after a refusal. ``stop`` (the target was
    refused, so ``p`` is not the target's policy) returns after step 5, before the config, unstaged and gate steps."""
    shellscan._check_str(text, "text")
    if "commit" not in effective_words(text, p.aliases):
        return []
    scan = shellscan.scan(text)
    if not scan.plain:
        return ["FAIL hook.bash.compound: git commit runs as its own command (%s); %s" % (safe_text(scan.reason), _WAY)]
    out: list = []
    for name in INHERITED_GIT_ENV:
        if name in p.env:
            out.append("FAIL hook.bash.target: the hook inherited %s; %s" % (name, _WAY))
    call = git_call(scan, p.aliases)
    if call is None:
        return out
    out = call.lines + out
    if call.sub == "commit":
        if n_flag(call.args) or n_flag(call.expansion_words):
            out.append("FAIL hook.bash.bypass.n-flag: git commit -n skips the hooks; the human can run the command "
                       "with the ! prefix")
    out = out + _alias_lines(call, p, out)
    if stop:
        return out
    if p.cfg_error is not None:
        out.append("FAIL hook.bash.config: %s; no commit runs until the config loads; fix the config file, or %s"
                   % (safe_text(p.cfg_error), _BANG))
    if out:
        return out
    try:
        paths = _unstaged_paths(p.root)
    except GateError as e:
        return ["FAIL hook.bash.gates: %s; %s" % (safe_text(e), _BANG)]
    paths = list(dict.fromkeys(paths))  # an unmerged path is listed twice by git diff: one line per path (CD10)
    if paths:
        return ["FAIL hook.bash.unstaged: %s: %s" % (safe_text(path), UNSTAGED_REASON) for path in paths]
    try:
        result = run_gates(p.root)
    except GateError as e:
        return ["FAIL hook.bash.gates: %s; %s" % (safe_text(e), _BANG)]
    if not isinstance(result, Result):
        return ["FAIL hook.bash.gates: the gate runner returned no result; " + _BANG]
    return ["FAIL hook.bash.gates: %s: %s" % (safe_text(ln.id), safe_text(ln.reason))
            for ln in result.lines if ln.status == "FAIL"]
