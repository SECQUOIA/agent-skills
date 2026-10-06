# Worktrees, Checkouts, and Shared State

Use before scratch execution, branch switching, merge probes, or work in a
checkout another session may use.

## Preserve the original checkout

Record its branch, HEAD, and status before switching or editing. The primary
checkout is suitable when unrelated files neither overlap nor affect verification.
Use isolation for overlapping or verification-affecting user changes, divergent
branches, wrong source, concurrent activity, or uncertain safety. Do not stash,
delete, or reset user work merely to
satisfy a clean-tree preference. A branch backup does not preserve uncommitted files.
Unexpected branch/HEAD movement can be another session's work; inspect fresh state
before responding, and never “repair” it by overwriting that work.

Read files with `git show <ref>:<path>` instead of materializing another tree into
the primary index. Never use `git checkout <ref> -- .` as an inspection operation.
If an accidental write occurs, identify and restore only your changes from a
verified snapshot; do not assume `reset --hard` is safe because an earlier check
was clean. For mutations, keep a byte-preserving pristine baseline and make each
probe in a disposable copy; see [mutation testing](mutation-testing.md).

## Choose a scratch form that meets the contract

- A detached worktree at the verified head is convenient when original-repository
  metadata writes are permitted. Use an absolute scratch path and verify its HEAD.
  Worktree creation/removal and fetching write `.git`; they are not no-write reads.
- If the original checkout **and its metadata** must remain untouched, use a
  separate scratch clone/repository, fetching there, or archive an already-local
  exact commit into scratch. An archive is not a Git repository; use a scratch
  clone if tests need `git ls-files`, revision metadata, or tracked-file discovery.
- Do not build an exact-head claim by copying an unrelated checkout and replacing
  only changed files. Unchanged dependencies and branch-only added files can
  alter behavior. Materialize the complete verified tree.
- Give concurrent agents separate scratch directories. Preserve reusable baselines
  outside child cleanup roots; each child removes only its own artifacts.

## Verify source and execution identity

Set an explicit absolute working directory/project path for each command. Confirm
the tested package/tree, not just a successful exit. Editable installs and import
finders can select a different checkout despite `PYTHONPATH`; inspect the imported
module's `__file__` (Julia: `Base.pathof`). Verify representative child interpreters
when tests spawn processes. Exclude copied `__pycache__` files; traceback filenames
alone can describe old bytecode and are not import-identity evidence.

Prefer an isolated install of the exact tree. A focused Python probe can load a
file through `importlib.util.spec_from_file_location`; repository tests need the
real module identity and appropriate package context. If a shim is necessary,
assert the loaded path and compose with existing test setup rather than overwriting
a tracked `conftest.py`. A uniquely named pytest plugin is safer than replacing
root configuration. Keep native extensions/generated bindings tied to the exact
source and toolchain; “native files unchanged by this PR” does not prove a borrowed
binary is current. Rebuild when identity cannot be established.

## Merge-result evidence

When base changes could affect the PR (especially renamed/deleted shared APIs),
inspect both directions: current-base consumers of PR removals and PR consumers
of base removals. Build/test the actual combination when static evidence leaves a
material compatibility question. An earlier result remains usable only for the
same relevant base/head inputs; do not repeat unrelated suites automatically.

`git merge-tree --write-tree` writes objects. For strict read-only inspection use
the three-argument form or execute the write-tree form in scratch. A cached
`refs/pull/<N>/merge` may lag the base: verify its base parent/tree before testing.
Conflict preferences `ours`/`theirs` operate on whole hunks; review both parents
and retain compatible contributions rather than treating them as semantic policy.

## Cleanup

Leave a worktree before removing it; remove only task-owned paths/refs and verify
its registration is gone. Prefer targeted removal over broad pruning. Preserve
and report user state; do not automatically stash or fast-forward a dirty primary
checkout after scratch work. If updating it is authorized, assess overlap first
and leave unresolved user edits intact. Restore the original branch only when
safe and consistent with concurrent activity.

For environment/setup failures rather than source defects, use
[environment troubleshooting](environment-troubleshooting.md).
