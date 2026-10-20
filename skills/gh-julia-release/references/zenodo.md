# Archive verification

Load this only for a release using Zenodo or an explicit archive task.

For a first GitHub-integrated archive, verify that the repository is
[enabled in Zenodo](https://help.zenodo.org/docs/github/enable-repository/)
before publishing the GitHub release. An active release webhook verifies setup,
not an archive or DOI. Inspect the metadata Zenodo will consume from the selected
release source: [`.zenodo.json` overrides `CITATION.cff`](https://help.zenodo.org/docs/github/describe-software/).
Confirm title/version, intended creator names/order and source-consistent license
before triggering automatic archival. Resolve missing attribution with the owner;
maintainer access does not establish authorship or an ORCID. Citation metadata can
be prepared before a DOI exists; omit identifiers that have not been assigned.

If registration already pins a source tree, preserve that provenance when archive
requirements arrive later. A main-only citation edit does not change the pinned
release archive. Report metadata gaps and follow the source review/verification
gates before selecting a changed tree, or use an authorized archive metadata
correction; do not silently replace the registered source.

A GitHub-integrated release triggers its archive. Wait for the version under the
existing concept DOI, or for the first record to establish one; do not create a
duplicate manual version. Verify the
tag/repository/concept relationship and record the new version DOI in the release
notes or owning tracker within the authorized edit scope. Use the verified version
DOI to cite an exact release and the concept DOI for the project across versions.
When a concept DOI already exists, keep release-bound `CITATION.cff` on that
evergreen identifier if the version DOI will not exist until after publication.

GitHub ownership does not establish access to a legacy Zenodo integration.
If its maintainer is unreachable, test the current maintainer's access with a
narrow authenticated API read, keeping the token in an environment variable and
out of output. Present the actual decision: transfer preserves one concept
lineage; a successor restores control but splits it. Do not silently wait
indefinitely or create a competing record. A successor requires user authorization.

For an authorized successor, archive the exact published release/tag artifact,
relate it to the legacy concept with `isNewVersionOf`, to the tag with
`isIdenticalTo`, and to the repository/publication as appropriate. Document the
evergreen concept and confirm the legacy integration cannot also deposit it.

Read back public metadata, files, checksums, and both concept/version DOI redirects
without authentication. Compare the record's license identifier with the tagged
source's license files. Report a mismatch separately from verified software
installation. Correcting published archive metadata requires verified deposit
access and authorization; do not change the source license merely to match
inherited archive metadata.

If the record and files are public but DOI.org returns
404, report **published; DOI verification pending**. Check DataCite registration
and retry the same identifiers in bounded checks. Keep DOI-dependent completion
criteria open; do not republish or upload another version to retry resolution.
