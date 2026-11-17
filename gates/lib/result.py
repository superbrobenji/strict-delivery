"""Gate result contract: PASS/FAIL lines, the run wrapper, argument parsing, repo root (standard library only)."""
from __future__ import annotations

import argparse
import ast
import builtins
import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Optional

from gates.lib import print_table
from gates.lib.yamlsub import MAX_DEPTH  # owner Q-R6R-2 (b): the renderer's nesting cap is the plan's MAX_DEPTH


class GateError(Exception):
    """A problem with a gate's input or environment; the message is the FAIL reason."""


class GitNotFound(GateError):
    """git is not on PATH (no repository hint can help)."""


@dataclass
class Line:
    status: str
    id: str
    reason: str = ""


def safe_text(s: object) -> str:
    """``s`` as one line: a backslash becomes ``\\\\`` and every non-printable character is escaped
    (``\\n``, ``\\xNN``, ``\\uNNNN``, ``\\UNNNNNNNN``), so the output is unambiguous."""
    text = _exact(s) if issubclass(type(s), str) else _exact(str(s))  # type(), never __class__ (Q-1C0R5-1 (a))
    out = []
    for c in text:
        if c == "\\":
            out.append("\\\\")
        elif print_table.is_printable(c):
            out.append(c)
        elif c == "\n":
            out.append("\\n")
        elif c == "\r":
            out.append("\\r")
        elif c == "\t":
            out.append("\\t")
        elif ord(c) <= 0xFF:
            out.append("\\x%02x" % ord(c))
        elif ord(c) <= 0xFFFF:
            out.append("\\u%04x" % ord(c))
        else:
            out.append("\\U%08x" % ord(c))
    return "".join(out)


@dataclass
class Result:
    gate: str
    lines: list = field(default_factory=list)

    def ok(self) -> bool:
        return bool(self.lines) and all(ln.status == "PASS" for ln in self.lines)

    def fail(self, id: str, reason: str) -> None:
        self.lines.append(Line("FAIL", id, reason))

    def passed(self, id: str) -> None:
        self.lines.append(Line("PASS", id))

    def render(self, as_json: bool) -> str:
        if as_json:
            return json.dumps({
                "gate": self.gate,
                "ok": self.ok(),
                "lines": [{"status": ln.status, "id": ln.id, "reason": str(ln.reason)} for ln in self.lines],
            }) + "\n"
        out = []
        for ln in self.lines:
            if ln.status == "PASS":
                out.append("PASS %s\n" % safe_text(ln.id))
            else:
                out.append("FAIL %s: %s\n" % (safe_text(ln.id), safe_text(ln.reason)))
        return "".join(out)


def _frozen_repr(x: object) -> str:
    """``repr`` of a ``str`` as /usr/bin/python3 3.9.6 (Unicode 13.0.0) prints it, on every interpreter (spec section
    14; owner F1 rule E1): quote ``"`` when the text holds ``'`` and no ``"``, else ``'``; a backslash and the chosen
    quote are escaped; TAB, LF, CR are ``\\t``, ``\\n``, ``\\r``; every other character that ``print_table.is_printable``
    refuses is ``\\xNN``, ``\\uNNNN`` or ``\\UNNNNNNNN`` in lower-case hex; the rest is raw. A ``str`` subclass is read
    through ``str.__str__`` (Q-1C0FIN2-R1 (a)); a value that is not a ``str`` (a converted value, never argv text) is
    ``repr(x)``, as 3.9.6 prints it."""
    if not issubclass(type(x), str):
        return repr(x)
    text = _exact(x)
    quote = '"' if "'" in text and '"' not in text else "'"
    out = [quote]
    for c in text:
        if c == "\\" or c == quote:
            out.append("\\" + c)
        elif c == "\t":
            out.append("\\t")
        elif c == "\n":
            out.append("\\n")
        elif c == "\r":
            out.append("\\r")
        elif print_table.is_printable(c):
            out.append(c)
        elif ord(c) <= 0xFF:
            out.append("\\x%02x" % ord(c))
        elif ord(c) <= 0xFFFF:
            out.append("\\u%04x" % ord(c))
        else:
            out.append("\\U%08x" % ord(c))
    out.append(quote)
    return "".join(out)


class _Shown:
    """A value whose ``repr`` is fixed text, so an argparse message template keeps its ``%r`` (and its translation)."""

    def __init__(self, text: str) -> None:
        self.text = text

    def __repr__(self) -> str:
        return self.text


class _UsageFormatter(argparse.HelpFormatter):
    """Usage wrapped as 3.9.6 wraps it (owner F1 rule E4): the usage text is cut into parts by a regular expression, so
    an option stays apart from its metavar; 3.13 keeps them together, which changes every usage line."""

    def _format_usage(self, usage, actions, groups, prefix):
        if prefix is None:
            prefix = argparse._("usage: ")
        if usage is not None:
            usage = usage % dict(prog=self._prog)
        elif not actions:
            usage = "%(prog)s" % dict(prog=self._prog)
        else:
            prog = "%(prog)s" % dict(prog=self._prog)
            optionals = []
            positionals = []
            for action in actions:
                if action.option_strings:
                    optionals.append(action)
                else:
                    positionals.append(action)
            format = self._format_actions_usage
            action_usage = format(optionals + positionals, groups)
            usage = " ".join([s for s in [prog, action_usage] if s])
            text_width = self._width - self._current_indent
            if len(prefix) + len(usage) > text_width:
                part_regexp = r"\(.*?\)+(?=\s|$)|" r"\[.*?\]+(?=\s|$)|" r"\S+"
                opt_usage = format(optionals, groups)
                pos_usage = format(positionals, groups)
                opt_parts = re.findall(part_regexp, opt_usage)
                pos_parts = re.findall(part_regexp, pos_usage)
                assert " ".join(opt_parts) == opt_usage
                assert " ".join(pos_parts) == pos_usage

                def get_lines(parts, indent, prefix=None):
                    lines = []
                    line = []
                    if prefix is not None:
                        line_len = len(prefix) - 1
                    else:
                        line_len = len(indent) - 1
                    for part in parts:
                        if line_len + 1 + len(part) > text_width and line:
                            lines.append(indent + " ".join(line))
                            line = []
                            line_len = len(indent) - 1
                        line.append(part)
                        line_len += len(part) + 1
                    if line:
                        lines.append(indent + " ".join(line))
                    if prefix is not None:
                        lines[0] = lines[0][len(indent):]
                    return lines

                if len(prefix) + len(prog) <= 0.75 * text_width:
                    indent = " " * (len(prefix) + len(prog) + 1)
                    if opt_parts:
                        lines = get_lines([prog] + opt_parts, indent, prefix)
                        lines.extend(get_lines(pos_parts, indent))
                    elif pos_parts:
                        lines = get_lines([prog] + pos_parts, indent, prefix)
                    else:
                        lines = [prog]
                else:
                    indent = " " * len(prefix)
                    parts = opt_parts + pos_parts
                    lines = get_lines(parts, indent)
                    if len(lines) > 1:
                        lines = []
                        lines.extend(get_lines(opt_parts, indent))
                        lines.extend(get_lines(pos_parts, indent))
                    lines = [prog] + lines
                usage = "\n".join(lines)
        return "%s%s\n\n" % (prefix, usage)


_IGNORED = argparse._("ignored explicit argument %r")

# Rule E7: argparse tells a negative number (a positional text such as ``-5``) from an option with a regular
# expression whose ``\d`` follows the interpreter's Unicode data. The digits are frozen at those of 3.9.6 (Unicode
# 13.0.0: 650 code points, the decimal digits, general category Nd), so ``-`` and a digit assigned later is an unknown
# option on every interpreter.
_DIGIT_RANGES = (
    (0x30, 0x39), (0x660, 0x669), (0x6F0, 0x6F9), (0x7C0, 0x7C9), (0x966, 0x96F), (0x9E6, 0x9EF), (0xA66, 0xA6F),
    (0xAE6, 0xAEF), (0xB66, 0xB6F), (0xBE6, 0xBEF), (0xC66, 0xC6F), (0xCE6, 0xCEF), (0xD66, 0xD6F), (0xDE6, 0xDEF),
    (0xE50, 0xE59), (0xED0, 0xED9), (0xF20, 0xF29), (0x1040, 0x1049), (0x1090, 0x1099), (0x17E0, 0x17E9),
    (0x1810, 0x1819), (0x1946, 0x194F), (0x19D0, 0x19D9), (0x1A80, 0x1A89), (0x1A90, 0x1A99), (0x1B50, 0x1B59),
    (0x1BB0, 0x1BB9), (0x1C40, 0x1C49), (0x1C50, 0x1C59), (0xA620, 0xA629), (0xA8D0, 0xA8D9), (0xA900, 0xA909),
    (0xA9D0, 0xA9D9), (0xA9F0, 0xA9F9), (0xAA50, 0xAA59), (0xABF0, 0xABF9), (0xFF10, 0xFF19), (0x104A0, 0x104A9),
    (0x10D30, 0x10D39), (0x11066, 0x1106F), (0x110F0, 0x110F9), (0x11136, 0x1113F), (0x111D0, 0x111D9),
    (0x112F0, 0x112F9), (0x11450, 0x11459), (0x114D0, 0x114D9), (0x11650, 0x11659), (0x116C0, 0x116C9),
    (0x11730, 0x11739), (0x118E0, 0x118E9), (0x11950, 0x11959), (0x11C50, 0x11C59), (0x11D50, 0x11D59),
    (0x11DA0, 0x11DA9), (0x16A60, 0x16A69), (0x16B50, 0x16B59), (0x1D7CE, 0x1D7FF), (0x1E140, 0x1E149),
    (0x1E2F0, 0x1E2F9), (0x1E950, 0x1E959), (0x1FBF0, 0x1FBF9),
)
_DIGIT = "[" + "".join("%s-%s" % (chr(lo), chr(hi)) for lo, hi in _DIGIT_RANGES) + "]"
_NEGATIVE_NUMBER = re.compile(r"^-%(d)s+$|^-%(d)s*\.%(d)s+$" % {"d": _DIGIT})  # argparse's pattern, with its ``\d`` frozen


class ParserRefused(ValueError):
    """A parser configuration that `_GateParser` does not admit (owner Q-G3-F1C-1 (a), Q-G3-F1R3-1 (a); F1 rules E8
    and E10). Argparse 3.9 and 3.12+ read some configurations differently, so the parity of their messages and
    results cannot be kept for them: only the configurations the 14 gates parsers use are admitted, every other one is
    refused by name when it is built, and again when parsing starts, before any argument is read."""


class OptionStringHoldsEquals(ParserRefused):
    """An option string holding ``=`` (``-a=b``, ``--x=``): 3.12+ matches an argument against it by prefix."""


class AbbrevDisabled(ParserRefused):
    """``allow_abbrev=False``: 3.12+ and 3.9 differ in what a single-dash abbreviation of a long single-dash option is."""


class ShortFlagWithoutLongAlias(ParserRefused):
    """A zero-argument single-dash flag with no long alias: 3.9 and 3.12+ read ``-x<text>`` differently."""


class ParserOptionRefused(ParserRefused):
    """A parser option other than the defaults (rows A1, A9): a positional argument, ``parents``, ``formatter_class``, ..."""


class OptionStringRefused(ParserRefused):
    """An option string that is not a long ASCII ``--name`` (row A2)."""


class ActionRefused(ParserRefused):
    """An action other than store, store_true, append, ``_Once`` and the help action (row A3)."""


class NargsRefused(ParserRefused):
    """A ``nargs`` other than None, or ``*`` on the one trailing positional (row A4)."""


class PositionalRefused(ParserRefused):
    """A second positional, or a positional that is not the plain store of a lower-case name (row A5)."""


class ArgumentOptionRefused(ParserRefused):
    """An ``add_argument`` keyword (or its value) outside the allowlist: ``type``, ``choices``, ``const``, ... (row A6)."""


class SubparsersRefused(ParserRefused):
    """A subparsers configuration other than the one ``findings`` uses (row A7)."""


class GroupRefused(ParserRefused):
    """An argument group or a mutually exclusive group (row A8)."""


class NestedGroup(GroupRefused):
    """A group created on a group: the negative-number test of its options is not under this module's control."""


class ParseEntryRefused(ParserRefused):
    """A parse entry other than ``parse_args(list_of_str)``, or ``set_defaults`` (row A10)."""


_E10 = " (refused: F1 rule E10)"
# Rule E10 string shapes: ASCII only, so no Unicode-version-dependent text reaches a usage, a help body or a message.
_LONG_OPTION = re.compile(r"--[a-z][a-z0-9]*(-[a-z0-9]+)*")
_NAME = re.compile(r"[a-z][a-z0-9_]*")
_METAVAR = re.compile(r"[A-Z][A-Z0-9_]*")
_SUB_METAVAR = re.compile(r"\{[a-z]+(,[a-z]+)*\}")
_SUB_NAME = re.compile(r"[a-z]+")
_PROG = re.compile(r"[a-z][a-z0-9 _-]*")
_HELP = re.compile(r"[ -$&-~]*")  # U+0020-U+007E without % (U+0025)


def _match(shape, x: object) -> bool:
    """Whether ``x`` is an exact ``str`` of the shape; no method of a subclass runs (Q-1C0FIN2-R1 (a))."""
    return type(x) is str and shape.fullmatch(x) is not None


def _describe(x: object) -> str:
    """``x`` for a refusal message, whatever it is, without calling a method of it: a str through ``_frozen_repr``
    (the same bytes on every interpreter), a small int, bool or None as itself, anything else by its type name."""
    t = type(x)
    if issubclass(t, str):
        return _frozen_repr(x)
    if x is None or t is bool:
        return "None" if x is None else ("True" if x else "False")
    if t is int:
        return "%d" % x if -10 ** 18 < x < 10 ** 18 else "a large int"  # no digit run: 3.13 limits int -> str
    return "an object of type %s" % _type_name(x)


def _class_name(cls: object) -> str:
    return _exact(_TYPE_NAME.__get__(cls)) if issubclass(type(cls), type) else "an object of type %s" % _type_name(cls)


def _refuse(error: type, what: str):
    raise error(what + _E10)


def _single_dash(option: str, prefix_chars: str) -> bool:
    return len(option) > 1 and option[0] in prefix_chars and option[1] not in prefix_chars


def _long_option(option: str, prefix_chars: str) -> bool:
    return len(option) > 1 and option[0] in prefix_chars and option[1] in prefix_chars


def _refuse_options(option_strings, nargs, prefix_chars: str) -> None:
    """Rule E8 for one action: an ``=`` in an option string, then a zero-argument action with a single-dash option
    string and no long one."""
    for option in option_strings:
        if "=" in option:
            raise OptionStringHoldsEquals("option string %s holds '=' (refused: F1 rule E8)" % _frozen_repr(option))
    if type(nargs) is int and nargs == 0 and any(_single_dash(o, prefix_chars) for o in option_strings) \
            and not any(_long_option(o, prefix_chars) for o in option_strings):
        raise ShortFlagWithoutLongAlias("single-dash flag %s has no long alias (refused: F1 rule E8)"
                                        % ", ".join(_frozen_repr(o) for o in option_strings))


def _refuse_registered(actions, option_string_actions, prefix_chars: str) -> None:
    """Rule E8 over a container's final state: every action, and every option string it is registered under (an edit
    of ``option_strings`` or of the registry after the action was added)."""
    for action in actions:
        _refuse_options(action.option_strings, action.nargs, prefix_chars)
    for option, action in option_string_actions.items():
        _refuse_options([option] + list(action.option_strings), action.nargs, prefix_chars)


class _Once(argparse.Action):
    """Store the value; a second occurrence (in full, with ``=`` or abbreviated) is an argument error."""

    def __call__(self, parser, namespace, values, option_string=None):
        if getattr(namespace, self.dest, None) is not None:
            parser.error("%s given more than once" % self.option_strings[0])
        setattr(namespace, self.dest, values)


class _GateSubParsersAction(argparse._SubParsersAction):
    """The subparsers action of `_GateParser`: one subparser name of ``[a-z]+`` per call, given once, no alias, no help
    and no keyword but ``prog`` (3.9 lets a name be given twice, 3.11+ refuses it)."""

    def add_parser(self, name, **kwargs):
        if not _match(_SUB_NAME, name):
            _refuse(SubparsersRefused, "subparser name %s" % _describe(name))
        if "allow_abbrev" in kwargs and kwargs["allow_abbrev"] is False:  # E8 keeps firing where it fired
            raise AbbrevDisabled("allow_abbrev=False (refused: F1 rule E8)")
        for key in kwargs:
            if type(key) is not str or key != "prog":
                _refuse(SubparsersRefused, "add_parser keyword %s" % _describe(key))
        if name in self._name_parser_map:
            _refuse(SubparsersRefused, "subparser name %s given twice" % _describe(name))
        parser = super().add_parser(name, **kwargs)
        parser._is_sub = True
        return parser


_ACTIONS = (argparse._StoreAction, argparse._StoreTrueAction, argparse._AppendAction, _Once)
_BY_NAME = {"store": argparse._StoreAction, "store_true": argparse._StoreTrueAction, "append": argparse._AppendAction}
_KNOWN_KEYWORDS = ("action", "nargs", "dest", "required", "default", "help", "metavar", "type", "choices", "const",
                   "version")
_BASE_REGISTRIES = argparse.ArgumentParser(add_help=False)._registries
_BASE_ACTION_REGISTRY = dict(_BASE_REGISTRIES["action"])
_IDENTITY_CODE = _BASE_REGISTRIES["type"][None].__code__


class _Spec:
    """What rows A2-A6 read of one argument: built from an action (build and parse start) or from the arguments of an
    ``add_argument`` call that argparse itself refused."""

    def __init__(self, cls, option_strings, nargs, dest, required, default, help, metavar, type_, choices, const):
        self.cls, self.option_strings, self.nargs, self.dest, self.required = cls, option_strings, nargs, dest, required
        self.default, self.help, self.metavar, self.type, self.choices, self.const = default, help, metavar, type_, choices, const


def _spec_of_action(a) -> _Spec:
    return _Spec(type(a), a.option_strings, a.nargs, a.dest, a.required, a.default, a.help, a.metavar, a.type,
                 a.choices, a.const)


def _spec_of_call(args, kwargs) -> _Spec:
    if "version" in kwargs:
        _refuse(ArgumentOptionRefused, "keyword version=%s" % _describe(kwargs["version"]))
    action = kwargs.get("action")
    if action is None:
        cls = argparse._StoreAction
    elif type(action) is str:
        cls = _BY_NAME.get(action)
        if cls is None:
            _refuse(ActionRefused, "action %s" % _describe(action))
    else:
        cls = action
    true = cls is argparse._StoreTrueAction
    if true and "nargs" in kwargs:
        _refuse(NargsRefused, "nargs %s given to store_true" % _describe(kwargs["nargs"]))
    positional = not args or (len(args) == 1 and args[0][:1] != "-")
    if positional:
        if args and "dest" in kwargs:
            _refuse(ArgumentOptionRefused, "keyword dest=%s given to a positional" % _describe(kwargs["dest"]))
        if "required" in kwargs:
            _refuse(ArgumentOptionRefused, "keyword required=%s on a positional" % _describe(kwargs["required"]))
        dest = args[0] if args else kwargs.get("dest")
    else:
        dest = kwargs.get("dest", "x")
    return _Spec(cls, [] if positional else list(args), 0 if true else kwargs.get("nargs"), dest,
                 kwargs.get("required", False), kwargs.get("default", False if true else None), kwargs.get("help"),
                 kwargs.get("metavar"), kwargs.get("type"), kwargs.get("choices"), kwargs.get("const", True if true else None))


def _count_positionals(actions) -> int:
    return sum(1 for a in actions if type(a.option_strings) is list and not a.option_strings)


def _refuse_spec(s: _Spec, positionals_before: int) -> None:
    """Rows A2-A6 for one argument. ``positionals_before`` is the number of positionals the parser already has."""
    if not any(s.cls is c for c in _ACTIONS):
        _refuse(ActionRefused, "action class %s" % _class_name(s.cls))
    if type(s.option_strings) is not list:
        _refuse(OptionStringRefused, "option_strings of type %s" % _type_name(s.option_strings))
    for option in s.option_strings:
        if not _match(_LONG_OPTION, option) or option == "--help":
            _refuse(OptionStringRefused, "option string %s" % _describe(option))
    positional = not s.option_strings
    if positional:
        if positionals_before:
            _refuse(PositionalRefused, "a second positional %s" % _describe(s.dest))
        if s.cls is not argparse._StoreAction:
            _refuse(PositionalRefused, "action class %s on a positional" % _class_name(s.cls))
        if not _match(_NAME, s.dest):
            _refuse(PositionalRefused, "positional name %s" % _describe(s.dest))
    else:
        if not _match(_NAME, s.dest):
            _refuse(ArgumentOptionRefused, "keyword dest=%s" % _describe(s.dest))
        if type(s.required) is not bool:
            _refuse(ArgumentOptionRefused, "keyword required=%s" % _describe(s.required))
    true = s.cls is argparse._StoreTrueAction
    if true:
        nargs_ok = type(s.nargs) is int and s.nargs == 0
    else:
        nargs_ok = s.nargs is None or (positional and type(s.nargs) is str and s.nargs == "*")
    if not nargs_ok:
        _refuse(NargsRefused, "nargs %s" % _describe(s.nargs))
    if s.type is not None:
        _refuse(ArgumentOptionRefused, "keyword type=%s" % _describe(s.type))
    if s.choices is not None:
        _refuse(ArgumentOptionRefused, "keyword choices=%s" % _describe(s.choices))
    if (s.const is not True) if true else (s.const is not None):
        _refuse(ArgumentOptionRefused, "keyword const=%s" % _describe(s.const))
    if (s.default is not False) if true else (s.default is not None):
        _refuse(ArgumentOptionRefused, "keyword default=%s" % _describe(s.default))
    if s.help is not None and not _match(_HELP, s.help):
        _refuse(ArgumentOptionRefused, "keyword help=%s" % _describe(s.help))
    if s.metavar is not None and not _match(_METAVAR, s.metavar):
        _refuse(ArgumentOptionRefused, "keyword metavar=%s" % _describe(s.metavar))


def _refuse_subparsers_action(a, positionals_before: int) -> None:
    """Row A7 for the one subparsers action: ``dest``, an optional ``{a,b}`` metavar, a bool ``required``, no help, no
    title, a `_GateParser` for every name, each name once."""
    if positionals_before:
        _refuse(PositionalRefused, "a subparsers action after a positional")
    if type(a.option_strings) is not list or a.option_strings:
        _refuse(SubparsersRefused, "subparsers action with option strings")
    if not _match(_NAME, a.dest):
        _refuse(SubparsersRefused, "subparsers dest %s" % _describe(a.dest))
    if a.metavar is not None and not _match(_SUB_METAVAR, a.metavar):
        _refuse(SubparsersRefused, "subparsers metavar %s" % _describe(a.metavar))
    if type(a.required) is not bool:
        _refuse(SubparsersRefused, "subparsers required=%s" % _describe(a.required))
    if a.help is not None or type(a.nargs) is not str or a.nargs != argparse.PARSER:
        _refuse(SubparsersRefused, "subparsers help or nargs")
    if a._parser_class is not _GateParser or type(a._choices_actions) is not list or a._choices_actions:
        _refuse(SubparsersRefused, "subparsers parser_class or help of a subparser")
    if not _match(_PROG, a._prog_prefix):
        _refuse(SubparsersRefused, "subparsers prog %s" % _describe(a._prog_prefix))
    choices = a.choices
    if type(choices) is not dict or choices is not a._name_parser_map:
        _refuse(SubparsersRefused, "subparsers choices")
    seen = []
    for name, sub in choices.items():
        if not _match(_SUB_NAME, name):
            _refuse(SubparsersRefused, "subparser name %s" % _describe(name))
        if type(sub) is not _GateParser:
            _refuse(SubparsersRefused, "subparser %s of type %s" % (_describe(name), _type_name(sub)))
        if any(sub is s for s in seen):
            _refuse(SubparsersRefused, "subparser name %s is an alias" % _describe(name))
        seen.append(sub)


def _refuse_added(action, positionals_before: int) -> None:
    if type(action) is _GateSubParsersAction:
        _refuse_subparsers_action(action, positionals_before)
    else:
        _refuse_spec(_spec_of_action(action), positionals_before)


def _refuse_call_values(args, kwargs) -> None:
    """The values of an ``add_argument`` call that argparse would call a method on, checked by exact type before it sees
    them: a ``str`` subclass or any other object anywhere a string goes is refused by the row that admits the string."""
    for a in args:
        if type(a) is not str:
            _refuse(OptionStringRefused, "option string or name %s" % _describe(a))
    for key, value in kwargs.items():
        if type(key) is not str:
            _refuse(ArgumentOptionRefused, "keyword %s" % _describe(key))
        if key in ("dest", "metavar", "help"):
            if value is not None and type(value) is not str:
                _refuse(ArgumentOptionRefused, "keyword %s=%s" % (key, _describe(value)))
        elif key == "action":
            if type(value) is not str and not issubclass(type(value), type):
                _refuse(ActionRefused, "action %s" % _describe(value))
        elif key == "nargs":
            if value is not None and type(value) is not str:  # an int is refused here: argparse builds a list of that length
                _refuse(NargsRefused, "nargs %s" % _describe(value))
        elif key == "required":
            if type(value) is not bool:
                _refuse(ArgumentOptionRefused, "keyword required=%s" % _describe(value))
        elif key not in _KNOWN_KEYWORDS:
            _refuse(ArgumentOptionRefused, "keyword %s" % _describe(key))


def _guarded_add_argument(parser, call, args, kwargs):
    """Row A2-A6 at the ``add_argument`` call. The refusals that need the built action fire in ``_add_action`` (E8 first);
    a call that argparse itself rejects (``nargs=0``, a positional ``required``, a ``%`` in help, ...) is named here."""
    if parser._constructing:
        return call(*args, **kwargs)
    _refuse_call_values(args, kwargs)
    try:
        return call(*args, **kwargs)
    except ParserRefused:
        raise
    except Exception:
        _refuse_spec(_spec_of_call(args, kwargs), _count_positionals(parser._actions))
        raise


class _Guarded:
    """Mixin of the argument groups `_GateParser` makes (the two argparse makes for itself): the options added through a
    group are checked (E8, E10), a group inside a group is refused, and the group's negative-number test is the frozen
    one (E7)."""

    def add_argument(self, *args, **kwargs):
        return _guarded_add_argument(self._container, super().add_argument, args, kwargs)

    def _add_action(self, action):
        _refuse_options(action.option_strings, action.nargs, self.prefix_chars)
        help_action = type(action) is argparse._HelpAction and self._container._constructing \
            and action.option_strings == ["-h", "--help"]
        if not help_action:
            _refuse_added(action, _count_positionals(self._actions))
        return super()._add_action(action)

    def add_argument_group(self, *args, **kwargs):
        raise NestedGroup("a group inside a group (refused: F1 rule E8)")

    def add_mutually_exclusive_group(self, **kwargs):
        raise NestedGroup("a group inside a group (refused: F1 rule E8)")

    def set_defaults(self, **kwargs):
        _refuse(ParseEntryRefused, "set_defaults")


class _GateArgumentGroup(_Guarded, argparse._ArgumentGroup):
    def __init__(self, container, *args, **kwargs) -> None:
        super().__init__(container, *args, **kwargs)
        self._container = container
        self._negative_number_matcher = _NEGATIVE_NUMBER


class _GateExclusiveGroup(_Guarded, argparse._MutuallyExclusiveGroup):
    def __init__(self, container, **kwargs) -> None:
        super().__init__(container, **kwargs)  # sets ``_container``
        self._negative_number_matcher = _NEGATIVE_NUMBER


class _KeptSeparator(list):
    """Argument strings of an option whose value is the text ``--``: 3.9's ``_get_values`` removes the first ``--`` it
    finds from the list (leaving none), 3.12+ keeps it as the value; this list refuses the removal (rule E9)."""

    def remove(self, value):
        raise ValueError(value)


def _refuse_registries(parser) -> None:
    """Row A3 over the registries: the ``action`` registry is argparse's own table, the ``type`` registry holds only its
    identity function, and no other kind exists (a ``register`` call after the build)."""
    registries = parser._registries
    if type(registries) is not dict:
        _refuse(ActionRefused, "registries of type %s" % _type_name(registries))
    for kind, table in registries.items():
        if type(kind) is not str or type(table) is not dict or kind not in ("action", "type"):
            _refuse(ActionRefused, "registry %s" % _describe(kind))
        for key in table:
            if key is not None and type(key) is not str:  # a key is hashed only after it is known to be exact
                _refuse(ActionRefused, "registry entry %s" % _describe(key))
    action = registries.get("action")
    kind_type = registries.get("type")
    if action is None or kind_type is None or len(action) != len(_BASE_ACTION_REGISTRY) or len(kind_type) != 1:
        _refuse(ActionRefused, "registry entries")
    for key, cls in action.items():
        if key not in _BASE_ACTION_REGISTRY or _BASE_ACTION_REGISTRY[key] is not cls:
            _refuse(ActionRefused, "registry entry for action %s" % _describe(key))
    for key, func in kind_type.items():
        if key is not None or type(func) is not type(_refuse_registries) or func.__code__ is not _IDENTITY_CODE:
            _refuse(ActionRefused, "registry entry for type %s" % _describe(key))


def _refuse_groups(parser) -> None:
    """Row A8 over the final state: the two groups argparse makes, made by this parser, and no exclusive group."""
    for group in parser._action_groups:
        if not isinstance(group, _GateArgumentGroup) or group._container is not parser:
            raise NestedGroup("an argument group this parser did not make (refused: F1 rule E8)")
    for group in parser._mutually_exclusive_groups:
        if not isinstance(group, _GateExclusiveGroup) or group._container is not parser:
            raise NestedGroup("an exclusive group this parser did not make (refused: F1 rule E8)")
    if len(parser._action_groups) != 2 or parser._action_groups[0] is not parser._positionals \
            or parser._action_groups[1] is not parser._optionals:
        _refuse(GroupRefused, "an argument group beyond the two argparse makes")
    if parser._mutually_exclusive_groups:
        _refuse(GroupRefused, "a mutually exclusive group")


_PARSER_KEYWORDS = ("prog", "add_help", "prefix_chars", "allow_abbrev", "exit_on_error", "conflict_handler")


class _GateParser(argparse.ArgumentParser):
    """Help and usage errors go to stderr and become GateError, never SystemExit. Every error text built from argv
    is the one 3.9.6 builds, whatever the interpreter (spec section 14; owner F1 rules E1-E5): the repr of argv text is
    ``_frozen_repr``, a single-dash combination such as ``-ha`` is an ignored explicit argument, usage wraps as 3.9.6
    wraps it, an ambiguous option is reported when the arguments are scanned, and a leading ``--`` is the subcommand's
    first value. An option value given as ``--`` is the text ``--`` (E9). Only the configurations the 14 gates parsers
    use are admitted (rule E10); every other one is refused by name (``ParserRefused``): see rows A1-A10 of the F1
    domain table. ``parse_args(list)`` is the one parse entry."""

    def __init__(self, *args, **kwargs) -> None:
        self._constructing, self._parsing, self._is_sub = True, False, False
        if args:
            _refuse(ParserOptionRefused, "positional argument %s" % _describe(args[0]))
        for key in kwargs:
            if type(key) is not str or key not in _PARSER_KEYWORDS:
                _refuse(ParserOptionRefused, "keyword %s" % _describe(key))
        if "prog" not in kwargs:
            _refuse(ParserOptionRefused, "prog is required (sys.argv is not read)")
        for key, shape in (("prog", _PROG),):
            if not _match(shape, kwargs[key]):
                _refuse(ParserOptionRefused, "keyword %s=%s" % (key, _describe(kwargs[key])))
        if kwargs.get("add_help", True) is not True:
            _refuse(ParserOptionRefused, "keyword add_help=%s" % _describe(kwargs["add_help"]))
        if "prefix_chars" in kwargs and not (type(kwargs["prefix_chars"]) is str and kwargs["prefix_chars"] == "-"):
            _refuse(ParserOptionRefused, "keyword prefix_chars=%s" % _describe(kwargs["prefix_chars"]))
        if kwargs.get("allow_abbrev", True) is not True:
            if kwargs["allow_abbrev"] is False:
                raise AbbrevDisabled("allow_abbrev=False (refused: F1 rule E8)")
            _refuse(ParserOptionRefused, "keyword allow_abbrev=%s" % _describe(kwargs["allow_abbrev"]))
        if kwargs.get("exit_on_error", True) is not True:
            _refuse(ParserOptionRefused, "keyword exit_on_error=%s" % _describe(kwargs["exit_on_error"]))
        if "conflict_handler" in kwargs and not (type(kwargs["conflict_handler"]) is str
                                                 and kwargs["conflict_handler"] == "error"):
            _refuse(ParserOptionRefused, "keyword conflict_handler=%s" % _describe(kwargs["conflict_handler"]))
        try:
            super().__init__(formatter_class=_UsageFormatter, **kwargs)
        finally:
            self._constructing = False
        self._negative_number_matcher = _NEGATIVE_NUMBER  # E7; the groups, which register the options, get it too

    def add_argument(self, *args, **kwargs):
        return _guarded_add_argument(self, super().add_argument, args, kwargs)

    def add_argument_group(self, *args, **kwargs):
        if not self._constructing:
            _refuse(GroupRefused, "add_argument_group")
        group = _GateArgumentGroup(self, *args, **kwargs)
        self._action_groups.append(group)
        return group

    def add_mutually_exclusive_group(self, **kwargs):
        _refuse(GroupRefused, "add_mutually_exclusive_group")

    def add_subparsers(self, **kwargs):
        if self._subparsers is not None:
            _refuse(SubparsersRefused, "a second add_subparsers")  # 3.9 reports it through error(), 3.12+ raises ArgumentError
        if self._is_sub:
            _refuse(SubparsersRefused, "add_subparsers on a subparser")
        for key in kwargs:
            if type(key) is not str or key not in ("dest", "metavar", "required"):
                _refuse(SubparsersRefused, "add_subparsers keyword %s" % _describe(key))
        if "dest" not in kwargs:
            _refuse(SubparsersRefused, "add_subparsers without dest")
        if not _match(_NAME, kwargs["dest"]):
            _refuse(SubparsersRefused, "subparsers dest %s" % _describe(kwargs["dest"]))
        if kwargs.get("metavar") is not None and not _match(_SUB_METAVAR, kwargs["metavar"]):
            _refuse(SubparsersRefused, "subparsers metavar %s" % _describe(kwargs["metavar"]))
        if "required" in kwargs and type(kwargs["required"]) is not bool:
            _refuse(SubparsersRefused, "subparsers required=%s" % _describe(kwargs["required"]))
        return super().add_subparsers(action=_GateSubParsersAction, **kwargs)

    def set_defaults(self, **kwargs):
        _refuse(ParseEntryRefused, "set_defaults")

    def _refuse_state(self, depth: int = 0) -> list:
        """Rules E8 and E10 over the parser's final state, and over its subparsers': what the build hooks did not see.
        Returns the parsers of the tree."""
        if self.allow_abbrev is False:
            raise AbbrevDisabled("allow_abbrev=False (refused: F1 rule E8)")
        self._refuse_options_state()
        _refuse_registries(self)
        _refuse_groups(self)
        for action in self._actions:
            if type(action.option_strings) is not list or any(type(o) is not str for o in action.option_strings):
                _refuse(OptionStringRefused, "option_strings of an action")
        _refuse_registered(self._actions, self._option_string_actions, self.prefix_chars)
        self._refuse_actions_state(depth)
        tree = [self]
        for action in self._actions:
            if type(action) is _GateSubParsersAction:
                for sub in action.choices.values():
                    tree.extend(sub._refuse_state(depth + 1))
        return tree

    def _refuse_options_state(self) -> None:
        if type(self) is not _GateParser:
            _refuse(ParserOptionRefused, "parser class %s" % _class_name(type(self)))
        if not _match(_PROG, self.prog):
            _refuse(ParserOptionRefused, "prog=%s" % _describe(self.prog))
        for name, ok in (("add_help", self.add_help is True),
                         ("prefix_chars", type(self.prefix_chars) is str and self.prefix_chars == "-"),
                         ("allow_abbrev", self.allow_abbrev is True),
                         ("exit_on_error", self.exit_on_error is True),
                         ("conflict_handler", type(self.conflict_handler) is str and self.conflict_handler == "error"),
                         ("formatter_class", self.formatter_class is _UsageFormatter),
                         ("usage", self.usage is None), ("description", self.description is None),
                         ("epilog", self.epilog is None), ("fromfile_prefix_chars", self.fromfile_prefix_chars is None),
                         ("argument_default", self.argument_default is None)):
            if not ok:
                _refuse(ParserOptionRefused, "attribute %s=%s" % (name, _describe(getattr(self, name))))
        if type(self._defaults) is not dict or self._defaults:
            _refuse(ParseEntryRefused, "set_defaults (a non-empty _defaults)")

    def _refuse_actions_state(self, depth: int) -> None:
        if not self._actions or type(self._actions[0]) is not argparse._HelpAction:
            _refuse(ActionRefused, "the help action is missing from the first place")
        positionals = 0
        for index, action in enumerate(self._actions):
            if type(action) is argparse._HelpAction:
                if index != 0 or action.option_strings != ["-h", "--help"] or type(action.nargs) is not int or action.nargs != 0:
                    _refuse(ActionRefused, "a help action %s" % _describe(action.option_strings[0] if action.option_strings else None))
            else:
                if type(action) is _GateSubParsersAction and depth:
                    _refuse(SubparsersRefused, "subparsers inside a subparser")
                _refuse_added(action, positionals)
                if not action.option_strings:
                    positionals += 1
        known = [id(a) for a in self._actions]
        for option, action in self._option_string_actions.items():
            if not _match(_LONG_OPTION, option) and option != "-h":
                _refuse(OptionStringRefused, "registered option string %s" % _describe(option))
            if id(action) not in known or option not in action.option_strings:
                _refuse(OptionStringRefused, "registered option string %s without its action" % _describe(option))
        for action in self._actions:
            for option in action.option_strings:
                if self._option_string_actions.get(option) is not action:
                    _refuse(OptionStringRefused, "option string %s is not registered" % _describe(option))

    def parse_args(self, args=None, namespace=None):
        if args is None or type(args) is not list or any(type(a) is not str for a in args):
            _refuse(ParseEntryRefused, "parse_args with %s (a list of str is required; sys.argv is not read)" % _describe(args))
        if namespace is not None:
            _refuse(ParseEntryRefused, "parse_args with a namespace")
        tree = self._refuse_state()
        for parser in tree:
            parser._parsing = True
        try:
            return super().parse_args(args, namespace)
        finally:
            for parser in tree:
                parser._parsing = False

    def parse_known_args(self, args=None, namespace=None):
        if not self._parsing:
            _refuse(ParseEntryRefused, "parse_known_args called directly")
        return super().parse_known_args(args, namespace)

    def parse_intermixed_args(self, args=None, namespace=None):
        _refuse(ParseEntryRefused, "parse_intermixed_args")

    def parse_known_intermixed_args(self, args=None, namespace=None):
        _refuse(ParseEntryRefused, "parse_known_intermixed_args")

    def _get_values(self, action, arg_strings):
        if action.option_strings and arg_strings == ["--"]:  # `--opt=--`: the value is the text `--` (E9)
            arg_strings = _KeptSeparator(arg_strings)
        return super()._get_values(action, arg_strings)

    def print_help(self, file=None) -> None:
        super().print_help(sys.stderr if file is None else file)

    def exit(self, status: int = 0, message: Optional[str] = None):
        if message:
            sys.stderr.write(message)
        if status == 0:
            raise GateError("help requested; no gate was run")
        raise GateError("invalid arguments (exit status %d)" % status)

    def error(self, message: str):
        self.print_usage(sys.stderr)
        sys.stderr.write("%s: error: %s\n" % (self.prog, message))
        raise GateError("invalid arguments: %s" % message)

    def _check_value(self, action, value):
        if action.choices is not None and value not in action.choices:  # only the subparsers action has choices
            args = {"value": _Shown(_frozen_repr(value)),
                    "choices": ", ".join(_frozen_repr(c) for c in action.choices)}
            msg = argparse._("invalid choice: %(value)r (choose from %(choices)s)")
            raise argparse.ArgumentError(action, msg % args)

    def _parse_optional(self, arg_string):
        combined = self._short_flag_combination(arg_string)
        if combined is not None:
            return combined
        found = super()._parse_optional(arg_string)
        if isinstance(found, list):  # 3.12+: the text before `=` of a single-dash argument is a prefix to match
            found = self._without_prefix_matches(arg_string, found)
        if isinstance(found, list) and len(found) > 1:  # 3.12+ reports an ambiguous option when it is consumed
            options = ", ".join(t[1] for t in found)
            self.error(argparse._("ambiguous option: %(option)s could match %(matches)s")
                       % {"option": arg_string, "matches": options})
        return found

    def _without_prefix_matches(self, arg_string, found):
        """Rule E6. For a single-dash argument with an ``=`` (``-=x``, ``-ab=x``) 3.12+ also matches the text before the
        ``=`` as a prefix of the option strings, so ``-=x`` could match every option; 3.9.6 matches the whole argument,
        which no option string starts with. Only the option named by the first two characters (``-a`` in ``-ab=x``) and an
        exact option before the ``=`` are kept; if nothing is left the argument is an unknown option, or a positional
        text when it holds a space (a negative number holds no ``=``)."""
        if len(arg_string) < 2 or arg_string[1] in self.prefix_chars or "=" not in arg_string:
            return found
        wanted = (arg_string[:2], arg_string.partition("=")[0])
        kept = [t for t in found if t[1] in wanted]
        if kept:
            return kept
        return None if " " in arg_string else [(None, arg_string, None, None)]

    def _short_flag_combination(self, arg_string):
        """Rule E3 for ``-h<rest>`` (today's only zero-argument single-dash option): the running interpreter's own
        ``_parse_optional`` shape for it, or None for any other argument. ``rest`` loses one leading ``=`` and then every
        leading ``h``; nothing left is the help, ``-h=`` alone and anything else is an ignored explicit argument, which
        the long form ``--help`` makes argparse raise on every interpreter (3.9.6 crashes on ``-h=``, 3.12+ shows the
        help for ``-ha``). Every such flag has a long alias: the parser refuses one without (E8, checked before parsing)."""
        actions = self._option_string_actions
        action = actions.get(arg_string[:2]) if len(arg_string) > 2 else None
        if action is None or action.nargs != 0:
            return None
        long_option = next(o for o in action.option_strings if o[1] in self.prefix_chars)
        rest = arg_string[2:]
        if rest.startswith("="):
            rest = rest[1:]
            if rest == "":
                return self._explicit_hit(arg_string[:2], action, long_option, "")
        while rest.startswith(arg_string[1]):
            rest = rest[1:]
        if rest == "":
            return super()._parse_optional(arg_string[:2])
        return self._explicit_hit(arg_string[:2], action, long_option, rest)

    def _explicit_hit(self, short_option, action, long_option, explicit_arg):
        exact = super()._parse_optional(short_option)  # the shape of this interpreter
        if isinstance(exact, list):
            return [(action, long_option, "", explicit_arg)]
        return action, long_option, explicit_arg

    def _parse_known_args(self, arg_strings, namespace, *rest):
        try:
            return super()._parse_known_args(self._subcommand_dashes(arg_strings), namespace, *rest)
        except argparse.ArgumentError as e:
            e.message = self._frozen_ignored(e.message)
            raise

    def _subcommand_dashes(self, arg_strings):
        """A leading ``--`` before the subcommand is the subparser action's first value on 3.9.6 (invalid choice
        ``'--'``) and dropped on 3.12+; doubling it gives 3.9.6's value on both."""
        positionals = self._get_positional_actions()
        if not positionals or positionals[0].nargs != argparse.PARSER or "--" not in arg_strings:
            return arg_strings
        first = arg_strings.index("--")
        if first == len(arg_strings) - 1:
            return arg_strings
        for a in arg_strings[:first]:
            if self._parse_optional(a) is None:
                return arg_strings
        return arg_strings[:first + 1] + ["--"] + arg_strings[first + 1:]

    def _frozen_ignored(self, message: str) -> str:
        """argparse's ``ignored explicit argument %r`` carries the interpreter's repr; re-render it with ``_frozen_repr``."""
        head, _, tail = _IGNORED.partition("%r")
        if not (message.startswith(head) and message.endswith(tail)):
            return message
        try:
            value = ast.literal_eval(message[len(head):len(message) - len(tail)])
        except (ValueError, SyntaxError):
            return message
        if not issubclass(type(value), str):
            return message
        return _IGNORED % _Shown(_frozen_repr(value))

def gate_args(prog: str) -> argparse.ArgumentParser:
    p = _GateParser(prog=prog, add_help=True)
    p.add_argument("--root", default=None, action=_Once, help="the tree to check (default: the repository root)")
    return p


def _exact(s: str) -> str:
    """The characters of ``s`` (a ``str`` or a subclass) as an exact ``str``; no method of a subclass runs
    (owner Q-1C0FIN2-R1 (a)), so a later ``%s``, ``+``, ``str()`` or json step cannot reach one."""
    return str.__str__(s)


_TYPE_NAME = type.__dict__["__name__"]


def _type_name(x: object) -> str:
    """The name of ``x``'s type as an exact ``str``, read past a metaclass that overrides ``__name__``."""
    return _exact(_TYPE_NAME.__get__(type(x)))


def _raw(x: object) -> str:
    """``x`` as text without Python's repr escaping, so that ``Result.render`` escapes it exactly once."""
    return _raw_on(x, ())


def _raw_on(x: object, path: tuple) -> str:
    """``_raw`` with the ids of the containers on the current path: one that contains itself renders as
    ``{...}`` or ``[...]``, as ``repr`` does (owner Q-1c0-3). Owner Q-1C0FIN2-1 (b), in repr's shape (pin R8): a
    set renders as ``{`` + its items sorted by their rendered text + ``}`` (``set()`` when empty), a frozenset as
    ``frozenset(`` + that + ``)`` (``frozenset()``), so the order does not depend on the hash seed. Bytes render
    as ``b'`` + the bytes decoded as Latin-1 + ``'`` (owner Q-F80W-3 (a)), so safe_text escapes each byte once.
    Every kind is read from ``type(x)``, never from ``x.__class__``, so an object cannot claim a kind (Q-1C0R5-1 (a))."""
    t = type(x)
    if issubclass(t, str):
        return _exact(x)
    if issubclass(t, bytes):
        return "b'" + bytes.decode(x, "latin-1") + "'"
    if not issubclass(t, (set, frozenset, dict, list, tuple)):
        return _leaf_text(x)
    if id(x) in path:
        return "[...]" if issubclass(t, (list, tuple)) else "{...}"
    if len(path) >= MAX_DEPTH:  # owner Q-R6R-2 (b): a fixed nesting cap, the same on every interpreter
        raise RecursionError("nesting deeper than %d" % MAX_DEPTH)
    inner = path + (id(x),)
    if issubclass(t, (set, frozenset)):
        items = sorted(_items_text([i for i in x], inner))
        body = "{" + ", ".join(items) + "}" if items else ""
        if issubclass(t, frozenset):
            return "frozenset(" + body + ")"
        return body or "set()"
    if issubclass(t, dict):
        texts = _items_text([o for k, v in x.items() for o in (k, v)], inner)
        return "{" + ", ".join(texts[n] + ": " + texts[n + 1] for n in range(0, len(texts), 2)) + "}"
    return "[" + ", ".join(_items_text([i for i in x], inner)) + "]"


def _items_text(items: list, path: tuple) -> list:
    """Each item rendered under its own guard (owner Q-R6R-1 (b)): an item that raises an Exception renders as that
    exception's type name. Every item is rendered before anything propagates, so what propagates does not depend on
    the order of the items (a set's order depends on the hash seed): a non-Exception BaseException first, else a
    RecursionError, which collapses the whole value to the type name, as nesting past the cap does (owner Q-R6R-2
    (b), Q-1C0V1R-3 (b)(i)). Of several non-Exception BaseExceptions, the one of highest rank (``_rank``)
    propagates; of one rank, the first collected (owner Q-R7R-0 (a), Q-R8-1 (a), Q-R8R-0 (a))."""
    out, stop = [], None
    for i in items:
        try:
            out.append(_raw_on(i, path))
        except RecursionError as e:
            stop = e if stop is None else stop
        except Exception as e:
            out.append(_type_name(e))
        except BaseException as e:
            if stop is None or issubclass(type(stop), Exception) or _rank(e) < _rank(stop):
                stop = e
    if stop is not None:
        raise stop
    return out


_MRO = type.__dict__["__mro__"]
_BUILTIN_CLASSES = frozenset(id(v) for v in vars(builtins).values() if issubclass(type(v), type))
# Owner Q-R8R-0 (a), Q-R9R-1 (c): the rank order; an entry the interpreter lacks (BaseExceptionGroup before 3.11)
# is skipped, so the remaining ranks keep their order.
_RANK_ORDER = ("KeyboardInterrupt", "SystemExit", "GeneratorExit", "BaseExceptionGroup")
_RANKS = {id(vars(builtins)[n]): r for r, n in enumerate(_RANK_ORDER) if n in vars(builtins)}
_OTHER = len(_RANK_ORDER)


def _rank(x: object) -> int:
    """The rank of ``x``'s type (smaller propagates first): the first built-in class in its real ``__mro__``,
    read through the ``type`` descriptor, so nothing the object or its metaclass defines is consulted (owner
    Q-R8R-0 (a), Q-R9R-1 (c), Q-R6-3 (a)): KeyboardInterrupt, SystemExit, GeneratorExit, BaseExceptionGroup, any
    other. Classes are compared by identity, so no name, ``__module__``, ``__qualname__`` or ``__eq__`` is read."""
    for c in _MRO.__get__(type(x)):
        if id(c) in _BUILTIN_CLASSES:
            return _RANKS.get(id(c), _OTHER)
    return _OTHER  # not reached: a type an ``except BaseException`` arm catches has BaseException in its __mro__


def _leaf_text(x: object) -> str:
    """``str(x)``; if that raises, ``repr(x)``; if that raises too, the type name, as a missing ``strerror``
    falls back to it (V1r-1, owner Q-1C0V1R-1 (a): a reason is always produced)."""
    for text in (str, repr):
        try:
            return _exact(text(x))
        except Exception:
            pass
    return _type_name(x)


def _s(x: object) -> str:
    """``str(x)`` by its characters, as CPython's own ``%S`` formatting takes it."""
    return _exact(str(x))


def _args_text(e: BaseException) -> str:
    """``BaseException.__str__(e)`` with ``_raw`` in place of ``str`` and ``repr``: the arguments rendered once. The
    arguments are not a container's items (owner Q-R7-1 (a)): each renders unguarded, in order, and the first that
    raises collapses the reason to the type name (Q-1C0V1R-3 (b)(i))."""
    if len(e.args) == 1:
        return _raw(e.args[0])
    return "[" + ", ".join(_raw(a) for a in e.args) + "]" if e.args else ""


def _exc_text(e: BaseException) -> str:
    """``str(e)`` with the repr that the exception's ``__str__`` applies to its arguments undone (verifier V-1):
    KeyError; OSError with a filename, or in its ``[Errno <errno>] <strerror>`` form; SyntaxError's message;
    and every ``__str__`` whose text is the default one, the repr of the arguments. In each branch a class's own
    ``__str__`` text stands (``_own_str_or``, owner Q-F80W-4 (a), Q-1C0FIN3-1 (a))."""
    if issubclass(type(e), KeyError) and e.args:
        return _own_str_or(e, KeyError, _args_text)
    if issubclass(type(e), OSError) and e.filename is not None:
        return _own_str_or(e, OSError, _filename_text)
    if type(e).__str__ is BaseException.__str__:
        return _args_text(e)
    try:
        text = _s(e)
    except Exception:  # the own __str__ cannot render an argument: render the arguments themselves
        return _args_text(e)
    return _own_str_text(e, text)


def _filename_text(e: OSError) -> str:
    """An OSError with a filename: ``[Errno <errno>] <strerror>: <filename>[ -> <filename2>]``, each part once."""
    head = "[Errno %s] " % _raw(e.errno) if e.errno is not None else ""
    out = head + _raw(e.strerror or _type_name(e)) + ": " + _raw(e.filename)
    if e.filename2 is not None:
        out += " -> " + _raw(e.filename2)
    return out


def _gate_filename_text(e: OSError) -> Optional[str]:
    """A GateError that is an OSError with a filename: main d9798af's reason was ``str(e)``, CPython's
    ``[Errno %S] %S: %R[ -> %R]``, so that form with each part once, the head kept whatever errno and strerror are
    and a filename2 shown wherever CPython shows it (F-r13r-1, owner Q-ES-V1 (a)). The form is read off
    ``OSError.__str__(e)`` itself, so a filename2 that the attribute reads as None but CPython shows is kept; None if
    that text is not this form (the caller then renders the text as the generic branch does)."""
    text = _text_of(lambda: OSError.__str__(e))
    head = _text_of(lambda: "[Errno %s] %s: %s" % (_s(e.errno), _s(e.strerror), _exact(repr(e.filename))))
    if text is None or head is None or not text.startswith(head):
        return None
    out = "[Errno %s] %s: %s" % (_raw(e.errno), _raw(e.strerror), _raw(e.filename))
    if text == head:
        return out
    if text[len(head):] == _text_of(lambda: " -> " + _exact(repr(e.filename2))):
        return out + " -> " + _raw(e.filename2)
    return None


_DICT = type.__dict__["__dict__"]


def _own_str_or(e: BaseException, base: type, fallback) -> str:
    """``e``'s own ``__str__`` text, if the ``__str__`` its type's real ``__mro__`` resolves to is no built-in
    class's in that ``__mro__`` (``object``'s included, owner Q-R13R-1 (b); read through the ``type`` descriptors,
    so a metaclass changes nothing and a class without an own ``__str__`` renders as before, F-r11r-1 (b)), as an
    exact ``str`` reconciled by ``_own_str_text``; if it is ``base``'s, or that own ``__str__`` raises or returns a
    non-str, ``fallback(e)``, the branch's rendering of the arguments; if it is another built-in's, main d9798af's
    form: the one argument in the KeyError branch (F-r13r-2), the filename form in the KeyError and OSError branches
    (F-r12r-1), else that built-in's form with each part once (``_built_in_text``) (owner Q-F80W-4 (a), Q-1C0FIN3-1
    (a), Q-1C0FIN2-R1 (a), Q-ES-V1 (a))."""
    mro = _MRO.__get__(type(e))
    own = next(_DICT.__get__(c)["__str__"] for c in mro if "__str__" in _DICT.__get__(c))
    for c in mro:
        if id(c) in _BUILTIN_CLASSES and _DICT.__get__(c).get("__str__") is own:
            if base is KeyError and len(e.args) == 1:  # F-r13r-2: main's KeyError branch rendered the one argument
                return fallback(e)
            if base is not BaseException and c is not OSError and _main_filename_form(e):  # F-r12r-1
                return _filename_text(e)
            return fallback(e) if c is base else _built_in_text(e, c)
    try:
        text = _s(e)
    except Exception:  # the own __str__ cannot render an argument: render the arguments themselves
        return fallback(e)
    return _own_str_text(e, text)


def _main_filename_form(e: BaseException) -> bool:
    """Whether main d9798af's ``_exc_text`` gave ``e`` the filename form: an OSError with a filename, unless it is a
    KeyError with one argument (main's KeyError branch came first). In the KeyError and OSError branches a class
    with no own ``__str__`` keeps that form whichever built-in ``__str__`` it resolves to; a GateError's reason was
    ``str(e)``, so not there (F-r12r-1, owner Q-ES-V1 (a))."""
    t = type(e)
    return issubclass(t, OSError) and e.filename is not None and not (issubclass(t, KeyError) and len(e.args) == 1)


def _built_in_text(e: BaseException, c: type) -> str:
    """The text of built-in ``c``'s ``__str__`` for ``e`` with the arguments rendered once: KeyError's and
    BaseException's from the arguments, OSError's with a filename from its parts, as their own branches give them
    (for a GateError, CPython's form, ``_gate_filename_text``); any other's (SyntaxError's, OSError's without a
    filename, ...) as the generic branch of ``_exc_text`` does."""
    if c is KeyError or c is BaseException:
        return _args_text(e)
    if c is OSError and e.filename is not None:
        text = _gate_filename_text(e) if issubclass(type(e), GateError) else _filename_text(e)
        if text is not None:
            return text
    try:
        text = _s(e)
    except Exception:  # as the generic branch: render the arguments themselves
        return _args_text(e)
    return _own_str_text(e, text)


def _text_of(make) -> Optional[str]:
    """``make()`` as an exact ``str``, or None if it raises: a form whose text cannot be computed is not the form
    of ``str(e)``."""
    try:
        return _exact(make())
    except Exception:
        return None


def _own_str_text(e: BaseException, text: str) -> str:
    """``text`` (``str(e)`` from an own ``__str__``) with the arguments rendered once where it shows them. When
    it shows them and they cannot render, the error propagates to ``_reason_text``, as for a default ``__str__``
    (owner Q-1C0V1R-3 (b)(i)); a text that does not show them stands."""
    if text == _text_of(lambda: BaseException.__str__(e)):  # an own __str__ that fell back to the default
        return _args_text(e)
    if issubclass(type(e), KeyError) and text == _text_of(lambda: KeyError.__str__(e)):  # F-r11r-1 (a)
        return _args_text(e)
    if issubclass(type(e), OSError) and e.filename is not None and text == _text_of(lambda: OSError.__str__(e)):
        # F-r11r-1 (a): the built-in filename form, each part once; a GateError's reason was str(e) in main (F-r13r-1)
        once = _gate_filename_text(e) if issubclass(type(e), GateError) else _filename_text(e)
        if once is not None:
            return once
    if issubclass(type(e), OSError) and text == _text_of(lambda: "[Errno %s] %s" % (_s(e.errno), _s(e.strerror))):
        return "[Errno %s] %s" % (_raw(e.errno), _raw(e.strerror))
    msg = _text_of(lambda: _s(e.msg)) if issubclass(type(e), SyntaxError) and e.msg is not None else None
    if msg is not None and text.startswith(msg):
        return _raw(e.msg) + text[len(msg):]
    return text


def _exit_text(e: SystemExit) -> str:
    code = e.code
    return "'%s'" % _exact(code) if issubclass(type(code), str) else _raw(code)


def _reason_text(e: BaseException, text) -> str:
    """``text(e)`` as an exact ``str``; if the exception itself cannot be read (its ``args`` raise), its type name,
    the ``_leaf_text`` fallback, so run_check always returns a reason (owner Q-1C0V1R-1 (a))."""
    try:
        return _exact(text(e))
    except Exception:
        return _type_name(e)


def run_check(name: str, check, args: list) -> Result:
    """Run ``check(args)``; anything but a non-empty Result becomes a FAIL line. Every reason and id that leaves
    is an exact ``str`` (F-1c0fin2-1, owner Q-1C0FIN2-R2 (a))."""
    try:
        result = check(args)
    except GateError as e:
        return _input_fail(name, _reason_text(e, lambda x: _own_str_or(x, BaseException, _args_text)))
    except SystemExit as e:
        return _input_fail(name, "exit requested (%s)" % _reason_text(e, _exit_text))
    except Exception as e:
        return _input_fail(name, "%s: %s" % (_type_name(e), _reason_text(e, _exc_text)))
    try:  # one guard over all the work after the check returns (owner Q-1C0R5-1 (a)); a BaseException propagates
        if not issubclass(type(result), Result):
            return _input_fail(name, "the check returned %s, not a Result" % _type_name(result))
        return _own_result(name, result)
    except Exception as e:  # the type-name fallback, as _reason_text gives for an exception it cannot render
        return _input_fail(name, _type_name(e))


_STATUSES = ("PASS", "FAIL")  # spec §13: a gate prints PASS id or FAIL id: reason lines


def _own_result(name: str, result: Result) -> Result:
    """A new Result built from the one the check returned, which is never changed (F-fin2r-1). Its shape is checked
    first (owner Q-1C0FIN2-U2 (a)): the gate an exact ``str``, ``lines`` a list (plan: ``Result(gate: str, lines:
    list)``), each entry a Line whose status is the exact ``str`` PASS or FAIL. Any other shape fails
    ``<name>.input`` with a named reason, as a value that is not a Result does; an empty list fails ``<name>.empty``.
    The gate must be ``name`` (owner Q-1C0R5-2 (a)). Kinds are read from ``type()``, never ``__class__``, so an
    object that claims to be a list, a Line or a str is refused (owner Q-1C0R5-1 (a)); a class whose real ``__mro__``
    holds Result or Line is a subclass (owner Q-R6-3 (a)). An id and a reason render through ``_raw``, item by item
    as an exception argument does (owner Q-F80W-5 (b), Q-R6-2 (a))."""
    try:
        gate, lines = result.gate, result.lines
    except Exception:
        return _input_fail(name, "the check returned a Result that cannot be read")
    if type(gate) is not str:
        return _input_fail(name, "the check returned a Result whose gate is %s, not a str" % _type_name(gate))
    if gate != _exact(name):
        return _input_fail(name, "the check returned a Result for gate %s, not %s" % (gate, _exact(name)))
    if not issubclass(type(lines), list):
        return _input_fail(name, "the check returned a Result whose lines is %s, not a list" % _type_name(lines))
    out = []
    for n, ln in enumerate(list.copy(lines), 1):
        if not issubclass(type(ln), Line):
            return _input_fail(name, "line %d of the Result is %s, not a Line" % (n, _type_name(ln)))
        try:
            status, id_, reason = ln.status, ln.id, ln.reason
        except Exception:
            return _input_fail(name, "line %d of the Result cannot be read" % n)
        if type(status) is not str:
            return _input_fail(name, "line %d of the Result has a status of type %s, not str" % (n, _type_name(status)))
        if status not in _STATUSES:
            return _input_fail(name, "line %d of the Result has status %s, not PASS or FAIL" % (n, status))
        out.append(Line(status, _raw(id_), _raw(reason)))
    if not out:
        empty = Result(name, [])
        empty.fail(name + ".empty", "the gate produced no lines")
        return empty
    return Result(gate, out)


def _input_fail(name: str, reason: str) -> Result:
    out = Result(name, [])
    out.fail(name + ".input", reason)
    return out


def run_gate(name: str, check, argv: Optional[list] = None) -> int:
    """Run a gate: ``--json`` counts only as ``argv[0]``; print the lines; exit code 0 only when ok."""
    args = list(sys.argv[1:] if argv is None else argv)
    as_json = args[:1] == ["--json"]
    if as_json:
        args = args[1:]
    result = run_check(name, check, args)
    sys.stdout.write(result.render(as_json))
    return 0 if result.ok() else 1


def repo_root() -> str:
    """``CLAUDE_PROJECT_DIR`` when set and non-empty (it must be a directory), else the git toplevel."""
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        if not os.path.isdir(env):
            raise GateError("CLAUDE_PROJECT_DIR is not a directory")
        return env
    from gates.lib import gitinfo
    try:
        return gitinfo.toplevel(".")
    except GitNotFound:
        raise
    except GateError as e:
        raise GateError("%s; run /strict-delivery:init" % e) from None
