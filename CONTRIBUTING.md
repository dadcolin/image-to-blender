# Adding a test case

Start with one complete object on white or an already removed background. Do not commit private references, credentials, EXIF/GPS, artist personal data, local filesystem paths, proprietary model weights or website screenshots containing customer information.

1. Confirm permission to process and publicly redistribute both input and chosen outputs. State the asset license separately from code; never infer CC0 from a public URL.
2. Keep a private original. Create a metadata-free public input and verify its pixels. Record its SHA, dimensions and format.
3. Run a unique output directory with recorded seed/settings and package/model versions. Record elapsed time separately for model loading/inference, meshing and Blender export/reopen. Do not count nested stages twice.
4. Inspect the input view, several orbit views, top/side and thin connections. Report skew, missing parts, floating fragments, text corruption and unseen surfaces. Preserve failures. Numerical tests are not visual approval.
5. If real dimensions are known, state the source, units and whether the targets are whole-object bounding sizes or manually selected part dimensions. Report the actual post-export dimensions. Label made-up targets as **demo**, not measurements.
6. Strip personal paths and custom data from a fresh public `.blend` copy; reopen and compare geometry/colors with the original. Include the exact public asset hashes. Do not publish the raw environment or service receipts.
7. Add a case README plus a record following `examples/case-template.json`. Keep large artifacts in a release, with links and hashes. Do not include example assets in the Blender extension ZIP.

For code changes, run `python -B -m pytest -q`. Add a focused regression when the bug affects source binding, coordinate conventions, covariance, dimensions or cancellation. Blender API changes also need an isolated actual Blender import/export check. A new GPU inference must be explicitly scheduled by its operator, never triggered by tests or package installation.
