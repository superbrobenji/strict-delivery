"""Gate ``schema``: every data file carries and obeys its schema (spec Appendix A, §13)."""
from __future__ import annotations

import copy
import os
import stat
import sys

from gates.lib import config, gitinfo, schema, yamlsub
from gates.lib.result import GateError, Result, gate_args, repo_root, run_gate

PRODUCES: tuple = ()


def _root(args: list) -> str:
    ns = gate_args("schema").parse_args(args)
    root = ns.root if ns.root is not None else repo_root()
    try:
        gitinfo.toplevel(root)
    except gitinfo.GitNotFound:
        raise
    except GateError as e:
        raise GateError("%s; run /strict-delivery:init" % e) from None
    gitinfo._require_toplevel(root)
    return root


def _raw_config(root: str) -> object:
    path = os.path.join(root, config.CONFIG_PATH)
    if not os.path.lexists(path):
        raise GateError("%s: missing; run /strict-delivery:init" % config.CONFIG_PATH)
    try:
        return yamlsub.load(path, config.CONFIG_PATH)
    except yamlsub.YamlError as e:
        raise GateError("%s (line %d)" % (e.reason, e.line) if e.line else e.reason) from None


def _read_text(root: str, rel: str) -> str:
    data = yamlsub._read_regular_file(os.path.join(root, *rel.split("/")), rel)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise yamlsub.YamlError(0, "%s: not valid UTF-8" % rel) from None


def _check_file(root: str, sch: schema.Schema, rel: str, from_glob: bool, cfg: dict) -> list:
    """The errors of one file; a problem reading it is one error."""
    full = os.path.join(root, *rel.split("/"))
    try:
        if from_glob:
            mode = os.lstat(full).st_mode
            if not stat.S_ISREG(mode):
                return ["is not a regular file (a directory, symlink or other entry is never followed)"]
        if sch.format == "markdown":
            return schema.validate_markdown(sch, _read_text(root, rel))
        return schema.validate(sch, yamlsub.load(full, rel), cfg)
    except yamlsub.YamlError as e:
        return ["%s (line %d)" % (e.reason, e.line) if e.line else e.reason]


def _check_kind(res: Result, root: str, sch: schema.Schema, cfg: dict) -> None:
    kind = sch.kind
    failed = False
    try:
        entries = schema.entries_of(sch, root, cfg)
        expected = schema.expected_paths(sch, cfg)
    except schema.LayoutError as e:
        res.fail("schema.%s.%s" % (kind, e.rel), str(e))
        return
    except schema.SchemaError as e:
        res.fail("schema.kinds.%s" % kind, str(e))
        return
    if kind not in schema.GENERATED_KINDS:
        present = {rel for rel, _ in entries}
        for rel in expected:
            if rel not in present:
                res.fail("schema.%s.%s" % (kind, rel), "missing")
                failed = True
    for rel, from_glob in entries:
        for problem in _check_file(root, sch, rel, from_glob, cfg):
            res.fail("schema.%s.%s" % (kind, rel), problem)
            failed = True
    if not failed:
        res.passed("schema.%s" % kind)


def check(args: list) -> Result:
    root = _root(args)
    raw = _raw_config(root)
    produced = schema.produced_kinds()
    try:
        loaded, problems = schema.scan_dir()
    except schema.SchemaError as e:
        raise GateError(str(e)) from None
    res = Result("schema")
    checked = [k for k in schema.KNOWN_KINDS if k == "config" or k in produced]
    failed = False
    for name, reason in problems:
        res.fail("schema.kinds.%s" % name, reason)
        failed = True
    for k in sorted(produced - set(schema.KNOWN_KINDS)):
        res.fail("schema.kinds.%s" % k, "produced kind is not in KNOWN_KINDS")
        failed = True
    bad = {name for name, _ in problems}
    for k in checked:
        if k not in loaded and k not in bad:
            res.fail("schema.kinds.%s" % k, "gates/schemas/%s.yml: missing" % k)
            failed = True
    if not failed:
        res.passed("schema.kinds")
    if "config" not in loaded:
        return res
    errors = schema.validate(loaded["config"], raw, copy.deepcopy(config.DEFAULTS))
    for e in errors:
        res.fail("schema.config.%s" % config.CONFIG_PATH, e)
    if errors:
        return res
    res.passed("schema.config")
    cfg = config.load(root)
    for k in checked:
        if k != "config" and k in loaded:
            _check_kind(res, root, loaded[k], cfg)
    return res


if __name__ == "__main__":
    sys.exit(run_gate("schema", check))
