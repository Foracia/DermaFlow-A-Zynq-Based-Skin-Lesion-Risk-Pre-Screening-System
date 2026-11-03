"""Dataset parsing and preprocessing for the delivered v12 inference contract."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image
import json


@dataclass(frozen=True)
class Sample:
    relative_path: str
    label: int
    disease: str
    path: Path
    patient_id: str = ""
    lesion_id: str = ""


def read_calibration_list(manifest: Path, image_root: Path) -> list[Sample]:
    """Parse path/label/disease TSV rows and ensure each image resolves safely."""
    manifest = Path(manifest)
    image_root = Path(image_root).resolve()
    rows: list[Sample] = []
    seen: set[str] = set()

    for line_number, raw in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        fields = raw.split("\t")
        if len(fields) != 3:
            raise ValueError(f"{manifest}:{line_number}: expected 3 tab-separated columns")
        relative_path, raw_label, disease = fields
        if relative_path in seen:
            raise ValueError(f"{manifest}:{line_number}: duplicate image path {relative_path!r}")
        seen.add(relative_path)
        try:
            label = int(raw_label)
        except ValueError as exc:
            raise ValueError(f"{manifest}:{line_number}: label must be 0 or 1") from exc
        if label not in (0, 1):
            raise ValueError(f"{manifest}:{line_number}: label must be 0 or 1")

        path = (image_root / Path(relative_path)).resolve()
        if not path.is_relative_to(image_root):
            raise ValueError(f"{manifest}:{line_number}: image path escapes image root")
        if not path.is_file():
            raise FileNotFoundError(f"{manifest}:{line_number}: image not found: {path}")
        rows.append(Sample(relative_path, label, disease, path))

    if not rows:
        raise ValueError(f"calibration manifest is empty: {manifest}")
    return rows


def read_split(split_file: Path, split_name: str, image_root: Path) -> list[Sample]:
    """Read one delivered split while preserving patient and lesion identifiers."""
    if split_name not in {"train", "val", "test"}:
        raise ValueError("split_name must be train, val, or test")
    payload = json.loads(Path(split_file).read_text(encoding="utf-8"))
    if split_name not in payload:
        raise ValueError(f"split file has no {split_name!r} partition")

    image_root = Path(image_root).resolve()
    rows: list[Sample] = []
    seen: set[str] = set()
    for index, fields in enumerate(payload[split_name]):
        if not isinstance(fields, list) or len(fields) != 4:
            raise ValueError(f"{split_file}:{split_name}[{index}]: expected 4 fields")
        relative_path, raw_label, patient_id, lesion_id = fields
        if not isinstance(relative_path, str) or relative_path in seen:
            raise ValueError(f"{split_file}:{split_name}[{index}]: invalid or duplicate path")
        seen.add(relative_path)
        if raw_label not in (0, 1):
            raise ValueError(f"{split_file}:{split_name}[{index}]: label must be 0 or 1")
        path = (image_root / Path(relative_path)).resolve()
        if not path.is_relative_to(image_root):
            raise ValueError(f"{split_file}:{split_name}[{index}]: path escapes image root")
        if not path.is_file():
            raise FileNotFoundError(f"{split_file}:{split_name}[{index}]: image not found: {path}")
        disease = Path(relative_path).stem.rsplit("_", 1)[-1]
        rows.append(Sample(relative_path, int(raw_label), disease, path,
                           str(patient_id), str(lesion_id)))
    if not rows:
        raise ValueError(f"split is empty: {split_name}")
    return rows


def load_image_tensor(
    image_path: Path,
    mean: tuple[float, float, float],
    std: tuple[float, float, float],
    size: tuple[int, int] = (128, 128),
) -> np.ndarray:
    """Return one RGB PIL-bilinear, normalized float32 NCHW image."""
    if len(mean) != 3 or len(std) != 3 or any(value <= 0 for value in std):
        raise ValueError("mean/std must each have three channels and std must be positive")
    width, height = size
    if width <= 0 or height <= 0:
        raise ValueError("size dimensions must be positive")

    with Image.open(image_path) as source:
        image = source.convert("RGB").resize(
            (width, height), resample=Image.Resampling.BILINEAR
        )
        pixels = np.asarray(image, dtype=np.float32) / np.float32(255.0)

    channel_mean = np.asarray(mean, dtype=np.float32).reshape(1, 1, 3)
    channel_std = np.asarray(std, dtype=np.float32).reshape(1, 1, 3)
    normalized = (pixels - channel_mean) / channel_std
    return np.ascontiguousarray(normalized.transpose(2, 0, 1)[None, ...], dtype=np.float32)
