"""Task L1.1 (process learnings A1, A2, A4, D3; owner 2026-11-24) and, later, the prompt and document rows of Task L2.1.

Every expected text below is typed by hand from the task, none read back from the files under test. The L2 rows are
added by extending L1_SENTENCES, L1_TOKENS and L1_DOC_PINS with L2_* tuples."""
import ast
import hashlib
import inspect
import random
import re
import sys
import unittest

from tests import prose_check as pc
from tests.prose_check import LABELS, block_problems, forbidden_hits, labels, paragraph, whole_token
from tests.test_playbook import (MS_DOC, PLAN_DOC, _DEFERRAL, _VERIFIER, deferral_problems, fix1_problems, read,
                                 verifier_step_problems)
from tests.test_prompt_blocks import (CONTINUATION, HANDOFF_ANCHOR, OWNER_RECOMMENDED, disk, in_para, key_problems,
                                      other_para, pin_problems, resume_problems)

L1_CONTROLLERS = ("controller", "stream_controller")          # Q-L-1 (b)
DENIAL_ROLES = L1_CONTROLLERS + ("program_controller",)       # program_controller from merged:records (Q-L-3 (a))

DELTA_CTRL = (
    "After an update from the base branch that follows the final review, dispatch a delta final review, not a fresh "
    "review of the whole branch: it covers the merge commit's diff, the base branch's changes to each module a "
    "`Consumes:` line of the branch's tasks names and the branch's uses of them, and one full suite on the new head; "
    "dispatch a fresh review of the whole branch only when the branch's own code changed beyond fix diffs that were "
    "reviewed.")
DELTA_FR = (
    "When the brief names a delta review after an update from the base branch, review the update instead of the "
    "whole branch: the merge commit's diff, the base branch's changes to each module a `Consumes:` line of the "
    "branch's tasks names and each place the branch uses them, and one full suite you run on the new head.",
    "First check that the only commits after the reviewed head are that merge and fix commits whose diffs were "
    "reviewed; otherwise report BLOCKED naming the commit, since only a review of the whole branch can judge it.")
A2_FIND = (
    "For each finding, search the code for every member of its class, each place its input dimension reaches, record "
    "the search command in the report, and list every member the search finds in its class statement.")
A2_REREVIEW = (
    "On a re-review, run each finding's search again before you judge the fix, and report each member missing from "
    "its class statement as a finding.")
A2_IMPL = (
    "Test every member a finding's class statement lists, each through the production call path; a member the fix "
    "rule does not let you fix is narrowed, its input refused, or reported under Decision needed, never left "
    "untested.")
FOLD = (
    "When STOP_NARROW or ESCALATE leaves open LOW or MEDIUM findings to register, ask the owner which task takes "
    "them, recommending a planned task of the same stream whose files include a path the findings name, and a new "
    "task only when no such task exists or the fix is too large for that task.")
DENIAL = (
    "A permission denial, yours or a child's, goes to the owner with the denial quoted verbatim, and the denied "
    "action waits for the answer; the same effect reached by another tool or command is the same action, so you "
    "never run it another way and never ask another agent to run it.")
OLD_SIBLING = "Test every sibling in the row's list or list it as an unrelated finding."
ESCALATE_CTRL = ("ESCALATE stops the loop: open LOW and MEDIUM findings are registered against a named follow-up task, "
                 "and an open CRITICAL or HIGH finding is an owner question that blocks only that task.")
SC_LOOPSTATS = "compute it after each review and ledger it as the `Loopstats:` line."

# (id, role, label, text, (where, anchor)): "before" -> " " + text + " " + anchor in the paragraph; "after" -> anchor + " " +
# text; "last" -> the paragraph ends with " " + text; "in" -> " " + text in the paragraph; every row also needs the text
# once in the whole file
L1_SENTENCES = (
    tuple(("A1", r, "Merge and checkpoint.", DELTA_CTRL, ("before", HANDOFF_ANCHOR)) for r in L1_CONTROLLERS)
    + (("A1", "final_reviewer", "Branch scope.", " ".join(DELTA_FR), ("last", None)),)
    + tuple(("A2", r, "Method.", A2_FIND + " " + A2_REREVIEW, ("last", None)) for r in ("task_reviewer", "final_reviewer"))
    + (("A2", "implementer", "Build.", A2_IMPL, ("in", None)),
       ("A4", "controller", "Continuation.", FOLD, ("after", ESCALATE_CTRL)),
       ("A4", "stream_controller", "Continuation.", FOLD, ("after", SC_LOOPSTATS)))
    + tuple(("D3", r, "Owner-only decisions.", DENIAL, ("before", OWNER_RECOMMENDED)) for r in DENIAL_ROLES))
L1_TOKENS = (
    tuple((r, "Merge and checkpoint.", t) for r in L1_CONTROLLERS
          for t in ("delta final review", "`Consumes:`", "one full suite on the new head", "fix diffs that were reviewed"))
    + (("final_reviewer", "Branch scope.", "delta review"), ("final_reviewer", "Branch scope.", "BLOCKED"),
       ("task_reviewer", "Method.", "every member"), ("task_reviewer", "Method.", "re-review"),
       ("final_reviewer", "Method.", "every member"), ("final_reviewer", "Method.", "re-review"),
       ("implementer", "Build.", "Test every member"), ("implementer", "Build.", "never left untested"))
    + tuple((r, "Continuation.", t) for r in L1_CONTROLLERS for t in ("planned task of the same stream", "ask the owner"))
    + tuple((r, "Owner-only decisions.", t) for r in DENIAL_ROLES
            for t in ("quoted verbatim", "same action", "another tool or command")))
# role -> (("first three lines", sha256), (label, sha256), ...): the paragraphs L1 does not edit, at the commit L1
# started from (14b518a), computed by hashlib and again by `shasum -a 256`
L1_UNCHANGED = {
    'controller': (
        ("first three lines", 'a29e0e608534901718ea48550daf3c8829a8f260de347920d66f6fc699cea025'),
        ('Verification method.', 'cdfe5f35952a3d355e601ffc1bce43eec51285cf5071e48bd1e4205c140a89a2'),
        ('Dispatch discipline.', '88a3c0723e5ae3baf5c8b51649a8fb5c745c76e122c655e0cef984997904d4bb'),
        ('Input domain.', 'aa90126efdc6e10776dbd5ebd063a8bf1fa6097ef83ffc01bd2dd1ce9398c612'),
        ('Oracle.', 'bdedce1e10d54048e7d57802d77d8c2dae874a4b0de12572d2460142d6191beb'),
        ('Rulings.', 'd4110109d4580fe23368eede84b1b9bd840fbfef3bee23e0111fcd2ee6ae77b3'),
        ('Finding class.', '66d28797419b25a59f80ab35dc4d2870a1bd5bd2f49d28f92f79a200c8c1604e'),
        ('Zero bugs.', '5a6303a00548443cb0a9baaf5c8b8c0d81baacf1ae283c8161d1451c60a06b55'),
        ('Budget.', 'e7ba7cf9490b69535c51f75708ae6be6aa6fbad3cc4929c14666e1d59cb566c6'),
        ('Background work.', '824eb10242c361649d3d1666517fa658637c35ad64851bf59969c5827fdf7293'),
        ('Report contract.', 'dc7bc77da8add1d4f587f8a58afa9d3704b80204b827c050d096e2827e16f7cd'),
    ),
    'stream_controller': (
        ("first three lines", 'e5b0eafb71c6aa40f4853b576031f5dd6166301ca360324b8015a74eff57dbaf'),
        ('Verification method.', 'cdfe5f35952a3d355e601ffc1bce43eec51285cf5071e48bd1e4205c140a89a2'),
        ('Dispatch discipline.', 'a53d2641dc064c9db480ae08676ffac042dc76e3cfdd9c440823c87d300d1930'),
        ('Input domain.', 'aa90126efdc6e10776dbd5ebd063a8bf1fa6097ef83ffc01bd2dd1ce9398c612'),
        ('Oracle.', 'bdedce1e10d54048e7d57802d77d8c2dae874a4b0de12572d2460142d6191beb'),
        ('Rulings.', 'd4110109d4580fe23368eede84b1b9bd840fbfef3bee23e0111fcd2ee6ae77b3'),
        ('Finding class.', '66d28797419b25a59f80ab35dc4d2870a1bd5bd2f49d28f92f79a200c8c1604e'),
        ('Zero bugs.', 'fb9bb7b99d5393f05356aa645fa9df253dcb49cc116a20d836b7bb00e135b80f'),
        ('Budget.', 'e7ba7cf9490b69535c51f75708ae6be6aa6fbad3cc4929c14666e1d59cb566c6'),
        ('Background work.', '7b806027a546591d490568e32e4f1c96437ec9c2a45855dfadde189b69d17c74'),
        ('Report contract.', '191b2e2da3b9a49c28feeffc2d5a5e7808e3d6600ea3e3030853ab67d1179730'),
    ),
    'final_reviewer': (
        ("first three lines", '2a08ebe0ae67faa7bf2ff2d25e03ad56564d5347e0b804cd7cbaf3ce5da9b838'),
        ('Verification method.', '70bd98733f6b4d4ec5c166366d6d37eb29ffa40926b15cb8f34b84003bf54e08'),
        ('Input domain.', '2daecd82ae94ee9aac3991f95551ace79c9552c0c4a1a457d68f468f952be18e'),
        ('No out-of-scope bucket.', 'fee22b455e51ea42fbdc6fd165e3c26eb5d9f48198c134f1ad823bd6901da856'),
        ('Verdict.', '7da5bd577c947041c8acdd5fb4aa6611d017f320d382bbac3fe5cba6517be955'),
        ('Zero bugs.', '7e8d9faa253a000db66861e6759abb536c6e4170c227f2ea9b8c771d7acde9b1'),
        ('No subagents.', 'ff5dbd4120af31ad1dac544195acfa7ee15e6159aa1f59e89adea252a83d6771'),
        ('Owner-only decisions.', 'da8450b08a114a475935f18c88e79ab55182e177bde7eace26a1394d42137dd6'),
        ('Budget.', 'add9c756a7a13ef11ccb1273ca8efd88ed2cbdfecb17de2ce581fe06a5e2a28e'),
        ('Background work.', 'e2a0224ff6f220b574a08d491c427637d3b7d6ada3508128409f79f47de93192'),
        ('Report contract.', 'c93fd7394fc51b2bf903fa020c7d04f18fc343a9c56e64a40b041860fd91a389'),
    ),
    'task_reviewer': (
        ("first three lines", 'f59b2193026acec54131dcaf8e7aff0efec10ee725cee81893851a32d18f740b'),
        ('Verification method.', 'ef1001183eff7749cfc35b7a86445de86533370312c63fbcac7e2b94a8c89d56'),
        ('Input domain.', '829899c13323d366c27ad415b07d5e13ae79c8d7973a2e2facda23f35aaf0f51'),
        ('No out-of-scope bucket.', 'a4efb38f42f022c872e6ab277d483780e00b3eaeb242d436b6d7a162a07846c5'),
        ('Verdict.', '05a18764b9debb188a1c981b7436091af2210e38ecc13141544526f232cff47b'),
        ('Zero bugs.', '2b80453bddcafd8eb071c3550719df0783e6e7263810f5ed150ac7a1a3d2f8f7'),
        ('No subagents.', 'ff5dbd4120af31ad1dac544195acfa7ee15e6159aa1f59e89adea252a83d6771'),
        ('Owner-only decisions.', 'da8450b08a114a475935f18c88e79ab55182e177bde7eace26a1394d42137dd6'),
        ('Budget.', 'add9c756a7a13ef11ccb1273ca8efd88ed2cbdfecb17de2ce581fe06a5e2a28e'),
        ('Background work.', 'e2a0224ff6f220b574a08d491c427637d3b7d6ada3508128409f79f47de93192'),
        ('Report contract.', 'c93fd7394fc51b2bf903fa020c7d04f18fc343a9c56e64a40b041860fd91a389'),
    ),
    'implementer': (
        ("first three lines", 'fb526621bb6962f986e905ff39efb8d0356350e97ad1e3ad1f9581df07a5d2ff'),
        ('Verification method.', '9304d7081e8c2429d7348a7946ae881ddbbd44524a6171c1b806d216c98f8ebd'),
        ('Input domain.', 'dca822fb0f0e94700e81599f74579c363f1804a89d6b801f87075b9b292c04f5'),
        ('Unstated behaviour.', 'fe25d80c882093db052ecce3e98de931ed19ef2d1197672c40036539f070792a'),
        ('Commit gate.', '0789c7f1d659c1ad604ab849454842d77fdab49e0aedfc639189fd57a6838281'),
        ('Zero bugs.', '9398f528181c3d97801f5466e1e3d98c203fa78df0b752f2ad5aa477368697f3'),
        ('No subagents.', 'ff5dbd4120af31ad1dac544195acfa7ee15e6159aa1f59e89adea252a83d6771'),
        ('Owner-only decisions.', '23cf7caeb1da22e6c96c3158e7bbeaf7429e0c3fbfa0bfc6070e1143957b520c'),
        ('Budget.', 'c4fd61d7bde9453b49a1576ce558f18c947114a74f3d6e8f4b4b43a7a6ee8687'),
        ('Background work.', 'e2a0224ff6f220b574a08d491c427637d3b7d6ada3508128409f79f47de93192'),
        ('Report contract.', 'ef86f7b70c5928beb829b93da59b9d59015192ecb9fa97228df839ab1cc7a9f9'),
    ),
    'program_controller': (       # its "Owner-only decisions." paragraph is edited from merged:records (F2)
        ("first three lines", 'd170dd1a78322108e0a9a2197f08f1dc2931e8b1cdcfcb59f44aaebdcd7ec284'),
        ('Verification method.', 'cdfe5f35952a3d355e601ffc1bce43eec51285cf5071e48bd1e4205c140a89a2'),
        ('Dispatch discipline.', '249234fbe03de3acd8c4034c48ae49af6b02033603e4d4e370c5e526250d14c9'),
        ('Sync.', '40b99ad82e5454b65664c8dadb473e15c146997d0e1732ac7a8e962743ea5081'),
        ('Merge relay.', '48bc6e37f950a76e88635f6d97ffa3828f3b48a3e9c6df1a03fcc48fafeaebeb'),
        ('Continuation.', 'f41686f6e73c8aafd2a03404fcd5c1f1faf14d30708fef3d54f6f805f598d8e5'),
        ('Budget.', 'e7ba7cf9490b69535c51f75708ae6be6aa6fbad3cc4929c14666e1d59cb566c6'),
        ('Background work.', '7b806027a546591d490568e32e4f1c96437ec9c2a45855dfadde189b69d17c74'),
        ('Report contract.', '42ed636bfe503c4ef9e596474c2ea5ab4a9a89bb2e09ce587a8249225a1eb4d7'),
    ),
}
L1_HARMLESS = (("controller", "Merge and checkpoint.", "After a merge run the cleanup step", "After a merge, run the cleanup step"),
               ("final_reviewer", "Branch scope.", "the seams between tasks", "the joins between tasks"),
               ("task_reviewer", "Method.", "line by line", "one line at a time"),
               ("implementer", "Build.", "then write the minimal code", "then write the least code"))
# the cadence pattern of test_every_stream_end_verifier_sentence_names_the_condition (tests/test_playbook.py), written out
STREAM_END = re.compile(r"stream-end final verifier|final verifier(?: \(where[^)]*\))? runs once per stream|go "
                        r"to the final verifier|in the verifier \(")

PE_NOW = ("Any other update after the final review (a conflict, a shared path, a consumed module or a skip dependency "
          "in `M`, a red gate, or any later commit on the branch) restarts the pull request's end at the final review.")
PE_NEW = ("An update after the final review that is not clean only because `M` holds a shared path, a consumed module "
          "or a skip dependency, with no conflict and no commit of the branch's own beyond reviewed fix diffs, gets a "
          "delta final review of the update (owner answer 2026-11-24, delta review, L:1056; spec §10 \"Verifier "
          "and merges\"): the merge's diff, `main`'s changes to the consumed modules and the branch's uses of them, and "
          "both full suites on the new head. Any other update after the final review (a conflict, a red gate, or any "
          "later commit on the branch beyond reviewed fix diffs) restarts the pull request's end at the final review.")
SE1_NOW = ("blocks no other stream waits on stay on the stream branch and go out with the stream's final pull "
           "request.")
SE1_ADD = ("An update from the base branch after the final review is reviewed as a delta (process learnings A1; owner "
           "2026-11-24): the review covers the merge's diff, the base branch's changes to the modules the branch's "
           "tasks consume and the branch's uses of them, and one full suite on the new head; a fresh review of the "
           "whole branch runs only when the branch's own code changed beyond fix diffs that were reviewed.")
SE2_NOW = "the `final_verifier` tries to break the branch."
SE2_ADD = ("A reviewer lists in each finding's class statement every member a search of the code finds and records "
           "the search; the implementer's fix tests each listed member; a re-review first runs each search again and "
           "reports a missing member as a finding (process learnings A2; owner 2026-11-24; the members list of "
           "`findings new` and its `gate_register` check are v0.2).")
SE3_NOW = ("an open CRITICAL or HIGH finding becomes an owner question that blocks only that task.")
SE3_ADD = ("For the LOW and MEDIUM findings either verdict leaves to register, the owner question on which task takes "
           "them recommends a planned task of the same stream whose files include a path the findings name, and a new "
           "task only when no such task exists or the fix is too large for that task (process learnings A4; owner "
           "2026-11-24).")
SE4_OLD = "the controller does not re-run the denied action, and a resumed agent runs only its own code"
SE4_NEW = ("the controller does not re-run the denied action and surfaces the denial to the owner, quoted verbatim; "
           "the same effect reached by another tool or command is the same action and waits for the owner's answer "
           "too (process learnings D3; owner 2026-11-24); a resumed agent runs only its own code")
PB1_NOW = "and that the branch matches the plan section it was built from."
PB1_ADD = ("An update from the base branch after this review is reviewed as a delta: the merge's diff, the base "
           "branch's changes to the modules the branch's tasks consume and the branch's uses of them, and one full "
           "suite on the new head; a fresh review of the whole branch runs only when the branch's own code changed "
           "beyond reviewed fix diffs.")
PB2_NOW = ("A class of findings is an epic with child rows, signed off only when every child is resolved and the whole "
           "class is tested and reviewed.")
PB2_ADD = ("A finding's class statement lists every member a search of the code finds, with the search recorded; the "
           "fix tests each member, and a re-review first runs the search again and reports a missing member as a "
           "finding.")
PB3_NOW = ("STOP_NARROW also stops the loop: the open findings are narrowed in one last round or registered for a "
           "planned task (\"Fix rule\").")
PB3_ADD = ("For the LOW and MEDIUM findings either verdict leaves to register, the owner question on which task takes "
           "them recommends a planned task of the same stream whose files include a path the findings name, and a new "
           "task only when no such task exists or the fix is too large for that task.")
PB4_OLD = "the controller does not re-run the denied action, and a resumed agent runs only its own code"
PB4_NEW = ("the controller does not re-run the denied action and surfaces the denial to the owner, quoted verbatim; "
           "the same effect reached by another tool or command is the same action and waits for the owner's answer "
           "too; a resumed agent runs only its own code")
# (id, rel, new text, the replaced old text or None, how often the new text occurs): an insertion pins its anchor
# sentence and the added text together, so the placement is pinned
L1_DOC_PINS = [
    ("SE-L1-1", MS_DOC, SE1_NOW + " " + SE1_ADD, None, 1),
    ("SE-L1-2", MS_DOC, SE2_NOW + " " + SE2_ADD, None, 1),
    ("SE-L1-3", MS_DOC, SE3_NOW + " " + SE3_ADD, None, 1),
    ("SE-L1-4", MS_DOC, SE4_NEW, SE4_OLD, 1),
    ("PE-L1-1", PLAN_DOC, PE_NEW, PE_NOW, 1),
    ("PB-L1-1", "playbook/review.md", PB1_NOW + " " + PB1_ADD, None, 1),
    ("PB-L1-2", "playbook/review.md", PB2_NOW + " " + PB2_ADD, None, 1),
    ("PB-L1-3", "playbook/review.md", PB3_NOW + " " + PB3_ADD, None, 1),
    ("PB-L1-4", "playbook/sessions.md", PB4_NEW, PB4_OLD, 1),
]
FILLER = ("alpha", "bravo", "delta", "echo", "foxtrot", "golf", "hotel", "india", "kilo", "lima", "mike", "tango")
X1_PUBLIC = ("l1_problems",)       # every public (no leading underscore) module-level function


def _exact(name, value, kind):
    if type(value) is not kind:
        raise TypeError("%s must be exactly %s, not %s" % (name, kind.__name__, type(value).__name__))


def l1_problems(role, text, rows=None):
    _exact("role", role, str)
    _exact("text", text, str)
    if rows is not None:
        _exact("rows", rows, tuple)
    out = []
    for ident, role_, label, s, (where, anchor) in (L1_SENTENCES if rows is None else rows):
        if role_ != role:
            continue
        try:
            p = paragraph(text, label)
        except ValueError as e:
            out.append("%s %s: unreadable: %s" % (ident, label, e))
            continue
        if text.count(s) != 1:
            out.append("%s %s: %d times in the file" % (ident, label, text.count(s)))
        ok = {"before": anchor is not None and (" " + s + " " + anchor) in p,
              "after": anchor is not None and (anchor + " " + s) in p,
              "last": p.endswith(" " + s),
              "in": (" " + s) in p}[where]
        if not ok:
            out.append("%s %s: not in place" % (ident, label))
    for role_, label, token in L1_TOKENS:
        if role_ == role and not whole_token(token, paragraph(text, label)):
            out.append("%s lacks %r" % (label, token))
    return out


def _has_denial(role):
    return role != "program_controller" or DENIAL in disk(role)


def _pe_pending(fid, text, new):
    return fid == "PE-L1-1" and PE_NOW in text and new not in text


class LearningsPromptTest(unittest.TestCase):
    def test_new_sentences_in_place_on_disk(self):                       # P1 P2 F1 F2
        for role in sorted({r for _, r, _, _, _ in L1_SENTENCES}):
            with self.subTest(role=role):
                t = disk(role)
                if not _has_denial(role):
                    self.skipTest("merged:records not on this branch")      # F2, ledgered; removed before the final review
                self.assertEqual(l1_problems(role, t), [])
                self.assertEqual(block_problems(t.encode("ascii"), role), [])
                self.assertEqual(forbidden_hits(t), [])
                self.assertEqual(pc.placeholder_hits(t), [])
                self.assertEqual(key_problems(role, t), [])
                self.assertEqual(resume_problems(role, t), [])
                self.assertEqual(labels(t), list(LABELS[role]))
                if role in ("stream_controller", "program_controller"):
                    self.assertEqual(pin_problems(role, t), [])

    def test_denial_skip_rule(self):                                       # F2
        for role in ("controller", "stream_controller", "final_reviewer", "task_reviewer", "implementer"):
            self.assertTrue(_has_denial(role), role)
        self.assertEqual(_has_denial("program_controller"), DENIAL in disk("program_controller"))
        self.assertFalse(_has_denial("program_controller") and DENIAL not in disk("program_controller"))

    def test_sentence_absent_moved_twice_glued_refused(self):             # P3-P6
        for ident, role, label, s, _ in L1_SENTENCES:
            if not _has_denial(role):
                continue
            t = disk(role)
            for name, bad in (("absent", in_para(t, label, lambda p: p.replace(" " + s, ""))),
                              ("moved", other_para(t, label, s, "Budget.")),
                              ("twice here", in_para(t, label, lambda p: p.replace(s, s + " " + s))),
                              ("twice elsewhere", in_para(t, "Budget.", lambda p: p + " " + s)),
                              ("glued", in_para(t, label, lambda p: p.replace(" " + s, s)))):
                with self.subTest(id=ident, role=role, case=name):
                    self.assertTrue(l1_problems(role, bad))

    def test_misplaced_refused(self):                                      # P7
        for ident, role, label, s, (where, anchor) in L1_SENTENCES:
            if where == "in" or not _has_denial(role):
                continue
            t = disk(role)
            first = in_para(t, label, lambda p: p.replace(" " + s, "").replace(label, label + " " + s, 1))
            with self.subTest(id=ident, role=role, case="moved to the start"):
                self.assertTrue(l1_problems(role, first))
            if where == "last":
                with self.subTest(id=ident, role=role, case="followed by a sentence"):
                    self.assertTrue(l1_problems(role, in_para(t, label, lambda p: p + " One more sentence.")))

    def test_tokens_joined_or_recased_refused(self):                      # P8
        for role, label, token in L1_TOKENS:
            if not _has_denial(role):
                continue
            t = disk(role)
            for name, fn in (("deleted", lambda p: p.replace(token, "zzz")),
                             ("joined", lambda p: p.replace(token, "x" + token)),
                             ("upper", lambda p: p.replace(token, token.upper()))):
                if fn(paragraph(t, label)) == paragraph(t, label):
                    continue                      # an upper-case token has no upper mutant
                with self.subTest(role=role, token=token, case=name):
                    self.assertTrue(l1_problems(role, in_para(t, label, fn)))

    def test_old_sibling_sentence_gone(self):                              # P9
        t = disk("implementer")
        self.assertNotIn(OLD_SIBLING, t)
        self.assertTrue(l1_problems("implementer", t.replace(A2_IMPL, OLD_SIBLING)))

    def test_continuation_pin_carries_the_fold(self):                      # P10
        self.assertIn(ESCALATE_CTRL + " " + FOLD + " A change-caused", CONTINUATION)
        self.assertEqual(paragraph(disk("controller"), "Continuation."), CONTINUATION)

    def test_other_paragraphs_unchanged(self):                             # P11
        for role, pins in L1_UNCHANGED.items():
            t = disk(role)
            self.assertEqual(hashlib.sha256("\n".join(t.split("\n")[:3]).encode("ascii")).hexdigest(), pins[0][1], role)
            for label, want in pins[1:]:
                with self.subTest(role=role, label=label):
                    self.assertEqual(hashlib.sha256(paragraph(t, label).encode("ascii")).hexdigest(), want)
            edited = {l for _, r, l, _, _ in L1_SENTENCES if r == role}
            self.assertEqual(len(pins) - 1 + len(edited), len(LABELS[role]), role)

    def test_new_sentences_join_no_class(self):                            # P12 P14
        for s in (DELTA_CTRL,) + DELTA_FR + (A2_FIND, A2_REREVIEW, A2_IMPL, FOLD, DENIAL):
            s.encode("ascii")
            self.assertIsNone(_DEFERRAL.search(s), s)
            self.assertIsNone(_VERIFIER.search(s), s)
            self.assertIsNone(STREAM_END.search(s), s)
            self.assertEqual(forbidden_hits(s), [], s)

    def test_char_and_forbidden_mutants_refused(self):                     # P13 P14 V2 G2
        rng = random.Random(20261128)
        chars = ["\t", "\x00", "\x1b", "\x7f", "§", "—", "Ⱟ"]
        chars += [chr(c) for c in range(0x20) if c != 0x0a]               # LF is the line ending, not a refused character
        while len(chars) < 7 + 31 + 200:
            cp = rng.randrange(0x80, 0x110000)
            if not 0xd800 <= cp <= 0xdfff:
                chars.append(chr(cp))
        for ident, role, label, s, _ in L1_SENTENCES:
            if not _has_denial(role):
                continue
            t = disk(role)
            for ch in chars:
                bad = in_para(t, label, lambda p: p.replace(s, s[:12] + ch + s[12:]))
                with self.subTest(id=ident, role=role, ch=repr(ch)):
                    self.assertTrue(block_problems(bad.encode("utf-8"), role))
            for word, name in (("D3", "spec-clause"), ("Opus", "model-name"), ("lap-timer", "lap-timer")):
                bad = in_para(t, label, lambda p: p.replace(s, s[:-1] + " " + word + "."))
                with self.subTest(id=ident, role=role, word=word):
                    self.assertIn(name, [h[0] for h in forbidden_hits(bad)])

    def test_digit_runs_same(self):                                         # V1
        for ident, role, label, s, _ in L1_SENTENCES:
            if not _has_denial(role):
                continue
            t = disk(role)
            got = [(block_problems(b.encode("ascii"), role), forbidden_hits(b), l1_problems(role, b))
                   for b in (in_para(t, label, lambda p: p.replace(label, label + " " + "9" * n + ".", 1))
                             for n in (1, 4300, 4301))]
            self.assertEqual(got[0], got[1], (ident, role))
            self.assertEqual(got[1], got[2], (ident, role))

    def test_source_names_no_unicode_tables(self):                         # V3
        src = inspect.getsource(sys.modules[__name__])
        for part in (("uni", "codedata"), ("is", "printable"), ("Base", "ExceptionGroup"), ("split", "lines"), (".lo", "wer(")):
            self.assertNotIn("".join(part), src, part)

    def test_source_names_no_path_operation(self):                         # PM
        src = inspect.getsource(sys.modules[__name__])
        banned = {"os", "pathlib", "shutil", "io", "glob", "tempfile"}
        for name, source in (("module", src), ("module with one open( call", src + "\nopen('x')\n")):
            hits = []
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.Import):
                    hits += [a.name for a in node.names if a.name.split(".")[0] in banned]
                if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in banned:
                    hits.append(node.module)
                if isinstance(node, ast.Name) and node.id == "open":
                    hits.append("open")
            with self.subTest(source=name):
                self.assertEqual(bool(hits), name != "module", hits)

    def test_public_helpers_take_exact_types(self):                        # X1
        tree = ast.parse(inspect.getsource(sys.modules[__name__]))
        public = [n.name for n in tree.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")]
        self.assertEqual(public, list(X1_PUBLIC))

        class Sub(str):
            def count(self, *a):
                raise AssertionError("work done before the type check")

        class SubTuple(tuple):
            pass

        text = disk("implementer")
        for name, value, ok in (("role", "implementer", True), ("role", Sub("implementer"), False),
                                ("role", b"implementer", False), ("role", None, False),
                                ("text", text, True), ("text", Sub(text), False), ("text", text.encode("ascii"), False),
                                ("text", None, False), ("rows", None, True), ("rows", (), True),
                                ("rows", [], False), ("rows", SubTuple(), False), ("rows", L1_SENTENCES[:1], True)):
            args = {"role": "implementer", "text": text, "rows": None}
            args[name] = value
            with self.subTest(param=name, value=type(value).__name__):
                if ok:
                    self.assertIsInstance(l1_problems(**args), list)
                else:
                    with self.assertRaises(TypeError) as cm:
                        l1_problems(**args)
                    self.assertIn(name, str(cm.exception))
                    self.assertIn(type(value).__name__, str(cm.exception))

    def test_harmless_rewordings_pass(self):                               # P15
        for role, label, old, new in L1_HARMLESS:
            t = disk(role)
            with self.subTest(role=role, label=label):
                if old not in paragraph(t, label):
                    self.skipTest("reworded on disk; unpinned, so never a failure")
                self.assertEqual(l1_problems(role, in_para(t, label, lambda p: p.replace(old, new, 1))), [])

    def test_generated_rewordings_pass(self):                              # G1
        rng = random.Random(20261128)
        paras = sorted({(r, l) for _, r, l, _, _ in L1_SENTENCES})
        for role, label in paras:
            if not _has_denial(role):
                continue
            t = disk(role)
            p = paragraph(t, label)
            keep = [s for _, r, l, s, _ in L1_SENTENCES if (r, l) == (role, label)]
            keep += [a for _, r, l, _, (_, a) in L1_SENTENCES if (r, l) == (role, label) and a is not None]
            keep += [tok for r, l, tok in L1_TOKENS if (r, l) == (role, label)]
            spans = [(m.start(), m.end()) for k in keep for m in re.finditer(re.escape(k), p)]
            words = [m for m in re.finditer(r"[A-Za-z]+", p)
                     if m.start() > len(label) and not any(a < m.end() and m.start() < b for a, b in spans)]
            self.assertGreater(len(words), 50, (role, label))
            for i in range(200):
                m = rng.choice(words)
                bad = t.replace(p, p[:m.start()] + rng.choice(FILLER) + p[m.end():])
                with self.subTest(role=role, label=label, case=i):
                    self.assertEqual(l1_problems(role, bad), [])

    def test_rows_argument_replaces_the_rows(self):                        # X1 (rows)
        t = disk("controller")
        bad = t.replace(" " + DELTA_CTRL, "")
        self.assertTrue([p for p in l1_problems("controller", bad) if p.startswith("A1 ")])
        self.assertEqual([p for p in l1_problems("controller", bad, ()) if p.startswith("A1 ")], [])
        row = ("X", "controller", "Budget.", "no such sentence.", ("in", None))
        self.assertEqual(l1_problems("controller", t, (row,)),
                         ["X Budget.: 0 times in the file", "X Budget.: not in place"])
        for where in ("before", "after"):                 # a before or after row with no anchor is refused, not crashed
            row = ("X", "controller", "Budget.", "no such sentence.", (where, None))
            self.assertEqual(l1_problems("controller", t, (row,)),
                             ["X Budget.: 0 times in the file", "X Budget.: not in place"])
        row = ("X", "controller", "Nonesuch.", "no such sentence.", ("in", None))
        self.assertEqual(l1_problems("controller", t, (row,)),
                         ["X Nonesuch.: unreadable: label 'Nonesuch.' found 0 times"])

    def test_pe_skip_rule(self):                                           # PE
        self.assertTrue(_pe_pending("PE-L1-1", PE_NOW, PE_NEW))
        self.assertFalse(_pe_pending("SE-L1-1", PE_NOW, PE_NEW))
        self.assertFalse(_pe_pending("PE-L1-1", PE_NEW, PE_NEW))
        self.assertFalse(_pe_pending("PE-L1-1", "no text", PE_NEW))
        self.assertFalse(_pe_pending("PE-L1-1", PE_NOW + PE_NEW, PE_NEW))


class LearningsDocsTest(unittest.TestCase):
    def test_every_doc_edit_in_place(self):                                # D1 PE
        for fid, rel, new, old, n in L1_DOC_PINS:
            with self.subTest(fid=fid):
                if _pe_pending(fid, read(rel), new):
                    self.skipTest("docs PR plan text not on this branch")
                self.assertEqual(fix1_problems(read(rel), new, old, n), [])

    def test_each_doc_pin_fails_restored(self):                            # D2 PE
        for fid, rel, new, old, n in L1_DOC_PINS:
            with self.subTest(fid=fid):
                if _pe_pending(fid, read(rel), new):
                    self.skipTest("docs PR plan text not on this branch")
                if old is not None:
                    self.assertTrue(fix1_problems(read(rel).replace(new, old), new, old, n))

    def test_each_doc_pin_fails_without_new(self):                         # D3r PE
        for fid, rel, new, old, n in L1_DOC_PINS:
            with self.subTest(fid=fid):
                if _pe_pending(fid, read(rel), new):
                    self.skipTest("docs PR plan text not on this branch")
                self.assertTrue(fix1_problems(read(rel).replace(new, ""), new, old, n))

    def test_playbook_edits_keep_playbook_checks(self):                    # D4 (Q-L-2 (b))
        for rel in ("playbook/review.md", "playbook/sessions.md"):
            t = read(rel)
            self.assertEqual(deferral_problems(t, rel), [])
            self.assertEqual(verifier_step_problems(t, rel), [])
            self.assertEqual(pc.placeholder_hits(t), [])
            self.assertEqual(forbidden_hits(t), [])
            t.encode("ascii")


if __name__ == "__main__":
    unittest.main()
