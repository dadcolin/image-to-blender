# SPDX-License-Identifier: GPL-3.0-or-later
"""Input contract and an explicit hook for independently installed matting tools."""
import importlib
from pathlib import Path

from PIL import Image, ImageOps


def prepare_input(path, background="white", hook=None):
    """Return pixels only. White mode retains upstream IDOL's BiRefNet removal.

    A hook is explicitly trusted Python code, ``module:function``. It receives
    a detached PIL RGB/RGBA image and must return a nonempty RGBA cutout.
    No hook is discovered, installed, downloaded or run automatically.
    """
    if background not in ("white", "alpha"):
        raise ValueError("Choose a white-background photo or an alpha cutout")
    with Image.open(Path(path)) as original:
        oriented = ImageOps.exif_transpose(original)
        mode = "RGBA" if "A" in oriented.getbands() or "transparency" in oriented.info else "RGB"
        converted = oriented.convert(mode)
        # No EXIF, ICC, comment, filename or image.info is carried to the output.
        pixels = Image.frombytes(mode, converted.size, converted.tobytes())
    if min(pixels.size) < 16 or max(pixels.size) > 16384:
        raise ValueError("Input sides must be between 16 and 16384 pixels")
    if hook:
        module, separator, name = hook.partition(":")
        if not separator or not module or not name or ":" in name:
            raise ValueError("Matting hook must be an explicit module:function")
        pixels = getattr(importlib.import_module(module), name)(pixels.copy())
        background = "alpha"
    if background == "alpha":
        if not isinstance(pixels, Image.Image) or pixels.mode != "RGBA":
            raise ValueError("A cutout must be a PIL RGBA image")
        low, high = pixels.getchannel("A").getextrema()
        if low == 255 or high == 0:
            raise ValueError("Cutout needs both transparent and visible pixels")
    else:
        # White mode deliberately delegates object masking to upstream BiRefNet.
        pixels = pixels.convert("RGB")
    return Image.frombytes(pixels.mode, pixels.size, pixels.tobytes())
