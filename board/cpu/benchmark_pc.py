"""PC CPU-only timing using the same inference API boundary as the board."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import psutil

from verify_ncnn import positive_probability, threshold_predictions

PACKAGE = Path(__file__).resolve().parent


def summarize(milliseconds):
    values = np.asarray(milliseconds, dtype=np.float64)
    if values.ndim != 1 or not len(values) or not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("timings must be a nonempty finite nonnegative sequence")
    return {
        "runs": int(len(values)),
        "mean_ms": float(values.mean()),
        "median_ms": float(np.median(values)),
        "p95_ms": float(np.percentile(values, 95)),
        "min_ms": float(values.min()),
        "max_ms": float(values.max()),
    }


def validate_inputs(inputs):
    if inputs.shape != (6, 3, 128, 128) or inputs.dtype != np.float32:
        raise ValueError("expected six float32 NCHW 128x128 golden inputs")
    if not np.isfinite(inputs).all():
        raise ValueError("non-finite input")


def reference_metrics(logits, reference, temperature, threshold):
    logits = np.asarray(logits)
    reference = np.asarray(reference)
    if logits.shape != reference.shape or not np.isfinite(reference).all():
        raise ValueError("invalid reference")
    probability = positive_probability(logits, temperature)
    prediction = threshold_predictions(probability, threshold)
    expected = threshold_predictions(positive_probability(reference, temperature), threshold)
    difference = np.abs(logits - reference)
    return {
        "logits": logits.tolist(),
        "max_abs_diff": float(difference.max()),
        "mean_abs_diff": float(difference.mean()),
        "argmax_mismatch_count": int(np.count_nonzero(logits.argmax(1) != reference.argmax(1))),
        "prediction": prediction.tolist(),
        "threshold_mismatch_count": int(np.count_nonzero(prediction != expected)),
    }


def snapshot(process):
    memory = process.memory_info()._asdict()
    return {
        "process_memory_bytes": memory,
        "rss_MiB": memory["rss"] / (1024 ** 2),
        "peak_working_set_MiB": memory.get("peak_wset", memory["rss"]) / (1024 ** 2),
        "peak_source": "Windows peak_wset" if "peak_wset" in memory else "current rss only, not OS peak",
        "host_memory": psutil.virtual_memory()._asdict(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, choices=("fp32", "kl", "eq"))
    parser.add_argument("--warmup", type=int, default=30)
    parser.add_argument("--runs", type=int, default=300)
    parser.add_argument("--output-json", required=True, type=Path)
    args = parser.parse_args()
    if args.warmup < 0 or args.runs < 1:
        parser.error("warmup >= 0 and runs >= 1 required")

    # Never invoke calibration/conversion tools here. This is runtime only.
    import ncnn

    contract = json.loads((PACKAGE / "interface/working_points.json").read_text())
    point = contract["candidates"][args.candidate]
    inputs = np.load(PACKAGE / "golden/input.npy", allow_pickle=False)
    validate_inputs(inputs)
    mats = [ncnn.Mat(np.ascontiguousarray(sample)) for sample in inputs]
    process = psutil.Process()
    before_load = snapshot(process)
    model_dir = PACKAGE / "models" / args.candidate
    start = time.perf_counter_ns()
    net = ncnn.Net()
    net.opt.num_threads = 1
    net.opt.use_vulkan_compute = False
    if net.load_param(str(model_dir / "model.param")) != 0:
        raise RuntimeError("model.param load failed")
    if net.load_model(str(model_dir / "model.bin")) != 0:
        raise RuntimeError("model.bin load failed")
    load_ms = (time.perf_counter_ns() - start) / 1e6
    after_load = snapshot(process)

    def infer(mat):
        extractor = net.create_extractor()
        if extractor.input(contract["input_blob"], mat) != 0:
            raise RuntimeError("input failed")
        status, output = extractor.extract(contract["output_blob"])
        if status != 0:
            raise RuntimeError("extract failed")
        logits = np.asarray(output.numpy(), dtype=np.float32).reshape(1, -1).copy()
        if logits.shape != (1, 2) or not np.isfinite(logits).all():
            raise RuntimeError("expected two finite logits")
        return logits

    logits = np.concatenate([infer(mat) for mat in mats], axis=0)
    reference = np.load(PACKAGE / f"references/{args.candidate}_logits.npy", allow_pickle=False)
    reference_check = reference_metrics(logits, reference, point["temperature"], point["threshold"])
    for index in range(args.warmup):
        infer(mats[index % len(mats)])
    before_cpu = process.cpu_times()
    wall_start = time.perf_counter_ns()
    timings = []
    for index in range(args.runs):
        start = time.perf_counter_ns()
        infer(mats[index % len(mats)])
        timings.append((time.perf_counter_ns() - start) / 1e6)
    phase_wall_ms = (time.perf_counter_ns() - wall_start) / 1e6
    after_cpu = process.cpu_times()
    result = {
        "measurement_date_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "processor": platform.processor(),
        "logical_cpus": os.cpu_count(),
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "psutil_version": psutil.__version__,
        "ncnn_version": ncnn.__version__,
        "ncnn_path": ncnn.__file__,
        "candidate": args.candidate,
        "batch": 1,
        "threads": int(net.opt.num_threads),
        "vulkan": bool(net.opt.use_vulkan_compute),
        "input_shape": list(inputs.shape),
        "warmup": args.warmup,
        "runs": args.runs,
        "reference_inferences_before_warmup": 6,
        "working_point": point,
        "reference_check": reference_check,
        "elapsed_clock": "time.perf_counter_ns (monotonic)",
        "timing_scope": "fresh extractor + input + synchronous extract + NumPy output copy/check; prepared Mat conversion, loading, preprocessing and postprocessing excluded",
        "memory_scope": "whole process including interpreter, libraries, golden inputs and model; not isolated model allocations",
        "before_model_load": before_load,
        "model_load_ms": load_ms,
        "after_model_load": after_load,
        "inference_api_ms": summarize(timings),
        "timing_ms_samples": timings,
        "phase_wall_ms": phase_wall_ms,
        "cpu_user_seconds": after_cpu.user - before_cpu.user,
        "cpu_system_seconds": after_cpu.system - before_cpu.system,
        "after_measurement": snapshot(process),
        "model_sha256": {
            name: hashlib.sha256((model_dir / name).read_bytes()).hexdigest()
            for name in ("model.param", "model.bin")
        },
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "board_script_sha256": hashlib.sha256((PACKAGE / "benchmark_ncnn.py").read_bytes()).hexdigest(),
        "input_sha256": hashlib.sha256((PACKAGE / "golden/input.npy").read_bytes()).hexdigest(),
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "candidate": args.candidate,
        "reference_check": reference_check,
        "inference_api_ms": result["inference_api_ms"],
        "peak_working_set_MiB": result["after_measurement"]["peak_working_set_MiB"],
        "output_json": str(args.output_json),
    }, indent=2))


if __name__ == "__main__":
    main()
