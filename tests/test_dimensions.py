# SPDX-License-Identifier: GPL-3.0-or-later
import unittest
import numpy as np

from image_to_blender.dimensions import (DimensionSpec, apply_dimensions, bounds_of, dimension_spec,
                                          verify_world_dimensions)


class DimensionTests(unittest.TestCase):
    def setUp(self):
        self.points = np.array([[-1, -2, 0], [1, 2, 8], [0.3, -1, 5]], dtype=np.float32)

    def test_no_dimension_is_not_a_guess(self):
        result, record = apply_dimensions(self.points, None)
        self.assertIs(result, self.points)
        self.assertIsNone(record)

    def test_uniform_height_scales_all_vertices_and_preserves_source(self):
        original = self.points.copy()
        result, record = apply_dimensions(self.points, DimensionSpec("uniform_single_axis", (500,), "mm", "z", "demo"))
        np.testing.assert_array_equal(result, original * 0.0625)
        np.testing.assert_array_equal(self.points, original)
        np.testing.assert_allclose(bounds_of(result)[2], [0.125, 0.25, 0.5])
        self.assertTrue(record["aspect_ratio_preserved"])
        self.assertFalse(record["non_uniform_scaling"])

    def test_xyz_fit_records_nonuniform_shape_change_and_meter_bounds(self):
        result, record = apply_dimensions(self.points, DimensionSpec("fit_xyz", (300, 250, 500), "mm", purpose="demo"))
        np.testing.assert_allclose(bounds_of(result)[2], [0.3, 0.25, 0.5], rtol=1e-7)
        self.assertTrue(record["non_uniform_scaling"])
        self.assertFalse(record["real_object_geometry_accuracy_improved"])
        self.assertFalse(record["real_object_dimensions_inferred"])

    def test_units_produce_identical_geometry(self):
        values = [apply_dimensions(self.points, DimensionSpec("uniform_single_axis", (value,), unit, "x"))[0]
                  for value, unit in [(500, "mm"), (50, "cm"), (0.5, "m")]]
        np.testing.assert_array_equal(values[0], values[1])
        np.testing.assert_array_equal(values[0], values[2])

    def test_invalid_or_missing_dimensions_refuse_instead_of_guessing(self):
        bad = [dict(axis="z"), dict(value=1), dict(axis="height", value=1), dict(dimensions=[1, 2]),
               dict(dimensions=[1, 2, 3], axis="z", value=1), dict(dimensions=[1, 0, 1]),
               dict(dimensions=[1, -1, 1]), dict(dimensions=[1, float("nan"), 1]),
               dict(axis="z", value=float("inf")), dict(axis="z", value=True)]
        for kwargs in bad:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                dimension_spec(**kwargs, unit="m", purpose="demo")
        with self.assertRaises(ValueError):
            DimensionSpec("guess", (1,), "m").validated()
        with self.assertRaises(ValueError):
            DimensionSpec("uniform_single_axis", (1, 2), "m", "z").validated()

    def test_verification_rejects_ui_units_only_and_unapplied_object_scale(self):
        result, record = apply_dimensions(self.points, DimensionSpec("uniform_single_axis", (0.5,), "m", "z"))
        self.assertTrue(verify_world_dimensions(result, record, (1, 1, 1), "METRIC", 1)["passed"])
        cases = [(self.points, (1, 1, 1), "METRIC", 1), (result, (.0625,) * 3, "METRIC", 1),
                 (result, (1, 1, 1), "NONE", 1), (result, (1, 1, 1), "METRIC", .01)]
        for points, scale, unit, length in cases:
            with self.assertRaises(ValueError):
                verify_world_dimensions(points, record, scale, unit, length)

    def test_float32_impossible_target_and_zero_selected_axis_refuse(self):
        for size in (1e100, 1e-100):
            with self.assertRaises(ValueError):
                apply_dimensions(self.points, DimensionSpec("uniform_single_axis", (size,), "m", "z"))
        with self.assertRaises(ValueError):
            apply_dimensions(np.array([[0, 0, 0], [1, 0, 2]]), DimensionSpec("uniform_single_axis", (1,), "m", "y"))


if __name__ == "__main__":
    unittest.main()
