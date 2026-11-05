# SPDX-License-Identifier: GPL-3.0-or-later
"""Self-contained mesh reader and dimension math: Python standard library only."""
import hashlib
import json
import math
from pathlib import Path
import re

MAX_BYTES = 256 * 1024 * 1024


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def artifact(base, spec):
    name = spec.get("path")
    if not isinstance(name, str) or not name or "\\" in name or re.match(r"^[A-Za-z]:", name):
        raise ValueError("Expected a portable relative artifact path")
    relative = Path(name)
    base = Path(base).resolve()
    target = (base / relative).resolve()
    if relative.is_absolute() or ".." in relative.parts or not target.is_relative_to(base) or not target.is_file():
        raise ValueError("Artifact path escapes or is missing")
    size = spec.get("bytes")
    expected = spec.get("sha256")
    if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_BYTES:
        raise ValueError("Artifact exceeds the 256 MiB import limit")
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("Artifact needs a SHA256")
    if target.stat().st_size != size or digest(target) != expected:
        raise ValueError("Artifact size/hash mismatch")
    return target


def read_json(path):
    path = Path(path)
    if not 0 < path.stat().st_size <= MAX_BYTES:
        raise ValueError("JSON size outside import limit")
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def load_bundle(path):
    path = Path(path).resolve()
    manifest_hash = digest(path)
    record = read_json(path)
    if (record.get("schema_version") != 1 or record.get("kind") != "density_mesh"
            or record.get("status") != "complete" or record.get("native_model_mesh") is not False
            or record.get("color_encoding") != "display_rgb_assumed_srgb"):
        raise ValueError("Choose the completed derived mesh-manifest.json")
    source_path = artifact(path.parent, record["source_manifest"])
    source = read_json(source_path)
    if source.get("schema_version") != 1 or source.get("kind") != "gaussian_source" or source.get("format") != "idol_standard_3dgs":
        raise ValueError("Missing IDOL source format binding")
    artifact(source_path.parent, source["artifact"])
    for optional_image in ("input", "model_input"):
        if optional_image in source:
            artifact(source_path.parent, source[optional_image])
    if source["artifact"]["sha256"] != record["source_ply_sha256"] or source.get("axis") != record.get("axis"):
        raise ValueError("Source binding differs")
    data = read_json(artifact(path.parent, record["mesh_json"]))
    if data.get("schema_version") != 1 or data.get("kind") != "triangle_mesh_data" or data.get("axis") != record["axis"]:
        raise ValueError("Mesh schema/axis mismatch")
    if data["axis"] not in ("y_up", "z_up"):
        raise ValueError("Unknown source axis")
    vertices, faces, colors = (data[key] for key in ("vertices", "faces", "colors"))
    if not 3 <= len(vertices) <= 2_000_000 or not 1 <= len(faces) <= 4_000_000 or len(colors) != len(vertices):
        raise ValueError("Mesh size outside import limits")
    if len(vertices) != record["metrics"]["vertices"] or len(faces) != record["metrics"]["faces"]:
        raise ValueError("Mesh counts differ from manifest")
    for rows in (vertices, colors):
        for row in rows:
            if not isinstance(row, list) or len(row) != 3 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in row):
                raise ValueError("Nonfinite or malformed coordinates/colors")
    if any(v < 0 or v > 1 for row in colors for v in row):
        raise ValueError("Colors must be in [0, 1]")
    for face in faces:
        if not isinstance(face, list) or len(face) != 3 or any(type(i) is not int or not 0 <= i < len(vertices) for i in face):
            raise ValueError("Invalid triangle")
        if len(set(face)) != 3:
            raise ValueError("Degenerate triangle")
    if data["axis"] == "y_up":
        data["vertices"] = [[x, z, -y] for x, y, z in vertices]
    if digest(path) != manifest_hash:
        raise ValueError("Manifest changed during import")
    return data, manifest_hash, record["source_ply_sha256"]


def dimension_transform(points, mode, targets, axis=2):
    """World-space meters in/out. Scale about bbox center, preserving placement."""
    points = [tuple(p) for p in points]
    if len(points) < 2 or any(len(p) != 3 or not all(math.isfinite(v) for v in p) for p in points):
        raise ValueError("Select at least two finite vertices")
    if mode not in ("UNIFORM", "XYZ") or axis not in (0, 1, 2):
        raise ValueError("Unknown dimension mode or axis")
    if len(targets) != (1 if mode == "UNIFORM" else 3) or any(not math.isfinite(v) or v <= 0 for v in targets):
        raise ValueError("All requested dimensions must be positive")
    low = [min(p[i] for p in points) for i in range(3)]
    high = [max(p[i] for p in points) for i in range(3)]
    sizes = [high[i] - low[i] for i in range(3)]
    if (mode == "XYZ" and min(sizes) <= 0) or (mode == "UNIFORM" and sizes[axis] <= 0):
        raise ValueError("Selected geometry has zero extent on a constrained axis")
    factors = ([targets[0] / sizes[axis]] * 3 if mode == "UNIFORM" else [targets[i] / sizes[i] for i in range(3)])
    center = [(low[i] + high[i]) / 2 for i in range(3)]
    result = [[center[i] + (p[i] - center[i]) * factors[i] for i in range(3)] for p in points]
    if any(not math.isfinite(v) for p in result for v in p):
        raise ValueError("Dimension transform overflow")
    return result, {"mode": mode, "axis": axis, "requested_meters": targets,
                    "source_dimensions_m": sizes, "scale_factors": factors,
                    "pivot": "selected_world_bbox_center", "physical_accuracy_inferred": False}
