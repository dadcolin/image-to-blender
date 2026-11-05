# SPDX-License-Identifier: GPL-3.0-or-later
"""IDOL Mesh Tools: local data import and explicit sizing. No model execution."""
import json
import math

import bpy
import bmesh
from bpy.props import EnumProperty, FloatProperty, FloatVectorProperty, PointerProperty, StringProperty
from bpy_extras.io_utils import ImportHelper
from mathutils import Vector

from .core import dimension_transform, load_bundle


def linear(value):
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def import_bundle(context, filepath):
    data, source_hash, native_hash = load_bundle(filepath)
    mesh = bpy.data.meshes.new("IDOL_Derived_Mesh")
    obj, material = None, None
    try:
        mesh.from_pydata(data["vertices"], [], data["faces"])
        mesh.update()
        colors = mesh.color_attributes.new(name="BakedColor", type="FLOAT_COLOR", domain="POINT")
        colors.data.foreach_set("color", [v for rgb in data["colors"] for v in (*map(linear, rgb), 1.0)])
        material = bpy.data.materials.new("IDOL_Baked_Appearance")
        material.use_nodes = True
        nodes = material.node_tree.nodes
        nodes.clear()
        output = nodes.new("ShaderNodeOutputMaterial")
        emission = nodes.new("ShaderNodeEmission")
        vertex = nodes.new("ShaderNodeVertexColor")
        vertex.layer_name = "BakedColor"
        material.node_tree.links.new(vertex.outputs["Color"], emission.inputs["Color"])
        material.node_tree.links.new(emission.outputs[0], output.inputs["Surface"])
        mesh.materials.append(material)
        obj = bpy.data.objects.new("IDOL_Derived_Object", mesh)
        obj["source_mesh_manifest_sha256"] = source_hash
        obj["source_ply_sha256"] = native_hash
        obj["derived_approximation_not_CAD"] = True
        context.collection.objects.link(obj)
        for selected in context.selected_objects:
            selected.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        return obj
    except BaseException:
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.meshes.remove(mesh)
        if material is not None:
            bpy.data.materials.remove(material)
        raise


class IDOL_OT_import(bpy.types.Operator, ImportHelper):
    bl_idname = "import_scene.idol_mesh_bundle"
    bl_label = "Import IDOL Derived Mesh"
    bl_options = {"REGISTER", "UNDO"}
    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT"

    def execute(self, context):
        try:
            obj = import_bundle(context, self.filepath)
            self.report({"INFO"}, f"Imported {len(obj.data.vertices):,} vertices; approximate mesh, dimensions uncalibrated")
            return {"FINISHED"}
        except Exception as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}


class IDOL_Settings(bpy.types.PropertyGroup):
    mode: EnumProperty(name="Scaling", items=[("UNIFORM", "Preserve proportions", "One dimension; equal scale on all axes"),
                                              ("XYZ", "Fit X / Y / Z", "Independent axes; changes proportions")])
    axis: EnumProperty(name="Axis", items=[("0", "X", "World X"), ("1", "Y", "World Y"), ("2", "Z / Height", "World Z")], default="2")
    unit: EnumProperty(name="Unit", items=[("mm", "mm", "Millimeters"), ("cm", "cm", "Centimeters"), ("m", "m", "Meters")], default="mm")
    value: FloatProperty(name="Target", default=500, min=0.000001)
    xyz: FloatVectorProperty(name="X / Y / Z", size=3, default=(300, 250, 500), min=0.000001)


class IDOL_OT_dimensions(bpy.types.Operator):
    bl_idname = "mesh.idol_set_dimensions"
    bl_label = "Apply Dimensions"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and context.mode in {"OBJECT", "EDIT_MESH"}

    def execute(self, context):
        obj = context.active_object
        settings = context.scene.idol_mesh_settings
        # This action intentionally changes base mesh vertices, not evaluated modifiers.
        if obj.modifiers or obj.data.shape_keys or obj.data.users > 1:
            self.report({"ERROR"}, "Use a single-user mesh without modifiers or shape keys")
            return {"CANCELLED"}
        if context.mode == "EDIT_MESH" and len(context.objects_in_mode) != 1:
            self.report({"ERROR"}, "Edit one object at a time")
            return {"CANCELLED"}
        edit = obj.mode == "EDIT"
        bm = bmesh.from_edit_mesh(obj.data) if edit else None
        vertices = [v for v in bm.verts if v.select and not v.hide] if edit else list(obj.data.vertices)
        original, mutated = [], False
        try:
            scale = context.scene.unit_settings.scale_length
            if not math.isfinite(scale) or scale <= 0:
                raise ValueError("Invalid scene unit scale")
            if abs(obj.matrix_world.determinant()) < 1e-12:
                raise ValueError("Object has a singular transform")
            inverse = obj.matrix_world.inverted()
            original = [v.co.copy() for v in vertices]
            world = [(obj.matrix_world @ co) * scale for co in original]
            multiplier = {"mm": 0.001, "cm": 0.01, "m": 1}[settings.unit]
            targets = [v * multiplier for v in (settings.xyz if settings.mode == "XYZ" else [settings.value])]
            result, record = dimension_transform(world, settings.mode, targets, int(settings.axis))
            local = [inverse @ (Vector(point) / scale) for point in result]
            if any(not math.isfinite(v) for point in local for v in point):
                raise ValueError("Target exceeds Blender coordinate precision")
            mutated = True
            for vertex, point in zip(vertices, local):
                vertex.co = point
            actual = [(obj.matrix_world @ v.co) * scale for v in vertices]
            if any(not math.isfinite(v) for point in actual for v in point):
                raise ValueError("Transformed world coordinates are not finite")
            wanted = [max(p[i] for p in result) - min(p[i] for p in result) for i in range(3)]
            measured = [max(p[i] for p in actual) - min(p[i] for p in actual) for i in range(3)]
            if any(abs(a - b) > max(abs(b) * 2e-5, 1e-7) for a, b in zip(measured, wanted)):
                for vertex, co in zip(vertices, original):
                    vertex.co = co
                raise ValueError("Coordinate precision cannot meet the target; geometry restored")
            if edit:
                bmesh.update_edit_mesh(obj.data, loop_triangles=True, destructive=False)
            else:
                obj.data.update()
            record.update(scope="selected_vertices" if edit else "whole_active_mesh",
                          affected_vertices=len(vertices), measured_dimensions_m=measured)
            obj["last_explicit_dimension_constraint"] = json.dumps(record)
            self.report({"INFO"}, "Dimensions applied; inspect adjoining geometry and save a new copy")
            return {"FINISHED"}
        except Exception as error:
            if mutated:
                for vertex, co in zip(vertices, original):
                    vertex.co = co
                if edit:
                    bmesh.update_edit_mesh(obj.data, loop_triangles=True, destructive=False)
                else:
                    obj.data.update()
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}


class IDOL_PT_tools(bpy.types.Panel):
    bl_label = "IDOL Mesh Tools"
    bl_idname = "IDOL_PT_tools"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "IDOL"

    def draw(self, context):
        layout = self.layout
        layout.operator(IDOL_OT_import.bl_idname)
        layout.separator()
        layout.label(text="Object Mode: whole active mesh")
        layout.label(text="Edit Mode: selected part vertices")
        settings = context.scene.idol_mesh_settings
        layout.prop(settings, "mode")
        layout.prop(settings, "unit")
        if settings.mode == "UNIFORM":
            layout.prop(settings, "axis")
            layout.prop(settings, "value")
        else:
            layout.prop(settings, "xyz")
            layout.label(text="Independent scaling changes shape", icon="INFO")
        layout.operator(IDOL_OT_dimensions.bl_idname)
        layout.label(text="Derived appearance, not CAD / PBR")


def menu_import(self, context):
    self.layout.operator(IDOL_OT_import.bl_idname, text="IDOL Derived Mesh (.json)")


CLASSES = (IDOL_Settings, IDOL_OT_import, IDOL_OT_dimensions, IDOL_PT_tools)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.idol_mesh_settings = PointerProperty(type=IDOL_Settings)
    bpy.types.TOPBAR_MT_file_import.append(menu_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_import)
    del bpy.types.Scene.idol_mesh_settings
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
