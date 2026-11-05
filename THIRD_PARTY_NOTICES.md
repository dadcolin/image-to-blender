# Third-party notices and acknowledgements

This is an independent community project. It is not an official Speridlabs, Meta, Black Forest Labs or Blender Foundation product, and no endorsement is claimed. Project-owned code is GPL-3.0-or-later; that declaration does not relicense the components below. See [docs/LICENSING.md](docs/LICENSING.md) for the distribution boundaries.

## IDOL

Image reconstruction is performed by **Speridlabs IDOL**, not by the mesh-conversion wrapper:

- [Official IDOL SDK](https://github.com/speridlabs/idol-sdk)
- [SDK Apache-2.0 license](https://github.com/speridlabs/idol-sdk/blob/4702a7f00850e34b6e83a2170cc123c3e9570744/LICENSE)
- [Official IDOL model card and weights](https://huggingface.co/speridlabs/idol)

The SDK revision inspected for this integration was `4702a7f00850e34b6e83a2170cc123c3e9570744`. Its license is Apache-2.0; the official IDOL model card separately labels its checkpoint Apache-2.0. Preserve upstream license and attribution notices when distributing upstream code. This project does not distribute IDOL checkpoints or claim authorship of IDOL's reconstruction model.

## Upstream model components

| Project | Credit and license source | Distribution here |
| --- | --- | --- |
| DINOv3 | Meta / [official repository and custom DINOv3 License](https://github.com/facebookresearch/dinov3/blob/main/LICENSE.md); [ViT-H+ model](https://huggingface.co/facebook/dinov3-vith16plus-pretrain-lvd1689m) | No weights or gated access credentials; obtain authorized upstream access separately. |
| FLUX.2 autoencoder | Black Forest Labs / [official separate Apache-2.0 autoencoder statement](https://github.com/black-forest-labs/flux2#flux2-autoencoder) | No weights. The separate autoencoder grant must not be attributed to the full dev model. See the serialization qualification in LICENSING.md. |
| FLUX.2-dev | Black Forest Labs / [full-model license](https://huggingface.co/black-forest-labs/FLUX.2-dev/blob/main/LICENSE.md) | Full-model weights are neither required nor distributed by this wrapper. |
| BiRefNet | ZhengPeng and contributors / [MIT code license, Copyright (c) 2024 ZhengPeng](https://github.com/ZhengPeng7/BiRefNet/blob/main/LICENSE); [official model card](https://huggingface.co/ZhengPeng7/BiRefNet) | No weights. IDOL's `birefnet.safetensors` is obtained from IDOL's own checkpoint repository; this notice does not assert binary identity with a different BiRefNet download. |

These acknowledgements do not grant additional model rights. The standalone pipeline's dependencies are not bundled into the self-contained mesh-import add-on.

## Blender and Python dependencies

[Blender](https://www.blender.org/) provides the mesh editing, scene and `.blend` capabilities. Its software license and trademarks remain with their respective holders; see [Blender licensing](https://www.blender.org/about/license/). The project's add-on uses Blender's public Python API. Blender itself is not redistributed by this repository.

The standalone CLI declares Python dependencies in `pyproject.toml`: NumPy, SciPy, scikit-image, plyfile, psutil and Pillow; tests additionally use pytest. Their implementations are installed separately, not copied into the add-on. A release that bundles dependency code or wheels must also carry the licenses and notices supplied by those exact distributions, including any vendored-library notices. This file is not a substitute for those full texts.

Official dependency license sources:

- [NumPy](https://github.com/numpy/numpy/blob/main/LICENSE.txt)
- [SciPy](https://github.com/scipy/scipy/blob/main/LICENSE.txt)
- [scikit-image](https://github.com/scikit-image/scikit-image/blob/main/LICENSE.txt)
- [plyfile](https://github.com/dranjan/python-plyfile/blob/master/COPYING)
- [psutil](https://github.com/giampaolo/psutil/blob/master/LICENSE)
- [Pillow](https://github.com/python-pillow/Pillow/blob/main/LICENSE)
- [pytest](https://github.com/pytest-dev/pytest/blob/main/LICENSE)

## Example assets

Example photographs, meshes and renders require their own recorded permission and asset license. They are not automatically covered by the project code license. No model weights, access tokens or personal configuration belong in an example archive. The Blender Extensions package should omit demonstration assets unless their required CC0 license has been explicitly established.

Reviewed: **2026-11-05**. Upstream licenses govern the actual versions obtained by each user.
