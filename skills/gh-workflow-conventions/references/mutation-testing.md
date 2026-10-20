# Targeted Mutation and Guard Verification

Use when a PR delivers a regression guard, a coverage claim is disputed, or a
consequential defect could plausibly escape existing tests. Select mutations to
answer that question; this is not a mandatory exhaustive test battery.

## Trustworthy harness

1. Preserve a byte-identical baseline of the candidate, including uncommitted work,
   outside the probe directory. Prefer a fresh disposable copy per mutation. Never
   restore candidate edits with `git checkout HEAD -- <file>` or `reset --hard`.
2. Run the unmutated candidate through the same harness and require the expected
   baseline outcome. Verify source/import/native identity, cwd, dependencies, and
   subprocess environment using [worktree guidance](worktrees-and-checkouts.md).
3. Apply a narrow mutation; assert its anchor matched and reread the altered source.
   Preserve line endings. Uniform green results may mean the edit never landed;
   uniform red results may mean the harness failed before reaching the tests.
4. Read the actual failure. Setup/collection errors, unrelated diagnostics, and
   downstream symptoms swallowed by broad exception handlers do not establish
   the intended guard. Parse real test result markers, not a bare `error` substring.
5. Restore from the baseline or discard the copy. Verify restored bytes before any
   reuse. Report the mutation, expected failure, and actual targeted outcome in
   plain language; label filtered cohorts and their counts accurately.

## Choose discriminating cases

- Red-on-base establishes the old bug is detected. When the new contract is broader,
  probe the particular untested distinction: identity/order versus count/shape,
  a missing entry versus a wrong entry, or composition versus isolated terms.
- Use at least two unequal elements for alignment/order, nonzero nonidentity terms
  for composition, and asymmetric shapes/values for transpose mistakes. For sparse
  formats, distinguish declared size from inferred nonzero support.
- Structured-field guards must bind values to the intended field. Retain the right
  token in another field while corrupting the target. Source guards must distinguish
  executable statements from strings, comments, logging, and dead declarations.
  Prefer parsing or behavior over broad substring checks.
- Inventory guards must enumerate the same representations as production, with a
  known nonempty cohort. Test a relevant missing record and a legitimate negative;
  narrowing a classifier without narrowing discovery can reject valid future data.
- A predicate such as “contains L1” may leave several wrong values indistinguishable.
  Assert complete expected states where the contract needs them. A widened tolerance
  cannot prove a consumer is absent: change the value in the direction that should
  cause the claimed consumer to fail.
- For chunking, fallbacks, or independent features, choose a probe for each material
  defect class actually claimed by the deliverable. There is no universal requirement
  to revert every changed hunk or independently repeat another agent's adequate,
  reproducible evidence. Inspect evidence quality before deciding to repeat it.
- When the question is what a new guard uniquely adds, compare the same relevant
  failure with and without that guard. Otherwise baseline duplication analysis is
  optional, not another automatic full-suite run.

A test calling a local mirror of production cannot detect removal of the real
call site. Exercise the real path with necessary heavy collaborators stubbed, or
state the limited helper contract. A probe replacing the production solver,
framework dispatch, or retry strategy tests its substitute; reject conclusions
that fail on known-valid controls. For file input/output identity contracts, include
symlink/hardlink aliases if input destruction is the risk, with bytes-preservation
and distinct-output controls.

Keep failure output bounded: single-line notebooks can turn one grep hit or string
assertion into megabytes. Prefer filename-only matches and concise diagnostics
without discarding the failure summary.
