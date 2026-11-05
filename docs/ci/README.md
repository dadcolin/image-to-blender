# Optional GitHub Actions setup

`github-actions.yml` is an inactive template for CPU-only Python 3.11 / 3.12 tests.
It never runs IDOL or downloads model weights.

The first release was published using an OAuth credential without GitHub's
`workflow` scope. GitHub refused the workflow-file push. Code, local tests and
release assets can still be published; no CI result is claimed.

A maintainer with appropriate workflow permission can review and copy this
template to `.github/workflows/test.yml` to activate it. Keep `contents: read`.
Do not store personal model or SSH credentials in the workflow.
