"""Append-only local capture storage and verified export for SYS-Round01.

No camera, board, or inference code is imported here. PNG defaults to explicit
level 6; saved RGB bytes are checked by decoding each written file.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import threading
import time
import uuid
import zipfile

import numpy as np
from PIL import Image


INDEX_FIELDS = ("capture_id", "mode", "frame_count", "risk_label", "refer_probability",
                "decision_threshold", "temperature", "model_identity",
                "inference_latency_ms", "bitstream_version")
_ID = re.compile(r"[0-9a-f]{32}\Z")
_LOCK = threading.RLock()


def _json_bytes(value):
    # Reject unsupported objects and non-finite numbers, including nested extras.
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")


def _finite(value, name, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite numeric data")
    if minimum is not None and value < minimum or maximum is not None and value > maximum:
        raise ValueError(f"{name} is out of range")


def _validate_result(result):
    if not isinstance(result, dict):
        raise TypeError("result must be a JSON dictionary")
    _json_bytes(result)
    if not isinstance(result.get("capture_id"), str) or not _ID.fullmatch(result["capture_id"]):
        raise ValueError("capture_id must be lowercase UUID hex")
    expected = {"normal": 1, "fusion": 3}.get(result.get("mode"))
    if expected is None or type(result.get("frame_count")) is not int or result["frame_count"] != expected:
        raise ValueError("normal mode requires one frame; fusion mode requires three frames")
    for field in ("risk_label", "model_identity", "bitstream_version"):
        if not isinstance(result.get(field), str) or not result[field].strip():
            raise ValueError(f"{field} must be a nonempty string")
    for field in ("refer_probability", "decision_threshold"):
        _finite(result.get(field), field, 0, 1)
    _finite(result.get("temperature"), "temperature", 0)
    if result["temperature"] == 0:
        raise ValueError("temperature must be positive")
    _finite(result.get("inference_latency_ms"), "inference_latency_ms", 0)


def _validate_metadata(frame, previous_sequence):
    if not isinstance(frame, dict):
        raise TypeError("each frame must be a dictionary")
    sequence = frame.get("sequence")
    if type(sequence) is not int or sequence <= previous_sequence:
        raise ValueError("frame sequences must be positive and strictly increasing")
    _finite(frame.get("captured_monotonic"), "captured_monotonic", 0)
    if not isinstance(frame.get("assessment"), dict):
        raise ValueError("frame assessment must be a JSON dictionary")
    _json_bytes({key: value for key, value in frame.items() if key != "rgb"})
    return sequence


def _linked(path):
    if not path.exists() and not path.is_symlink():
        return False
    info = path.lstat()
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) &
                                      getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _confined(root, path):
    path = Path(path).absolute()
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ValueError("path must remain inside the result root") from exc
    if ".." in relative.parts:
        raise ValueError("path traversal is forbidden")
    current = root
    for part in relative.parts:
        current = current / part
        if _linked(current):
            raise ValueError("linked files and directories are forbidden")
    return path


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _write_json(path, value, exclusive=False):
    with path.open("xb" if exclusive else "wb") as stream:
        stream.write(_json_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())


class ResultStore:
    """Save unique immutable cases; reaching limit refuses new cases, deleting none."""

    def __init__(self, root, limit=200, *, png_compress_level=6):
        if type(limit) is not int or limit < 1:
            raise ValueError("limit must be a positive integer")
        if type(png_compress_level) is not int or not 0 <= png_compress_level <= 9:
            raise ValueError("png_compress_level must be an integer from 0 through 9")
        self.root = Path(root).resolve()
        self.limit = limit
        self.png_compress_level = png_compress_level

    def save(self, result, frames):
        archive_started = time.perf_counter()
        _validate_result(result)
        if not isinstance(frames, list) or len(frames) != result["frame_count"]:
            raise ValueError("frames must contain exactly frame_count entries")
        shape, sequence = None, 0
        for frame in frames:
            sequence = _validate_metadata(frame, sequence)
            rgb = frame.get("rgb")
            if (not isinstance(rgb, np.ndarray) or rgb.dtype != np.uint8 or rgb.ndim != 3
                    or rgb.shape[2] != 3 or min(rgb.shape[:2]) < 1):
                raise ValueError("each rgb must be a nonempty uint8 HxWx3 array")
            if shape is not None and rgb.shape != shape:
                raise ValueError("all input frames must have the same shape")
            shape = rgb.shape
        # Copy JSON and arrays so callers cannot change the persisted capture mid-save.
        manifest = json.loads(_json_bytes(result))
        snapshots = [({k: json.loads(_json_bytes(v)) for k, v in f.items() if k != "rgb"},
                      np.array(f["rgb"], copy=True, order="C")) for f in frames]
        with _LOCK:
            case = _confined(self.root, self.root / ("capture_" + result["capture_id"]))
            if case.exists():
                raise FileExistsError(f"capture already exists: {case.name}")
            existing = list(self.root.glob("capture_*")) if self.root.exists() else []
            if len(existing) >= self.limit:
                raise ValueError("result store limit reached; existing cases were preserved")
            self.root.mkdir(parents=True, exist_ok=True)
            case.mkdir()  # Exclusive ownership; no old case is ever overwritten.
            result_path = case / "result.json"
            manifest.update(save_status="incomplete", images=[], case_dir=str(case), result_path=str(result_path),
                            png_compress_level=self.png_compress_level, png_nbytes=0)
            try:
                _write_json(result_path, manifest, exclusive=True)
                for index, (metadata, rgb) in enumerate(snapshots, 1):
                    filename = f"frame_{index:02d}.png"
                    image_path = case / filename
                    input_image = Image.fromarray(rgb)
                    with image_path.open("xb") as stream:
                        encode_started = time.perf_counter()
                        input_image.save(stream, format="PNG", compress_level=self.png_compress_level)
                        png_encode_write_ms = (time.perf_counter() - encode_started) * 1000.0
                        flush_started = time.perf_counter()
                        stream.flush()
                        os.fsync(stream.fileno())
                        flush_fsync_ms = (time.perf_counter() - flush_started) * 1000.0
                    readback_started = time.perf_counter()
                    png = image_path.read_bytes()
                    with Image.open(io.BytesIO(png)) as image:
                        readback = np.asarray(image)
                        if image.mode != "RGB" or not np.array_equal(readback, rgb):
                            raise OSError("PNG readback differs from input RGB")
                        readback_hash = _digest(readback.tobytes())
                    png_hash = _digest(png)
                    rgb_hash = _digest(rgb.tobytes())
                    readback_verify_ms = (time.perf_counter() - readback_started) * 1000.0
                    metadata.update(filename=filename, sha256=png_hash,
                                    rgb_sha256=rgb_hash,
                                    readback_rgb_sha256=readback_hash,
                                    shape=list(rgb.shape), dtype="uint8",
                                    png_compress_level=self.png_compress_level, png_nbytes=len(png),
                                    png_encode_write_ms=png_encode_write_ms,
                                    flush_fsync_ms=flush_fsync_ms, readback_verify_ms=readback_verify_ms)
                    manifest["images"].append(metadata)
                    manifest["png_nbytes"] += len(png)
                index_path = _confined(self.root, self.root / "index.csv")
                if index_path.exists():
                    with index_path.open(encoding="utf-8", newline="") as stream:
                        if next(csv.reader(stream), None) != list(INDEX_FIELDS):
                            raise ValueError("existing index.csv header is incompatible")
                is_new_index = not index_path.exists()
                with index_path.open("a", encoding="utf-8", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=INDEX_FIELDS)
                    if is_new_index:
                        writer.writeheader()
                    writer.writerow({key: result[key] for key in INDEX_FIELDS})
                    stream.flush()
                    os.fsync(stream.fileno())
                manifest["save_status"] = "complete"
                pending = case / "result.pending.json"
                manifest["archive_elapsed_before_commit_scope"] = (
                    "save entry through validation, snapshots, PNG encoding, flush/fsync, "
                    "readback verification and index update; excludes final complete JSON "
                    "serialization/write/fsync and atomic replace")
                manifest["archive_elapsed_before_commit_ms"] = (time.perf_counter() - archive_started) * 1000.0
                _write_json(pending, manifest, exclusive=True)
                os.replace(pending, result_path)
            except Exception as exc:
                manifest["save_status"] = "incomplete"
                manifest["save_error"] = f"{type(exc).__name__}: {exc}"
                try:
                    _write_json(result_path, manifest)
                except OSError:
                    pass  # Missing/invalid JSON is also excluded from every export.
                raise
            return manifest


def _verified_case(root, case):
    _confined(root, case)
    if not case.is_dir() or not _ID.fullmatch(case.name.removeprefix("capture_")):
        raise ValueError("malformed capture directory")
    result_path = _confined(root, case / "result.json")
    manifest_bytes = result_path.read_bytes()
    result = json.loads(manifest_bytes)
    _validate_result(result)
    if case.name != "capture_" + result["capture_id"] or result.get("save_status") != "complete":
        raise ValueError("capture identity mismatch or incomplete save")
    records = result.get("images")
    if not isinstance(records, list) or len(records) != result["frame_count"]:
        raise ValueError("image count mismatch")
    members = [(f"{case.name}/result.json", manifest_bytes)]
    sequence, shape = 0, None
    for index, record in enumerate(records, 1):
        sequence = _validate_metadata(record, sequence)
        filename = f"frame_{index:02d}.png"
        if record.get("filename") != filename:
            raise ValueError("unexpected image filename")
        png = _confined(root, case / filename).read_bytes()
        if _digest(png) != record.get("sha256"):
            raise ValueError("PNG file hash mismatch")
        with Image.open(io.BytesIO(png)) as image:
            rgb = np.asarray(image)
            if image.format != "PNG" or image.mode != "RGB" or rgb.dtype != np.uint8:
                raise ValueError("invalid RGB PNG")
            if list(rgb.shape) != record.get("shape") or record.get("dtype") != "uint8":
                raise ValueError("PNG shape/dtype mismatch")
            if shape is not None and rgb.shape != shape:
                raise ValueError("inconsistent frame shapes")
            shape = rgb.shape
            digest = _digest(rgb.tobytes())
            if digest != record.get("rgb_sha256") or digest != record.get("readback_rgb_sha256"):
                raise ValueError("PNG pixel hash mismatch")
        members.append((f"{case.name}/{filename}", png))
    return members, {key: result[key] for key in INDEX_FIELDS}


def export_results(root, destination=None):
    """Zip only verified complete captures and report each skipped capture.

    destination may be a ZIP path or a directory below root. Every archive gets
    an exclusive new filename; a requested existing filename is never replaced.
    """
    root = Path(root).resolve()
    with _LOCK:
        root.mkdir(parents=True, exist_ok=True)
        if destination is None:
            target = root / "exports" / f"results_{uuid.uuid4().hex}.zip"
        else:
            target = Path(destination)
            if not target.is_absolute():
                target = root / target
            target = _confined(root, target)
            if target.suffix.lower() != ".zip":
                target = target / f"results_{uuid.uuid4().hex}.zip"
        target = _confined(root, target)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target = target.with_name(f"{target.stem}_{uuid.uuid4().hex}.zip")
        report = {"complete_count": 0, "skipped_count": 0, "complete": [], "skipped": []}
        filtered_index = io.StringIO(newline="")
        index_writer = csv.DictWriter(filtered_index, fieldnames=INDEX_FIELDS)
        index_writer.writeheader()
        # ZIP_STORED avoids changing the baseline PNG compression or recompressing PNGs.
        with zipfile.ZipFile(target, mode="x", compression=zipfile.ZIP_STORED) as archive:
            for case in sorted(root.glob("capture_*")):
                try:
                    members, index_row = _verified_case(root, case)
                except Exception as exc:
                    report["skipped"].append({"case": case.name, "reason": f"{type(exc).__name__}: {exc}"})
                    report["skipped_count"] += 1
                    continue
                for name, data in members:
                    archive.writestr(name, data)
                index_writer.writerow(index_row)
                report["complete"].append(case.name)
                report["complete_count"] += 1
            archive.writestr("index.csv", filtered_index.getvalue().encode("utf-8"))
            archive.writestr("export_report.json", _json_bytes(report))
        return dict(archive_path=str(target), complete_count=report["complete_count"],
                    skipped_count=report["skipped_count"], report=report)
