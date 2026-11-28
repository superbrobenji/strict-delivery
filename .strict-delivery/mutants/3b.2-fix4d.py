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
}
