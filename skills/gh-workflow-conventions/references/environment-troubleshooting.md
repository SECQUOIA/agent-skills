# Environment and Client Troubleshooting

Use the matching symptom only. Preserve source and environment identity while
repairing setup. These are conditional recipes, not assumptions about every client.

## Runtime, PATH, and caches

- If an executable exists outside a wrapper but disappears inside it, inspect PATH
  within that wrapper. Some conda configurations rebuild PATH. Activation or a
  scoped path can preserve a solver, but do not prepend a directory whose Python
  or test runner shadows the selected environment. Check resolved executables.
- Before an editable/native build, verify interpreter and install prefix. Conflicting
  `VIRTUAL_ENV`/`CONDA_PREFIX` can target another environment even when the frontend
  lives in scratch. If it alters the wrong install, restore the known prior state
  and verify it before continuing.
- Missing wheels, manifest syntax errors, or solver `Unknown keyword` can reflect
  mismatched pinned runtime/tool versions. Reproduce under the declared versions
  and flags before judging the source. Package metadata and installed distribution
  records can disagree after mixed pip/conda updates; recreate only a disposable
  prefix rather than deleting a user's environment.
- On read-only cache failures, use a task-scoped writable cache (`PIXI_CACHE_DIR`,
  `PRE_COMMIT_HOME`, or the project's `UV_CACHE_DIR`) and preserve that choice on
  retry. An offline resolver limited to cached versions cannot prove a dependency
  conflict. Retry with authorized network access or report incomplete cache evidence.
- For pre-commit, inspect file/type selectors before installing environments. If
  every hook is inapplicable, record that rather than installing just to see SKIPPED.
  Do not grant host/network access to untrusted hooks merely to reproduce CI.
- If venv bootstrapping lacks `ensurepip`, a scratch `pip --target` installation
  can supply missing pure dependencies. Verify the intended source and interpreter;
  do not use an unrelated global install as a silent substitute.
- An unavailable system tool may have a supported scoped distribution (for example
  a bundled Pandoc wheel). Use that only when compatible with the documented build;
  verify the executable in the same environment that will run the check.
- If pytest collection fails only in a scratch tree whose root contains
  `__init__.py`, check whether the directory name is a valid Python identifier;
  a hyphenated scratch name can corrupt package discovery.

## Julia

Root and `test/Project.toml` environments have different dependencies. Prefer the
repository's targeted-test command; `JULIA_LOAD_PATH` can combine root, test, and
stdlib paths in scratch. Do not run `Pkg.develop` against the user's tracked test
project just to create that combination. An ignored Manifest can still select a
Julia version or absolute path dependency. Preserve user manifests; use the matching
runtime or a clean scratch environment. Do not copy another checkout's ignored
manifest into scratch. Require `Base.pathof` to point into the tested tree.

## Jupyter and process restrictions

A stale kernelspec can point into a deleted environment. Inspect its `argv`, then
use a scratch kernelspec and explicit execution override. If repository tests pick
the notebook's fixed kernel name internally, shadow that name under a scratch
`JUPYTER_PATH`; merely changing `JUPYTER_DATA_DIR` may not win precedence. Avoid
editing committed kernelspec metadata for local repair. Clean up any task-created
spec after execution. Recheck native build identity separately from kernel identity.

Black worker sockets, Jupyter kernel ports, and browser-backed image export can
fail before performing the check under a sandbox. Retry the same intended command
with available, authorized process permissions; do not claim a static read or
fast mode substitutes for the omitted execution. Likewise an optional solver's
availability probe may need to launch a process: distinguish executable discovery,
sandbox denial, and license failure.

## Documentation builds

Match builder major versions to config formats before debugging content. For local
resource checks, remove URL query/fragment components; deployment-owned assets such
as Documenter `versions.js` need deployment evidence instead of a per-version disk
check. PDF text extraction can fail on Type 3 fonts; inspect `pdffonts`, and install
a supported scalable-font package when authorized. A missing TeX class dependency
is an environment gap; use `kpsewhich` to identify it. Do not substitute stub class
packages and claim the real document toolchain was validated.

## Command execution

Use explicit workdir/absolute paths rather than relying on whether a client keeps
`cd` across calls. If a wrapper demonstrably drops heredoc stdin, use a script file;
its directory can affect Python imports, so place it in the intended tree or
configure the source path and verify `__file__`.

When the client reports a command-shape approval mismatch, separate compound setup,
execution, and cleanup into reviewable commands with the same intended semantics.
Request supported narrow permission for the required environment wrapper instead
of silently dropping it. A policy denial is not a reason to evade controls. For
`.git` read-only errors, inspect actual status and request metadata-write permission
if the workflow permits it; do not delete locks without evidence of a stale lock.
