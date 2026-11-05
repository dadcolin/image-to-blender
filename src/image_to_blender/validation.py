# SPDX-License-Identifier: GPL-3.0-or-later
"""SHA-bound, relative-path artifact manifests. No machine-specific trust list."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path):
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream)


def write_json_new(path, record):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2, allow_nan=False)
        stream.write("\n")


def resolve_artifact(base, spec):
    base = Path(base).resolve()
    if not isinstance(spec, dict):
        raise ValueError("Artifact binding must be an object")
    text = spec.get("path")
    if not isinstance(text, str) or not text or "\\" in text:
        raise ValueError("Artifact path must be a portable relative POSIX path")
    relative = Path(text)
    if relative.is_absolute() or re.match(r"^[A-Za-z]:", text) or ".." in relative.parts:
        raise ValueError("Artifact path cannot be absolute or escape its manifest directory")
    path = (base / relative).resolve()
    if path == base or not path.is_relative_to(base) or not path.is_file():
        raise ValueError("Artifact must be a file within its manifest directory")
    expected = spec.get("sha256")
    size = spec.get("bytes")
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("Artifact requires a lowercase SHA256")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise ValueError("Artifact requires a positive byte length")
    if path.stat().st_size != size or sha256(path) != expected:
        raise ValueError("Artifact SHA256 or size differs from its manifest")
    return path


def artifact_record(path, base):
    path, base = Path(path).resolve(), Path(base).resolve()
    return {"path": path.relative_to(base).as_posix(), "sha256": sha256(path), "bytes": path.stat().st_size}


@dataclass(frozen=True)
class GaussianSource:
    manifest_path: Path
    artifact_path: Path
    manifest: dict
    manifest_sha256: str

    def bound_artifacts(self):
        """Resolve every local file referenced by the native-source contract.

        Image bindings are optional for imported native PLY files, but once
        present they have the same path/size/SHA requirements as the PLY. No
        external URL is fetched and absent optional fields are never invented.
        """
        return {key: resolve_artifact(self.manifest_path.parent, self.manifest[key])
                for key in ("artifact", "input", "model_input") if key in self.manifest}

    def revalidate(self):
        if sha256(self.manifest_path) != self.manifest_sha256:
            raise ValueError("Source manifest changed during processing")
        self.bound_artifacts()


def validate_source_manifest(path):
    path = Path(path).resolve()
    before = sha256(path)
    record = read_json(path)
    if record.get("schema_version") != 1 or record.get("kind") != "gaussian_source":
        raise ValueError("Expected schema_version=1 and kind=gaussian_source")
    if record.get("format") != "idol_standard_3dgs" or record.get("axis") not in ("y_up", "z_up"):
        raise ValueError("Expected explicit IDOL standard3DGS encoding and y_up/z_up coordinates")
    artifact = resolve_artifact(path.parent, record["artifact"])
    for key in ("input", "model_input"):
        if key in record:
            resolve_artifact(path.parent, record[key])
    if sha256(path) != before:
        raise ValueError("Source manifest changed while being read")
    return GaussianSource(path, artifact, record, before)


def validate_mesh_manifest(path):
    path = Path(path).resolve()
    before = sha256(path)
    record = read_json(path)
    if record.get("schema_version") != 1 or record.get("kind") != "density_mesh":
        raise ValueError("Expected a density_mesh manifest")
    if record.get("status") != "complete" or record.get("native_model_mesh") is not False:
        raise ValueError("Mesh must be complete and explicitly derived")
    if record.get("axis") not in ("y_up", "z_up") or record.get("color_encoding") != "display_rgb_assumed_srgb":
        raise ValueError("Mesh coordinate/color convention is missing")
    source_path = resolve_artifact(path.parent, record["source_manifest"])
    source = validate_source_manifest(source_path)
    if source.manifest["axis"] != record["axis"] or source.manifest["artifact"]["sha256"] != record["source_ply_sha256"]:
        raise ValueError("Mesh axis or source PLY binding is inconsistent")
    arrays = resolve_artifact(path.parent, record["arrays"])
    resolve_artifact(path.parent, record["triangle_ply"])
    resolve_artifact(path.parent, record["mesh_json"])
    if sha256(path) != before:
        raise ValueError("Mesh manifest changed while being read")
    return record, arrays, source
