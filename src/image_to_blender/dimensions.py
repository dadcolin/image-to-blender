# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicit dimensions for Blender X/Y/Z coordinates; never infer real dimensions."""
import math
from dataclasses import dataclass

import numpy as np

UNITS_TO_METERS = {"mm": 0.001, "cm": 0.01, "m": 1.0}
AXES = {"x": 0, "y": 1, "z": 2}
RELATIVE_TOLERANCE = 2e-6


@dataclass(frozen=True)
class DimensionSpec:
    mode: str
    values: tuple[float, ...]
    unit: str
    axis: str | None = None
    purpose: str = "user-specified"

    def validated(self):
        if self.mode not in ("fit_xyz", "uniform_single_axis"):
            raise ValueError("Unknown dimension mode")
        if self.mode == "uniform_single_axis" and len(self.values) != 1:
            raise ValueError("Uniform scaling requires one dimension")
        return dimension_spec(self.values if self.mode == "fit_xyz" else None, self.axis,
                              self.values[0] if self.mode == "uniform_single_axis" else None,
                              self.unit, self.purpose)


def add_dimension_arguments(parser):
    parser.add_argument("--dimensions", nargs=3, type=float, metavar=("X", "Y", "Z"))
    parser.add_argument("--dimension-axis", choices=tuple(AXES))
    parser.add_argument("--dimension-value", type=float)
    parser.add_argument("--unit", choices=tuple(UNITS_TO_METERS))
    parser.add_argument("--dimension-purpose", choices=("demo", "user-specified"))


def dimension_spec(dimensions=None, axis=None, value=None, unit=None, purpose=None):
    if all(item is None for item in (dimensions, axis, value, unit, purpose)):
        return None
    if unit not in UNITS_TO_METERS or purpose not in ("demo", "user-specified"):
        raise ValueError("Dimensions require explicit mm/cm/m unit and demo/user-specified purpose")
    if dimensions is not None:
        if axis is not None or value is not None or len(dimensions) != 3:
            raise ValueError("Choose exactly three axis dimensions OR one axis/value")
        numbers, mode = list(dimensions), "fit_xyz"
    else:
        if axis not in AXES or value is None:
            raise ValueError("Uniform scaling requires one explicit x/y/z axis and a value")
        numbers, mode = [value], "uniform_single_axis"
    if any(isinstance(number, bool) or not isinstance(number, (int, float))
           or not math.isfinite(number) or number <= 0 for number in numbers):
        raise ValueError("All dimensions must be finite positive numbers")
    meters = [number * UNITS_TO_METERS[unit] for number in numbers]
    if any(not math.isfinite(number) or number <= 0 for number in meters):
        raise ValueError("Dimension cannot be represented in meters")
    return {"mode": mode, "axis": axis, "requested_values": numbers, "input_unit": unit,
            "requested_meters": meters, "purpose": purpose}


def spec_from_args(args):
    return dimension_spec(args.dimensions, args.dimension_axis, args.dimension_value, args.unit, args.dimension_purpose)


def bounds_of(vertices):
    points = np.asarray(vertices, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) < 2 or not np.isfinite(points).all():
        raise ValueError("Expected finite N by 3 mesh coordinates")
    lower, upper = points.min(axis=0), points.max(axis=0)
    return lower, upper, upper - lower


def verify_world_dimensions(world_vertices, record, object_scale, unit_system, scale_length):
    if unit_system != "METRIC" or scale_length != 1.0:
        raise ValueError("Dimensioned scene must use meters at scale_length=1")
    if not np.array_equal(np.asarray(object_scale), np.ones(3)):
        raise ValueError("Dimension scaling must be baked into vertices, not left on object.scale")
    lower, upper, actual = bounds_of(world_vertices)
    expected = np.asarray(record["target_bbox_dimensions_m"], dtype=np.float64)
    if expected.shape != (3,) or not np.isfinite(expected).all() or np.any(expected < 0):
        raise ValueError("Invalid recorded target dimensions")
    tolerance = expected * RELATIVE_TOLERANCE
    if np.any(np.abs(actual - expected) > tolerance):
        raise ValueError("Actual world-space dimensions do not match the meter targets")
    return {"world_bbox_m": [lower.tolist(), upper.tolist()], "actual_dimensions_m": actual.tolist(),
            "target_dimensions_m": expected.tolist(), "absolute_error_m": np.abs(actual - expected).tolist(),
            "tolerance_m": tolerance.tolist(), "relative_tolerance": RELATIVE_TOLERANCE,
            "object_scale_applied": True, "meter_units_verified": True, "passed": True}


def apply_dimensions(vertices, spec):
    # A caller with no constraints must retain its exact original array/geometry.
    if spec is None:
        return vertices, None
    if isinstance(spec, DimensionSpec):
        spec = spec.validated()
    spec = dimension_spec(spec["requested_values"] if spec["mode"] == "fit_xyz" else None,
                          spec["axis"], spec["requested_values"][0] if spec["mode"] == "uniform_single_axis" else None,
                          spec["input_unit"], spec["purpose"])
    lower, upper, dimensions = bounds_of(vertices)
    if spec["mode"] == "fit_xyz":
        if np.any(dimensions <= 0):
            raise ValueError("Three-axis fit requires nonzero extent on every source axis")
        target = np.asarray(spec["requested_meters"], dtype=np.float64)
        factors = target / dimensions
    else:
        index = AXES[spec["axis"]]
        if dimensions[index] <= 0:
            raise ValueError("The selected source axis has zero extent")
        factor = spec["requested_meters"][0] / dimensions[index]
        factors = np.full(3, factor, dtype=np.float64)
        target = dimensions * factor
    if not np.isfinite(factors).all() or np.any(factors <= 0):
        raise ValueError("Unrepresentable dimension scale factors")
    # Blender stores float32 mesh coordinates. Transform around the original origin.
    with np.errstate(over="ignore", invalid="ignore"):
        transformed = (np.asarray(vertices, dtype=np.float64) * factors).astype(np.float32)
    nonuniform = not np.allclose(factors, factors[0], rtol=1e-12, atol=0)
    record = {**spec, "axis_convention": "Blender_z_up; X/Y horizontal axes, Z height; length/width not inferred",
              "source_bbox_model_units": [lower.tolist(), upper.tolist()],
              "source_bbox_dimensions_model_units": dimensions.tolist(), "target_bbox_dimensions_m": target.tolist(),
              "scale_factors_baked_into_vertices": factors.tolist(), "pivot": "original_object_origin",
              "non_uniform_scaling": nonuniform, "aspect_ratio_preserved": not nonuniform,
              "changes_shape_if_axis_ratios_differ": spec["mode"] == "fit_xyz",
              "real_object_dimensions_inferred": False, "real_object_geometry_accuracy_improved": False,
              "coordinate_precision": "float64 computation, float32 Blender mesh storage"}
    record["export_coordinate_check"] = verify_world_dimensions(transformed, record, (1, 1, 1), "METRIC", 1.0)
    return transformed, record
