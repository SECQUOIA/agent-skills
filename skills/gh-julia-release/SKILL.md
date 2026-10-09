---
name: gh-julia-release
description: Publish a Julia package release through its documented General or URL-only workflow, then verify the exact Pkg.add install path. Use for explicit release, registration, or tagging requests.
---

# Publish a Julia release

Read [shared conventions](../gh-workflow-conventions/SKILL.md). A release request
authorizes the release workflow, including its necessary PR, tag, and publication
steps; it does not authorize changing the package's distribution policy.

## Establish the release

Resolve the package, version, and distribution policy from `Project.toml`,
maintained release documentation, workflows, and settled decisions. If General
versus URL-only remains genuinely undecided or contradictory after those checks,
ask the user to decide before publishing. Reuse an explicit decision already made
in this task; routine release preparation does not need another confirmation.
Never introduce Registrator or TagBot to a URL-only package as a convenience.

Inspect existing tags, releases, open release PRs, CI, and applicable registry PRs
to resume work without duplication. Compare user-visible changes since the last
release: maintenance or citation edits alone need not create a package version
unless requested or required by policy. Protect local work and use a clean release
checkout based on the fresh remote default branch.

For a repository with Zenodo integration or an explicit archive request, read
[archive verification](references/zenodo.md) during preparation as well as
post-publication verification.

## Prepare and merge

- Wait for default-branch CI on a just-merged implementation before branching.
- Bump necessary version metadata; refresh sibling docs/test/benchmark compat
  pins on this package when the bump makes them stale. An already-correct
  version does not need an empty bump.
- Before registration or tagging freezes the release, compare license identifiers
  in release-bound citation files and any prepared archive metadata with the
  release source's license files. Correct mismatched metadata in preparation;
  do not infer the source license from citation or inherited archive fields.
- Check the exact release source's README, notes, installation and versioned
  manual for absolute preparation claims that become false after publication.
  Keep future commands conditional on verified availability; put dated mutable
  status in tracker evidence or explicitly historical context. A later main-only
  edit cannot repair wording already frozen in the registered tree.
- When adding or changing registration, TagBot or release-documentation automation,
  read [publication automation](references/publication-automation.md) before
  selecting the release commit or introducing credentials/triggers.
- For tagged URL installs, commit the reproducible
  `Pkg.add(url="REPOSITORY_URL", rev="vX.Y.Z")` example when policy requires it.
  The reviewed PR may reference the future tag created after its merge.
- Run proportionate package checks, including `Pkg.test()` when feasible and the
  local docs build when the release checklist requires it. Record limitations.
- Push and open the release PR when changes are needed. Verify current-head
  required checks and mergeability before merging; do not bypass CI.
- Before publishing, verify the exact release commit and its default-branch
  push checks, when configured. Reuse local verification when its relevant source,
  tests, inputs, and environment remain unchanged; live publication gates still
  require evidence for the exact release commit.

## Publish through the chosen path

**General:** Trigger `@JuliaRegistrator register` from a supported issue or commit
comment, with a short `Release notes:` block. Read back the response and registry
PR. Observe registry checks and AutoMerge with bounded, low-cadence polling.
Ordinary comments can pause AutoMerge; comment only when needed, using
`[noblock]` when appropriate. Registry merge alone is not publication completion.
Inspect TagBot and allow it to finish before attempting manual recovery.

**URL-only:** Immediately recheck both the tag and release. Verify existing
artifacts and complete only missing steps; retargeting or recreating an existing
artifact requires explicit user authorization. Announcing the action is not
authorization. When absent, create an annotated `vX.Y.Z` tag on the verified green release
commit, push it, then create a non-draft GitHub release from that tag. Verify the
remote annotated tag and its dereferenced commit. Observe tag-triggered workflows.

## Verify the user installation

Use a **fresh temporary project and fresh depot** with the default package-server
resolution. For General, run `Pkg.Registry.update(); Pkg.add("Package")`; an
explicit-version install alone does not prove normal users receive the release.
For URL-only, run the exact documented URL and tag install.

Assert the resolved version, then run `using Package` in that installation.
For URL installs also verify the manifest's `repo-rev` and record its
`git-tree-sha1`. Propagation probes may use `JULIA_PKG_PRECOMPILE_AUTO=0` to
check the version before costly precompilation; keep the final import gate.
If General is merged but default installation resolves the prior version, retry
with a new depot after a bounded wait and report propagation pending if necessary.

Verify the GitHub release and relevant workflows. For either distribution path,
require the tag's dereferenced SHA (not its tag-object SHA) to equal the verified
release commit. A mismatch stops publication completion; apply the same explicit
authorization boundary before any retargeting.
A release's branch-valued `targetCommitish` does not override
the tag's actual target.
For General, also require the version's registry `git-tree-sha1`, the verified
release package tree (the package subtree for a monorepo) and the installed
manifest tree to match. A matching version number alone does not establish that
users received the verified source.

Post downstream updates only when requested and after installation/import succeed.
Check the target before posting; include the applicable PRs, release and install
evidence without duplicate updates.

Report publication and any pending gates separately: distribution path, release
commit/tag, PR and release links, exact install verification, relevant checks,
and requested downstream updates.
