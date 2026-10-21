# GitHub Target Resolution and Reads

Use for target/ref identity and complete inventories. For CLI failures, use
[GitHub troubleshooting](github-troubleshooting.md).

## Repository and object identity

- An explicit URL selects the authoritative repository, even when the current
  checkout is unrelated. Inspect remotes for a bare number; `gh` may choose a
  fork's upstream parent. Pass `--repo OWNER/REPO` on object, list, and run calls,
  or use literal `repos/OWNER/REPO/...` API paths. Confirm returned URLs and titles.
- Resolve the current branch explicitly when using `gh pr view --repo`; do not
  assume it still infers a branch. An issue API can return a PR: check the URL or
  `pull_request` field. If an issue number evidently means its implementation PR,
  establish and announce that mapping; obtain clarification before a write when
  the requested target remains ambiguous.
- A missing or terminal target is not license to act on another. Check repository
  identity and relevant open targets, then report a verified no-op or ambiguity.
  The invoking skill decides whether a resolved issue is actionable.
- Use structured fields sufficient for the decision, including `url`, `number`,
  state, and PR `headRefOid`. Bind reusable GraphQL query variables instead of
  replacing text. Check returned identity before using IDs for mutations.
  For merge readiness requiring repository merge settings and review threads, use
  `gh api graphql` with repository fields `mergeCommitAllowed`,
  `squashMergeAllowed`, `rebaseMergeAllowed`, and `deleteBranchOnMerge`, plus the
  needed `pullRequest` fields and paginated connections. Use GraphQL for
  `baseRefOid` or `closingIssuesReferences` when the installed CLI does not
  expose them, and REST `repos/OWNER/REPO/pulls/<N>` for `rebaseable` when
  selecting rebase.

## Ref-pinned source

- Resolve the live head and base branch separately. The REST PR's `.base.sha`
  may be an older snapshot; query the live base ref. Refresh exact remote-tracking
  refs before ancestry/diff decisions. Save each fetched SHA or use named refs:
  a later fetch overwrites `FETCH_HEAD`.
- Fetch `pull/<N>/head` from the remote whose repository matches the PR's **base
  repository**, not a guessed `origin` or fork branch name. Verify the result equals
  `headRefOid`. Fetching a ref does not check it out. Verify the execution tree
  before running tests; use [worktree guidance](worktrees-and-checkouts.md).
- For divergent local PR branches, build from the verified remote head in an
  isolated checkout and append the intended commits. Do not reset, merge, rebase,
  or force-push divergent local history merely to make its branch name match.
- Read every file supporting a claim at the inspected ref, including unchanged
  dependencies: `git show <head>:<path>` or `contents/<path>?ref=<head>`. Use the
  refreshed base/head merge-base diff, not `HEAD^..HEAD`, for PR scope.
  For files larger than 1 MB, the contents API can return `encoding: "none"` and
  empty `content`. Re-read that same ref-pinned endpoint with
  `-H 'Accept: application/vnd.github.raw'` before calling it empty or unavailable;
  save large responses and inspect only the relevant sections.
- A historical commit unavailable to local fetch can still be valid provenance.
  Verify it and its exact file through `gh api`; distinguish GitHub availability
  from local object availability.

## Complete file and thread inventories

- Use the paginated PR-files endpoint for changed-file sets and `changedFiles`
  for counts. `gh pr view --json files` may truncate at 100. On oversized diffs,
  reconstruct filenames with the API and inspect actual blobs locally; missing
  patches or zero addition/deletion counters do not establish empty content.
  GitHub's 3,000-file endpoint cap or unresolved set disagreement prevents a
  complete-review claim; report the scope limit.
- Request `reviewThreads.isResolved`, `isOutdated`, and stable locations such as
  `originalLine`. Paginate both threads and each thread's comments. An outdated
  `line: null` does not remove the finding. Use REST review comments for missing
  hunks or database reply IDs; confirm the latest comment is included.
- Preserve one output object per source comment when projecting inventories:
  jq `markers: [.body | scan(...)]` retains unmarked comments, while an unwrapped
  `scan` can drop or duplicate them. Compare IDs when a transformation can alter
  membership. Derive cohort counts from the enumerated ID set.
- ReviewNB anchors can refer to notebook JSON metadata. Parse its
  `ReviewNBCommentContext-DoNotDelete` marker's `data-cellIndex` and confirm the
  mapping against a known cell before using it; ordinary GitHub reply endpoints
  still apply.

## Read integrity

Inventory actionable items in a user-supplied report/checklist separately from
GitHub threads. New requirements supersede stale premises; an unchanged re-drop
does not create a new implementation round. Reuse valid prior evidence, verify
relevant current state, and report source-artifact coverage or a supported no-op.

Check the API command's own success before consuming filters. Do not mix raw
content response headers with JSON `--jq`. `gh api` fields change its default
method to POST, so use `-X GET` for REST reads with query fields. For file-backed
queries use `-F query=@<file>`; `-f` sends a literal string. Automatic GraphQL
pagination expects `$endCursor` wired to `after:`; inspect `pageInfo` when nested
connections require separate loops.

For absence claims, enumerate the corpus and validate a search against a known
positive; include case/aliases and imported fragments as relevant. Distinguish
active code from comments. Check that logs are nonempty and readable as text.
Verify mutable state at publication time when it supports a finding or action;
prefer durable invariants over prose that becomes false when its own remedy lands.

Project integrations and process arguments can contain credentials. Project only
needed non-sensitive fields; inspect webhook hostnames without paths/queries and
known-process metadata without full argument/environment dumps.
