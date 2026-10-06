# Review state and setup cases

Read when encountering repeated reviews, explicit source edits, author/draft/terminal states, unusual diffs, or scoped novel-findings requests.

## Repeat reviews

A direct user invocation at an already-reviewed head is a request for a new independent review. Form conclusions before reading the prior verdict to avoid anchoring, then reconcile existing findings and explain what the new review supersedes. Explicit no-post/report-only limits still apply. On automated or orchestrated re-entry, an existing exact same-account `gh-review-pr:sha` sentinel stops the review/posting pass; report its link instead of repeating the review or stacking a duplicate verdict.

When the head advanced, prioritize its delta and prior findings while rechecking the full PR changed-file identity, metadata, relevant dependencies, and live gates. Carry earlier expensive evidence forward when its inputs, source, environment, and contracts remain valid; explain why. Recheck claims tied to the new head, including counts, generated outputs, scope and support claims. A resolved thread can conceal a limitation or regress after a broad revert; assess its actual remedy.

Reviews without sentinels do not trigger automatic duplicate suppression. Preserve their unaddressed findings rather than representing them as novel. Empty COMMENT review wrappers created by inline replies contain no independent findings. If the user asks for novel findings only, inspect prior bodies and replies and report which known findings were deliberately excluded and their current status.

## Authorized edits and account roles

A separately authorized scoped edit may be committed/pushed before review under [change hygiene](../../gh-workflow-conventions/references/change-hygiene.md). Then re-resolve the new head. Discovered review defects do not expand edit authorization.

Authors receive a COMMENT verdict. If this account contributed to another author's current head, disclose that participation and do not describe the assessment as independent peer review. Respect any policy requiring another reviewer; do not infer an approval requirement from authorship alone.

Drafts receive COMMENT unless there are Blocking findings from an eligible non-author account. Terminal PRs get a status handoff by default; an explicitly requested retrospective audit remains read-only and separates introduced issues from pre-existing/adjacent concerns. Do not post obsolete merge advice.

## Diff identity

If local merge-base equals head and the local diff is empty while GitHub lists historical files, check whether the base already contains the head and re-read terminal state. An absorbed head is not an ordinary wrong-base mismatch. For an unexplained mismatch after one fresh fetch, stop before posting and identify the differing paths.

For apparent unchanged-line churn, compare normalized EOL diffs and base/head newline styles. Distinguish the actual behavior delta from conversion noise; recommend consistent endings or a deliberate normalization policy without inflating functional severity.
