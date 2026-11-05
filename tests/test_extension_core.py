# SPDX-License-Identifier: GPL-3.0-or-later
"""Test the extension's standalone reader/math without importing Blender."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location(
    "idol_extension_core", Path(__file__).resolve().parents[1] / "extension/idol_mesh_tools/core.py")
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)


def encoded(path, data):
    path.write_text(json.dumps(data, allow_nan=False), encoding="utf-8")
    return {"path": path.name, "sha256": core.digest(path), "bytes": path.stat().st_size}


def make_bundle(folder, axis="y_up"):
    native = folder / "native.ply"
    # The extension validates the source byte binding; PLY semantics are checked
    # during extraction by the independent CLI, not parsed again by Blender.
    native.write_bytes(b"ply\nformat ascii 1.0\nend_header\n")
    source = {"schema_version": 1, "kind": "gaussian_source", "format": "idol_standard_3dgs",
              "axis": axis, "artifact": {"path": native.name, "bytes": native.stat().st_size,
                                         "sha256": core.digest(native)}}
    data = {"schema_version": 1, "kind": "triangle_mesh_data", "axis": axis,
            "vertices": [[0, 0, 0], [1, 2, 3], [0, 2, 0]], "faces": [[0, 1, 2]],
            "colors": [[0.2, 0.4, 0.6], [0, 0, 0], [1, 1, 1]]}
    manifest = {"schema_version": 1, "kind": "density_mesh", "status": "complete",
                "native_model_mesh": False, "axis": axis, "color_encoding": "display_rgb_assumed_srgb",
                "source_manifest": encoded(folder / "source.json", source),
                "source_ply_sha256": core.digest(native), "metrics": {"vertices": 3, "faces": 1},
                "mesh_json": encoded(folder / "mesh-data.json", data)}
    encoded(folder / "mesh-manifest.json", manifest)
    return folder / "mesh-manifest.json", manifest, data


class ExtensionCoreTests(unittest.TestCase):
    def test_valid_bundle_axis_exactly_once_and_inputs_unchanged(self):
        for axis in ("y_up", "z_up"):
            with self.subTest(axis=axis), tempfile.TemporaryDirectory() as temp:
                folder = Path(temp)
                path, record, original = make_bundle(folder, axis)
                hashes = {p.name: core.digest(p) for p in folder.iterdir()}
                data, manifest_hash, native_hash = core.load_bundle(path)
                expected = [[x, z, -y] for x, y, z in original["vertices"]] if axis == "y_up" else original["vertices"]
                self.assertEqual(data["vertices"], expected)
                self.assertEqual(data["faces"], original["faces"])
                self.assertEqual(data["colors"], original["colors"])
                self.assertEqual(manifest_hash, hashes[path.name])
                self.assertEqual(native_hash, record["source_ply_sha256"])
                self.assertEqual(hashes, {p.name: core.digest(p) for p in folder.iterdir()})

    def test_artifact_escape_missing_tamper_and_size_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            path = folder / "data.json"
            spec = encoded(path, {"value": 1})
            for name in ("../data.json", "C:/data.json", "x\\data.json", "/data.json", "missing.json"):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    core.artifact(folder, dict(spec, path=name))
            for size in (0, -1, True, core.MAX_BYTES + 1):
                with self.subTest(size=size), self.assertRaises(ValueError):
                    core.artifact(folder, dict(spec, bytes=size))
            path.write_text('{"value":2}', encoding="utf-8")
            with self.assertRaises(ValueError):
                core.artifact(folder, spec)

    def test_bad_mesh_values_even_with_matching_hash_rejected(self):
        cases = (
            ("vertices", [[0, 0, 0], [True, 2, 3], [0, 2, 0]]),
            ("colors", [[0, 0, 0], [1.1, 0, 0], [0, 0, 0]]),
            ("faces", [[0, 1, 3]]), ("faces", [[0, 0, 2]]), ("faces", [[0, True, 2]]),
            ("axis", "unknown"),
        )
        for key, value in cases:
            with self.subTest(key=key, value=value), tempfile.TemporaryDirectory() as temp:
                folder = Path(temp)
                path, record, data = make_bundle(folder)
                data[key] = value
                record["mesh_json"] = encoded(folder / "mesh-data.json", data)
                encoded(path, record)
                with self.assertRaises(ValueError):
                    core.load_bundle(path)

    def test_source_binding_and_manifest_counts_rejected(self):
        for change in ("source", "axis", "counts", "status"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temp:
                path, record, _ = make_bundle(Path(temp))
                if change == "source":
                    record["source_ply_sha256"] = "0" * 64
                elif change == "axis":
                    record["axis"] = "z_up"
                elif change == "counts":
                    record["metrics"]["vertices"] = 4
                else:
                    record["status"] = "planned"
                encoded(path, record)
                with self.assertRaises(ValueError):
                    core.load_bundle(path)

    def test_uniform_dimensions_preserve_center_and_ratios_without_mutation(self):
        original = [[10, -4, 20], [12, 2, 24], [11, -1, 22]]
        points = copy.deepcopy(original)
        actual, record = core.dimension_transform(points, "UNIFORM", [0.5], 2)
        self.assertEqual(points, original)
        self.assertEqual(record["scale_factors"], [0.125] * 3)
        self.assertEqual([max(p[i] for p in actual) - min(p[i] for p in actual) for i in range(3)], [0.25, 0.75, 0.5])
        self.assertEqual([(max(p[i] for p in actual) + min(p[i] for p in actual)) / 2 for i in range(3)], [11, -1, 22])
        self.assertFalse(record["physical_accuracy_inferred"])

    def test_independent_dimensions_match_three_world_axes(self):
        result, record = core.dimension_transform([[10, 20, 30], [12, 26, 34]], "XYZ", [0.3, 0.25, 0.5])
        for i, target in enumerate([0.3, 0.25, 0.5]):
            self.assertAlmostEqual(max(p[i] for p in result) - min(p[i] for p in result), target)
        self.assertEqual(len(set(record["scale_factors"])), 3)

    def test_invalid_dimensions_refuse_before_returning_geometry(self):
        points = [[0, 0, 0], [1, 2, 3]]
        for targets in ([0], [-1], [float("nan")], [float("inf")], [], [1, 2]):
            with self.subTest(targets=targets), self.assertRaises(ValueError):
                core.dimension_transform(points, "UNIFORM", targets)
        for mode, axis in (("guess", 2), ("UNIFORM", 3)):
            with self.assertRaises(ValueError):
                core.dimension_transform(points, mode, [1], axis)
        with self.assertRaises(ValueError):
            core.dimension_transform([[0, 0, 0], [1, 0, 3]], "XYZ", [1, 1, 1])
        with self.assertRaises(ValueError):
            core.dimension_transform([[0, 0, 0], [1, 2, float("nan")]], "UNIFORM", [1])


if __name__ == "__main__":
    unittest.main()
