# SPDX-License-Identifier: GPL-3.0-or-later
"""Anisotropic Gaussian-density mesh approximation, not native model geometry."""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import math
from pathlib import Path
import shutil
import time

import numpy as np

from .validation import artifact_record, sha256, validate_source_manifest, write_json_new

SH_C0 = 0.28209479177387814


@dataclass(frozen=True)
class MeshConfig:
    resolution: int = 256
    iso_level: float = 0.5
    min_opacity: float = 0.005
    cutoff_sigma: float = 3.0
    tile_voxels: int = 32768
    max_voxel_evaluations: int = 1_000_000_000
    max_faces: int = 2_000_000
    max_extent: float = 4.0
    max_memory_gib: float = 1.5
    min_available_gib: float = 2.0

    def validate(self):
        if isinstance(self.resolution, bool) or not isinstance(self.resolution, int) or not 16 <= self.resolution <= 512:
            raise ValueError("Grid resolution must be an integer between 16 and 512")
        if not all(math.isfinite(value) for value in (self.iso_level, self.min_opacity, self.cutoff_sigma,
                                                     self.max_extent, self.max_memory_gib, self.min_available_gib)):
            raise ValueError("Mesh settings must be finite")
        if self.iso_level <= 0 or not 0 <= self.min_opacity < 1 or not 1 <= self.cutoff_sigma <= 6:
            raise ValueError("Invalid density, opacity, or cutoff")
        if self.max_extent <= 0 or self.max_memory_gib <= 0 or self.min_available_gib < 0:
            raise ValueError("Invalid extent or memory limits")
        for value, low, high in ((self.tile_voxels, 64, 262144), (self.max_faces, 4, 20_000_000),
                                 (self.max_voxel_evaluations, 1, 100_000_000_000)):
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise ValueError("Invalid integer work limit")


def native_ply_data(path):
    from plyfile import PlyData
    ply = PlyData.read(str(path), mmap=True)
    if [element.name for element in ply.elements] != ["vertex"]:
        raise ValueError("Expected vertex-only standard 3DGS PLY, not a triangle mesh")
    data = ply["vertex"].data
    required = ["x", "y", "z", "opacity", *[f"scale_{i}" for i in range(3)],
                *[f"rot_{i}" for i in range(4)], *[f"f_dc_{i}" for i in range(3)]]
    if not len(data) or not set(required).issubset(data.dtype.names or ()):
        raise ValueError("PLY is missing standard3DGS position/log-scale/wxyz/logit-opacity/SH0 fields")
    if any(data[name].dtype.kind != "f" for name in required):
        raise ValueError("Standard3DGS fields must be floating point")
    return data


def _resource_check(config, process, cancel):
    import psutil
    if cancel is not None and cancel.is_set():
        raise InterruptedError("Mesh reconstruction cancelled")
    rss = process.memory_info().rss
    available = psutil.virtual_memory().available
    if rss > config.max_memory_gib * 2**30 or available < config.min_available_gib * 2**30:
        raise MemoryError("Local reconstruction exceeded its configured RAM guard")
    return rss

def quaternion_matrices(quaternions, np):
    q = np.asarray(quaternions, dtype=np.float64)
    lengths = np.linalg.norm(q, axis=1)
    if not np.isfinite(q).all() or np.any(lengths < 1e-10):
        raise ValueError("Invalid Gaussian quaternion")
    q = q / lengths[:, None]
    w, x, y, z = q.T
    matrix = np.empty((len(q), 3, 3), dtype=np.float64)
    matrix[:, 0, 0] = 1 - 2 * (y*y + z*z)
    matrix[:, 0, 1] = 2 * (x*y - w*z)
    matrix[:, 0, 2] = 2 * (x*z + w*y)
    matrix[:, 1, 0] = 2 * (x*y + w*z)
    matrix[:, 1, 1] = 1 - 2 * (x*x + z*z)
    matrix[:, 1, 2] = 2 * (y*z - w*x)
    matrix[:, 2, 0] = 2 * (x*z - w*y)
    matrix[:, 2, 1] = 2 * (y*z + w*x)
    matrix[:, 2, 2] = 1 - 2 * (x*x + y*y)
    return matrix


def decode_gaussians(data, min_opacity, cutoff, np):
    def columns(names):
        return np.column_stack([data[name] for name in names]).astype(np.float64)

    centers = columns(("x", "y", "z"))
    scales_log = columns(("scale_0", "scale_1", "scale_2"))
    opacity_logit = np.asarray(data["opacity"], dtype=np.float64)
    if not all(np.isfinite(a).all() for a in (centers, scales_log, opacity_logit)):
        raise ValueError("Non-finite Gaussian attributes")
    z = np.exp(-np.abs(opacity_logit))
    alpha = np.where(opacity_logit >= 0, 1 / (1 + z), z / (1 + z))
    keep = alpha >= min_opacity
    if not keep.any():
        raise ValueError("Opacity threshold excludes every Gaussian")
    centers, alpha, scales_log = centers[keep], alpha[keep], scales_log[keep]
    with np.errstate(over="raise", divide="raise", invalid="raise"):
        scales = np.exp(scales_log)
        if np.any(scales <= 0):
            raise ValueError("Invalid Gaussian scale")
        rotations = quaternion_matrices(columns(("rot_0", "rot_1", "rot_2", "rot_3"))[keep], np)
        inverse_cov = (rotations * (1 / scales**2)[:, None, :]) @ rotations.transpose(0, 2, 1)
        extents = cutoff * np.sqrt(np.sum(rotations**2 * (scales**2)[:, None, :], axis=2))
    coefficients = columns(("f_dc_0", "f_dc_1", "f_dc_2"))[keep]
    if not np.isfinite(coefficients).all() or not np.isfinite(extents).all() or not np.isfinite(inverse_cov).all():
        raise ValueError("Invalid covariance or SH attributes")
    colors_unclipped = 0.5 + SH_C0 * coefficients
    colors = np.clip(colors_unclipped, 0, 1)
    stats = {"source_gaussians": len(data), "retained_gaussians": len(centers),
             "opacity_filtered_gaussians": int((~keep).sum()),
             "color_values_clipped": int(((colors_unclipped < 0) | (colors_unclipped > 1)).sum())}
    return centers, alpha, inverse_cov, extents, colors, stats


def grid_layout(centers, extents, resolution, max_extent, np):
    low = (centers - extents).min(axis=0)
    high = (centers + extents).max(axis=0)
    longest = float((high - low).max())
    if not math.isfinite(longest) or longest <= 0 or longest > max_extent:
        raise ValueError("Gaussian support bounds exceed the configured extent limit")
    # A cubic isotropic grid keeps geometry proportions and includes two empty
    # guard voxels at every end of the largest support bounding interval.
    side = longest / (1 - 4 / (resolution - 1))
    origin = (low + high) / 2 - side / 2
    spacing = side / (resolution - 1)
    start = np.clip(np.ceil((centers - extents - origin) / spacing).astype(np.int64), 0, resolution - 1)
    stop = np.clip(np.floor((centers + extents - origin) / spacing).astype(np.int64), 0, resolution - 1)
    sizes = np.maximum(stop - start + 1, 0)
    candidates = np.prod(sizes, axis=1, dtype=np.int64)
    return origin, spacing, start, stop, candidates


def accumulate_gaussian(field, color_field, center, alpha, precision, color, start, stop,
                        origin, spacing, cutoff, tile_voxels, np):
    if np.any(stop < start):
        return
    # Three-dimensional tiles prevent an oversized XY plane from evading the
    # temporary-memory cap. No grid脳Gaussian broadcast is ever allocated.
    edge = max(1, int(tile_voxels ** (1 / 3)))
    for x0 in range(int(start[0]), int(stop[0]) + 1, edge):
        x1 = min(x0 + edge, int(stop[0]) + 1)
        dx = (origin[0] + np.arange(x0, x1) * spacing - center[0])[:, None, None]
        for y0 in range(int(start[1]), int(stop[1]) + 1, edge):
            y1 = min(y0 + edge, int(stop[1]) + 1)
            dy = (origin[1] + np.arange(y0, y1) * spacing - center[1])[None, :, None]
            for z0 in range(int(start[2]), int(stop[2]) + 1, edge):
                z1 = min(z0 + edge, int(stop[2]) + 1)
                dz = (origin[2] + np.arange(z0, z1) * spacing - center[2])[None, None, :]
                distance = (precision[0, 0]*dx*dx + precision[1, 1]*dy*dy + precision[2, 2]*dz*dz
                            + 2*precision[0, 1]*dx*dy + 2*precision[0, 2]*dx*dz + 2*precision[1, 2]*dy*dz)
                weight = (alpha * np.exp(-0.5 * np.maximum(distance, 0)) * (distance <= cutoff**2)).astype(np.float32)
                region = (slice(x0, x1), slice(y0, y1), slice(z0, z1))
                field[region] += weight
                for channel in range(3):
                    color_field[(channel,) + region] += weight * color[channel]


def remove_exact_zero_area_export_faces(vertices, faces, colors, np):
    """Remove only exactly collapsed float32-export faces, never small faces.

    Marching cubes can produce extremely narrow triangles. Coordinate export
    can collapse one of these even with allow_degenerate=False in grid space.
    Measure in float64 so the norm itself does not underflow in float32.
    """
    corners = vertices.astype(np.float64, copy=False)[faces]
    cross = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    if not np.isfinite(cross).all():
        raise ValueError("Non-finite export triangle")
    zero = np.all(cross == 0, axis=1)
    removed = int(zero.sum())
    report = {"method": "exact_zero_cross_product_in_float64_only", "tolerance": 0,
              "input_vertices": len(vertices), "input_faces": len(faces),
              "removed_zero_area_faces": removed, "removed_unreferenced_vertices": 0}
    if removed > max(8, int(len(faces) * 0.001)):
        raise ValueError("Unexpectedly many exact zero-area export faces")
    if removed:
        kept = faces[~zero]
        referenced, remapped = np.unique(kept, return_inverse=True)
        report["removed_unreferenced_vertices"] = len(vertices) - len(referenced)
        vertices, colors = vertices[referenced], colors[referenced]
        faces = remapped.reshape(-1, 3).astype(np.int32)
    return vertices, faces, colors, report


def validate_mesh(vertices, faces, np):
    if vertices.ndim != 2 or vertices.shape[1] != 3 or faces.ndim != 2 or faces.shape[1] != 3:
        raise ValueError("Expected triangle mesh arrays")
    if len(vertices) < 4 or len(faces) < 4 or not np.isfinite(vertices).all():
        raise ValueError("Empty or non-finite reconstructed mesh")
    if faces.min() < 0 or faces.max() >= len(vertices) or np.any((faces[:, 0] == faces[:, 1]) | (faces[:, 1] == faces[:, 2]) | (faces[:, 0] == faces[:, 2])):
        raise ValueError("Invalid triangle indices")
    precise_vertices = vertices.astype(np.float64, copy=False)
    areas = np.linalg.norm(np.cross(precise_vertices[faces[:, 1]] - precise_vertices[faces[:, 0]], precise_vertices[faces[:, 2]] - precise_vertices[faces[:, 0]]), axis=1)
    if np.any(areas <= 0) or not np.isfinite(areas).all():
        raise ValueError("Degenerate triangle detected")
    return {"vertices": len(vertices), "faces": len(faces), "bounds": [vertices.min(0).tolist(), vertices.max(0).tolist()],
            "finite": True, "zero_area_faces": 0}


def reconstruct(manifest_path, output_dir, config=None, *, cancel=None):
    """Return a new mesh manifest. An outer worker watchdog can enforce hard limits.

    This library only checks its own RSS cooperatively; it never kills its caller
    or a shared process. ``cancel`` may be a threading.Event.
    """
    import psutil
    from plyfile import PlyData, PlyElement
    from scipy.ndimage import map_coordinates
    from skimage.measure import marching_cubes

    config = config or MeshConfig()
    config.validate()
    source = validate_source_manifest(manifest_path)
    output = Path(output_dir).resolve()
    if output.exists():
        raise FileExistsError("Choose a new output directory; never overwrite source/output artifacts")
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    process = psutil.Process()
    peak = 0
    try:
        peak = max(peak, _resource_check(config, process, cancel))
        data = native_ply_data(source.artifact_path)
        centers, alpha, precision, extents, colors, stats = decode_gaussians(data, config.min_opacity, config.cutoff_sigma, np)
        if "gaussian_count" in source.manifest and source.manifest["gaussian_count"] != len(data):
            raise ValueError("Gaussian count differs from the source manifest")
        origin, spacing, starts, stops, candidates = grid_layout(centers, extents, config.resolution, config.max_extent, np)
        work = int(candidates.sum(dtype=np.int64))
        estimated = (24 * config.resolution**3 + len(centers) * 320 + config.max_faces * 96
                     + config.tile_voxels * 96 + 256 * 2**20)
        if work > config.max_voxel_evaluations or estimated > config.max_memory_gib * 2**30:
            raise MemoryError("Planned density work or memory exceeds its configured cap")
        plan = {"parameters": asdict(config), "estimated_peak_bytes": estimated, "voxel_candidates": work,
                "origin": origin.tolist(), "spacing": spacing, **stats}
        write_json_new(output / "plan.json", plan)
        field = np.zeros((config.resolution,) * 3, dtype=np.float32)
        color_field = np.zeros((3, config.resolution, config.resolution, config.resolution), dtype=np.float32)
        for index in range(len(centers)):
            if index % 256 == 0:
                peak = max(peak, _resource_check(config, process, cancel))
            if candidates[index] > 0:
                accumulate_gaussian(field, color_field, centers[index], alpha[index], precision[index], colors[index],
                                    starts[index], stops[index], origin, spacing, config.cutoff_sigma, config.tile_voxels, np)
        peak = max(peak, _resource_check(config, process, cancel))
        field_min, field_max = float(field.min()), float(field.max())
        if not field_min < config.iso_level < field_max:
            raise ValueError("Isosurface threshold lies outside sampled density")
        grid_vertices, faces, _, _ = marching_cubes(field, level=config.iso_level, gradient_direction="ascent",
                                                   allow_degenerate=False, method="lewiner")
        if len(faces) > config.max_faces:
            raise MemoryError("Mesh exceeds face cap; no silent decimation")
        coords = grid_vertices.T
        density = map_coordinates(field, coords, order=1, mode="nearest", prefilter=False)
        vertex_colors = np.column_stack([map_coordinates(color_field[channel], coords, order=1, mode="nearest", prefilter=False)
                                         / np.maximum(density, np.finfo(np.float32).tiny) for channel in range(3)])
        vertex_colors = np.clip(vertex_colors, 0, 1).astype(np.float32)
        vertices = (grid_vertices.astype(np.float64) * spacing + origin).astype(np.float32)
        vertices, faces, vertex_colors, cleanup = remove_exact_zero_area_export_faces(vertices, faces.astype(np.int32), vertex_colors, np)
        metrics = validate_mesh(vertices, faces, np)
        del field, color_field, coords, density
        peak = max(peak, _resource_check(config, process, cancel))
        edges = np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
        edges.sort(axis=1)
        edges, counts = np.unique(edges, axis=0, return_counts=True)
        metrics.update(boundary_edges=int((counts == 1).sum()), nonmanifold_edges=int((counts > 2).sum()))
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components
        graph = coo_matrix((np.ones(len(edges), dtype=np.uint8), (edges[:, 0], edges[:, 1])), shape=(len(vertices), len(vertices))).tocsr()
        metrics["connected_components"] = int(connected_components(graph, directed=False, return_labels=False))
        del edges, counts, graph
        arrays_path = output / "mesh.npz"
        with arrays_path.open("xb") as stream:
            np.savez(stream, vertices=vertices, faces=faces, colors=vertex_colors)
        json_path = output / "mesh-data.json"
        write_json_new(json_path, {"schema_version": 1, "kind": "triangle_mesh_data", "axis": source.manifest["axis"],
                                   "vertices": vertices.tolist(), "faces": faces.tolist(), "colors": vertex_colors.tolist()})
        peak = max(peak, _resource_check(config, process, cancel))
        vdata = np.empty(len(vertices), dtype=[("x", "f4"), ("y", "f4"), ("z", "f4"), ("red", "u1"), ("green", "u1"), ("blue", "u1")])
        for i, name in enumerate(("x", "y", "z")):
            vdata[name] = vertices[:, i]
        for i, name in enumerate(("red", "green", "blue")):
            vdata[name] = np.rint(vertex_colors[:, i] * 255).astype(np.uint8)
        fdata = np.empty(len(faces), dtype=[("vertex_indices", "i4", (3,))])
        fdata["vertex_indices"] = faces
        ply_path = output / "mesh.ply"
        with ply_path.open("xb") as stream:
            PlyData([PlyElement.describe(vdata, "vertex"), PlyElement.describe(fdata, "face")], text=False).write(stream)
        source.revalidate()
        source_copy = output / "source"
        source_copy.mkdir()
        copied_paths = set()
        for key, bound_path in source.bound_artifacts().items():
            copied_artifact = source_copy / source.manifest[key]["path"]
            if copied_artifact == source_copy / "manifest.json":
                raise ValueError("Source artifact cannot collide with the copied source manifest")
            if copied_artifact in copied_paths:
                continue  # Two optional fields may legitimately name the same image.
            copied_artifact.parent.mkdir(parents=True, exist_ok=True)
            with bound_path.open("rb") as inp, copied_artifact.open("xb") as out:
                shutil.copyfileobj(inp, out)
            copied_paths.add(copied_artifact)
        with source.manifest_path.open("rb") as inp, (source_copy / "manifest.json").open("xb") as out:
            shutil.copyfileobj(inp, out)
        copied_source = validate_source_manifest(source_copy / "manifest.json")
        if copied_source.manifest_sha256 != source.manifest_sha256:
            raise ValueError("Copied source manifest does not match the original")
        source.revalidate()
        result = {"schema_version": 1, "kind": "density_mesh", "status": "complete",
                  "completed_at": datetime.now(timezone.utc).isoformat(), "elapsed_seconds": round(time.monotonic() - started, 3),
                  "source_manifest": artifact_record(source_copy / "manifest.json", output),
                  "source_ply_sha256": source.manifest["artifact"]["sha256"], "axis": source.manifest["axis"],
                  "arrays": artifact_record(arrays_path, output), "triangle_ply": artifact_record(ply_path, output),
                  "mesh_json": artifact_record(json_path, output),
                  "method": "anisotropic_gaussian_sum_density_lewiner_marching_cubes", "native_model_mesh": False,
                  "engineering_approximation": True, "color_encoding": "display_rgb_assumed_srgb",
                  "color_method": "density_weighted_SH0_baked_appearance_not_PBR", "metrics": metrics,
                  "density_range": [field_min, field_max], "sampling_plan": plan, "export_numerical_cleanup": cleanup,
                  "parameters": asdict(config), "peak_rss_bytes_sampled": peak,
                  "resource_enforcement": "cooperative_own_RSS_checks; use_external_worker_watchdog_for_hard_limits",
                  "component_removal": False, "smoothing": False, "decimation": False, "visual_qa_approved": False}
        write_json_new(output / "mesh-manifest.json", result)
        return output / "mesh-manifest.json"
    except BaseException as error:
        write_json_new(output / "failure.json", {"status": "failed", "error_type": type(error).__name__, "automatic_retry": False})
        raise
