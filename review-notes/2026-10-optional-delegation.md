# Optional delegation while preserving solo workflows

The user requested multiagent readiness without losing single-agent usability.
The preceding review found a sound parent/helper authority boundary but incomplete
assignment, integration, and recovery contracts. This change starts from
`38edfac` and preserves that commit's review-exception fixes and prior history.

## Design decisions

- Keep the same 13 public skills and their completion criteria. A component skill
  can run in one agent; invoking it does not require spawning another agent.
- Put substantial coordination detail in one conditional
  [delegation reference](../skills/gh-workflow-conventions/references/delegation.md),
  routed before delegation, writes, concurrent editing, and managed-skill changes.
- Bound children by their assigned task even when they load a full workflow.
  Prepared findings or patches are not verified publication or phase completion.
- Keep one integration owner and one publisher per target/surface. Nested helpers
  do not acquire ownership automatically; independent sessions need an acknowledged
  handoff. Existing duplicate markers remain useful but are not atomic claims.
- Prefer isolated writers. An intentionally shared checkout requires disjoint
  paths and one index/branch/commit owner. Also own or serialize mutable package
  environments, generated outputs, and other shared resources.
- Require compact, relevant handoffs tied to source, changes, checks and pending
  actions. Preserve valid evidence; check the combined behavior where changes
  interact rather than rerunning every component test merely because it came
  from another agent.
- Preserve partial work and require actual worker/command quiescence before
  workspace reassignment or cleanup. Reconcile dispatched writes through readback.
  Propagate changed user scope and inspect late results against current inputs.
- Use existing task history or a task-owned checkpoint only when delegated
  continuation needs it. Preserve cumulative budgets. Ordinary solo execution
  needs neither worker records nor an orchestration service.

Authorized private consumers use the same conditional contract and preserve their
solo phase ordering, review gates, and scope. Their names and contents remain
outside tracked history. No client invocation policy, hook mode, model choice,
or live GitHub state is changed by this update.

## Validation scope

The evaluation additions exercise solo fallback, bounded child authority,
resource ownership, integration, changed source, cancellation, nested delegation,
and competing publishers. Raw observations stay separate from grader expectations.
Disposable Git fixtures exercise actual concurrent workers and a sequential path;
these scripted checks validate fixtures and observable Git outcomes, not model
performance or a production scheduler. The existing fake-GitHub publication
fixture remains limited to one writer.

This is an instruction contract with regression evidence, not an atomic locking
system. Uncoordinated writers on the same branch or external target are outside
the supported workflow. Comparative live trials across clients and models remain
separate work; passing a harness does not establish those results.

The full deterministic suite passes **174 tests**, including five new concurrent
Git fixture checks and a rubric regression that accepts solo, isolated-worker,
and coordinated shared-checkout plans while rejecting uncoordinated mutation.
Public metadata/links, all 16 shared/local skill entrypoints, the local consumer
interface check, changed Python lint, shell syntax, and diff checks pass.

Independent review resolved two contract ambiguities (coordinated shared
checkouts and nested ownership) and two evaluation issues. The grading now accepts
the shared-checkout mode the contract permits. The cancellation fixture performs
and preserves an actual write after the cancellation request, rather than merely
observing a waiting thread. Solo and parallel paths produce identical final trees;
the user checkout and both conflicting worker results remain preserved.

## Candidate decision check

An actor given only the prepared prompts and allowed skill documents produced
plans for `c034`–`c043`. A separate reviewer mapped the actual steps to the hidden
rubrics. The preserved score is **10/10 behavior, 9/10 routing, zero unassessed**.
The routing mismatch is `c039`: its original worker-replacement request supplied
no PR/review context, while the grader required `gh-address-review-comments`.
The actor selected shared coordination guidance and proposed the required safe
cancellation and replacement behavior. The current case adds the earlier user
request identifying that review workflow; the original score was not changed,
and this revised scenario has not received another model trial. Removing that
new observation reconstructs the original case used in this check.

These are annotated proposed decisions, not executed GitHub workflows. The grader
also noted that one passing solo case ordered its link check before publication
without explicitly spelling out successful checking as a gate. That limits what
the mapped score establishes. All ten cases shared one actor context; resource
access was constrained by instructions, not a hardened sandbox. Runtime deployment,
reasoning effort, and client metadata remain unknown. Collection was manual, with
separate grading context and no comparative model trial.

An earlier preparation was interrupted before completion while fixture grading
was finalized. It remains unscored; the final preparation used identical prompts
and documents and the corrected ownership rubric. No response or score from a
completed historical trial was overwritten.

Provenance (SHA-256):

- Document bundle: `abcbe3212ed47e9d75bd5f307a49698771beee975ec01952ad701b4a6fb9046f`
- Original selected cases: `175ea40d8b622bdcab25b8278b97022656c83a6bbcabdf10906d48af5168496a`
- Selected expectations: `0d933d06570667554be6b753a9ed573ad1a1176b1fd34c4edf257518170ed064`
- Manifest file: `addf2628c4b83609b0172ae5421535ddd16795c7f87551f06808d20fc3182299`
- Original score file: `707ae72fafacce635a0426e1ea294c4619776c9edc2479559e9479c13fb0a57f`
