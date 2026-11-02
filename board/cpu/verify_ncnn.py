"""Run a single-input ncnn model on preprocessed NCHW .npy vectors."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

DEFAULT_MEAN = (0.66557, 0.522759, 0.462534)
DEFAULT_STD = (0.14092, 0.140212, 0.146932)


def preprocess_rgb_uint8(rgb: np.ndarray, mean=DEFAULT_MEAN,
                         std=DEFAULT_STD) -> np.ndarray:
    rgb = np.asarray(rgb)
    if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("image must be an HxWx3 RGB uint8 array")
    if rgb.shape[0] == 0 or rgb.shape[1] == 0:
        raise ValueError("image dimensions must be non-zero")
    mean = np.asarray(mean, dtype=np.float32)
    std = np.asarray(std, dtype=np.float32)
    if mean.shape != (3,) or std.shape != (3,):
        raise ValueError("mean and std must each contain three RGB values")
    if not np.isfinite(mean).all() or not np.isfinite(std).all() or np.any(std <= 0):
        raise ValueError("normalization values must be finite and std positive")

    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required for the contract resize") from exc
    # Pillow < 9.1 exposes BILINEAR directly on Image rather than Resampling.
    resampling = getattr(Image, "Resampling", Image)
    resized = Image.fromarray(rgb).resize((128, 128), resampling.BILINEAR)
    chw = np.asarray(resized, dtype=np.float32).transpose(2, 0, 1) / 255.0
    normalized = (chw - mean.reshape(3, 1, 1)) / std.reshape(3, 1, 1)
    return np.ascontiguousarray(normalized[None, ...], dtype=np.float32)


def positive_probability(logits: np.ndarray, temperature: float) -> np.ndarray:
    logits = np.asarray(logits)
    if logits.ndim != 2 or logits.shape[1] != 2:
        raise ValueError("logits must have shape [N, 2]")
    if not np.isfinite(logits).all():
        raise ValueError("logits must contain only finite values")
    if not np.isfinite(temperature) or temperature <= 0:
        raise ValueError("temperature must be finite and positive")

    scaled = logits.astype(np.float64) / float(temperature)
    scaled -= scaled.max(axis=1, keepdims=True)
    exp_logits = np.exp(scaled)
    return exp_logits[:, 1] / exp_logits.sum(axis=1)


def threshold_predictions(probability: np.ndarray, threshold: float) -> np.ndarray:
    probability = np.asarray(probability, dtype=np.float64)
    if probability.ndim != 1 or not np.isfinite(probability).all():
        raise ValueError("probability must be a finite one-dimensional array")
    if not np.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be in [0, 1]")
    return (probability >= float(threshold)).astype(np.int64)


def run_ncnn(param_path: Path, bin_path: Path, inputs: np.ndarray,
             input_name: str = "in0", output_name: str = "out0") -> np.ndarray:
    try:
        import ncnn
    except ImportError as exc:
        raise RuntimeError("ncnn Python runtime is not installed") from exc

    inputs = np.asarray(inputs, dtype=np.float32)
    if inputs.ndim != 4 or inputs.shape[1:] != (3, 128, 128):
        raise ValueError("inputs must have shape [N, 3, 128, 128]")
    if inputs.shape[0] == 0 or not np.isfinite(inputs).all():
        raise ValueError("inputs must be non-empty and finite")

    net = ncnn.Net()
    if net.load_param(str(param_path)) != 0:
        raise RuntimeError(f"failed to load ncnn param: {param_path}")
    if net.load_model(str(bin_path)) != 0:
        raise RuntimeError(f"failed to load ncnn model: {bin_path}")

    outputs = []
    for sample in inputs:
        sample = np.ascontiguousarray(sample)
        extractor = net.create_extractor()
        if extractor.input(input_name, ncnn.Mat(sample)) != 0:
            raise RuntimeError(f"ncnn input failed: {input_name}")
        status, output = extractor.extract(output_name)
        if status != 0:
            raise RuntimeError(f"ncnn output failed: {output_name}")
        logits = np.asarray(output.numpy(), dtype=np.float32).reshape(-1)
        if logits.shape != (2,) or not np.isfinite(logits).all():
            raise RuntimeError(f"expected two finite logits, got {logits.shape}")
        outputs.append(logits.copy())
    return np.stack(outputs)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-param", required=True, type=Path)
    parser.add_argument("--model-bin", required=True, type=Path)
    input_source = parser.add_mutually_exclusive_group(required=True)
    input_source.add_argument("--inputs", type=Path,
                              help="preprocessed float32 NCHW .npy, [N,3,128,128]")
    input_source.add_argument("--image", type=Path,
                              help="one RGB image to preprocess with the contract")
    parser.add_argument("--reference", type=Path,
                        help="optional expected logits .npy, [N,2]")
    parser.add_argument("--input-name", default="in0")
    parser.add_argument("--output-name", default="out0")
    parser.add_argument("--temperature", type=float, default=0.8904876994104525)
    parser.add_argument("--threshold", type=float, default=0.697673760670338)
    parser.add_argument("--output-json", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.image:
        from PIL import Image
        with Image.open(args.image) as image:
            inputs = preprocess_rgb_uint8(np.asarray(image.convert("RGB")))
    else:
        inputs = np.load(args.inputs, allow_pickle=False)
    logits = run_ncnn(args.model_param, args.model_bin, inputs,
                      args.input_name, args.output_name)
    probability = positive_probability(logits, args.temperature)
    predictions = threshold_predictions(probability, args.threshold)
    result = {
        "samples": int(len(inputs)),
        "input_shape": list(inputs.shape),
        "input_source": str(args.image if args.image else args.inputs),
        "logits": logits.tolist(),
        "positive_probability": probability.tolist(),
        "prediction": predictions.tolist(),
        "positive_class_index": 1,
        "temperature": args.temperature,
        "threshold": args.threshold,
        "comparison": ">=",
    }
    if args.reference:
        if args.image:
            raise ValueError("--reference can only be used with --inputs")
        reference = np.load(args.reference, allow_pickle=False)
        if reference.shape != logits.shape:
            raise ValueError("reference shape must match model logits")
        difference = np.abs(logits - reference)
        result["reference_comparison"] = {
            "max_abs_diff": float(difference.max()),
            "mean_abs_diff": float(difference.mean()),
            "argmax_mismatch_count": int(np.count_nonzero(
                logits.argmax(axis=1) != reference.argmax(axis=1))),
        }
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output_json:
        args.output_json.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
