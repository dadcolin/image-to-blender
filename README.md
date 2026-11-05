# Image to Blender

**English** | [简体中文](README.zh-CN.md)

**Reconstruct an object from an image with [Speridlabs IDOL](https://github.com/speridlabs/idol-sdk), then convert its Gaussian representation into an editable triangle mesh and a [Blender](https://www.blender.org/) `.blend` file.**

An experimental workflow for single-object product images, such as furniture and lamps. Start with a **white-background image or a PNG cutout with transparency**. An explicit, replaceable matting hook lets you use another background-removal tool.

This independent project uses **IDOL for image reconstruction** and **Blender for mesh editing and `.blend` export**. It does not train a new reconstruction model. It is not an official Speridlabs IDOL or Blender Foundation project. [@blender](https://github.com/blender) is credited as an upstream project, not as an endorsement.

## A real lamp test

| Input, shared with the contributor's permission | Mesh preview from the actual IDOL result |
| --- | --- |
| ![White-background lamp photograph](examples/lamp/lamp-reference.png) | ![Actual derived lamp mesh](examples/lamp/lamp-IDOL-preview.png) |

See the [lamp example and downloads](examples/lamp/README.md) and [measured environment and timings](docs/BENCHMARKS.md). The example comes from real model inference on DGX Spark; a manually constructed object was not substituted for the model result. Public copies have private metadata removed. Existing meshes can be resized without repeating inference.

**This is approximate reconstruction, not dimensionally accurate CAD, clean topology, or a print-ready part.** A single image cannot establish hidden geometry. Thin rods, gaps, planes, rectangular angles, text, and metallic surfaces can be reconstructed incorrectly. The lamp example retains fragments and boundary edges rather than hiding them for presentation. Vertex colors are baked appearance, not separated PBR materials. Dimension controls constrain the bounding box; they do not automatically correct shear or recover unknown structure.

## Two ways to use it

1. **Standalone Python workflow:** image → native IDOL 3DGS → anisotropic density field / Marching Cubes → mesh → `.blend`. Reconstruction can run on Spark while mesh import and export run in Windows Blender.
2. **Separately installed Blender add-on:** import a local mesh bundle and set dimensions for an entire object or manually selected vertices. It works offline using Blender's built-in Python. It does not run IDOL, install Torch, or download models. The add-on ZIP does not include example assets.

The current distribution is an independent GitHub project and add-on ZIP. **It has not been approved or listed on the official Blender Extensions platform.** See [submission and licensing boundaries](docs/LICENSING.md#blender-extensions-submission). The external model runtime is not intended for submission to Blender's main source repository.

## Install the Blender add-on

Download `idol_mesh_tools-0.1.0.zip` from [Releases](https://github.com/dadcolin/image-to-blender/releases). In Blender 4.2+, open **Preferences → Add-ons → Install from Disk**, select the ZIP, and enable **IDOL Mesh Tools**. Blender 4.2 is the declared minimum; see [validation details](docs/VALIDATION.md) for the version actually tested.

- Open the **IDOL** sidebar in the 3D View, or **File → Import → IDOL Derived Mesh**.
- Select `mesh-manifest.json` from a complete mesh bundle. Keep its referenced `mesh-data.json` and `source/` at their original relative locations. Import is rejected if file hashes do not match.
- **Object Mode:** set dimensions for the entire active mesh.
- **Edit Mode:** manually select vertices for a part, such as the shade or base, then size that selection. Unselected vertices are preserved. There is no automatic semantic segmentation; local scaling can stretch connecting geometry and needs inspection.
- **Preserve proportions:** choose X, Y, or Z (height) and scale uniformly.
- **Fit X / Y / Z:** independently match three axis extents, which can change proportions. X and Y are world axes; the add-on does not infer a product's “length” and “width.”
- Units: **mm / cm / m**. Operations support Undo. The add-on does not overwrite or automatically save the current file; save your own `.blend` copy.

Dimension operations reject meshes with modifiers, shape keys, shared mesh data, or multi-object Edit Mode. This avoids treating the base mesh's dimensions as the final visible result.

## Install the standalone converter

Requires **Python 3.11+**. Use a dedicated virtual environment, separate from Blender's Python:

```bash
git clone https://github.com/dadcolin/image-to-blender.git
cd image-to-blender
python -m venv .venv
# Linux: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e '.[test]'
```

Only image inference requires IDOL and Torch. Follow the [official IDOL instructions](https://github.com/speridlabs/idol-sdk) to install a CUDA-compatible PyTorch build for your platform, then install the SDK revision inspected for this integration:

```bash
python -m pip install 'idol @ git+https://github.com/speridlabs/idol-sdk.git@4702a7f00850e34b6e83a2170cc123c3e9570744'
```

Dependency installation may change the PyTorch version; review the install plan first. Spark/aarch64 needs builds for that platform, not x86 wheels. The versions used in the reference run are recorded in [BENCHMARKS.md](docs/BENCHMARKS.md).

Obtain model weights from upstream; they are not distributed in this repository. DINOv3 and FLUX dependencies require your own valid upstream access. Configure access using local Hugging Face login tools as directed upstream. **Do not put tokens in command examples, issues, or the repository.** The IDOL checkpoint revision is pinned; encoder dependencies are loaded from the upstream configuration and may download on first use. Read [component licensing](docs/LICENSING.md): the code's GPL license does not make every model or image unrestricted for commercial use.

## Reconstruct and export

Use one complete object on a white or transparent background. Keep thin structures and outer edges visible. Exclude product-page text, dimension arrows, watermarks, and unrelated objects. Process only images you have permission to use.

```bash
# GPU machine: one inference run, with hash-bound native/ and derived/mesh/ artifacts
python -B -m image_to_blender.cli reconstruct lamp.png --background white --output outputs/lamp-01

# Existing cutout: requires actual transparency; skips IDOL's BiRefNet mask inference
python -B -m image_to_blender.cli reconstruct cutout.png --background alpha --output outputs/lamp-02

# Export on the same machine if Blender is available; adjust the executable path as needed
python -B -m image_to_blender.cli reconstruct lamp.png --output outputs/lamp-03 --blender blender
```

The current IDOL SDK still loads BiRefNet during initialization, even with an alpha input. Skipping its mask inference does not eliminate that loading or memory cost. Defaults are eager / SDPA execution, 50 steps, 262,144 Gaussians, seed 42, real-image mode, and crop margin 1.7. Failed inference is not automatically retried.

If the GPU is on Spark and Blender is on Windows, copy the **entire `derived/mesh/` directory** to Windows, then import it with the add-on or use the CLI below. Transfer is the operator's responsibility; this repository contains no personal SSH configuration, server addresses, or service start/stop logic.

```bash
# Reuse a generated mesh and uniformly scale it to a height of 500 mm
python -B -m image_to_blender.cli export --mesh-manifest outputs/lamp-01/derived/mesh/mesh-manifest.json --blender blender --output outputs/lamp-height-500 --dimension-axis z --dimension-value 500 --unit mm --dimension-purpose user-specified

# Fit three bounding-box extents: changes proportions, not an automatic structural correction
python -B -m image_to_blender.cli export --mesh-manifest outputs/lamp-01/derived/mesh/mesh-manifest.json --blender blender --output outputs/lamp-xyz --dimensions 300 250 500 --unit mm --dimension-purpose user-specified

# Extract another mesh without repeating inference; experiment with resolution and density threshold
python -B -m image_to_blender.cli mesh --source-manifest outputs/lamp-01/native/source-manifest.json --output outputs/lamp-new-mesh --resolution 256 --iso-level 0.5
```

Each output directory must not already exist. Export starts a fresh Blender process to reopen the file and verify vertices, faces, colors, Edit Mode, and actual bounding-box dimensions. These are technical checks, not visual acceptance. Keep the native Gaussians and artifact manifests so the source can be independently checked. See [workflow and geometry details](docs/WORKFLOW.md).

## Replaceable background-removal hook

By default, white-background images use IDOL's bundled BiRefNet. To use another matting tool, provide a Python module you trust:

```python
# my_matting.py (place on your Python import path)
def remove_background(image):
    # Plug in your separately installed matting model here.
    # Return a PIL RGBA image with both transparent and visible pixels.
    raise NotImplementedError
```

Explicitly pass `--matting-hook my_matting:remove_background` to `reconstruct`. The hook runs only in the standalone inference process, never in the Blender add-on. It is executable Python code and runs only when you explicitly select it. The program does not discover, download, or install third-party matting code.

## Test more objects

One lamp does not establish accuracy across furniture or other object classes. Contributions with white-background lamps, bookshelves, chairs, and other objects are welcome. Follow [CONTRIBUTING.md](CONTRIBUTING.md) and [the case template](examples/case-template.json): retain image permission, input SHA, seed, settings, per-stage timings, geometry metrics, and observations from multiple views. Include failures as well as attractive results. Do not report dimensional accuracy without real measurements.

## Development, status, and licensing

```bash
python -B -m pytest -q
blender --command extension build --source-dir extension/idol_mesh_tools --output-dir dist
blender --command extension validate dist/idol_mesh_tools-0.1.0.zip
```

See [GitHub Actions](https://github.com/dadcolin/image-to-blender/actions) for current status. [CI setup documentation](docs/ci/README.md) describes the workflow setup; [VALIDATION.md](docs/VALIDATION.md) records local checks and their limits. This README does not assert that the latest CI run passed.

Project code is [GPL-3.0-or-later](LICENSE). Credits and licensing boundaries for IDOL, DINOv3, FLUX VAE, BiRefNet, and Blender are documented in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and [LICENSING.md](docs/LICENSING.md). Example assets have separate permission statements; they are not automatically distributed under the code's GPL license or CC0.
