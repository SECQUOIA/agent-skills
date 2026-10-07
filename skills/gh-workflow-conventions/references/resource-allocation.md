# Allocate models, reasoning, and helpers

Read when choosing resources for a workflow or assignment. These are starting
recommendations, not measured reliability floors. Honor explicit user choices at
their stated scope, including solo execution. An existing setting or past habit
does not establish an optimal setting or a minimum for every helper.

## Allocate by the work

Use ordinary depth for bounded retrieval and procedures with clear inputs and
well-understood checks. Use substantive depth for debugging, technical review,
design choices, scientific claims, and deciding whether evidence is adequate.
Consider exceptional depth for unresolved numerical, security, concurrency, or
other difficult correctness questions; compare its benefit before making it a
default. A consequential write alone does not require maximum reasoning.

Tests and live reads still require judgment: selecting an inadequate test or
misreading a gate can produce a wrong result despite successful checks. Spend
reasoning on that uncertainty as well as on implementation. Higher effort never
replaces required evidence; lower effort never permits skipping checks or joining
separate preflight, write, and readback phases. Reassess the approach, evidence,
and environment after repeated failure rather than only increasing effort.

Read the dated [client mapping](runtime-settings.md) only when selecting concrete
settings or resolving what the client can apply. Use supported controls for an
authorized helper selection. Skill prose cannot change the primary's runtime
setting. If a different primary setting would materially help, recommend it once
and continue useful work with the available setting. Do not change saved settings
as a side effect of a workflow; an explicit configuration request is separate.

## Workflow starting points

Apply the row to the actual phase: a simple item within a complex workflow may
need ordinary depth, while difficult verification in a procedural skill may need
substantive depth. Helpers count concurrently, excluding the primary. These
examples permit delegation; they do not require it or expand the skill's scope.

| Workflow | Starting depth and escalation | Optional helper contribution |
|---|---|---|
| `explain-pr-to-me` | Ordinary; substantive for complex technical explanations | 0 normally; 1 for a long history or separate subsystem |
| `gh-pages-deployment` | Ordinary; substantive for ambiguous hosting, rendering, or security behavior | 0 normally; 1–2 for independent host/build/rendered evidence |
| `gh-merge-pr`, `gh-julia-release` | Ordinary gates; substantive for approval deltas, provenance, or distribution decisions | 0 normally; 1 for an independent artifact or install check |
| `sync-secquoia-skills`, `submit-learnings` | Ordinary; preserve the existing conflict/stop procedure | 0 normally; serialize shared Git operations |
| `apply-conversation-lessons` | Ordinary for a narrow correction; substantive for policy edits or compression | 0 normally; 1 for a consequential invariant/consumer audit |
| `gh-issue-to-pr` | Ordinary for clear-scope features; substantive for bugs, design, or scientific code | 0 normally; 1–2 for independent components, reproductions, or checks |
| `gh-address-review-comments` | Ordinary for straightforward feedback; substantive for correctness disputes | 0 normally; 1–2 for disjoint fixes with isolated resources |
| `gh-triage-issue` | Substantive reproduction and diagnosis | 0 normally; 1 for an independent reproduction or competing diagnosis |
| `gh-verify-review-resolution` | Ordinary for simple items; substantive for partial fixes or cross-cutting/scientific claims | 0 normally; 1–2 for independent item groups |
| `gh-review-pr` | Substantive; exceptional is a candidate for difficult security/scientific defects | 0 for small changes; 1–2 for independent domains on a large PR |
| `gh-workflow-conventions` | Inherit the invoking task; this is a reference | No additional helpers just to load policy |

For composed or long-running workflows, allocate by phase and retain one overall
concurrency budget. If the client cannot change effort by phase, choose a setting
suited to the hardest material judgment; a long run alone does not demand the
strongest model or maximum effort. Component calls do not create fresh budgets.

## Bound optional delegation

Prefer solo execution for short or tightly coupled work. Helpers can supply
parallelism, context isolation, or independent scrutiny; quality improvements are
hypotheses to evaluate. Give each a separable contribution whose evidence or patch
the coordinator can assess under the [delegation contract](delegation.md).
Independent implementation remains supported with isolated mutable resources.
An evidence collector may use ordinary depth; interpreting disputed evidence or
designing a reproduction can warrant substantive depth regardless of its role.

As a starting budget, use 0–2 concurrent helpers across the entire task, including
nested descendants. Expand only for identified independent work with a clear
benefit, within explicit user limits and available runtime capacity. Available
slots also account for other active descendants; no worker gets a fresh allowance.
Keep concurrency separate from review rounds, verification passes, CI-fix attempts,
and rate-limit budgets. Preserve each owning skill's scope, counter, and stop rule
across phases and re-entry. Resource choices do not alter publisher handoffs.

When a selection or comparison depends on model/effort, distinguish requested
settings from client-reported settings and unavailable metadata. Within explicit
user constraints, inherit or use a compatible setting if an override cannot be
applied; disclose a material substitution or an unmet explicit request. Unknown
effort alone does not invalidate sound evidence or require moving all work to the
primary. Record relevant metadata
in the existing handoff or evaluation record; ordinary solo work needs no new log.
Apply the same authority rules across models, without permanent model-name bans.

For comparative trials, use the lessons skill's
[resource evaluation guidance](../../apply-conversation-lessons/references/evidence.md#resource-allocation-comparisons).
Do not treat a small passing sample as proof of a safe minimum or a quality gain.
