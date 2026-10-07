# Release and rollback

Version 1.0.0 is declared in `pyproject.toml`, `app/main.py`, `/health`, and `CHANGELOG.md`. Keep those values aligned for future versions.

Before tagging, run the locked install, lint, format check, tests, and the in-process demo. Inspect API behavior and dependency changes. Commit only source, docs, lock files, and non-sensitive example evidence. Ignore SQLite files, virtual environments, coverage output, and secrets.

`.github/workflows/ci.yml` runs Python 3.11/3.12 checks and uploads coverage/test results. `.github/workflows/release.yml` runs validation when a `v*` tag is pushed, verifies the tag/version relationship, archives the committed source, and creates a GitHub Release. Only the release job gets `contents: write`. No deployment or paid service is configured.

```bash
git tag v1.0.0
git push origin v1.0.0
```

GitHub Actions must be enabled and the repository must allow the workflow token to create releases. If a release fails, inspect the workflow before retrying; do not retag different source with the same published version. The packaged folder contains workflow definitions, not an already published GitHub Release.

Rollback: retain the previous source tag/container image, snapshot the database using SQLite's backup API, stop new traffic, run the previous version with the same persistent volume, and verify readiness, generation, trace retrieval, and response status. This initial release creates tables if absent but has no migration framework. Future incompatible schema changes require versioned migrations and a tested rollback/restore plan.

Docker commands are supplied but container construction must be validated in a Docker-enabled environment before deployment.
