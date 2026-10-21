---
name: apply-conversation-lessons
description: Fold conversation takeaways or lessons into existing skills when requested. Use for durable workflow improvements; does not run automatically or submit accumulated changes.
---

# Apply Conversation Lessons

Capture reusable lessons when requested. A successful pass may conclude that no
skill change is warranted. Consider every skill used, including this one, but
change only the smallest appropriate owner.

## Decide what earns a change

1. Combine the user's requested changes with evidence from the conversation.
   Re-read the current target before drawing conclusions from an earlier version.
2. For a mature shared skill, require an explicit request for the durable change,
   a missing safeguard against destructive action/security exposure/incorrect
   external writes, or the same failure in at least three independent episodes
   under the relevant rule version. Retries and agent switches on one task are
   one episode. Recurrence makes an edit eligible, not mandatory.
3. When the encounter runner is available, inspect
   `python -B <skill>/scripts/encounter_ledger.py report --json` before triage.
   Use [evidence guidance](references/evidence.md) to interpret its revisions,
   modes, and model attribution. Do not equate classifier flags with model errors.
   If a helper returns `ENOENT` despite being readable through another tool,
   inspect its symlink destination and the executing sandbox's filesystem
   visibility before declaring it missing. Resolve the path with `readlink -f`
   where available; execution outside permitted roots requires supported,
   authorized filesystem access, which may involve Antigravity's
   `BypassSandbox: true` when allowed by the active runtime. If that access is
   unavailable, report the helper as inaccessible and continue triage using
   available evidence.
4. Keep lessons that prevent plausible wrong results, silent damage, or repeated
   expensive rediscovery. Retire one-off facts, obvious recoverable command errors,
   generic advice, and preferences already supplied by higher-level instructions.
5. Search for an existing rule and its history. Distinguish an execution miss from
   a lesson already captured after the event. Clarify or relocate an ambiguous or
   poorly placed rule; do not append a synonym. Shared rules belong with their
   shared owner. Prefer a distributable executable guard for deterministic checks
   when its implementation is within the user's authorized scope.

## Edit and validate

- Read available skill-creator guidance. Resolve installed symlinks and read each
  file at the path to be edited; use bounded chunks if output truncates.
- When choosing models, effort, or helpers, use shared
  [resource allocation](../gh-workflow-conventions/references/resource-allocation.md).
- Before editing a managed/shared repository, follow
  [managed changes](references/managed-changes.md). Keep user-owned customizations
  out of plugin caches unless the user specifically requested a cache edit.
- Keep discovery descriptions short and precise. Put policy, outcomes, and routing
  in the core; put substantial conditional detail in references. Do not wait for
  a tool's output limit before reducing unnecessary context.
- Preserve non-obvious invariants. Account for removed substantive rules as
  consolidated, relocated, or deliberately retired with reasons. Check that
  callers reach relocated rules before the action they govern. Independent
  verification at a handoff can remain necessary even when its wording is shared.
  Record consequential dispositions and validation limits in the commit body or
  a tracked review note; a temporary audit alone is not durable review evidence.
- Update affected consumers, including authorized private orchestrators, when
  contracts change. Keep private skill names and contents outside tracked files.
  Keep shared instructions agent-neutral and frontmatter compatible with both
  consumers; place client-specific metadata in its supported sidecar/configuration.
- Validate each changed skill using the available skill-creator validator with
  absolute paths and a dependency-equipped interpreter. Missing tooling is a
  validation limitation, not proof of invalid content. Check relative links and
  relevant sidecar/catalog/install surfaces; run changed executable helpers.
- For substantial routing or permission changes, use realistic behavioral cases,
  including requests that must not activate the workflow. For model upgrades,
  compare against the previous skill and a policy-equivalent minimal baseline;
  see [evidence guidance](references/evidence.md). Do not infer better behavior
  from smaller files or passing metadata validation alone.

## Handoff

Report implemented and declined lessons, changed skills, validation, and remaining
limitations. State whether this skill changed and why. For managed skills, report
the personal branch and local commits; submission is a separate user-initiated
workflow.
