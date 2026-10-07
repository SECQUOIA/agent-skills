# Follow-up review of resource allocation

The user authorized fixes from Claude's review where supported. The reviewed
baseline is `fee5b3795294d301646586b11361b0f86d53c101`. Synchronization against
unchanged upstream `26fc0c643f51efadb874b9f84737bd61cd56f711` preserved all 14 local
commits. Backup: `backup/sync-resource-followup-fee5b37`.

## Findings and dispositions

- **M1, billing:** make existing billing authorization and task budgets explicit.
  New billing or separately billed usage needs authorization covering it; existing
  approval remains valid. An optional override with unknown billing retains the
  existing authorized setting. Do not introduce approval for every ordinary model
  selection or token-use variation. Claude's documented headless/SDK billing
  behavior makes relying on an interactive consent prompt inadequate.
- **M2, nested helpers:** add an explicit additional-helper allowance to assignments,
  defaulting to zero. The coordinator reserves nonoverlapping capacity from one
  task budget; workers cannot create a new allowance from spare platform slots.
  Count live helpers and unused reservations before allocating, and release unused
  capacity before reassigning it. The separate review/verification/CI budgets and
  existing publication handoffs are unchanged. These are coordination instructions,
  not a platform-enforced semaphore or demonstrated scheduling guarantee.
- **L1, Claude effort:** describe omitted helper effort as an inference from the
  documented override behavior, not a confirmed value for a different model.
  Unreported helper effort remains unknown.
- **L2, Codex forks:** attribute fork inheritance and observed slot counts to the
  active runtime contract, not the public subagent page. Recheck the executing
  runtime rather than treating observed capacity as a portable default.
- **L3, compatibility:** document current Claude model-version requirements and
  distinguish the actual executing client/provider from a terminal binary on PATH.
  No client upgrade or configuration change is performed by a skill invocation.
- **L4, exceptional work:** clarify that this describes task difficulty, not an
  automatic effort increase. Retain the current candidate pending comparison;
  identify stronger effort or Fable as options within availability and billing
  authorization. No claim of a measured improvement is made.
- **L5, solo and primary:** trigger allocation guidance before adding helpers or
  recommending changed settings. Condition a specific primary recommendation on
  knowing its setting; otherwise advice stays conditional. Existing solo execution
  gains no settings check, report, or approval ritual.
- **L6, evaluation provenance:** add effort-source metadata and a separate requested
  effort field to both harnesses, preserving differing requested and reported values.
  Labels remain operator-supplied; the harness does not establish that a client or
  API actually applied them. Existing trials are not backfilled or reinterpreted.

The optional approximate statistical bound was not added. The existing warning
about small samples remains appropriate; a numerical bound would require explicit
sampling assumptions and does not establish reliability across different tasks.
Nor was the proposed restriction to overrides only for a different workload added:
an override can be justified by availability or evidence on the same workload.

## Correction to the previous review note

The prior note's runtime-aware wording described an intended coordination rule,
not tested enforcement. Explicit nested allowances were missing. Its statement
that official controls were checked also did not identify the fork rule's actual
source: runtime instructions. This follow-up supplies those missing distinctions;
the earlier note and historical evaluation results remain intact.

## Validation and limits

An independent document review found no remaining issue in the four policy files.
It checked public/private reachability, official product claims, and static cases
for two helpers exhausting a two-helper budget, capacity returning after completion,
authorized metered use, new optional billing, solo work, and unknown primary settings.
No private source or client configuration was changed. Public metadata/links and
the conventions entrypoint validator pass.

The final frozen source passes all **199 deterministic tests**, including eight
new effort-provenance regression tests. They cover differing requested/reported
values, unknown/default and legacy fields, both CLI/API paths, and invalid labels
rejected before an adapter runs or artifacts change. An independent code reviewer
also ran the 38-test harness suite and script/module entrypoints; it found no
remaining issue. Python lint, shell syntax, and diff checks pass. Two existing
TemporaryDirectory ResourceWarnings remain, without test failures.

The provenance change is additive: current trial format versions remain usable,
old missing/null fields stay missing/null when scored, and no historical trial is
relabeled. The flags are metadata inputs, not automatic runtime collectors or
client-setting controls. Final integration checks are recorded with the commits.

No paid model batch, comparative effort experiment, live workflow, automatic billing
probe, or actual nested-spawn test was run. Static walkthroughs and harness tests
do not prove model adherence, platform enforcement, or an optimal resource policy.
