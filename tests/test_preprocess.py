# SPDX-License-Identifier: GPL-3.0-or-later
from PIL import Image, PngImagePlugin
import pytest
from image_to_blender.preprocess import prepare_input


def test_metadata_removed_without_pixel_change(tmp_path):
    path = tmp_path / "input.png"
    image = Image.new("RGB", (24, 32), (250, 249, 248))
    info = PngImagePlugin.PngInfo()
    info.add_text("private", "must not survive")
    image.save(path, pnginfo=info)
    result = prepare_input(path)
    assert result.tobytes() == image.tobytes()
    assert result.info == {}


def test_alpha_contract(tmp_path):
    path = tmp_path / "cutout.png"
    image = Image.new("RGBA", (24, 24), (0, 0, 0, 0))
    image.paste((40, 80, 120, 255), (4, 4, 20, 20))
    image.save(path)
    assert prepare_input(path, "alpha").tobytes() == image.tobytes()
    Image.new("RGBA", (24, 24), (0, 0, 0, 255)).save(path)
    with pytest.raises(ValueError, match="transparent"):
        prepare_input(path, "alpha")


def test_explicit_hook(tmp_path, monkeypatch):
    import sys, types
    module = types.ModuleType("example_matting")
    def cutout(image):
        result = image.convert("RGBA")
        result.putpixel((0, 0), (0, 0, 0, 0))
        return result
    module.cutout = cutout
    monkeypatch.setitem(sys.modules, "example_matting", module)
    path = tmp_path / "input.png"
    Image.new("RGB", (24, 24), "white").save(path)
    assert prepare_input(path, hook="example_matting:cutout").mode == "RGBA"
