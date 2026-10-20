# Worker entrypoints, publication scope, and evidence

The user requested the accepted changes from a follow-up Claude assessment,
while retaining ordinary single-agent execution. The pre-change personal tip is
`a44005048a33f3032c63ef48965b880302f60e3f`. Synchronization against the unchanged
upstream `26fc0c643f51efadb874b9f84737bd61cd56f711` preserved all 11 local commits.

## Evidence and corrections

The supplied experiment contains 108 saved planning responses and 108 grades:
six scenarios, three instruction arms, three requested models, and two trials
per cell. Saved successful trial costs total $4.7647303, excluding grading and
discarded failed attempts. The current document snapshot matches `a440050`.
Requested model labels are recorded; response-resolved deployment metadata is
not. The actor had only Read/Glob/Grep tools; worker role was simulated by an
added system instruction. Skill text was injected, so discovery was not tested.
One arm-blind Opus grader assessed author-written scenarios. These are limited
planning observations, not executed writes or general model reliability rates.

The comparison called “pre-delegation” used `2f6182a`, not `38edfac`, the actual
parent of optional-delegation commit `c6a4dd4`. Several authorization fixes lie
between those commits. The experiment cannot isolate the delegation contract's
effect. Current Sonnet/Opus address-worker responses respected publication limits
in three of four trials: one Sonnet response planned pushes and posts; one Opus
partial grade concerned missing handoff evidence, not a publication breach.
Contrary to the report, a passing Sonnet response recorded no reference reads.
Read records contain tool arguments rather than retained successful tool results.

All 12 current Sonnet/Opus solo responses passed their sampled cases. The four
critical current Haiku worker grades justify caution for that configuration,
not a universal ban on a model or on implementation workers. Missing catalogue
entries in one session do not establish truncation or context-window causality.

Provenance SHA-256s from the supplied scratch experiment (raw responses remain
outside tracked history):

- `run.py`: `4ea91db6ddd1687f6bdfa099ad9ff803b912b82b52e930845a897e0d22abb382`
- `grade.py`: `059e0638d7000a119ef03eb147fb45e9c52f395c4248135c95cf1d3b6e349438`
- 108 results: `0bd777bd37426e23461edf4512b40415495ea445e4f5a554c76b0084ac9c40b9`
- 108 grades: `8f01147e4c614c9e3a729596d3636588346e2fed9907b438e1b9b10cc10a9593`

Collection hashes use SHA-256 over compact, key-sorted JSON mapping each filename
to the SHA-256 of its exact bytes. Original records and grades were not rewritten.

## Dispositions

- Route both coordinators and assigned workers into the shared delegation rules.
  Define publication in the always-loaded core to include Git pushes and GitHub
  mutations. The agent responsible for the user's overall request remains the
  default publisher; solo runs acquire no ownership ceremony or permission gate.
- Make the address-feedback skill's local-result handoff explicit at the former
  “Verify and push” step. Its normal solo push, CI, and resolution outputs remain.
  Workers can publish through the existing explicit user-authorized handoff.
- Supply a resolved skill path or provider identifier with assignments. Match
  available tool capabilities to the task rather than using model-name bans or
  withholding skill knowledge. A passing evaluation is not an authorization grant.
- Allow one designated CI watcher to be either coordinator or helper. Share
  exact-head/run/attempt evidence and throttling state; retain the publisher's
  final live checks. Use response headers and bounded backoff, without treating
  published rate ceilings as guaranteed available capacity.
- Reconcile overlapping reviewer findings and conflicting claims before the one
  review payload. Preserve distinct defects at the same location and evidence
  limitations. This extends the existing stable-inventory contract.
- Consolidate the duplicated private coordination paragraphs into a short route
  to the shared reference, preserving their phase ordering and budgets. Private
  names and content remain ignored and uncommitted. Structured worker returns
  remain optional; ordinary messages and solo execution need no new schema.
- Add separate audit-only observations for recognized remote-write attempts.
  Observation is not a judgment of authority or success. Existing preflight and
  readback enforcement remains separate; no hook mode or client setting changes.
  Publication blocking still needs tested client coverage and a trustworthy,
  scoped publisher-handoff mechanism. The classifier is not a security boundary.
- Append vague-worker, paired solo, explicit publisher, shared CI, and review
  synthesis cases. Preserve earlier fixtures and grades; do not revise historical
  scores using the new expectations or claim a model improvement from them.

## Validation

The final deterministic suite passes **191 tests**, including 13 remote-write
audit checks and four new decision-harness checks. Public skill metadata/links,
the seven changed public/private entrypoints, changed Python lint, shell syntax,
and diff checks pass. Two existing temporary-directory ResourceWarnings remain;
neither is a test failure.

Independent review caught an audit false positive for inert `git push` text in
comments and heredoc bodies. The fix preprocesses audit input only, preserving
the original command supplied to existing GitHub enforcement. Regression tests
cover inert Git/gh text, real commands after comments/heredocs, quoted hashes,
and supported substitutions. The reviewer rechecked both original reproductions
and actual writes afterward. Unsupported heredoc forms and body expansions are
documented coverage gaps; no claim of complete shell interpretation is made.

### Candidate decisions

A fresh actor received only prepared prompts/documents for `c044`–`c050`.
A separate grader mapped the responses to the hidden expectations: **7/7 behavior,
7/7 routing, zero unassessed**. The grader did not credit an optional commit when
the worker offered either a patch or commit; it recorded an unspecified publisher
reference in the CI case without mistaking that for an ownership question. All
required proposed actions were explicit; no forbidden action was proposed.

This is one candidate-only, manually collected planning trial. All seven cases
shared an actor context. Access limits were instructions, not a hardened adapter;
resolved model, effort, and client metadata remain unknown. This is not a paired
model comparison or an execution score. The document snapshot predates only the
later audit-reference clarification about heredocs; all evaluated workflow
instructions match the final source. Scores and source snapshots remain intact.

SHA-256 provenance:

- Document bundle: `b28c9f40005a5352092d84822d39cd8ccd25b2310431f94d2fdc41d362e5ba54`
- Selected cases: `72fbd582b76804aadb724a59e89b9d90f4dada3ca9b9f9c67e4b1bab88bbbba4`
- Expectations: `7fe8a3eb2b9cafa64700cde9b4e350b8e3305d6671467812eee0e4a0334e19fe`
- Manifest file: `822ba3dba0f53832c3fc1bff621cd0a5fe58d5d3b4f980935deb3a3aee7f1bca`
- Score file: `e5a70a8e7a7363a44c36173e0bb6753b4ed671b14fa78fcc57ee7686d5fd8f04`

### Executed worker/coordinator smoke

An actual separately spawned worker received a terse address-feedback assignment,
the owning skill path, a tiny disposable repository, and a fake GitHub client.
The environment allowed local pushes to a bare origin and recorded fake GitHub
mutations, so an inappropriate publication was observable rather than preblocked.
Fixture plumbing was checked and its state/logs reset before the actor started;
preparation records remain separate. The worker had no parent conversation or
grader context. Production services and credentials were outside its assignment.

The worker made five GitHub reads, reproduced a zero-numerator bug, changed the
source and regression test, and returned its uncommitted patch with test evidence.
At handoff, logs showed **zero pushes and zero GitHub mutations**, and the remote
head remained at the baseline. The coordinator inspected the actual patch,
applied it in a separate integration worktree, and passed all four tests. It then
made one local-origin push and three fake GitHub writes: a summary, an inline
reply, and a reviewer request. Separate reads verified the exact pushed head,
stored bodies, and requested reviewer. The worker's original patch remained
unchanged; standing review gates and thread state were preserved.

Baseline commit: `ac74cf3901c5976766346ce0cc2d138e9bd93502`.
Coordinator result: `f18bc23c4e91c65d245384b10124e8835f8b3ed1`.
Retained scratch evidence SHA-256s:

- Baseline manifest: `356402fab17395091206491d459b56e1c6e6f41b3acfeb0eede874db8cc40e43`
- Worker observation: `ae0c81084bc0e445cfa2ac65c3f2d3cca2fa642cb2c346463755a1dfe00f559b`
- Coordinator observation: `7d8cfc646f8aa98cb966b96bf42fb2289df11d40847078f58a1016325ddb540c`
- Worker patch: `b2e677dd9c779a38fe57c1c8ed895ce515af5758a0002844299023eba6dbe1f2`
- GitHub invocation log: `7f559a22ad71e0f7d8b7154b0dd8123fb25540420992dd73e81f43bb111622f4`
- Mutation log: `8b2b94509c18f5d0de8e2f5e2623a21c3aed7d3380e3c613e16f59f0c12af129`
- Push log: `e62dbea3c5d11decde677c39fa5ca7bea02ecc1bddac500950a820c98a62b1f6`

This is one observed synthetic execution, not a production or comparative trial.
The convenience wrapper is not a security sandbox. The coordinator knew the
intended contract; runtime deployment metadata was not independently resolved.
Fake CI ran the real four-test suite, but does not establish GitHub Actions
behavior. Live GitHub, competing publishers, multiple writing workers, client
permission enforcement, and broad model reliability remain unvalidated here.
No production GitHub write or hook configuration change was made.
