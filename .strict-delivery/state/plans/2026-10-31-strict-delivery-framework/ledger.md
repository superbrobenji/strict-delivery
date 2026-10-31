# Ledger: docs/strict-delivery/plans/2026-10-31-strict-delivery-framework.md

Bootstrap (spec §16): no gates in this repository; judgment rules applied by hand. Commit gate until gates land: unittest on python3 (3.9.6) and python3.13, clean tree.

## Block 1a (branch block/b1a, base c4f36f1)

Pre-flight scan:
| pair / task | produces vs consumes | result |
|---|---|---|
| 1a.1 -> 1a.2 | yamlsub.load(path, shown) raises YamlError; config.load wraps it as GateError with file and line | consistent |
| 1a.1 -> 1a.2 | emit() used by tests/helpers.make_repo | consistent |
| 1a.2 -> 1a.3 | cfg paths.state, ids.*, state.shard_size; gitinfo.show for immutability | consistent |
| 1a.1 self | test_invalid_utf8 asserts substrings of str(YamlError(0, ...)) | consistent |
| 1a.2 self | __main__ registers commands that later tasks fill; `check` has no gates yet | consistent (empty table until 1b.2) |
| 1a.3 self | schema:1 wrappers vs load() row shapes | consistent after plan edit |
| 1a.* vs Global Constraints | stdlib only, unittest, both interpreters | consistent |
| plan vs repo | no .gitignore; SDD workspace .superpowers/ and __pycache__ would be untracked, blocking the clean-tree commit gate | gap |

Ruling: .gitignore (`.superpowers/`, `__pycache__/`, `.strict-delivery/receipts/`) is created in Task 1a.1 -- the clean-tree rule needs it and no task owns it -- cost if wrong: one extra file in 1a.1's diff -- spec §5 (receipts git-ignored), §16
Ruling: strict prompt blocks are dispatched verbatim; their lap-timer commit-gate paths (tools/gates/run_all.py, tools/.venv) do not exist here, so each ## Task states this repo's bootstrap commit gate -- cost if wrong: a child follows the wrong gate text -- spec §16 bootstrap
Task 1a.1: dispatched implementer (sonnet), base c4f36f1
Task 1a.1: implementer DONE b762d65; controller re-ran gate at b762d65: py3.9 OK, py3.13 OK, tree clean but ledger; task review dispatched (opus)
Task 1a.1: review DONE_WITH_FINDINGS (opus): F1 Important unicode strip(); F2 Important tab after ':'/'-'; F3 Minor block-scalar blank lines; F4 Minor emit writes depth parse refuses; F5 Minor IntEnum emit differs 3.9/3.13; F6 Minor over-quoting vs brief "only when". Strict: minors are fixed in this fix round, never deferred.
Ruling: unstated grammar rules 1,2,5,6,7 (extra plain-start refusals `, ] } ? -`, trailing-comma refusal, control-char/surrogate refusal, top-level scalar accepted, quoted '<<' is a plain key) stand -- each refuses an input outside the accepted grammar (fail closed) or accepts a node the grammar already lists -- cost if wrong: a hand-written file using these needs quoting -- plan Global Constraints "every other YAML feature is refused with a line number", spec §6
Ruling: unstated rule 8 (load() on missing/unreadable file raises OSError) is a defect, fixed in round 1 as YamlError naming `shown` -- brief: "Every YamlError from it carries shown"; gates fail closed on missing input as <gate>.input -- cost if wrong: none -- spec §13
Owner question pending: rules 3,4 (MAX_INT_CHARS=1000, MAX_DEPTH=50) are acceptance limits the spec does not state; current values kept until answered.
Owner answer 2026-10-31: MAX_INT_CHARS=1000, MAX_DEPTH=50 kept, added to spec §6 (uncommitted; goes to the 1a.1 re-review as a diff file, committed after review)
Task 1a.1: fix round 1 implementer DONE be290af; controller gate at be290af: 3.9 OK, 3.13 OK
Task 1a.1: fix round 1/5 (F1-F5, R8 addressed; F6 residual `---`/`...` over-quoted; new N1 Important: emit writes leading U+FEFF plain, load strips it; N2 Minor: F1 peek line :238 untested; S1 spec wording; commits b762d65..be290af)
D30 check: N1 is inside F6's recorded class (emit quotes only when plain would not come back identical) -- the class now reads "through load()", not only parse(); no new class, loop continues.
Q-yaml-1 (escape non-printables vs literal) settled by the brief's "quoted ... only when a plain scalar would not re-parse as the same str" -- no ruling, brief stands.
S1: controller rewords spec §6 limits line (emitter refuses with an error, no line) -- in spec-limits.diff for round-2 re-review.
Task 1a.1: fix round 2 implementer DONE 591e3ec; controller gate 3.9 OK, 3.13 OK
Task 1a.1: fix round 2/5 (N1, N2, S1 addressed; F6 residual addressed for values/items/top; N3 Minor open: keys judged as if first line at indent 0, over-quoting U+FEFF and '--- a'/'... a' keys elsewhere -- inside F6 class; commits be290af..591e3ec)
Task 1a.1: fix round 3 implementer DONE 673c61e; controller gate 3.9 OK, 3.13 OK
Task 1a.1: fix round 3/5 (N3 addressed, N1 holds, no new breakage; commits 591e3ec..673c61e)
Controller miss: rereview-1 listed `load("a\0b")` ValueError as out of scope; it is in R8's class (load fails closed as YamlError naming `shown` on any path problem) and in this task's own code since b762d65, so the task is incomplete. Entered at b762d65; missed because R8 was worded "missing or unreadable" instead of the class. Round 4 (fresh implementer, one tier up per strict fix loop).
Task 1a.1: fix round 4 (fresh opus) DONE 4b7cebb, eb022ef (fspath-raises inside class per dispatch wording); controller gate 3.9 OK, 3.13 OK
Task 1a.1: fix round 4/5 (R8-b addressed over 32 cases; new N4 Minor caused by round 4: fd leak when path swapped to a directory between stat and open, yamlsub.py:479/:485; commits 673c61e..eb022ef)
D30 trip: N4 (resource leak) is outside R8-b's recorded class (fail closed on path problems). Fixes stopped; read-only investigator dispatched on where each 1a.1 defect entered and why its review missed it; owner gets process changes with evidence before round 5.
Investigation (opus, read-only) DONE: report task-1a.1-investigation.md. Root causes RC1 no input-domain table; RC2 oracle not production path / no independent expected value; RC3 unstated rules recorded as claims not questions; RC4 class worded by value then used as scope fence; RC5 fix rounds swap mechanisms without invariant list or per-line mutants. Proposed PC1-PC5. D-4: controller's fspath-inside-R8-b call may be an owner-only class widening.
Halted for owner: PC1-PC5 adoption and scope; D-4; then round 5 (N4).
Owner answers 2026-10-31: (1) PC1-PC5 adopted for this plan now and for this repo's block-3 prompt blocks; shared ~/.claude skill untouched. (2) D-4 confirmed: a PathLike whose __fspath__ raises is inside R8-b (owner, not controller). (3) Round 5 with the new process: 1a.1 input-domain table + N4 + red rows + expected-value fuzz.
Plan edited (PC1-PC5 under "Process for this plan"); spec §6 limits edit; both uncommitted, in process-text.diff for the round-5 re-review, committed after it.
Task 1a.1 input-domain table: task-1a.1-domain.md (controller draft, rows P1-P12, L1-L6, E1-E6).
class (N4): load error paths: every refusal path in load releases every fd it opened.
Task 1a.1: round 5 not started (round-4 agent BLOCKED: budget before any work; no commits). Round 5 re-dispatched to a fresh opus implementer with its own budget (tokens=200000 minutes=75), matching the owner-approved 'one larger round, about an hour'.
Task 1a.1: round 5 (fresh opus) NEEDS_DECISION: 571d963 N4, 9e39d51 table rows + red P5 fix (` #` in flow), c715d55 oracle fuzz; 112 tests; 8/8 mutants killed; controller gate 3.9 OK 3.13 OK; docs edits verified intact.
Process incident: round-5 implementer ran `git stash`/`pop`, briefly stashing the controller's uncommitted docs edits (told not to touch them). Restored intact (diff matches process-text.diff). Reported to owner.
Halted for owner: D1-D9 (round-5 report "Decision needed"). Scoped re-review of eb022ef..c715d55 dispatched meanwhile.
Owner answers 2026-10-31 on D1-D9 (all recommended): D1 keep TypeError for non-str parse input; D2 tab after #, |, |- accepted (table amended); D3 tab at block-scalar line start refused; D4 `#` and `|` starting a flow item refused (code change); D5 tab in the whitespace after `: ` refused, like `- \t` (code change); D6 control chars emitted as \u escapes; D7 next-line scalars and multi-line flow/quoted scalars refused by design; D8 empty | gives "", deeper whitespace-only lines stay content; D9 error wording not a contract.
class (D4): flow-item first character: `#` and `|` refused, like the other indicators. class (D5): leading whitespace of a value after a `:` or `- ` separator: a tab anywhere in it is refused.
D4/D5 land as an owner-directed change after the round-5 re-review (not a sixth fix round).
Task 1a.1: round-5 re-review (fresh opus) NEEDS_DECISION: N4 ADDRESSED (23 paths x 50 calls, 0 fds); P5-red ADDRESSED; T1 22/24 (T1-a: P1, P5 tests pin current behaviour, close with D1/D2 rulings); T2-a: oracle alphabet misses values within rows (flow ` #`, tab after `,`, `- `/`? ` starts, block-scalar blank variants, CRLF), and a mutant removing the P5 fix survives TestOracle; Q-yamlsub-1: ` #` in a block-scalar body is content (my P5 class overreached); Q-yamlsub-2: row vs value coverage. Divergences: P5 class line not in PC5 form (controller miss); spec §6 does not define a nesting level.
Breaker: 5 rounds used; open items go to the owner (no round 6).
Owner answers 2026-10-31: program/board.md renamed program/status.md (spec §5, §9 x2, §11 edited); Q-yamlsub-2 (a) value-level oracle coverage; Q-yamlsub-1 (a) narrow class; spec §6 nesting-level sentence (a) added; owner-directed change: D4, D5, T1-a, T2-a.
class (P5-comment, restated in PC5 form): comment start: ` #` (space or tab then #) outside quoted scalars and block-scalar bodies, in every other position including flow sequences.
class (T2-a): oracle alphabet: every value listed in rows P2-P6 and P10, plus CRLF, generated with expected values.
Owner answers 2026-10-31: (1) docs namespaced under docs/strict-delivery/ (INDEX.md, specs/, plans/, reviews/); (2) init/upgrade never overwrite a non-framework path, conflicts listed; (3) this repo's docs move under docs/strict-delivery/ after Task 1a.1 review closes; plus: init migrates existing docs/superpowers/{specs,plans} with git mv and reference rewrite, on the owner's word. Spec §3, §4, §5, §9, §14, §17 and plan 1a.2 defaults + block-4 outline edited (uncommitted, in process-text.diff). Also fixed: spec §5 "superpowers layout by default" contradicted docs/specs.
Owner answer 2026-10-31: lean tree (a) all three: generated files git-ignored and regenerated; post-merge prune of plan workspace and reviews with <sha>:<path> evidence; init-managed .gitignore block. Spec §5, §8, §9 and plan 1b.3 (evidence sha:path + test), 1c.2 (ignore generated files) edited, uncommitted.
Owner answer 2026-10-31: batch owner questions (per task, before dispatch, from the input-domain table; mid-task questions held to the next stop); keep strict profile; keep full v0.1 scope. Plan process section edited.
Task 1a.1: owner-directed change DONE (NEEDS_DECISION U1, U2; UF-1 dead regex tail): 13fde15, b4d41d6, 4399b04; controller gate 3.9 OK 3.13 OK; docs intact. Scoped review dispatched; U1/U2 held for the review stop (batching).
Owner answer 2026-10-31: batching stays as recorded (upfront batch before dispatch; mid-task questions held to next stop).
Owner answers 2026-10-31: (a) streams: stream B (block 3 prose) and stream C (stack detection + gate_cites, after 1a merges) alongside stream A; (d) read-only look at lap-timer block/program-tooling and block/strict-delivery-b5 as port candidates; new requirement: the streams way of working becomes a first-class framework feature (planning large efforts as programs of streams, with gates, tracking docs and agent roles specified). Sequence: investigation -> spec §11 expansion (owner review) -> stream B/C plan sections (owner review) -> launch. Stream A continues meanwhile.
Owner answer 2026-10-31: streams feature: (a) wait for investigator report, then superpowers brainstorming (section-by-section approval), then spec (expanded §11 or linked sub-spec), then writing-plans update, then launch streams B and C. Stream A continues.
Task 1a.1: closing review (fresh opus) NEEDS_DECISION: D4, D5, T1-a, Q-yamlsub-1 ADDRESSED; T2-a ADDRESSED at value level; T2-b (caused by this change): _DocGen docstring claims every P5 indicator x follower pair, some pairs and \udfff never generated; UF-1 dead `[ \t]*` at yamlsub.py:395 (this task's code, quality finding under PC4); Q-yamlsub-3 pairs vs followers; U1 unsettled, and `k:\t`/`-\t` accepted contradict table P5; U2 contradicts table P5.
D30 check: T2-b inside T2-a's class (oracle alphabet); no new class.
Process text: PT-1 (doctor/gate_index with ignored indexes), PT-2 (no-overwrite vs managed-block insertion), PT-4 (live plan workspaces tracked) fixed by controller in spec; PT-3 (this repo's docs paths) is the planned move after 1a.1 closes.
Incident: closing reviewer overwrote earlier agents' scratch probe files (cov.py, mut.py) in the shared scratchpad; transcripts intact. Future dispatches: every agent uses its own mktemp -d, never the shared scratchpad.
Owner answers 2026-10-31: U1 (c) refuse all: a tab after `: ` or `- ` is refused whatever follows (comment, end of line, value); U2 (a) `|`/`|-` header followed by NBSP or other non-space content refused, table P5 amended; Q-yamlsub-3 (a) every P5 indicator x every follower pair generated, plus \udfff.
class (U1): separator followers: a tab directly after `:` or `-` separators, or in the whitespace after them, is refused with the line, whatever follows.
class (Q-yamlsub-3/T2-b): oracle alphabet: every (P5 indicator, P5 follower) pair and every listed P2-P3 code point.
Task 1a.1: final owner change DONE b0b50a2, 6301cd0, 47eb880; controller gate 3.9 OK 3.13 OK (115); docs intact; scoped review dispatched
Task 1a.1: final-change review DONE_WITH_FINDINGS: U1, UF-1 ADDRESSED; U2-t (no test for header + space/tab + text; a mutant accepting `k: | x` survives); T2-c (oracle counts " \t" as tab-after-separator; a mutant removing direct tabs survives TestOracle); production code correct on every probe. PT-1 leftovers (spec §14 "stale index", plan block-5 "wraps index.stale") fixed by controller; PT-2, PT-4 ADDRESSED.
Fix cap long exceeded (5 rounds + 2 owner changes): test-only gaps go to the owner.
Owner answer 2026-10-31: (a) one last test-only change on Task 1a.1 (U2-t, T2-c), then scoped review. class (U2-t): block-scalar header followers: header then space/tab then non-comment text is refused, pinned by a test. class (T2-c): oracle pair count: a tab pair is counted only when the tab is directly after the separator.
Task 1a.1: test-only change DONE 004854a (gates/ untouched); controller gate 3.9 OK 3.13 OK; scoped review dispatched
Task 1a.1: complete (commits c4f36f1..004854a; closing review clean: spec, quality, claims-executed all pass; 5 fix rounds + 3 owner-directed changes)
Docs moved: fc3aaf2 (reviewed process text), 63222e0 + 43a6beb (this repo's spec and plan under docs/strict-delivery/; mechanical move, goes to the block-1a final review).
CHECKPOINT 1a 1a.1 head=43a6beb tests=115/115 gates=n/a next=1a.2
