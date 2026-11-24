"""Gate ``index``: the four generated files render, validate against their schemas, are untracked and git-ignored
(spec 5, 9, 13; plan Task 5b.2). The gate renders in memory and writes nothing."""
from __future__ import annotations

import os
import shlex
from typing import Optional

from gates.lib import config, gitinfo, schema, yamlsub
from gates.lib.result import GateError, Result, gate_args, repo_root, run_gate
from gates.tools import index

PRODUCES: tuple = ()


def _root(args: list) -> str:
    ns = gate_args("index").parse_args(args)
    root = ns.root if ns.root is not None else repo_root()
    try:
        gitinfo.toplevel(root)
    except gitinfo.GitNotFound:
        raise
    except GateError as e:
        raise GateError("%s; run /strict-delivery:init" % e) from None
    gitinfo._require_toplevel(root)
    return root


def _shape(files: object) -> Optional[str]:
    """None when ``render`` returned four ``str`` paths with ``str`` texts; else what it returned."""
    if type(files) is not dict:
        return "render returned %s, not a dict" % type(files).__name__
    if len(files) != len(index.PRODUCES):
        return "render returned %d paths, not %d" % (len(files), len(index.PRODUCES))
    if any(type(k) is not str or type(v) is not str for k, v in files.items()):
        return "render returned a path or a text that is not a str"
    return None


def _valid(kind: str, text: str, cfg: dict) -> list:
    try:
        sch = schema.load_schema(os.path.join(schema.SCHEMAS_DIR, kind + ".yml"))
    except schema.SchemaError as e:
        raise GateError(str(e)) from None
    if sch.format != "yaml":
        return schema.validate_markdown(sch, text)
    try:
        value = yamlsub.parse(text)
    except yamlsub.YamlError as e:
        return ["%s (line %d)" % (e.reason, e.line) if e.line else e.reason]
    return schema.validate(sch, value, cfg)


def check(args: list) -> Result:
    root = _root(args)
    cfg = config.load(root)
    res = Result("index")
    try:
        files = index.render(root, cfg)
    except GateError as e:
        res.fail("index.render", str(e))
        return res
    except Exception as e:
        res.fail("index.render", "%s: %s" % (type(e).__name__, e))
        return res
    bad = _shape(files)
    if bad:
        res.fail("index.render", bad)
        return res
    res.passed("index.render")
    paths = list(files)
    failed = False
    for kind, path in zip(index.PRODUCES, paths):
        for why in _valid(kind, files[path], cfg):
            res.fail("index.valid." + path, why)
            failed = True
    if not failed:
        res.passed("index.valid")
    failed = False
    try:
        tracked = gitinfo.tracked_files(root)
    except GateError as e:
        res.fail("index.tracked", str(e))
        failed = True
        tracked = frozenset()
    for path in paths:
        if path in tracked:
            res.fail("index.tracked." + path, "generated; never commit it: git rm --cached %s" % shlex.quote(path))
            failed = True
    if not failed:
        res.passed("index.tracked")
    failed = False
    for path in paths:
        try:
            ignored = gitinfo.is_ignored(root, path)
        except GateError as e:
            res.fail("index.ignored." + path, str(e))
            failed = True
            continue
        if not ignored:
            res.fail("index.ignored." + path, "add it to .gitignore (spec §5)")
            failed = True
    if not failed:
        res.passed("index.ignored")
    return res


def main(argv: Optional[list] = None) -> int:
    return run_gate("index", check, argv)


if __name__ == "__main__":
    raise SystemExit(main())
