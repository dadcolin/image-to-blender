# Geometry, files and resource boundaries

IDOL predicts oriented Gaussian ellipsoids, opacity and spherical-harmonic color from one image. It does not output a native editable triangle mesh. This project samples the anisotropic field

`D(x) = sum_i alpha_i * exp(-0.5 * (x-mu_i)^T Sigma_i^-1 (x-mu_i))`

and extracts an isosurface with Lewiner Marching Cubes. The default is a 256³ grid, density threshold 0.5, opacity floor 0.005 and 3-sigma finite support. Covariance uses all three scales and the wxyz quaternion. Colors are density-weighted SH0 appearance, treated as display RGB and converted to linear vertex colors for an emission material. No PBR decomposition is claimed.

No smoothing, decimation, component deletion, semantic furniture fitting or automatic unshearing is performed. Strictly zero-area triangles produced by float32 export can be removed under a recorded tiny numerical cleanup cap; other structural defects remain visible. Thin geometry and faint surfaces depend on sampling resolution/threshold. Changing those parameters does not add information missing from the original image.

## Source and output contracts

All manifests are JSON with `schema_version: 1`. Paths are relative POSIX paths confined to the manifest directory, with SHA256 and byte length. Validation proves file consistency, not trusted authorship or model accuracy. Do not treat a self-created manifest as a signed remote receipt.

- Native `source-manifest.json`: `kind=gaussian_source`, `format=idol_standard_3dgs`, explicit `axis=y_up|z_up`, and `artifact={path,sha256,bytes}`. The PLY stores floating XYZ, log scales, wxyz rotation, logit opacity and SH0 `f_dc_0..2`. `gaussian_count` is optional and checked when present.
- Derived `mesh-manifest.json`: `kind=density_mesh`, `native_model_mesh=false`, a bound copy of source manifest/native PLY under `source/`, NPZ arrays, triangle PLY and portable `mesh-data.json`, each with SHA/bytes. Mesh metrics and sampling settings are recorded.
- Portable `mesh-data.json`: `kind=triangle_mesh_data`, explicit source axis, `vertices`, triangle `faces` and RGB `colors` lists. The add-on reads this using only Python's standard library and Blender APIs. It validates the source manifest/PLY binding; NPZ and triangle PLY are alternate representations and are not consumed by the add-on.
- `.blend.json` and `reopen.json`: technical export/reopen checks. `visual_qa_approved=false` until a separate actual visual review. The source mesh and its evidence stay intact.

IDOL's PLY exporter changes z-up model space to y-up. Blender import applies `(x,y,z) -> (x,z,-y)` once for an explicitly y-up source. Unknown axis conventions are rejected. No real-world size is inferred.

The CLI bakes dimension factors into vertices, uses meter units and rechecks the persisted world-space bounding box. Whole-object uniform scaling preserves proportions. Independent XYZ fitting changes proportions. The interactive add-on scales about the selected world-space bounding-box center and accounts for the current scene unit scale; in Edit Mode it affects selected vertices only. This is a manual part control, not automatic segmentation or an articulated constraint solver. Shared connecting faces may stretch, and sequential whole/part operations do not establish simultaneous CAD constraints.

## Why retain 3DGS and intermediate files?

The model's output is 3DGS; this workflow cannot simply skip that representation while still using IDOL unchanged. Serialization could be removed in a future in-memory optimization, but it is not the model's fundamental geometry limitation. Current files retain auditable evidence and let users redo meshing or dimensions without another GPU run. Reusing a mesh skips both IDOL and density sampling.

## Execution boundaries

The portable CLI never pauses services, connects to a personal server, changes drivers or changes a system model configuration. The operator must schedule an adequate resource window. Existing production services remain the operator's responsibility.

`reconstruct` isolates inference in a child process (default 24 GiB own RSS cap, 16 GiB system available-RAM floor, 1800 seconds). CPU meshing/export use a 1.5 GiB own RSS cap, 2 GiB available floor and 600 seconds per stage. Flags allow deliberate platform tuning. These are observed host-memory checks, **not a hard GPU-memory quota**; unified-memory hardware can affect accounting. Cancellation/limit failures clean up only that invocation's process tree. No model retry is automatic. Internal `_infer` / `_mesh` commands are worker implementation details, not the documented entry points.

A failed output directory is kept for diagnosis and must not be reused. Local logs may contain local paths emitted by dependencies: do not publish them unreviewed. Metadata-free input copies preserve oriented pixels, not original EXIF or ICC metadata. EXIF orientation is applied; stripping an ICC profile can change interpretation for unusual color-managed inputs. Use sRGB PNG/JPEG for predictable colors.
