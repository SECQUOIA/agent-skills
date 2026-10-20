# Workload-based resource guidance

The user requested refinements after comparing Codex and Claude assessments of
model selection, reasoning effort, and optional delegation. The user's habitual
high effort was explicitly described as arbitrary, not a required minimum. This
change adds portable starting recommendations, without changing client settings.

Pre-change personal tip: `a790dee57243ce09585f57e8fce22abd288a9222`.
Pinned upstream: `26fc0c643f51efadb874b9f84737bd61cd56f711`.
Synchronization left both unchanged and preserved all 13 unique local commits.
The pre-change tip is retained at `backup/sync-resource-guidance-a790dee`.

## Dispositions

- Add a conditional resource-allocation reference owned by shared conventions.
  Its public-workflow table and composed-workflow guidance use workload tiers,
  with concrete model/effort candidates confined to a dated client mapping.
  Ordinary solo execution gains no required helper, coordination log, or approval.
- Allocate reasoning to difficult judgments, including selecting and interpreting
  verification. Successful checks do not establish that the chosen checks were
  adequate. Repeated failure calls for examining the approach and environment,
  not automatically requesting ever-higher effort.
- Treat current settings, helper counts, and workflow rows as starting hypotheses.
  Preserve explicit user choices; do not encode a universal effort floor, model
  ban, or assumption that the coordinator and every helper need the same depth.
- Use a starting concurrency budget of zero to two helpers for the whole task,
  including nested descendants. Expansion needs identified independent work and
  available runtime capacity. This is a recommendation, not an experimentally
  established optimum or a new platform maximum.
- Preserve independent implementation in isolated worktrees, explicit worker
  publication handoffs, all verification, and each existing budget's scope and
  stopping rule. Concurrency, review rounds, verification passes, CI attempts,
  and rate limits remain distinct; invocation/re-entry does not replenish them.
- Distinguish requested settings, client-reported values, and missing metadata.
  Unknown effort alone does not invalidate evidence. Supported fallbacks remain
  subject to explicit user constraints. Skills do not edit saved settings or
  install client-specific helper definitions as a workflow side effect.
- Extend the lessons skill's evidence guidance for controlled resource comparisons:
  fixed-model solo effort arms first, helper factors separately, absolute quality
  criteria, false findings and rework as well as recall, and usage across agents.
  Small samples and zero observed failures do not establish non-inferiority.
- Existing public entrypoints already load shared conventions. The lessons skill
  receives a direct conditional route; the delegation reference points to the
  resource guide. Private consumers already load the core and delegation contract,
  so their sources and phase/budget rules need no duplicated allocation paragraph.

No existing substantive rule was removed. Discovery metadata, publication scopes,
hook behavior, client configuration, and historical evaluation records are unchanged.

## Evidence boundaries

Official model and client references are linked from the dated mapping, reviewed
2026-10-07. They document capabilities and directional advice; the workflow table
is a recommendation, not a vendor benchmark or measured SECQUOIA reliability floor.
Anthropic's effort examples and pooled benchmark categories do not establish the
benefit of one adjacent effort level for these workflows or for another vendor.

Earlier Claude decision harnesses omitted an effort flag and excluded settings
files, but inherited an environment that was not preserved. Their saved results
discarded initialization events. The reported default effort therefore remains
inferred/unconfirmed. Their passing plans are not executed workflow outcomes or
controlled comparisons of effort. The inspected client can optionally report
effort in initialization metadata; a missing field remains unknown, and such a
report does not independently establish every API turn's applied setting.

The encounter ledger was inspected before editing. Its legacy attribution and
unresolved-target limitations prevent deriving an effort recommendation from
its raw counts. No new recurrence or causal model-performance claim is made.

## Validation

- Public metadata and local documentation links pass; both changed skill
  entrypoints pass the skill-creator validator.
- The existing deterministic suite passes 191 tests. Two existing temporary-
  directory ResourceWarnings remain; neither is a test failure. No executable
  behavior changed, and no wording-matching tests were added.
- Installed roots for both clients resolve all 13 public and three private skill
  entrypoints to canonical sources. Private content stays ignored and unchanged.
- An independent reviewer checked all public routes, three private consumers,
  official client claims, and static walkthroughs for solo work, a scientific
  review/fix/verify loop, nested budgets, and unavailable effort controls. It
  caught an ambiguity about a configured Codex default effort; the wording now
  specifies that neither the spawn nor agent defaults supplies an effort before
  falling back to the model default. Targeted re-review found no remaining issue.
  These walkthroughs are document review, not executed workflow trials.

No comparative model/effort trial, paid experiment batch, or live workflow was
run for this change. Deterministic validation and document review do not prove
the allocation recommendations improve task outcomes.
