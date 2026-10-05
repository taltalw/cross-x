#!/usr/bin/env python3
"""审计阶段1领域选择方案的组合熵；仅使用 Python 标准库。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

DEFAULT_DOMAINS = (
    "chemistry", "computer_science", "financial", "geography",
    "legal", "mathematics", "medical",
)
REPORT_FILES = (
    "summary.json", "summary.csv", "per_source.csv", "combinations.csv",
    "selection_rates.csv", "report.md",
)


def validate_config(domains: list[str], domain_counts: list[int]) -> None:
    """验证声明的领域全集与融合规模。

    Raises:
        ValueError: 全集或融合规模不合法。
    """
    if len(domains) < 2 or len(set(domains)) != len(domains):
        raise ValueError("--domains 至少包含两个不重复的领域")
    if any(not isinstance(d, str) or not d.strip() for d in domains):
        raise ValueError("领域名必须是非空字符串")
    if not domain_counts or len(set(domain_counts)) != len(domain_counts):
        raise ValueError("--domain-counts 必须非空且不重复")
    if any(type(k) is not int or not 2 <= k <= len(domains) for k in domain_counts):
        raise ValueError("domain_count 必须是 2 到领域全集大小之间的整数")


def validate_record(row: dict, domains: list[str]) -> tuple[str, int, tuple, str]:
    """校验阶段1记录，返回源领域、规模、无序组合、源样本身份。

    Args:
        row: 一行阶段1 JSON 对象。
        domains: 固定领域全集。

    Returns:
        用于分组、计数和检测重复的标准化字段。
    """
    if not isinstance(row, dict):
        raise ValueError("每行必须是 JSON 对象")
    if "difficulty" in row or "fused_question" in row:
        raise ValueError("检测到最终题目记录；请使用 1_generate_fusion_plans 阶段1文件")
    source, k, added = (row.get(f) for f in ("source_domain", "domain_count", "fusion_domains"))
    if source not in domains:
        raise ValueError(f"未知 source_domain: {source!r}")
    if type(k) is not int or not 2 <= k <= len(domains):
        raise ValueError(f"非法 domain_count: {k!r}")
    if not isinstance(added, list) or any(not isinstance(d, str) for d in added):
        raise ValueError("fusion_domains 必须是领域名称列表")
    if len(added) != k - 1 or len(set(added)) != len(added):
        raise ValueError("fusion_domains 必须包含 k-1 个互不重复的附加领域")
    if source in added or any(d not in domains for d in added):
        raise ValueError("fusion_domains 不能包含源领域或全集之外的领域")
    sample = row.get("sample")
    if not isinstance(sample, dict) or any(
        not isinstance(sample.get(f), str) for f in ("prompt", "completion")
    ):
        raise ValueError("必须提供 sample.prompt 和 sample.completion 字符串以识别源样本")
    identity = hashlib.sha256(json.dumps(
        [sample["prompt"], sample["completion"]], ensure_ascii=False,
    ).encode("utf-8")).hexdigest()
    return source, k, tuple(sorted(added)), identity


def load_plans(input_path: Path, domains: list[str], domain_counts: list[int]) -> tuple:
    """读取文件或递归读取目录，拒绝重复的源样本与融合规模。

    Returns:
        按 (源领域, k) 分组的 Counter，以及含 SHA256 的输入审计信息。
    """
    validate_config(domains, domain_counts)
    input_path = input_path.resolve()
    if not input_path.exists():
        raise ValueError(f"输入不存在: {input_path}")
    files = sorted(input_path.rglob("*.jsonl")) if input_path.is_dir() else [input_path]
    if not files:
        raise ValueError(f"输入目录中没有 JSONL 文件: {input_path}")
    counts, seen = {}, {}
    metadata = {"input_path": str(input_path), "files": [], "rows_read": 0,
                "rows_included": 0, "rows_excluded_by_k": 0, "blank_lines": 0}
    for path in files:
        content = path.read_bytes()
        file_info = {"path": str(path), "sha256": hashlib.sha256(content).hexdigest(), "rows": 0}
        for line_number, line in enumerate(content.decode("utf-8-sig").splitlines(), 1):
            if not line.strip():
                metadata["blank_lines"] += 1
                continue
            location = f"{path}:{line_number}"
            try:
                source, k, added, identity = validate_record(json.loads(line), domains)
                metadata["rows_read"] += 1
                file_info["rows"] += 1
                if k not in domain_counts:
                    metadata["rows_excluded_by_k"] += 1
                    continue
                key = (source, k, identity)
                if key in seen:
                    raise ValueError(f"重复源样本/融合规模；首次出现于 {seen[key]}。请勿合并重复运行或难度变体")
                seen[key] = location
                counts.setdefault((source, k), Counter())[added] += 1
                metadata["rows_included"] += 1
            except ValueError as exc:
                raise ValueError(f"{location}: {exc}") from exc
        metadata["files"].append(file_info)
    if not metadata["rows_included"]:
        raise ValueError("输入为空或没有符合 --domain-counts 的方案")
    return counts, metadata


def entropy(counts) -> float:
    """由非负计数计算自然对数熵；空计数的原始熵约定为零。"""
    total = sum(counts)
    return -math.fsum((n / total) * math.log(n / total) for n in counts if n) if total else 0.0


def compute_metrics(counts: dict, domains: list[str], domain_counts: list[int]) -> dict:
    """计算逐源领域组合熵、覆盖率、边缘选择率及等权宏平均。

    Args:
        counts: load_plans 返回的组合计数，键为 (source_domain, k)。
        domains: 固定的可选领域全集，同时定义宏平均的源领域全集。
        domain_counts: 要分别报告的融合规模。

    Returns:
        包含 summary_by_k、per_source、combinations、selection_rates 的报告。
        缺少源领域时完整宏平均为 None，局部平均单列。
    """
    validate_config(domains, domain_counts)
    report = {"summary_by_k": [], "per_source": [], "combinations": [], "selection_rates": []}
    for k in domain_counts:
        groups = []
        for source in domains:
            candidates = sorted(d for d in domains if d != source)
            possibilities = list(combinations(candidates, k - 1))
            frequencies = counts.get((source, k), Counter())
            if any(t not in possibilities or type(n) is not int or n < 0 for t, n in frequencies.items()):
                raise ValueError(f"{source}, k={k}: 非法组合或计数")
            n, m = sum(frequencies.values()), len(possibilities)
            observed = sum(v > 0 for v in frequencies.values())
            h = entropy(list(frequencies.values())) if n else None
            added_counts = Counter()
            for targets, frequency in frequencies.items():
                for target in targets:
                    added_counts[target] += frequency
            marginal_h = entropy(list(added_counts.values())) if n else None
            group = {
                "source_domain": source, "domain_count": k, "n_plans": n,
                "possible_combinations": m, "observed_combinations": observed,
                "entropy_nats": h,
                "dde": h / math.log(m) if n and m > 1 else None,
                "coverage": observed / m if n else None,
                "marginal_dde": marginal_h / math.log(len(candidates)) if n and len(candidates) > 1 else None,
                "status": "missing" if not n else ("single_possible_combination" if m == 1 else "ok"),
            }
            groups.append(group)
            for targets in possibilities:
                frequency = frequencies.get(targets, 0)
                report["combinations"].append({
                    "source_domain": source, "domain_count": k,
                    "fusion_domains": list(targets), "count": frequency,
                    "probability": frequency / n if n else None,
                })
            for target in candidates:
                report["selection_rates"].append({
                    "source_domain": source, "domain_count": k, "target_domain": target,
                    "count": added_counts[target],
                    "inclusion_rate": added_counts[target] / n if n else None,
                    "slot_probability": added_counts[target] / (n * (k - 1)) if n else None,
                })
        observed_groups = [g for g in groups if g["n_plans"]]
        defined = [g["dde"] for g in observed_groups if g["dde"] is not None]
        observed_mean = math.fsum(defined) / len(defined) if defined else None
        complete = len(observed_groups) == len(domains)
        summary = {
            "domain_count": k, "n_plans": sum(g["n_plans"] for g in groups),
            "expected_source_domains": len(domains), "observed_source_domains": len(observed_groups),
            "possible_combinations_per_source": math.comb(len(domains) - 1, k - 1),
            "macro_dde": observed_mean if complete else None,
            "observed_source_macro_dde": observed_mean,
            "macro_coverage": math.fsum(g["coverage"] for g in observed_groups) / len(domains) if complete else None,
            "missing_source_domains": [g["source_domain"] for g in groups if not g["n_plans"]],
        }
        report["summary_by_k"].append(summary)
        report["per_source"].extend(groups)
    return report


def format_number(value) -> str:
    """为人读报告格式化数值，保留 N/A 与零的区别。"""
    return "N/A" if value is None else f"{value:.4f}"


def render_markdown(report: dict) -> str:
    """生成中文审计报告。"""
    meta = report["metadata"]
    lines = [
        "# 领域分布熵（DDE）审计结果", "",
        f"输入：{meta['input_path']}", "",
        f"读取 {len(meta['files'])} 个文件、{meta['rows_read']} 条记录；纳入 {meta['rows_included']} 条，按 k 排除 {meta['rows_excluded_by_k']} 条。",
        "", "声明领域全集：" + "、".join(report["domains"]), "",
        "以固定源领域 a 和融合规模 k 分组，T 是除 a 之外的 k−1 个领域的无序组合。",
        "p(T)=n(T)/N；H=−Σ p(T)ln p(T)；DDE=H/ln C(m−1,k−1)。未出现组合贡献为零。", "",
        "## 按融合规模汇总", "",
        "| k | 方案数 | 有数据源领域/声明源领域 | 完整宏平均 DDE | 已观察源领域均值 | 完整宏平均覆盖率 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for s in report["summary_by_k"]:
        lines.append(f"| {s['domain_count']} | {s['n_plans']} | {s['observed_source_domains']}/{s['expected_source_domains']} | {format_number(s['macro_dde'])} | {format_number(s['observed_source_macro_dde'])} | {format_number(s['macro_coverage'])} |")
    lines.extend(["", "## 逐源领域结果", "",
                  "| 源领域 | k | 方案数 | 已观察/理论组合数 | DDE | 覆盖率 | 状态 |",
                  "|---|---:|---:|---:|---:|---:|---|"])
    for g in report["per_source"]:
        lines.append(f"| {g['source_domain']} | {g['domain_count']} | {g['n_plans']} | {g['observed_combinations']}/{g['possible_combinations']} | {format_number(g['dde'])} | {format_number(g['coverage'])} | {g['status']} |")
    lines.extend(["", "## 阅读说明", "",
        "- 完整宏平均对声明全集中的源领域等权平均；任一源领域缺失则为 N/A，另列局部均值。",
        "- 理论组合数只有 1 时，归一化分母为零，DDE 为 N/A；存在数据时原始熵为 0、覆盖率为 1。",
        "- 一个 atomic 样本在每个 k 下通常只有一个方案，此处衡量一组源样本的选域分布，不能推断单个样本的采样熵。",
        "- DDE 衡量组合多样性，不直接衡量知识融合质量。有限样本及不同 k 的组合空间影响比较。",
        "- CSV 空值和 JSON null 表示缺失或无定义，不应作为 0 绘图。",
        "- combinations.csv 包含零频次组合，可画组合频次图；selection_rates.csv 可画源领域×目标领域热图。",
        "- inclusion_rate 的行和为 k−1；slot_probability 的行和为 1。边缘熵仅为辅助指标，不能替代组合熵。",
        "", "程序未调用模型；输入文件 SHA256 见 summary.json。", ""])
    return "\n".join(lines)


def write_reports(report: dict, output_path: Path, overwrite: bool = False) -> None:
    """在独立目录写入六份报告，默认拒绝覆盖已存在的报告。

    Raises:
        ValueError: 输出会写入输入目录、覆盖输入文件或覆盖未经允许的报告。
    """
    output_path = output_path.resolve()
    input_path = Path(report["metadata"]["input_path"])
    if input_path.is_dir() and (output_path == input_path or input_path in output_path.parents):
        raise ValueError("输出目录不能位于输入目录内部，请另选审计结果目录")
    input_files = {Path(f["path"]).resolve() for f in report["metadata"]["files"]}
    for name in REPORT_FILES:
        dest = output_path / name
        if dest.is_symlink() or dest.resolve() in input_files or dest.is_dir():
            raise ValueError(f"输出路径不是安全的独立报告文件: {dest}")
        if dest.exists() and not overwrite:
            raise ValueError(f"报告已存在: {dest}；请换输出目录，或使用 --overwrite 覆盖报告")
    output_path.mkdir(parents=True, exist_ok=True)
    (output_path / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8",
    )
    for filename, key in (("summary.csv", "summary_by_k"), ("per_source.csv", "per_source"),
                          ("combinations.csv", "combinations"), ("selection_rates.csv", "selection_rates")):
        rows = report[key]
        with (output_path / filename).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            for row in rows:
                writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v for k, v in row.items()})
    (output_path / "report.md").write_text(render_markdown(report), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """命令行入口；成功返回 0，输入或写入错误返回 2。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="阶段1 JSONL 文件或目录（递归）")
    parser.add_argument("--output", type=Path, required=True, help="独立报告输出目录")
    parser.add_argument("--domains", nargs="+", default=list(DEFAULT_DOMAINS), help="固定领域全集，默认当前七领域")
    parser.add_argument("--domain-counts", nargs="+", type=int, default=[2, 3, 4], help="融合规模，包含源领域；默认 2 3 4")
    parser.add_argument("--overwrite", action="store_true", help="允许覆盖输出目录内的六份报告")
    args = parser.parse_args(argv)
    try:
        counts, metadata = load_plans(args.input, args.domains, args.domain_counts)
        report = compute_metrics(counts, args.domains, args.domain_counts)
        report.update({"schema_version": 1, "domains": args.domains, "domain_counts": args.domain_counts,
                       "definition": "H(T|source=a,k) / ln(C(m-1,k-1)); equal-source macro average",
                       "metadata": metadata})
        write_reports(report, args.output, args.overwrite)
    except (ValueError, OSError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2
    print(f"已审计 {metadata['rows_included']} 个方案；结果: {args.output.resolve()}")
    for row in report["summary_by_k"]:
        print(f"k={row['domain_count']}: N={row['n_plans']}, macro_DDE={format_number(row['macro_dde'])}, coverage={format_number(row['macro_coverage'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
