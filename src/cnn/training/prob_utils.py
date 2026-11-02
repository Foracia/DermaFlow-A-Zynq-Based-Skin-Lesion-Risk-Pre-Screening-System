# -*- coding: utf-8 -*-
r"""
概率与阈值计算的**唯一实现**。

## 为什么单独成文件（审查意见 P1-C）

交付包里曾出现同一个模型的两个阈值：
    metrics_unified.json  : 0.5512092988993387
    operating_point.json  : 0.5512093305587769

根因是**两条概率计算路径**：
    unified_eval.py   用 numpy float64 softmax
    finalize_run.py   用 torch float32 softmax

float32 与 float64 的尾数差异，落在"有一个正类样本的概率恰好在
阈值位置上"时，会导致 recall 差 1 个 TP（80.49% vs 79.88%）。

**修复：两个脚本都 import 本模块，不再各自实现。**

## 约定（必须与 README/MODEL_SPEC 的声明一致）

    logits 先转 float64，再除以 T，再 softmax
    判定为 p_positive >= threshold（含等号）
    阈值直接取验证集正类样本的概率值本身，不做插值
"""

import numpy as np

# 这些常量必须与交付文档中的"锁定口径"一致
PROB_DTYPE = "float64（softmax 前 logits 转 double）"
DECISION_RULE = "p_positive >= threshold"
DEFAULT_THRESHOLD = 0.5


def softmax_prob(logits, T):
    """返回正类（malignant）概率，float64。

    logits : (N, 2) float32/float64
    T      : 温度（float）
    """
    l = np.asarray(logits, dtype=np.float64) / float(T)
    e = np.exp(l - l.max(axis=1, keepdims=True))
    p = e / e.sum(axis=1, keepdims=True)
    return p[:, 1]


def threshold_for_recall(prob, labels, target_recall):
    """在给定集合上选阈值，使 recall 恰好 >= target_recall。

    **直接取正类样本的概率值本身**（不插值），配合 `>=` 判定，
    结果完全确定、可复现。

    返回 (threshold, need, n_pos)：
        need  = 需要被判为正类的正类样本个数
        n_pos = 该集合的正类样本总数

    注意：调用方只应传入**验证集**的 prob/labels。
    在测试集上调用即为调参，会使评测失去独立性。
    """
    prob = np.asarray(prob, dtype=np.float64)
    labels = np.asarray(labels)
    pos = np.sort(prob[labels == 1])[::-1]
    n_pos = len(pos)
    if n_pos == 0:
        return DEFAULT_THRESHOLD, 0, 0
    need = int(np.ceil(target_recall * n_pos))
    need = max(1, min(need, n_pos))
    th = float(pos[need - 1])
    # 浮点边界保护：若因精度仍未达标，再降一档
    ok = int((prob[labels == 1] >= th).sum())
    while ok < need and need < n_pos:
        need += 1
        th = float(pos[need - 1])
        ok = int((prob[labels == 1] >= th).sum())
    return th, need, n_pos


def confusion(prob, labels, th):
    """按锁定口径计算混淆矩阵与指标。"""
    pred = (np.asarray(prob, dtype=np.float64) >= float(th)).astype(int)
    labels = np.asarray(labels)
    tp = int(((pred == 1) & (labels == 1)).sum())
    fn = int(((pred == 0) & (labels == 1)).sum())
    tn = int(((pred == 0) & (labels == 0)).sum())
    fp = int(((pred == 1) & (labels == 0)).sum())
    sens = tp / max(tp + fn, 1)
    spec = tn / max(tn + fp, 1)
    return {
        "threshold": float(th), "TP": tp, "FN": fn, "TN": tn, "FP": fp,
        "recall_positive": sens, "specificity": spec,
        "balanced_accuracy": (sens + spec) / 2,
        "precision": tp / max(tp + fp, 1),
        "npv": tn / max(tn + fn, 1),
    }
