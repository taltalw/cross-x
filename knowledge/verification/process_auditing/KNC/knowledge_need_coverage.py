#!/usr/bin/env python3
"""完全离线：从阶段3保存的 embedding hits 计算阈值覆盖及缺失诊断。"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

if __package__:
    from .knc_saved_core import (DEFAULT_DOMAINS, DEFAULT_THRESHOLDS, compute_metrics,
        extract_scores, load_input, select_plans, stable_id)
else:
    from knc_saved_core import (DEFAULT_DOMAINS, DEFAULT_THRESHOLDS, compute_metrics,
        extract_scores, load_input, select_plans, stable_id)

TABLES = ("pair_scores", "requirement_scores", "requirement_coverage", "per_plan", "per_source", "summary")
REPORT_FILES = tuple(name + ".csv" for name in TABLES) + ("summary.json", "run_manifest.json", "report.md")


def number(value: float | None) -> str:
    """将比例显示为百分比，缺失值保持N/A。"""
    return "N/A" if value is None else f"{value:.2%}"


def render_report(report: dict) -> str:
    """输出中文结果，区分保存命中率和完整配对覆盖界限。"""
    meta, settings = report["manifest"]["input"], report["manifest"]["settings"]
    threshold = settings["threshold"]
    main = [r for r in report["summary"] if r["threshold"] == threshold and r["budget"] == "all"]
    scores = [r for r in report["requirement_scores"] if r["budget"] == "all"]
    visible = [r["best_saved_score"] for r in scores if r["best_saved_score"] is not None]
    known_pairs = sum(r["observed_pairs"] for r in scores)
    total_pairs = sum(r["candidate_count"] for r in scores)
    lines = ["# KNC：已保存 Embedding 分数的离线阈值审计", "",
        "本报告没有加载模型、生成向量或调用API。指标表示保存命中的相似度覆盖，不是知识充分支持率。", "",
        f"输入：{meta['input_path']}", "",
        f"读取 {meta['rows_read']} 条记录，选择 {len(report['manifest']['sample'])} 个方案、{len(scores)} 项需求。",
        f"配置：seed={settings['seed']}；主阈值={threshold:g}；全部保留候选。", "",
        f"有保存分数的需求：{len(visible)}/{len(scores)}；有保存分数的配对：{known_pairs}/{total_pairs}。",
        f"可见的需求最佳分数范围：{min(visible):.6f}–{max(visible):.6f}。" if visible else "未观察到需求的 embedding 分数。", "",
        "## 主阈值结果", "",
        "| k | 方案数 | 需求数 | 源领域覆盖 | 保存命中宏平均 | 局部源领域均值 | 完整配对保守上界 | 需求分数可用率（宏平均） |",
        "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in main:
        lines.append(f"| {r['domain_count']} | {r['n_plans']} | {r['n_needs']} | {r['observed_sources']}/{r['expected_sources']} | {number(r['macro_knc_saved'])} | {number(r['observed_source_knc_saved'])} | {number(r['macro_complete_upper'])} | {number(r['macro_need_score_availability'])} |")
    lines.extend(["", "## 阈值敏感性（全部保留候选）", "",
                  "| 阈值 | k | 保存命中宏平均 | 完整配对保守区间 |", "|---:|---:|---:|---|"])
    for r in report["summary"]:
        if r["budget"] == "all":
            lines.append(f"| {r['threshold']:g} | {r['domain_count']} | {number(r['macro_knc_saved'])} | [{number(r['macro_complete_lower'])}, {number(r['macro_complete_upper'])}] |")
    lines.extend(["", "## 主阈值逐源领域结果", "",
                  "| 源领域 | k | 方案数 | 保存命中率 | 需求分数可用率 |", "|---|---:|---:|---:|---:|"])
    for r in report["per_source"]:
        if r["threshold"] == threshold and r["budget"] == "all":
            lines.append(f"| {r['source_domain']} | {r['domain_count']} | {r['n_plans']} | {number(r['knc_saved'])} | {number(r['need_score_availability'])} |")
    lines.extend(["", "## 正确解读", "",
        "- 保存命中率：至少有一个已保存embedding分数≥阈值的需求，按新增领域与源领域等权汇总。",
        "- 没有保存分数的配对在CSV中为空、JSON中为null；没有把相似度填成0。",
        "- 存在阈值命中则完整配对覆盖可确定为1；无命中且仍缺配对分数时为unknown；全部配对已知且低于阈值时为0。",
        "- 保存命中率等于完整配对阈值覆盖的保守下界。上界把未知需求视为覆盖；该范围不是置信区间，也不是语义支持率区间。",
        "- 需求分数可用率衡量每项需求是否至少有一个分数，不代表完整矩阵已保存；应同时看配对分数可用率。",
        "- 完整宏平均要求声明的全部源领域有数据。局部输入只报告局部均值；N/A不是0。",
        "- 0.70未经语义标注校准。零命中只表示保存分数未达阈值，不代表知识支持率为零。",
        "- 默认每源领域只抽一个跨k共享原子样本，共21方案、7个原子样本；用于方法检查，不代表全量总体结论。",
        "- 候选预算使用输入RRF排序的前缀；仅统计其中保存的embedding分数，不按本指标重新排列候选。",
        "- 输入位置、内容哈希、模型配置、样本ID见run_manifest.json；逐需求最佳候选及原文见requirement_scores.csv。", ""])
    return "\n".join(lines)


def write_reports(report: dict, output: Path, overwrite: bool = False) -> None:
    """验证所有目标路径后写九份报告，保护原始输入和已有文件。"""
    output = output.resolve()
    metadata = report["manifest"]["input"]
    input_path = Path(metadata["input_path"])
    if input_path.is_dir() and (output == input_path or input_path in output.parents):
        raise ValueError("输出目录不能位于输入目录内部")
    input_files = {Path(f["path"]).resolve() for f in metadata["files"]}
    for name in REPORT_FILES:
        target = output / name
        if target.is_symlink() or target.is_dir() or target.resolve() in input_files:
            raise ValueError(f"不安全的报告路径: {target}")
        if target.exists() and not overwrite:
            raise ValueError(f"报告已存在: {target}；请换目录或添加 --overwrite")
    output.mkdir(parents=True, exist_ok=True)
    for name in TABLES:
        rows = report[name]
        # 空候选输入仍输出可读取的配对表头。
        fields = list(rows[0]) if rows else ["requirement_id", "candidate_id", "embedding_score", "status"]
        with (output / (name + ".csv")).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for k, v in row.items()})
    for name, data in (("run_manifest.json", report["manifest"]), ("summary.json", report)):
        (output / name).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (output / "report.md").write_text(render_report(report), encoding="utf-8")


def build_report(args) -> dict:
    """完成读取、固定抽样与统计，未通过输入检查前不写结果。"""
    thresholds = sorted(set(args.thresholds + [args.threshold]))
    if any(not math.isfinite(t) or not -1 <= t <= 1 for t in thresholds):
        raise ValueError("阈值必须为[-1,1]内有限数值")
    budgets = list(dict.fromkeys(["all"] + args.budgets))
    if any(b != "all" and (not b.isdigit() or int(b) < 1 or str(int(b)) != b) for b in budgets):
        raise ValueError("预算必须为all或正整数，如1 3 5 10")
    plans, metadata = load_input(args.input, args.domains, args.domain_counts)
    selected = select_plans(plans, args.domain_counts, args.samples_per_source,
                            args.seed, args.source_domains, args.all_plans)
    if not selected:
        raise ValueError("没有选择到可评测方案")
    config_fields = ("embedding_config_hash", "method", "rrf_k", "top_k_per_query_method", "candidate_limit")
    configurations = {stable_id({f: p["retrieval"].get(f) for f in config_fields}) for p in selected}
    if len(configurations) != 1:
        raise ValueError("选中方案的embedding或检索配置不同，请分开运行，不能混合汇总")
    pairs, requirements = extract_scores(selected, budgets)
    report = compute_metrics(requirements, args.domains, args.domain_counts, thresholds, budgets)
    report.update(pair_scores=pairs, requirement_scores=requirements)
    report["manifest"] = {"schema_version": 1, "metric": "KNC-Emb-Saved",
        "definition": "saved embedding score threshold hits; conservative bounds for unrecorded pairs; not semantic support",
        "input": metadata, "offline": True, "model_calls": 0,
        "settings": {"domains": args.domains, "domain_counts": args.domain_counts,
                     "source_domains": args.source_domains, "seed": args.seed,
                     "samples_per_source": args.samples_per_source, "all_plans": args.all_plans,
                     "threshold": args.threshold, "thresholds": thresholds, "budgets": budgets},
        "retrieval_config": {f: selected[0]["retrieval"].get(f) for f in (*config_fields, "embedding_model")},
        "sample": [{f: p[f] for f in ("plan_id", "atomic_id", "source_domain", "domain_count", "input_file", "input_line")}
                   for p in selected]}
    return report


def main(argv: list[str] | None = None) -> int:
    """CLI入口：成功返回0，输入或输出错误返回2。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="阶段3 JSONL文件或目录")
    parser.add_argument("--output", type=Path, required=True, help="独立审计输出目录")
    parser.add_argument("--domains", nargs="+", default=list(DEFAULT_DOMAINS), help="领域全集，默认七领域")
    parser.add_argument("--domain-counts", type=int, nargs="+", default=[2, 3, 4])
    parser.add_argument("--source-domains", nargs="+", help="仅抽样这些源领域；不缩小宏平均全集")
    parser.add_argument("--samples-per-source", type=int, default=1, help="每源领域跨k共享原子样本数，默认1")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--all-plans", action="store_true", help="不抽样，使用所选源领域和k的全部方案")
    parser.add_argument("--threshold", type=float, default=0.70, help="主报告阈值，默认0.70")
    parser.add_argument("--thresholds", type=float, nargs="+", default=DEFAULT_THRESHOLDS, help="敏感性阈值列表，自动包含主阈值")
    parser.add_argument("--budgets", nargs="+", default=["1", "3", "5", "10"], help="每域候选前缀预算，自动包含all")
    parser.add_argument("--overwrite", action="store_true", help="允许覆盖九份审计报告")
    args = parser.parse_args(argv)
    try:
        report = build_report(args)
        write_reports(report, args.output, args.overwrite)
    except (ValueError, OSError, TypeError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2
    print(f"纯离线完成：{len(report['manifest']['sample'])}个方案；模型调用=0；{args.output.resolve()}")
    for row in report["summary"]:
        if row["threshold"] == args.threshold and row["budget"] == "all":
            print(f"k={row['domain_count']}: 保存命中宏平均={number(row['macro_knc_saved'])}, 局部均值={number(row['observed_source_knc_saved'])}, 需求分数可用率={number(row['observed_source_need_score_availability'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
