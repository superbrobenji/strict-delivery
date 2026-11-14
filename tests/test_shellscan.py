"""Tests for the shell scanner (gates.lib.shellscan): plain simple commands, the cd form, token_in. Every expected
value is written here from the input-domain table (task-3b.1-domain.md), never computed by the scanner."""
import dataclasses
import time
import unittest

from gates.lib.shellscan import Scan, scan, token_in


def P(argv=(), asg=(), cd=None):
    return {"plain": True, "reason": "", "argv": tuple(argv), "assignments": tuple(asg), "cd": cd}


def NP(reason):
    return {"plain": False, "reason": reason, "argv": (), "assignments": (), "cd": None}


class Sub(str):
    pass


class ScanCase(unittest.TestCase):
    def check(self, text, expected, words=None):
        with self.subTest(text=text):
            s = scan(text)
            got = {"plain": s.plain, "reason": s.reason, "argv": s.argv, "assignments": s.assignments, "cd": s.cd}
            self.assertEqual(got, expected)
            if words is not None:
                self.assertEqual(s.words, tuple(words))

    def many(self, cases):
        for text, expected in cases:
            self.check(text, expected)


class ShapeTest(ScanCase):
    def test_scan_dataclass_shape(self):  # D1
        self.assertEqual([f.name for f in dataclasses.fields(Scan)], ["plain", "cd", "assignments", "argv", "reason", "words"])
        s = scan("git commit")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            s.plain = False
        for t in ("git commit", "a && b", "A=1 git x", "echo $(x)", "cd /w && git commit"):
            with self.subTest(text=t):
                s = scan(t)
                self.assertIs(type(s.argv), tuple)
                self.assertIs(type(s.assignments), tuple)
                self.assertIs(type(s.words), tuple)
        self.assertEqual(scan("A=1 git x").assignments, (("A", "1"),))
        self.assertIs(type(scan("A=1 git x").assignments[0]), tuple)


class SeparatorTest(ScanCase):
    def test_separators_not_plain(self):  # S1-S7, plan Step 1
        s = scan("git add x && git commit")
        self.assertFalse(s.plain)
        self.assertEqual(s.reason, "operator &&")
        self.many([
            ("git add x; git commit", NP("operator ;")),
            ("git add x && git commit", NP("operator &&")),
            ("a || b", NP("operator ||")),
            ("a | b", NP("operator |")),
            ("a |& b", NP("operator |")),
            ("git push &", NP("operator &")),
            ("a & b", NP("operator &")),
            ("a;; b", NP("operator ;")),
            ("a\nb", NP("operator newline")),
            ("\ngit commit", NP("operator newline")),
            ("a\n\nb", NP("operator newline")),
        ])

    def test_trailing_newlines_dropped(self):  # S8
        self.many([("git commit\n", P(("git", "commit"))), ("git commit\n\n\n", P(("git", "commit"))),
                   ("git commit \\\n", P(("git", "commit")))])

    def test_crlf(self):  # S9
        self.many([("git commit\r\n", P(("git", "commit\r"))), ("a\r\nb", NP("operator newline"))])

    def test_plain_commit(self):  # S10, plan Step 1
        s = scan("git commit -m 'a && b'")
        self.assertTrue(s.plain)
        self.assertEqual(s.argv, ("git", "commit", "-m", "a && b"))
        self.check("git commit -m 'a && b'", P(("git", "commit", "-m", "a && b")))

    def test_quoted_separators_plain(self):  # S10
        self.many([
            ('git commit -m "a; b"', P(("git", "commit", "-m", "a; b"))),
            ("git commit -m 'a|b'", P(("git", "commit", "-m", "a|b"))),
            ('echo "x & y"', P(("echo", "x & y"))),
            ("git commit -m 'a\nb'", P(("git", "commit", "-m", "a\nb"))),
            ("echo 'a; b'", P(("echo", "a; b"))),
            ("echo 'a || b'", P(("echo", "a || b"))),
            ('echo "a\nb"', P(("echo", "a\nb"))),
            ("echo 'a |& b'", P(("echo", "a |& b"))),
            ('echo "a ;; b"', P(("echo", "a ;; b"))),
        ])

    def test_first_construct_is_reason(self):  # S11
        self.many([("a > x; b", NP("redirection")), ("a; b > x", NP("operator ;")), ("a $X; b", NP("expansion")),
                   ("a 'oops; b", NP("unbalanced quote")), ("a; 'oops", NP("operator ;")),
                   ("a (b) ; c", NP("grouping")), ("a ; (b)", NP("operator ;"))])


class GroupingTest(ScanCase):
    def test_grouping_and_substitution_not_plain(self):  # G1-G6, plan Step 1
        for t in ("(git commit)", "{ git commit; }", "echo $(git commit)", "echo `git commit`"):
            self.assertFalse(scan(t).plain)
        self.many([
            ("(git commit)", NP("grouping")),
            ("a (b)", NP("grouping")),
            ("((1))", NP("grouping")),
            ("{ git commit; }", NP("grouping")),
            ("a }", NP("grouping")),
            ("a )", NP("grouping")),
            ("echo $(git commit)", NP("substitution")),
            ("echo $((1))", NP("substitution")),
            ("echo `git commit`", NP("substitution")),
            ('echo "`git commit`"', NP("substitution")),
            ('echo "$(git commit)"', NP("substitution")),
            ("diff <(a) b", NP("substitution")),
            ("tee >(a)", NP("substitution")),
            ("'(x)'", P(("(x)",))),
            ('"(x)"', P(("(x)",))),
            ("'$(x)'", P(("$(x)",))),
            ("'{'", P(("{",))),
            ("echo '`x`'", P(("echo", "`x`"))),
            ("echo \\`x\\`", P(("echo", "`x`"))),
        ])

    def test_glob_not_plain(self):  # G7
        self.many([
            ("git add *.py", NP("expansion")),
            ("git add *", NP("expansion")),
            ("ls a*", NP("expansion")),
            ("a?b", NP("expansion")),
            ("x[1]", NP("expansion")),
            ("[", NP("expansion")),
            ("git add '*.py'", P(("git", "add", "*.py"))),
            ('git add "a?b"', P(("git", "add", "a?b"))),
            ("git add \\*.py", P(("git", "add", "*.py"))),
            ("echo x\\[1]", P(("echo", "x[1]"))),
            ("echo x'['1]", P(("echo", "x[1]"))),
        ])

    def test_brace_expansion_not_plain(self):  # G8
        self.many([
            ("{a,b}", NP("expansion")),
            ("x{1..3}", NP("expansion")),
            ("git commit --no-verif{y,}", NP("expansion")),
            ("a{b,c}d", NP("expansion")),
            ("git show HEAD@{1}", P(("git", "show", "HEAD@{1}"))),
            ("x{", P(("x{",))),
            ("a}b", P(("a}b",))),
            ("{}", P(("{}",))),
            ("a{b\\,c}", P(("a{b,c}",))),
            ("a{b','c}", P(("a{b,c}",))),
            ("a{'b'.c}", P(("a{b.c}",))),
            ("}a,{", P(("}a,{",))),
            ("a,{b}", P(("a,{b}",))),
            ("a..{b}", P(("a..{b}",))),
            ("x{a.'x'.b}", P(("x{a.x.b}",))),
            ("{a`,{b}}", NP("expansion")),
        ])

    def test_tilde_not_plain(self):  # G9
        self.many([
            ("cd ~ && x", NP("expansion")),
            ("~/x", NP("expansion")),
            ("A=~/x git", NP("expansion")),
            ("A=a:~/b git", NP("expansion")),
            ("git log HEAD~1", P(("git", "log", "HEAD~1"))),
            ("a~b", P(("a~b",))),
            ("'~'", P(("~",))),
            ("\\~", P(("~",))),
            ("A='~' git", P(("git",), (("A", "~"),))),
            ("A=a:'~' git", P(("git",), (("A", "a:~"),))),
            ("A=a~ git", P(("git",), (("A", "a~"),))),
            ("git --opt=~x", P(("git", "--opt=~x"))),
        ])

    def test_append_assignment_not_plain(self):  # G10
        self.many([("A+=1 git", NP("expansion")), ("git A+=1", P(("git", "A+=1")))])


class ExpansionTest(ScanCase):
    def test_expansions(self):  # X1, X4
        self.many([
            ("echo $X", NP("expansion")),
            ("echo ${X}", NP("expansion")),
            ("echo a$", NP("expansion")),
            ("echo $1", NP("expansion")),
            ("echo $?", NP("expansion")),
            ("echo $", NP("expansion")),
            ("echo $'a'", NP("expansion")),
            ('echo $"a"', NP("expansion")),
        ])

    def test_double_quoted_dollar_not_plain(self):  # X2, X3, X5, plan Step 1
        self.assertEqual(scan('git commit -m "$MSG"').reason, "expansion")
        self.assertTrue(scan("git commit -m '$MSG'").plain)
        self.many([
            ('echo "$X"', NP("expansion")),
            ('echo "a$"', NP("expansion")),
            ("echo '$X'", P(("echo", "$X"))),
            ("echo \\$X", P(("echo", "$X"))),
            ('echo "\\$X"', P(("echo", "$X"))),
        ])


class RedirectionTest(ScanCase):
    def test_redirections(self):  # R1, R2
        for t in (">x", ">>x", "2>&1", "<x", "<<<x", "&>x", "&>>x", ">|x", "<>x", "<&0", "a >x", "a 2>&1", "a <<-x", "a >& x"):
            self.check(t, NP("redirection"))
        self.many([("'>'", P((">",))), ('"a<b"', P(("a<b",))), ("echo '2>&1'", P(("echo", "2>&1")))])

    def test_heredoc_not_plain(self):  # R1, plan Step 1
        self.assertEqual(scan("git commit -F - <<'EOF'\nmsg\nEOF").reason, "redirection")
        self.many([
            ("<<EOF\nb\nEOF", NP("redirection")),
            ("<<-'EOF'\nb\n\tEOF", NP("redirection")),
            ("git commit -F - <<'EOF'\nmsg\nEOF", NP("redirection")),
        ])


class QuoteTest(ScanCase):
    def test_unbalanced_quote_not_plain(self):  # Q1, Q2, plan Step 1
        self.assertEqual(scan("git commit -m 'oops").reason, "unbalanced quote")
        self.check("git commit -m 'oops", NP("unbalanced quote"), ("git", "commit", "-m", "oops"))
        self.many([('git commit -m "oops', NP("unbalanced quote")), ('"a\'', NP("unbalanced quote")),
                   ("git commit \\", NP("unbalanced quote"))])
        self.assertEqual(scan('git "oops x').words, ("git", "oops x"))

    def test_quotes(self):  # Q3-Q8
        self.many([
            ("git commit -m ''", P(("git", "commit", "-m", ""))),
            ('git commit -m ""', P(("git", "commit", "-m", ""))),
            ('""', P(("",))),
            ("a'b'\"c\"", P(("abc",))),
            ("git commit -m 'a\nb'", P(("git", "commit", "-m", "a\nb"))),
            ('git commit -m "a\nb"', P(("git", "commit", "-m", "a\nb"))),
            ('"\\""', P(('"',))),
            ('"\\\\"', P(("\\",))),
            ('"\\$"', P(("$",))),
            ('"\\`"', P(("`",))),
            ('"a\\\nb"', P(("ab",))),
            ('"\\a"', P(("\\a",))),
            ("\\a", P(("a",))),
            ("\\ ", P((" ",))),
            ("\\;", P((";",))),
            ("\\'", P(("'",))),
            ("a\\\nb", P(("ab",))),
            ("'a\\'", P(("a\\",))),
            ("a'b c'd", P(("ab cd",))),
        ])


class WordTest(ScanCase):
    def test_reserved_words(self):  # W1-W3
        self.many([
            ("!", NP("reserved word")),
            ("[[", NP("reserved word")),
            ("]]", NP("reserved word")),
            ("a !", NP("reserved word")),
            ("a!b", P(("a!b",))),
            ("git show HEAD@{1}", P(("git", "show", "HEAD@{1}"))),
            ("x]]", P(("x]]",))),
            ("'!'", P(("!",))),
            ('"[["', P(("[[",))),
            ("'}'", P(("}",))),
        ])

    def test_comments(self):  # W4, W5
        self.many([
            ("git commit # x", NP("comment")),
            ("#x", NP("comment")),
            ("#a$X", NP("comment")),
            ("a;#b", NP("operator ;")),
            ("a#b", P(("a#b",))),
            ("'#x'", P(("#x",))),
            ("\\#x", P(("#x",))),
            ('"#x"', P(("#x",))),
        ])

    def test_empty_text_plain(self):  # W6
        for t in ("", "   ", "\n", "\n\n", " \t "):
            self.check(t, P(), ())

    def test_words_field(self):  # W7
        self.check("git add x && git commit", NP("operator &&"), ("git", "add", "x", "&&", "git", "commit"))
        self.check("a>b", NP("redirection"), ("a", ">", "b"))
        self.check("echo $(git commit)", NP("substitution"), ("echo", "$", "(", "git", "commit", ")"))
        self.check("git commit -m 'a b'", P(("git", "commit", "-m", "a b")), ("git", "commit", "-m", "a b"))
        self.check("2>&1", NP("redirection"), ("2", ">&", "1"))
        self.check("a\nb", NP("operator newline"), ("a", "\n", "b"))
        self.check("a&&b||c;;d;e|&f|g&>>h&>i&j<<<k<<-l<<m<>n<&o<p>>q>&r>|s>t", NP("operator &&"),
                   ("a", "&&", "b", "||", "c", ";;", "d", ";", "e", "|&", "f", "|", "g", "&>>", "h", "&>", "i", "&",
                    "j", "<<<", "k", "<<-", "l", "<<", "m", "<>", "n", "<&", "o", "<", "p", ">>", "q", ">&", "r", ">|",
                    "s", ">", "t"))
        self.check("(a)", NP("grouping"), ("(", "a", ")"))
        self.check("A=1 git x\n", P(("git", "x"), (("A", "1"),)), ("A=1", "git", "x"))
        self.check("cd /w && git commit", P(("git", "commit"), (), "/w"), ("cd", "/w", "&&", "git", "commit"))
        self.check("echo `x`", NP("substitution"), ("echo", "`x`"))


class AssignmentTest(ScanCase):
    def test_assignments_split(self):  # A1-A6, plan Step 1
        self.assertEqual(scan("GIT_INDEX_FILE=x git commit").assignments, (("GIT_INDEX_FILE", "x"),))
        self.many([
            ("A=1 git", P(("git",), (("A", "1"),))),
            ("GIT_INDEX_FILE=x git commit", P(("git", "commit"), (("GIT_INDEX_FILE", "x"),))),
            ("A= git", P(("git",), (("A", ""),))),
            ("1A=x git", P(("1A=x", "git"))),
            ("'A'=1 git", P(("A=1", "git"))),
            ("A\\=1 git", P(("A=1", "git"))),
            ("A-B=1 git", P(("A-B=1", "git"))),
            ("A'B'=1 git", P(("AB=1", "git"))),
            ("A=1", P((), (("A", "1"),))),
            ("A=1 B=2", P((), (("A", "1"), ("B", "2")))),
            ("_a9=1 B2= git x", P(("git", "x"), (("_a9", "1"), ("B2", "")))),
            ("git B=2", P(("git", "B=2"))),
            ("A='x y' git", P(("git",), (("A", "x y"),))),
            ('A="x" git', P(("git",), (("A", "x"),))),
            ("A=b=c git", P(("git",), (("A", "b=c"),))),
            ("A=1 git B=2", P(("git", "B=2"), (("A", "1"),))),
        ])


class CdTest(ScanCase):
    def test_cd_form_is_the_only_plain_compound(self):  # CD1-CD5, plan Step 1
        s = scan("cd /w/x && git commit -m m")
        self.assertTrue(s.plain)
        self.assertEqual((s.cd, s.argv), ("/w/x", ("git", "commit", "-m", "m")))
        for t in ("cd /w/x; git commit", "cd /w/x && cd y && git commit", "cd /w/x && git commit && git push", "cd - && git commit"):
            self.assertFalse(scan(t).plain)
        self.many([
            ("cd /w/x && git commit -m m", P(("git", "commit", "-m", "m"), (), "/w/x")),
            ("cd '/w/a b' && git push", P(("git", "push"), (), "/w/a b")),
            ("cd /w/x&&git commit", P(("git", "commit"), (), "/w/x")),
            ("cd /w/x && A=1 git commit", P(("git", "commit"), (("A", "1"),), "/w/x")),
            ("cd /w/x && cd y", P(("cd", "y"), (), "/w/x")),
            ("cd /w/x && git commit\n", P(("git", "commit"), (), "/w/x")),
            ("cd /w/x; git commit", NP("operator ;")),
            ("cd /w/x || git commit", NP("operator ||")),
            ("cd && git commit", NP("operator &&")),
            ("cd - && git commit", NP("operator &&")),
            ("cd -P /w && git commit", NP("operator &&")),
            ("cd -P && git commit", NP("operator &&")),
            ("ls /w && git commit", NP("operator &&")),
            ("cd -- && git commit", NP("operator &&")),
            ("cd a b && x", NP("operator &&")),
            ("cd '' && x", NP("operator &&")),
            ('"cd" /w && x', NP("operator &&")),
            ("A=1 cd /w && x", NP("operator &&")),
            ("cd /w/x && cd y && git commit", NP("operator &&")),
            ("cd /w/x && git commit && git push", NP("operator &&")),
            ("cd /w/x &&", NP("operator &&")),
            ("cd /w/x && git commit # c", NP("comment")),
            ("cd $W && git commit", NP("expansion")),
            ("cd /w/x && git commit; git push", NP("operator ;")),
            ("cd /w/x && git commit > o", NP("redirection")),
            ("cd /w/x && A+=1 git", NP("expansion")),
        ])


class CharacterTest(ScanCase):
    def test_characters(self):  # CH1-CH4
        self.check("git\tcommit", P(("git", "commit")))
        self.check("git commit -m é", P(("git", "commit", "-m", "é")))
        for ch in (" ", " ", "　", "\u0085"):
            self.check("git%scommit" % ch, P(("git%scommit" % ch,)))
        for t in ("git\x00commit", "'a\x00'"):
            with self.subTest(text=t):
                s = scan(t)
                self.assertFalse(s.plain)
                self.assertEqual(s.reason, "nul character")
                self.assertEqual((s.argv, s.assignments, s.cd), ((), (), None))
        for ch in ("\x01", "\x0b", "\x0c", "\x1b", "\x7f"):
            self.check("a%sb c" % ch, P(("a%sb" % ch, "c")))

    def test_non_str_text_is_type_error(self):  # CH5, V3
        for bad in (None, b"git", Sub("git"), 5, ["git"]):
            with self.subTest(bad=bad):
                with self.assertRaises(TypeError):
                    scan(bad)

    def test_long_text_linear(self):  # CH6
        t0 = time.perf_counter()
        s = scan("a " * 100000)
        took = time.perf_counter() - t0
        self.assertTrue(s.plain)
        self.assertEqual(len(s.argv), 100000)
        self.assertLess(took, 2.0)

    def test_huge_numbers_are_text(self):  # V1
        d4300, d4301 = "7" * 4300, "7" * 4301
        self.check("git commit -m " + d4300, P(("git", "commit", "-m", d4300)))
        self.check("git commit -m " + d4301, P(("git", "commit", "-m", d4301)))
        self.check("A=%s git" % d4301, P(("git",), (("A", d4301),)))
        self.check(d4301 + ">x", NP("redirection"))

    def test_unicode_version_independent(self):  # V2
        self.check("a\U0001f6ddb x", P(("a\U0001f6ddb", "x")))
        self.check("a᠎b x", P(("a᠎b", "x")))
        self.check("A١=1 git", P(("A١=1", "git")))
        self.check("١=1 git", P(("١=1", "git")))
        self.check("A=١ git", P(("git",), (("A", "١"),)))
        self.assertEqual(scan("a\U0001f6ddb ᠎").argv, ("a\U0001f6ddb", "᠎"))


class TokenInTest(unittest.TestCase):
    def test_token_boundaries(self):  # T1-T5, T9, plan Step 1
        self.assertIs(token_in("xgit commit", "git"), False)
        self.assertTrue(token_in("a 'git' b", "git"))
        self.assertTrue(token_in("core.HooksPath", "hookspath", True))
        for text in ("git x", "x git", "git"):
            with self.subTest(text=text):
                self.assertIs(token_in(text, "git"), True)
        for text in ("xgit", "git-x", "-git", "_git", "git_", "1git", "git2"):
            with self.subTest(text=text):
                self.assertIs(token_in(text, "git"), False)
        for text in (".git", "/git", '"git"', "'git'", "git.", "(git)", "égit", "gité"):
            with self.subTest(text=text):
                self.assertIs(token_in(text, "git"), True)
        for text in ("xgit git", "gitgit git", "git-x git", "gitgit git gitgit"):
            with self.subTest(text=text):
                self.assertIs(token_in(text, "git"), True)
        self.assertIs(token_in("core.HooksPath", "hookspath", False), False)
        self.assertIs(token_in("core.HooksPath", "hookspath"), False)
        self.assertIs(token_in("core.hookspath", "HooksPath", True), True)
        self.assertIs(token_in("x.HOOKSPATHx", "hookspath", True), False)
        self.assertIs(token_in("gh pr merge", "pr merge"), True)
        self.assertIs(token_in("gh xpr merge", "pr merge"), False)
        self.assertIs(token_in("gh pr merge9", "pr merge"), False)
        self.assertIs(token_in("a\nb", "b"), True)
        self.assertIs(token_in("--no-verify", "no"), False)

    def test_token_casefold_ascii_only(self):  # T6, T7
        self.assertIs(token_in("KOOKSPATH", "kookspath", True), False)
        self.assertIs(token_in("HOOKSPATH", "hookspath", True), False)
        self.assertIs(token_in("HOOKSPATH", "hookspath", True), True)
        self.assertIs(token_in("xK", "k", True), False)
        self.assertIs(token_in("hooksİpath", "hooksipath", True), False)
        self.assertIs(token_in("K", "k", True), False)
        self.assertIs(token_in("a{", "a[", True), False)
        self.assertIs(token_in("a`", "a@", True), False)
        self.assertIs(token_in("Z", "z", True), True)
        self.assertIs(token_in("xa.a.a", "a.a"), True)
        self.assertIs(token_in("K", "k", True), True)
        self.assertIs(token_in("a", ""), False)
        self.assertIs(token_in("", ""), False)
        self.assertIs(token_in("", "a"), False)

    def test_token_in_type_error(self):  # T8
        for args in ((None, "a"), ("a", None), (b"a", "a"), ("a", b"a"), (Sub("a"), "a"), ("a", Sub("a")), (1, 1)):
            with self.subTest(args=args):
                with self.assertRaises(TypeError):
                    token_in(*args)
