# Licensing and publication boundaries

Reviewed against the official sources below on **2026-11-05**. This document records the project's release choices and the evidence behind them; it does not replace upstream license terms or guarantee clearance of a particular image or result.

## Project code and the two distribution packages

Project-owned CLI and add-on code is licensed **GPL-3.0-or-later**, as declared in `pyproject.toml`; distribute it with the repository's full `LICENSE` text and preserve source notices. Third-party components retain their own licenses. See [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

The packages have different responsibilities:

| Package | Intended contents | Excluded contents |
| --- | --- | --- |
| Standalone GitHub CLI | Local artifact validation, Gaussian-to-mesh conversion, Blender export and verification; instructions for running the separate upstream IDOL workflow | Model weights, authentication tokens, user caches and private configuration |
| Self-contained Blender add-on | Import already-created local meshes and set dimensions using Blender's built-in Python interfaces | IDOL inference, model downloads, external Python or pip installation, NumPy dependency, shell/SSH helpers and external inference services |

The add-on must work with suitable local mesh files independently of IDOL. Its listing must describe **mesh import and dimensions**, not claim image-to-3D inference inside Blender. The independent CLI's requirements must not become hidden or optional dependencies of the platform add-on.

## Model and SDK licenses

| Component | Official evidence | Consequence for this project |
| --- | --- | --- |
| Speridlabs IDOL SDK | [Apache-2.0 license at the reviewed SDK revision](https://github.com/speridlabs/idol-sdk/blob/4702a7f00850e34b6e83a2170cc123c3e9570744/LICENSE) | Credit IDOL. If redistributing its code, include Apache-2.0, retain applicable notices, mark modifications and carry an upstream NOTICE when present. |
| IDOL checkpoint | [Official `speridlabs/idol` model card](https://huggingface.co/speridlabs/idol) labels the model `apache-2.0` | This label is not a license for every dependency. Obtain weights separately from upstream; do not bundle them here. |
| DINOv3 ViT-H+ | [Official model card](https://huggingface.co/facebook/dinov3-vith16plus-pretrain-lvd1689m), [DINOv3 License](https://github.com/facebookresearch/dinov3/blob/main/LICENSE.md), updated August 19, 2025 | Custom **DINOv3 License**, not Apache/MIT/GPL. Users must obtain authorized access and comply with that agreement. |
| FLUX.2 autoencoder | [BFL's autoencoder statement](https://github.com/black-forest-labs/flux2#flux2-autoencoder) explicitly identifies [the `ae.safetensors` checkpoint](https://huggingface.co/black-forest-labs/FLUX.2-dev/blob/main/ae.safetensors) | BFL says: **“The autoencoder is released under Apache 2.0.”** This is a component-specific grant. |
| Full FLUX.2-dev model | [Official model card](https://huggingface.co/black-forest-labs/FLUX.2-dev), [FLUX Non-Commercial License](https://huggingface.co/black-forest-labs/FLUX.2-dev/blob/main/LICENSE.md) | The full dev model has different terms; do not label it Apache-2.0. This workflow does not need its full diffusion transformer or text encoders. |
| BiRefNet | [Official code license](https://github.com/ZhengPeng7/BiRefNet/blob/main/LICENSE), [official model card](https://huggingface.co/ZhengPeng7/BiRefNet) | MIT; preserve the copyright and permission notice when distributing covered copies. |

### DINOv3 is a separate access and license boundary

The DINOv3 agreement permits use and modification subject to its conditions. Redistribution of DINO Materials and derivatives must remain under that agreement and include it. Research publications must acknowledge DINOv3. The agreement also contains trade-control, privacy, prohibited-end-use and reverse-engineering restrictions, warranty disclaimers and termination provisions. It is not a blanket non-commercial-only license, but neither is it an unrestricted Apache/MIT dependency. The GPL license on this wrapper does not relicense DINO Materials. Read the [actual agreement](https://github.com/facebookresearch/dinov3/blob/main/LICENSE.md) before use or redistribution.

### FLUX VAE: what was and was not verified

The reviewed IDOL SDK loads `AutoencoderKLFlux2` from the official repository's [`vae/` subdirectory](https://huggingface.co/black-forest-labs/FLUX.2-dev/tree/main/vae), rather than loading the full FLUX.2-dev pipeline. BFL's explicit separate Apache-2.0 statement names `ae.safetensors`. The full-model license also recognizes separately licensed elements.

This audit did **not** compare the tensors in the particular Diffusers `vae/diffusion_pytorch_model.safetensors` serialization with that explicitly linked checkpoint. Preserve the downloaded repository revision, exact file paths and this separate-license evidence in private run records. Do not present an unverified serialization comparison as completed, and verify the precise variant before any future weight redistribution. We distribute neither variant.

Do not conclude that the autoencoder is non-commercial merely from the parent repository's license label; do not extend its Apache grant to the entire FLUX.2-dev model either. Download gating and the license applying to an individual component are distinct questions.

## Input images, generated meshes and examples

The GPL license on the code does not by itself license input photographs, reference artwork, textures, model weights or generated `.blend` files. Blender likewise distinguishes its software license from artwork made with it: see [Blender's license explanation](https://www.blender.org/about/license/).

The contributor has confirmed authority to publish the lamp input and generated example results. That confirmation is not a universal clearance for future uploads, a transfer of third-party trademarks or an automatic CC0 dedication. Give each published example an explicit asset license and provenance. **Do not bundle example images, meshes or renders in the extension ZIP unless the necessary CC0 grant has been explicitly established.** The add-on can be distributed without these assets.

Model license labels do not guarantee that a particular output is non-infringing or free of portrait, trademark or input-image restrictions. A mesh conversion also does not create new permission to reuse its source image. Do not describe all pipeline dependencies or all results as universally cleared for commercial use.

## Blender Extensions submission

The [platform Terms of Service](https://extensions.blender.org/terms-of-service/) were last updated August 10, 2026. Relevant requirements are:

- Add-ons must comply with GPLv3-or-later; included binary/art assets must be CC0, with required credits in the manifest (§1).
- Do not put “Blender” in the extension name, use its logo in extension promotional graphics or imply endorsement (§2).
- Ship reviewable, functional Python code. External registrations or keys must not block functionality (§3).
- Network use needs declared permission and must respect `bpy.app.online_access`; sending user data needs authorization (§4).
- Packages must be self-contained, without downloaded external functional components or remote code, even for optional features (§5).

Accordingly, only the independent local mesh add-on is a candidate for this platform. The external IDOL/Torch/model workflow is not part of its ZIP or advertised functionality. This separation is a release design, **not a promise of acceptance**.

The [official publishing guide](https://extensions.blender.org/about/) requires upload followed by review. The [upload entry](https://extensions.blender.org/submit/) redirects unauthenticated visitors to Blender ID; an authorized maintainer must sign in and submit the validated package. Follow the [add-on guidelines](https://developer.blender.org/docs/handbook/extensions/addon_guidelines/) and [moderation guidelines](https://developer.blender.org/docs/features/extensions/moderation/guidelines/). Do not mark a release approved until its actual review succeeds.

A community listing is different from an official Blender-maintained repository. [Blender's hosting policy](https://developer.blender.org/docs/handbook/extensions/hosted/) normally recommends a personal or external repository; official hosting is reserved for specific maintenance circumstances. This project's GitHub repository is independent. Link to [IDOL](https://github.com/speridlabs/idol-sdk) and [Blender](https://www.blender.org/) as upstream projects; use descriptive repository topics such as `blender-addon`, `image-to-3d` and `idol`, without claiming either project's endorsement.

## Release checks

Before distributing a source archive, wheel or add-on ZIP:

1. Include the full project license and applicable third-party notices; inspect the actual packaged files, not only the source tree.
2. Exclude checkpoints, download caches, credentials, machine-specific configuration and private run data.
3. Keep the standalone CLI dependency environment outside the add-on package. Do not install it from inside Blender.
4. Record licenses for any deliberately included assets. A public image URL alone is not permission to redistribute or dedicate it to CC0.
5. Recheck upstream license revisions and platform rules when changing models, dependencies, assets or packaging.
