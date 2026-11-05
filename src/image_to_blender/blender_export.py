# SPDX-License-Identifier: GPL-3.0-or-later
"""Run inside a fresh Blender process; this module never launches external tools."""
import argparse
import json
import math
from pathlib import Path
import shutil
import sys

sys.dont_write_bytecode = True
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from image_to_blender.dimensions import add_dimension_arguments, apply_dimensions, spec_from_args, verify_world_dimensions
from image_to_blender.validation import (artifact_record, read_json, resolve_artifact, sha256,
                                         validate_mesh_manifest, write_json_new)


def blender_vertices(vertices, axis):
    """Convert the explicitly declared source axis convention exactly once."""
    result = np.asarray(vertices, dtype=np.float32).copy()
    if axis == "y_up":
        result = result[:, [0, 2, 1]].copy()
        result[:, 2] *= -1
    elif axis != "z_up":
        raise ValueError("Unknown source axis convention")
    return result


def _arrays(manifest_path):
    record, path, _ = validate_mesh_manifest(manifest_path)
    with np.load(path, allow_pickle=False) as data:
        if set(data.files) != {"vertices", "faces", "colors"}:
            raise ValueError("Unexpected mesh-array schema")
        vertices, faces, colors = (data[name].copy() for name in ("vertices", "faces", "colors"))
    if vertices.ndim != 2 or vertices.shape[1] != 3 or colors.shape != vertices.shape:
        raise ValueError("Invalid mesh coordinates/colors")
    if faces.ndim != 2 or faces.shape[1] != 3 or faces.dtype.kind not in "iu":
        raise ValueError("Expected integer triangle indices")
    if not len(vertices) or not len(faces) or not np.isfinite(vertices).all() or not np.isfinite(colors).all():
        raise ValueError("Empty or nonfinite mesh")
    if faces.min() < 0 or faces.max() >= len(vertices) or np.any(colors < 0) or np.any(colors > 1):
        raise ValueError("Invalid triangle indices or color range")
    if len(vertices) != record["metrics"]["vertices"] or len(faces) != record["metrics"]["faces"]:
        raise ValueError("Mesh counts differ from the manifest")
    return record, vertices, faces.astype(np.int32), colors.astype(np.float32)


def _source_bundle(manifest_path, output_parent):
    manifest_path, output_parent = Path(manifest_path).resolve(), Path(output_parent).resolve()
    record, _, native = validate_mesh_manifest(manifest_path)
    if manifest_path.is_relative_to(output_parent):
        return manifest_path
    target = output_parent / "mesh-evidence"
    target.mkdir(exist_ok=False)
    # Preserve declared relative names, including safe in-bundle symlink
    # aliases, rather than copying only their resolved target basenames.
    sources = {Path(manifest_path.name): manifest_path}

    def include(relative, source):
        if relative in sources and sources[relative] != source:
            raise ValueError("Source artifact paths collide in the copied evidence")
        sources[relative] = source

    for key in ("source_manifest", "arrays", "triangle_ply", "mesh_json"):
        include(Path(record[key]["path"]), resolve_artifact(manifest_path.parent, record[key]))
    source_folder = Path(record["source_manifest"]["path"]).parent
    for key, source in native.bound_artifacts().items():
        include(source_folder / native.manifest[key]["path"], source)
    for relative, source in sources.items():
        dest = target / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as inp, dest.open("xb") as out:
            shutil.copyfileobj(inp, out)
    copied = target / manifest_path.name
    validate_mesh_manifest(copied)
    if sha256(copied) != sha256(manifest_path):
        raise ValueError("Copied mesh evidence differs from its source")
    return copied


def _fresh_bpy():
    import bpy
    if "--factory-startup" not in sys.argv or "--disable-autoexec" not in sys.argv or bpy.data.filepath:
        raise RuntimeError("Use fresh Blender --factory-startup --disable-autoexec")
    return bpy


def _linear_colors(colors):
    linear = np.where(colors <= 0.04045, colors / 12.92, ((colors + 0.055) / 1.055) ** 2.4)
    return np.column_stack((linear, np.ones(len(linear), dtype=np.float32))).astype(np.float32)


def export_in_blender(mesh_manifest, output_blend, dimensions=None):
    bpy = _fresh_bpy()
    from mathutils import Vector
    source = Path(mesh_manifest).resolve()
    original_source_hash = sha256(source)
    output = Path(output_blend).resolve()
    receipt_path = output.with_suffix(".blend.json")
    if output.suffix.lower() != ".blend" or output.exists() or receipt_path.exists():
        raise FileExistsError("Choose a new .blend and receipt; originals are never overwritten")
    record, original, faces, colors = _arrays(source)
    vertices, dimension_record = apply_dimensions(blender_vertices(original, record["axis"]), dimensions)
    output.parent.mkdir(parents=True, exist_ok=True)
    evidence = _source_bundle(source, output.parent)
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    mesh = bpy.data.meshes.new("DerivedDensityMesh")
    mesh.vertices.add(len(vertices))
    mesh.vertices.foreach_set("co", vertices.ravel())
    mesh.loops.add(len(faces) * 3)
    mesh.loops.foreach_set("vertex_index", faces.ravel())
    mesh.polygons.add(len(faces))
    mesh.polygons.foreach_set("loop_start", np.arange(0, len(faces) * 3, 3, dtype=np.int32))
    mesh.polygons.foreach_set("loop_total", np.full(len(faces), 3, dtype=np.int32))
    mesh.update(calc_edges=True)
    if mesh.validate(verbose=False, clean_customdata=False):
        raise ValueError("Blender corrected mesh data; refusing silent geometry changes")
    attr = mesh.color_attributes.new(name="BakedColor", type="FLOAT_COLOR", domain="POINT")
    attr.data.foreach_set("color", _linear_colors(colors).ravel())
    obj = bpy.data.objects.new("DerivedMesh", mesh)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    obj["source_mesh_manifest_sha256"] = original_source_hash
    obj["native_model_mesh"] = False
    obj["visual_qa_approved"] = False
    material = bpy.data.materials.new("BakedSH0Appearance_NotPBR")
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    color_node = nodes.new("ShaderNodeVertexColor")
    color_node.layer_name = "BakedColor"
    emission = nodes.new("ShaderNodeEmission")
    surface = nodes.new("ShaderNodeOutputMaterial")
    material.node_tree.links.new(color_node.outputs["Color"], emission.inputs["Color"])
    material.node_tree.links.new(emission.outputs["Emission"], surface.inputs["Surface"])
    mesh.materials.append(material)
    scene = bpy.context.scene
    if dimension_record:
        scene.unit_settings.system = "METRIC"
        scene.unit_settings.scale_length = 1.0
        scene.unit_settings.length_unit = "METERS"
        obj["dimension_purpose"] = dimension_record["purpose"]
        if dimension_record["purpose"] == "demo":
            obj.name = "DEMO_DerivedMesh"
    lower, upper = vertices.min(0), vertices.max(0)
    center = Vector(((lower.astype(np.float64) + upper) / 2).tolist())
    radius = float(np.linalg.norm(upper.astype(np.float64) - lower) / 2)
    if not math.isfinite(radius) or radius <= 0:
        raise ValueError("Invalid mesh bounds")
    camera_data = bpy.data.cameras.new("ReviewCamera")
    camera = bpy.data.objects.new("ReviewCamera", camera_data)
    scene.collection.objects.link(camera)
    direction = Vector((4, -6, 3)).normalized()
    camera.location = center + direction * radius * 4
    camera.rotation_euler = (-direction).to_track_quat("-Z", "Y").to_euler()
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = radius * 2.3
    camera_data.clip_start = max(radius * 1e-4, 1e-6)
    camera_data.clip_end = max(100, radius * 10)
    scene.camera = camera
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = scene.render.resolution_y = 768
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = "Standard"
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.shading.type = "MATERIAL"
                area.spaces.active.region_3d.view_perspective = "CAMERA"
    note = bpy.data.texts.new("ReconstructionProvenance.txt")
    note.write("Derived Gaussian-density mesh; single-image hidden geometry is inferred.\n"
               "Baked appearance, not recovered PBR, CAD, retopology or manufacturing approval.\n")
    note.write(json.dumps({"mesh_manifest": record, "dimension_constraint": dimension_record}, indent=2))
    validate_mesh_manifest(source)
    if sha256(source) != original_source_hash:
        raise ValueError("Source mesh manifest changed during Blender import")
    bpy.ops.wm.save_as_mainfile(filepath=str(output), check_existing=True)
    result = {"schema_version": 1, "kind": "blend_export", "status": "complete",
              "blend": artifact_record(output, output.parent), "source_mesh_manifest": artifact_record(evidence, output.parent),
              "source_mesh_manifest_sha256": original_source_hash, "source_ply_sha256": record["source_ply_sha256"],
              "axis_transform": "Rx_minus90_y_up_to_z_up" if record["axis"] == "y_up" else "identity_z_up",
              "vertices": len(vertices), "faces": len(faces), "blender_version": bpy.app.version_string,
              "dimension_constraint": dimension_record, "native_model_mesh": False, "visual_qa_approved": False}
    write_json_new(receipt_path, result)
    return receipt_path


def verify_blend_in_blender(blend_path, receipt_path, report_path):
    bpy = _fresh_bpy()
    blend, receipt_path, report = map(lambda value: Path(value).resolve(), (blend_path, receipt_path, report_path))
    if report.exists():
        raise FileExistsError("Never overwrite a verification report")
    receipt = read_json(receipt_path)
    if receipt.get("schema_version") != 1 or receipt.get("kind") != "blend_export" or receipt.get("status") != "complete":
        raise ValueError("Expected a completed blend_export receipt")
    if resolve_artifact(receipt_path.parent, receipt["blend"]) != blend:
        raise ValueError("Blend path differs from its receipt")
    source = resolve_artifact(receipt_path.parent, receipt["source_mesh_manifest"])
    if sha256(source) != receipt["source_mesh_manifest_sha256"]:
        raise ValueError("Source manifest binding differs")
    record, vertices, faces, colors = _arrays(source)
    expected, _ = apply_dimensions(blender_vertices(vertices, record["axis"]), receipt["dimension_constraint"])
    bpy.ops.wm.open_mainfile(filepath=str(blend), load_ui=False, use_scripts=False)
    meshes = [obj for obj in bpy.data.objects if obj.type == "MESH"]
    if len(meshes) != 1 or len(meshes[0].modifiers):
        raise ValueError("Expected one actual mesh with no modifiers")
    obj = meshes[0]
    if obj.get("source_mesh_manifest_sha256") != receipt["source_mesh_manifest_sha256"]:
        raise ValueError("Stored mesh source binding differs")
    if len(obj.data.vertices) != len(expected) or len(obj.data.polygons) != len(faces):
        raise ValueError("Persisted topology counts differ")
    actual = np.empty(len(expected) * 3, dtype=np.float32)
    obj.data.vertices.foreach_get("co", actual)
    actual = actual.reshape(-1, 3)
    if not np.array_equal(actual, expected):
        raise ValueError("Persisted vertices differ from the verified source transform")
    indices = np.empty(len(faces) * 3, dtype=np.int32)
    obj.data.loops.foreach_get("vertex_index", indices)
    if not np.array_equal(indices.reshape(-1, 3), faces):
        raise ValueError("Persisted triangle indices differ")
    attr = obj.data.color_attributes.get("BakedColor")
    if attr is None or attr.domain != "POINT" or len(attr.data) != len(expected):
        raise ValueError("Vertex colors were not preserved")
    color_values = np.empty(len(expected) * 4, dtype=np.float32)
    attr.data.foreach_get("color", color_values)
    if not np.allclose(color_values.reshape(-1, 4), _linear_colors(colors), rtol=1e-6, atol=1e-7):
        raise ValueError("Persisted colors differ")
    matrix = np.asarray(obj.matrix_world, dtype=np.float64)
    world = actual.astype(np.float64) @ matrix[:3, :3].T + matrix[:3, 3]
    dimension_check = None
    if receipt["dimension_constraint"]:
        units = bpy.context.scene.unit_settings
        dimension_check = verify_world_dimensions(world, receipt["dimension_constraint"], obj.scale, units.system, units.scale_length)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    if obj.mode != "EDIT":
        raise ValueError("Mesh edit mode is unavailable")
    bpy.ops.object.mode_set(mode="OBJECT")
    if sha256(blend) != receipt["blend"]["sha256"]:
        raise ValueError("Blend changed during verification")
    result = {"schema_version": 1, "kind": "blend_verification", "status": "passed", "blend_sha256": sha256(blend),
              "vertices": len(expected), "faces": len(faces), "source_vertices_faces_colors_preserved": True,
              "edit_mode_verified": True, "dimension_check": dimension_check, "visual_qa_approved": False}
    write_json_new(report, result)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--manifest")
    parser.add_argument("--output")
    parser.add_argument("--blend")
    parser.add_argument("--receipt")
    parser.add_argument("--report")
    add_dimension_arguments(parser)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    dimensions = spec_from_args(args)
    if args.verify:
        if not all((args.blend, args.receipt, args.report)) or args.manifest or args.output or dimensions:
            parser.error("Verification needs only --blend --receipt --report")
        result = verify_blend_in_blender(args.blend, args.receipt, args.report)
    else:
        if not args.manifest or not args.output or any((args.blend, args.receipt, args.report)):
            parser.error("Export needs --manifest and --output")
        result = export_in_blender(args.manifest, args.output, dimensions)
    print(json.dumps({"artifact": str(result)}))


if __name__ == "__main__":
    main()
