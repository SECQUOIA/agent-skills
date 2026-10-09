# Registration and release-documentation automation

Read when adding or changing these mechanisms. Use current official
[Registrator](https://github.com/JuliaRegistries/Registrator.jl) and
[TagBot](https://github.com/JuliaRegistries/TagBot) guidance plus applicable
repository/organization conventions. Verify
app installation scope and existing credential permissions; GitHub repository
access alone does not prove the registration app is installed. Identify missing
setup without treating the release request as authority to change settings/secrets.

Inspect the actual trigger chain. Tag/release events created with `GITHUB_TOKEN`
do not trigger downstream Actions workflows; adding a tag trigger alone does not
establish a documentation publication path. TagBot also documents restrictions
when the selected release commit changes workflow files. Check the chosen source
and current guidance before registration, rather than discovering an unpublishable
tagging path after General merges. Do not add a token or empty version bump as an
automatic workaround. Any newly selected commit needs exact-source verification.

A maintainer-dispatched documentation refresh can use existing credentials and
preserve a default-branch-only environment. Validate the real tag's dereferenced
commit, expected package identity/version, reviewed default-branch ancestry,
matching registry package tree for General releases and published non-draft
release before selecting release source. Build that exact source under the existing
trusted event/environment gates; do not relax those gates merely to support version routing. Use
[deployment guidance](../../gh-pages-deployment/SKILL.md) for the publisher and
shared destination lock/history checks.

Create stable/version aliases only from real release content and retain dev and
publication metadata. Local routing fixtures establish prepared behavior, not a
successful hosted release refresh. Verify served routing/navigation/search after
the actual run. A separate aggregate publisher needs its own source wording and
refresh assessed; dispatch cannot correct stale installation claims in its source.
