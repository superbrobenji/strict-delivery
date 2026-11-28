M = {
    # Task 3b.2 fix round 4 part d (review 4d: R4d-1 to R4d-5), gates/lib/bashpolicy.py. One entry per operand of every
    # changed production condition or call (stream-common line 70). The killing test class follows each entry as
    # "K tests.<module>.<Class> (<test>)"; KILL below names the module (CI3 format). The run_gates arity member of R4d-3
    # is not in this commit (NEEDS_DECISION), so it has no entry.
    # --- R4d-5: Policy frozen; F4d-5b: GitCall frozen
    "MD4-1": ("gates/lib/bashpolicy.py", "@dataclasses.dataclass(frozen=True)\nclass Policy:", "@dataclasses.dataclass(frozen=False)\nclass Policy:"),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (test_policy_frozen)
    "MD4-2": ("gates/lib/bashpolicy.py", "@dataclasses.dataclass(frozen=True)\nclass GitCall:", "@dataclasses.dataclass(frozen=False)\nclass GitCall:"),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (test_git_call_frozen)
    # --- R4d-2: Policy.agent_key non-empty
    "MD4-3": ("gates/lib/bashpolicy.py", '        if self.agent_key == "":   # row F4d-2 (R4d-2)', "        if False:   # row F4d-2 (R4d-2)"),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (test_policy_agent_key_non_empty, test_policy_agent_key_reader_relation)
    "MD4-4": ("gates/lib/bashpolicy.py", 'if self.agent_key == "":   # row F4d-2', 'if self.agent_key == "x":   # row F4d-2'),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (test_policy_agent_key_non_empty)
    "MD4-5": ("gates/lib/bashpolicy.py", 'if self.agent_key == "":   # row F4d-2', 'if self.agent_key != "":   # row F4d-2'),
    # K tests.test_bashpolicy.ExactTypesRound4dTest, tests.test_bashpolicy.ExactTypesPolicyTest (every pol())
    "MD4-6": ("gates/lib/bashpolicy.py", '"Policy.agent_key must be a non-empty str"', '"Policy.agent_key must be a str"'),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (test_policy_agent_key_non_empty)
    # --- R4d-3: Policy.state_access a Python function or method binding no arguments (ET25, ruling)
    "MD4-7": ("gates/lib/bashpolicy.py", "        if not _function_of_no_arguments(self.state_access):", "        if False:"),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (test_policy_state_access_arity)
    "MD4-8": ("gates/lib/bashpolicy.py", "_function_of_no_arguments(self.state_access)", "_function_of_no_arguments(lambda: None)"),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (test_policy_state_access_arity)
    "MD4-9": ("gates/lib/bashpolicy.py", '"Policy.state_access must be a function or method of no arguments"', '"Policy.state_access must be callable"'),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (test_policy_state_access_arity)
    "MD4-10": ("gates/lib/bashpolicy.py", "    target = fn.__func__ if type(fn) is types.MethodType else fn\n", "    target = fn\n"),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (a bound method of a Python function refused)
    "MD4-11": ("gates/lib/bashpolicy.py", "if type(fn) is types.MethodType else fn", "if callable(fn) else fn"),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (a function has no __func__: AttributeError at every pol())
    "MD4-12": ("gates/lib/bashpolicy.py", "    if type(target) is not types.FunctionType:\n", "    if not callable(target):\n"),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (the class _Call0, a callable object of no arguments, MethodType(len, 1) accepted)
    "MD4-13": ("gates/lib/bashpolicy.py", "    if type(target) is not types.FunctionType:\n", "    if type(target) is not types.BuiltinFunctionType:\n"),
    # K tests.test_bashpolicy.ExactTypesRound4dTest, tests.test_bashpolicy.ExactTypesPolicyTest (every pol() refused). The isinstance
    # relaxation is equivalent (types.FunctionType cannot be subclassed), so it has no entry.
    "MD4-14": ("gates/lib/bashpolicy.py", "        inspect.signature(fn).bind()\n", "        inspect.signature(fn)\n"),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (lambda x, keyword-only, Recorder().__call__ accepted)
    "MD4-15": ("gates/lib/bashpolicy.py", "        inspect.signature(fn).bind()\n", "        inspect.signature(target).bind()\n"),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (_Call0().__call__: its __func__ needs self, refused)
    "MD4-16": ("gates/lib/bashpolicy.py", "        inspect.signature(fn).bind()\n    except (TypeError, ValueError):", "        inspect.signature(fn).bind()\n    except TypeError:"),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (the __wrapped__ loop: a raw ValueError)
    "MD4-17": ("gates/lib/bashpolicy.py", "        inspect.signature(fn).bind()\n    except (TypeError, ValueError):", "        inspect.signature(fn).bind()\n    except ValueError:"),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (lambda x: a raw binding TypeError, another message)
    "MD4-18": ("gates/lib/bashpolicy.py", "    except (TypeError, ValueError):\n        return False\n    return True\n", "    except (TypeError, ValueError):\n        return True\n    return True\n"),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (lambda x accepted)
    "MD4-19": ("gates/lib/bashpolicy.py", "    except (TypeError, ValueError):\n        return False\n    return True\n", "    except (TypeError, ValueError):\n        return False\n    return False\n"),
    # K tests.test_bashpolicy.ExactTypesRound4dTest, tests.test_bashpolicy.ExactTypesPolicyTest (every pol())
    "MD4-20": ("gates/lib/bashpolicy.py", "    if type(target) is not types.FunctionType:\n        return False\n", "    if type(target) is not types.FunctionType:\n        return True\n"),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (dict, a callable object accepted)
    # --- R4d-1: GitCall.__post_init__ (row F4d-1c)
    "MD4-21": ("gates/lib/bashpolicy.py", 'for name in ("lines", "args", "expansion_words", "expansions"):', 'for name in ("args", "expansion_words", "expansions"):'),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (test_git_call_fields_exact_types, field lines)
    "MD4-22": ("gates/lib/bashpolicy.py", 'for name in ("lines", "args", "expansion_words", "expansions"):', 'for name in ("lines", "expansion_words", "expansions"):'),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (field args)
    "MD4-23": ("gates/lib/bashpolicy.py", 'for name in ("lines", "args", "expansion_words", "expansions"):', 'for name in ("lines", "args", "expansions"):'),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (field expansion_words)
    "MD4-24": ("gates/lib/bashpolicy.py", 'for name in ("lines", "args", "expansion_words", "expansions"):', 'for name in ("lines", "args", "expansion_words"):'),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (field expansions)
    "MD4-25": ("gates/lib/bashpolicy.py", "            if type(value) is not list or any(type(word) is not str for word in value):   # row F4d-1c", "            if any(type(word) is not str for word in value):   # row F4d-1c"),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (_ListSub(), () accepted; None raises a raw TypeError)
    "MD4-26": ("gates/lib/bashpolicy.py", "            if type(value) is not list or any(type(word) is not str for word in value):   # row F4d-1c", "            if type(value) is not list:   # row F4d-1c"),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (["x", 1], [_StrSub("x")], [b"x"], [None] accepted)
    "MD4-27": ("gates/lib/bashpolicy.py", "            if type(value) is not list or any(type(word) is not str for word in value):   # row F4d-1c", "            if not isinstance(value, list) or any(type(word) is not str for word in value):   # row F4d-1c"),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (_ListSub() accepted)
    "MD4-28": ("gates/lib/bashpolicy.py", "            if type(value) is not list or any(type(word) is not str for word in value):   # row F4d-1c", "            if type(value) is not list or any(not isinstance(word, str) for word in value):   # row F4d-1c"),
    # K tests.test_bashpolicy.ExactTypesRound4dTest ([_StrSub("x")] accepted)
    "MD4-29": ("gates/lib/bashpolicy.py", '"GitCall.%s must be a list of str" % name', '"GitCall.%s must be a list" % name'),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (message)
    "MD4-30": ("gates/lib/bashpolicy.py", 'for name in ("argv_C", "sub"):', 'for name in ("sub",):'),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (field argv_C)
    "MD4-31": ("gates/lib/bashpolicy.py", 'for name in ("argv_C", "sub"):', 'for name in ("argv_C",):'),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (field sub)
    "MD4-32": ("gates/lib/bashpolicy.py", "if value is not None and type(value) is not str:   # row F4d-1c", "if type(value) is not str:   # row F4d-1c"),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (argv_C=None and sub=None refused: every git_call without -C)
    "MD4-33": ("gates/lib/bashpolicy.py", "if value is not None and type(value) is not str:   # row F4d-1c", "if value is not None:   # row F4d-1c"),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (test_git_call_construction_sites: git -C d refused)
    "MD4-34": ("gates/lib/bashpolicy.py", "if value is not None and type(value) is not str:   # row F4d-1c", "if value is not None and not isinstance(value, str):   # row F4d-1c"),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (_StrSub("d") accepted)
    "MD4-35": ("gates/lib/bashpolicy.py", '"GitCall.%s must be None or a str" % name', '"GitCall.%s must be a str" % name'),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (message)
    "MD4-36": ("gates/lib/bashpolicy.py", "        if type(self.env_refused) is not bool:   # row F4d-1c", "        if False:   # row F4d-1c"),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (0, 1, None, "yes", [] accepted); isinstance is equivalent (bool has no subclass), no entry
    "MD4-37": ("gates/lib/bashpolicy.py", '"GitCall.env_refused must be a bool"', '"env_refused must be a bool"'),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (message)
    # --- R4d-1: shell_alias_texts (F4d-1a) and expansion_c_option (F4d-1b)
    "MD4-38": ("gates/lib/bashpolicy.py", "    if type(call) is not GitCall:   # row F4d-1a (R4d-1)", "    if False:   # row F4d-1a (R4d-1)"),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (test_shell_alias_texts_exact_types)
    "MD4-39": ("gates/lib/bashpolicy.py", "    if type(call) is not GitCall:   # row F4d-1a (R4d-1)", "    if not isinstance(call, GitCall):   # row F4d-1a (R4d-1)"),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (the _GitCallSub case)
    "MD4-40": ("gates/lib/bashpolicy.py", "    _check_aliases(aliases)   # row F4d-1a (as ET12)\n", ""),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (_DictSub, mappingproxy, a str-subclass key accepted)
    "MD4-41": ("gates/lib/bashpolicy.py", '# row F4d-1a (R4d-1)\n        raise TypeError("call must be a GitCall")', '# row F4d-1a (R4d-1)\n        raise TypeError("call must be GitCall")'),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (message)
    "MD4-42": ("gates/lib/bashpolicy.py", "    if type(call) is not GitCall:   # row F4d-1b (R4d-1)", "    if False:   # row F4d-1b (R4d-1)"),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (test_expansion_c_option_exact_types)
    "MD4-43": ("gates/lib/bashpolicy.py", "    if type(call) is not GitCall:   # row F4d-1b (R4d-1)", "    if not isinstance(call, GitCall):   # row F4d-1b (R4d-1)"),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (the _GitCallSub case)
    "MD4-44": ("gates/lib/bashpolicy.py", '# row F4d-1b (R4d-1)\n        raise TypeError("call must be a GitCall")', '# row F4d-1b (R4d-1)\n        raise TypeError("call must be GitCall")'),
    # K tests.test_bashpolicy.ExactTypesRound4dTest (message)
    # --- R4d-3, the run_gates member (row F4d-3r, ch/hk8-3b2-fix4d3.md): _function_of_one_argument and its call. The
    # relaxation hasattr(func, ...) -> hasattr(run, ...) is equivalent (a bound method forwards attribute reads to its
    # __func__), so it has no entry.
    # Equivalent mutants (owner rule 2026-11-28; each fact checked on 3.9.6 and 3.13.18 by probe5.py of ch/hk8-3b2-fix4d3.md):
    # dropped hasattr(func, name) -> hasattr(run, name) in _function_of_one_argument: run is func, or a bound method that forwards the four attribute reads to func, or the first operand already refused it
    # dropped type(run) is types.MethodType -> isinstance(run, types.MethodType) in _function_of_one_argument: types.MethodType cannot be subclassed
    # dropped type(func) is not types.FunctionType -> not isinstance(func, types.FunctionType) in _function_of_one_argument: types.FunctionType cannot be subclassed
    # dropped type(target) is not types.FunctionType -> not isinstance(target, types.FunctionType) in _function_of_no_arguments (part d, noted at MD4-13): types.FunctionType cannot be subclassed
    # dropped type(fn) is types.MethodType -> isinstance(fn, types.MethodType) in _function_of_no_arguments (part d): types.MethodType cannot be subclassed
    # dropped type(self.env_refused) is not bool -> not isinstance(self.env_refused, bool) in GitCall.__post_init__ (part d, noted at its entry): bool cannot be subclassed
    "MD4-45": ("gates/lib/bashpolicy.py", '_SIGNATURE_SOURCES = ("__signature__", "__wrapped__", "_partialmethod", "__partialmethod__")', '_SIGNATURE_SOURCES = ("__wrapped__", "_partialmethod", "__partialmethod__")'),
    # K tests.test_bashpolicy.RunGatesRound4dTest (test_run_gates_refused: __signature__ of one parameter on a function of none)
    "MD4-46": ("gates/lib/bashpolicy.py", '_SIGNATURE_SOURCES = ("__signature__", "__wrapped__", "_partialmethod", "__partialmethod__")', '_SIGNATURE_SOURCES = ("__signature__", "_partialmethod", "__partialmethod__")'),
    # K tests.test_bashpolicy.RunGatesRound4dTest (test_run_gates_refused: __wrapped__ of one parameter on a function of none)
    "MD4-47": ("gates/lib/bashpolicy.py", '_SIGNATURE_SOURCES = ("__signature__", "__wrapped__", "_partialmethod", "__partialmethod__")', '_SIGNATURE_SOURCES = ("__signature__", "__wrapped__", "__partialmethod__")'),
    # K tests.test_bashpolicy.RunGatesRound4dTest (test_run_gates_refused: _partialmethod of *a on 3.9, _partialmethod of three on 3.13)
    "MD4-48": ("gates/lib/bashpolicy.py", '_SIGNATURE_SOURCES = ("__signature__", "__wrapped__", "_partialmethod", "__partialmethod__")', '_SIGNATURE_SOURCES = ("__signature__", "__wrapped__", "_partialmethod")'),
    # K tests.test_bashpolicy.RunGatesRound4dTest (test_run_gates_refused: __partialmethod__ of *a on 3.13, of three on 3.9)
    "MD4-49": ("gates/lib/bashpolicy.py", "    func = run.__func__ if type(run) is types.MethodType else run\n", "    func = run\n"),
    # K tests.test_bashpolicy.RunGatesRound4dTest (test_run_gates_accepted: bound method refused)
    "MD4-50": ("gates/lib/bashpolicy.py", "if type(run) is types.MethodType else run", "if callable(run) else run"),
    # K tests.test_bashpolicy.RunGatesRound4dTest (test_run_gates_accepted: a function has no __func__, raw AttributeError)
    "MD4-51": ("gates/lib/bashpolicy.py", "if type(run) is types.MethodType else run", "if type(run) is types.BuiltinMethodType else run"),
    # K tests.test_bashpolicy.RunGatesRound4dTest (test_run_gates_accepted: bound method refused)
    "MD4-52": ("gates/lib/bashpolicy.py", "    if type(func) is not types.FunctionType or any(", "    if False or any("),
    # K tests.test_bashpolicy.RunGatesRound4dTest (test_run_gates_refused: callable object and partial accepted; print on 3.13)
    "MD4-53": ("gates/lib/bashpolicy.py", "    if type(func) is not types.FunctionType or any(", "    if not callable(func) or any("),
    # K tests.test_bashpolicy.RunGatesRound4dTest (test_run_gates_refused: callable object of one argument accepted)
    "MD4-54": ("gates/lib/bashpolicy.py", "    if type(func) is not types.FunctionType or any(", "    if type(func) is not types.BuiltinFunctionType or any("),
    # K tests.test_bashpolicy.RunGatesRound4dTest, tests.test_bashpolicy.CommitRefusalsTest (every accepted run_gates refused)
    "MD4-55": ("gates/lib/bashpolicy.py", "types.FunctionType or any(hasattr(func, name) for name in _SIGNATURE_SOURCES):", "types.FunctionType or False:"),
    # K tests.test_bashpolicy.RunGatesRound4dTest (test_run_gates_refused: __signature__ / __wrapped__ of one parameter on a function of none)
    "MD4-56": ("gates/lib/bashpolicy.py", "types.FunctionType or any(hasattr(func, name) for name in _SIGNATURE_SOURCES):", "types.FunctionType and any(hasattr(func, name) for name in _SIGNATURE_SOURCES):"),
    # K tests.test_bashpolicy.RunGatesRound4dTest (test_run_gates_refused: callable object accepted)
    "MD4-57": ("gates/lib/bashpolicy.py", "_SIGNATURE_SOURCES):\n        return False\n", "_SIGNATURE_SOURCES):\n        return True\n"),
    # K tests.test_bashpolicy.RunGatesRound4dTest (test_run_gates_refused: callable object, print, len accepted)
    "MD4-58": ("gates/lib/bashpolicy.py", "        inspect.signature(run).bind(None)\n", "        inspect.signature(run).bind()\n"),
    # K tests.test_bashpolicy.RunGatesRound4dTest (test_run_gates_accepted: lambda root refused)
    "MD4-59": ("gates/lib/bashpolicy.py", "        inspect.signature(run).bind(None)\n", "        inspect.signature(run).bind(None, None)\n"),
    # K tests.test_bashpolicy.RunGatesRound4dTest (test_run_gates_accepted: lambda root refused)
    "MD4-60": ("gates/lib/bashpolicy.py", "        inspect.signature(run).bind(None)\n", "        inspect.signature(func).bind(None)\n"),
    # K tests.test_bashpolicy.RunGatesRound4dTest (test_run_gates_accepted: bound method, its __func__ needs self, refused)
    "MD4-61": ("gates/lib/bashpolicy.py", "    except (TypeError, ValueError):   # no one-argument binding", "    except TypeError:   # no one-argument binding"),
    # K tests.test_bashpolicy.RunGatesRound4dTest (test_run_gates_refused: method of a function of no parameter, raw ValueError)
    "MD4-62": ("gates/lib/bashpolicy.py", "    except (TypeError, ValueError):   # no one-argument binding", "    except ValueError:   # no one-argument binding"),
    # K tests.test_bashpolicy.RunGatesRound4dTest (test_run_gates_refused: no parameter, raw binding TypeError)
    "MD4-63": ("gates/lib/bashpolicy.py", "an unreadable signature\n        return False\n    return True\n", "an unreadable signature\n        return True\n    return True\n"),
    # K tests.test_bashpolicy.RunGatesRound4dTest (test_run_gates_refused: no parameter accepted)
    "MD4-64": ("gates/lib/bashpolicy.py", "an unreadable signature\n        return False\n    return True\n", "an unreadable signature\n        return False\n    return False\n"),
    # K tests.test_bashpolicy.RunGatesRound4dTest, tests.test_bashpolicy.CommitRefusalsTest (every accepted run_gates refused)
    "MD4-65": ("gates/lib/bashpolicy.py", "    if not _function_of_one_argument(run_gates):   # row F4d-3r (R4d-3)", "    if False:   # row F4d-3r (R4d-3)"),
    # K tests.test_bashpolicy.RunGatesRound4dTest (test_run_gates_refused)
    "MD4-66": ("gates/lib/bashpolicy.py", "    if not _function_of_one_argument(run_gates):   # row F4d-3r (R4d-3)", "    if _function_of_one_argument(run_gates):   # row F4d-3r (R4d-3)"),
    # K tests.test_bashpolicy.RunGatesRound4dTest, tests.test_bashpolicy.CommitRefusalsTest (every accepted run_gates refused)
    "MD4-67": ("gates/lib/bashpolicy.py", "_function_of_one_argument(run_gates):   # row F4d-3r", "_function_of_one_argument(lambda root: None):   # row F4d-3r"),
    # K tests.test_bashpolicy.RunGatesRound4dTest (test_run_gates_refused)
    "MD4-68": ("gates/lib/bashpolicy.py", '"run_gates must be a function or method of one argument"', '"run_gates must be callable"'),
    # K tests.test_bashpolicy.RunGatesRound4dTest (test_run_gates_refused: message)
}
KILL = {
    "MD4-1": ("tests.test_bashpolicy",),
    "MD4-2": ("tests.test_bashpolicy",),
    "MD4-3": ("tests.test_bashpolicy",),
    "MD4-4": ("tests.test_bashpolicy",),
    "MD4-5": ("tests.test_bashpolicy",),
    "MD4-6": ("tests.test_bashpolicy",),
    "MD4-7": ("tests.test_bashpolicy",),
    "MD4-8": ("tests.test_bashpolicy",),
    "MD4-9": ("tests.test_bashpolicy",),
    "MD4-10": ("tests.test_bashpolicy",),
    "MD4-11": ("tests.test_bashpolicy",),
    "MD4-12": ("tests.test_bashpolicy",),
    "MD4-13": ("tests.test_bashpolicy",),
    "MD4-14": ("tests.test_bashpolicy",),
    "MD4-15": ("tests.test_bashpolicy",),
    "MD4-16": ("tests.test_bashpolicy",),
    "MD4-17": ("tests.test_bashpolicy",),
    "MD4-18": ("tests.test_bashpolicy",),
    "MD4-19": ("tests.test_bashpolicy",),
    "MD4-20": ("tests.test_bashpolicy",),
    "MD4-21": ("tests.test_bashpolicy",),
    "MD4-22": ("tests.test_bashpolicy",),
    "MD4-23": ("tests.test_bashpolicy",),
    "MD4-24": ("tests.test_bashpolicy",),
    "MD4-25": ("tests.test_bashpolicy",),
    "MD4-26": ("tests.test_bashpolicy",),
    "MD4-27": ("tests.test_bashpolicy",),
    "MD4-28": ("tests.test_bashpolicy",),
    "MD4-29": ("tests.test_bashpolicy",),
    "MD4-30": ("tests.test_bashpolicy",),
    "MD4-31": ("tests.test_bashpolicy",),
    "MD4-32": ("tests.test_bashpolicy",),
    "MD4-33": ("tests.test_bashpolicy",),
    "MD4-34": ("tests.test_bashpolicy",),
    "MD4-35": ("tests.test_bashpolicy",),
    "MD4-36": ("tests.test_bashpolicy",),
    "MD4-37": ("tests.test_bashpolicy",),
    "MD4-38": ("tests.test_bashpolicy",),
    "MD4-39": ("tests.test_bashpolicy",),
    "MD4-40": ("tests.test_bashpolicy",),
    "MD4-41": ("tests.test_bashpolicy",),
    "MD4-42": ("tests.test_bashpolicy",),
    "MD4-43": ("tests.test_bashpolicy",),
    "MD4-44": ("tests.test_bashpolicy",),
    "MD4-45": ("tests.test_bashpolicy",),
    "MD4-46": ("tests.test_bashpolicy",),
    "MD4-47": ("tests.test_bashpolicy",),
    "MD4-48": ("tests.test_bashpolicy",),
    "MD4-49": ("tests.test_bashpolicy",),
    "MD4-50": ("tests.test_bashpolicy",),
    "MD4-51": ("tests.test_bashpolicy",),
    "MD4-52": ("tests.test_bashpolicy",),
    "MD4-53": ("tests.test_bashpolicy",),
    "MD4-54": ("tests.test_bashpolicy",),
    "MD4-55": ("tests.test_bashpolicy",),
    "MD4-56": ("tests.test_bashpolicy",),
    "MD4-57": ("tests.test_bashpolicy",),
    "MD4-58": ("tests.test_bashpolicy",),
    "MD4-59": ("tests.test_bashpolicy",),
    "MD4-60": ("tests.test_bashpolicy",),
    "MD4-61": ("tests.test_bashpolicy",),
    "MD4-62": ("tests.test_bashpolicy",),
    "MD4-63": ("tests.test_bashpolicy",),
    "MD4-64": ("tests.test_bashpolicy",),
    "MD4-65": ("tests.test_bashpolicy",),
    "MD4-66": ("tests.test_bashpolicy",),
    "MD4-67": ("tests.test_bashpolicy",),
    "MD4-68": ("tests.test_bashpolicy",),
}
