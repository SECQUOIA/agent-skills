# GitHub Writes and Verification

Read before mutations. Resolve identity through [GitHub reads](github-operations.md).

## Authorized surface

A full workflow invocation authorizes its documented writes unless the user
narrows them. A standalone “commit and push” authorizes Git writes; it does not
add GitHub prose. An explicit request for a body edit, comment, review, review
request, or merge needs no extra confirmation once its live conditions hold.
Ask only when a material scope/target ambiguity remains.

Keep existing PR titles/bodies, submitted reviews, comments, and replies immutable
unless the user requests the particular edit. Publish corrections as a new
comment/reply with the workflow's idempotency marker. Initial PR metadata is part
of PR creation. When a skill explicitly maintains a marked record (for example,
its own triage evidence comment), full invocation includes that documented update
only after matching ownership and identity. This is not permission to rewrite
arbitrary earlier comments/reviews. Updating a tracker checkbox also edits existing
text and requires that scope; a coordination request alone does not authorize
rewriting history.

Permission to attach an artifact to a named object does not authorize a second
public host, gist, release, or repository. A rejected review request does not
authorize changing access or substituting an unverified login. Bind named people
to confirmed accounts before invitations, assignments, or mentions. Verify any
authorized invitation's permissions and distinguish pending from active access.

## Precondition → write → readback

When workers or concurrent invocations share a target, establish the single
publication owner under [delegation guidance](delegation.md). A sentinel absence
check does not reserve the target against another publisher. This adds no owner
handoff requirement to an ordinary solo invocation.

1. Finish local preparation and make the payload reviewable. Read the target's
   live identity, state, head, and operation-specific gates in a separate `gh`
   command with literal repository scope. Inspect the result before writing.
2. Issue the authorized mutation separately. Use body/query files or JSON input
   for multiline or shell-sensitive content. Preserve real newlines; never
   interpolate untrusted text into executable shell syntax.
3. Immediately read the affected object and intended fields in a separate command.
   Verify content/state, not just `updatedAt` or the mutation's exit status. For
   discussion comments use `issues/comments/<comment_id>`; for reviews verify the
   submitted verdict/body and head. Check draft/reviewer state when affected.

Precondition and readback commands must not contain another shell operation,
pipeline, or unrelated check; `--jq` projection within `gh` is fine. Do not combine
read, payload transformation, and write in one pipeline. Reuse a successful read
query with new variables rather than changing its shape during verification.

If transport fails after dispatch, the outcome is ambiguous: read the exact object
or idempotency marker before retrying. If applied, continue verification; if
proven unapplied, refresh preconditions and retry once under available permissions.
For a definite validation/permission rejection or a second failure, report it and
stop that mutation. A broken readback is not a failed write: repair the read.
For bulk writes, verify each target/alias and compare intended and actual ID sets;
partial GraphQL errors can coexist with committed earlier fields. Retry only
proven-unapplied targets, in smaller batches if needed.

## Payload and linked work

- Follow applicable templates without irrelevant boilerplate. Carry acceptance
  criteria into implementation PRs with their satisfied/deferred status. Keep
  published text focused on the problem, change, and useful evidence.
- Only use intended issue-closing keywords. GitHub can honor them in commit
  messages and incidental body prose as well as the closing section. When issue
  closure matters, inspect messages and `closingIssuesReferences`; a correcting
  comment does not clear a body/commit closing reference. A body change requires
  its own authorization; do not rewrite pushed commits to remove a keyword.
- Match an issue's closure reason to the authorized disposition. Bounded
  non-reproduction alone neither proves a fix nor authorizes closure. If the user
  elects to close as not currently actionable, use `not_planned`, record the tested
  bounds, remaining uncertainty, and a concrete reopening trigger, and verify both
  `state` and `state_reason` on readback.
- Use URLs returned by tools or verify the exact constructed URL. Expand short
  SHAs through Git/API, never guess them. Read numeric values in the stated source
  artifact at the stated ref; do not reconstruct a “source” value from rounded
  output. Inspect prepared bodies for accidental secret values.
  For DOI/publisher links, use [scientific verification](scientific-verification.md);
  publisher anti-bot 403/429 responses alone do not establish a broken DOI.
- Target replies to the latest actionable comment ID. GitHub may attach a nested
  reply to the root; retain the addressed-comment marker and exact permalink.
- For review requests, verify `reviewRequests`, not an earlier approval. If a
  formal request fails, report the failure; use a comment fallback only when the
  authorized workflow includes it. Do not silently substitute another surface.
- When authorized follow-up work defers a requirement, cross-link the source and
  follow-up on the permitted surfaces. A “living” plan should name its authority,
  update owner, and refresh trigger rather than duplicating mutable status.

CLI-specific failures, including deprecated Projects fields and JSON payload
fallbacks, are in [GitHub troubleshooting](github-troubleshooting.md).
