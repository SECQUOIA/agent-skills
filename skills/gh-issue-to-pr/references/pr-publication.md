# Publish an implementation PR

Read before committing/pushing/opening or updating the implementation record. Apply shared [change hygiene](../../gh-workflow-conventions/references/change-hygiene.md) and [GitHub write rules](../../gh-workflow-conventions/references/github-writes.md).

Match observed commit conventions and inspect the staged tree, including relevant ignored generated state. Recheck duplicate/concurrent PR state immediately before push. Continue existing PRs without silently rewriting title/body/history; post a new current-state comment marked `<!-- gh-issue-to-pr:head=<HEAD_SHA> -->` when the implementation makes narrative stale, and skip an exact rerun.

For a new PR, use the actual repository template and create it draft. Preserve mandatory legal/DCO/AI-disclosure blocks and answer them honestly; never check a human-review acknowledgment on a human's behalf. Tailor optional sections to the change instead of adding empty boilerplate. If a changelog needs the PR number, open the verified draft first and append a normal follow-up commit; do not amend pushed history.

Describe the problem, resulting behavior, scope, validation and material limits. Include branch/base/stack details when relevant, linked triage and covered criteria, and concrete dependency/follow-up relationships. Use Closes for fully resolved issues, Refs for partial work with unmet criteria and closure path; state that non-default-base integration may defer automatic closure. A replacement PR should say Supersedes and explain any deliberate behavioral/artifact differences.

For intentionally unexecuted notebooks, state the reason and actual validation. For private/canonical inputs, label pinned aggregate evidence and identify a shareable revision or approved artifact ID; do not claim a public golden check independently recomputes private results. Protect the underlying private source.

After posting, verify exact stored content and links. Author-side COMMENT reviews cannot formally approve the PR; mention the constraint only when it matters to the next step. Keep the PR draft when policy requires human review before engagement, regardless of green CI.
