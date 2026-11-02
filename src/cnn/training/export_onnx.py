# -*- coding: utf-8 -*-
"""
将 PyTorch 检查点导出为 ONNX，并生成 PTQ 校准名单及数值核对结果。

用法：
    python src/cnn/training/export_onnx.py --checkpoint data/models/checkpoint.pt \
        --output-dir build/output/model_export --split data/models/split.json \
        --dataset /path/to/dataset.csv --img-root /path/to/images

默认读取随包 checkpoint.pt，输出静态 batch=1；结果写入新目录，
保留原模型文件。导出后使用 ONNX Runtime 核对输出数值。
"""

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import torch

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from model_derm import build_model, INPUT_SIZE

def _build_model_from_ckpt(ckpt):
    """从 checkpoint 构建模型 —— **不依赖 eval_matrix**。

    ## 为什么内联

    model_package 审查指出：`source/export_onnx.py` 里
    `from eval_matrix import build_any_model` 在交付包内会
    ModuleNotFoundError，因为 `eval_matrix.py` 没有随包。

    这里给出等价的最小实现：按 `ckpt['arch']['name']` 分派到
    随包的模型定义（`model_hybrid` / `model_derm`）。
    """
    arch = ckpt["arch"]
    name = arch.get("name", "DermCNN")
    if name == "HybridDermCNN":
        from model_hybrid import build_hybrid
        # ⚠ 注意 build_hybrid 的真实签名：
        #   (backbone, n_blocks, pretrained, width, head_ch, freeze_backbone)
        #   它**没有** n_classes 参数（二分类是固定的）。
        #   pretrained=False：导出时不需要下载权重，state_dict 会覆盖。
        return build_hybrid(backbone=arch.get("backbone", "resnet18"),
                            n_blocks=arch.get("n_blocks", 0),
                            pretrained=False,
                            width=arch.get("width", 1.0),
                            head_ch=tuple(arch.get("head_ch", (32, 64, 128))),
                            freeze_backbone=True)
    # 普通 DermCNN
    cps = arch.get("convs_per_stage")
    if cps is None:
        # 从 state_dict 的键名推断
        sd = ckpt["model_state"]
        keys = [k for k in sd
                if k.startswith("stage1.body.")
                and k.endswith(".weight") and sd[k].dim() == 4]
        cps = len(keys) or 1
    return build_model(width=arch.get("width", 1.0),
                       n_classes=arch.get("n_classes", 2),
                       convs_per_stage=cps,
                       gap_mode=arch.get("gap_mode", "avgpool"))


def _resolve_data_path(name, extra_dirs=()):
    """在多个候选位置找数据文件（包根 / 包根 data / 脚本目录）。

    审查意见：默认 split 解析到 `source/data/...`，而实际在包根 `data/`。
    """
    cands = []
    for d in (HERE.parents[2] / "data" / "models", HERE, HERE / "data", HERE.parent, HERE.parent / "data",
              *[Path(x) for x in extra_dirs]):
        cands.append(Path(d) / name)
    for c in cands:
        if c.exists():
            return c
    return None


IMG_ROOT_DEFAULT = str(HERE.parents[2] / "data" / "dataset" / "images")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", help="可选训练目录；读取其中的 checkpoint.pt 或 fp32_best.pt")
    ap.add_argument("--checkpoint", type=Path, help="检查点路径，默认使用随包 data/models/checkpoint.pt")
    ap.add_argument("--output-dir", type=Path, help="新的导出目录，默认 build/output/model_export")
    ap.add_argument("--opset", type=int, default=17,
                    help="默认 17（已验证本模型可产出）；"
                         "11/13 需要旧导出器，18 只能用 dynamo 新导出器")
    ap.add_argument("--dynamic-batch", action="store_true",
                    help="默认静态 batch=1；加这个开关才用动态轴")
    ap.add_argument("--n-calib", type=int, default=300,
                    help="校准集图片数（建议 200-500）")
    ap.add_argument("--img-root", default=IMG_ROOT_DEFAULT)
    ap.add_argument("--split", default=None,
                    help="划分文件路径。**必须显式指定**，"
                         "不再从 checkpoint 回退（曾导致校准集取自旧划分）")
    ap.add_argument("--dataset", default=None,
                    help="含 class_short 的索引 CSV（默认按候选路径找）")
    ap.add_argument("--calib-seed", type=int, default=42,
                    help="校准集抽样随机种子（写入契约，保证可复现）")
    ap.add_argument("--gap-mode", default="avgpool",
                    choices=["avgpool", "adaptive"],
                    help="avgpool=AvgPool2d(16,16)，可导出 opset17；"
                         "adaptive=原实现，会强制变成 opset18")
    args = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    # Input selection is separate from the new export directory.
    release_root = HERE.parents[2]
    if args.checkpoint is not None:
        ckpt_path = args.checkpoint.resolve()
    elif args.run:
        input_dir = Path(args.run).resolve()
        ckpt_path = next((input_dir / name for name in ("checkpoint.pt", "fp32_best.pt")
                          if (input_dir / name).is_file()), input_dir / "checkpoint.pt")
    else:
        ckpt_path = release_root / "data/models/checkpoint.pt"
    if not ckpt_path.exists():
        raise SystemExit(f"找不到检查点：{ckpt_path}；可使用 --checkpoint 显式指定")
    run_dir = (args.output_dir or release_root / "build/output/model_export").resolve()
    if run_dir.exists():
        raise SystemExit(f"导出目录已存在：{run_dir}；请使用新的 --output-dir")
    run_dir.mkdir(parents=True)
    print(f"  检查点: {ckpt_path}")
    print(f"  导出目录: {run_dir}")

    ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    arch = ckpt["arch"]
    pre = ckpt["preprocess"]
    state = ckpt["model_state"]

    # 从 state_dict 反推每个 stage 有几层卷积 —— 老 checkpoint 里没有记这个字段，
    # 如果按默认值 1 建模型会加载失败，所以这里做一次自愈。
    def infer_convs_per_stage(sd):
        keys = [k for k in sd if k.startswith("stage1.body.") and k.endswith(".weight")
                and sd[k].dim() == 4]
        nums = sorted(int(k.split(".")[2]) for k in keys)
        return len(nums) if nums else 1

    is_hybrid = arch.get("name") == "HybridDermCNN"
    cps = 0 if is_hybrid else (arch.get("convs_per_stage")
                               or infer_convs_per_stage(state))
    if not is_hybrid and "convs_per_stage" not in arch:
        print(f"  [自愈] checkpoint 未记录 convs_per_stage，"
              f"从 state_dict 反推 = {cps}")

    print("=" * 72)
    print("ONNX 导出")
    print("=" * 72)
    print(f"  权重      : {ckpt_path}")
    print(f"  结构      : {arch}")
    if is_hybrid:
        print(f"              -> 混合架构（骨干 {arch['backbone']}"
              f" n_blocks={arch['n_blocks']}，头部通道 {arch['head_ch']}）")
    else:
        print(f"              -> 实际 convs_per_stage={cps}  gap={args.gap_mode}")
    print(f"  温度 T    : {ckpt['temperature']:.4f}")
    print(f"  预处理    : mean={pre['mean']}  std={pre['std']}")
    print(f"  算子白名单: 见 model_derm.OPERATOR_WHITELIST")
    if args.gap_mode == "adaptive":
        print("  ⚠ gap_mode=adaptive 会导出 ReduceMean，实际 opset 将被强制为 18")

    # 统一走 build_any_model（它会按 arch 分派普通/混合模型），
    # 避免在两处重复维护建模逻辑。
    model = _build_model_from_ckpt(ckpt)
    missing, unexpected = model.load_state_dict(state, strict=False)
    if unexpected:
        raise SystemExit(f"权重不匹配，多余键 {len(unexpected)} 个：{unexpected[:3]}")
    if missing:
        raise SystemExit(f"权重不匹配，缺失键 {len(missing)} 个：{missing[:3]}")
    model.eval()

    dummy = torch.zeros(1, 3, INPUT_SIZE, INPUT_SIZE)
    onnx_path = run_dir / "model.onnx"
    dynamic_axes = None
    if args.dynamic_batch:
        dynamic_axes = {"input": {0: "batch"}, "logits": {0: "batch"}}

    def _real_opset(path):
        """读回导出文件里真实的 opset 版本 —— 不能相信我们请求的值。
        PyTorch 2.11 的 dynamo 导出器请求低版本时会静默产出 opset 18。"""
        try:
            import onnx
            m = onnx.load(str(path))
            return {imp.domain or "ai.onnx": imp.version for imp in m.opset_import}
        except Exception as e:
            return {"读取失败": str(e)}

    def _do_export(use_dynamo):
        """PyTorch 2.9+ 默认走 dynamo 新导出器（需要 onnxscript），
        但它只能产出 opset 18；旧导出器（TorchScript 路径）能产出低版本。
        两边都试，用「实际产出的 opset」跟请求值匹配的那个。"""
        kwargs = dict(input_names=["input"], output_names=["logits"],
                      opset_version=args.opset,
                      do_constant_folding=True,
                      dynamic_axes=dynamic_axes)
        if use_dynamo is not None:
            kwargs["dynamo"] = use_dynamo
        torch.onnx.export(model, dummy, str(path), **kwargs)
        return _real_opset(path)

    results = []
    for use_dynamo in (False, True):        # 先旧后新：旧的对低 opset 更靠谱
        path = run_dir / f"model_onnx{use_dynamo:d}.onnx"
        try:
            real = _do_export(use_dynamo)
            results.append((use_dynamo, path, real, None))
        except Exception as e:
            results.append((use_dynamo, None, None, f"{type(e).__name__}: {e}"))

    if not any(r[1] for r in results):
        print("\n[错误] 两种导出方式都失败：")
        for d, _, _, msg in results:
            print(f"  dynamo={bool(d)}: {str(msg)[:200]}")
        print("\n缺依赖的话装一下：pip install onnx onnxscript onnxruntime")
        raise SystemExit(1)

    # 选「实际 opset 最接近请求值」的那个；同分时优先旧导出器
    def score(r):
        if r[1] is None:
            return (9, 9)
        v = r[2].get("ai.onnx", 999)
        return (0 if v == args.opset else 1, v)

    results.sort(key=score)
    used_dynamo, onnx_path, real_ops, err = results[0]
    onnx_path.replace(run_dir / "model.onnx")
    onnx_path = run_dir / "model.onnx"

    print(f"\n[out] ONNX -> {onnx_path}  "
          f"({onnx_path.stat().st_size / 1024:.1f} KB)")
    print(f"      导出器   : {'dynamo 新路径' if used_dynamo else 'TorchScript 旧路径'}")
    print(f"      请求 opset: {args.opset}   实际 opset: {real_ops}")
    if real_ops.get("ai.onnx") != args.opset:
        print(f"      ⚠ 实际 opset 与请求不一致！原因见导出器版本限制。")
        print(f"        若下游必须用 opset {args.opset}，"
              f"请确认 gap_mode=avgpool（避免 ReduceMean）后重试。")
    for d, p, v, msg in results[1:]:
        print(f"      （备选：dynamo={bool(d)} -> "
              f"{v if v else str(msg)[:60]}）")

    # ---------------- 数值回验（这一步不能省）----------------
    print("\n" + "-" * 72)
    print("ONNX Runtime 数值回验")
    print("-" * 72)
    try:
        import onnxruntime as ort
    except ImportError:
        print("[skip] 没装 onnxruntime，无法回验。")
        print("       装一下：pip install onnxruntime  （然后重跑本脚本）")
        ort = None

    if ort is not None:
        sess = ort.InferenceSession(str(onnx_path),
                                    providers=["CPUExecutionProvider"])
        # 关键：按模型**声明**的输入形状喂数据。
        # 静态 batch=1 时喂 8 张会被 ONNX Runtime 拒绝：
        #   "Got invalid dimensions for input: input, index: 0 Got: 8 Expected: 1"
        inp_meta = sess.get_inputs()[0]
        declared = inp_meta.shape
        batch = declared[0] if isinstance(declared[0], int) else 8
        shape = [batch if not isinstance(d, int) else d for d in declared]
        print(f"  模型声明的输入: {inp_meta.name} shape={declared} "
              f"dtype={inp_meta.type}")
        print(f"  回验用的形状  : {shape}")

        rng = np.random.default_rng(0)
        x = rng.standard_normal(shape).astype(np.float32)
        with torch.no_grad():
            torch_out = model(torch.from_numpy(x)).numpy()
        onnx_out = sess.run(["logits"], {inp_meta.name: x})[0]
        diff = np.abs(torch_out - onnx_out).max()
        print(f"  最大绝对误差: {diff:.3e}")
        if diff < 1e-4:
            print("  ✓ 通过（< 1e-4），转换没有引入可测误差")
        else:
            print("  ✗ 不通过！转换有问题，后面量化的结论都会失真。")
            print("    排查：opset 版本 / 是否含不支持算子 / AMP 残留")
        np.savez(run_dir / "onnx_check.npz",
                 torch_out=torch_out, onnx_out=onnx_out)

    # ---------------- 校准集文件列表 ----------------
    print("\n" + "-" * 72)
    print("PTQ 校准集（**只能来自训练集**，不得触碰 val/test）")
    print("-" * 72)

    # ⚠ 修复过一次严重错误：此前用 ckpt.get("split_file") 回退到默认
    #   data/split.json（v1 旧划分），导致校准名单从**旧数据**抽取，
    #   且混入了 66 张 val、55 张 test 图像。
    #   现在：显式解析 split 文件，且用**图像级**三重断言把关。
    # ⚠ 审查意见：默认路径必须能在**包根 data/** 和 **脚本目录 data/** 都找到。
    #   此前只找 HERE/data，而 source/ 下的脚本会误解析到 source/data/split.json。
    if args.split:
        split_file = Path(args.split)
        if not split_file.is_absolute():
            split_file = Path.cwd() / split_file
    else:
        split_file = _resolve_data_path("split.json")
        if split_file is None:
            raise SystemExit(
                "找不到 data/split.json。\n"
                "   请在包根目录运行，或用 --split 显式指定路径。\n"
                "   （脚本候选目录：脚本所在目录、其 data/、包根、包根 data/）")
    if not split_file.exists():
        raise SystemExit(f"划分文件不存在: {split_file}")
    split = json.loads(split_file.read_text(encoding="utf-8"))
    print(f"  划分文件: {split_file}")
    if "meta" in split:
        print(f"  meta.group_by = {split['meta'].get('group_by')!r}  "
              f"样本数 = {split['meta'].get('n_samples')}")

    train = split["train"]
    train_paths = {r[0] for r in train}
    val_paths = {r[0] for r in split["val"]}
    test_paths = {r[0] for r in split["test"]}
    print(f"  训练集 {len(train)} 张 / 验证集 {len(val_paths)} / "
          f"测试集 {len(test_paths)}")

    # 按类别分层抽样（用类别标签，保证覆盖各病种）
    # ⚠ 审查意见：缺失时**不能静默回退**成二分类 label0/label1，
    #   否则无法按六种病变分层抽校准图，而且不会报错。
    import pandas as pd
    if args.dataset:
        ds_csv = Path(args.dataset)
        if not ds_csv.is_absolute():
            ds_csv = Path.cwd() / ds_csv
    else:
        ds_csv = _resolve_data_path("dataset.csv")
    if ds_csv is None or not ds_csv.exists():
        raise SystemExit(
            "找不到含 class_short 的索引 CSV。\n"
            "   校准集需按六种病变分层抽取，缺少类别映射会静默退化成"
            "二分类，因此这里直接报错。\n"
            "   请用 --dataset 指定，或在包根目录运行。")
    d = pd.read_csv(ds_csv)
    if "class_short" not in d.columns:
        raise SystemExit(f"{ds_csv} 缺少 class_short 列，无法按病种分层。")
    cls_map = dict(zip(d["image_path"], d["class_short"]))
    print(f"  类别映射: {ds_csv.name}"
          f"（{len(cls_map)} 条，{d['class_short'].nunique()} 个病种）")

    def key_of(row):
        """分组键 —— 用划分文件里的**患者 ID**（与分组的语义一致）。

        ⚠ split 的行结构是 [path, label, patient_id, lesion_key]，
          所以 row[2] 是患者 ID、row[3] 是病灶键。
        """
        return row[2] if len(row) > 2 else row[0]

    # ⚠ 抽样方法修正（v11 审查的连带发现）：
    #   此前是"先按病种抽 n_calib 张，再按患者去重"。
    #   问题：**结果张数取决于随机抽中多少跨病种患者**（本例训练集有 131 人
    #   跨病种），所以实际抽出 271 张而非 344 —— 数量不可预期、不可解释。
    #   现在改为：**先按患者聚合，每患者只保留一条，再按病种分层抽样**。
    #   这样每张校准图对应唯一患者，张数可控，且类别覆盖更好。
    by_pat = {}
    for row in train:
        k = key_of(row)
        # 同一患者只保留一条（优先保留"阳性"那条，保证阳性类覆盖）
        if k not in by_pat or (row[1] == 1 and by_pat[k][1] != 1):
            by_pat[k] = row
    uniq = list(by_pat.values())
    print(f"  训练集 {len(train)} 张 -> 按患者去重后 {len(uniq)} 张"
          f"（{len(by_pat)} 个患者）")

    by_cls = defaultdict(list)
    for row in uniq:
        by_cls[cls_map.get(row[0], f"label{row[1]}")].append(row)

    rng = random.Random(args.calib_seed)
    picked = []
    for c, items in sorted(by_cls.items()):
        want = max(1, round(args.n_calib * len(items) / len(uniq)))
        picked += rng.sample(items, min(want, len(items)))
    rng.shuffle(picked)

    # 此时已保证同一患者至多一条，无需再去重（保留一次断言）
    seen_groups, final = set(), []
    for row in picked:
        k = key_of(row)
        if k in seen_groups:
            continue
        seen_groups.add(k)
        final.append(row)
    final_paths = {r[0] for r in final}

    # ---------- 三重断言（任一失败即中止）----------
    ov_val = final_paths & val_paths
    ov_test = final_paths & test_paths
    not_in_train = final_paths - train_paths
    print(f"\n  抽取 {len(final)} 张，覆盖 {len(seen_groups)} 个分组")
    print(f"    【断言1】校准图 ⊆ 训练集 : "
          f"{'✅' if not not_in_train else f'❌ {len(not_in_train)} 张不在训练集'}")
    print(f"    【断言2】与验证集交集   : {len(ov_val)} "
          f"{'✅' if not ov_val else '❌'}")
    print(f"    【断言3】与测试集交集   : {len(ov_test)} "
          f"{'✅' if not ov_test else '❌'}")
    if not_in_train or ov_val or ov_test:
        raise SystemExit("校准集污染！已中止，不写出任何文件")

    # 类别组成
    cc = Counter(cls_map.get(r[0], f"label{r[1]}") for r in final)
    tc = Counter(cls_map.get(r[0], f"label{r[1]}") for r in train)
    print(f"\n  类别组成（校准 / 训练）：")
    for c in sorted(set(cc) | set(tc)):
        print(f"    {c:<6} {cc.get(c,0):>4} / {tc.get(c,0):>5}")

    n0 = sum(1 for r in final if int(r[1]) == 0)
    n1 = sum(1 for r in final if int(r[1]) == 1)
    print(f"  二分类比例 {n0}:{n1}   "
          f"（训练集 {sum(1 for r in train if int(r[1])==0)}:"
          f"{sum(1 for r in train if int(r[1])==1)}）")

    calib_txt = run_dir / "calibration_list.txt"
    with calib_txt.open("w", encoding="utf-8") as f:
        for r in final:
            c = cls_map.get(r[0], "")
            f.write(f"{r[0]}\t{int(r[1])}\t{c}\n")
    print(f"\n[out] 校准集列表 -> {calib_txt}")

    # ---------------- 接口契约（结构化，字段可直接被程序读取）----------------
    # ⚠ 修复审查意见「机器接口仍引用不存在的旧文件」：
    #   1. calibration.split_file 曾写 "data\split_v4.json"，实际交付包内是
    #      "data/split.json"（反斜杠 + 旧文件名）。现在统一写**正斜杠的相对路径**，
    #      并立即断言该文件确实存在。
    #   2. 温度曾以字符串 "T=1.036216" 输出（截断到 6 位），
    #      现在改为结构化数值字段，并补充概率 dtype / 判定符号 /
    #      默认阈值 / 冻结阈值 / 阈值选定来源。
    #   3. 校准图根目录是交付方本机路径，改为显式的数据获取说明 +
    #      可用 --img-root 覆盖，不再作为隐含依赖。

    def rel(p):
        """相对**交付包根目录**的正斜杠路径。

        ⚠ v11 审查发现：此前直接返回 str(p)，当在包内运行导出
        （`--run .`）时会写入**绝对路径**，如
        `E:/26嵌赛/model/deliver/data/split.json` —— 契约不可移植。

        现在按三级回退：
          1. 能相对 run_dir（包根）就相对它
          2. 否则能相对 HERE 就相对 HERE
          3. 再否则：查找与 run_dir 下同名的文件，用它的相对路径
        """
        p = Path(p).resolve()
        for base in (run_dir.resolve(), HERE.resolve()):
            try:
                return str(p.relative_to(base)).replace("\\", "/")
            except ValueError:
                continue
        # 回退：在 run_dir 下按文件名找同名文件
        for cand in run_dir.rglob(p.name):
            try:
                return str(cand.resolve().relative_to(
                    run_dir.resolve())).replace("\\", "/")
            except ValueError:
                continue
        return p.name   # 最后手段：只留文件名（至少是可移植的）

    split_rel = rel(split_file)
    # 交付包里划分文件被重命名为 data/split.json，两个候选都接受
    # ⚠ 基目录必须是 **run_dir（包根）**，不是 HERE（脚本所在目录）
    split_candidates = [run_dir / split_rel, run_dir / "data" / "split.json",
                        HERE / "data" / "split.json"]
    split_ok = any(c.exists() for c in split_candidates)
    print(f"\n  契约引用自检：split_file = {split_rel!r}  "
          f"{'✅ 存在' if split_ok else '❌ 不存在'}")

    T_full = float(ckpt["temperature"])
    contract = {
        "contract_version": "2.0",
        "model_file": str(onnx_path.name),
        "input_name": "input",
        "input_shape": ([None, 3, INPUT_SIZE, INPUT_SIZE] if args.dynamic_batch
                        else [1, 3, INPUT_SIZE, INPUT_SIZE]),
        "input_dtype": "float32",
        "input_layout": "NCHW, RGB",
        "input_normalization": {
            "formula": "(pixel/255 - mean) / std",
            "mean": pre["mean"], "std": pre["std"],
            "input_range_global": [
                round(min(-m / s for m, s in zip(pre["mean"], pre["std"])), 4),
                round(max((1 - m) / s for m, s in zip(pre["mean"], pre["std"])), 4),
            ],
        },
        "output_name": "logits",
        "output_shape": [1, 2],
        "output_order": ["negative(暂不需就医)", "positive(建议就医)"],
        "output_order_text": "[negative(暂不需就医), positive(建议就医)]",
        # ⚠ 审查意见 4.3：必须结构化列出病种归属，
        #   不能只给一句文字描述 —— 下游程序要能直接读。
        "class_definition": {
            "positive": {
                "index": 1,
                "label": "建议就医",
                "diseases": ["BCC", "SCC", "MEL", "ACK"],
                "note": "ACK 为癌前病变；BCC/SCC/MEL 为恶性",
            },
            "negative": {
                "index": 0,
                "label": "暂不需就医",
                "diseases": ["NEV", "SEK"],
                "note": "良性病变",
            },
            "differs_from_dataset_original": True,
            "dataset_original_positive": ["BCC", "SCC", "MEL"],
            "rationale": (
                "设备输出标签为『建议就医』而非『恶性』，"
                "故判据为『是否需要就医』。ACK 是癌前病变、需就医。"),
        },

        # ---- 概率与判定（结构化）----
        "temperature": T_full,
        "probability_formula": "softmax(logits / T)",
        "probability_dtype": "float64",
        "comparison": ">=",
        "positive_class_index": 1,
        "default_threshold": 0.5,
        "frozen_threshold": None,      # 由 finalize_run.py 回填
        "threshold_selected_on": "val",
        "decision_rule": "p_positive >= threshold",

        # ---- 校准集 ----
        "calibration": {
            "list_file": "calibration_list.txt",
            "n_images": len(final),
            "columns": ["image_path", "label", "class_short"],
            "image_path_is_relative_to": "img_root",
            "img_root": {
                "default_local": args.img_root,
                "required_layout":
                    "img_root/<class_folder>/<image_path>，"
                    "与 PAD-UFES-20 原始目录结构一致",
                "override": "用 --img-root 覆盖；交付方本机路径不是契约的一部分",
                "data_source":
                    "PAD-UFES-20（CC BY 4.0）"
                    "https://data.mendeley.com/datasets/zr7vgbcyr2/1",
            },
            # 相对交付包内实际文件名（正斜杠）
            "split_file": ("data/split.json" if (HERE / "data" / "split.json").exists()
                           else split_rel),
            "split_meta_group_by": split.get("meta", {}).get("group_by"),
            "calib_seed": args.calib_seed,
            "verified_no_val_test_overlap": True,
            "verified_subset_of_train": True,
            "class_counts": {k: v for k, v in sorted(cc.items())},
            "must_use_same_preprocess": True,
            "note": "含三重断言：校准图 ⊆ 训练集、"
                    "与验证/测试集图像级交集为 0",
        },
        "opset": args.opset,
        "notes": [
            "预处理已包含在输入侧；若 PL 侧希望在硬件内做归一化，需要另行折算。",
            "温度 T 是一次常数除法，可折进量化 scale，硬件成本为零。",
            "若量化后 logits 尺度变化较大，温度需要重新拟合（用 logits.npz 回验）。",
            "本契约中的路径均为**交付包内相对路径**（正斜杠）。",
            "量化方案（per-tensor / per-channel、累加器位宽）"
            "仅为**候选，待 PTQ 端到端结果确认**。",
        ],
    }

    # 契约自检：所有引用的文件都必须存在
    missing = []
    for key, val in (("model_file", contract["model_file"]),
                     ("calibration.list_file",
                      contract["calibration"]["list_file"]),
                     ("calibration.split_file",
                      contract["calibration"]["split_file"])):
        cand = [run_dir / val, HERE / val, run_dir / "data" / Path(val).name]
        if not any(c.exists() for c in cand):
            missing.append((key, val))
    if missing:
        raise SystemExit(f"❌ 契约引用了不存在的文件：{missing}")
    print(f"  契约引用自检：全部存在 ✅")
    # ⚠ 审查意见：frozen_threshold 此前写 None，等未随包的 finalize_run.py 回填。
    #   这里改为：若包内已有契约（含 frozen_threshold），则继承它；
    #   否则在字段里明确标注"待回填"，不静默留 None。
    prev_contract = run_dir / "handoff_contract.json"
    if contract.get("frozen_threshold") is None and prev_contract.exists():
        try:
            prev = json.loads(prev_contract.read_text(encoding="utf-8"))
            if prev.get("frozen_threshold") is not None:
                contract["frozen_threshold"] = prev["frozen_threshold"]
                print(f"  已从既有契约继承 frozen_threshold = "
                      f"{prev['frozen_threshold']!r}")
        except Exception as e:
            print(f"  ⚠ 读取既有契约失败: {e}")
    if contract.get("frozen_threshold") is None:
        contract["frozen_threshold_status"] = (
            "待回填：本次导出未指定工作点。"
            "请运行工作点选择流程后写入此字段。")

    contract_path = run_dir / "handoff_contract.json"
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=1),
                             encoding="utf-8")
    print(f"[out] 接口契约 -> {contract_path}")

    print("\n" + "=" * 72)
    print("交接清单（这些一起给蒲）")
    print("=" * 72)
    for f in ("model.onnx", "calibration_list.txt", "handoff_contract.json",
              "metrics.json", "logits.npz", "operating_point.json"):
        p = run_dir / f
        print(f"  {'✅' if p.exists() else '❌'} {p}")
    # 数据集底座：从实际使用的 split 文件反推同版本的数据文件
    # （旧版按 run 名猜版本，v4 划分会被误判为 v3 —— 已修正）
    suffix = split_file.stem.replace("split", "")     # split_v4 -> _v4
    for f in (split_file,
              HERE / "data" / f"dataset{suffix}.csv",
              HERE / "data" / f"preprocess{suffix}.json",
              run_dir / "temperature.json"):
        print(f"  {'✅' if f.exists() else '❌'} {f}")
    print("=" * 72)


if __name__ == "__main__":
    main()
