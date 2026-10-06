# Publish a resolution batch

Read only when summary/reply publication is authorized. Apply shared [GitHub write rules](../../gh-workflow-conventions/references/github-writes.md) before each write.

Refresh review threads, bodies and discussion targets before claiming completeness. New actionable feedback requires triage; do not silently exclude it. Record the actual PR head and a deterministic batch digest of sorted target IDs/finding markers plus the normalized summary body before its marker.

Use:

- Summary: `<!-- gh-arc:sha=<HEAD_SHA>:batch=<BATCH_ID>:target=summary -->`
- Inline reply: `<!-- gh-arc:sha=<HEAD_SHA>:comment=<COMMENT_ID> -->`
- New feedback on an already marked same-head target: `<!-- gh-arc:sha=<HEAD_SHA>:batch=<BATCH_ID>:comment=<COMMENT_ID> -->`

Read existing top-level/review comments before posting and skip exact marker matches. A prior unmarked reply is evidence, not marker-based idempotency. A previously handled target needs no repeated identical reply when its marker is current and no newer feedback arrived. A same-head metadata/deferral cycle can still need a new batch summary. For genuinely new feedback on an already marked same-head target, use the exact batch-qualified reply marker above so the old marker cannot suppress a new disposition.

Post one new summary per distinct batch; never rewrite prior summaries, replies, or PR metadata without explicit authorization. Link superseded text when useful. Include fixing commits, changes, validation/current CI, target-specific dispositions, and outstanding risks/gates. Cover body-only findings by stable marker/title instead of inventing inline targets. Lead with declined Blocking items and the required human decision.

Reply to each targeted inline comment via `gh api repos/{owner}/{repo}/pulls/{number}/comments/{comment_id}/replies -F body=@<file>`. The numeric ID and pull number are required; lowercase `-f` would send the filename literally. State the disposition and evidence, attribute the actual fixing commit, and explain basis-changing relabels rather than just repeating a new label. Capture each returned ID and verify its stored body/marker before the next write. Ambiguous outcomes require readback before retry; report definitive failures. Never mark threads resolved here.

After verified publication, re-request eligible human reviewers whose actionable targets this batch fully resolved. Exclude author, authenticated account, bots, informational/declined/partial-only reviewers, and existing reviewRequests. An exact no-op rerun does not re-request. Re-read open state/head/current requests, use the shared review-request procedure, and verify intended logins appear. Report permission failures or fallback comments distinctly from formal requests; reviewDecision is not proof of a request.

Re-read formal review and merge gates for the final handoff. Replies and passing checks do not clear another reviewer's CHANGES_REQUESTED.
