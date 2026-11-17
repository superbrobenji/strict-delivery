"""Tests of gates/lib/dispatch.py (plan Task 2c.3; rows K1-K9, E1-E7, P1-P2, H1-H9, M2, M9, S1-S15 of the input-domain
table task-2c.3-domain.md). Every expected value is written out here by hand from the plan and the spec, never read
back from ``dispatch``. The git rows run on real fixture repositories (``GitIsolatedTestCase``)."""
import os
import unittest

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
                                     "program_controller": 3, "stream_controller": 3, "task_reviewer": 3,
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
