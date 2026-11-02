"""User-operated Linux board benchmark; no installation or system changes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import resource
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import ncnn
import numpy as np

from verify_ncnn import (
    positive_probability,
    preprocess_rgb_uint8,
    threshold_predictions,
)

ROOT = Path(__file__).resolve().parent


def snapshot() -> dict:
    memory = {}
    for line in Path("/proc/self/status").read_text().splitlines():
        key, _, value = line.partition(":")
        if key in ("VmRSS", "VmHWM"):
            memory[key + "_KiB"] = int(value.split()[0])
    nodes = {}
    patterns = (
        (Path("/sys/devices/system/cpu"), "cpu*/cpufreq/scaling_cur_freq"),
        (Path("/sys/devices/system/cpu"), "cpu*/cpufreq/scaling_governor"),
        (Path("/sys/class/thermal"), "thermal_zone*/temp"),
    )
    for directory, pattern in patterns:
        for path in directory.glob(pattern):
            try:
                nodes[str(path)] = path.read_text().strip()
            except OSError:
                nodes[str(path)] = None
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "process_memory": memory,
        "process_peak_rss_KiB": int(usage.ru_maxrss),
        "load_average": list(os.getloadavg()),
        "frequency_governor_temperature_raw": nodes,
    }


def describe(milliseconds: list[float]) -> dict:
    values = np.asarray(milliseconds, dtype=np.float64)
    if not len(values) or not np.isfinite(values).all() or (values < 0).any():
        raise RuntimeError("invalid timing samples")
    return {
        "runs": int(len(values)),
        "mean_ms": float(values.mean()),
        "median_ms": float(np.median(values)),
        "p95_ms": float(np.percentile(values, 95)),
        "min_ms": float(values.min()),
        "max_ms": float(values.max()),
    }


def measure(label, step, warmup, runs):
    print(f"{label}: warmup={warmup}, runs={runs}", flush=True)
    for index in range(warmup):
        step(index)
    before = resource.getrusage(resource.RUSAGE_SELF)
    wall_start = time.perf_counter_ns()
    durations = []
    for index in range(runs):
        durations.append(step(index))
        if (index + 1) % min(25, runs) == 0:
            print(f"{label}: {index + 1}/{runs}", flush=True)
    wall_ms = (time.perf_counter_ns() - wall_start) / 1e6
    after = resource.getrusage(resource.RUSAGE_SELF)
    result = {
        "phase_wall_ms_including_loop_and_progress": wall_ms,
        "cpu_user_seconds": after.ru_utime - before.ru_utime,
        "cpu_system_seconds": after.ru_stime - before.ru_stime,
        "process_snapshot_after_phase": snapshot(),
    }
    # A step returns named durations; percentile of the total is measured
    # directly, never obtained by summing individual stage percentiles.
    for key in durations[0]:
        result[key] = describe([item[key] for item in durations])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, choices=("fp32", "kl", "eq"))
    parser.add_argument("--threads", type=int, default=1, choices=(1, 2))
    parser.add_argument("--warmup", type=int, default=30)
    parser.add_argument("--runs", type=int, default=300)
    parser.add_argument("--image", type=Path)
    parser.add_argument("--output-json", type=Path, required=True)
    args = parser.parse_args()
    if args.warmup < 0 or args.runs < 1:
        parser.error("warmup must be >= 0 and runs must be >= 1")
    if not sys.platform.startswith("linux"):
        parser.error("this measurement entry is for the Linux board")

    contract = json.loads((ROOT / "interface/working_points.json").read_text())
    point = contract["candidates"][args.candidate]
    inputs = np.load(ROOT / "golden/input.npy", allow_pickle=False)
    if inputs.shape != (6, 3, 128, 128) or inputs.dtype != np.float32:
        raise RuntimeError("expected six float32 NCHW golden inputs")
    if not np.isfinite(inputs).all():
        raise RuntimeError("non-finite input")
    mats = [ncnn.Mat(np.ascontiguousarray(sample)) for sample in inputs]
    before_load = snapshot()
    model_dir = ROOT / "models" / args.candidate
    start = time.perf_counter_ns()
    net = ncnn.Net()
    net.opt.num_threads = args.threads
    net.opt.use_vulkan_compute = False
    if net.load_param(str(model_dir / "model.param")) != 0:
        raise RuntimeError("failed to load model.param")
    if net.load_model(str(model_dir / "model.bin")) != 0:
        raise RuntimeError("failed to load model.bin")
    load_ms = (time.perf_counter_ns() - start) / 1e6
    after_load = snapshot()

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

    # This correctness check performs six inferences before explicit warmup.
    logits = np.concatenate([infer(mat) for mat in mats], axis=0)
    reference = np.load(ROOT / f"references/{args.candidate}_logits.npy", allow_pickle=False)
    if reference.shape != logits.shape or not np.isfinite(reference).all():
        raise RuntimeError("invalid reference")
    probability = positive_probability(logits, point["temperature"])
    prediction = threshold_predictions(probability, point["threshold"])
    expected = threshold_predictions(
        positive_probability(reference, point["temperature"]), point["threshold"]
    )
    difference = np.abs(logits - reference)

    def tensor_step(index):
        start = time.perf_counter_ns()
        infer(mats[index % len(mats)])
        return {"inference_api_ms": (time.perf_counter_ns() - start) / 1e6}

    result = {
        "board_wall_clock_utc_unverified": datetime.now(timezone.utc).isoformat(),
        "elapsed_clock": "time.perf_counter_ns (monotonic)",
        "platform": platform.platform(),
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "ncnn_version": ncnn.__version__,
        "ncnn_path": ncnn.__file__,
        "candidate": args.candidate,
        "threads": int(net.opt.num_threads),
        "vulkan": bool(net.opt.use_vulkan_compute),
        "batch": 1,
        "warmup_per_phase": args.warmup,
        "runs_per_phase": args.runs,
        "reference_inferences_before_warmup": 6,
        "working_point": point,
        "model_sha256": {
            name: hashlib.sha256((model_dir / name).read_bytes()).hexdigest()
            for name in ("model.param", "model.bin")
        },
        "reference_check": {
            "logits": logits.tolist(),
            "max_abs_diff": float(difference.max()),
            "mean_abs_diff": float(difference.mean()),
            "argmax_mismatch_count": int(np.count_nonzero(logits.argmax(1) != reference.argmax(1))),
            "prediction": prediction.tolist(),
            "threshold_mismatch_count": int(np.count_nonzero(prediction != expected)),
        },
        "before_model_load": before_load,
        "model_load_ms": load_ms,
        "after_model_load": after_load,
        "timing_scope": "fresh extractor + input + synchronous extract + NumPy output copy/check; prepared Mat conversion, loading, preprocessing and postprocessing excluded",
        "memory_scope": "whole process including interpreter, libraries, inputs and model; not isolated model allocations",
    }
    result["prepared_tensor"] = measure("prepared_tensor", tensor_step, args.warmup, args.runs)

    if args.image:
        import PIL
        from PIL import Image

        def image_step(index):
            start = time.perf_counter_ns()
            with Image.open(args.image) as image:
                rgb = np.asarray(image.convert("RGB"))
            normalized = preprocess_rgb_uint8(rgb)
            mat = ncnn.Mat(np.ascontiguousarray(normalized[0]))
            prepared = time.perf_counter_ns()
            image_logits = infer(mat)
            inferred = time.perf_counter_ns()
            threshold_predictions(
                positive_probability(image_logits, point["temperature"]), point["threshold"]
            )
            finished = time.perf_counter_ns()
            return {
                "decode_preprocess_mat_ms": (prepared - start) / 1e6,
                "inference_api_ms": (inferred - prepared) / 1e6,
                "postprocess_ms": (finished - inferred) / 1e6,
                "end_to_end_ms": (finished - start) / 1e6,
            }

        result["image_source"] = str(args.image)
        result["pillow_version"] = PIL.__version__
        result["image_scope"] = "repeated PNG open/decode/RGB/resize/normalize/Mat/inference/postprocess; OS file cache not flushed; not camera capture or video throughput"
        result["image_pipeline"] = measure("image_pipeline", image_step, args.warmup, args.runs)
    result["after_all_phases"] = snapshot()
    result["validation_scope"] = "six golden inputs and optional single image; not complete dataset accuracy"
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
