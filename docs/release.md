# Releasing wisepay-observability

This package has **no deployment**. A "release" means cutting a new version tag
so the consuming services can pin it, and publishing a GitHub Release so a
validated wheel + sdist are built and attached.

The version is derived from the git tag by `setuptools-scm` — there is no
version string to bump in source. The tag *is* the version.

## Versioning policy (SemVer)

Tags are bare SemVer, matching the existing history (`1.0.0`, `1.1.0`, ...).

- **MAJOR** — a breaking change to the public API (`setup_logging`,
  `TraceMiddleware`, `OpenSearchHandler`, the context helpers,
  `build_outgoing_headers`) **or** to the emitted log-document shape that the
  OpenSearch index mapping / dashboards depend on (renaming/removing a field,
  changing a type).
- **MINOR** — backward-compatible additions (a new log field, a new optional
  parameter, a new helper).
- **PATCH** — bug fixes that don't change the public API or document shape.

Because every service pins this package by tag, **a version bump here is a
fan-out** — see below.

## Cutting a release

1. Make sure `master` is green (the `tests` workflow passed on the merge).
2. Create the release from `master`, which creates the tag and fires the
   `release-artifacts` workflow:

   ```bash
   gh release create 1.2.0 \
     --repo wisepayru/observability \
     --target master \
     --title 1.2.0 \
     --generate-notes
   ```

   (Or use the GitHub Releases UI — "publish" is what triggers the workflow;
   `release: types: [published]`.)

3. `release-artifacts.yml` then:
   - re-runs the test suite (`uses: ./.github/workflows/test.yml`) so a release
     can never ship un-tested code;
   - builds the wheel + sdist with `python -m build`;
   - asserts the built version matches the tag (fails if the tag isn't at a
     clean commit, i.e. a `.devN` version was produced);
   - uploads `dist/*` to the release with `gh release upload --clobber`.

Check the run on the self-hosted runner and confirm the two assets are attached
to the release.

## Fan-out: updating the consumers

The artifacts are for validation/availability. The **install path stays
git-by-tag**, so a bump is not picked up until each consumer re-pins:

```
wisepay-observability @ git+https://github.com/wisepayru/observability.git@1.2.0
```

Consuming repos (update the `@<tag>` and let their CI run):

- `ym-api`
- `iris`
- `currency-exchange-rates-api`
- `tg-bot`
- `currency-exchange-rates-parsers`
- `banking`

Bump them deliberately — a MAJOR (document-shape) change must be rolled out in
step with any OpenSearch index-mapping change.

## Rollback

Re-pin the affected consumer(s) to the previous tag and let their deploy run.
Release assets for older tags stay attached, so nothing needs to be rebuilt.
