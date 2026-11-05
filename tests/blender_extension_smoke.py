# SPDX-License-Identifier: GPL-3.0-or-later
"""Inside fresh Blender: register/import/size real mesh, without saving source.

blender --background --factory-startup --disable-autoexec --python-exit-code 1
  --python tests/blender_extension_smoke.py -- --manifest mesh-manifest.json
  --report new-smoke.json
"""
import argparse
import hashlib
import importlib
import json
import math
from pathlib import Path
import sys

import bpy
import bmesh


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def bounds(points):
    return [max(p[i] for p in points) - min(p[i] for p in points) for i in range(3)]


def close(actual, expected):
    return abs(actual - expected) <= max(abs(expected) * 3e-5, 1e-7)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--installed-module")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    manifest, report = Path(args.manifest).resolve(), Path(args.report).resolve()
    if report.exists():
        raise FileExistsError("Do not overwrite the smoke report")
    if bpy.data.filepath or (not args.installed_module and "--factory-startup" not in sys.argv) or "--disable-autoexec" not in sys.argv:
        raise RuntimeError("Run in fresh Blender without an opened user file")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "extension"))
    addon = importlib.import_module(args.installed_module or "idol_mesh_tools")
    before_hash = digest(manifest)
    existing = list(bpy.data.objects)
    existing_names = [obj.name for obj in existing]
    if not args.installed_module:
        addon.register()
    else:
        assert args.installed_module in bpy.context.preferences.addons
    try:
        assert bpy.ops.import_scene.idol_mesh_bundle(filepath=str(manifest)) == {"FINISHED"}
        obj = bpy.context.active_object
        assert obj.type == "MESH" and len(obj.data.vertices) > 10
        assert all(bpy.data.objects.get(name) is old for name, old in zip(existing_names, existing))
        count = len(obj.data.vertices)
        scale = bpy.context.scene.unit_settings
        scale.system = "METRIC"
        scale.scale_length = 1.0
        settings = bpy.context.scene.idol_mesh_settings
        settings.mode, settings.unit, settings.axis, settings.value = "UNIFORM", "mm", "2", 500
        pre_dimensions = bounds([obj.matrix_world @ v.co for v in obj.data.vertices])
        assert bpy.ops.mesh.idol_set_dimensions() == {"FINISHED"}
        whole = bounds([obj.matrix_world @ v.co for v in obj.data.vertices])
        factor = 0.5 / pre_dimensions[2]
        assert close(whole[2], 0.5), whole
        assert all(close(whole[i], pre_dimensions[i] * factor) for i in range(3))
        assert tuple(obj.scale) == (1.0, 1.0, 1.0)
        whole_record = json.loads(obj["last_explicit_dimension_constraint"])
        assert whole_record["scope"] == "whole_active_mesh"

        # Exercise world-space handling on a rotated/scaled object in a scene
        # whose unit scale is centimeters. The operation must bake only selected
        # vertices and leave the object matrix and all other coordinates alone.
        obj.location = (1.2, -0.7, 0.3)
        obj.rotation_euler = (0.1, 0.2, 0.35)
        obj.scale = (1.3, 0.8, 1.1)
        scale.scale_length = 0.01
        bpy.context.view_layer.update()
        matrix_before = obj.matrix_world.copy()
        bpy.context.tool_settings.mesh_select_mode = (True, False, False)
        bpy.ops.object.mode_set(mode="EDIT")
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        for face in bm.faces:
            face.select_set(False)
        for edge in bm.edges:
            edge.select_set(False)
        for vertex in bm.verts:
            vertex.select_set(False)
        z_values = sorted(v.co.z for v in bm.verts)
        cutoff = z_values[len(z_values) // 2]
        chosen = {v.index for v in bm.verts if v.co.z > cutoff and not v.hide}
        assert 2 < len(chosen) < count - 2
        for index in chosen:
            bm.verts[index].select_set(True)
        bm.select_flush_mode()
        bmesh.update_edit_mesh(obj.data, loop_triangles=True, destructive=False)
        selected = [v for v in bm.verts if v.select and not v.hide]
        selected_ids = {v.index for v in selected}
        original = {v.index: tuple(v.co) for v in bm.verts}
        selected_world = [(obj.matrix_world @ v.co) * scale.scale_length for v in selected]
        before_selected = bounds(selected_world)
        assert min(before_selected) > 0
        targets = [before_selected[0] * 0.9, before_selected[1] * 1.1, before_selected[2] * 0.8]
        settings.mode, settings.unit = "XYZ", "mm"
        settings.xyz = tuple(value * 1000 for value in targets)
        assert bpy.ops.mesh.idol_set_dimensions() == {"FINISHED"}
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        actual_selected = bounds([(obj.matrix_world @ bm.verts[i].co) * scale.scale_length for i in selected_ids])
        assert all(close(a, b) for a, b in zip(actual_selected, targets)), (actual_selected, targets)
        assert all(tuple(v.co) == original[v.index] for v in bm.verts if v.index not in selected_ids)
        assert any(tuple(bm.verts[i].co) != original[i] for i in selected_ids)
        assert obj.matrix_world == matrix_before
        part_record = json.loads(obj["last_explicit_dimension_constraint"])
        assert part_record["scope"] == "selected_vertices"
        assert part_record["affected_vertices"] == len(selected_ids)
        bpy.ops.object.mode_set(mode="OBJECT")
        assert all(bpy.data.objects.get(name) is old for name, old in zip(existing_names, existing))
        assert not bpy.data.filepath and digest(manifest) == before_hash
        before_overflow = [tuple(v.co) for v in obj.data.vertices]
        settings.unit, settings.mode = "m", "XYZ"
        settings.xyz = (1e38, 1e38, 1e38)
        rejected = False
        try:
            rejected = bpy.ops.mesh.idol_set_dimensions() == {"CANCELLED"}
        except RuntimeError:
            rejected = True
        assert rejected
        assert [tuple(v.co) for v in obj.data.vertices] == before_overflow
        result = {"schema_version": 1, "kind": "blender_extension_smoke", "status": "passed",
                  "blender_version": bpy.app.version_string, "source_mesh_manifest_sha256": before_hash,
                  "imported_vertices": count, "whole_target_m": 0.5, "whole_dimensions_m": whole,
                  "whole_dimensions_record": whole_record, "selected_dimensions_record": part_record,
                  "selected_expected_m": targets, "selected_actual_m": actual_selected,
                  "unselected_vertices_unchanged": True, "object_matrix_unchanged": True,
                  "existing_scene_objects_preserved": True, "source_unchanged": True,
                  "saved_any_blend": False, "visual_qa_approved": False}
        result["overflow_rejected_geometry_unchanged"] = True
        result["installed_extension"] = bool(args.installed_module)
        with report.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2, allow_nan=False)
            stream.write("\n")
        print("EXTENSION_SMOKE_PASS")
    finally:
        if bpy.context.active_object and bpy.context.active_object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        if args.installed_module:
            import addon_utils
            addon_utils.disable(args.installed_module, default_set=False)
            assert not hasattr(bpy.types.Scene, "idol_mesh_settings")
        else:
            addon.unregister()


if __name__ == "__main__":
    main()
