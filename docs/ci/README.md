# GitHub Actions setup

CI is active in [`.github/workflows/test.yml`](../../.github/workflows/test.yml).
The **CPU tests** workflow runs on pushes and pull requests, using
`ubuntu-latest` with Python **3.11 and 3.12**. Each job installs `.[test]` and
runs `python -B -m pytest -q`. Repository permissions remain `contents: read`.

## Verified run

[Run 42075007097](https://github.com/dadcolin/image-to-blender/actions/runs/42075007097)
completed with **success** on **2026-11-05 at 17:29 UTC**, for commit
[`68ea3751c344832a73c2fb71fd780f162dacc7fa`](https://github.com/dadcolin/image-to-blender/commit/68ea3751c344832a73c2fb71fd780f162dacc7fa).
Both `unit (3.11)` and `unit (3.12)` passed. See
[GitHub Actions](https://github.com/dadcolin/image-to-blender/actions) for current
status; the result above applies to that specific commit and run.

The workflow tests the CPU Python code, including simulated IDOL adapter
interactions. It does not run GPU inference, download model weights, or launch
Blender. See [VALIDATION.md](../VALIDATION.md) for the separate local Blender
checks and real-model history.

## Reuse and maintenance

[github-actions.yml](github-actions.yml) remains a reference template. The
active workflow under `.github/workflows/` is authoritative for this repository.
To set up the checks in another repository, review the template and place it at
`.github/workflows/test.yml` using an account with permission to update workflows.
Keep `contents: read`, and do not store personal model or SSH credentials in the
workflow. Check the actual Actions run after changing the configuration.
