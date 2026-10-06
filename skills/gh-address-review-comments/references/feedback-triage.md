# Feedback triage and exceptional remedies

Read for overlapping/broad feedback, explicit deferrals, metadata/settings findings, or questions whose remedy is uncertain.

Map each target to its full rationale and an observable acceptance check. Multiple comments about one refactor need one coherent correction and separate dispositions, not contradictory per-thread patches. Read the anchored symbol, producers/consumers, keyword/state-key contracts, and relevant repository convention before interpreting terse naming/design feedback. Verify both the diagnosis and proposed remedy; preserve the valid concern when a suggested fix is incorrect or incomplete.

A question can reveal a defect and warrant a reproducing test. A comment explicitly accepting the existing behavior is informational. Re-read current head for already-delivered fixes, especially after rebases; if a definition disappeared, trace remaining callers and prior versions before accepting a “delete the leftover” suggestion.

An explicit maintainer-prescribed nonblocking follow-up is the requested disposition when technically sound. Verify and record the permitted follow-up with cross-links; do not override it with an unnecessary code commit. A repository comment can support interpretation of task scope but does not independently authorize unrelated external writes. If the follow-up surface is not covered by user or repository-policy authorization, prepare the concrete record and report the remaining permission need. A declined Blocking request remains unresolved for a human decision.

For stale title/body text, report corrections in the new summary by default. Edit the original title/body only when the user requested that surface. If the finding specifically required changing it, a correction comment leaves it Partially addressed; do not claim completion or re-request review as fully resolved. Settings-only fixes likewise require explicit policy/user authorization, preserve unrelated settings, and need live readback rather than a dummy commit.

Refresh live dependencies when earlier feedback describes drafts, stacked bases, or a conditional sibling handoff. A landed prerequisite can make a formerly future obligation current. An authorized append-only base merge must preserve both parents' in-scope intent and be verified; do not infer authority for another PR's edits from this PR's feedback.

For broad simplification/removal, inspect compatibility promises and base consumers before deleting an apparently unused API. Verify removed paths/fields and docs across the full PR diff. Preserve exact requested literals when correct; rewrap rather than abbreviating them. Stable citations should use pinned revisions or durable symbols instead of moving line references.

Re-run the affected path after requested changes that expose new inputs or defaults. A newly visible defect in the PR's own changed behavior belongs in the fix; unrelated nonblocking defects do not justify expanding scope or filing new issues without authorization. For performance/benchmark claims, use representative evidence when available and state unavailable solvers/data rather than inferring results from wiring.
