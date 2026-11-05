# SPDX-License-Identifier: GPL-3.0-or-later
import json
import math
from pathlib import Path
import tempfile
import threading
import unittest

import numpy as np
from plyfile import PlyData, PlyElement

from image_to_blender.blender_export import blender_vertices, _source_bundle
from image_to_blender.mesh import (MeshConfig, decode_gaussians, native_ply_data, reconstruct,
                                   remove_exact_zero_area_export_faces, validate_mesh)
from image_to_blender.validation import (artifact_record, read_json, sha256, validate_mesh_manifest,
                                         validate_source_manifest, write_json_new)


def gaussian_rows(scales=(0.1, 0.1, 0.1), rotation=(1, 0, 0, 0), rgb=(0.2, 0.6, 0.9)):
    fields = ["x", "y", "z", "opacity", *[f"scale_{i}" for i in range(3)],
              *[f"rot_{i}" for i in range(4)], *[f"f_dc_{i}" for i in range(3)]]
    rows = np.zeros(1, dtype=[(name, "f4") for name in fields])
    rows["opacity"] = math.log(0.8 / 0.2)
    for i in range(3):
        rows[f"scale_{i}"] = math.log(scales[i])
        rows[f"f_dc_{i}"] = (rgb[i] - 0.5) / 0.28209479177387814
    for i in range(4):
        rows[f"rot_{i}"] = rotation[i]
    return rows


def source_fixture(folder, axis="y_up", include_images=False):
    source = folder / "source"
    source.mkdir()
    artifact = source / "native.ply"
    PlyData([PlyElement.describe(gaussian_rows(), "vertex")], text=False).write(str(artifact))
    manifest = source / "manifest.json"
    record = {"schema_version": 1, "kind": "gaussian_source", "format": "idol_standard_3dgs",
              "axis": axis, "artifact": artifact_record(artifact, source), "gaussian_count": 1}
    if include_images:
        from PIL import Image
        (source / "images").mkdir()
        for key, color in (("input", "white"), ("model_input", "red")):
            image_path = source / "images" / (key + ".png")
            Image.new("RGB", (2, 2), color=color).save(image_path)
            record[key] = artifact_record(image_path, source)
    write_json_new(manifest, record)
    return manifest, artifact


class MeshTests(unittest.TestCase):
    def test_rotated_anisotropic_covariance_is_not_replaced_with_spheres(self):
        rows = gaussian_rows((0.1, 0.2, 0.3), (math.sqrt(0.5), 0, 0, math.sqrt(0.5)))
        _, alpha, precision, extent, colors, _ = decode_gaussians(rows, 0, 3, np)
        np.testing.assert_allclose(precision[0], np.diag([25, 100, 1 / 0.3**2]), rtol=1e-6, atol=1e-8)
        np.testing.assert_allclose(extent[0], [0.6, 0.3, 0.9], rtol=1e-6)
        np.testing.assert_allclose(alpha, [0.8], rtol=1e-6)
        np.testing.assert_allclose(colors[0], [0.2, 0.6, 0.9], atol=1e-7)

    def test_exact_zero_cleanup_does_not_drop_small_real_triangles(self):
        vertices = np.array([[0, 0, 0], [1e-20, 0, 0], [0, 1e-20, 0], [2e-20, 0, 0]], dtype=np.float32)
        faces = np.array([[0, 1, 2], [0, 1, 3]], dtype=np.int32)
        colors = np.arange(12, dtype=np.float32).reshape(4, 3)
        v, f, c, report = remove_exact_zero_area_export_faces(vertices, faces, colors, np)
        np.testing.assert_array_equal(v, vertices[:3])
        np.testing.assert_array_equal(f, [[0, 1, 2]])
        np.testing.assert_array_equal(c, colors[:3])
        self.assertEqual(report["removed_zero_area_faces"], 1)
        self.assertEqual(len(vertices), 4)

    def test_explicit_axis_conversion_is_applied_only_for_y_up(self):
        points = np.array([[1, 2, 3], [-2, 4, -6]], dtype=np.float32)
        np.testing.assert_array_equal(blender_vertices(points, "y_up"), [[1, 3, -2], [-2, -6, -4]])
        np.testing.assert_array_equal(blender_vertices(points, "z_up"), points)
        np.testing.assert_array_equal(points, [[1, 2, 3], [-2, 4, -6]])
        with self.assertRaises(ValueError):
            blender_vertices(points, "unspecified")

    def test_actual_small_density_export_round_trips_all_formats_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, raw = source_fixture(root)
            before = (sha256(source), sha256(raw))
            manifest = reconstruct(source, root / "derived", MeshConfig(resolution=49,
                                   iso_level=0.8 * math.exp(-0.5), min_available_gib=0, max_faces=100_000))
            record, arrays_path, copied_source = validate_mesh_manifest(manifest)
            self.assertEqual(before, (sha256(source), sha256(raw)))
            self.assertEqual(copied_source.manifest_sha256, before[0])
            self.assertEqual(record["axis"], "y_up")
            with np.load(arrays_path, allow_pickle=False) as arrays:
                vertices, faces, colors = (arrays[key] for key in ("vertices", "faces", "colors"))
                radius = np.linalg.norm(vertices.astype(np.float64), axis=1)
                self.assertLess(float(np.max(np.abs(radius - 0.1))), record["sampling_plan"]["spacing"] * 0.2)
                np.testing.assert_allclose(colors, np.broadcast_to([0.2, 0.6, 0.9], colors.shape), atol=2e-6)
                corners = vertices.astype(np.float64)[faces]
                volume = np.einsum("ij,ij->i", corners[:, 0], np.cross(corners[:, 1], corners[:, 2])).sum() / 6
                self.assertGreater(volume, 0)
                self.assertLess(abs(volume / (4 * math.pi * 0.1**3 / 3) - 1), 0.04)
                payload = read_json(manifest.parent / "mesh-data.json")
                self.assertEqual(payload["axis"], "y_up")
                np.testing.assert_array_equal(payload["vertices"], vertices)
                np.testing.assert_array_equal(payload["faces"], faces)
                np.testing.assert_array_equal(payload["colors"], colors)
                ply = PlyData.read(str(manifest.parent / "mesh.ply"), mmap=False)
                self.assertEqual(len(ply["vertex"].data), len(vertices))
                self.assertEqual(len(ply["face"].data), len(faces))
                validate_mesh(vertices, faces, np)
            self.assertFalse(record["native_model_mesh"])
            self.assertFalse(record["visual_qa_approved"])
            with self.assertRaises(FileExistsError):
                reconstruct(source, manifest.parent, MeshConfig(min_available_gib=0))
            raw.write_bytes(raw.read_bytes() + b"changed")
            with self.assertRaises(ValueError):
                validate_source_manifest(source)
            # A self-contained result remains verifiable after the original source changes.
            validate_mesh_manifest(manifest)
            copied_source.artifact_path.write_bytes(copied_source.artifact_path.read_bytes() + b"changed")
            with self.assertRaises(ValueError):
                validate_mesh_manifest(manifest)

    def test_unknown_axis_path_escape_and_changed_manifest_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            source, _ = source_fixture(Path(temp))
            original = read_json(source)
            for field, value in [("axis", "unknown"), ("format", "point_cloud")]:
                source.write_text(json.dumps({**original, field: value}), encoding="utf-8")
                with self.assertRaises(ValueError):
                    validate_source_manifest(source)
            for path in ["../native.ply", "/native.ply", "C:/native.ply", "dir\\native.ply"]:
                source.write_text(json.dumps({**original, "artifact": {**original["artifact"], "path": path}}), encoding="utf-8")
                with self.assertRaises(ValueError):
                    validate_source_manifest(source)
            source.write_text(json.dumps(original), encoding="utf-8")
            checked = validate_source_manifest(source)
            source.write_text(json.dumps(original) + " ", encoding="utf-8")
            with self.assertRaises(ValueError):
                checked.revalidate()

    def test_optional_images_are_bound_copied_and_preserved_through_export_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, _ = source_fixture(root, include_images=True)
            original = validate_source_manifest(source)
            hashes = {key: sha256(path) for key, path in original.bound_artifacts().items()}
            manifest = reconstruct(source, root / "derived", MeshConfig(resolution=32, min_available_gib=0))
            _, _, copied = validate_mesh_manifest(manifest)
            self.assertEqual(hashes, {key: sha256(path) for key, path in copied.bound_artifacts().items()})
            self.assertEqual(original.manifest_sha256, copied.manifest_sha256)
            export = root / "export"
            export.mkdir()
            evidence = _source_bundle(manifest, export)
            _, _, exported = validate_mesh_manifest(evidence)
            self.assertEqual(hashes, {key: sha256(path) for key, path in exported.bound_artifacts().items()})
            self.assertEqual(hashes, {key: sha256(path) for key, path in original.bound_artifacts().items()})
            self.assertEqual(sha256(source), original.manifest_sha256)
            # Mutating the originals cannot alter or break either copied bundle.
            original.bound_artifacts()["input"].write_bytes(b"altered original image")
            with self.assertRaises(ValueError):
                original.revalidate()
            validate_mesh_manifest(manifest)
            validate_mesh_manifest(evidence)
            exported.bound_artifacts()["model_input"].write_bytes(b"altered copied image")
            with self.assertRaises(ValueError):
                validate_mesh_manifest(evidence)

    def test_optional_image_path_hash_type_and_missing_files_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            source, _ = source_fixture(Path(temp), include_images=True)
            original = read_json(source)
            for replacement in (None, "https://example.invalid/image.png",
                                {**original["input"], "path": "../input.png"},
                                {**original["input"], "path": "images/missing.png"},
                                {**original["input"], "sha256": "0" * 64}):
                with self.subTest(replacement=replacement):
                    source.write_text(json.dumps({**original, "input": replacement}), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        validate_source_manifest(source)

    def test_shared_optional_image_path_is_copied_once(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, _ = source_fixture(root, include_images=True)
            record = read_json(source)
            record["model_input"] = record["input"].copy()
            source.write_text(json.dumps(record), encoding="utf-8")
            manifest = reconstruct(source, root / "derived", MeshConfig(resolution=32, min_available_gib=0))
            _, _, copied = validate_mesh_manifest(manifest)
            artifacts = copied.bound_artifacts()
            self.assertEqual(artifacts["input"], artifacts["model_input"])
            export = root / "export"
            export.mkdir()
            evidence = _source_bundle(manifest, export)
            validate_mesh_manifest(evidence)

    def test_cancellation_and_insufficient_work_budget_never_report_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, _ = source_fixture(root)
            cancel = threading.Event()
            cancel.set()
            with self.assertRaises(InterruptedError):
                reconstruct(source, root / "cancelled", MeshConfig(resolution=32, min_available_gib=0), cancel=cancel)
            self.assertFalse((root / "cancelled/mesh-manifest.json").exists())
            with self.assertRaises(MemoryError):
                reconstruct(source, root / "capped", MeshConfig(resolution=32, min_available_gib=0, max_voxel_evaluations=1))
            self.assertFalse((root / "capped/mesh-manifest.json").exists())

    def test_invalid_config_and_wrong_ply_schema_rejected(self):
        for config in [MeshConfig(resolution=0), MeshConfig(iso_level=float("nan")), MeshConfig(min_opacity=1),
                       MeshConfig(max_memory_gib=-1), MeshConfig(tile_voxels=True)]:
            with self.assertRaises(ValueError):
                config.validate()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "point-cloud.ply"
            PlyData([PlyElement.describe(np.zeros(4, dtype=[("x", "f4"), ("y", "f4"), ("z", "f4")]), "vertex")]).write(str(path))
            with self.assertRaises(ValueError):
                native_ply_data(path)


if __name__ == "__main__":
    unittest.main()
