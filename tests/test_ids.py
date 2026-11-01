"""Tests for ids (gates.lib.ids): validation, minting, the UTC date. Expected values are written here, not derived
from the code under test."""
import datetime
import itertools
import random
import string
import types
import unittest
from unittest import mock

from gates.lib import ids
from gates.lib.ids import ALPHABET, id_pattern, id_problem, mint, utc_today
from gates.lib.result import GateError

GOOD = "DEC-20261031-k3f9"
LITERAL_ALPHABET = "23456789abcdefghijkmnpqrstuvwxyz"


class Sub(str):
    pass


class AlphabetTest(unittest.TestCase):
    def test_alphabet_is_32_chars_without_0_1_l_o(self):
        self.assertEqual(ALPHABET, LITERAL_ALPHABET)
        self.assertEqual(len(ALPHABET), 32)
        self.assertFalse(set("01lo") & set(ALPHABET))
        self.assertTrue(set("k3f9") <= set(ALPHABET))


class IdProblemTest(unittest.TestCase):
    def refused(self, value, prefix="DEC"):
        reason = id_problem(value, prefix)
        self.assertNotEqual(reason, "", repr(value))
        self.assertIsInstance(reason, str)
        self.assertIn(LITERAL_ALPHABET, reason, repr(value))
        self.assertIn(prefix, reason)
        return reason

    def test_example_id_valid(self):  # I1 exact str, I5 right prefix
        self.assertEqual(id_problem(GOOD, "DEC"), "")
        self.assertEqual(id_problem("F-20261031-k3f9", "F"), "")

    def test_every_alphabet_char_valid_in_every_position(self):  # I3 positive side
        for pos in range(4):
            for c in LITERAL_ALPHABET:
                suffix = "2222"[:pos] + c + "2222"[pos + 1:]
                self.assertEqual(id_problem("DEC-20261031-" + suffix, "DEC"), "", suffix)

    def test_value_type(self):  # I1
        for v in (Sub(GOOD), 7, None, True, False, GOOD.encode(), 1.5, [GOOD], (GOOD,)):
            self.refused(v)

    def test_str_subclass_refused_like_non_str(self):  # I1 owner Q-1a3-1
        self.assertEqual(id_problem(GOOD, "DEC"), "")
        self.assertNotEqual(id_problem(Sub(GOOD), "DEC"), "")

    def test_hand_written_bad_ids_refused(self):  # Review Focus 3
        for v in ["DEC-20261031-K3F9", "DEC-20261031-l0o1", "DEC-20261031-k3f", "DEC-20261031-k3f9a",
                  "F-20261031-k3f9", "DEC-2026103-k3f9", " DEC-20261031-k3f9", "DEC-20261031-k3f9\n", 7, None,
                  True]:
            reason = id_problem(v, "DEC")
            self.assertNotEqual(reason, "", repr(v))
            self.assertIn(ALPHABET, reason)

    def test_case(self):  # I2
        for v in ["DEC-20261031-K3F9", "DEC-20261031-k3F9", "DEC-20261031-k3f9".replace("k", "K"),
                  "dec-20261031-k3f9", "Dec-20261031-k3f9"]:
            self.refused(v)

    def test_excluded_suffix_chars(self):  # I3
        for c in "01lo":
            for pos in range(4):
                suffix = "2222"[:pos] + c + "2222"[pos + 1:]
                self.refused("DEC-20261031-" + suffix)

    def test_uppercase_letters(self):  # I3
        for c in string.ascii_uppercase:
            self.refused("DEC-20261031-22%s2" % c)

    def test_non_ascii_suffix_chars(self):  # I3
        for c in ("é", "３", "ａ", "٢", "ḱ"):
            self.refused("DEC-20261031-22%s2" % c)

    def test_suffix_length(self):  # I4
        self.refused("DEC-20261031-k3f")
        self.refused("DEC-20261031-k3f9a")
        self.refused("DEC-20261031-")
        self.assertEqual(id_problem("DEC-20261031-k3f9", "DEC"), "")

    def test_prefix(self):  # I5
        self.refused("F-20261031-k3f9")           # another kind's prefix
        self.refused("DE-20261031-k3f9")          # DEC vs DE
        self.refused("DECX-20261031-k3f9")
        self.refused("DEC--20261031-k3f9")        # extra '-'
        self.refused("-20261031-k3f9")            # empty prefix
        self.refused("20261031-k3f9")
        self.refused("DEC-20261031-k3f9", "DE")   # the configured prefix decides
        self.refused("DEC-20261031-k3f9", "F")
        self.assertEqual(id_problem("DE-20261031-k3f9", "DE"), "")

    def test_prefix_is_literal_not_a_pattern(self):  # I5: a regex-special prefix matches only itself
        self.refused("DEC-20261031-k3f9", "D.C")
        self.refused("DEC-20261031-k3f9", "DEC|X")

    def test_date_digits(self):  # I6
        self.refused("DEC-2026103-k3f9")
        self.refused("DEC-202610311-k3f9")
        self.refused("DEC-2026103a-k3f9")
        self.refused("DEC-٢٠٢٦١٠٣١-k3f9")         # Arabic-indic digits
        self.refused("DEC-２０２６１０３１-k3f9")  # fullwidth digits

    def test_date_must_be_calendar_valid(self):  # OQ-3, I7
        for d in ("20260230", "20261399", "20261300", "20261032", "00000101", "20260431", "20230229"):
            self.refused("DEC-%s-k3f9" % d)
        for d in ("20240229", "20991231", "00010101", "20260101", "99991231"):
            self.assertEqual(id_problem("DEC-%s-k3f9" % d, "DEC"), "", d)

    def test_date_never_compared_with_clock(self):  # I7
        with mock.patch.object(ids, "utc_today", side_effect=AssertionError("clock read")):
            self.assertEqual(id_problem("DEC-29991231-k3f9", "DEC"), "")

    def test_surroundings(self):  # I8
        for v in (" " + GOOD, GOOD + " ", GOOD + "\n", "\n" + GOOD, GOOD + "\r\n", GOOD[:4] + "\x00" + GOOD[4:],
                  GOOD + "\x00", "\t" + GOOD):
            self.refused(v)

    def test_id_pattern_fullmatch(self):
        pat = id_pattern("DEC")
        self.assertTrue(pat.fullmatch(GOOD))
        self.assertIsNone(pat.fullmatch(GOOD + "x"))
        self.assertIsNone(pat.fullmatch(GOOD + "\n"))
        self.assertEqual(pat.fullmatch(GOOD).group(1), "20261031")


class MintTest(unittest.TestCase):
    D = datetime.date(2026, 10, 31)

    def test_mint_matches_pattern_and_seeded_draw(self):  # I9 oracle
        got = mint("DEC", set(), self.D, random.Random(0))
        rng = random.Random(0)
        self.assertEqual(got, "DEC-20261031-" + "".join(rng.choice(LITERAL_ALPHABET) for _ in range(4)))
        self.assertEqual(id_problem(got, "DEC"), "")
        self.assertTrue(id_pattern("DEC").fullmatch(got))

    def test_mint_redraws_on_collision(self):  # I9
        first = mint("DEC", set(), self.D, random.Random(0))
        new = mint("DEC", {first}, self.D, random.Random(0))
        self.assertNotEqual(new, first)
        self.assertTrue(id_pattern("DEC").fullmatch(new))
        rng = random.Random(0)
        draws = ["".join(rng.choice(LITERAL_ALPHABET) for _ in range(4)) for _ in range(2)]
        self.assertEqual(new, "DEC-20261031-" + draws[1])

    def test_other_prefix_or_date_does_not_block(self):  # I9
        first = mint("DEC", set(), self.D, random.Random(0))
        other = {first.replace("DEC", "F"), first.replace("20261031", "20261101"), "DEC-20261031-ZZZZ", 5, None}
        self.assertEqual(mint("DEC", other, self.D, random.Random(0)), first)

    def test_mint_uses_given_date(self):  # I11
        self.assertTrue(mint("F", set(), datetime.date(2026, 10, 31), random.Random(1)).startswith("F-20261031-"))
        self.assertTrue(mint("F", set(), datetime.date(2026, 11, 1), random.Random(1)).startswith("F-20261101-"))

    def test_mint_old_year_keeps_eight_digits(self):  # I11
        got = mint("DEC", set(), datetime.date(999, 1, 2), random.Random(1))
        self.assertTrue(got.startswith("DEC-09990102-"), got)
        self.assertEqual(id_problem(got, "DEC"), "")

    def test_mint_takes_a_datetime_date_part(self):  # I11: today is a date; a datetime is a date subclass
        got = mint("DEC", set(), datetime.datetime(2026, 10, 31, 23, 59, 59), random.Random(1))
        self.assertTrue(got.startswith("DEC-20261031-"))

    def test_exhaustion_raises_without_drawing(self):  # I10, owner Q-1a3-2
        everything = {"DEC-20261031-" + "".join(t) for t in itertools.product(LITERAL_ALPHABET, repeat=4)}
        self.assertEqual(len(everything), 32 ** 4)
        rng = mock.Mock(spec=random.Random)
        rng.choice.side_effect = AssertionError("drew before the exhaustion check")
        with self.assertRaises(GateError) as cm:
            mint("DEC", everything, self.D, rng)
        self.assertIn("DEC", str(cm.exception))
        self.assertIn("20261031", str(cm.exception))
        self.assertEqual(rng.choice.call_count, 0)

    def test_one_free_suffix_is_found(self):  # I10 boundary: 32^4 - 1 taken
        everything = {"DEC-20261031-" + "".join(t) for t in itertools.product(LITERAL_ALPHABET, repeat=4)}
        everything.discard("DEC-20261031-k3f9")
        self.assertEqual(mint("DEC", everything, self.D, random.Random(5)), "DEC-20261031-k3f9")

    def test_strings_that_are_not_ids_do_not_count_toward_exhaustion(self):  # I10
        everything = {"DEC-20261031-" + "".join(t) for t in itertools.product(LITERAL_ALPHABET, repeat=4)}
        everything.discard("DEC-20261031-k3f9")
        everything |= {"DEC-20261031-0000", "DEC-20261031-k3f9x", "DEC-20261031-K3F9"}
        self.assertEqual(mint("DEC", everything, self.D, random.Random(5)), "DEC-20261031-k3f9")

    def test_full_day_of_another_prefix_or_date_is_not_exhaustion(self):  # I10
        full = {"F-20261031-" + "".join(t) for t in itertools.product(LITERAL_ALPHABET, repeat=4)}
        full |= {"DEC-20261030-" + s[-4:] for s in full}
        self.assertTrue(mint("DEC", full, self.D, random.Random(5)).startswith("DEC-20261031-"))


class UtcTodayTest(unittest.TestCase):
    def fake_module(self, instant):
        real = datetime

        class FakeDateTime(real.datetime):
            @classmethod
            def now(cls, tz=None):
                if tz is None:  # local time: a zone fourteen hours ahead of UTC
                    return instant.astimezone(real.timezone(real.timedelta(hours=14))).replace(tzinfo=None)
                return instant.astimezone(tz)

        return types.SimpleNamespace(datetime=FakeDateTime, timezone=real.timezone, date=real.date,
                                     timedelta=real.timedelta)

    def test_utc_today_uses_utc_not_local_time(self):  # I11
        instant = datetime.datetime(2026, 10, 31, 23, 59, 59, tzinfo=datetime.timezone.utc)
        with mock.patch.object(ids, "datetime", self.fake_module(instant)):
            self.assertEqual(utc_today(), datetime.date(2026, 10, 31))  # local would say 2026-11-01

    def test_utc_today_after_midnight(self):  # I11
        instant = datetime.datetime(2026, 11, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
        with mock.patch.object(ids, "datetime", self.fake_module(instant)):
            self.assertEqual(utc_today(), datetime.date(2026, 11, 1))

    def test_utc_today_is_a_plain_date(self):
        got = utc_today()
        self.assertIs(type(got), datetime.date)


if __name__ == "__main__":
    unittest.main()
