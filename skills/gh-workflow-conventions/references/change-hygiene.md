# Change, Commit, and Push Hygiene

Use for local modifications, staging, pushing, or authorized cleanup. Preserve user
work under [worktree guidance](worktrees-and-checkouts.md).

## Scope and staged content

When edits are delegated, follow [ownership and integration](delegation.md) before
staging: one owner operates each shared index, and worker results remain intact
until their integration is verified.

- Stage explicit intended paths. Inspect `git status --porcelain -uall` as well as
  working-tree and cached diffs: ordinary diff omits untracked files, and a probe
  can leave the index at a different revision than the tested worktree. Review the
  actual cached content before committing. Keep unrelated files and credentials
  out; include intended binary/generated artifacts only after their checks.
- To undo accidental staging, use `git restore --staged` for previously tracked
  files. `git rm --cached` on them stages a deletion. For newly assembled trees,
  inspect ignored paths too; broad ignores can silently omit required data/evidence.
  Verify the intended inventory before removing any working copies.
- Preserve existing line endings and JSON serialization. For CRLF, inspect
  `git ls-files --eol` and use CR-aware comparisons rather than normalizing a whole
  file to silence whitespace diagnostics. A no-index diff exit 1 can mean files
  differ; inspect diagnostics or use the staged whitespace check.
- Avoid empty commits on already-applied reruns. Use real paragraphs in commit
  messages and inspect intended issue-closing keywords before push. After an
  ambiguous push, read the remote ref before any retry; if unapplied, refresh
  preconditions and retry once, then report any remaining failure.

## Credentials

Pass service credentials through supported secret mechanisms, never literal
repository content or published output. Inspect generated artifacts and prepared
payloads for tokens, host paths, and unintended byproducts before staging/posting.
Use least-privilege CI credentials and account for who can modify workflows and
which environment protections gate secret access. Do not expose secret values in
the inspection itself.

If a credential was published, stop propagation, notify the user without repeating
it, and recommend revocation/rotation. Deletion or history rewriting does not revoke
it; old commits, PR refs, reflogs, and external copies can retain it. History cleanup
and contacting support require their own authorization and cannot establish remote
erasure from local success alone.

## Generated, opaque, and frozen artifacts

- Before editing a binary/opaque artifact, refresh the relevant base and ensure the
  edit includes newer contributions. Resolve stale edits against the current
  artifact, not by choosing a whole side. For OOXML inspect package members and
  rendered/text differences, not paragraph text alone.
- A generator can lag deliberate human edits to its artifact. Compare the two and
  encode accepted changes into the generator before rebuilding; do not overwrite
  newer human intent. Compare rebuilt output with the accepted artifact.
- Keep integrity-pinned evidence packages unchanged by routine formatters. Exclude
  frozen paths from irrelevant style tools; a real change must deliberately update
  the manifest/archive and release provenance together.
- Notebook sources, outputs, and recorded execution SHAs need the ordering in
  [notebook artifacts](notebook-artifacts.md). For regeneration, identity, or render
  claims use [artifact verification](artifact-verification.md).

## Authorized cleanup

Delete only task-owned or explicitly authorized paths. An unfamiliar untracked
file is not disposable merely because it appears generated. Do not add repository
ignore changes as a workaround for unrelated local state.

For bulk branch cleanup, inventory live remote refs, cached tracking refs,
worktrees, and open-PR head/base branches separately. Protect default, protected,
checked-out, and open-PR refs. Require ancestry into a retained ref or established
patch equivalence; retain uncertain/unique work. Record exact SHAs in a verified
recovery bundle, including remote-only candidates, then recheck tips immediately
before deletion and skip moved refs. Report local deletion, remote deletion, and
tracking-ref pruning distinctly with the recovery location.
