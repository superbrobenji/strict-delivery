"""B4 mutation harness (spec 8: each mutant runs on a private export, never the checkout).

usage, from any directory inside the repository:  python3 B4-mutate.py <commit> [<transcript path>]
For every group of findings it makes a private `git worktree add --detach` of <commit> in its own mkdtemp directory,
and for each mutant: (1) present run of the targeted modules, (2) one exact string change to one file, a syntax check
(compile()) of the mutated file when it is a .py file, the mutant run, (3) the file written back byte for byte and
read back, the restored run. Each run is on /usr/bin/python3 and /opt/homebrew/bin/python3.13 (in parallel). The
worktree is removed with `git worktree remove` at the end. An outcome is KILLED (rc != 0) or SURVIVED (rc == 0).
The groups run as parallel child processes of this script; the parts are joined into the transcript at the end."""
import os
import re
import subprocess
import sys
import tempfile

PYS = (("python3", "/usr/bin/python3"), ("python3.13", "/opt/homebrew/bin/python3.13"))
SK, PB, PR = "tests.test_skill", "tests.test_playbook", "tests.test_prompt_blocks"
ENV = dict(os.environ, PATH="/Library/Developer/CommandLineTools/usr/bin:" + os.environ["PATH"])
SRC = subprocess.run(["git", "rev-parse", "--show-toplevel"], stdout=subprocess.PIPE, check=True).stdout.decode().strip()
THIS = os.path.abspath(__file__)

OG = ("A table enumerates the full input class or restricts the input, so the code refuses what lies outside the "
      "enumerated class, and never samples an open grammar.")
OG_SKILL = ("Every input-domain table enumerates the full input class or restricts the input, so the code refuses what "
            "lies outside the enumerated class, and never samples an open grammar.")
LIVE_PB = ("Before it writes that handoff, a controller dispatches nothing new and waits, inside its turn, for the "
           "handback of every child still running; a child that a usage-limit stop cuts off before its handback is "
           "listed in the handoff's `live_subagents`.")
LIVE_CT = ("Before you write your handoff, dispatch nothing new and wait, inside your turn, for the handback of every "
           "child still running; a child that a usage-limit stop cuts off before its handback is listed in your "
           "handoff's `live_subagents`.")
U2_SKILL = ("Every dispatch carries its role's prompt block byte for byte and chooses a tier; its `## Model` names the "
            "model config `models.tiers` maps that tier to, and every other line of a brief or report names tiers, "
            "never a model.")
U2_SKILL_OLD = ("Every dispatch carries its role's prompt block byte for byte and names a tier, never a model; config "
                "`models.tiers` maps each tier to a model.")
U2_ROLES = ("A role runs at its minimum tier or above. A dispatch chooses a tier, and config `models.tiers` maps each "
            "tier to the model the project uses: the dispatch's `## Model` names that model, and every other line of a "
            "brief or report names tiers, never a model.")
U2_ROLES_OLD = ("A role runs at its minimum tier or above, and a dispatch names a tier, never a model: config "
                "`models.tiers` maps each tier to the model the project uses.")
U2_CT = ("Name tiers in every brief and report, never a model, except under `## Model`, which names the model that "
         "`models.tiers` maps the chosen tier to.")
U2_CT_OLD = "Name tiers in every brief and report, never a model."
CT = "skills/strict-delivery/prompts/controller.md"
SKILLF = "skills/strict-delivery/SKILL.md"
ROLES = "playbook/roles.md"
REVIEW = "playbook/review.md"
SESS = "playbook/sessions.md"
TSK, TPB, TPR = "tests/test_skill.py", "tests/test_playbook.py", "tests/test_prompt_blocks.py"
OWN = {TSK: (SK,), TPB: (PB,), TPR: (PR,), SKILLF: (SK, PB), CT: (PR, PB), ROLES: (PB,), REVIEW: (PB,), SESS: (PB,)}

# section -> (title, [(name, file, old, new)])
SECTIONS = {
    "FR-1": ("FR-1: harmless-rewording self-check requires its sample phrase on disk (prompt blocks, playbook, K20)", [
        ("DIRECTIVE_HARMLESS skip reverted to assertIn", TPR,
         '                if old not in paragraph(t, label):\n                    self.skipTest("FR-1: %r is reworded on disk; unpinned, so never a failure" % old)\n',
         '                self.assertIn(old, paragraph(t, label))\n'),
        ("DIRECTIVE_HARMLESS skip made invisible (continue)", TPR,
         '                    self.skipTest("FR-1: %r is reworded on disk; unpinned, so never a failure" % old)\n',
         '                    continue\n'),
        ("B3_HARMLESS skip reverted to assertIn", TPB,
         '                if old not in b3_unit(pc.section(t, heading), start):\n                    self.skipTest("FR-1: %r is reworded on disk; unpinned, so never a failure" % old)\n',
         '                self.assertIn(old, b3_unit(pc.section(t, heading), start))\n'),
        ("B3_HARMLESS skip made invisible (continue)", TPB,
         '                    self.skipTest("FR-1: %r is reworded on disk; unpinned, so never a failure" % old)\n',
         '                    continue\n'),
        ("K20 SD-R7 skip reverted to a bare index", TPB,
         '            self.harmless_phrase_skipped_if_absent(why)\n',
         '            why.index("of a class")\n'),
    ]),
    "U-3": ("U-3: test_skill HARMLESS rows go through changed() and need the phrase on disk", [
        ("HARMLESS skip reverted to changed() presence check", TSK,
         '                if old not in t:\n                    self.skipTest("FR-1/U-3: %r is reworded on disk; unpinned, so never a failure" % old)\n',
         '                changed(t, old, new)\n'),
        ("HARMLESS skip made invisible (continue)", TSK,
         '                    self.skipTest("FR-1/U-3: %r is reworded on disk; unpinned, so never a failure" % old)\n',
         '                    continue\n'),
    ]),
    "FV-1": ("FV-1: placement checks count each new sentence over its paragraph or unit, not its file", [
        ("placed_problem counts over the paragraph", TPR,
         'any(text.count(s) != 1 for s in sentences)', 'any(p.count(s) != 1 for s in sentences)'),
        ("b3_problems counts over the unit", TPB,
         'if any(text.count(s) != 1 for s in sentences):', 'if any(unit.count(s) != 1 for s in sentences):'),
    ]),
    "U-6": ("U-6: substring pins in the skill's pin check", [
        ("section-level pin check back to a substring", TSK,
         'need(pc.whole_token(pin.lower(), low), "pin: %s %r absent" % (h, pin))',
         'need(pin.lower() in low, "pin: %s %r absent" % (h, pin))'),
        ("sentence-level pin check back to a substring", TSK,
         'need(any(pc.whole_token(pin.lower(), s.lower()) for pin in PINS[h]),',
         'need(any(pin.lower() in s.lower() for pin in PINS[h]),'),
    ]),
    "U-2": ("U-2: shipped prose says a dispatch names a tier, never a model", [
        ("SKILL.md line back to the old unqualified text", SKILLF, U2_SKILL, U2_SKILL_OLD),
        ("SKILL.md `## Model` clause dropped", SKILLF,
         "; its `## Model` names the model config `models.tiers` maps that tier to,", ","),
        ("roles.md back to the old unqualified text", ROLES, U2_ROLES, U2_ROLES_OLD),
        ("roles.md `## Model` clause dropped", ROLES,
         ": the dispatch's `## Model` names that model, and every other line", ", and every other line"),
        ("controller.md back to the old unqualified text", CT, U2_CT, U2_CT_OLD),
        ("controller.md `## Model` exception dropped", CT,
         ", except under `## Model`, which names the model that `models.tiers` maps the chosen tier to.", "."),
        ("controller.md sentence copied into Oracle.", CT, "Oracle. A test calls", "Oracle. " + U2_CT + " A test calls"),
        ("roles.md sentence copied into Budget cap", ROLES,
         "Each role's budget cap is config", "A dispatch chooses a tier, and config `models.tiers` maps each tier to the model the project uses: the dispatch's `## Model` names that model, and every other line of a brief or report names tiers, never a model. Each role's budget cap is config"),
    ]),
    "U-4": ("U-4: the input-domain table rule lacks spec 8 :505's open-grammar sentence", [
        ("review.md sentence deleted", REVIEW, " " + OG, ""),
        ("sessions.md sentence deleted", SESS, " " + OG, ""),
        ("SKILL.md line deleted", SKILLF, "\n\n" + OG_SKILL, ""),
        ("controller.md sentence deleted", CT, " " + OG, ""),
        ("review.md sentence copied into item 2", REVIEW,
         "never one read back from the code under test.", "never one read back from the code under test. " + OG),
        ("sessions.md sentence copied into Blocks and checkpoints", SESS, "No limit has a default.",
         "No limit has a default. " + OG),
        ("SKILL.md sentence copied into Verification method line 1", SKILLF,
         "and record both commands with their output.", "and record both commands with their output. " + OG_SKILL),
        ("controller.md sentence copied into Oracle.", CT, "Oracle. A test calls", "Oracle. " + OG + " A test calls"),
    ]),
    "U-5": ("U-5: controller handoff with live children", [
        ("SKILL.md line deleted", SKILLF, "\n\n" + LIVE_PB, ""),
        ("sessions.md sentence deleted", SESS, " " + LIVE_PB, ""),
        ("controller.md sentence deleted", CT, " " + LIVE_CT, ""),
        ("SKILL.md sentence copied into Continuation line", SKILLF,
         "with a clean worktree at every checkpoint.", "with a clean worktree at every checkpoint. " + LIVE_PB),
        ("sessions.md sentence copied into Blocks and checkpoints", SESS, "No limit has a default.",
         "No limit has a default. " + LIVE_PB),
        ("controller.md sentence copied into Background work.", CT, "Background work. A job",
         "Background work. " + LIVE_CT + " A job"),
        ("controller.md sentence moved into Continuation. (PB7 pins it unchanged)", CT,
         "Nothing continues from inherited memory, and the owner never clears the session and re-prompts.",
         LIVE_CT + " Nothing continues from inherited memory, and the owner never clears the session and re-prompts."),
    ]),
}
GROUPS = (("FR-1", "U-3", "FV-1", "U-6"), ("U-2",), ("U-4",), ("U-5",))


def run(root, mods):
    procs = [(n, subprocess.Popen([py, "-m", "unittest"] + list(mods), cwd=root, env=ENV,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT)) for n, py in PYS]
    out = []
    for n, p in procs:
        text = p.communicate()[0].decode("utf-8", "replace")
        tail = [l for l in text.strip().split("\n") if l][-1] if text.strip() else ""
        failing = sorted({m.group(1) for m in re.finditer(r"^(?:FAIL|ERROR): (\w+)", text, re.M)})
        out.append((n, p.returncode, tail, failing))
    return out


def lines(tag, label, res):
    out = []
    for n, rc, tail, failing in res:
        word = ("KILLED" if rc != 0 else "SURVIVED") if tag == "mutant" else ("PASS" if rc == 0 else "FAIL")
        out.append("%-8s %-8s %-62s %-10s rc=%d %s %s" % (tag, word, label, n, rc, tail, ",".join(failing)[:130]))
    return out


def child(commit, secs, outpath):
    tmp = tempfile.mkdtemp()
    wt = os.path.join(tmp, "wt")
    subprocess.run(["git", "worktree", "add", "--detach", "-q", wt, commit], cwd=SRC, check=True)
    log = open(outpath, "w")

    def w(s):
        log.write(s + "\n")
        log.flush()
    count = {"mutants": 0, "killed": 0, "survived": 0}
    try:
        for sec in secs:
            title, mutants = SECTIONS[sec]
            w("")
            w("## %s" % sec)
            w(title)
            w("export: git worktree add --detach %s %s (private, removed afterwards); runs: PATH=/Library/Developer/CommandLineTools/usr/bin:$PATH <python> -m unittest <modules>" % ("<mktemp -d>/wt", commit))
            for name, rel, old, new in mutants:
                mods = OWN[rel]
                path = os.path.join(wt, rel)
                with open(path, "rb") as f:
                    orig = f.read()
                text = orig.decode("utf-8")
                if text.count(old) != 1:
                    w("ABORT %s: old string occurs %d times in %s" % (name, text.count(old), rel))
                    raise SystemExit(2)
                w("mutant: %s [%s] modules: %s" % (name, rel, " ".join(m.split(".")[-1] for m in mods)))
                for l in lines("present", name, run(wt, mods)):
                    w(l)
                mutated = text.replace(old, new, 1)
                if rel.endswith(".py"):
                    compile(mutated, rel, "exec")            # SyntaxError aborts the script: the mutant would be moot
                    w("syntax   OK       %s: compile() of the mutated file" % rel)
                else:
                    w("syntax   n/a      %s is markdown" % rel)
                with open(path, "wb") as f:
                    f.write(mutated.encode("utf-8"))
                try:
                    res = run(wt, mods)
                finally:
                    with open(path, "wb") as f:
                        f.write(orig)
                with open(path, "rb") as f:
                    assert f.read() == orig
                for l in lines("mutant", name, res):
                    w(l)
                for n, rc, tail, failing in res:
                    count["mutants"] += 1
                    count["killed" if rc != 0 else "survived"] += 1
                for l in lines("restored", name, run(wt, mods)):
                    w(l)
        w("")
        w("count %s: %s" % (",".join(secs), count))
    finally:
        log.close()
        subprocess.run(["git", "worktree", "remove", "--force", wt], cwd=SRC, check=True)
        os.rmdir(tmp)


def main():
    if sys.argv[1] == "--child":
        child(sys.argv[2], sys.argv[4].split(","), sys.argv[3])
        return
    commit = sys.argv[1]
    final = sys.argv[2]
    scratch = tempfile.mkdtemp()
    parts = []
    procs = []
    for i, g in enumerate(GROUPS):
        part = os.path.join(scratch, "part%d.txt" % i)
        parts.append(part)
        procs.append(subprocess.Popen([sys.executable, THIS, "--child", commit, part, ",".join(g)]))
    for p in procs:
        p.wait()
    with open(final, "a") as out:
        for part, p in zip(parts, procs):
            with open(part) as f:
                out.write(f.read())
        total = sum(len(SECTIONS[s][1]) for g in GROUPS for s in g)
        out.write("\ntotal: %d distinct mutants in %d sections (each run on 2 interpreters, so %d mutant runs); child exit codes %s\n"
                  % (total, sum(len(g) for g in GROUPS), 2 * total, [p.returncode for p in procs]))


main()
