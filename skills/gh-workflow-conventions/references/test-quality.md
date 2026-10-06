# Proportionate Verification

Use when selecting checks or judging whether evidence supports a claim. Match the
verification to the changed contract, consequence, and existing evidence. A typo or
reversible prose edit does not need a new regression test. A regression, disputed
guard, or consequential behavior needs a check that could actually falsify it.

## Choose the claim, then the check

- Exercise the real user-facing path when practical. Test the observable contract,
  not a mirrored implementation or a substring that merely resembles it. Derive
  expected values independently where useful. A mocked collaborator proves its
  calling boundary, not that collaborator's behavior; honor repository test policy
  and use the smallest justified boundary double.
- Confirm the fixture enters the claimed path and has nondegenerate inputs. Equal
  axis lengths, single-element orderings, zero/identity terms, or truncated integer
  arrays can hide the exact defect being tested. Choose unequal/asymmetric values
  when alignment or composition matters. Equality of two empty extractions does
  not prove parity; assert the expected nonempty cohort first.
- Check changed producer/consumer boundaries, fast paths, caches, and relevant
  fallback/default combinations. Validate lifecycle transitions on a reused object
  when clearing or changing an option matters. Tests of only fresh instances may
  miss retained state.
- Reuse evidence whose source, environment, exercised behavior, and artifact are
  still applicable. Repeat affected checks after meaningful changes, conflicts, or
  uncertainty; do not rerun every experiment simply because a workflow changes or
  a new reviewer participates. Live GitHub gates retain their own freshness rules.
- Preserve a distinction between local, hosted, credentialed, and fixture evidence.
  An explicitly required hosted/UI execution remains unverified until performed
  or the user accepts a faithful surrogate. Paid/live reruns require appropriate
  authorization; old results cannot be relabeled as current-head execution.

## Guards and coverage

Add guards for recurring failure classes or stable relationships, not one-off
spelling fixes or exact prose. Keep expensive suites lean without removing behavior,
ordering, and boundary assertions. If test removal is claimed to preserve coverage,
compare relevant line identities and branch arcs under matched environments when
coverage tooling is available; equal totals alone cannot establish that claim.
Use durations before attributing parallel-suite wall-time changes to slower tests.
Structural/count checks introduced for extraction parity should say so; do not
present them as permanent scientific invariants that future model changes must obey.

For a regression fix, establish failure before the fix when feasible. Use targeted
[mutation testing](mutation-testing.md) when the deliverable is a guard, coverage is
disputed, or a plausible consequential defect could remain green. Choose informative
mutations for the claimed contract; do not require exhaustive per-hunk batteries
for every PR. Report the tested defect classes and remaining limits.

For a plan/schema-only deliverable, verify shipped schemas/tables and concrete test
contracts against the owning issue. Do not demand implementation tests outside
that scope or describe downstream executable tests as already delivered.

## Specialized checks

| Trigger | Reference |
|---|---|
| Scientific equations, units, optimization guarantees, benchmarks | [Scientific verification](scientific-verification.md) |
| Committed notebooks, outputs, execution provenance, stochastic samples | [Notebook artifacts](notebook-artifacts.md) |
| Generated tables, figures, documents, archives, rendered parity | [Artifact verification](artifact-verification.md) |
| Replacement dependencies, API compatibility, optional backends, CI test selection | [Dependency and API contracts](dependency-contracts.md) |
| A guard's sensitivity or disputed regression coverage | [Mutation testing](mutation-testing.md) |

A check that fails during setup/collection is not automatically a behavioral
failure; use [environment guidance](test-environment.md). For optional diagnostic
sidecars after a successful expensive operation, verify absent/malformed metadata
preserves the usable result unless the public contract makes that metadata required.
