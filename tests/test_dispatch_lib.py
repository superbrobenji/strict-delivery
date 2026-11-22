"""Tests of gates/lib/dispatch.py (plan Task 2c.3; rows K1-K9, E1-E7, P1-P2, H1-H9, M2, M9, S1-S15 of the input-domain
table task-2c.3-domain.md). Every expected value is written out here by hand from the plan and the spec, never read
back from ``dispatch``. The git rows run on real fixture repositories (``GitIsolatedTestCase``)."""
import os
import unittest
from unittest import mock

from gates.lib import dispatch, gitinfo, migrations
from gates.lib.dispatch import (CONTROLLER_ROLES, DISPATCHERS, HEADINGS, LEVELS_BELOW, MIN_TIERS, ROLES, SMALL_ROLES,
                                block_errors, depth_ok, limits_of, min_tier, model_line, parse, role_of, small_errors,
                                small_line, small_tier, tier_of)
from gates.lib.result import GateError
from tests.helpers import (INT_LIMITS, GitIsolatedTestCase, commit_all, git, int_limit, make_repo, minimal_config,
                           write_record)

WORKERS = ("implementer", "implementer_transcription", "task_reviewer", "final_reviewer", "final_verifier",
           "exception_reviewer", "audit_reviewer", "audit_verifier", "investigator", "plan_writer", "plan_reviewer",
           "drafter")


# The dispatcher table of plan P:2076-2085, written out by hand: for each program_live and each of the fifteen child
# roles, the literal tuple of dispatcher ids allowed to dispatch it. Nothing here is computed.
EXPECTED = {
    True: {
        "program_controller": ("session",),
        "stream_controller": ("session", "program_controller"),
        "controller": ("stream_controller", "controller"),
        "implementer": ("stream_controller", "controller"),
        "implementer_transcription": ("stream_controller", "controller"),
        "task_reviewer": ("stream_controller", "controller"),
        "final_reviewer": ("stream_controller", "controller"),
        "final_verifier": ("stream_controller", "controller"),
        "exception_reviewer": ("stream_controller", "controller"),
        "audit_reviewer": ("stream_controller", "controller"),
        "audit_verifier": ("stream_controller", "controller"),
        "investigator": ("stream_controller", "controller"),
        "plan_writer": ("stream_controller", "controller"),
        "plan_reviewer": ("stream_controller", "controller"),
        "drafter": ("stream_controller", "controller"),
    },
    False: {
        "program_controller": (),
        "stream_controller": (),
        "controller": ("session", "controller"),
        "implementer": ("session", "controller"),
        "implementer_transcription": ("session", "controller"),
        "task_reviewer": ("session", "controller"),
        "final_reviewer": ("session", "controller"),
        "final_verifier": ("session", "controller"),
        "exception_reviewer": ("session", "controller"),
        "audit_reviewer": ("session", "controller"),
        "audit_verifier": ("session", "controller"),
        "investigator": ("session", "controller"),
        "plan_writer": ("session", "controller"),
        "plan_reviewer": ("session", "controller"),
        "drafter": ("session", "controller"),
    },
}


class ConstantsTest(unittest.TestCase):
    def test_roles_literal(self):                                   # K1, spec section 10, Q-H1
        self.assertEqual(ROLES, ("program_controller", "stream_controller", "controller", "implementer",
                                 "implementer_transcription", "task_reviewer", "final_reviewer", "final_verifier",
                                 "exception_reviewer", "audit_reviewer", "audit_verifier", "investigator",
                                 "plan_writer", "plan_reviewer", "drafter"))

    def test_min_tiers_literal(self):                               # K2
        self.assertEqual(MIN_TIERS, {"implementer_transcription": 1, "implementer": 2, "controller": 3,
                                     "program_controller": 3, "stream_controller": 3, "task_reviewer": 2,
                                     "final_reviewer": 3, "audit_reviewer": 3, "audit_verifier": 3, "investigator": 3,
                                     "final_verifier": 4, "exception_reviewer": 4, "plan_writer": 3,
                                     "plan_reviewer": 3, "drafter": 2})

    def test_controller_roles_literal(self):                        # K3
        self.assertEqual(CONTROLLER_ROLES, ("program_controller", "stream_controller", "controller"))

    def test_headings_literal(self):                                # K4
        self.assertEqual(HEADINGS, ("## Role", "## Brief", "## Findings", "## Claims",
                                    "## Budget: tokens=<n> minutes=<n>", "## Model", "## Report", "## Strict block",
                                    "## Task"))

    def test_small_roles_task_reviewer_only(self):                  # K5, Q-RD-12 (a)
        self.assertEqual(SMALL_ROLES, ("task_reviewer",))

    def test_levels_below_literal(self):                            # K6
        self.assertEqual(LEVELS_BELOW, {"program_controller": 2, "stream_controller": 1, "controller": 1})

    def test_dispatchers_all_triples(self):                         # K8, K9: 2 x 16 x 15 = 480 cells
        self.assertEqual(set(EXPECTED), {True, False})
        for live in (True, False):
            self.assertEqual(tuple(EXPECTED[live]), ROLES)          # the table names each of the 15 roles, in order
            self.assertEqual(set(DISPATCHERS[live]), set(ROLES))
        n = 0
        for live in (True, False):
            for d in ROLES + ("session",):
                for child in ROLES:
                    with self.subTest(live=live, dispatcher=d, child=child):
                        n += 1
                        self.assertEqual(d in DISPATCHERS[live][child], d in EXPECTED[live][child])
        self.assertEqual(n, 480)
        for live in (True, False):                                  # the literal tuples too (the gate prints them)
            for child in ROLES:
                with self.subTest(live=live, child=child):
                    self.assertEqual(tuple(DISPATCHERS[live][child]), EXPECTED[live][child])

    def test_program_session_may_not_dispatch_workers(self):       # F-B2p2-5
        self.assertNotIn("session", DISPATCHERS[True]["implementer"])
        self.assertIn("session", DISPATCHERS[False]["implementer"])
        self.assertEqual(DISPATCHERS[False]["program_controller"], ())
        self.assertEqual(DISPATCHERS[False]["stream_controller"], ())

    def test_workers_dispatch_nobody(self):                         # K9
        for w in WORKERS:
            for live in (True, False):
                for child in ROLES:
                    self.assertNotIn(w, DISPATCHERS[live][child])


class LimitsTest(unittest.TestCase):
    D, C = "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH", "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS"

    def test_limits_measured_mapping(self):
        """Measured by the coordinator 2026-11-01 (plan P:1289): depth unset gives levels 1-2 the Agent tool (limit 3),
        depth 5 gives levels 1-5 (limit 6); concurrency unset refuses past 20, set to 30 ran 25."""
        self.assertEqual((dispatch.CLAUDE_DEFAULT_DEPTH, dispatch.CLAUDE_DEFAULT_CONCURRENT), (3, 20))   # K7
        self.assertEqual(limits_of({}, {}), (3, 20))                                                      # E1
        for n, want in (("1", 2), ("2", 3), ("5", 6)):                                                    # E2
            self.assertEqual(limits_of({}, {self.D: n})[0], want)
        for n, want in (("1", 1), ("30", 30)):                                                            # E3
            self.assertEqual(limits_of({}, {self.C: n})[1], want)
        self.assertEqual(limits_of({"limits": {"max_depth": 5, "max_concurrent": 30}}, {}), (3, 20))      # E6

    def test_limits_env_refused(self):                              # E4
        for bad in ("0", "-1", "abc", "", " 5", "5 ", "05", "+5", "5.0", "٥", "５", "1_0", "5\n", "\U0001FAE8"):
            for name in (self.D, self.C):
                with self.subTest(name=name, value=bad[:12]):
                    with self.assertRaises(ValueError) as e:
                        limits_of({}, {name: bad})
                    self.assertIn(name, str(e.exception))

    def test_limits_env_digit_cap(self):                            # I4, K1: 600 digits accepted, 601 or more refused
        """G3: one cap of 600 digits, below 640 (the lowest PYTHONINTMAXSTRDIGITS CPython accepts), so int() never
        raises and the verdict is the same under every limit setting."""
        for lim in INT_LIMITS:
            with int_limit(lim):
                for name in (self.D, self.C):
                    for n in (601, 700, 4300, 4301):
                        with self.subTest(limit=lim, name=name, digits=n):
                            with self.assertRaises(ValueError) as e:
                                limits_of({}, {name: "9" * n})
                            self.assertEqual(str(e.exception), "%s must be a decimal integer of at least 1 (digits 0-9 "
                                             "only, no sign, space or leading zero, at most 600 digits)" % name)
                with self.subTest(limit=lim, digits=600, name="concurrent"):
                    self.assertEqual(limits_of({}, {self.C: "9" * 600})[1], 10 ** 600 - 1)
                with self.subTest(limit=lim, digits=600, name="depth"):
                    self.assertEqual(limits_of({}, {self.D: "9" * 600})[0], 10 ** 600)    # d + 1 has 601 digits

    def test_limits_effective_minimum(self):                        # E5
        for cfgv, env, want in ((5, "5", 5), (6, "5", 6), (7, "5", 6), (2, "5", 2), (3, None, 3), (1, None, 1)):
            e = {} if env is None else {self.D: env}
            self.assertEqual(limits_of({"limits": {"max_depth": cfgv}}, e)[0], want)
        for cfgv, env, want in ((10, "30", 10), (30, "30", 30), (40, "30", 30), (25, None, 20), (5, None, 5)):
            e = {} if env is None else {self.C: env}
            self.assertEqual(limits_of({"limits": {"max_concurrent": cfgv}}, e)[1], want)

    def test_limits_sources(self):                                  # E7
        self.assertEqual(limits_of({"limits": {"max_depth": 4}}, {self.D: "9"}), (4, 20))   # both
        self.assertEqual(limits_of({}, {self.D: "9"}), (10, 20))                            # env only
        self.assertEqual(limits_of({"limits": {"max_depth": 2}}, {}), (2, 20))              # config only
        self.assertEqual(limits_of({}, {}), (3, 20))                                        # neither

    def test_controller_needs_levels_below(self):                   # P1, P2: every cell written out
        # The literal set of dispatcher levels that pass, per role kind, written by hand (P:2090-2092: a program
        # controller needs two levels below it, a stream or sub-controller one, a worker none).
        passing = {
            3: {"program_controller": (0,), "stream_controller": (0, 1), "controller": (0, 1), "worker": (0, 1, 2)},
            6: {"program_controller": (0, 1, 2, 3), "stream_controller": (0, 1, 2, 3, 4), "controller": (0, 1, 2, 3, 4),
                "worker": (0, 1, 2, 3, 4, 5)},
        }
        kinds = {"program_controller": ("program_controller",), "stream_controller": ("stream_controller",),
                 "controller": ("controller",), "worker": WORKERS}
        self.assertEqual(len(WORKERS), 12)
        self.assertEqual(set(WORKERS) | set(CONTROLLER_ROLES), set(ROLES))
        cells = 0
        for limit in (3, 6):
            for kind, roles in kinds.items():
                for role in roles:
                    for level in range(0, limit + 1):
                        with self.subTest(limit=limit, role=role, level=level):
                            cells += 1
                            self.assertEqual(depth_ok(role, level, limit), level in passing[limit][kind])
        self.assertEqual(cells, 15 * 4 + 15 * 7)
        self.assertTrue(depth_ok("program_controller", 0, 3) and not depth_ok("program_controller", 1, 3))
        self.assertTrue(depth_ok("controller", 1, 3) and not depth_ok("controller", 2, 3))
        self.assertTrue(depth_ok("implementer", 2, 3) and not depth_ok("implementer", 3, 3))


def good_prompt(role="implementer", block="BLOCK\n", model="sonnet", brief="b", findings="", claims="x"):
    return ("## Role\n%s\n\n## Brief\n%s\n\n## Findings\n%s\n\n## Claims\n%s\n\n"
            "## Budget: tokens=1000 minutes=10\n\n## Model\n%s\n\n## Report\nr\n\n## Strict block\n\n%s\n"
            "## Task\nt\n" % (role, brief, findings, claims, model, block))


class GrammarTest(unittest.TestCase):
    def test_headings_exact_order(self):                            # H1
        sections, errors = parse(good_prompt())
        self.assertEqual(errors, [])
        self.assertEqual(list(sections), ["Role", "Brief", "Findings", "Claims", "Budget", "Model", "Report",
                                          "Strict block", "Task"])
        self.assertEqual(sections["Strict block"], "\nBLOCK\n\n")
        self.assertEqual(sections["Role"], "implementer\n\n")

    def swap(self, a, b):
        t = good_prompt()
        return t.replace(a, "@@").replace(b, a).replace("@@", b)

    def test_headings_malformed(self):                              # H2-H5
        good = good_prompt()
        cases = {
            "missing Role": good.replace("## Role\n", ""), "missing Task": good.replace("## Task\n", ""),
            "swapped": self.swap("## Brief", "## Role"),
            "duplicated": good + "## Task\nagain\n", "extra": good.replace("## Report\n", "## X\n## Report\n"),
            "heading inside brief": good.replace("\nb\n", "\n## Role\n", 1),
            "##Role": good.replace("## Role", "##Role"), "### Role": good.replace("## Role", "### Role"),
            "preamble": "hello\n" + good, "BOM": "﻿" + good, "blank line first": "\n" + good,
            "CRLF": good.replace("\n", "\r\n"), "empty": "",
        }
        for name, text in cases.items():
            with self.subTest(name):
                self.assertTrue(parse(text)[1], name)
        self.assertTrue(any("preamble" in e for e in parse("hello\n" + good)[1]))
        self.assertTrue(any("missing heading ## Role" in e for e in parse(good.replace("## Role\n", ""))[1]))

    def test_budget_forms(self):                                    # H6
        good = good_prompt()
        ok = "## Budget: tokens=1000 minutes=10"
        for bad in ("## Budget: tokens=0 minutes=10", "## Budget: tokens=01 minutes=10", "## Budget: tokens=-1 minutes=10",
                    "## Budget: tokens=1.5 minutes=10", "## Budget: tokens=1000", "## Budget:  tokens=1000 minutes=10",
                    "## Budget: tokens=1000 minutes=10 ", "## Budget", "## Budget: tokens=1000 minutes=0",
                    "## Budget: tokens=%s minutes=10" % ("1" * 4301 + "x"), "## Budget: tokens=١ minutes=10"):
            with self.subTest(bad[:40]):
                errors = parse(good.replace(ok, bad))[1]
                self.assertTrue(any("budget heading" in e for e in errors), errors)
        self.assertEqual(parse(good.replace(ok, "## Budget: tokens=%s minutes=10" % ("1" * 4301)))[1], [])  # regex only

    def test_role_of(self):                                         # H7
        self.assertEqual(role_of("implementer"), "implementer")
        self.assertEqual(role_of("\nimplementer\n"), "implementer")
        self.assertEqual(role_of("implementer\nthen more text\n"), "implementer")
        for r in ROLES:
            self.assertEqual(role_of(r + "\n"), r)
        for bad in ("implementer extra", " implementer", "implementor", "Implementer", "", "\n\n", "implementer\r",
                    "ࡰ", "some prose\nimplementer"):
            with self.subTest(bad):
                with self.assertRaises(ValueError):
                    role_of(bad)

    def test_model_line(self):                                      # M1: D8
        self.assertEqual(model_line("sonnet\n\n"), "sonnet")
        self.assertEqual(model_line("\nsonnet\n"), "sonnet")
        for bad in ("", "\n", "a\nb\n", "a\n\nb\n"):
            self.assertIsNone(model_line(bad))


class BlockTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.d = os.path.realpath(td.name)
        self.text = "# Strict block: implementer\n\nbody\n"
        with open(os.path.join(self.d, "implementer.md"), "w", encoding="utf-8", newline="") as f:
            f.write(self.text)
        with open(os.path.join(self.d, "controller.md"), "w", encoding="utf-8", newline="") as f:
            f.write("# Strict block: controller\n")

    def test_block_byte_for_byte(self):                             # H8
        self.assertEqual(block_errors("\n" + self.text + "\n", "implementer", self.d), [])
        self.assertTrue(block_errors("\n" + self.text + " \n", "implementer", self.d))

    def test_block_variants(self):                                  # H8
        t = self.text
        for name, body in (("trailing space", "\n" + t.replace("body", "body ") + "\n"), ("no final empty line", "\n" + t),
                           ("no leading empty line", t + "\n"), ("CRLF", ("\n" + t + "\n").replace("\n", "\r\n")),
                           ("another role's block", "\n# Strict block: controller\n\n"), ("empty", "")):
            with self.subTest(name):
                self.assertEqual(len(block_errors(body, "implementer", self.d)), 1)
        missing = block_errors("\n" + t + "\n", "program_controller", self.d)    # no file before Task P4.x
        self.assertEqual(len(missing), 1)
        self.assertIn(os.path.join(self.d, "program_controller.md"), missing[0])


class TierTest(unittest.TestCase):
    def cfg(self, **tiers):
        c = minimal_config()
        c["models"] = {"tiers": tiers}
        return c

    def test_tier_of(self):                                         # M2
        c = self.cfg(tier1="h", tier2="s", tier3="o")
        self.assertEqual([tier_of(m, c) for m in ("h", "s", "o", "x", "S")], [1, 2, 3, None, None])
        c4 = self.cfg(tier1="h", tier2="s", tier3="o", tier4="f")
        self.assertEqual(tier_of("f", c4), 4)
        self.assertEqual(tier_of("f", c), None)                     # tier4 unset: nothing names it

    def test_model_in_two_tiers_is_error(self):                     # M2
        with self.assertRaises(ValueError):
            tier_of("m", {"models": {"tiers": {"tier3": "m", "tier4": "m"}}})

    def test_min_tier_unset_tier4(self):                            # M4, M8
        c = self.cfg(tier1="h", tier2="s", tier3="o")
        self.assertEqual(min_tier("final_verifier", c), 3)
        self.assertEqual(min_tier("exception_reviewer", c), 3)
        c["top_tier_fallback"] = "tier2"
        self.assertEqual(min_tier("final_verifier", c), 2)
        for bad in ("tier9", "tier4", "", "opus", 3, 3.0, True, None, ["tier3"], ("tier3",), {"tier3": 1}, b"tier3"):
            c["top_tier_fallback"] = bad                            # F-2c3-R1-3: any non-str is a ValueError too
            for role in ("final_verifier", "exception_reviewer"):
                with self.subTest(fallback=repr(bad), role=role):
                    with self.assertRaises(ValueError) as e:
                        min_tier(role, c)
                    self.assertEqual(str(e.exception), "top_tier_fallback '%s' names a tier that is unset or not "
                                     "tier1-tier4" % (bad,))
            self.assertEqual(min_tier("controller", c), 3)          # a role whose minimum is below tier4 never reads it
            self.assertEqual(min_tier("implementer", c), 2)
        c["top_tier_fallback"] = "tier3"
        c["top_tier_roles"] = ["exception_reviewer"]
        with self.assertRaises(ValueError):
            min_tier("final_verifier", c)                           # needs tier4, which is unset
        self.assertEqual(min_tier("controller", c), 3)

    def test_min_tier_set_tier4(self):                              # M5: the fallback is ignored
        c = self.cfg(tier1="h", tier2="s", tier3="o", tier4="f")
        c["top_tier_fallback"] = "tier9"
        self.assertEqual(min_tier("final_verifier", c), 4)
        for role, want in MIN_TIERS.items():
            self.assertEqual(min_tier(role, c), want)

    def test_small_tier_from_config(self):                          # M9
        from gates.lib import config
        self.assertEqual(config.DEFAULTS["reviews"]["small"]["tier"], "tier2")        # the default, Q-RD-10 (b)
        self.assertEqual(small_tier("task_reviewer", {"reviews": config.DEFAULTS["reviews"]}), 2)
        for name, want in (("tier1", 1), ("tier2", 2), ("tier3", 3)):
            self.assertEqual(small_tier("task_reviewer", {"reviews": {"small": {"tier": name}}}), want)


LINE = "small-re-review: plan=2026-10-31-x task=2c.3 round=2 fix=%s..%s narrowed=none questions=none prev-fix-defects=0"
A7, B40 = "abcdef0", "0123456789abcdef0123456789abcdef01234567"


class SmallLineTest(unittest.TestCase):
    def test_small_line_parsed_and_malformed_refused(self):         # S1-S4, S11
        self.assertIsNone(small_line("no line here\nsmall-re-review:no space\n"))      # S1
        got = small_line("intro\n" + LINE % (A7, B40) + "\ntail")
        self.assertEqual(got, {"plan": "2026-10-31-x", "task": "2c.3", "round": 2, "fix": (A7, B40), "narrowed": [],
                               "questions": "none", "prev-fix-defects": 0})        # S2
        self.assertEqual(small_line((LINE % (A7, B40)).replace("narrowed=none", "narrowed=1,3"))["narrowed"], ["1", "3"])
        ok = LINE % (A7, B40)
        bad = {
            "plan missing": ok.replace("plan=2026-10-31-x ", ""), "task missing": ok.replace("task=2c.3 ", ""),
            "round missing": ok.replace("round=2 ", ""), "fix missing": ok.replace("fix=%s..%s " % (A7, B40), ""),
            "narrowed missing": ok.replace("narrowed=none ", ""), "questions missing": ok.replace("questions=none ", ""),
            "prev missing": ok.replace(" prev-fix-defects=0", ""),
            "swapped": ok.replace("plan=2026-10-31-x task=2c.3", "task=2c.3 plan=2026-10-31-x"),
            "repeated": ok + " round=2", "round=0": ok.replace("round=2", "round=0"),
            "round=05": ok.replace("round=2", "round=05"),
            "6-char sha": ok.replace(A7, "abcdef"), "41-char sha": ok.replace(B40, B40 + "0"),
            "uppercase": ok.replace(A7, "ABCDEF0"), "narrowed empty": ok.replace("narrowed=none", "narrowed="),
            "narrowed 1,,2": ok.replace("narrowed=none", "narrowed=1,,2"), "narrowed 01": ok.replace("narrowed=none", "narrowed=01"),
            "two spaces": ok.replace("round=2 fix", "round=2  fix"), "trailing space": ok + " ",
            "unknown key": ok + " extra=1", "questions other": ok.replace("questions=none", "questions=1"),
            "prev other": ok.replace("prev-fix-defects=0", "prev-fix-defects=1"),
            "unicode": ok.replace("2c.3", "2cࡰ"),
        }
        for name, line in bad.items():
            with self.subTest(name):
                with self.assertRaises(ValueError):
                    small_line(line)
        with self.assertRaises(ValueError):
            small_line(ok + "\n" + ok)                                                  # S4
        self.assertEqual(small_line(ok.replace("round=2", "round=5"))["round"], 5)       # parses; refused by S8

    def test_round_and_narrowed_digits(self):                       # I1, I2, K1: [1-9][0-9]* of up to 600 digits (G1)
        ok = LINE % (A7, B40)
        for lim in INT_LIMITS:
          with int_limit(lim):
            for n in (1, 9, 10, 11, 600):
                digits = "1" + "0" * (n - 1)
                with self.subTest(limit=lim, n=n, key="round"):
                    got = small_line(ok.replace("round=2", "round=" + digits))
                    self.assertEqual((len(str(got["round"])), got["round"] == 10 ** (n - 1)), (n, True))
                with self.subTest(limit=lim, n=n, key="narrowed one"):
                    got = small_line(ok.replace("narrowed=none", "narrowed=" + digits))
                    self.assertEqual(got["narrowed"], [digits])
                with self.subTest(limit=lim, n=n, key="narrowed list"):
                    got = small_line(ok.replace("narrowed=none", "narrowed=3,%s,%s" % (digits, digits)))
                    self.assertEqual(got["narrowed"], ["3", digits, digits])
            for n in (601, 700, 4300, 4301):
                long_ = "1" + "0" * (n - 1)
                for key, text in (("round", ok.replace("round=2", "round=" + long_)),
                                  ("narrowed", ok.replace("narrowed=none", "narrowed=" + long_)),
                                  ("narrowed", ok.replace("narrowed=none", "narrowed=2,%s" % long_)),
                                  ("narrowed", ok.replace("narrowed=none", "narrowed=%s,2" % long_))):
                    with self.subTest(limit=lim, n=n, key=key, shape=text[40:60]):
                        with self.assertRaises(ValueError) as e:
                            small_line(text)
                        self.assertEqual(str(e.exception), "small-re-review: key %s is malformed" % key)
            for key, text in (("round", ok.replace("round=2", "round=٥")),
                              ("round", ok.replace("round=2", "round=５")),
                              ("round", ok.replace("round=2", "round=\U0001FAE8")),
                              ("narrowed", ok.replace("narrowed=none", "narrowed=1,\U0001FAE8")),
                              ("narrowed", ok.replace("narrowed=none", "narrowed=1,٥"))):   # K2: ASCII digits only
                with self.subTest(limit=lim, key=key, shape="non-ASCII digit"):
                    with self.assertRaises(ValueError) as e:
                        small_line(text)
                    self.assertEqual(str(e.exception), "small-re-review: key %s is malformed" % key)
        for key, text in (("round", ok.replace("round=2", "round=0" + "1" * 10)),
                          ("narrowed", ok.replace("narrowed=none", "narrowed=1,0" + "1" * 10))):
            with self.subTest(key=key, shape="leading zero"):
                with self.assertRaises(ValueError) as e:
                    small_line(text)
                self.assertEqual(str(e.exception), "small-re-review: key %s is malformed" % key)

    def test_named_key(self):
        with self.assertRaises(ValueError) as e:
            small_line((LINE % (A7, B40)).replace("round=2", "round=0"))
        self.assertIn("round", str(e.exception))


FTAG = "finding/%d" % migrations.current_version("finding")


class SmallErrorsTest(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = make_repo(self.work)
        self.cfg = self.load_cfg()
        self.fid = "F-20261031-k3f9"
        self.base = self.commit({"src/a.txt": "1\n"})

    def load_cfg(self):
        from gates.lib import config
        return config.load(self.root)

    def commit(self, files, msg="c"):
        for rel, text in files.items():
            p = os.path.join(self.root, *rel.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(text if isinstance(text, bytes) else text.encode("utf-8"))
        return commit_all(self.root, msg)

    def finding(self, fid, severity):
        write_record(self.root, ".strict-delivery/state/findings/%s.yml" % fid,
                     {"schema": FTAG, "id": fid, "severity": severity})
        commit_all(self.root, "finding")

    def line(self, a, b, **kw):
        d = {"plan": "p", "task": "t", "round": 2, "fix": (a, b), "narrowed": [], "questions": "none",
             "prev-fix-defects": 0}
        d.update(kw)
        return d

    def fix(self, files):
        a = git(self.root, "rev-parse", "HEAD")
        b = self.commit(files)
        return a, b

    def test_small_errors_thresholds(self):                         # S6
        for n, ok in ((149, True), (150, True), (151, False)):
            with self.subTest(lines=n):
                a, b = self.fix({"src/l%d.txt" % n: "x\n" * n})
                self.finding(self.fid, "LOW")
                got = small_errors(self.line(a, b), [self.fid], self.root, self.cfg)
                self.assertEqual(got == [], ok, got)
                if not ok:
                    self.assertIn("max_lines", got[0])
        for n, ok in ((3, True), (4, True), (5, False)):
            with self.subTest(files=n):
                a, b = self.fix({"src/f%d_%d.txt" % (n, i): "x\n" for i in range(n)})
                got = small_errors(self.line(a, b), [self.fid], self.root, self.cfg)
                self.assertEqual(got == [], ok, got)
        cfg = dict(self.cfg, reviews={"small": dict(self.cfg["reviews"]["small"], max_files=1)})
        for n, ok in ((1, True), (2, False)):
            a, b = self.fix({"src/m%d_%d.txt" % (n, i): "x\n" for i in range(n)})
            self.assertEqual(small_errors(self.line(a, b), [self.fid], self.root, cfg) == [], ok)

    def test_small_errors_diff_kinds(self):                         # S7
        a, b = self.fix({"src/bin.dat": b"\x00\x01\x02\xff\n"})
        self.finding(self.fid, "MEDIUM")
        got = small_errors(self.line(a, b), [self.fid], self.root, self.cfg)
        self.assertEqual(got, ["fix changes the binary file src/bin.dat"])
        git(self.root, "mv", "src/a.txt", "src/renamed.txt")
        a = git(self.root, "rev-parse", "HEAD")
        b = commit_all(self.root, "rename")
        cfg = dict(self.cfg, reviews={"small": dict(self.cfg["reviews"]["small"], max_files=1)})
        got = small_errors(self.line(a, b), [self.fid], self.root, cfg)
        self.assertEqual(got, ["fix changes 2 files, more than reviews.small.max_files 1"])   # both paths count
        a, b = self.fix({"src/sp ace/é ü.txt": "x\n"})
        self.assertEqual(small_errors(self.line(a, b), [self.fid], self.root, self.cfg), [])   # -z parsing
        a, b = self.fix({"src/tab\tname.txt": "x\n"})
        self.assertEqual(small_errors(self.line(a, b), [self.fid], self.root, self.cfg), [])

    def test_small_errors_exclude_and_severity(self):               # S7, S10
        self.finding(self.fid, "LOW")
        a, b = self.fix({"CLAUDE.md": "x\n"})
        self.assertEqual(small_errors(self.line(a, b), [self.fid], self.root, self.cfg),
                         ["fix changes CLAUDE.md, which matches reviews.small.exclude CLAUDE.md"])
        a, b = self.fix({".github/workflows/ci.yml": "x\n", "src/ok.txt": "x\n"})
        got = small_errors(self.line(a, b), [self.fid], self.root, self.cfg)
        self.assertEqual(got, ["fix changes .github/workflows/ci.yml, which matches reviews.small.exclude "
                               ".github/workflows/**"])
        a, b = self.fix({"src/free.txt": "x\n"})
        self.assertEqual(small_errors(self.line(a, b), [self.fid], self.root, self.cfg), [])

    def test_small_errors_findings(self):                           # S10
        a, b = self.fix({"src/n.txt": "x\n"})
        other, high, crit = "F-20261031-m4n5", "F-20261031-p6q7", "F-20261031-r8s9"
        self.finding(self.fid, "LOW")
        self.finding(other, "MEDIUM")
        self.finding(high, "HIGH")
        self.finding(crit, "CRITICAL")
        run = lambda ids: small_errors(self.line(a, b), ids, self.root, self.cfg)
        self.assertEqual(run([self.fid, other]), [])                                         # LOW and MEDIUM together
        self.assertEqual(run([]), ["## Findings names no finding id"])
        self.assertEqual(run(["F-20261031-zzzz"]), ["finding F-20261031-zzzz names no finding record"])
        self.assertEqual(run([high]), ["finding %s is not LOW or MEDIUM" % high])
        self.assertEqual(run([crit]), ["finding %s is not LOW or MEDIUM" % crit])

    def test_round_5_never_small(self):                             # S8
        a, b = self.fix({"src/r.txt": "x\n"})
        self.finding(self.fid, "LOW")
        for r in (1, 2, 3, 4):
            self.assertEqual(small_errors(self.line(a, b, round=r), [self.fid], self.root, self.cfg), [])
        got = small_errors(self.line(a, b, round=5), [self.fid], self.root, self.cfg)
        self.assertEqual(len(got), 1)
        self.assertIn("round 5", got[0])
        for r in (10 ** 8, 10 ** 9, 10 ** 10):                      # F-2c3-R1-4: a long round is a reason, not malformed
            got = small_errors(self.line(a, b, round=r), [self.fid], self.root, self.cfg)
            self.assertEqual(got, ["round %d: only rounds 1-4 may be small; round 5 always runs at the minimum tier" % r])

    def test_small_errors_ancestry(self):                           # S9, D10
        a, b = self.fix({"src/s.txt": "x\n"})
        self.finding(self.fid, "LOW")
        got = small_errors(self.line(b, a), [self.fid], self.root, self.cfg)
        self.assertEqual(got, ["fix: %s is not an ancestor of %s" % (b, a)])
        got = small_errors(self.line("1234567", b), [self.fid], self.root, self.cfg)
        self.assertEqual(got, ["fix: git merge-base --is-ancestor failed (exit 128)"])

    def test_controller_fields(self):                               # S11
        a, b = self.fix({"src/c.txt": "x\n"})
        self.finding(self.fid, "LOW")
        self.assertEqual(small_errors(self.line(a, b, questions="open"), [self.fid], self.root, self.cfg),
                         ["questions is not none"])
        self.assertEqual(small_errors(self.line(a, b, **{"prev-fix-defects": 1}), [self.fid], self.root, self.cfg),
                         ["prev-fix-defects is not 0"])

    def test_small_errors_pinned_diff_invocation(self):             # S12, plan P:33: the options of every parsed git call
        from unittest import mock
        a, b = self.fix({"src/p.txt": "x\n"})
        self.finding(self.fid, "LOW")
        real = gitinfo.subprocess.run
        argvs = []

        def spy(argv, *args, **kw):
            argvs.append(list(argv))
            return real(argv, *args, **kw)
        with mock.patch.object(gitinfo.subprocess, "run", spy):
            self.assertEqual(small_errors(self.line(a, b), [self.fid], self.root, self.cfg), [])
        diff = [v for v in argvs if "diff" in v][0]
        self.assertEqual(diff[diff.index("diff"):], ["diff", "--no-color", "--numstat", "-z", "--no-renames",
                                                     "--no-ext-diff", "--no-textconv", a + ".." + b, "--"])

    def test_small_errors_ignore_colour_and_abbrev_config(self):    # S12, plan P:33
        files = {"src/big.txt": "x\n" * 151}
        a, b = self.fix(files)
        self.finding(self.fid, "LOW")
        plain = small_errors(self.line(a, b), [self.fid], self.root, self.cfg)
        self.assertEqual(len(plain), 1)
        for key, val in (("color.ui", "always"), ("color.diff", "always"), ("core.abbrev", "7")):
            git(self.root, "config", key, val)
        self.assertEqual(small_errors(self.line(a, b), [self.fid], self.root, self.cfg), plain)
        a, b = self.fix({"src/small.txt": "x\n"})
        self.assertEqual(small_errors(self.line(a, b), [self.fid], self.root, self.cfg), [])


# ---------------------------------------------------------------- Task P4.3: required and program_errors
# Rows RQ1-RQ15, PC1-PC11, BL1-BL26, V1-V4, LM10 of task-P4.3-domain.md with the binding decisions D-Q1..D-Q4 (a).
# Expected values are written by hand from the plan lines P:3200-3205 and the table, never read from ``dispatch``.
import json
import re
import subprocess
import sys

from gates.lib import config as config_lib
from gates.lib import yamlsub
from tests.test_programs_lib import NAME, STATUS_TEXT, row, stream

PROGS = ".strict-delivery/state/programs"
ENVS = ("CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH", "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS")


def add_program(root, name=NAME, streams=("a", "b"), base="main", back="main", with_folder=True):
    """The program ``name`` on ``<name>/integration`` cut from ``base`` (HEAD is left on ``back``)."""
    git(root, "checkout", "-q", "-b", name + "/integration", base)
    if with_folder:
        d = PROGS + "/" + name
        r = row(*[stream(s, [s + "/"], merge_order=i + 1) for i, s in enumerate(streams)], program=name)
        write_record(root, d + "/streams.yml", r)
        for f, t in (("status.md", STATUS_TEXT), ("sync-log.md", "<!-- schema: sync-log/1 -->\n"),
                     ("merged.md", "<!-- schema: merged-log/1 -->\n")):
            with open(os.path.join(root, d, f), "w", encoding="utf-8") as fh:
                fh.write(t)
    commit_all(root, "program " + name)
    git(root, "checkout", "-q", back)


def config_for(profile="strict"):
    return dict(minimal_config(), profile=profile)


class ProgFx(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        for name in ENVS:
            os.environ.pop(name, None)
        self.root = make_repo(self.work, config_for("strict"))
        for key, val in (("color.ui", "always"), ("color.diff", "always"), ("core.abbrev", "7")):
            git(self.root, "config", key, val)

    def cfg(self, profile="strict"):
        write_record(self.root, ".strict-delivery/config.yml", config_for(profile))
        commit_all(self.root, "config " + profile)
        return config_lib.load(self.root)

    def refs(self):
        return git(self.root, "for-each-ref", "--format=%(refname) %(objectname)")


def sec(brief, **others):
    d = {"Brief": brief}
    d.update(others)
    return d


class RequiredTest(ProgFx):
    def test_required_on_light_when_program_live(self):            # RQ1, RQ2, RQ5, RQ14
        light = self.cfg("light")
        r = dispatch.required(self.root, light)
        self.assertIs(r, False)                                     # RQ1
        self.assertIs(dispatch.required(self.root, self.cfg("strict")), True)      # RQ5 none
        add_program(self.root)
        self.assertIs(dispatch.required(self.root, light), True)    # RQ2
        self.assertIs(dispatch.required(self.root, self.cfg("strict")), True)      # RQ5 live

    def test_required_each_profile(self):                          # RQ3, RQ4
        for live in (False, True):
            if live:
                add_program(self.root)
            self.assertIs(dispatch.required(self.root, self.cfg("standard")), True, live)
            self.assertIs(dispatch.required(self.root, self.cfg("strict")), True, live)

    def test_required_two_live_programs(self):                     # RQ6
        light = self.cfg("light")
        add_program(self.root)
        add_program(self.root, "20261102-y")
        self.assertIs(dispatch.required(self.root, light), True)

    def test_required_branch_without_folder_light_false(self):     # RQ7
        light = self.cfg("light")
        add_program(self.root, with_folder=False)
        self.assertIs(dispatch.required(self.root, light), False)

    def test_required_stream_records_branch_and_tag_alone_false(self):   # RQ8
        light = self.cfg("light")
        for b in (NAME + "/a/main", NAME + "/records"):
            git(self.root, "branch", b, "main")
        git(self.root, "tag", NAME + "/integration", "main")
        self.assertIs(dispatch.required(self.root, light), False)

    def test_required_ignores_current_branch(self):                # RQ9
        light = self.cfg("light")
        add_program(self.root)
        for how in ("on integration", "on main", "detached"):
            if how == "on integration":
                git(self.root, "checkout", "-q", NAME + "/integration")
            elif how == "on main":
                git(self.root, "checkout", "-q", "main")
            else:
                git(self.root, "checkout", "-q", "--detach", "main")
            with self.subTest(how):
                self.assertIs(dispatch.required(self.root, light), True)

    def test_required_ignores_colour_and_abbrev_config(self):      # RQ10 (the fixture sets all three)
        light = self.cfg("light")
        git(self.root, "config", "diff.noprefix", "true")
        self.assertIs(dispatch.required(self.root, light), False)
        add_program(self.root)
        self.assertIs(dispatch.required(self.root, light), True)

    def test_required_live_programs_raises(self):                  # RQ11, D-Q1 (a): True, never False
        light = self.cfg("light")
        nogit = os.path.join(self.tmp, "nogit")
        os.mkdir(nogit)
        for profile in ("light", "standard", "strict"):
            with self.subTest(profile):
                self.assertIs(dispatch.required(nogit, dict(light, profile=profile)), True)

    def test_required_cfg_forms(self):                             # RQ12, D-Q1 (a)
        for profile in ("", "Strict", None, 5, ["strict"], "light "):
            with self.subTest(profile=profile):
                self.assertIs(dispatch.required(self.root, dict(config_lib.load(self.root), profile=profile)), True)
        c = dict(config_lib.load(self.root))
        del c["profile"]
        self.assertIs(dispatch.required(self.root, c), True)
        for bad in (None, [], "light", 3):
            with self.subTest(cfg=bad):
                with self.assertRaises(ValueError) as cm:
                    dispatch.required(self.root, bad)
                self.assertIn("cfg", str(cm.exception))

    def test_required_root_forms(self):                            # RQ13, D-Q1 (a)
        class S(str):
            pass
        light = self.cfg("light")
        for bad in (None, b"x", S(self.root), 5, ["x"]):
            with self.subTest(root=repr(bad)):
                with self.assertRaises(ValueError) as cm:
                    dispatch.required(bad, light)
                self.assertIn("root", str(cm.exception))
                with self.assertRaises(ValueError):
                    dispatch.required(bad, dict(light, profile="strict"))     # types checked before the short-circuit
        for ok_but_unusable in ("", os.path.join(self.tmp, "missing"), os.path.join(self.root, ".strict-delivery", "config.yml")):
            with self.subTest(root=ok_but_unusable):
                self.assertIs(dispatch.required(ok_but_unusable, light), True)

    def test_required_is_read_only(self):                          # RQ15
        light = self.cfg("light")
        add_program(self.root)
        before = (git(self.root, "status", "--porcelain", "--untracked-files=all"), self.refs())
        dispatch.required(self.root, light)
        dispatch.required(self.root, dict(light, profile="strict"))
        self.assertEqual((git(self.root, "status", "--porcelain", "--untracked-files=all"), self.refs()), before)


class ProgramErrorsTest(ProgFx):
    def setUp(self):
        super().setUp()
        self.cfg_ = config_lib.load(self.root)

    def pe(self, brief, role="stream_controller", live=True, **others):
        return dispatch.program_errors(sec(brief, **others), role, self.root, self.cfg_, live)

    def sfx(self, errs):
        return [s for s, _ in errs]

    def test_program_live_claim_checked_against_git(self):         # PC1-PC4
        self.assertEqual(self.pe("b", "implementer", False), [])               # PC1
        e = self.pe("b", "implementer", True)                                  # PC4
        self.assertEqual(self.sfx(e), ["program"])
        self.assertIn("true", e[0][1])
        self.assertIn("false", e[0][1])
        add_program(self.root)
        self.assertEqual(self.pe("b", "implementer", True), [])                # PC2
        e = self.pe("b", "implementer", False)                                 # PC3
        self.assertEqual(self.sfx(e), ["program"])
        self.assertIn("true", e[0][1])
        self.assertIn("false", e[0][1])
        self.assertTrue(("program", e[0][1]) in e)

    def test_claim_two_live_programs(self):                        # PC5
        add_program(self.root)
        add_program(self.root, "20261102-y")
        self.assertEqual(self.pe("b", "implementer", True), [])
        self.assertEqual(self.sfx(self.pe("b", "implementer", False)), ["program"])

    def test_non_program_roles_only_claim_checked(self):           # PC7, BL11
        for live_fx in (False, True):
            if live_fx:
                add_program(self.root)
            for role in ("implementer", "controller", "task_reviewer", "drafter", "unknown", ""):
                for claim in (False, True):
                    with self.subTest(role=role, fx=live_fx, claim=claim):
                        got = self.sfx(self.pe("no program line", role, claim))
                        self.assertEqual(got, [] if claim == live_fx else ["program"])

    def test_claim_pair_precedes_brief_pairs(self):                # PC8
        add_program(self.root)
        got = self.pe("b", "stream_controller", False)
        self.assertEqual(got[0][0], "program")
        self.assertIn("program_live", got[0][1])
        self.assertTrue(len(got) >= 2)

    def test_program_errors_argument_types(self):                  # PC6, PC9, PC10, D-Q1 (a)
        class S(str):
            pass
        for claim in (1, 0, None, "true", []):
            with self.subTest(claim=claim):
                with self.assertRaises(ValueError) as cm:
                    dispatch.program_errors(sec("b"), "implementer", self.root, self.cfg_, claim)
                self.assertIn("program_live", str(cm.exception))
        for bad in (None, [], "Brief"):
            with self.subTest(sections=bad):
                with self.assertRaises(ValueError) as cm:
                    dispatch.program_errors(bad, "implementer", self.root, self.cfg_, False)
                self.assertIn("sections", str(cm.exception))
        with self.assertRaises(ValueError) as cm:
            dispatch.program_errors({"Brief": 5}, "implementer", self.root, self.cfg_, False)
        self.assertIn("Brief", str(cm.exception))
        self.assertEqual(dispatch.program_errors({}, "implementer", self.root, self.cfg_, False), [])   # no Brief: ""
        for role in (None, S("implementer"), 5):
            with self.subTest(role=role):
                with self.assertRaises(ValueError) as cm:
                    dispatch.program_errors(sec("b"), role, self.root, self.cfg_, False)
                self.assertIn("role", str(cm.exception))
        for bad in (None, [], "x"):
            with self.assertRaises(ValueError) as cm:
                dispatch.program_errors(sec("b"), "implementer", self.root, bad, False)
            self.assertIn("cfg", str(cm.exception))
        for bad in (None, b"x", S(self.root)):
            with self.assertRaises(ValueError) as cm:
                dispatch.program_errors(sec("b"), "implementer", bad, self.cfg_, False)
            self.assertIn("root", str(cm.exception))

    def test_program_errors_git_failure(self):                     # PC11, D-Q3: live_programs' GateError escapes
        nogit = os.path.join(self.tmp, "nogit")
        os.mkdir(nogit)
        for root in (nogit, ""):
            with self.subTest(root=root):
                with self.assertRaises(GateError):
                    dispatch.program_errors(sec("b"), "implementer", root, self.cfg_, False)

    # ---- the program: line
    def test_program_line_required(self):                          # BL1
        add_program(self.root)
        for role in ("program_controller", "stream_controller"):
            with self.subTest(role):
                got = self.pe("b", role)
                self.assertEqual(self.sfx(got)[0], "program")
                self.assertEqual(self.pe("", role)[0][0], "program")

    def test_stream_controller_names_known_stream(self):           # BL2, BL13, BL14
        add_program(self.root)
        self.assertEqual(self.pe("program: %s\nstream: a" % NAME), [])
        self.assertEqual(self.pe("program: %s\nstream: b" % NAME), [])
        for s in ("nope", "c"):
            with self.subTest(stream=s):
                got = self.pe("program: %s\nstream: %s" % (NAME, s))
                self.assertEqual(self.sfx(got), ["stream"])
        self.assertEqual(self.pe("program: %s" % NAME, "program_controller"), [])

    def test_program_line_closed_program(self):                    # BL3, BL4
        add_program(self.root)
        add_program(self.root, "20261103-nofolder", with_folder=False)
        for p in ("20261102-y", "20261103-nofolder"):
            with self.subTest(p):
                got = self.pe("program: %s\nstream: a" % p)
                self.assertEqual(self.sfx(got)[0], "program")

    def test_two_program_lines_refused(self):                      # BL5
        add_program(self.root)
        add_program(self.root, "20261102-y")
        for brief in ("program: %s\nprogram: %s" % (NAME, NAME), "program: %s\nprogram: 20261102-y" % NAME):
            with self.subTest(brief):
                for role in ("program_controller", "stream_controller"):
                    self.assertEqual(self.pe(brief + "\nstream: a", role)[0][0], "program")

    def test_program_line_leading_space(self):                     # BL6
        add_program(self.root)
        for lead in (" ", "\t", "  "):
            with self.subTest(repr(lead)):
                self.assertEqual(self.pe(lead + "program: " + NAME, "program_controller")[0][0], "program")

    def test_program_line_forms(self):                             # BL7
        add_program(self.root)
        for brief in ("Program: " + NAME, "program:" + NAME, "program:  " + NAME, "program: " + NAME + " ",
                      "program: " + NAME + "\r", "program: ", "program: " + NAME + " extra", "program: <p>",
                      "program: " + NAME + "\r\nstream: a", "PROGRAM: " + NAME):
            with self.subTest(repr(brief)):
                self.assertEqual(self.pe(brief, "program_controller")[0][0], "program")

    def test_program_line_name_grammar(self):                      # BL8, V1b
        add_program(self.root)
        for name in ("x", "20261301-x", "20260229-x", "20261101-", "20261101-X", "20261101-a/b", "20261101-..",
                     "20261101-" + "x" * 4301, "20261101-x\x00", "20261101-é", "١" * 8 + "-x", "20261101-x ",
                     "20261101-x" + "١"):
            with self.subTest(repr(name[:30])):
                got = self.pe("program: " + name, "program_controller")
                self.assertEqual(self.sfx(got), ["program"])
                self.assertLess(len(got[0][1]), 300, got)                  # the quoted value is cut, whatever its length

    def test_program_line_only_in_brief(self):                     # BL9
        add_program(self.root)
        line = "program: %s\nstream: a\n" % NAME
        for sect in ("Task", "Findings", "Claims", "Report", "Strict block", "Role", "Model"):
            with self.subTest(sect):
                self.assertEqual(self.pe("nothing here", "stream_controller", True, **{sect: line})[0][0], "program")

    def test_program_line_position(self):                          # BL10
        add_program(self.root)
        pl, sl = "program: " + NAME, "stream: a"
        small = "small-re-review: plan=p"
        for brief in (pl + "\n" + sl, sl + "\n" + pl, "x\n" + pl + "\ny\n" + sl + "\nz", "\n" + pl + "\n\n" + sl + "\n",
                      small + "\n" + pl + "\n" + sl, pl + "\n" + small + "\n" + sl):
            with self.subTest(repr(brief)):
                self.assertEqual(self.pe(brief), [])

    def test_non_program_roles_need_no_program_line(self):         # BL11
        add_program(self.root)
        for role in ("implementer", "controller", "task_reviewer"):
            self.assertEqual(self.pe("none", role, True), [])

    def test_stream_line_ignored_for_program_controller(self):     # BL12
        add_program(self.root)
        base = self.pe("program: " + NAME, "program_controller")
        for extra in ("stream: a", "stream: nope", "stream: a\nstream: b", "stream:x", " stream: a", "stream: "):
            with self.subTest(extra):
                self.assertEqual(self.pe("program: %s\n%s" % (NAME, extra), "program_controller"), base)
        bad = self.pe("x\nstream: nope", "program_controller")
        self.assertNotIn("stream", self.sfx(bad))

    def test_stream_line_required(self):                           # BL15
        add_program(self.root)
        self.assertEqual(self.sfx(self.pe("program: " + NAME)), ["stream"])

    def test_two_stream_lines_refused(self):                       # BL16
        add_program(self.root)
        for extra in ("stream: a\nstream: b", "stream: a\nstream: a"):
            self.assertEqual(self.sfx(self.pe("program: %s\n%s" % (NAME, extra))), ["stream"])

    def test_stream_line_forms(self):                              # BL17
        add_program(self.root)
        for v in (" stream: a", "Stream: a", "stream:a", "stream: a ", "stream: a\r", "stream: ", "stream: integration",
                  "stream: records", "stream: A", "stream: a/b", "stream: aé", "stream: " + "a" * 4301,
                  "stream: a\x00", "\tstream: a", "stream:  a"):
            with self.subTest(repr(v[:30])):
                self.assertEqual(self.sfx(self.pe("program: %s\n%s" % (NAME, v))), ["stream"])

    def test_stream_integration_and_records_refused_even_if_listed(self):   # BL17, M17
        add_program(self.root, streams=("a", "integration", "records"))
        for s in ("integration", "records"):
            with self.subTest(s):
                self.assertEqual(self.sfx(self.pe("program: %s\nstream: %s" % (NAME, s))), ["stream"])

    def test_stream_looked_up_in_named_program(self):              # BL18, M16
        add_program(self.root)
        add_program(self.root, "20261102-y", streams=("c",))
        self.assertEqual(self.sfx(self.pe("program: %s\nstream: c" % NAME)), ["stream"])
        self.assertEqual(self.pe("program: 20261102-y\nstream: c"), [])
        self.assertEqual(self.sfx(self.pe("program: 20261102-y\nstream: a")), ["stream"])

    def test_stream_read_from_integration_tip(self):               # BL19, M15
        add_program(self.root, streams=("a", "b"))
        git(self.root, "checkout", "-q", "main")
        write_record(self.root, PROGS + "/" + NAME + "/streams.yml",
                     row(stream("c", ["c/"], merge_order=1), program=NAME))      # working tree and main only
        commit_all(self.root, "main lists c")
        write_record(self.root, PROGS + "/" + NAME + "/streams.yml", row(stream("d", ["d/"], merge_order=1), program=NAME))
        self.assertEqual(self.pe("program: %s\nstream: a" % NAME), [])
        self.assertEqual(self.sfx(self.pe("program: %s\nstream: c" % NAME)), ["stream"])
        self.assertEqual(self.sfx(self.pe("program: %s\nstream: d" % NAME)), ["stream"])

    def test_stream_pair_when_program_unresolved(self):            # BL20, D-Q4 (a)
        add_program(self.root)
        got = self.pe("program: nope\nstream: a")
        self.assertEqual(got[0][0], "program")
        self.assertIn(("stream", "stream not checked: the program line failed"), got)
        got = self.pe("stream: a")
        self.assertIn(("stream", "stream not checked: the program line failed"), got)
        self.assertEqual(len(got), 2)

    def test_stream_program_files_unreadable(self):                # BL21, D-Q3
        add_program(self.root)
        d = os.path.join(PROGS, NAME)
        bad = {"yaml error": "a: [\n", "duplicate key": "a: 1\na: 2\n", "list": "- 1\n", "bom": "﻿schema: streams/1\n",
               "cr": "schema: streams/1\r\n"}
        for name, text in bad.items():
            with self.subTest(name):
                git(self.root, "checkout", "-q", NAME + "/integration")
                with open(os.path.join(self.root, d, "streams.yml"), "w", encoding="utf-8", newline="") as fh:
                    fh.write(text)
                commit_all(self.root, name)
                git(self.root, "checkout", "-q", "main")
                got = self.pe("program: %s\nstream: a" % NAME)
                self.assertEqual(self.sfx(got), ["stream"])
                self.assertIn("streams.yml", got[0][1])
                git(self.root, "checkout", "-q", NAME + "/integration")
                git(self.root, "reset", "-q", "--hard", "HEAD~1")
                git(self.root, "checkout", "-q", "main")
        for f in ("status.md", "sync-log.md", "merged.md"):
            with self.subTest(f):
                git(self.root, "checkout", "-q", NAME + "/integration")
                git(self.root, "rm", "-q", d + "/" + f)
                git(self.root, "commit", "-q", "-m", "rm " + f)
                git(self.root, "checkout", "-q", "main")
                got = self.pe("program: %s\nstream: a" % NAME)
                self.assertEqual(self.sfx(got), ["stream"])
                self.assertIn(f, got[0][1])
                git(self.root, "checkout", "-q", NAME + "/integration")
                git(self.root, "reset", "-q", "--hard", "HEAD~1")
                git(self.root, "checkout", "-q", "main")

    def test_stream_list_shapes(self):                             # BL22
        add_program(self.root)
        git(self.root, "checkout", "-q", NAME + "/integration")
        r = row(stream("a", ["a/"], merge_order=1), program=NAME)
        r["streams"] = [5, "x", {"id": 3}, {"id": "a"}, {"id": "a"}, {"nid": "b"}]
        write_record(self.root, PROGS + "/" + NAME + "/streams.yml", r)
        commit_all(self.root, "odd")
        git(self.root, "checkout", "-q", "main")
        self.assertEqual(self.pe("program: %s\nstream: a" % NAME), [])
        self.assertEqual(self.sfx(self.pe("program: %s\nstream: b" % NAME)), ["stream"])

    def test_integration_tag_does_not_hide_branch(self):           # BL23, M18
        add_program(self.root)
        git(self.root, "tag", NAME + "/integration", "main")
        self.assertEqual(self.pe("program: %s\nstream: a" % NAME), [])

    def test_program_errors_git_states(self):                      # BL24
        add_program(self.root)
        brief = "program: %s\nstream: a" % NAME
        git(self.root, "config", "diff.noprefix", "true")
        for how in ("detached", "on integration"):
            git(self.root, "checkout", "-q", "--detach" if how == "detached" else NAME + "/integration")
            with self.subTest(how):
                self.assertEqual(self.pe(brief), [])
        git(self.root, "checkout", "-q", "main")
        unborn = os.path.join(self.tmp, "unborn")
        os.mkdir(unborn)
        git(unborn, "init", "-q", "-b", "main")
        for key, val in (("user.email", "a@b.invalid"), ("user.name", "x")):
            git(unborn, "config", key, val)
        got = dispatch.program_errors(sec(brief), "stream_controller", unborn, self.cfg_, False)
        self.assertEqual(got[0][0], "program")
        spaced = os.path.join(self.tmp, "a b")
        os.mkdir(spaced)
        make_repo(spaced, config_for("strict"))
        add_program(spaced)
        self.assertEqual(dispatch.program_errors(sec(brief), "stream_controller", spaced, self.cfg_, True), [])

    def test_program_errors_shallow_clone(self):                   # BL24 shallow clone
        add_program(self.root)
        brief = "program: %s\nstream: a" % NAME
        shallow = os.path.join(self.tmp, "shallow")
        git(self.tmp, "clone", "-q", "--depth", "1", "--no-single-branch", "file://" + self.root, shallow)
        git(shallow, "branch", NAME + "/integration", "origin/" + NAME + "/integration")
        self.assertTrue(os.path.exists(os.path.join(shallow, ".git", "shallow")))
        got = dispatch.program_errors(sec(brief), "stream_controller", shallow, self.cfg_, True)
        self.assertEqual(got, [])
        self.assertEqual(self.pe(brief), got)                      # same verdict as the plain fixture

    def test_program_errors_merge_in_progress(self):               # BL24 MERGE_HEAD
        add_program(self.root)
        brief = "program: %s\nstream: a" % NAME
        git(self.root, "checkout", "-q", "-b", "side", "main")
        write_record(self.root, "side.yml", {"k": "v"})
        commit_all(self.root, "side")
        git(self.root, "checkout", "-q", "main")
        write_record(self.root, "main.yml", {"k": "w"})
        commit_all(self.root, "main")
        git(self.root, "merge", "--no-commit", "--no-ff", "side")
        self.assertTrue(os.path.exists(os.path.join(self.root, ".git", "MERGE_HEAD")))
        self.assertEqual(self.pe(brief), [])

    def test_program_errors_newline_in_path(self):                 # BL24 newline in the checkout path
        brief = "program: %s\nstream: a" % NAME
        nl = os.path.join(self.tmp, "a\nb")
        try:
            os.mkdir(nl)
        except OSError as exc:
            self.skipTest("filesystem refuses a newline in a directory name: %s" % exc)
        make_repo(nl, config_for("strict"))
        add_program(nl)
        self.assertEqual(dispatch.program_errors(sec(brief), "stream_controller", nl, self.cfg_, True), [])

    def test_program_errors_shape(self):                           # BL25, V2
        add_program(self.root)
        hostile = ("\x00\r\né Ꟁ೏\\" + "x" * 5000, "١", "﻿", "\x1b[31m")
        for h in hostile:
            for brief in ("program: " + h, "program: %s\nstream: %s" % (NAME, h), "program: %s\nprogram: %s" % (h, h)):
                with self.subTest(repr(h[:12]), brief=repr(brief[:20])):
                    got = self.pe(brief)
                    self.assertIsInstance(got, list)
                    self.assertTrue(got)
                    for item in got:
                        self.assertIs(type(item), tuple)
                        self.assertEqual(len(item), 2)
                        self.assertIn(item[0], ("program", "stream"))
                        self.assertTrue(item[1] and item[1].isascii() and re.fullmatch(r"[\x20-\x7e]+", item[1]), item)
                        self.assertLess(len(item[1]), 600, item)               # a hostile 5000-char value is cut

    def test_program_line_unicode_version_free(self):              # V2, M12
        add_program(self.root)
        for ch in ("Ꟁ", "ꟁ", "ೳ", "⿼", "١", "É"):
            for brief in ("program: 20261101-%s" % ch, "Program: " + NAME.replace("x", ch)):
                with self.subTest(hex(ord(ch)), brief=brief):
                    self.assertEqual(self.sfx(self.pe(brief, "program_controller")), ["program"])
        self.assertEqual(self.pe("program: " + NAME, "program_controller"), [])

    def test_brief_split_on_lf_only(self):                         # V4
        add_program(self.root)
        for sep in ("\x85", " ", "\x0b", "\x0c", "\x1c", " "):
            with self.subTest(hex(ord(sep))):
                self.assertEqual(self.sfx(self.pe("x%sprogram: %s" % (sep, NAME), "program_controller")), ["program"])

    def test_program_errors_read_only(self):                       # BL26
        add_program(self.root)
        before = (git(self.root, "status", "--porcelain", "--untracked-files=all"), self.refs())
        for brief in ("program: \x00", "program: %s\nstream: é" % NAME, "program: %s\nstream: a" % NAME):
            self.pe(brief)
        self.assertEqual((git(self.root, "status", "--porcelain", "--untracked-files=all"), self.refs()), before)

    def test_big_numerals_in_streams_yml(self):                    # V1a
        add_program(self.root)
        git(self.root, "checkout", "-q", NAME + "/integration")
        p = os.path.join(self.root, PROGS, NAME, "streams.yml")
        with open(p, encoding="utf-8") as fh:
            text = fh.read()
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text.replace("estimate: 5", "estimate: " + "9" * 4301))
        commit_all(self.root, "big")
        git(self.root, "checkout", "-q", "main")
        got = self.pe("program: %s\nstream: a" % NAME)
        self.assertTrue(got == [] or self.sfx(got) == ["stream"], got)     # never a traceback, on both interpreters

    def test_no_exception_group_in_dispatch_files(self):           # LM10, V3
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for rel in ("gates/lib/dispatch.py", "gates/gate_dispatch.py"):
            with open(os.path.join(here, rel), encoding="utf-8") as fh:
                src = fh.read()
            self.assertNotIn("ExceptionGroup", src)
            self.assertNotIn("except*", src)


# ---------------------------------------------------------------- Task 4b.2: project roles in the library (rows RO, MT, PP, BU, V)
# Expected values are written out by hand from the plan (:4405-4410) and spec section 10, never read back from dispatch.

SPEC_ROLES = ("program_controller", "stream_controller", "controller", "implementer", "implementer_transcription",
              "task_reviewer", "final_reviewer", "final_verifier", "exception_reviewer", "audit_reviewer",
              "audit_verifier", "investigator", "plan_writer", "plan_reviewer", "drafter")
ENTRY = {"prompt": "p.md", "min_tier": "tier2"}
COLLISION = "%s: a project role may not reuse a framework role id"
EXPECTED_MIN = {"implementer_transcription": 1, "implementer": 2, "drafter": 2, "task_reviewer": 2,
                "program_controller": 3, "stream_controller": 3, "controller": 3, "final_reviewer": 3,
                "audit_reviewer": 3, "audit_verifier": 3, "investigator": 3, "plan_writer": 3, "plan_reviewer": 3,
                "final_verifier": 4, "exception_reviewer": 4}
CFG4 = {"models": {"tiers": {"tier1": "a", "tier2": "b", "tier3": "c", "tier4": "d"}}}


def cfg_with(**roles):
    return dict(CFG4, roles={k: dict(ENTRY) for k in roles})


class RolesOfTest(unittest.TestCase):
    def test_roles_of_absent_is_roles(self):                       # RO1, RO16
        for cfg in ({}, {"models": {}}, {"roles": {}}):             # RO9
            got = dispatch.roles_of(cfg)
            self.assertIs(type(got), tuple)
            self.assertEqual(got, SPEC_ROLES)

    def test_roles_of_one(self):                                    # RO2
        self.assertEqual(dispatch.roles_of(cfg_with(doc_writer=1)), SPEC_ROLES + ("doc_writer",))

    def test_roles_of_sorted(self):                                 # RO3, CF2, V5
        cfg = {"roles": {"zz": dict(ENTRY), "aa": dict(ENTRY), "m": dict(ENTRY)}}
        self.assertEqual(dispatch.roles_of(cfg), SPEC_ROLES + ("aa", "m", "zz"))

    def test_project_role_collision_fails(self):                    # RO4: each of the fifteen
        for rid in SPEC_ROLES:
            with self.subTest(rid):
                with self.assertRaises(ValueError) as cm:
                    dispatch.roles_of({"roles": {rid: dict(ENTRY)}})
                self.assertEqual(str(cm.exception), COLLISION % rid)

    def test_roles_of_two_collisions_names_first_sorted(self):      # RO5, RO6
        with self.assertRaises(ValueError) as cm:
            dispatch.roles_of({"roles": {"plan_writer": {}, "doc_writer": {}, "drafter": {}}})
        self.assertEqual(str(cm.exception), COLLISION % "drafter")

    def test_project_role_named_session(self):                      # RO8, Q3
        with self.assertRaises(ValueError) as cm:
            dispatch.roles_of({"roles": {"session": dict(ENTRY)}})
        self.assertEqual(str(cm.exception), "session: a project role may not reuse the dispatcher id session")

    def test_roles_of_near_collisions_accepted(self):               # RO7
        ids = ["controller_x", "implementer2", "plan_writer_", "drafter1", "a", "x_"]
        got = dispatch.roles_of({"roles": {i: dict(ENTRY) for i in ids}})
        self.assertEqual(got, SPEC_ROLES + tuple(sorted(ids)))

    def test_roles_of_wrong_shapes(self):                           # RO10, RO11, RO13
        import collections

        class D(dict):
            pass
        for roles in (None, 5, True, "x", [], ["a"], collections.OrderedDict(), D()):
            with self.subTest(roles=repr(roles)):
                with self.assertRaises(ValueError):
                    dispatch.roles_of({"roles": roles})

        class S(str):
            pass
        for key in (1, None, True, ("a",), b"x", S("x")):
            with self.subTest(key=repr(key)):
                with self.assertRaises(ValueError):
                    dispatch.roles_of({"roles": {key: {}}})
        for cfg in (None, [], "x", 5):
            with self.subTest(cfg=repr(cfg)):
                with self.assertRaises(ValueError):
                    dispatch.roles_of(cfg)

    def test_roles_of_id_grammar(self):                             # RO12, V2
        for bad in ("X", "1x", "a-b", "a.b", "", "x\n", "x ", " x", "x\x00", "﻿x", "ｘ", "kK",
                    "Ꟁ", "\U0001fae8", "_x"):
            with self.subTest(repr(bad)):
                with self.assertRaises(ValueError):
                    dispatch.roles_of({"roles": {bad: {}}})

    def test_roles_of_leaves_constants_alone(self):                 # RO14, RO17, DR11
        before = (dispatch.ROLES, dispatch.CONTROLLER_ROLES, dict(dispatch.MIN_TIERS),
                  {k: dict(v) for k, v in dispatch.DISPATCHERS.items()})
        ids = (id(dispatch.ROLES), id(dispatch.CONTROLLER_ROLES), id(dispatch.MIN_TIERS), id(dispatch.DISPATCHERS))
        a = dispatch.roles_of(cfg_with(doc_writer=1))
        b = dispatch.roles_of(cfg_with(other=1))
        self.assertNotIn("doc_writer", b)
        self.assertNotIn("other", a)
        self.assertEqual(before, (dispatch.ROLES, dispatch.CONTROLLER_ROLES, dispatch.MIN_TIERS, dispatch.DISPATCHERS))
        self.assertEqual(ids, (id(dispatch.ROLES), id(dispatch.CONTROLLER_ROLES), id(dispatch.MIN_TIERS),
                               id(dispatch.DISPATCHERS)))
        self.assertNotIn("doc_writer", dispatch.CONTROLLER_ROLES)
        self.assertEqual(dispatch.dispatchers_for(True, "doc_writer"), ("stream_controller", "controller"))
        self.assertEqual(dispatch.dispatchers_for(False, "doc_writer"), ("session", "controller"))
        self.assertEqual(dispatch.dispatchers_for(False, "controller"), ("session", "controller"))
        self.assertEqual(dispatch.dispatchers_for(True, "stream_controller"), ("session", "program_controller"))

    def test_roles_of_many_and_long(self):                          # RO15
        got = dispatch.roles_of({"roles": {"a" * 5000: dict(ENTRY)}})
        self.assertEqual(got, SPEC_ROLES + ("a" * 5000,))
        many = ["r%04d" % i for i in range(1000)]
        got = dispatch.roles_of({"roles": {i: dict(ENTRY) for i in reversed(many)}})
        self.assertEqual(got, SPEC_ROLES + tuple(many))


class MinTierOfTest(unittest.TestCase):
    def test_min_tier_of_framework_roles(self):                     # MT1
        for role, want in EXPECTED_MIN.items():
            with self.subTest(role):
                self.assertEqual(dispatch.min_tier_of(role, CFG4), want)

    def test_min_tier_of_framework_fallback(self):                  # MT2, Q1 (a)
        cfg = {"models": {"tiers": {"tier1": "a", "tier2": "b", "tier3": "c"}}}
        self.assertEqual(dispatch.min_tier_of("final_verifier", cfg), 3)
        self.assertEqual(dispatch.min_tier_of("exception_reviewer", cfg), 3)
        with self.assertRaises(ValueError):
            dispatch.min_tier_of("final_verifier", dict(cfg, top_tier_roles=[]))

    def test_min_tier_of_project_role_each_tier(self):             # MT3
        for name, want in (("tier1", 1), ("tier2", 2), ("tier3", 3), ("tier4", 4)):
            with self.subTest(name):
                got = dispatch.min_tier_of("x", dict(CFG4, roles={"x": {"prompt": "p.md", "min_tier": name}}))
                self.assertIs(type(got), int)
                self.assertEqual(got, want)

    def test_project_role_tier4_unset_returns_four(self):           # MT5
        cfg = {"models": {"tiers": {"tier1": "a"}}, "roles": {"x": {"prompt": "p.md", "min_tier": "tier4"}},
               "top_tier_roles": ["x"]}
        self.assertEqual(dispatch.min_tier_of("x", cfg), 4)

    def test_min_tier_of_unknown_role(self):                        # MT7
        for role in ("nosuch", "Doc_writer", ""):
            with self.subTest(repr(role)):
                with self.assertRaises(ValueError):
                    dispatch.min_tier_of(role, cfg_with(doc_writer=1))

    def test_min_tier_of_malformed_entry(self):                     # MT8
        for tier in ("tier5", 3, "3", True, None, "Tier2", " tier2", "tier٢", ["tier2"]):
            with self.subTest(repr(tier)):
                with self.assertRaises(ValueError):
                    dispatch.min_tier_of("x", dict(CFG4, roles={"x": {"prompt": "p.md", "min_tier": tier}}))
        for entry in ({"prompt": "p.md"}, 5, None, []):
            with self.subTest(repr(entry)):
                with self.assertRaises(ValueError):
                    dispatch.min_tier_of("x", dict(CFG4, roles={"x": entry}))

    def test_min_tier_of_argument_types(self):                      # MT9
        class S(str):
            pass
        for role in (None, 5, b"x", ):
            with self.assertRaises(ValueError):
                dispatch.min_tier_of(role, CFG4)
        for cfg in (None, []):
            with self.assertRaises(ValueError):
                dispatch.min_tier_of("implementer", cfg)

    def test_project_entry_never_lowers_framework_tier(self):       # MT10
        cfg = dict(CFG4, roles={"plan_writer": {"prompt": "p.md", "min_tier": "tier1"}})
        self.assertEqual(dispatch.min_tier_of("plan_writer", cfg), 3)

    def test_min_tier_reads_one_digit_only(self):                   # MT11, V1
        seen = []

        def spy(text, *a):
            seen.append(text)
            return int(text, *a)
        for lim in INT_LIMITS:
            with int_limit(lim):
                for name, want in (("tier1", 1), ("tier2", 2), ("tier3", 3), ("tier4", 4)):
                    with self.subTest(limit=lim, name=name):
                        cfg = dict(CFG4, roles={"x": {"prompt": "p.md", "min_tier": name}})
                        with mock.patch.object(dispatch, "int", spy, create=True):
                            del seen[:]
                            got = dispatch.min_tier_of("x", cfg)
                        self.assertEqual((got, type(got), seen), (want, int, [name[4]]))
                for bad in ("tier" + "9" * 5000, "tier٢", "tier2" + "0" * 5000):
                    with self.subTest(limit=lim, bad=bad[:12]):
                        cfg = dict(CFG4, roles={"x": {"prompt": "p.md", "min_tier": bad}})
                        with mock.patch.object(dispatch, "int", spy, create=True):
                            del seen[:]
                            with self.assertRaises(ValueError):
                                dispatch.min_tier_of("x", cfg)
                        self.assertEqual(seen, [])


class PromptPathTest(unittest.TestCase):
    def test_prompt_path_framework_role(self):                      # PP1
        for cfg in ({}, cfg_with(doc_writer=1)):
            self.assertEqual(dispatch.prompt_path("implementer", cfg, "/pd", "/r"), "/pd/implementer.md")

    def test_prompt_path_project_role(self):                        # PP2
        for rel in ("p.md", "a/b/c.md", ".strict-delivery/prompts/x.md", "é.md"):
            with self.subTest(rel):
                cfg = {"roles": {"x": {"prompt": rel, "min_tier": "tier2"}}}
                self.assertEqual(dispatch.prompt_path("x", cfg, "/pd", "/r"), "/r/" + rel)

    def test_prompt_path_refuses_escaping_paths(self):              # PP21
        class S(str):
            pass
        for bad in ("../p.md", "a/../p.md", "/etc/passwd", "//p.md", "a//b.md", "./p.md", "", None, 5, S("p.md"),
                    "p.txt", "a\x00b.md", "a\nb.md", "p.md ", "a\\b.md", ".md"):
            with self.subTest(repr(bad)):
                with self.assertRaises(ValueError):
                    dispatch.prompt_path("x", {"roles": {"x": {"prompt": bad, "min_tier": "tier2"}}}, "/pd", "/r")

    def test_prompt_path_unknown_role(self):                        # PP22
        for cfg in ({}, {"roles": {"x": {"min_tier": "tier2"}}}):
            with self.assertRaises(ValueError):
                dispatch.prompt_path("x" if cfg else "nosuch", cfg, "/pd", "/r")


class RoleOfProjectTest(unittest.TestCase):
    def test_role_of_project_role_exact(self):                      # DR9, DR10
        roles = SPEC_ROLES + ("doc_writer",)
        self.assertEqual(role_of("doc_writer\n", roles), "doc_writer")
        self.assertEqual(role_of("\n\ndoc_writer\nthen text\n", roles), "doc_writer")
        for body in ("doc_writer ", " doc_writer", "Doc_writer", "doc_writer\r", "doc_writer extra"):
            with self.subTest(repr(body)):
                with self.assertRaises(ValueError):
                    role_of(body, roles)
        with self.assertRaises(ValueError):
            role_of("doc_writer")                                    # one argument: framework roles only
        self.assertEqual(role_of("implementer"), "implementer")


class BudgetNumbersTest(unittest.TestCase):
    def head(self, t, m):
        return "## Role\nr\n\n## Budget: tokens=%s minutes=%s\n\n## Model\n" % (t, m)

    def test_budget_numbers(self):                                  # BU3 source, BU12, BU14
        self.assertEqual(dispatch.budget_numbers(self.head(1, 2)), ("1", "2"))
        self.assertEqual(dispatch.budget_numbers(self.head(1, 2) + "## Budget: tokens=5 minutes=6\n"), ("1", "2"))
        for bad in ("tokens=0 minutes=1", "tokens=01 minutes=1", "tokens=-1 minutes=1", "tokens=1.5 minutes=1",
                    "tokens=1", "tokens=1  minutes=1", "tokens=1 minutes=1 ", "tokens=١ minutes=1", ""):
            with self.subTest(bad):
                self.assertIsNone(dispatch.budget_numbers("## Budget: " + bad if bad else "## Budget"))
        self.assertIsNone(dispatch.budget_numbers("body tokens=1 minutes=1"))

    def test_digit_text_same_on_both(self):                         # V1, BU15, BU16
        for lim in INT_LIMITS:
            with int_limit(lim):
                for n in (599, 600, 601, 4300, 4301):
                    with self.subTest(limit=lim, digits=n):
                        self.assertEqual(dispatch.budget_numbers(self.head("9" * n, 1)), ("9" * n, "1"))
                        self.assertTrue(dispatch.over_cap("9" * n, 5))
                        self.assertEqual(dispatch.over_cap("9" * n, 10 ** 600 - 1), n > 600)
                self.assertFalse(dispatch.over_cap("5", 5))
                self.assertTrue(dispatch.over_cap("6", 5))
                self.assertFalse(dispatch.over_cap("4", 5))

    def test_no_forbidden_calls_in_new_code(self):                 # V2, V3, MU35
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for rel in ("gates/lib/dispatch.py", "gates/gate_dispatch.py"):
            with open(os.path.join(here, rel), encoding="utf-8") as fh:
                src = fh.read()
            for word in (".lower(", ".casefold(", ".isprintable(", ".isidentifier(", ".isalnum(", ".isdigit(", "import unicodedata",
                         "except Exception", "except BaseException", "BaseExceptionGroup"):
                self.assertNotIn(word, src, rel)
