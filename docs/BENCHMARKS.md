# Measured reference workflow

These are observations from completed runs on 2026-11-05, not a sustained throughput benchmark or a guarantee for this package. The reference workflow used the same IDOL-to-density-mesh approach before it was packaged here. The [lamp example provenance](../examples/lamp/provenance.json) identifies the input, model revisions, extraction parameters, and output geometry. No first-time downloads or installation time is included.

## Environment

| Stage | Recorded environment |
| --- | --- |
| Image to native 3DGS | NVIDIA DGX Spark, NVIDIA GB10, Linux aarch64; OS-reported total memory 124,610 MiB (about 121.7 GiB) |
| GPU runtime | PyTorch 2.13.0+cu130, torchvision 0.28.0+cu130, CUDA build 13.0 |
| Model stack | transformers 5.22.1, diffusers 0.42.1, huggingface_hub 2.4.0, safetensors 0.8.0, tensordict 0.15.4 |
| Inference data packages | NumPy 2.4.6, Pillow 13.0.0, plyfile 1.1.5 |
| Mesh extraction | Separate Windows workstation, CPU; Python 3.13.14, NumPy 2.5.4, SciPy 1.18.1, scikit-image 0.26.0, plyfile 1.1.5, psutil 7.2.2 |
| Blender export and reopen | Windows, Blender 5.2.3 LTS in background mode, two threads, script auto-execution disabled |

The GPU environment's Python patch version and the Windows CPU model were not captured in the retained timing receipts. The figures therefore should not be treated as fully specified hardware comparisons. No GPU was used for the local mesh extraction/export measurements.

IDOL SDK commit: `4702a7f00850e34b6e83a2170cc123c3e9570744`.

| Model | Revision |
| --- | --- |
| `speridlabs/idol` | `2731c2291fc65a797c5cb627a5e5526fc1490902` |
| `facebook/dinov3-vith16plus-pretrain-lvd1689m` | `c807c9eeea853df70aec4069e6f56b28ddc82acc` |
| `black-forest-labs/FLUX.2-dev` (VAE only) | `26afe3a78bb242c0a8bb181dcc8937bb16e5c66c` |

The lamp used a 401 × 498 real photograph, crop margin 1.7, seed 42, 50 steps, guidance 3.0, time rescale 3.0, and 262,144 output Gaussians. DINOv3 used bfloat16; attention was SDPA, `optimize=False`, with no `torch.compile`. Mesh extraction used resolution 256³, isovalue 0.5, minimum opacity 0.005, and 3-sigma support. PyTorch recorded peak allocated/reserved memory of 5,375,304,704 / 7,589,593,088 bytes; these allocator counters are not whole-system memory usage.

## What was timed

| Measurement | Seconds | Included work |
| --- | ---: | --- |
| Lamp: image to native 3DGS | **72.624** | Model construction/loading, preprocessing, inference, native export and validation, cleanup |
| Lamp: existing 3DGS to dimensioned `.blend` | **59.870** | CPU density/mesh extraction, illustrative XYZ sizing, Blender save, fresh-process reopen checks |
| Lamp: existing mesh to resized `.blend` | **14.179** | Reuse of cached mesh, illustrative height scaling, Blender save, fresh-process reopen checks |

The last two rows are **alternative starting points**, not sequential stages. Neither runs the neural model. The 59.870-second row includes subprocess phases of 49.041 seconds for extraction, 6.075 for export, and 4.746 for reopen; the small remainder is orchestration overhead. The 14.179-second row includes 8.587 seconds for export and 5.584 for reopen. Do not add those nested phase values to their totals.

The sizing tests used demonstration values, not measurements of the physical lamp: one set X/Y/Z to 300/250/500 mm; the other uniformly scaled the Z extent to 500 mm. They verify export/scaling behavior, not dimensional reconstruction accuracy. The published lamp example retains the original, uncalibrated model proportions and has no dimension constraint applied.

For the original unsized lamp export shown in this repository, separately measured serial phases were:

| Phase | Seconds |
| --- | ---: |
| Density mesh extraction, numerical checks and writes | 51.851 |
| Blender import and save | 12.384 |
| Fresh-process reopen and Edit Mode verification | 3.149 |
| Twelve review renders | 11.832 |
| Total of these four phases | **79.216** |

The first three phases total 67.384 seconds without review renders. This was an earlier local execution path; do not combine it with the alternative 59.870- or 14.179-second export measurements. The original mesh process recorded a peak RSS of 313,266,176 bytes; conservative admission estimates and available system memory can still delay execution.

## End-to-end expectations and limits

After the native lamp result was completed, restoration and health checks for co-resident serving workloads took another **227.590 seconds** in this run. That interval also includes worker exit and controller polling; it is not a measurement of one model's loading time. Adding the native 72.624 seconds, this restoration interval, and the original local 79.216 seconds gives **379.430 seconds (6 min 19.4 sec)** for those selected serial phases. Network transfer, admission/queue time, and manual visual inspection were not separately timed and are not included in that sum.

Under comparable idle resources with weights already present, a practical planning budget was **6–8 minutes for a new image including workload restoration**, or **1–2 minutes to export an existing native 3DGS result**. These are planning ranges from a small sample, not latency guarantees. The 14.179-second cached-mesh operation is one measured resize/export, not a promise for arbitrary meshes.

The earlier two-image table/character run took 141.918 seconds in total with one model construction. Its table and character CPU mesh extractions took 22.970 and 25.155 seconds respectively. This does not establish warm-batch throughput: the inputs differ, the sample is tiny, and no sustained prewarmed batch benchmark was run. No images-per-hour claim is made.

Excluded from these timing figures: dependency installation, gated-model approval and downloads, human authentication waits, queue/drain waits, debugging failures, memory contention pauses, network transfer, and manual visual review. Model loading is already inside the native timer; density sampling and marching cubes are already inside the mesh timer. Adding them again would double-count work.
