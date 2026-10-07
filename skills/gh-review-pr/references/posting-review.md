# Posting a maintainer review

Read after the technical inventory is complete, before a review write. Apply the shared [GitHub write rules](../../gh-workflow-conventions/references/github-writes.md).

## Live state and ownership

Re-read PR state, head, current account, existing reviews, and relevant merge gates. If head moved, assess the delta before selecting a new reviewed SHA. If the PR merged/closed during review, report the race and adapt to a retrospective assessment rather than posting stale “before merge” advice. A retrospective review requires the user's requested scope.

A `PENDING` review authored by the current account may be a human's draft or another session's work. Preserve it unless an operation log identifies that exact review ID as created by this operation. Only that provenance permits cleanup of an abandoned pending artifact. Account, head, timestamp proximity, or similar content alone are insufficient. If an unrelated draft prevents atomic posting, report the precise conflict; do not delete or submit it.

Use `<!-- gh-review-pr:sha=<HEAD_SHA> -->` in the body. An exact existing sentinel by this account stops automated duplicate posting. A direct user re-review or explicitly requested same-head verdict change permits a new review; link the review it supersedes and retain the sentinel. Consult [review state](review-state-edge-cases.md) for repeated/terminal cases. Each body-only finding needs its own unique `<!-- gh-review-pr:finding=<slug> -->` marker.

## Construct one review

When multiple helpers contribute, reconcile their findings into one inventory
before choosing the verdict. Merge reports of the same defect, retain distinct
defects even at the same location, and resolve conflicting severity or remedy
claims against the reviewed source and evidence. Preserve each finding's evidence
and limitations; derive counts and stable markers from the reconciled inventory.
Helpers return findings to the designated publisher rather than posting separately.

Build one JSON object with a serializer: `commit_id`, `event`, `body`, and `comments` (empty for a body-only review). Submit with `gh api repos/{owner}/{repo}/pulls/{number}/reviews --method POST --input <json-file>`.

Validate every inline path/line/side against the exact hunks GitHub exposes, not simply an existing head line or a non-null patch. Use a nearby changed line and identify the actual location in prose when needed. Put binary/large-file findings with no exposed hunk into the marked review body. Never nest fences inside a suggestion block.

Where required conversation resolution would create gates an automated workflow cannot clear, prefer marked body findings unless the user will resolve inline threads. Preserve actionable content and explain that presentation choice briefly. Derive all severity totals from the same inventory, separating inline and body subtotals.

Choose the event in this order:

1. PR author: `COMMENT`; GitHub rejects the author's APPROVE/REQUEST_CHANGES.
2. Blocking findings: `REQUEST_CHANGES`.
3. Draft or not otherwise merge-ready: `COMMENT` with the actionable gate.
4. No blocking findings and verified merge readiness: `APPROVE`.

A COMMENT does not withdraw an earlier decision-bearing review. If the user explicitly requests withdrawal of this account's approval without a Blocking finding, submit the superseding explanation and dismiss that approval through the review dismissals endpoint. Verify the old review is DISMISSED and the resulting aggregate decision; another reviewer's approval may still keep it APPROVED. Do not invent a blocker to change the event.

## Verify or recover

Capture the submitted ID and re-read that exact review, its commit, event/state, body, and inline comments. Use GraphQL thread locations to inspect posted anchors; REST null line/side fields alone do not prove an invalid anchor. Re-read current reviewDecision, merge state, and policy before claiming approval cleared a gate. Newly created threads may themselves require resolution.

A definite `Line could not be resolved` rejection permits one corrected retry only after confirming no artifact was created, fixing anchors, and repeating live head/state/sentinel checks. For any ambiguous outcome, read back before retrying under the shared rule. For other definite rejection or a second failure, stop and report the exact error.

Do not modify or delete submitted review history. Report review link/ID, reviewed SHA, outcome and evidence, material limitations, and remaining gates. Keep account/tool mechanics in chat unless a maintainer must act on them.
