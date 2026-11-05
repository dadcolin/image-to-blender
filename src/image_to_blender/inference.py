# SPDX-License-Identifier: GPL-3.0-or-later
"""Adapter for the separately installed, Apache-2.0 IDOL SDK. No weights bundled."""
from datetime import datetime, timezone
import importlib.metadata
import math
from pathlib import Path
import time

from .preprocess import prepare_input
from .validation import artifact_record, sha256, write_json_new

IDOL_REVISION = "2731c2291fc65a797c5cb627a5e5526fc1490902"
SDK_REVISION = "4702a7f00850e34b6e83a2170cc123c3e9570744"
WEIGHT_NAMES = ("config.json", "denoiser.safetensors", "decoder.safetensors",
                "decoder_gs.safetensors", "birefnet.safetensors")


def infer(image, output_dir, *, background="white", hook=None, weights=None,
          revision=IDOL_REVISION, device="cuda", seed=42, steps=50,
          num_gaussians=262144, crop_margin=1.7, cfg_strength=3.0,
          min_available_gib=16.0):
    """Run once, preserving pixels, native PLY and relative-path provenance.

    No service control or remote execution. A model/driver error is propagated;
    never automatically retry. A CPU caller must explicitly select device=cpu.
    """
    import psutil
    if not math.isfinite(min_available_gib) or min_available_gib <= 0:
        raise ValueError("Available-memory floor must be finite and positive")
    if psutil.virtual_memory().available < min_available_gib * 2**30:
        raise MemoryError("Insufficient available RAM; no model loaded")
    if not 1 <= steps <= 1000 or not 32768 <= num_gaussians <= 1048576 or num_gaussians % 32:
        raise ValueError("Invalid sampling steps or Gaussian count")
    if not math.isfinite(crop_margin) or crop_margin < 1 or not math.isfinite(cfg_strength):
        raise ValueError("Invalid crop margin or CFG strength")
    prepared = prepare_input(image, background, hook)
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    prepared.save(output / "source.png")
    started = time.monotonic()
    try:
        import torch
        import idol.pipeline as sdk
        from idol.models import layers
        if device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError("CUDA is unavailable; no implicit CPU fallback")
        if weights is None:
            from huggingface_hub import snapshot_download
            weights = snapshot_download("speridlabs/idol", revision=revision,
                                        allow_patterns=list(WEIGHT_NAMES))
        weight_dir = Path(weights)
        weight_hashes = {name: sha256(weight_dir / name) for name in WEIGHT_NAMES}
        layers.ATTN_BACKEND = "sdpa"
        pipe = sdk.IdolPipeline.from_pretrained(str(weight_dir), device=device,
                                                dinov3_dtype="bf16", optimize=False)
        result = pipe(prepared, mode="real", seed=seed, steps=steps,
                      num_gaussians=num_gaussians, crop_margin=crop_margin,
                      cfg_strength=cfg_strength, rescale_t=3.0)
        ply = output / "native.ply"
        result.gaussian.save_ply(str(ply))
        # Pixel-only output, with no metadata from the caller's input file.
        from PIL import Image
        encoded = result.preprocessed_image.convert("RGB")
        Image.frombytes("RGB", encoded.size, encoded.tobytes()).save(output / "model-input.png")
        versions = {}
        for package in ("idol", "torch", "torchvision", "transformers", "diffusers", "numpy", "Pillow"):
            try:
                versions[package] = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                versions[package] = "unknown"
        record = {
            "schema_version": 1, "kind": "gaussian_source", "format": "idol_standard_3dgs",
            "axis": "y_up", "artifact": artifact_record(ply, output), "gaussian_count": num_gaussians,
            "input": artifact_record(output / "source.png", output),
            "model_input": artifact_record(output / "model-input.png", output),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "model": {"repo": "speridlabs/idol", "weight_sha256": weight_hashes,
                      "sdk_pipeline_sha256": sha256(sdk.__file__), "versions": versions},
            "parameters": {"seed": seed, "steps": steps, "num_gaussians": num_gaussians,
                           "crop_margin": crop_margin, "cfg_strength": cfg_strength,
                           "rescale_t": 3.0, "mode": "real", "optimize": False,
                           "attention": "sdpa", "input_background": background,
                           "external_matting_used": bool(hook)},
            "camera": result.camera, "elapsed_seconds": round(time.monotonic() - started, 3),
            "automatic_retry": False, "geometry_accuracy_approved": False,
        }
        write_json_new(output / "source-manifest.json", record)
        return output / "source-manifest.json"
    except BaseException as error:
        write_json_new(output / "failure.json", {"stage": "inference", "error_type": type(error).__name__,
                                                 "automatic_retry": False})
        raise
