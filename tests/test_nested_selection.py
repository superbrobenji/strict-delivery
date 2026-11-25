"""Tests of Task CI2 row N1: the nested run of ``tests.test_self_adoption.CopyTest.test_suite_needs_no_local_main`` holds
exactly the tests of tests.test_run_all and tests.test_self_adoption whose path can resolve a base branch or ``main`` of
the clone, and every test it leaves out names the checkout only to read a file or load its config."""
import inspect
import re
import unittest

from tests import test_self_adoption
from tests.test_self_adoption import NESTED_MODULES, NESTED_SELECT, nested_ids

# hand-written from a grep of the two modules (tests that run git or the gates with cwd, -C, a root or a clone of REPO)
EXPECTED = [
    "tests.test_run_all.ArgvTest.test_module_run_end_to_end",
    "tests.test_run_all.BaseTest.test_absent_base_ref_real_gates",
    "tests.test_run_all.BaseTest.test_dash_leading_base_forwarded_as_one_token",
    "tests.test_run_all.BaseTest.test_dash_leading_root_forwarded_as_one_token",
    "tests.test_run_all.VersionLineTest.test_real_repo_passes_with_the_version_line_last",
    "tests.test_self_adoption.ConfigTest.test_config_only_four_keys_added",
    "tests.test_self_adoption.CopyTest.test_hooks_in_a_disposable_clone",
    "tests.test_self_adoption.CopyTest.test_run_all_passes_on_a_copy_with_main",
    "tests.test_self_adoption.CopyTest.test_run_all_shallow_clone_fails_closed",
    "tests.test_self_adoption.CopyTest.test_shim_fails_closed_when_framework_lacks_githook",
    "tests.test_self_adoption.CopyTest.test_suite_needs_no_local_main",
]
# the forms in which a test left out of the nested run may name the checkout: reading a file, the plugin path for a
# subprocess, loading the config, running the schema check (it resolves no base)
READ_ONLY_USES = (r"os\.path\.join\(REPO,", r"PYTHONPATH=REPO", r"config\.load\(REPO\)", r"\"--root\", REPO\]")


def sources(selected):
    """(id, source) of every test of the nested modules; ``selected`` picks the ones the rule keeps or leaves out."""
    import importlib
    out = []

    def walk(suite):
        for item in suite:
            if isinstance(item, unittest.TestSuite):
                walk(item)
            else:
                src = inspect.getsource(getattr(type(item), item._testMethodName))
                if bool(NESTED_SELECT.search(src)) == selected:
                    out.append((item.id(), src))
    for name in NESTED_MODULES:
        walk(unittest.defaultTestLoader.loadTestsFromModule(importlib.import_module(name)))
    return out


class NestedSelectionTest(unittest.TestCase):
    def test_n1_selection_is_the_listed_tests(self):  # N1
        self.assertEqual(sorted(nested_ids()), EXPECTED)

    def test_n1_the_test_itself_is_in_the_selection(self):  # N1: the nested run re-checks that the clone has no main
        self.assertIn("tests.test_self_adoption.CopyTest.test_suite_needs_no_local_main", nested_ids())

    def test_n1_left_out_tests_do_not_run_git_on_the_checkout(self):  # N1
        left_out = sources(False)
        self.assertGreater(len(left_out), 100)
        for tid, src in left_out:
            with self.subTest(tid):
                rest = src
                for form in READ_ONLY_USES:
                    rest = re.sub(form, "", rest)
                self.assertIsNone(re.search(r"\bREPO\b", rest), tid)

    def test_n1_every_test_is_in_or_out(self):  # N1: nothing is lost between the two lists
        kept, out = sources(True), sources(False)
        self.assertEqual(sorted(i for i, _ in kept), EXPECTED)
        total = 0
        for name in NESTED_MODULES:
            import importlib
            total += unittest.defaultTestLoader.loadTestsFromModule(importlib.import_module(name)).countTestCases()
        self.assertEqual(len(kept) + len(out), total)

    def test_n1_select_pattern_is_the_rule(self):  # N1: a pattern that matches nothing selects nothing
        self.assertEqual(nested_ids(NESTED_MODULES, re.compile(r"no test says this \(")), [])
        self.assertIs(test_self_adoption.NESTED_SELECT, NESTED_SELECT)

    def test_n1_every_alternative_of_the_rule_matches_its_form(self):  # N1: no alternative is dead weight
        forms = {
            "clone_copy": "clone = self.clone_copy('x', main=False)",
            "gates_run_all": "code, out = self.gates_run_all(clone)",
            "self.sub(": "out, code = self.sub([])",
            "has_local_main": "self.assertFalse(self.has_local_main(clone))",
            "cwd=REPO": "subprocess.run(argv, cwd=REPO)",
            "-C REPO": 'subprocess.run(["git", "-C", REPO, "show", x])',
            "git(REPO": 'names = git(REPO, "ls-files")',
        }
        for name, text in forms.items():
            with self.subTest(name):
                self.assertIsNotNone(NESTED_SELECT.search(text))
                rest = NESTED_SELECT.sub("", text)
                self.assertIsNone(NESTED_SELECT.search(rest))
        for text in ("root = make_repo(self.work)", "out, code = self.run_main(['--root', root])",
                     "config.load(REPO)", "os.path.join(REPO, 'gates')"):
            self.assertIsNone(NESTED_SELECT.search(text), text)
