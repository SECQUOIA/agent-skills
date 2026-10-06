---
name: gh-pages-deployment
description: Diagnose stale or missing GitHub Pages and hosted documentation sites. Use for deployment checks or requested deployment changes; diagnosis alone does not authorize settings or workflow changes.
---

# Check a documentation deployment

Read [shared conventions](../gh-workflow-conventions/SKILL.md). Resolve the
repository, canonical site, and actual hosting path before attributing a failure.
Diagnosis is read-only. A request to fix or take down a site authorizes the
corresponding changes within its scope; do not ask again for an already-authorized
repair.

## Identify the publisher

Use `gh` for GitHub state. Verify URL-to-repository mapping, fork versus upstream,
and any referenced merge commit. Read `repos/OWNER/REPO/pages` and `build_type`.
A 404 can mean absent Pages configuration, insufficient access, or an incorrect
target. **It does not prove external hosting.** Check authentication/permissions,
repository configuration, DNS, maintained links, and host-specific evidence.

- **Actions Pages:** inspect the relevant workflow, its exact head SHA, deployment
  records for `github-pages`, and deployment statuses.
- **Legacy branch Pages:** inspect the configured branch/path and
  `pages/builds/latest`. An unrelated deploy workflow, billing failure, or skipped
  preview does not establish the state of the legacy publisher.
- **External documentation host:** verify the project's configured repository and
  build evidence at that host. For Read the Docs, inspect project/build API data
  when accessible; project access is separate from GitHub permissions. A rapid
  failure with no checked-out commit suggests a pre-checkout/configuration
  problem; confirm the log before naming its cause. Identify who can change the
  host connection when that action is needed.

## Check deployment and visible content

Queued, waiting, and in-progress jobs are not failed merely because they take
several minutes. Missing logs, including `BlobNotFound`, during an active run
are inconclusive. Use bounded observation and report pending work honestly.

Use the configured canonical URL, then compare served commit metadata,
timestamps, or relevant visible content with the intended release/merge. A
cache-busted metadata endpoint is useful when the site exposes one; otherwise
state the weaker evidence from HTML and headers.

An asset's HTTP 200 proves that URL is served, not that the page renders it.
For a rendering complaint, inspect the browser's actual requests or built
HTML/JS/CSP: picture/WebP substitution, lazy loading, and policy restrictions can
select or block a different URL. Use existing browser tooling when it resolves
the symptom; do not install a browser for an unrelated deployment check.

## Make the authorized change

For a requested repair, fix the evidenced cause and validate it. Reproduce a
hosted configuration build from the dependency set being committed, so the test
represents the host's eventual environment. If only diagnosis was requested,
present the concrete proposed change and its evidence before requesting authority.

For an authorized fork takedown, recheck the exact fork, delete its Pages
configuration, and read it back. Disable only the deployment workflow needed to
prevent recreation; leave unrelated and upstream workflows alone. Confirm the
public fork URL stops serving the site, allowing bounded CDN propagation. A
post-delete API 404 corroborates the known deletion but is not sufficient by
itself to prove public takedown.

Report repository/host, relevant run or deployment links, canonical URL,
published-content evidence, changes made, and any pending propagation or access
limitations.
