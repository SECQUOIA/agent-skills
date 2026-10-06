# GitHub CLI, Transport, and Client Troubleshooting

Use only for an observed symptom. Client behavior and supported flags vary;
check the installed version/help rather than treating a past workaround as a
universal requirement. Do not change global configuration merely to inspect a PR.

| Symptom | Narrow response |
|---|---|
| `gh` missing under WSL | Check whether Windows `gh.exe` is available; quote its path. Windows Git ownership errors do not require a global `safe.directory` change when local Git and explicit API calls suffice. |
| `gh auth status` disagrees with successful calls | A successful narrow read in the intended repository establishes that operation's access. Do not force reauthentication from the diagnostic alone. |
| DNS/socket/connection failure under restricted networking | Identify the sandbox restriction and retry the same read once with supported permission escalation when allowed; distinguish it from a definite auth/validation rejection. Respect denials. |
| `not a git repository`, unexpected owner in a 404 URL | Re-anchor `git` with explicit workdir or `-C`, and `gh` with explicit repository scope. A working-directory or fork-default error is not evidence that the object disappeared. |
| Unsupported JSON field/flag | Use installed help and supported fields or the narrow REST/GraphQL equivalent. Obtain `headRefOid` from REST `.head.sha` when needed; never substitute local HEAD. |
| Rich GraphQL read times out | Retry a narrow REST object/comments read. An unavailable rich response does not prove absence. |
| Contents API returns empty content or `encoding: "none"` for a large file | Use the ref-pinned raw-content fallback in [GitHub reads](github-operations.md); empty JSON content does not prove an empty file. |
| `--slurp` unavailable | Paginate supported output and parse pages separately; nested GraphQL connections may need explicit cursor loops. |
| ProjectsV2 `INSUFFICIENT_SCOPES` | Report the missing `read:project` access and the claim it prevents verifying. Do not invent Project counts or change account scopes without authorization. |
| Deprecated Projects field notice during a write | Read the target: some CLI versions exit zero without applying it. If unapplied, repeat the same authorized write through narrow REST and verify the actual field. |
| `gh pr merge` refuses locally despite a verified review exception | Recheck the actor's live exception and every remaining gate under [CI and checks](ci-and-checks.md). Use the equivalent server-validated merge endpoint through `gh api`, preserving the repository, PR, allowed strategy, and exact head `sha` guard, then read back the merge. Do not substitute `--admin`; a server-side policy/permission rejection still stops the mutation. |
| EOF/timeout/reset after mutation dispatch | Apply [ambiguous-outcome readback](github-writes.md) before retrying. If a body-file PATCH is proven unapplied, a JSON `--input` payload is a suitable equivalent. |
| Readback query fails after a successful write | Repair the query; do not resubmit the write. |
| Empty completed-job logs | Fetch `actions/jobs/<job_id>/logs` directly; confirm nonempty output before absence claims. Running jobs may not expose complete logs yet. |
| DOI redirects to a publisher that returns 403/429 | Use [scientific verification](scientific-verification.md) to distinguish a valid DOI mapping from blocked automated HTML access; do not report the DOI broken from that final response alone. |

A permission-limited branch-protection 404/403 does not prove an unprotected
branch; use [CI and checks](ci-and-checks.md). An API capability claim based on
memory should be checked against the live GraphQL schema or current official
reference before telling the user the UI is required.

Use temporary files for complex queries, scripts, and payloads. `gh --jq` does not
imply a standalone `jq` executable exists. If a wrapper drops stdin, run a script
file instead of a heredoc. If an approval mechanism rejects a compound command,
use separate reviewable operations with the same semantics; do not disguise a
rejected operation or widen its permissions. See [environment troubleshooting](environment-troubleshooting.md).
