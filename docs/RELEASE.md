# Release guide

This guide covers how a version is chosen, prepared, tagged, published and
verified. What each version changed is recorded in the
[changelog](../CHANGELOG.md), not here.

## Versioning

The package follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
While the major version is 0, a minor bump marks backward-compatible features or
a wave of related changes, and a patch bump marks fixes only. Declaring a stable
1.0.0 API is a separate, explicit decision.

The package version is independent of the schema versions: policy `1.0`, suite
`1.0` and `1.1`, report `1.0`, receipt `1.0`, suite receipt `1.0`, replay `1.0`
and the `sha256-canonical-json-v1` digest algorithm. A schema version changes
only through an explicit schema decision, never as a side effect of a release.

`src/constitutional_agent_testbench/_version.py` is the single source of the
package version. `pyproject.toml` reads it at build time, the package re-exports
it as `__version__`, and `constitutional-agent-testbench --version` prints it.

## Prepare the release pull request

1. Set `__version__` in `_version.py` to the new `X.Y.Z`.
2. In `CHANGELOG.md`, move the `## [Unreleased]` entries into a new
   `## [X.Y.Z] - YYYY-MM-DD` section grouped as Added, Changed and Fixed. Leave
   `## [Unreleased]` empty above it and update the link references at the end
   of the file.
3. Add `release/vX.Y.Z-manifest.json` in the same shape as the previous
   manifest: version, Python requirement, pinned build backend, the two
   artifact names and the `SHA256SUMS` sidecar.
4. Update the `Current package version` line in `README.md`.
5. Run `python scripts/check_version.py`. It must report that every surface
   agrees; the "Lint and metadata" CI job runs the same check.

## Merge and tag

1. Merge the release pull request with a merge commit once every CI check is
   green.
2. Wait for the CI run on the merge commit on `main` to finish green.
3. Dry-run the release workflow from `main`. The build job must pass and the
   publish job must be skipped:

   ```text
   gh workflow run release-assets.yml --ref main
   ```

4. Create an annotated tag on the merge commit and push it. The tag is
   `vX.Y.Z` and must equal the package version:

   ```text
   git tag -a vX.Y.Z -m "constitutional-agent-testbench X.Y.Z" <merge-commit>
   git push origin vX.Y.Z
   ```

A GitHub Release is public. Do not tag before the merge commit's CI is green.

## What the release workflow does

`.github/workflows/release-assets.yml` runs on every pushed `vX.Y.Z` tag and on
manual dispatch.

The build job has a read-only token. It:

1. runs `scripts/check_version.py --tag vX.Y.Z` and stops on any mismatch;
2. builds the wheel and source distribution with the pinned `build` and
   setuptools releases, and requires exactly the two expected archive names;
3. installs the wheel, checks `--version`, and runs the unit suite and the
   installed adopter check;
4. writes `SHA256SUMS` inside `dist/` with relative file names and verifies it
   with `sha256sum -c`;
5. extracts the release notes from the `## [X.Y.Z]` changelog section and
   retains everything as a 14-day workflow artifact.

The publish job runs only for tags and is the only job with `contents: write`.
It downloads the verified artifact and creates the GitHub Release with
`gh release create vX.Y.Z --verify-tag`, attaching the wheel, the source
distribution and `SHA256SUMS`.

If publishing fails after the tag exists, fix the cause and re-run the failed
job. Do not move or recreate a pushed tag.

## Verify a published release

```text
gh release download vX.Y.Z -R EauDoon/constitutional-agent-testbench
sha256sum -c SHA256SUMS
```

Both archives must report `OK`. Installing the wheel and running
`constitutional-agent-testbench --version` must print the tagged version.

## Distribution contents

The distribution installs two console commands, `constitutional-agent-testbench`
and `constitutional-agent-testbench-playground`, and runs as
`python -m constitutional_agent_testbench`. The repository-only `evals` package
is outside `src/` and is not part of the wheel; the source distribution includes
it so its tests can run, and the evaluation runner stays available inside a
checkout or an unpacked source distribution as `python -m evals.runner`.

## Not automated

Publication to PyPI is not automated and remains a separate decision. Versions
before 0.6.0 have per-version manifests under `release/` but no tags or GitHub
Releases, because no artifacts were retained for them.
