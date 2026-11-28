# Task 3b.2 fix round 4 (review 4: R4-2 to R4-5; a test-only round), CI3 format (tests/ci_mutants.py on main).
# Converted by the hooks stream controller 8 from the implementer's par_mutants table ch/hk7-3b2-fix4-mutants.py
# (the killing test classes per id are named there). M4-1..M4-3: one per pin of rows F4-1..F4-3 (R4-2, R4-3, R4-5).
# M4-4..M4-12: row F4-4 (R4-4), one per row with no red evidence in review 4: A2, A5, A8, A12 (hook level), B8, B9,
# V1 (A), V1 (B), V1 (C). M4-10..M4-12 are interpreter-dependent; tests.test_bashpolicy.ConstantsTest
# (test_no_unicode_db_calls) fails on both interpreters, so each is expected KILLED, not SPLIT.

M = {
    'M4-1': ('gates/lib/bashpolicy.py', '        if word == "-i":\n', '        if word == "-i" and not operands:\n'),
    'M4-2': ('gates/lib/bashpolicy.py', '            or any(shellscan.token_in(view, name, True) for view in views for name in aliases))', '            or any(_fold(name) in _runs(_fold(view)) for view in views for name in aliases))'),
    'M4-3': ('gates/lib/bashpolicy.py', '        while n < len(words) and words[n].startswith("-"):\n            n += 2 if words[n] in _VALUE_OPTIONS else 1\n', '        while n < len(words) and (words[n].startswith("-") or words[n] == ""):\n            n += 2 if words[n] in _VALUE_OPTIONS else 1\n'),
    'M4-4': ('gates/hooks/pre_bash.py', '    if not (is_commit or is_write):\n        return []\n', '    if not (is_commit or is_write):\n        return _inherited_lines(ctx)\n'),
    'M4-5': ('gates/lib/bashpolicy.py', 'WRITE_TEXT_WORDS = GIT_WRITES + ("branch", "checkout", "switch", "fetch")\n', 'WRITE_TEXT_WORDS = GIT_WRITES + ("branch", "checkout", "switch", "fetch", "status")\n'),
    'M4-6': ('gates/lib/bashpolicy.py', '        if "git" in folded and "-c" in toks[folded.index("git") + 1:]:\n', '        if "-c" in toks:\n'),
    'M4-7': ('gates/lib/bashpolicy.py', '    views = (text, " ".join(shellscan.scan(text).words))\n    if not any(', '    views = (" ".join(shellscan.scan(text).words),)\n    if not any('),
    'M4-8': ('gates/lib/bashpolicy.py', '    if not any(shellscan.token_in(view, "git", True) for view in views):\n', '    if not any(shellscan.token_in(view, "git", True) or shellscan.token_in(view, "g") for view in views):\n'),
    'M4-9': ('gates/hooks/pre_bash.py', '    rule = write_text_refusals(command, aliases, p0.agent_key)\n', '    rule = write_text_refusals(command, {**aliases, **{w: "log" for w in scan.words}}, p0.agent_key)\n'),
    'M4-10': ('gates/hooks/pre_bash.py', '    rule = write_text_refusals(command, aliases, p0.agent_key)\n', '    rule = write_text_refusals(command, aliases, p0.agent_key) if all(\n        int(w) >= 0 for w in command.replace(";", " ").split() if w.isdigit()) else []\n'),
    'M4-11': ('gates/lib/bashpolicy.py', '        elif "=" in word and word[0] != "=" and all(ch in _ASCII_ALNUM or ch == "_" for ch in word.split("=", 1)[0]):\n', '        elif "=" in word and word[0] != "=" and all(ch.isalnum() or ch == "_" for ch in word.split("=", 1)[0]):\n'),
    'M4-12': ('gates/lib/bashpolicy.py', '    reason = safe_text(scan.reason) if not scan.plain else _NOT_GIT\n', '    reason = safe_text(scan.reason) if not scan.plain and all(\n        int(w) >= 0 for w in text.replace(";", " ").split() if w.isdigit()) else _NOT_GIT\n'),
}
KILL = {
    'M4-1': ('tests.test_bashpolicy', 'tests.test_hook_bash'),
    'M4-2': ('tests.test_bashpolicy', 'tests.test_hook_bash'),
    'M4-3': ('tests.test_hook_bash',),
    'M4-4': ('tests.test_hook_bash',),
    'M4-5': ('tests.test_hook_bash',),
    'M4-6': ('tests.test_bashpolicy', 'tests.test_hook_bash'),
    'M4-7': ('tests.test_hook_bash',),
    'M4-8': ('tests.test_hook_bash',),
    'M4-9': ('tests.test_hook_bash',),
    'M4-10': ('tests.test_hook_bash', 'tests.test_bashpolicy'),
    'M4-11': ('tests.test_hook_bash', 'tests.test_bashpolicy'),
    'M4-12': ('tests.test_bashpolicy',),
}
