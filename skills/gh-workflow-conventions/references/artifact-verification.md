# Generated and Rendered Artifact Verification

Use when the deliverable claims regeneration, output parity, published layout, or
artifact integrity. Inspect the artifact semantics; source correctness alone does
not prove a rendered/generated result is correct.

## Rebuild and compare

Materialize the exact candidate in a clean scratch checkout/archive. Verify required
inputs are tracked or explicitly supplied, then force the generator to run: archive
mtimes can cause `make`/`latexmk` to declare committed targets up to date. Confirm it
actually wrote the output. A generator with missing inputs should fail before
clobbering a committed artifact with empty/placeholder content.

If a check archives `HEAD`, its pass covers that commit, not uncommitted candidate
artifacts. Use a scratch candidate commit or materialized candidate tree. Recheck
only after relevant artifact/source changes. For cross-platform numeric last-bit
differences, round at the presentation boundary to justified precision, not inside
shared scientific computation or by weakening the comparison arbitrarily.

Choose and report the equality layer:

- Deterministic output: whole-file byte identity, using supported deterministic
  timestamps/settings where appropriate.
- Archive formats with nondeterministic ZIP metadata: complete member inventory
  including duplicates and every member's uncompressed raw bytes, plus structural
  validation and relevant consumer/render checks. Call this member-byte identity.
- Intentional semantic comparisons: name exclusions/normalizations and inspect
  the affected visible output. Do not label a normalized comparison byte-identical.

Generated artifacts may include deliberate human edits absent from their generator.
Follow [change hygiene](change-hygiene.md) before rebuilding over them.

## Installable distributions

For release readiness or packaging changes, verify the built distribution rather
than relying on source tests, an editable install, or a successful build. Check
that archives contain the library code and required runtime resources; when both
a source archive and a binary distribution ship, build the latter from the former.
Install the artifact with its declared dependencies in a clean environment and
exercise representative imports and resource consumers outside the checkout.
Exclude checkout paths and editable import hooks, and verify imports resolve to
the installed artifact. Report the runtimes actually checked and any gaps before
publishing or claiming release readiness. Prefer a project CI guard for this
contract when packaging is the defect being fixed.

## Rendered contracts

For changed visual content, inspect relevant rendered pages/figures; a successful
build does not detect collisions, clipped labels, or wrong figure/caption pairings.
For unchanged-rendering claims, compare a baseline and candidate semantically and
visually rather than interpreting timestamp-only binary differences as regressions.
PDF layout claims require the actual class/fonts/spacing and ink bounds against the
page/margins, with visual inspection of borderline pages. OOXML edits require
package relationships/styles/sections as well as visible text; inherited cover
headers can affect body pages even when old members remain unchanged.

For README badge/link rendering defects, inspect GitHub's rendered anchors/images
and actual badge text. HTTP 200 is not proof of the intended label. If GitHub's
image proxy disagrees with the canonical image, check both before editing source;
a transient cache response is not a repository defect.

Scientific values and comparisons use [scientific verification](scientific-verification.md).
Notebook output/provenance uses [notebook artifacts](notebook-artifacts.md). Build
package/font gaps use [environment troubleshooting](environment-troubleshooting.md).
