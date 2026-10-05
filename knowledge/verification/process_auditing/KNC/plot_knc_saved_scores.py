#!/usr/bin/env python3
"""将离线KNC汇总画成可导出的论文草图；仅绘图需要matplotlib。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def draw_figures(report: dict, output: Path, budget_threshold: float) -> None:
    """输出阈值与分数、分数可用率、候选预算三组PNG/PDF/SVG。

    Args:
        report: knowledge_need_coverage.py生成的summary.json内容。
        output: 图像输出目录。
        budget_threshold: 候选预算曲线使用的已计算阈值。
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter

    settings = report["manifest"]["settings"]
    if budget_threshold not in settings["thresholds"]:
        raise ValueError("预算曲线阈值必须已在summary.json中计算")
    ks = settings["domain_counts"]
    colors = dict(zip(ks, ["#2563eb", "#d97706", "#059669", "#9333ea", "#dc2626", "#475569"]))
    markers = dict(zip(ks, ["o", "s", "^", "D", "v", "P"]))
    partial = any(r["macro_knc_saved"] is None for r in report["summary"])
    metric = "observed_source_knc_saved" if partial else "macro_knc_saved"
    population = "observed sources only" if partial else "equal-source macro average"
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "savefig.dpi": 180, "pdf.fonttype": 42, "svg.fonttype": "none"})
    output.mkdir(parents=True, exist_ok=True)

    def save(fig, name):
        """保存同一图的栅格与矢量版本。"""
        for suffix in ("png", "pdf", "svg"):
            fig.savefig(output / f"{name}.{suffix}", bbox_inches="tight")
        plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), layout="constrained")
    for k in ks:
        rows = sorted((r for r in report["summary"] if r["domain_count"] == k and r["budget"] == "all"),
                      key=lambda r: r["threshold"])
        axes[0].plot([r["threshold"] for r in rows], [r[metric] for r in rows],
                     color=colors[k], marker=markers[k], label=f"k = {k}")
        needs = [r for r in report["requirement_scores"] if r["domain_count"] == k and r["budget"] == "all"]
        scores = sorted(r["best_saved_score"] for r in needs if r["best_saved_score"] is not None)
        if scores:
            axes[1].step([scores[0]] + scores + [max(scores[-1], settings["threshold"])],
                         [0] + [(i + 1) / len(scores) for i in range(len(scores))] + [1],
                         where="post", color=colors[k], label=f"k = {k}, n = {len(scores)}/{len(needs)}")
    for ax in axes:
        ax.axvline(settings["threshold"], color="#64748b", linestyle="--", linewidth=1,
                   label=f"Main threshold = {settings['threshold']:g}")
        ax.yaxis.set_major_formatter(PercentFormatter(1))
        ax.set_ylim(-0.025, 1.05)
        ax.grid(axis="y", alpha=0.2)
        ax.legend(fontsize=8)
    axes[0].set(xlabel="Similarity threshold", ylabel="KNC-Emb-Saved", title=f"Threshold sensitivity\n{population}")
    axes[1].set(xlabel="Best saved embedding score", ylabel="Empirical cumulative fraction",
                title="Observed best-score distribution\npooled needs; missing scores excluded")
    save(fig, "knc_threshold_and_scores")

    fig, ax = plt.subplots(figsize=(7, 4), layout="constrained")
    for x, k in enumerate(ks):
        needs = [r for r in report["requirement_scores"] if r["domain_count"] == k and r["budget"] == "all"]
        observed = sum(r["observed_pairs"] for r in needs)
        total = sum(r["candidate_count"] for r in needs)
        available = sum(r["observed_pairs"] > 0 for r in needs)
        for offset, value, label, color, annotation in (
            (-0.18, available / len(needs) if needs else 0, "Needs with any saved score", "#334155", f"{available}/{len(needs)}"),
            (0.18, observed / total if total else 0, "Pairs with saved scores", "#94a3b8", f"{observed}/{total}"),
        ):
            ax.bar(x + offset, value, width=0.34, color=color, label=label if x == 0 else None)
            ax.text(x + offset, value + 0.02, annotation if (needs and (total or offset < 0)) else "N/A",
                    ha="center", fontsize=9)
    ax.set_xticks(range(len(ks)), [f"k = {k}" for k in ks])
    ax.set(ylim=(0, 1.3), ylabel="Availability (pooled counts)", title="Saved-score availability; all retained candidates")
    ax.set_yticks([0, 0.2, 0.4, 0.6, 0.8, 1])
    ax.yaxis.set_major_formatter(PercentFormatter(1))
    ax.legend(loc="upper right", fontsize=8)
    save(fig, "knc_score_availability")

    numeric = sorted((b for b in settings["budgets"] if b != "all"), key=int)
    labels = numeric + ["all"]
    fig, ax = plt.subplots(figsize=(7, 4), layout="constrained")
    for k in ks:
        rows = {r["budget"]: r for r in report["summary"]
                if r["domain_count"] == k and r["threshold"] == budget_threshold}
        ax.plot(range(len(labels)), [rows[b][metric] for b in labels],
                marker=markers[k], color=colors[k], label=f"k = {k}")
    ax.set_xticks(range(len(labels)), labels)
    ax.set(xlabel="Candidate prefix budget per added domain (categorical)", ylabel="KNC-Emb-Saved",
           ylim=(-0.025, 1.05), title=f"Budget sensitivity at threshold {budget_threshold:g}\n{population}")
    ax.yaxis.set_major_formatter(PercentFormatter(1))
    ax.grid(axis="y", alpha=0.2)
    ax.legend()
    save(fig, "knc_candidate_budget")


def main() -> None:
    """读取现有审计结果，不重新计算或补齐embedding分数。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="审计输出summary.json")
    parser.add_argument("--output", type=Path, help="默认为summary.json旁的figures目录")
    parser.add_argument("--budget-threshold", type=float, default=0.30)
    args = parser.parse_args()
    report = json.loads(args.input.read_text(encoding="utf-8"))
    output = args.output or args.input.parent / "figures"
    draw_figures(report, output, args.budget_threshold)
    print(f"三组图已生成（PNG/PDF/SVG）: {output.resolve()}")


if __name__ == "__main__":
    main()
