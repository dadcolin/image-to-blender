# SPDX-License-Identifier: GPL-3.0-or-later
"""Portable pipeline; never stops services, connects by SSH, or retries models."""
import argparse
from pathlib import Path
import shutil
import sys

from .dimensions import add_dimension_arguments, spec_from_args
from .runner import guarded
from .validation import artifact_record, write_json_new


def dimension_argv(args):
    spec = spec_from_args(args)
    if spec is None:
        return []
    values = (["--dimensions", *map(str, args.dimensions)] if args.dimensions else
              ["--dimension-axis", args.dimension_axis, "--dimension-value", str(args.dimension_value)])
    return values + ["--unit", args.unit, "--dimension-purpose", args.dimension_purpose]


def export_blend(manifest, output, blender, dimensions, max_memory_gib=1.5, min_available_gib=2):
    from . import blender_export
    executable = shutil.which(str(blender))
    if not executable:
        raise FileNotFoundError("Blender executable not found")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    blend = output / "model.blend"
    prefix = [executable, "--background", "--factory-startup", "--disable-autoexec", "--threads", "2",
              "--python-exit-code", "1", "--python", str(Path(blender_export.__file__).resolve()), "--"]
    limits = dict(max_memory_gib=max_memory_gib, min_available_gib=min_available_gib)
    stages = [guarded(prefix + ["--manifest", str(Path(manifest).resolve()), "--output", str(blend),
                               *dimensions], output, "export", **limits)]
    stages.append(guarded(prefix + ["--verify", "--blend", str(blend), "--receipt", str(blend) + ".json",
                                   "--report", str(output / "reopen.json")], output, "reopen", **limits))
    write_json_new(output / "result.json", {"schema_version": 1, "status": "exported_and_reopened",
                                           "blend": artifact_record(blend, output), "stages": stages,
                                           "visual_qa_approved": False})
    return blend


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    for name in ("reconstruct", "_infer"):
        p = sub.add_parser(name, help="Image to native IDOL data and mesh" if name == "reconstruct" else argparse.SUPPRESS)
        p.add_argument("image")
        p.add_argument("--output", required=True)
        p.add_argument("--background", choices=("white", "alpha"), default="white")
        p.add_argument("--matting-hook", help="Explicit trusted Python module:function returning RGBA")
        p.add_argument("--weights", help="Existing IDOL weight directory; otherwise downloads the pinned revision")
        p.add_argument("--device", default="cuda")
        p.add_argument("--seed", type=int, default=42)
        p.add_argument("--steps", type=int, default=50)
        p.add_argument("--num-gaussians", type=int, default=262144)
        p.add_argument("--crop-margin", type=float, default=1.7)
        p.add_argument("--inference-min-free-gib", type=float, default=16)
        if name == "reconstruct":
            p.add_argument("--inference-max-rss-gib", type=float, default=24)
            p.add_argument("--inference-timeout", type=float, default=1800)
            p.add_argument("--blender", help="Optionally export/reopen a .blend here after reconstruction")
            add_dimension_arguments(p)
    for name in ("mesh", "_mesh"):
        p = sub.add_parser(name)
        p.add_argument("--source-manifest", required=True)
        p.add_argument("--output", required=True)
        p.add_argument("--resolution", type=int, default=256)
        p.add_argument("--iso-level", type=float, default=0.5)
        p.add_argument("--max-memory-gib", type=float, default=1.5)
        p.add_argument("--min-available-gib", type=float, default=2)
    p = sub.add_parser("export", help="Reuse an existing mesh; no model inference")
    p.add_argument("--mesh-manifest", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--blender", required=True)
    p.add_argument("--max-memory-gib", type=float, default=1.5)
    p.add_argument("--min-available-gib", type=float, default=2)
    add_dimension_arguments(p)
    return root


def mesh_stage(source, output, *, resolution=256, iso_level=0.5, max_memory_gib=1.5, min_available_gib=2):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    guarded([sys.executable, "-B", "-m", "image_to_blender.cli", "_mesh", "--source-manifest", str(source),
             "--output", str(output / "mesh"), "--resolution", str(resolution), "--iso-level", str(iso_level),
             "--max-memory-gib", str(max_memory_gib), "--min-available-gib", str(min_available_gib)],
            output, "density", max_memory_gib=max_memory_gib, min_available_gib=min_available_gib)
    return output / "mesh" / "mesh-manifest.json"


def main(argv=None):
    args = parser().parse_args(argv)
    if args.command == "_infer":
        from .inference import infer
        result = infer(args.image, args.output, background=args.background, hook=args.matting_hook,
                       weights=args.weights, device=args.device, seed=args.seed, steps=args.steps,
                       num_gaussians=args.num_gaussians, crop_margin=args.crop_margin,
                       min_available_gib=args.inference_min_free_gib)
    elif args.command == "_mesh":
        from .mesh import reconstruct, MeshConfig
        result = reconstruct(args.source_manifest, args.output,
                             MeshConfig(resolution=args.resolution, iso_level=args.iso_level,
                                        max_memory_gib=args.max_memory_gib, min_available_gib=args.min_available_gib))
    elif args.command == "mesh":
        result = mesh_stage(Path(args.source_manifest).resolve(), args.output, resolution=args.resolution,
                            iso_level=args.iso_level, max_memory_gib=args.max_memory_gib,
                            min_available_gib=args.min_available_gib)
    elif args.command == "export":
        result = export_blend(args.mesh_manifest, args.output, args.blender, dimension_argv(args),
                              args.max_memory_gib, args.min_available_gib)
    else:
        dims = dimension_argv(args)
        if dims and not args.blender:
            raise ValueError("Dimensions are applied at Blender export; supply --blender or use export later")
        output = Path(args.output).resolve()
        output.mkdir(parents=True, exist_ok=False)
        cmd = [sys.executable, "-B", "-m", "image_to_blender.cli", "_infer", str(Path(args.image).resolve()),
               "--output", str(output / "native"), "--background", args.background, "--device", args.device,
               "--seed", str(args.seed), "--steps", str(args.steps), "--num-gaussians", str(args.num_gaussians),
               "--crop-margin", str(args.crop_margin), "--inference-min-free-gib", str(args.inference_min_free_gib)]
        for key, value in (("--weights", args.weights), ("--matting-hook", args.matting_hook)):
            if value:
                cmd.extend((key, value))
        guarded(cmd, output, "inference", max_memory_gib=args.inference_max_rss_gib,
                min_available_gib=args.inference_min_free_gib, timeout_seconds=args.inference_timeout)
        result = mesh_stage(output / "native" / "source-manifest.json", output / "derived")
        if args.blender:
            result = export_blend(result, output / "blender", args.blender, dims)
    print(str(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
