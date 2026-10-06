# Contributor heads and transferred feedback

Read before editing when the head belongs to another contributor or the feedback source differs from the destination PR.

Query the PR's `head.repo.full_name`, head ref/SHA, author, and `maintainer_can_modify`. The modification flag governs forks; `false` on a same-repository PR is not a permission denial. Separately identify authorship even within one repository. Full user authorization to address the named PR permits safe in-scope fixes; material design choices still require the repository/user's intended direction.

A fork push requires `maintainer_can_modify` or verified ownership by the acting account; if modification is disabled and the account does not own the fork, do not try the write. Prepare a patch and report the author handoff. For an authorized push to someone else's branch, explain the changes and authorship clearly in the resolution summary. After pushing, poll the PR object until its head matches the actual pushed SHA before reporting checks or publishing head-specific markers.

When feedback is on a merged/closed source PR, apply it elsewhere only when the user explicitly names an open destination. Read source feedback, but edit/test/commit/push only the destination head. Publish one summary on the destination, and source inline replies linking the destination and fixing commits. Keep source threads unresolved. Request eligible reviewers on the destination; source review state does not transfer. Do not post a redundant source summary unless requested.
