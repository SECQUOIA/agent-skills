---
name: apply-conversation-lessons
description: Capture lessons learned from the current conversation and implement durable improvements into existing skills (Codex or Claude). Use when the user asks for an end-of-conversation lessons pass, wants takeaways folded into skills, asks what should be improved in skills from recent work, or explicitly invokes $apply-conversation-lessons.
---

# Apply Conversation Lessons

## Overview

Turn recent workflow friction into concise, durable skill updates. Prefer improving existing skills over creating new ones, and keep every edit proportional to the lesson learned.

This skill cannot run automatically at every conversation end. Use it when the user invokes it or explicitly asks for a closing lessons-learned pass.

## Workflow

1. Collect lessons.
   - Always infer candidate lessons from the current conversation when this skill is invoked.
   - If the user supplied lessons or requested a specific change, include that input alongside the inferred candidates.
   - Enumerate every skill used in the session, including this skill, and consider whether each has a durable lesson before narrowing to edits.
   - Ask a follow-up only when a likely edit would be risky or ambiguous. Do not invent user preferences as facts.

2. Triage each lesson.
   - Keep lessons that are reusable, procedural, and likely to prevent repeated friction.
   - Drop one-off project facts, transient tool outputs, personal notes, and broad style preferences already covered by system instructions.
   - Map each kept lesson to the smallest relevant existing skill. Create a new skill only if no existing skill has a natural ownership boundary.
   - When a lesson applies across several sibling skills that share a conventions subskill (for example the `gh-*` skills that read `gh-workflow-conventions`), map it to the shared subskill instead of repeating the change in each skill. Keep a lesson in a single skill only when it applies there alone.

3. Edit skills conservatively.
   - Read each target skill completely before changing it.
   - If the target skill lives in a shared or managed repo, follow "Shared Or Managed Skill Repos" below before editing: commit on a personal branch, never the default branch.
   - Prefer durable user-owned skills under the agent's skills home: `$CODEX_HOME/skills` (or `~/.codex/skills`) for Codex, and `~/.claude/skills` for Claude. When a Claude skill is a symlink into `~/.codex/skills`, edit the real Codex file; that single source updates both agents. Do not edit plugin cache skills under `.codex/plugins/cache/` (or an equivalent Claude plugin cache) unless the user explicitly asks for that; cache edits may be overwritten.
   - A single-source skill shared by both agents is read by Claude AND Codex, so keep the lesson's wording agent-neutral: describe the underlying tool/CLI behavior (`gh`, `git`, pytest, command-prefix permission matching) rather than one agent's specifics. Route a genuinely agent-specific lesson — for example Claude Code's `Bash(cmd:*)` allowlist syntax or a Codex-only setting — to that agent's own skills home instead of the shared file, or state it agent-neutrally if the concept applies to both.
   - The same split applies to frontmatter *fields*, not just body wording: a single-source shared skill must use only the fields both agents accept (`name`, `description`, and where supported `license`, `allowed-tools`, `metadata`). Claude-only extensions such as `model`, `effort`, `context`, `agent`, `disallowed-tools`, or `disable-model-invocation` fail Codex's frontmatter validator (it rejects unknown keys) and are ignored by Codex at runtime, so a lesson needing them must go to a Claude-only skills home rather than into the shared file.
   - If a lesson maps only to a plugin-cache skill, report it as an unimplemented candidate unless creating or updating a user-owned skill is clearly warranted.
   - If updating skills, follow the `skill-creator` principles when available: read it from its listed source locator, then keep changes concise with no auxiliary docs or references unless they are genuinely needed.
   - Add the lesson at the workflow point where a future agent would need it; avoid duplicating nearby rules.
   - Removing duplication is *relocation*, never deletion. Before finalizing, read the removed lines (`git diff -U0 | grep '^-'`) and account for each one: relocated to the shared subskill, preserved verbatim, or deliberately dropped with a stated reason. Watch for the failure where a "just deduplicating" edit quietly deletes an independent check — when a downstream skill re-verifies an upstream skill's work, that redundancy is deliberate. A handoff should remove the retyping, not the checking.
   - Treat shared convention subskills as first-class edit targets. When a skill delegates rules to a referenced subskill, put cross-cutting lessons in the subskill and leave the referencing skills' pointers intact rather than re-inlining the rule in each one. If a subskill edit changes what a referencing skill needs to point at, update those pointers too; if it changes the subskill's `description` triggers, update that as well.
   - Preserve frontmatter unless the trigger behavior itself changes. Update any sidecar agent metadata that is present (for example `agents/openai.yaml`) only when its user-facing metadata becomes stale.

4. Validate.
   - Run the skill validator for every changed skill when available. The validator ships with the `skill-creator` system skill, not with the edited skill's own repo: run `python <skill-creator>/scripts/quick_validate.py <skill-folder>` (e.g. `~/.codex/skills/.system/skill-creator/scripts/quick_validate.py` for Codex, or the equivalent under the Claude skills home). A skills repo shipping no validator of its own does NOT mean none is available — locate `skill-creator` before concluding validation is impossible.
   - If the validator script exists but is not executable, retry it with the appropriate interpreter such as `python <validator> <skill-folder>` before treating validation as unavailable.
   - If validation tooling is unavailable, at least inspect frontmatter, required fields, and Markdown structure.
   - Report any skill that could not be edited or validated.

## Shared Or Managed Skill Repos

Some skills are distributed through a shared repository that a single reviewer curates (for example a private research-group or class repo). Treat a skill as *managed* when its real folder is inside a git repository that has a remote you do not solely own, or the repository root contains a `.managed-skills` marker, or its README/CONTRIBUTING says so.

In a managed repo, never edit the default branch in place and never push automatically:

- If the managed checkout is not writable in the current environment, create a writable temporary worktree on a short-lived branch from the personal learnings branch. Edit, validate, and commit there; then fast-forward the personal branch to that commit and remove the temporary worktree/branch. Do not bypass the environment's file-edit safeguards with shell rewrites.
- Commit lessons on a personal working branch. If the working tree is on the default branch, create `learnings/<user>` from the current default branch first, then commit there with a clear message. Before writing the message, check `git log --oneline -5 -- <target file>` (or the repo's recent history) for an established convention — for example a shared `learnings:` prefix — and match it instead of inventing a new style, since the same `gh-review-pr`/`gh-merge-pr` skills will later process this branch's history.
- If the personal branch already has uncommitted skill changes, inspect them before editing. When they are valid accumulated lessons, validate and commit them before finalizing the pass (use separate commits when practical); when they are unrelated or ambiguous, leave them untouched and report that they must be resolved before `submit-learnings` can run.
- When the user asks to adopt lessons from another contributor's learning branch, do not branch from or merge that contributor branch. Switch to the user's personal branch, restore or copy only the selected skill paths from the source branch, then validate and commit those copied files there. Check `git status --porcelain -uall` so newly added skill folders are not missed by diff-only inspection.
- Accumulate lessons on that branch across sessions. Do not open or push a pull request on every invocation; the repo's cadence (for example a weekly push reviewed by a single reviewer) owns that step.
- Before starting new edits, sync the personal branch with the latest default branch so already-merged updates from others are incorporated and conflicts surface early — the sibling `sync-secquoia-skills` skill owns that procedure (fetch, rebase, and refresh of installed skill links); use it, or its manual fetch-and-rebase equivalent when it is unavailable. Keep each lesson small and self-contained to minimize cross-author merge conflicts.
- When the user asks to submit accumulated learnings, hand off to the `submit-learnings` skill (it rebases on the default branch, pushes the personal branch, and opens one PR); the single reviewer then reviews with `gh-review-pr` and merges with `gh-merge-pr`. This serializes changes through review instead of colliding on the default branch.
- Route a lesson that is genuinely personal and not meant for the shared set to a skill outside the managed repo, so the shared skills stay canonical.

## Final Response

Summarize the lessons implemented, the skills changed, validation performed, and any lessons intentionally declined as too broad or one-off. Always state whether this skill itself changed or was intentionally left unchanged, with the reason, because invoking it makes it a natural candidate target. In a managed repo, also report the personal branch used and that submitting the accumulated learnings for review is a separate, user-initiated step.
