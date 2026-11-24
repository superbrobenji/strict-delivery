"""Tests for the shell scanner (gates.lib.shellscan): the closed grammar of plain commands, the cd form, token_in.
Every expected value is written here from the input-domain table (task-3b.1-domain-r4.md, revision 4, and the rows
of task-3b.1-domain.md that it carries), never computed by the scanner."""
import dataclasses
import gc
import signal
import time
import unittest

import gates.lib.shellscan as shellscan
from gates.lib.shellscan import Scan, scan, token_in

# K: bash and zsh reserved words and zsh precommand modifiers (rows N7, W8, W9).
K = ("case coproc do done elif else esac fi for function if in select then time until while repeat foreach end "
     "nocorrect noglob declare export float integer local readonly typeset - builtin command exec").split()
ALLOW = ("GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY", "LANG", "LC_ALL", "TZ")


def P(argv=(), asg=(), cd=None):
    return {"plain": True, "reason": "", "argv": tuple(argv), "assignments": tuple(asg), "cd": cd}


def NP(reason):
    return {"plain": False, "reason": reason, "argv": (), "assignments": (), "cd": None}


class Sub(str):
    pass


# CH6 (F6; r4 R4-3; r5 F5-2, F5-3): each shape is timed at n and CH6_SPAN * n units; a linear scanner gives a growth
# ratio near CH6_SPAN (16), a quadratic one near CH6_SPAN ** 2 (256); the bound sits between them (fix round 5: the
# span was 4 with bound 8, which a quadratic with a small constant passed by chance). No wall-clock bound.
CH6_SPAN = 16
CH6_BOUND = 64
CH6_ROUNDS = 3


def _fields(s):
    return {"plain": s.plain, "reason": s.reason, "argv": s.argv, "assignments": s.assignments, "cd": s.cd,
            "words": s.words}


def _pw(argv, words, asg=(), cd=None):
    exp = P(argv, asg, cd)
    exp["words"] = tuple(words)
    return exp


def _npw(reason, words):
    exp = NP(reason)
    exp["words"] = tuple(words)
    return exp


def _scan(text):
    return _fields(scan(text))


def _token(text):
    return token_in(text, "a")


# (name, n, text of k units, call, expected result for k units written by hand). The path each shape enters in
# gates/lib/shellscan.py is named; the fix-5 transcript holds a quadratic mutant per path, each failing this test.
CH6_SHAPES = (
    # _tokenize: the fast path (_WHOLE) and the blank branch; scan: the token loops; _chars on a fast word
    ("fast", 20000, lambda k: "a " * k, _scan, lambda k: _pw(("a",) * k, ("a",) * k)),
    # the _RUN slow path, then an escaped character, per unit (one word)
    ("escaped", 2000, lambda k: "x " + "a\\ " * k, _scan, lambda k: _pw(("x", "a " * k), ("x", "a " * k))),
    # a single-quoted part per word, and flush and _word_checks per word
    ("quoted", 2000, lambda k: "x " + "'a' " * k, _scan, lambda k: _pw(("x",) + ("a",) * k, ("x",) + ("a",) * k)),
    # the per-character loop of one single-quoted part
    ("sq-word", 4000, lambda k: "x '" + "a" * k + "'", _scan, lambda k: _pw(("x", "a" * k), ("x", "a" * k))),
    # a double-quoted part per word
    ("dq", 2000, lambda k: "x " + '"a" ' * k, _scan, lambda k: _pw(("x",) + ("a",) * k, ("x",) + ("a",) * k)),
    # the per-character loop of one double-quoted part; _word_checks per character
    ("dq-word", 4000, lambda k: 'x "' + "a" * k + '"', _scan, lambda k: _pw(("x", "a" * k), ("x", "a" * k))),
    # the four escapes inside double quotes (\" \\ \$ \`)
    ("dq-escape", 1000, lambda k: 'x "' + '\\"\\\\\\$\\`' * k + '"', _scan,
     lambda k: _pw(("x", '"\\$`' * k), ("x", '"\\$`' * k))),
    # a line join inside double quotes
    ("dq-join", 2000, lambda k: 'x "' + ".\\\n" * k + '"', _scan, lambda k: _pw(("x", "." * k), ("x", "." * k))),
    # a $ and a backtick inside double quotes
    ("dq-subst", 1000, lambda k: "x " + '"$a`b`" ' * k, _scan,
     lambda k: _npw("expansion", ("x",) + ("$a`b`",) * k)),
    # an unquoted $ and an unquoted backtick (the slow path's own branches), one word
    ("subst", 2000, lambda k: "x " + "$`" * k, _scan, lambda k: _npw("expansion", ("x", "$`" * k))),
    # a line join between words
    ("join", 4000, lambda k: "x" + " \\\n" * k + " y", _scan, lambda k: _pw(("x", "y"), ("x", "y"))),
    # an unquoted newline (an operator) per unit
    ("newline", 2000, lambda k: "a\n" * k + "b", _scan, lambda k: _npw("operator newline", ("a", "\n") * k + ("b",))),
    # an operator per unit; scan's operator loop
    ("operator", 2000, lambda k: "a ; " * k + "b", _scan, lambda k: _npw("operator ;", ("a", ";") * k + ("b",))),
    # the assignment value loop of _word_checks (a ':' before each value character)
    ("value", 4000, lambda k: "TZ=" + "a:" * k + " git", _scan,
     lambda k: _pw(("git",), ("TZ=" + "a:" * k, "git"), (("TZ", "a:" * k),))),
    # the name loop of _assign_head
    ("name", 4000, lambda k: "A" * k + "=1 git", _scan, lambda k: _npw("assignment", ("A" * k + "=1", "git"))),
    # scan's leading-assignment loop and the assignment loop of the argv assembly
    ("assignments", 6000, lambda k: "TZ=1 " * k + "git", _scan,
     lambda k: _pw(("git",), ("TZ=1",) * k + ("git",), (("TZ", "1"),) * k)),
    # the loop of _digits_assign and _chars on one long fast-path program word
    ("digits", 8000, lambda k: "1" * k + " x", _scan, lambda k: _pw(("1" * k, "x"), ("1" * k, "x"))),
    # the loop of _program_word
    ("program", 4000, lambda k: "/" + "a/" * k + " x", _scan,
     lambda k: _pw(("/" + "a/" * k, "x"), ("/" + "a/" * k, "x"))),
    # the cd prefix: the segment loop of _cd_target
    ("cd", 40000, lambda k: "cd /" + "a/" * k + " && git x", _scan,
     lambda k: _pw(("git", "x"), ("cd", "/" + "a/" * k, "&&", "git", "x"), cd="/" + "a/" * k)),
    # the occurrence loop of token_in (every occurrence has a token character beside it)
    ("token_in", 256000, lambda k: "a" * k, _token, lambda k: False),
)


class _OverBudget(Exception):
    pass


def _over_budget(signum, frame):
    raise _OverBudget()


def _cpu(call, text, limit):
    """CPU seconds of ``call(text)`` and its result; ``(None, None)`` when the call reaches ``limit`` CPU seconds (an
    ITIMER_PROF signal stops it, so a quadratic run never runs long); ``limit`` 0 sets no limit."""
    try:
        signal.setitimer(signal.ITIMER_PROF, limit)
        try:
            t0 = time.process_time()
            out = call(text)
            took = time.process_time() - t0
        finally:
            signal.setitimer(signal.ITIMER_PROF, 0)
    except _OverBudget:
        return None, None
    return took, out


def ch6_growth(shape, check, n):
    """Time one CH6 shape at base size n: CH6_ROUNDS rounds, each first n units then CH6_SPAN * n units (the sizes
    alternate, so a change in machine load falls on both); CPU time of this process, the cyclic collector off while
    timed (its cost follows the size of the whole test process, not the text). ``check(result, expected)`` runs on
    every finished call. A large run stopped at CH6_BOUND times the smallest small run so far counts as infinite: its
    ratio to the final smallest small run is above the bound too, so the stop never changes the verdict.
    Returns (ratio, small, large)."""
    name, _n, make, call, expect = shape
    big = CH6_SPAN * n
    texts = {n: make(n), big: make(big)}
    took = {n: [], big: []}
    enabled = gc.isenabled()
    old = signal.signal(signal.SIGPROF, _over_budget)
    try:
        for _ in range(CH6_ROUNDS):
            for size in (n, big):
                limit = 0 if size == n else CH6_BOUND * min(took[n])
                gc.disable()
                t, out = _cpu(call, texts[size], limit)
                if enabled:
                    gc.enable()
                if t is None:
                    took[size].append(float("inf"))
                    continue
                took[size].append(t)
                check(out, expect(size))
    finally:
        signal.setitimer(signal.ITIMER_PROF, 0)
        signal.signal(signal.SIGPROF, old)
        if enabled:
            gc.enable()
    return min(took[big]) / min(took[n]), took[n], took[big]


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
        for t in ("git commit", "a && b", "TZ=1 git x", "echo $(x)", "cd /w && git commit"):
            with self.subTest(text=t):
                s = scan(t)
                self.assertIs(type(s.argv), tuple)
                self.assertIs(type(s.assignments), tuple)
                self.assertIs(type(s.words), tuple)
        self.assertEqual(scan("TZ=1 git x").assignments, (("TZ", "1"),))
        self.assertIs(type(scan("TZ=1 git x").assignments[0]), tuple)


class SeparatorTest(ScanCase):
    def test_separators_not_plain(self):  # N1: S1-S7, plan Step 1
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

    def test_trailing_newlines_dropped(self):  # N1 boundary: S8
        self.many([("git commit\n", P(("git", "commit"))), ("git commit\n\n\n", P(("git", "commit"))),
                   ("git commit \\\n", P(("git", "commit"))), ("git commit \\\n -m x", P(("git", "commit", "-m", "x")))])

    def test_plain_commit(self):  # S10, plan Step 1
        s = scan("git commit -m 'a && b'")
        self.assertTrue(s.plain)
        self.assertEqual(s.argv, ("git", "commit", "-m", "a && b"))
        self.check("git commit -m 'a && b'", P(("git", "commit", "-m", "a && b")))

    def test_quoted_separators_plain(self):  # N1 boundary: S10
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

    def test_every_separator_inside_both_quote_kinds(self):  # S10, F3b-2: plan :3600 "each unquoted and inside single and double quotes"
        # the separator stays in the word, kind by kind; a trailing newline and CRLF are separators too
        seps = [("&&", "a && b"), ("||", "a || b"), ("|", "a | b"), ("|&", "a |& b"), ("&", "a & b"), (";;", "a ;; b"),
                (";", "a ; b"), ("newline", "a\nb"), ("trailing newline", "a\n"), ("CRLF", "a\r\nb")]
        for name, word in seps:
            for q in ("'", '"'):
                with self.subTest(sep=name, quote=q):
                    self.check("echo %s%s%s" % (q, word, q), P(("echo", word)))
        for q in ("'", '"'):
            with self.subTest(sep="plan :3686 git commit -m", quote=q):
                self.check("git commit -m %sa && b%s" % (q, q), P(("git", "commit", "-m", "a && b")))

    def test_first_construct_is_reason(self):  # S11 and the section 1 precedence (invariant: first construct wins)
        self.many([("a > x; b", NP("redirection")), ("a; b > x", NP("operator ;")), ("a $X; b", NP("expansion")),
                   ("a 'oops; b", NP("unbalanced quote")), ("a; 'oops", NP("operator ;")),
                   ("a (b) ; c", NP("grouping")), ("a ; (b)", NP("operator ;")),
                   # a catch-all at a smaller position wins over a specific construct after it
                   ("x a'b' > o", NP("quoting")), ("x é $X", NP("character")), ("A=1 git > o", NP("assignment")),
                   ("'git' > o", NP("command word")),
                   # at the same position a specific construct wins over a catch-all
                   ("=git", NP("expansion")), ("! x", NP("reserved word")), ("A+=1 git", NP("expansion")),
                   ("x {", NP("grouping")), ("x }", NP("grouping")),
                   # r4: `{a,b}` is no brace expansion any more; the program word ranks over the `{` character (N15)
                   ("{a,b}", NP("command word")),
                   # r4: an unquoted brace is `character` at its own position, before or after another construct
                   ("x a} $X", NP("character")), ("x $X a}", NP("expansion")), ("x {*}", NP("character")),
                   ("x *{", NP("expansion")), ("x a}; y", NP("character")), ("x a} > o", NP("character")),
                   ("x a'b{", NP("unbalanced quote")), ("x a{'b", NP("character"))])


class GroupingTest(ScanCase):
    def test_grouping_and_substitution_not_plain(self):  # N2, N3: G1-G6, plan Step 1
        for t in ("(git commit)", "{ git commit; }", "echo $(git commit)", "echo `git commit`"):
            self.assertFalse(scan(t).plain)
        self.many([
            ("(git commit)", NP("grouping")),
            ("a (b)", NP("grouping")),
            ("((1))", NP("grouping")),
            ("{ git commit; }", NP("grouping")),
            ("a }", NP("grouping")),
            ("a )", NP("grouping")),
            ("{", NP("grouping")),
            ("}", NP("grouping")),  # r4 invariant: a lone unquoted `{` or `}` keeps the specific reason
            ("x {", NP("grouping")),
            ("x } y", NP("grouping")),
            ("TZ=1 { git commit; }", NP("grouping")),
            ("cd /w && { git commit; }", NP("grouping")),
            ("echo $(git commit)", NP("substitution")),
            ("echo $((1))", NP("substitution")),
            ("echo `git commit`", NP("substitution")),
            ('echo "`git commit`"', NP("substitution")),
            ('echo "$(git commit)"', NP("substitution")),
            ("diff <(a) b", NP("substitution")),
            ("tee >(a)", NP("substitution")),
            ("x '(x)'", P(("x", "(x)"))),
            ('x "(x)"', P(("x", "(x)"))),
            ("x '$(x)'", P(("x", "$(x)"))),
            ("x '{'", P(("x", "{"))),
            ("echo '`x`'", P(("echo", "`x`"))),
            ("echo \\`x\\`", P(("echo", "`x`"))),
            # the same quoted texts as the program word are a quoted program word (N8)
            ("'(x)'", NP("command word")),
            ('"(x)"', NP("command word")),
            ("'{'", NP("command word")),
        ])

    def test_glob_not_plain(self):  # N4: G7
        self.many([
            ("git add *.py", NP("expansion")),
            ("git add *", NP("expansion")),
            ("ls a*", NP("expansion")),
            ("x a?b", NP("expansion")),
            ("x x[1]", NP("expansion")),
            ("[", NP("expansion")),
            ("x [", NP("expansion")),
            ("*x", NP("expansion")),
            ("git add '*.py'", P(("git", "add", "*.py"))),
            ('git add "a?b"', P(("git", "add", "a?b"))),
            ("git add \\*.py", P(("git", "add", "*.py"))),
            ("echo x\\[1]", NP("character")),  # `]` unquoted is outside U (N11)
            ("echo x'[1]'", P(("echo", "x[1]"))),
            ("echo x'['1']'", P(("echo", "x[1]"))),
            ("a?b", NP("command word")),  # the program word sits at position 0
        ])

    def test_brace_not_plain(self):  # N15 (r4; R4-1, R4-2), replaces the G8 test: every unquoted `{` or `}` refused
        # R4-1 (zsh close brace): a `}` that ends a word, as an argument
        r41 = ("x}", "a{b}}", "'{'}", "a\\{}", '"a"}', "''a}", "+}", "x\\{a,b}")
        # R4-2 (zsh brace range with quoted or escaped separators or bounds)
        r42 = ("{1.\\.3}", "{1.'.'3}", '{1".".3}', "{1'..'3}", "{'1..3'}", '{"1..3"}', "c{o.'.'o}mmit", "{-1.\\.1}",
               "{01.\\.3}", "{1.\\.3.\\.2}")
        # the forms that were `expansion` or plain before r4
        old = ("{a,b}", "x{a,b}y", "x{1..3}", "HEAD@{1}", "@{u}", "x{", "a{b}", "x}y", "{a", "}a", "{}", "}a,{",
               "a{b,c}d", "a{b\\,c}", "a{b','c}", "a{'b'.c}", "a,{b}", "a..{b}", "x{a.'x'.b}", "'a'{b", "{a}")
        for m in r41 + r42 + old:
            self.check("x " + m, NP("character"))
            self.check("x " + m + " y", NP("character"))
        # every R4-1 member followed by a line join and a second command, and at the end (row N15)
        for m in r41:
            self.check("git commit -m " + m + "\\\n git push --force", NP("character"))
            self.check("p " + m + "\\\n\\\n q y", NP("character"))
            self.check("p " + m + "\\\n\tq y", NP("character"))
            self.check("p " + m + "\\\n", NP("character"))
        self.many([
            # R4-1 reproducers: a line join and a second command after the `}`, and the `}` at the end
            ("git commit -m x}\\\n git push --force", NP("character")),
            ("p a}\\\n\\\n q y", NP("character")),
            ("p a}\\\n\tq y", NP("character")),
            ("p x}\\\n", NP("character")),
            ("p x}", NP("character")),
            ("p x}\n", NP("character")),
            # R4-2 reproducer
            ("git commit --no-verif{y.\\.y}", NP("character")),
            ("git commit --no-verif{y,}", NP("character")),
            ("x a{b,c}d", NP("character")),
            ("git show HEAD@{1}", NP("character")),
            ("x x{1..3}", NP("character")),
            ("x a}b", NP("character")),
            ("x x{", NP("character")),
            # in the program word (N8), in an assignment value, in the cd target
            ("{a,b}", NP("command word")),
            ("{a`,{b}}", NP("command word")),
            ("{a x", NP("command word")),
            ("}a x", NP("command word")),
            ("x{1..3}", NP("command word")),
            ("TZ=x} git", NP("character")),
            ("TZ=a{1.\\.3}b git", NP("character")),
            ("TZ={a,b} git", NP("character")),
            ("TZ=1 git x}", NP("character")),
            ("cd /w/a} && x", NP("character")),
            ("cd /w/{a,b} && x", NP("character")),
            ("cd /w && git x{", NP("character")),
            # a lone brace keeps `grouping` (N2)
            ("a }", NP("grouping")),
            ("{ git commit; }", NP("grouping")),
            # still plain: quoted or escaped braces are ordinary (the plan example, revised, is 'HEAD@{1}')
            ("git show 'HEAD@{1}'", P(("git", "show", "HEAD@{1}"))),
            ('git show "HEAD@{1}"', P(("git", "show", "HEAD@{1}"))),
            ("git show HEAD@\\{1\\}", P(("git", "show", "HEAD@{1}"))),
            ("x '{a,b}'", P(("x", "{a,b}"))),
            ("x a\\}", P(("x", "a}"))),
            ("x a'}'", P(("x", "a}"))),
            ("x '{'", P(("x", "{"))),
            ('x "}"', P(("x", "}"))),
            ("x \\{a,b\\}", P(("x", "{a,b}"))),
            ("x '--no-verif{y.\\.y}'", P(("x", "--no-verif{y.\\.y}"))),
            ("cd '/w/{a}' && git x", P(("git", "x"), (), "/w/{a}")),
            ("TZ='x}' git", P(("git",), (("TZ", "x}"),))),
            ("TZ=\\{a,b\\} git", P(("git",), (("TZ", "{a,b}"),))),
        ])

    def test_tilde_not_plain(self):  # N4: G9 widened to every word
        self.many([
            ("cd ~ && x", NP("expansion")),
            ("~/x", NP("expansion")),
            ("x ~", NP("expansion")),
            ("TZ=~/x git", NP("expansion")),
            ("TZ=a:~/b git", NP("expansion")),
            ("git x=~/y", NP("expansion")),
            ("git --p=~/y", NP("expansion")),
            ("git a:~b", NP("expansion")),
            ("git --opt=~x", NP("expansion")),
            ("git log HEAD~1", P(("git", "log", "HEAD~1"))),
            ("x a~b", P(("x", "a~b"))),
            ("x '~'", P(("x", "~"))),
            ("x \\~", P(("x", "~"))),
            ("git x='~'/y", P(("git", "x=~/y"))),
            ("git x\\=~/y", P(("git", "x=~/y"))),
            ("git a':'~b", P(("git", "a:~b"))),
            ("TZ='~' git", P(("git",), (("TZ", "~"),))),
            ("TZ=a:'~' git", P(("git",), (("TZ", "a:~"),))),
            ("TZ=a~ git", P(("git",), (("TZ", "a~"),))),
        ])

    def test_append_assignment_not_plain(self):  # N4: G10
        self.many([("TZ+=1 git", NP("expansion")), ("A+=1 git", NP("expansion")), ("git A+=1", P(("git", "A+=1")))])


class ExpansionTest(ScanCase):
    def test_expansions(self):  # N4: X1, X4
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

    def test_double_quoted_dollar_not_plain(self):  # N4: X2, X3, X5, plan Step 1
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
    def test_redirections(self):  # N5: R1, R2
        for t in (">x", ">>x", "2>&1", "<x", "<<<x", "&>x", "&>>x", ">|x", "<>x", "<&0", "a >x", "a 2>&1", "a <<-x", "a >& x"):
            self.check(t, NP("redirection"))
        self.many([("x '>'", P(("x", ">"))), ('x "a<b"', P(("x", "a<b"))), ("echo '2>&1'", P(("echo", "2>&1")))])

    def test_heredoc_not_plain(self):  # N5: R1, plan Step 1
        self.assertEqual(scan("git commit -F - <<'EOF'\nmsg\nEOF").reason, "redirection")
        self.many([
            ("<<EOF\nb\nEOF", NP("redirection")),
            ("<<-'EOF'\nb\n\tEOF", NP("redirection")),
            ("git commit -F - <<'EOF'\nmsg\nEOF", NP("redirection")),
        ])


class QuoteTest(ScanCase):
    def test_unbalanced_quote_not_plain(self):  # N13: Q1, Q2, plan Step 1
        self.assertEqual(scan("git commit -m 'oops").reason, "unbalanced quote")
        self.check("git commit -m 'oops", NP("unbalanced quote"), ("git", "commit", "-m", "oops"))
        self.many([('git commit -m "oops', NP("unbalanced quote")), ('"a\'', NP("unbalanced quote")),
                   ("git commit \\", NP("unbalanced quote")), ("git commit -m 'a' 'b", NP("unbalanced quote")),
                   # the quote that would split a token (rule Q) is unbalanced: the specific reason wins
                   ("x a'b", NP("unbalanced quote")), ('x a"b', NP("unbalanced quote"))])
        self.assertEqual(scan('git "oops x').words, ("git", "oops x"))

    def test_quotes(self):  # Q3, Q5, Q6, Q7, Q8 (members not moved to N10), as argument words
        self.many([
            ("git commit -m ''", P(("git", "commit", "-m", ""))),
            ('git commit -m ""', P(("git", "commit", "-m", ""))),
            ('x ""', P(("x", ""))),
            ("git commit -m 'a\nb'", P(("git", "commit", "-m", "a\nb"))),
            ('git commit -m "a\nb"', P(("git", "commit", "-m", "a\nb"))),
            ('x "\\""', P(("x", '"'))),
            ('x "\\\\"', P(("x", "\\"))),
            ('x "\\$"', P(("x", "$"))),
            ('x "\\`"', P(("x", "`"))),
            ('x "\\a"', P(("x", "\\a"))),
            ("x \\a", P(("x", "a"))),
            ("x \\ ", P(("x", " "))),
            ("x \\;", P(("x", ";"))),
            ("x a\\;", P(("x", "a;"))),
            ("x \\'", P(("x", "'"))),
            ("x 'a\\'", P(("x", "a\\"))),
            # the same as the program word: a quoted or escaped program word (N8)
            ('""', NP("command word")),
            ("''", NP("command word")),
            ('"\\""', NP("command word")),
            ("\\a", NP("command word")),
        ])

    def test_quoting_splits_token(self):  # N10 (rule Q)
        self.many([
            ("git c'o'mmit", NP("quoting")),
            ("git commit --no-'verify'", NP("quoting")),
            ("git commit -'-no-verify'", NP("quoting")),
            ('git commit -m"fix"', NP("quoting")),
            ("x a'b'\"c\"", NP("quoting")),
            ("x a\\\nb", NP("quoting")),
            ('x "a\\\nb"', NP("quoting")),
            ("x ab\\c", NP("quoting")),
            ('git "co"mmit', NP("quoting")),
            ("TZ=a'b' git", NP("quoting")),
            ("cd '/w/a'b && git x", NP("quoting")),
            ("x a'b c'd", NP("quoting")),
            ("git commit --no-verif\\y", NP("quoting")),
            ("git commit \\-\\-no-verify", NP("quoting")),
            ("x 'a''b'", NP("quoting")),
            ("git commit -m 'a && b'", P(("git", "commit", "-m", "a && b"))),
            ('git commit -m "fix bug"', P(("git", "commit", "-m", "fix bug"))),
            ("git log --format='%H %s'", P(("git", "log", "--format=%H %s"))),
            ('git commit --author="B S"', P(("git", "commit", "--author=B S"))),
            ("git commit -m 'fix'", P(("git", "commit", "-m", "fix"))),
            ("x \\a", P(("x", "a"))),
            ("x \\ ", P(("x", " "))),
            ("x a\\;", P(("x", "a;"))),
            ("x 'a\\'", P(("x", "a\\"))),
            ("git commit -m ''", P(("git", "commit", "-m", ""))),
            ("x x'.'y", P(("x", "x.y"))),
            ("TZ='x y' git", P(("git",), (("TZ", "x y"),))),
        ])


class WordTest(ScanCase):
    def test_reserved_words(self):  # N7: W1, W3
        self.many([
            ("!", NP("reserved word")),
            ("[[", NP("reserved word")),
            ("]]", NP("reserved word")),
            ("x !", NP("reserved word")),
            ("x [[", NP("reserved word")),
            ("x ]]", NP("reserved word")),
            ("! x", NP("reserved word")),
            ("git show HEAD@{1}", NP("character")),  # r4 (N15): unquoted braces are refused; quoted they are plain
            ("git show 'HEAD@{1}'", P(("git", "show", "HEAD@{1}"))),
            ("x '!'", P(("x", "!"))),
            ('x "[["', P(("x", "[["))),
            ("x '}'", P(("x", "}"))),
            ("'!'", NP("command word")),
            ('"[["', NP("command word")),
        ])

    def test_reserved_words_in_command_position(self):  # N7: W8, W9
        self.assertEqual(len(K), 33)
        for w in K:
            self.many([
                (w + " git commit", NP("reserved word")),
                (w, NP("reserved word")),
                ("TZ=1 " + w + " git", NP("reserved word")),
                ("cd /w && " + w + " git commit", NP("reserved word")),
                ("git commit -m " + w, P(("git", "commit", "-m", w))),
                ("git log -- " + w, P(("git", "log", "--", w))),
                ("TZ=" + w + " git", P(("git",), (("TZ", w),))),
                ("git " + w, P(("git", w))),
            ])
        self.many([
            ("time git commit", NP("reserved word")),
            ("TZ=1 LANG=C time git", NP("reserved word")),
            ("TZ=1 git", P(("git",), (("TZ", "1"),))),
            ("TZ=1", P((), (("TZ", "1"),))),
            ("timex git", P(("timex", "git"))),
            ("Time git", P(("Time", "git"))),
            ("time\tgit", NP("reserved word")),
            ("x time git", P(("x", "time", "git"))),
            ("TZ+=1 time git", NP("expansion")),
            ("a; time git", NP("operator ;")),
            ("time git commit; x", NP("reserved word")),
            ("TZ=1 time git > o", NP("reserved word")),
        ])

    def test_command_word(self):  # N8
        quoted = ("'git' commit", '"git" commit', "\\git commit", "g'i't commit", "'time' git", "\\time git",
                  "'exec' git", "\\command git", "'' x", '"" x', "./x\\\n.sh y", "gi\\\nt commit")
        chars = ("%1 x", "%+", "%%", "git@x y", "a:b", "x+y", "é x", "a!b x", "x] y", "git\rx y", "-x y", "--help",
                 "HEAD~1", "x{1..3}", "{a x", "}a x", "{a,b} x", "a} x", "x%1 git")
        for t in quoted + chars:
            self.check(t, NP("command word"))
            self.check("TZ=1 " + t, NP("command word"))
            self.check("cd /w && " + t, NP("command word"))
        for w in K:  # a quoted or escaped K word is a quoted program word, not a reserved word
            self.many([("'" + w + "' git", NP("command word")), ('"' + w + '" git', NP("command word")),
                       ("\\" + w + " git", NP("command word"))])
        self.many([
            # precedence: a specific construct at the program word's first character wins
            ("=git", NP("expansion")),
            ("#x", NP("comment")),
            ("{", NP("grouping")),
            ("*x", NP("expansion")),
            ("time", NP("reserved word")),
            ("-", NP("reserved word")),
            ("1=x git", NP("expansion")),
            # still plain
            ("git commit", P(("git", "commit"))),
            ("/usr/bin/git x", P(("/usr/bin/git", "x"))),
            ("./run.sh", P(("./run.sh",))),
            ("python3 x", P(("python3", "x"))),
            ("git-lfs x", P(("git-lfs", "x"))),
            ("a_b.c x", P(("a_b.c", "x"))),
            ("1 git", P(("1", "git"))),
            ("TZ=1 /usr/bin/git x", P(("/usr/bin/git", "x"), (("TZ", "1"),))),
            ("cd /w && ./run.sh -x", P(("./run.sh", "-x"), (), "/w")),
        ])

    def test_equals_expansion_not_plain(self):  # N4: G11, G12
        self.many([
            ("=git commit", NP("expansion")),
            ("git commit -m =x", NP("expansion")),
            ("git -m =x", NP("expansion")),
            ("cd =w && git commit", NP("expansion")),
            ("=", NP("expansion")),
            ("git commit -m '=x'", P(("git", "commit", "-m", "=x"))),
            ("git commit -m \\=x", P(("git", "commit", "-m", "=x"))),
            ("git commit -m a=b", P(("git", "commit", "-m", "a=b"))),
            ("TZ==1 git", NP("expansion")),
            ("TZ==x git", NP("expansion")),
            ("git commit --m=x", P(("git", "commit", "--m=x"))),
            ("git --format=x", P(("git", "--format=x"))),
            ("=x '='", NP("expansion")),
            ("TZ==python3 git", NP("expansion")),
            ("TZ=a:=python3 git", NP("expansion")),
            ("TZ=a:=x git", NP("expansion")),
            ("TZ=a\\:=x git", NP("expansion")),
            ("TZ=a':'=x git", NP("expansion")),
            ("TZ='=x' git", P(("git",), (("TZ", "=x"),))),
            ("TZ=\\=x git", P(("git",), (("TZ", "=x"),))),
            ("TZ=a=b git", P(("git",), (("TZ", "a=b"),))),
            ("TZ=a:'=x' git", P(("git",), (("TZ", "a:=x"),))),
            ("TZ=a:\\=x git", P(("git",), (("TZ", "a:=x"),))),
            ("TZ=a\\:~/b git", NP("expansion")),
            ("TZ=a':'~/b git", NP("expansion")),
            ('TZ=a":"~/b git', NP("expansion")),
            ("TZ=a:'~'/b git", P(("git",), (("TZ", "a:~/b"),))),
            ("git B==x", NP("expansion")),
            ("git B=a:=x", NP("expansion")),
            ("1=x git", NP("expansion")),
            ("10+=v git", NP("expansion")),
            ("x '=x'", P(("x", "=x"))),
            ("x \\=x", P(("x", "=x"))),
        ])

    def test_zsh_sweep(self):  # Z1 under the closed grammar (verdicts per N4/N7/N8/N11)
        self.many([
            # zshexpn HISTORY EXPANSION: `!` unquoted mid-word is outside U
            ("echo !!", NP("character")),
            ("echo !$", NP("character")),
            ("echo a!b", NP("character")),
            ("echo \\!x", P(("echo", "!x"))),
            ('echo "\\!"', P(("echo", "\\!"))),
            # zshexpn PROCESS SUBSTITUTION: <(..) >(..) =(..)
            ("cat <(a)", NP("substitution")),
            ("tee >(a)", NP("substitution")),
            ("cat =(a)", NP("expansion")),
            # zshexpn PARAMETER EXPANSION, COMMAND SUBSTITUTION, ARITHMETIC EXPANSION
            ("echo $x", NP("expansion")),
            ("echo ${x}", NP("expansion")),
            ("echo $[1+1]", NP("expansion")),
            ("echo $((1))", NP("substitution")),
            ("echo $(a)", NP("substitution")),
            ("echo `a`", NP("substitution")),
            # zshexpn BRACE EXPANSION (r4, N15: every unquoted brace is refused, so none of these reaches zsh)
            ("echo x{a,b}y", NP("character")),
            ("echo {1..3}", NP("character")),
            ("echo {a..c}", NP("character")),
            ("echo {1..10..2}", NP("character")),
            ("echo {a}", NP("character")),
            ("echo {}", NP("character")),
            ("echo a{b}", NP("character")),
            ("echo 'a{b}'", P(("echo", "a{b}"))),
            # zshexpn FILENAME EXPANSION: ~, ~+, ~-, ~name, ~[dyn], =cmd, assignments
            ("echo ~", NP("expansion")),
            ("echo ~+", NP("expansion")),
            ("echo ~-", NP("expansion")),
            ("echo ~root", NP("expansion")),
            ("echo ~[x]", NP("expansion")),
            ("echo =ls", NP("expansion")),
            ("echo a~b", P(("echo", "a~b"))),
            # zshexpn FILENAME GENERATION: * ? [..] qualifiers, <n-m>, (a|b)
            ("echo *", NP("expansion")),
            ("echo a?", NP("expansion")),
            ("echo [a]", NP("expansion")),
            ("echo *(.)", NP("expansion")),
            ("echo <1-3>", NP("redirection")),
            ("echo (a|b)", NP("grouping")),
            # zshmisc SIMPLE COMMANDS & PIPELINES: | |& && || ; & &| &! newline
            ("a &|", NP("operator &")),
            ("a &!", NP("operator &")),
            ("a |& b", NP("operator |")),
            ("a ;& b", NP("operator ;")),
            ("a ;| b", NP("operator ;")),
            # zshmisc REDIRECTION, MULTIOS, REDIRECTIONS WITH NO COMMAND
            ("a {fd}>f", NP("character")),
            ("a >! f", NP("redirection")),
            ("a >>& f", NP("redirection")),
            ("a >&| f", NP("redirection")),
            ("< f", NP("redirection")),
            # zshmisc COMPLEX COMMANDS, ALTERNATE FORMS, RESERVED WORDS
            ("if a; then b; fi", NP("reserved word")),
            ("for i in a; do b; done", NP("reserved word")),
            ("repeat 3 a", NP("reserved word")),
            ("foreach i (a); b; end", NP("reserved word")),
            ("coproc a", NP("reserved word")),
            ("[[ a ]]", NP("reserved word")),
            ("(( 1 ))", NP("grouping")),
            ("f() { a; }", NP("grouping")),
            ("TZ=(1 2) a", NP("grouping")),
            ("A=(1 2) a", NP("assignment")),
            ("A[1]=x a", NP("command word")),
            # zshmisc JOBS: a command word starting with % is outside the command-word set (N8)
            ("%1", NP("command word")),
            ("%+ x", NP("command word")),
            ("TZ=1 %%", NP("command word")),
            ("cd /w && %1", NP("command word")),
            ("git log %1", P(("git", "log", "%1"))),
            ("'%1' x", NP("command word")),
            ("\\%1 x", NP("command word")),
            ("TZ=%1 git", P(("git",), (("TZ", "%1"),))),
            # zshparam: digits are a parameter name, so `1=x` is an assignment in zsh
            ("1=x git", NP("expansion")),
            ("0=v git", NP("expansion")),
            ("10+=v git", NP("expansion")),
            ("TZ=1 2=x git", NP("expansion")),
            ("cd /w && 1=x git", NP("expansion")),
            ("1A=x git", NP("command word")),
            ("git 1=x", P(("git", "1=x"))),
            ("'1'=x git", NP("command word")),
            ("1\\=x git", NP("command word")),
            ("1 git", P(("1", "git"))),
            ("+=x git", NP("command word")),
            ("1'+'=x git", NP("command word")),
            ("x%1 git", NP("command word")),
            ("TZ=1 x%1 git", NP("command word")),
            ("12 x", P(("12", "x"))),
            # zshparam ARGV0 (F5) and the other special parameters: not on the allow-list (N9)
            ("ARGV0=git-push git origin HEAD:main", NP("assignment")),
        ])

    def test_comments(self):  # N6: W4, W5
        self.many([
            ("git commit # x", NP("comment")),
            ("#x", NP("comment")),
            ("#a$X", NP("comment")),
            ("cd /w && git commit # c", NP("comment")),
            ("a;#b", NP("operator ;")),
            ("x a#b", P(("x", "a#b"))),
            ("x '#x'", P(("x", "#x"))),
            ("x \\#x", P(("x", "#x"))),
            ('x "#x"', P(("x", "#x"))),
            ("a#b", NP("command word")),
        ])

    def test_empty_text_plain(self):  # W6
        for t in ("", "   ", "\n", "\n\n", " \t ", "\\\n"):
            self.check(t, P(), ())

    def test_words_field(self):  # W7 (invariant: words)
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
        self.check("TZ=1 git x\n", P(("git", "x"), (("TZ", "1"),)), ("TZ=1", "git", "x"))
        self.check("cd /w && git commit", P(("git", "commit"), (), "/w"), ("cd", "/w", "&&", "git", "commit"))
        self.check("echo `x`", NP("substitution"), ("echo", "`x`"))
        self.check("git c'o'mmit", NP("quoting"), ("git", "commit"))
        self.check("A=1 git", NP("assignment"), ("A=1", "git"))
        self.check("cd +1 && git commit", NP("operator &&"), ("cd", "+1", "&&", "git", "commit"))
        self.check("x a{b} 'c}'", NP("character"), ("x", "a{b}", "c}"))  # r4: a brace leaves the words as written
        self.check("x \\{ '}'", P(("x", "{", "}")), ("x", "{", "}"))


class AssignmentTest(ScanCase):
    def test_assignments_split(self):  # A1-A6 with ALLOW names, plan Step 1 (invariant: the assignment split)
        self.assertEqual(scan("GIT_INDEX_FILE=x git commit").assignments, (("GIT_INDEX_FILE", "x"),))
        self.many([
            ("GIT_INDEX_FILE=x git commit", P(("git", "commit"), (("GIT_INDEX_FILE", "x"),))),
            ("TZ=1 git", P(("git",), (("TZ", "1"),))),
            ("TZ= git", P(("git",), (("TZ", ""),))),
            ("1A=x git", NP("command word")),
            ("'A'=1 git", NP("command word")),
            ("A\\=1 git", NP("command word")),
            ("A-B=1 git", NP("command word")),
            ("A'B'=1 git", NP("command word")),
            ("LANG=C", P((), (("LANG", "C"),))),
            ("TZ=1 LANG=C", P((), (("TZ", "1"), ("LANG", "C")))),
            ("GIT_DIR=1 GIT_WORK_TREE= git x", P(("git", "x"), (("GIT_DIR", "1"), ("GIT_WORK_TREE", "")))),
            ("git B=2", P(("git", "B=2"))),
            ("TZ='x y' git", P(("git",), (("TZ", "x y"),))),
            ('TZ="x" git', P(("git",), (("TZ", "x"),))),
            ("TZ=b=c git", P(("git",), (("TZ", "b=c"),))),
            ("TZ=1 git B=2", P(("git", "B=2"), (("TZ", "1"),))),
        ])

    def test_assignment_allow_list(self):  # N9 (F5)
        for t in ("ARGV0=git-push git origin HEAD:main", "PATH=/tmp/x git commit", "A=1 git", "A= git", "A=1",
                  "HOME=/x git", "IFS=x git", "GIT_CONFIG_PARAMETERS=x git", "BASH_ENV=x git", "ENV=x git",
                  "ZDOTDIR=x git", "path=x git", "argv=x git", "LD_PRELOAD=x git", "DYLD_INSERT_LIBRARIES=x git",
                  "_=x git", "git_dir=x git", "tz=1 git", "A=1 TZ=1 git", "TZ=1 A=1 git", "cd /w && A=1 git commit",
                  "ARGV0=x", "A='x y' git", "A=1 'git' x"):
            self.check(t, NP("assignment"))
        for name in ALLOW:
            self.check(name + "=x git commit", P(("git", "commit"), ((name, "x"),)))
            self.check(name + "=", P((), ((name, ""),)))
        self.many([
            ("TZ= git", P(("git",), (("TZ", ""),))),
            ("LANG=C", P((), (("LANG", "C"),))),
            ("TZ='x y' git", P(("git",), (("TZ", "x y"),))),
            ('TZ="x" git', P(("git",), (("TZ", "x"),))),
            ("cd /w/x && TZ=1 git commit", P(("git", "commit"), (("TZ", "1"),), "/w/x")),
            ("git B=2", P(("git", "B=2"))),
            ("git ARGV0=x", P(("git", "ARGV0=x"))),
        ])


class CdTest(ScanCase):
    def test_cd_form_is_the_only_plain_compound(self):  # N12: CD1-CD6, plan Step 1 (invariant: the cd form)
        s = scan("cd /w/x && git commit -m m")
        self.assertTrue(s.plain)
        self.assertEqual((s.cd, s.argv), ("/w/x", ("git", "commit", "-m", "m")))
        for t in ("cd /w/x; git commit", "cd /w/x && cd y && git commit", "cd /w/x && git commit && git push", "cd - && git commit"):
            self.assertFalse(scan(t).plain)
        self.many([
            ("cd /w/x && git commit -m m", P(("git", "commit", "-m", "m"), (), "/w/x")),
            ("cd '/w/a b' && git push", P(("git", "push"), (), "/w/a b")),
            ("cd /w/x&&git commit", P(("git", "commit"), (), "/w/x")),
            ("cd /w/x && TZ=1 git commit", P(("git", "commit"), (("TZ", "1"),), "/w/x")),
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
            ("TZ=1 cd /w && x", NP("operator &&")),
            ('"cd" /w && x', NP("command word")),
            ("A=1 cd /w && x", NP("assignment")),
            ("cd /w/x && cd y && git commit", NP("operator &&")),
            ("cd /w/x && git commit && git push", NP("operator &&")),
            ("cd /w/x &&", NP("operator &&")),
            ("cd /w/x && git commit # c", NP("comment")),
            ("cd $W && git commit", NP("expansion")),
            ("cd /w/x && git commit; git push", NP("operator ;")),
            ("cd /w/x && git commit > o", NP("redirection")),
            ("cd /w/x && A+=1 git", NP("expansion")),
            ("xcd /w && git commit", NP("operator &&")),  # CD6
            ("abcd /w && x", NP("operator &&")),
            ("cdx /w && x", NP("operator &&")),
            ("CD /w && x", NP("operator &&")),
            ("Cd /w && x", NP("operator &&")),
            ("cd time && git commit", NP("operator &&")),
            ("cd /w && time git commit", NP("reserved word")),
        ])

    def test_cd_target_absolute(self):  # N12 (F7)
        for t in ("cd +1 && git commit", "cd -2 && x", "cd y && git commit", "cd ./x && x", "cd ../x && x",
                  "cd /w/../x && x", "cd /w/./x && x", "cd /w/.. && x", "cd . && x", "cd .. && x", "cd /w/. && x",
                  "cd /.. && x", "cd '/w/..' && x", "cd x/y && x", "cd '' && x", "cd %1 && x"):
            self.check(t, NP("operator &&"))
        self.many([
            # r4 amendment of N12: a CD3/CD6 member with an earlier construct reports it (smallest position)
            ('"cd" /w && x', NP("command word")),
            ("A=1 cd /w && x", NP("assignment")),
            ("TZ=1 cd /w && x", NP("operator &&")),
            # r4 (N15): an unquoted brace in the cd target
            ("cd /w/{a,b} && x", NP("character")),
            ("cd /w/a} && x", NP("character")),
            ("cd {/w,/x} && x", NP("character")),
            ("cd '/w/{a}' && git x", P(("git", "x"), (), "/w/{a}")),
            ("cd /w/x && git commit -m m", P(("git", "commit", "-m", "m"), (), "/w/x")),
            ("cd '/w/a b' && git push", P(("git", "push"), (), "/w/a b")),
            ("cd /w/x&&git commit", P(("git", "commit"), (), "/w/x")),
            ("cd / && x", P(("x",), (), "/")),
            ("cd /w/.x && x", P(("x",), (), "/w/.x")),
            ("cd /w/x.. && x", P(("x",), (), "/w/x..")),
            ("cd //w && x", P(("x",), (), "//w")),
            ("cd /w/x/ && x", P(("x",), (), "/w/x/")),
            ("cd /w/... && x", P(("x",), (), "/w/...")),
        ])


class CharacterTest(ScanCase):
    OUTSIDE = ("\r", "\x01", "\x0b", "\x0c", "\x1b", "\x7f", "é", "\u00a0", "\u2028", "\u3000", "\u0085",
               "\U0001f6dd", "\u180e", "\u0661", "!", "]")

    def test_characters(self):  # N11, N14, CH1
        self.check("git\tcommit", P(("git", "commit")))
        self.check("git commit\r\n", NP("character"))
        for ch in self.OUTSIDE:
            self.check("x a%sb" % ch, NP("character"))
            self.check("TZ=a%sb git" % ch, NP("character"))
            self.check("x 'a%sb'" % ch, P(("x", "a%sb" % ch)))
            self.check('x "a%sb"' % ch, P(("x", "a%sb" % ch)))
            self.check("x \\%s" % ch, P(("x", ch)))
            if ch != "!":
                self.check("x " + ch, NP("character"))
        self.many([
            ("x x]", NP("character")),
            ("x x]]", NP("character")),
            ("x {a", NP("character")),
            ("x }a", NP("character")),
            ("x a!b", NP("character")),
            ("git commit -m 'é'", P(("git", "commit", "-m", "é"))),
            ('git commit -m "a\x01b"', P(("git", "commit", "-m", "a\x01b"))),
            ("x 'a!b'", P(("x", "a!b"))),
            ('x "x]"', P(("x", "x]"))),
            ("x \\é", P(("x", "é"))),
            # CRLF between commands: the CR is the first construct (by position), in an argument or the program word
            ("x a\r\nb", NP("character")),
            ("a\r\nb", NP("command word")),
            ("git commit\r\ngit push", NP("character")),  # r4 amendment of N11 (r3 said `operator newline`)
        ])
        for t in ("x git\x00commit", "x 'a\x00'", 'x "a\x00"', "x \\\x00", "git commit\x00", "x y\x00"):
            self.check(t, NP("nul character"))
        self.check("git\x00commit", NP("command word"))

    def test_non_str_text_is_type_error(self):  # CH5, V3
        for bad in (None, b"git", Sub("git"), 5, ["git"]):
            with self.subTest(bad=bad):
                with self.assertRaises(TypeError):
                    scan(bad)

    def test_long_text_linear(self):  # CH6 (F6; r4 R4-3; r5 F5-2, F5-3): growth ratio per shape; no wall-clock bound
        # One shape per per-character or per-word path of the scanner (CH6_SHAPES), each result compared with the
        # Scan written by hand at both sizes; ratio best-of-rounds large / best-of-rounds small below CH6_BOUND, first at
        # the base size n // 8 (a quadratic with a large constant fails there, at little cost), then at n (a quadratic
        # with a small constant, such as a copy of the rest of the text per word, shows only at large sizes).
        self.assertGreaterEqual(len(CH6_SHAPES), 20)
        for shape in CH6_SHAPES:
            for base in (shape[1] // 8, shape[1]):
                ratio = float("inf")
                with self.subTest(shape=shape[0], base=base):
                    ratio, small, large = ch6_growth(shape, self.assertEqual, base)
                    self.assertGreater(min(small), 0)
                    self.assertLess(ratio, CH6_BOUND, "small %r large %r" % (small, large))
                if ratio >= CH6_BOUND:
                    break

    def test_huge_numbers_are_text(self):  # V1
        d4300, d4301 = "7" * 4300, "7" * 4301
        self.check("git commit -m " + d4300, P(("git", "commit", "-m", d4300)))
        self.check("git commit -m " + d4301, P(("git", "commit", "-m", d4301)))
        self.check("TZ=%s git" % d4301, P(("git",), (("TZ", d4301),)))
        self.check(d4301 + ">x", NP("redirection"))

    def test_unicode_version_independent(self):  # V2, N11
        for ch in ("\U0001f6dd", "\u180e", "\u0661"):
            self.check("x a%sb" % ch, NP("character"))
            self.check("x 'a%sb'" % ch, P(("x", "a%sb" % ch)))
            self.check('x "%s"' % ch, P(("x", ch)))
        self.check("A\u0661=1 git", NP("command word"))
        self.check("\u0661=1 git", NP("command word"))
        self.check("TZ=\u0661 git", NP("character"))
        self.check("TZ='\u0661' git", P(("git",), (("TZ", "\u0661"),)))
        with open(shellscan.__file__, encoding="utf-8") as f:
            source = f.read()
        for name in (".isspace(", ".isalnum(", ".isalpha(", ".isdigit(", ".isdecimal(", ".isnumeric(", ".lower(",
                     ".upper(", ".casefold(", "unicodedata", "re.I", "IGNORECASE", "\\s", "\\w", "\\d"):
            with self.subTest(name=name):
                self.assertNotIn(name, source)


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
