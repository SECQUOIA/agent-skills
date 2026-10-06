# Explicitly requested verification closeout

Read only after the complete assessment when the user authorized a specific write. Apply shared [GitHub write rules](../../gh-workflow-conventions/references/github-writes.md). A recommendation or automated invocation does not authorize closeout.

Supported actions are a new assessment comment, one outcome review, resolution of threads just classified Addressed, and marking an open draft ready. Perform only the named actions; no merge, source fix, push, CI trigger/re-run/cancel, or unrelated metadata edit follows implicitly. Re-read exact targets, state, and head before and after every write. If head changed, refresh affected assessments before writing.

For a requested comment, use a top-level discussion comment and distinguish the content assessment from the recorded review verdict. Name every remaining body-only finding: resolving inline threads does not settle findings that have no thread. Do not replace or delete earlier comments.

For an outcome review, follow [review posting](../../gh-review-pr/references/posting-review.md), including serialized atomic payload, sentinel/idempotency, provenance-based pending-review protection, and exact stored-state readback. Explicit approval/outcome requests permit a new decision at an already reviewed head; automated retries do not. A pre-existing PENDING review is never disposable merely because the authenticated account owns it.

Use APPROVE only when every inventoried item is Addressed at the unchanged head, no new defect surfaced, the PR is ready under live gates, and the account is not the author. Use COMMENT otherwise; do not issue REQUEST_CHANGES or smuggle new findings into this outcome review. Recommend `gh-review-pr` for new reviewer judgment. Do not duplicate the same outcome in a discussion comment unless the user requests both surfaces. Re-read reviewDecision afterward; the posted state alone does not prove all gates cleared.

Resolve only verified Addressed threads without newer disagreement, never Partially addressed, Not addressed, or declined Blocking items. Use the shared bulk-thread procedure and verify every target. Report any remaining body findings separately even when there are no unresolved threads. After marking ready, inspect fresh workflows triggered by readiness and report their actual state.

If all content is addressed but CHANGES_REQUESTED remains, identify the reviewer whose decision remains and the re-review/dismissal needed. An eligible outcome review from that same account may update its verdict; another account's approval does not erase it. For the author account, a requested affirming comment can record evidence, but cannot serve as formal approval.
