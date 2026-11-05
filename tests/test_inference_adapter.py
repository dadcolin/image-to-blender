# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline adapter contracts, not model-quality or real-GPU acceptance tests.

The stand-in SDK writes a tiny synthetic PLY payload. Its hashes exercise
provenance plumbing only; no assertion treats it as an actual IDOL result.
"""
import hashlib
import json
from pathlib import Path
import sys
import types

from PIL import Image, PngImagePlugin
import psutil
import pytest

from image_to_blender import cli, inference
from image_to_blender.validation import validate_source_manifest


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture
def fake_sdk(tmp_path, monkeypatch):
    """Replace every model/download boundary before the adapter can import it."""
    weights = tmp_path / "tiny-test-weights"
    weights.mkdir()
    for name in inference.WEIGHT_NAMES:
        (weights / name).write_bytes(b"synthetic test weight: " + name.encode())
    sdk_file = tmp_path / "stand_in_pipeline.py"
    sdk_file.write_text("# Test stand-in; no trained model is executed.\n", encoding="utf-8")
    state = types.SimpleNamespace(
        weights=weights, sdk_file=sdk_file, loads=[], calls=[], saves=[], downloads=[],
        fail=None, cuda_available=False, cuda_queries=0,
    )
    torch = types.ModuleType("torch")

    def cuda_available():
        state.cuda_queries += 1
        return state.cuda_available

    torch.cuda = types.SimpleNamespace(is_available=cuda_available)
    idol = types.ModuleType("idol")
    idol.__path__ = []
    sdk = types.ModuleType("idol.pipeline")
    sdk.__file__ = str(sdk_file)
    models = types.ModuleType("idol.models")
    models.__path__ = []
    layers = types.ModuleType("idol.models.layers")
    layers.ATTN_BACKEND = "test-unset"

    class FakeGaussian:
        def save_ply(self, path):
            state.saves.append(Path(path))
            if state.fail == "save":
                raise RuntimeError("synthetic failure detail must not enter receipt")
            Path(path).write_bytes(b"ply\nformat ascii 1.0\ncomment synthetic adapter test\nend_header\n")

    class FakePipeline:
        @classmethod
        def from_pretrained(cls, path, **kwargs):
            state.loads.append((path, kwargs))
            if state.fail == "load":
                raise RuntimeError("synthetic failure detail must not enter receipt")
            return cls()

        def __call__(self, image, **kwargs):
            state.calls.append((image.copy(), kwargs))
            if state.fail == "infer":
                raise RuntimeError("synthetic failure detail must not enter receipt")
            processed = Image.new("RGBA", (18, 20), (19, 37, 83, 255))
            processed.info.update(comment="discard model metadata", icc_profile=b"discard profile")
            processed.getexif()[315] = "discard author metadata"
            state.processed = processed.copy()
            return types.SimpleNamespace(gaussian=FakeGaussian(), preprocessed_image=processed,
                                         camera={"width": 18, "height": 20, "focal": 24.0})

    sdk.IdolPipeline = FakePipeline
    idol.pipeline = sdk
    idol.models = models
    models.layers = layers
    hub = types.ModuleType("huggingface_hub")

    def snapshot_download(repo, **kwargs):
        state.downloads.append((repo, kwargs))
        return str(weights)

    hub.snapshot_download = snapshot_download
    for name, module in (("torch", torch), ("idol", idol), ("idol.pipeline", sdk),
                         ("idol.models", models), ("idol.models.layers", layers),
                         ("huggingface_hub", hub)):
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(psutil, "virtual_memory", lambda: types.SimpleNamespace(available=64 * 2**30))
    monkeypatch.setattr(inference.importlib.metadata, "version", lambda name: "0.0.test")
    state.layers = layers
    return state


@pytest.fixture
def source_image(tmp_path):
    path = tmp_path / "input.png"
    image = Image.new("RGB", (24, 32), (71, 109, 143))
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("comment", "discard input metadata")
    exif = Image.Exif()
    exif[315] = "discard input author"
    image.save(path, pnginfo=metadata, exif=exif, icc_profile=b"discard input profile")
    return path


def test_real_adapter_sanitizes_images_binds_files_and_forwards_parameters(tmp_path, fake_sdk, source_image):
    before = source_image.read_bytes()
    output = tmp_path / "native"
    manifest = inference.infer(
        source_image, output, weights=fake_sdk.weights, device="cpu", seed=2026,
        steps=13, num_gaussians=32768, crop_margin=2.25, cfg_strength=4.5,
        min_available_gib=3.0,
    )
    assert manifest == output / "source-manifest.json"
    assert source_image.read_bytes() == before
    assert fake_sdk.downloads == []
    assert fake_sdk.cuda_queries == 0
    assert fake_sdk.loads == [(str(fake_sdk.weights), {
        "device": "cpu", "dinov3_dtype": "bf16", "optimize": False,
    })]
    assert len(fake_sdk.calls) == 1
    passed_image, parameters = fake_sdk.calls[0]
    assert passed_image.info == {}
    assert parameters == {
        "mode": "real", "seed": 2026, "steps": 13, "num_gaussians": 32768,
        "crop_margin": 2.25, "cfg_strength": 4.5, "rescale_t": 3.0,
    }
    assert fake_sdk.layers.ATTN_BACKEND == "sdpa"
    assert fake_sdk.saves == [output / "native.ply"]
    with Image.open(source_image) as original, Image.open(output / "source.png") as saved:
        assert saved.tobytes() == original.convert("RGB").tobytes()
        assert saved.info == {}
        assert not saved.getexif()
    with Image.open(output / "model-input.png") as saved:
        assert saved.mode == "RGB"
        assert saved.tobytes() == fake_sdk.processed.convert("RGB").tobytes()
        assert saved.info == {}
        assert not saved.getexif()
    record = json.loads(manifest.read_text())
    assert record["kind"] == "gaussian_source"
    assert record["format"] == "idol_standard_3dgs"
    assert record["axis"] == "y_up"
    assert record["gaussian_count"] == 32768
    assert record["automatic_retry"] is False
    assert record["geometry_accuracy_approved"] is False
    for key, name in (("artifact", "native.ply"), ("input", "source.png"),
                      ("model_input", "model-input.png")):
        assert record[key] == {"path": name, "sha256": file_sha(output / name),
                               "bytes": (output / name).stat().st_size}
    assert record["model"]["repo"] == "speridlabs/idol"
    assert record["model"]["weight_sha256"] == {
        name: file_sha(fake_sdk.weights / name) for name in inference.WEIGHT_NAMES
    }
    assert record["model"]["sdk_pipeline_sha256"] == file_sha(fake_sdk.sdk_file)
    assert record["parameters"] == dict(parameters, optimize=False, attention="sdpa",
                                        input_background="white", external_matting_used=False)
    # Verify the public manifest consumer binds the files, then detects tampering.
    source = validate_source_manifest(manifest)
    source.revalidate()
    with (output / "model-input.png").open("ab") as stream:
        stream.write(b"tampered")
    with pytest.raises(ValueError, match="SHA256 or size"):
        source.revalidate()
    serialized = manifest.read_text()
    assert str(tmp_path) not in serialized
    assert "discard" not in serialized


def test_default_download_is_pinned_and_restricted_to_expected_files(tmp_path, fake_sdk, source_image):
    inference.infer(source_image, tmp_path / "native", device="cpu")
    assert fake_sdk.downloads == [("speridlabs/idol", {
        "revision": inference.IDOL_REVISION, "allow_patterns": list(inference.WEIGHT_NAMES),
    })]
    assert len(fake_sdk.loads) == len(fake_sdk.calls) == 1


@pytest.mark.parametrize("stage,counts", [("load", (1, 0, 0)), ("infer", (1, 1, 0)), ("save", (1, 1, 1))])
def test_failures_propagate_once_and_do_not_publish_success(tmp_path, fake_sdk, source_image, stage, counts):
    fake_sdk.fail = stage
    output = tmp_path / "native"
    with pytest.raises(RuntimeError, match="synthetic failure"):
        inference.infer(source_image, output, weights=fake_sdk.weights, device="cpu")
    assert (len(fake_sdk.loads), len(fake_sdk.calls), len(fake_sdk.saves)) == counts
    assert not (output / "source-manifest.json").exists()
    assert json.loads((output / "failure.json").read_text()) == {
        "stage": "inference", "error_type": "RuntimeError", "automatic_retry": False,
    }
    assert "synthetic failure detail" not in (output / "failure.json").read_text()


def test_unavailable_cuda_never_falls_back_or_downloads(tmp_path, fake_sdk, source_image):
    output = tmp_path / "native"
    with pytest.raises(RuntimeError, match="no implicit CPU fallback"):
        inference.infer(source_image, output, device="cuda:0")
    assert fake_sdk.cuda_queries == 1
    assert fake_sdk.downloads == fake_sdk.loads == fake_sdk.calls == []
    assert not (output / "source-manifest.json").exists()


@pytest.mark.parametrize("overrides", [
    {"steps": 0}, {"steps": 1001}, {"num_gaussians": 32769},
    {"num_gaussians": 32736}, {"num_gaussians": 1048608},
    {"crop_margin": 0.9}, {"crop_margin": float("nan")},
    {"cfg_strength": float("inf")}, {"min_available_gib": 0},
    {"min_available_gib": float("inf")}, {"background": "unknown"},
])
def test_invalid_configuration_rejected_before_model_or_output(tmp_path, fake_sdk, source_image, overrides):
    output = tmp_path / "native"
    with pytest.raises(ValueError):
        inference.infer(source_image, output, weights=fake_sdk.weights, device="cpu", **overrides)
    assert fake_sdk.loads == fake_sdk.calls == fake_sdk.downloads == []
    assert not output.exists()


def test_memory_floor_rejected_before_any_model_work(tmp_path, monkeypatch, fake_sdk, source_image):
    monkeypatch.setattr(psutil, "virtual_memory", lambda: types.SimpleNamespace(available=2 * 2**30))
    output = tmp_path / "native"
    with pytest.raises(MemoryError, match="no model loaded"):
        inference.infer(source_image, output, weights=fake_sdk.weights, device="cpu", min_available_gib=3)
    assert fake_sdk.loads == fake_sdk.downloads == []
    assert not output.exists()


@pytest.mark.parametrize("kind", ["tiny", "invalid_file", "opaque_alpha"])
def test_invalid_image_rejected_before_model_work(tmp_path, fake_sdk, kind):
    image = tmp_path / "bad.png"
    options = {}
    if kind == "tiny":
        Image.new("RGB", (15, 24)).save(image)
    elif kind == "invalid_file":
        image.write_bytes(b"not an image")
    else:
        Image.new("RGBA", (24, 24), (1, 2, 3, 255)).save(image)
        options["background"] = "alpha"
    output = tmp_path / "native"
    with pytest.raises((ValueError, OSError)):
        inference.infer(image, output, weights=fake_sdk.weights, device="cpu", **options)
    assert fake_sdk.loads == fake_sdk.calls == []
    assert not output.exists()


def test_missing_local_weight_fails_before_loading_and_existing_output_is_preserved(tmp_path, fake_sdk, source_image):
    (fake_sdk.weights / inference.WEIGHT_NAMES[-1]).unlink()
    output = tmp_path / "native"
    with pytest.raises(FileNotFoundError):
        inference.infer(source_image, output, weights=fake_sdk.weights, device="cpu")
    assert fake_sdk.loads == fake_sdk.calls == []
    assert not (output / "source-manifest.json").exists()
    previous = {path.name: path.read_bytes() for path in output.iterdir()}
    with pytest.raises(FileExistsError):
        inference.infer(source_image, output, weights=fake_sdk.weights, device="cpu")
    assert previous == {path.name: path.read_bytes() for path in output.iterdir()}


def test_cli_worker_passes_options_to_real_adapter(tmp_path, monkeypatch, fake_sdk, source_image, capsys):
    matting = types.ModuleType("test_matting_hook")

    def cutout(image):
        assert image.info == {}
        result = image.convert("RGBA")
        result.putpixel((0, 0), (0, 0, 0, 0))
        result.info["comment"] = "discard hook metadata"
        return result

    matting.cutout = cutout
    monkeypatch.setitem(sys.modules, "test_matting_hook", matting)
    output = tmp_path / "native"
    assert cli.main([
        "_infer", str(source_image), "--output", str(output), "--weights", str(fake_sdk.weights),
        "--device", "cpu", "--seed", "7", "--steps", "9", "--num-gaussians", "65536",
        "--crop-margin", "1.9", "--inference-min-free-gib", "4",
        "--matting-hook", "test_matting_hook:cutout",
    ]) == 0
    assert capsys.readouterr().out.strip() == str(output / "source-manifest.json")
    image, parameters = fake_sdk.calls[0]
    assert image.mode == "RGBA" and image.getpixel((0, 0))[3] == 0
    assert image.info == {}
    assert parameters["seed"] == 7 and parameters["steps"] == 9
    assert parameters["num_gaussians"] == 65536 and parameters["crop_margin"] == 1.9
    record = json.loads((output / "source-manifest.json").read_text())
    assert record["parameters"]["external_matting_used"] is True


@pytest.mark.parametrize("worker_fails", [False, True])
def test_cli_parent_has_one_guarded_inference_handoff(tmp_path, monkeypatch, source_image, worker_fails, capsys):
    output = tmp_path / "run"
    weights = tmp_path / "weights with spaces"
    guards, meshes = [], []

    def guard(argv, directory, stage, **limits):
        guards.append((argv, directory, stage, limits))
        if worker_fails:
            raise RuntimeError("test worker failed")

    def mesh(source, destination):
        meshes.append((source, destination))
        return destination / "mesh" / "mesh-manifest.json"

    monkeypatch.setattr(cli, "guarded", guard)
    monkeypatch.setattr(cli, "mesh_stage", mesh)
    argv = [
        "reconstruct", str(source_image), "--output", str(output), "--weights", str(weights),
        "--device", "cpu", "--seed", "18", "--steps", "11", "--num-gaussians", "32768",
        "--crop-margin", "2.1", "--inference-min-free-gib", "3",
        "--inference-max-rss-gib", "5", "--inference-timeout", "42",
        "--matting-hook", "example:cutout",
    ]
    if worker_fails:
        with pytest.raises(RuntimeError, match="test worker failed"):
            cli.main(argv)
        assert meshes == []
    else:
        assert cli.main(argv) == 0
        assert meshes == [(output / "native" / "source-manifest.json", output / "derived")]
    assert len(guards) == 1
    command, directory, stage, limits = guards[0]
    assert command[:6] == [sys.executable, "-B", "-m", "image_to_blender.cli", "_infer", str(source_image)]
    parsed = cli.parser().parse_args(command[4:])
    assert parsed.output == str(output / "native")
    assert parsed.weights == str(weights) and parsed.matting_hook == "example:cutout"
    assert (parsed.device, parsed.seed, parsed.steps, parsed.num_gaussians) == ("cpu", 18, 11, 32768)
    assert parsed.crop_margin == 2.1 and parsed.inference_min_free_gib == 3
    assert directory == output and stage == "inference"
    assert limits == {"max_memory_gib": 5, "min_available_gib": 3, "timeout_seconds": 42}
    capsys.readouterr()
