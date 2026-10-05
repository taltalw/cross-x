"""LLM5 固定复核路由与分母明确的描述统计；仅使用本地最终记录。"""

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

DIMENSIONS = (
    "cross_domain_necessity", "fusion_dependency", "correctness_evaluability",
    "knowledge_grounding", "naturalness_clarity",
)
INITIAL_STAGES = ("blind_structure", "evidence_scoring")
CRITICAL_FLAGS = frozenset(("key_answer_error", "single_domain_shortcut",
                            "subset_shortcut", "redundant_domain", "source_contradiction"))
FLAG_DIMENSIONS = {
    "key_answer_error": "correctness_evaluability",
    "single_domain_shortcut": "cross_domain_necessity",
    "subset_shortcut": "cross_domain_necessity",
    "redundant_domain": "cross_domain_necessity",
    "source_contradiction": "knowledge_grounding",
    "invalid_dependency": "fusion_dependency",
}
FINAL_STATUSES = ("execution_incomplete", "pending_review", "pending_human",
                  "llm_consensus_pass", "llm_consensus_fail",
                  "llm_resolved_pass", "llm_resolved_fail")


def _rate(count, denominator):
    return count / denominator if denominator else None


def _metric(count, denominator):
    return {"count": count, "denominator": denominator, "rate": _rate(count, denominator)}


def _index(samples, records):
    sample_index = {}
    for sample in samples:
        sid = sample["sample_id"]
        if not isinstance(sid, str) or not sid or sid in sample_index:
            raise ValueError(f"重复或非法 sample_id: {sid!r}")
        sample_index[sid] = sample
    record_index = {}
    for record in records:
        sid, judge, stage = (record.get(key) for key in ("sample_id", "judge_id", "stage"))
        if sid not in sample_index or judge not in ("J1", "J2", "J3"):
            raise ValueError(f"未知记录: {(sid, judge, stage)!r}")
        if stage not in INITIAL_STAGES + ("adjudication",) or (stage == "adjudication" and judge != "J3"):
            raise ValueError(f"非法阶段: {(sid, judge, stage)!r}")
        key = (sid, judge, stage)
        if key in record_index:
            raise ValueError(f"重复最终记录（重试不应传入）: {key!r}")
        if record.get("status") not in ("ok", "error"):
            raise ValueError(f"非法执行状态: {key!r}")
        if record["status"] == "ok":
            output = record.get("output")
            if not isinstance(output, dict):
                raise ValueError(f"成功记录缺少 JSON 对象: {key!r}")
            if output.get("sample_id", sid) != sid or output.get("stage", stage) != stage:
                raise ValueError(f"记录与输出身份不一致: {key!r}")
            if stage == "evidence_scoring":
                _scores(output)
        record_index[key] = record
    return sample_index, record_index


def _scores(output):
    dimensions = output.get("dimensions", {})
    if set(dimensions) != set(DIMENSIONS):
        raise ValueError("阶段2必须包含且仅包含固定五维")
    result = {}
    for dimension in DIMENSIONS:
        item = dimensions[dimension]
        value, status = item.get("score"), item.get("status")
        if status == "unjudgeable" and value is None:
            result[dimension] = None
        elif status == "scored" and type(value) is int and 0 <= value <= 4:
            result[dimension] = value
        else:
            raise ValueError(f"非法维度评分: {dimension}")
    return result


def _output(index, sid, judge, stage="evidence_scoring"):
    record = index.get((sid, judge, stage), {})
    return record.get("output") if record.get("status") == "ok" else None


def _consistent(output):
    scores = _scores(output)
    audit_status = output.get("necessity_audit", {}).get("status")
    necessity = scores["cross_domain_necessity"]
    if audit_status == "verified_shortcut" and (necessity is None or necessity >= 3):
        return False
    if audit_status == "unresolved" and necessity is not None:
        return False
    for flag in output.get("flags", []):
        dimension = FLAG_DIMENSIONS.get(flag.get("type"))
        if flag.get("status") == "confirmed" and dimension and (scores[dimension] or 0) >= 3:
            return False
    return True


def _complete(index, sid, judge):
    return (all(_output(index, sid, judge, stage) is not None for stage in INITIAL_STAGES)
            and _consistent(_output(index, sid, judge)))


def _passes(scores):
    return all(value is not None and value >= 3 for value in scores.values())


def _critical(output):
    """关键结构化结论即使漏填flags，也必须进入复核和人工。"""
    output = output or {}
    flags = [flag for flag in output.get("flags", []) if flag.get("type") in CRITICAL_FLAGS]
    if output.get('answer_check', {}).get('status') in ('incorrect', 'ambiguous'):
        flags.append({'type': 'key_answer_error', 'status': 'structured_answer_check'})
    if any(item.get('necessity') == 'redundant' for item in output.get('domain_checks', [])):
        flags.append({'type': 'redundant_domain', 'status': 'structured_domain_check'})
    audit = output.get('necessity_audit', {}).get('status')
    if audit == 'verified_shortcut':
        flags.append({'type': 'subset_shortcut', 'status': 'verified_necessity_audit'})
    if audit == 'unresolved' or any(item.get('necessity') == 'uncertain'
                                  for item in output.get('domain_checks', [])):
        flags.append({'type': 'necessity_uncertain', 'status': 'unresolved_necessity_audit'})
    return flags


def _stratum(sample):
    metadata = sample.get("metadata", {})
    return tuple(metadata.get(key) for key in ("source_domain", "k", "difficulty"))


def _label(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _finalize(route, index):
    sid = route["sample_id"]
    route["review_kind"] = ("trigger" if route["rule_triggered"] else
                            "audit" if route["audit_selected"] else
                            "forced" if route["needs_review"] else None)
    route["recommended_joint_pass"] = None
    route["human_review_reasons"] = []
    if not route["needs_review"]:
        return
    # 独立发现的关键问题不能被整合阶段的 human_review_required=false 覆盖。
    for judge in ("J1", "J2", "J3"):
        for flag in _critical(_output(index, sid, judge)):
            route["human_review_reasons"].append(f"{judge}:{flag['type']}:{flag.get('status')}")
    adjudication = _output(index, sid, "J3", "adjudication")
    if not _complete(index, sid, "J3") or adjudication is None:
        if route["human_review_reasons"]:
            route["status"] = "pending_human"
        return
    resolutions = adjudication.get("dimension_resolutions", [])
    resolved = {item.get("dimension"): item for item in resolutions}
    if len(resolutions) != 5 or set(resolved) != set(DIMENSIONS):
        raise ValueError(f"复核必须逐项覆盖五维: {sid}")
    recommended = {}
    for dimension, item in resolved.items():
        status, score = item.get("recommended_status"), item.get("recommended_score")
        if status == "unjudgeable" and score is None:
            recommended[dimension] = None
        elif status == "scored" and type(score) is int and 0 <= score <= 4:
            recommended[dimension] = score
        else:
            raise ValueError(f"非法复核建议评分: {sid}:{dimension}")
        if not isinstance(item.get("basis"), str) or not item["basis"].strip():
            route["human_review_reasons"].append(f"missing_resolution_basis:{dimension}")
    route["recommended_joint_pass"] = _passes(recommended)
    audit_status = adjudication.get("necessity_audit", {}).get("status")
    necessity = recommended["cross_domain_necessity"]
    if audit_status == "verified_shortcut" and (necessity is None or necessity >= 3):
        raise ValueError("复核确认捷径却未给必要性0–2分")
    if audit_status == "unresolved" and necessity is not None:
        raise ValueError("复核必要性未决必须保留U/null")
    if audit_status in ("verified_shortcut", "unresolved"):
        route["human_review_reasons"].append(f"adjudication_necessity:{audit_status}")
    if any(value is None for value in recommended.values()):
        route["human_review_reasons"].append("unjudgeable_after_review")
    if adjudication.get("unresolved_issues"):
        route["human_review_reasons"].append("unresolved_issues")
    if adjudication.get("human_review_required") or adjudication.get("human_review_reasons"):
        route["human_review_reasons"].append("reviewer_requested_human")
    if route["recommended_joint_pass"] != route["initial_joint_pass"]:
        route["human_review_reasons"].append("initial_joint_pass_changed")
    route["status"] = ("pending_human" if route["human_review_reasons"] else
                       "llm_resolved_pass" if route["recommended_joint_pass"] else "llm_resolved_fail")


def route_samples(samples, records, audit_fraction=0.1, seed="20261005", force_review=False):
    """计算全部触发、确定性分层抽查及机器最终状态。

    Args:
        samples: 含 sample_id 和 metadata 的内部样本列表。
        records: 每个样本、评审、阶段唯一的最终记录；不含中间重试。
        audit_fraction: 一致通过集合每层抽查比例，零表示显式关闭抽查。
        seed: 抽查种子；与样本 ID 一起计算稳定哈希。
        force_review: 对完整双初审样本额外强制复核，供 smoke 使用。

    Returns:
        按 sample_id 排序的路由列表；缺失初审不进入自动结论。
    """
    if type(audit_fraction) not in (int, float) or not math.isfinite(audit_fraction) or not 0 <= audit_fraction <= 1:
        raise ValueError("audit_fraction 必须位于 [0, 1]")
    sample_index, index = _index(samples, records)
    routes, eligible = [], defaultdict(list)
    for sid in sorted(sample_index):
        route = dict(sample_id=sid, reasons=[], needs_review=False, audit_selected=False,
                     initial_joint_pass=None, status="execution_incomplete", rule_triggered=False)
        routes.append(route)
        if not all(_complete(index, sid, judge) for judge in ("J1", "J2")):
            route["reasons"].append("execution_incomplete")
            continue
        scores = [_scores(_output(index, sid, judge)) for judge in ("J1", "J2")]
        route["initial_joint_pass"] = all(_passes(score) for score in scores)
        for dimension in DIMENSIONS:
            left, right = (score[dimension] for score in scores)
            if left is None or right is None:
                route["reasons"].append(f"unjudgeable:{dimension}")
            else:
                if abs(left - right) >= 2:
                    route["reasons"].append(f"numeric_gap:{dimension}")
                if (left >= 3) != (right >= 3):
                    route["reasons"].append(f"threshold_disagreement:{dimension}")
        for judge in ("J1", "J2"):
            route["reasons"].extend(f"critical_flag:{judge}:{flag['type']}:{flag.get('status')}"
                                    for flag in _critical(_output(index, sid, judge)))
        route["rule_triggered"] = bool(route["reasons"])
        if not route["rule_triggered"] and route["initial_joint_pass"]:
            eligible[_stratum(sample_index[sid])].append(route)
        if force_review:
            route["reasons"].append("force_review")
    for stratum, candidates in eligible.items():
        ranked = sorted(candidates, key=lambda route: (
            hashlib.sha256(_label([str(seed), stratum, route["sample_id"]]).encode()).hexdigest(),
            route["sample_id"]))
        count = min(len(ranked), math.ceil(len(ranked) * audit_fraction))
        for route in ranked[:count]:
            route["audit_selected"] = True
            route["reasons"].append("stratified_audit")
    for route in routes:
        if route["initial_joint_pass"] is not None:
            route["needs_review"] = bool(route["reasons"])
            route["status"] = ("pending_review" if route["needs_review"] else
                               "llm_consensus_pass" if route["initial_joint_pass"] else "llm_consensus_fail")
        _finalize(route, index)
    return routes


def _dimension_row(outputs, dimension, base):
    values = [_scores(output)[dimension] for output in outputs]
    numeric = [value for value in values if value is not None]
    n, total = len(numeric), len(values)
    row = dict(base, dimension=dimension, denominator=total, numeric_n=n,
               mean=statistics.mean(numeric) if n else None,
               sample_sd=statistics.stdev(numeric) if n > 1 else None,
               median=statistics.median(numeric) if n else None,
               pass_count=sum(value >= 3 for value in numeric), unjudgeable_count=total - n)
    row.update(pass_rate=_rate(row["pass_count"], total),
               numeric_pass_rate=_rate(row["pass_count"], n),
               unjudgeable_rate=_rate(total - n, total))
    for score in range(5):
        row[f"score_{score}_count"] = numeric.count(score)
        row[f"score_{score}_rate"] = _rate(numeric.count(score), total)
    return row


def _group_rows(samples):
    groups = {("overall", "all"): list(samples)}
    for sample in samples:
        source, k, difficulty = _stratum(sample)
        for name, value in (("k", k), ("difficulty", difficulty), ("source_domain", source),
                            ("k_difficulty", [k, difficulty])):
            groups.setdefault((name, _label(value)), []).append(sample)
    return sorted(groups.items())


def aggregate(samples, records, audit_fraction=0.1, seed="20261005", smoke=False):
    """按配对完整集合统计初审，并单列复核子集、计划分母和最终状态。

    Args:
        samples: 内部样本列表。
        records: 唯一最终记录列表。
        audit_fraction: 预先固定的分层抽查比例。
        seed: 预先固定的抽查种子。
        smoke: 强制完整初审进入复核，并明确标记为流程验证数据。

    Returns:
        JSON 可序列化报告；所有零分母的比率、无数值的均值为 None。
    """
    samples, records = list(samples), list(records)
    _, index = _index(samples, records)
    routes = route_samples(samples, records, audit_fraction, seed, force_review=smoke)
    route_index = {route["sample_id"]: route for route in routes}
    report = {"protocol": {"version": "LLM5-v1", "audit_fraction": audit_fraction,
                           "seed": str(seed), "smoke": bool(smoke),
                           "independence": "not_independent_smoke" if smoke else "operator_declared"},
              "dimension_statistics": [], "disagreement_statistics": [], "joint_statistics": [],
              "group_statistics": [], "j3_statistics": [], "audit_strata": [], "routes": routes}
    for (group_by, group), group_samples in _group_rows(samples):
        base = {"group_by": group_by, "group": group}
        ids = [sample["sample_id"] for sample in group_samples]
        paired = [sid for sid in ids if route_index[sid]["initial_joint_pass"] is not None]
        n, planned = len(paired), len(ids)
        all_scores = {sid: [_scores(_output(index, sid, judge)) for judge in ("J1", "J2")] for sid in paired}
        large, threshold, unknown = set(), set(), set()
        for dimension in DIMENSIONS:
            for judge in ("J1", "J2"):
                report["dimension_statistics"].append(_dimension_row(
                    [_output(index, sid, judge) for sid in paired], dimension, dict(base, judge_id=judge)))
            numeric_pairs, exact_count, large_count, threshold_count, xor_count, consensus = 0, 0, 0, 0, 0, 0
            for sid, scores in all_scores.items():
                left, right = [score[dimension] for score in scores]
                xor_count += (left is None) != (right is None)
                if left is None or right is None:
                    unknown.add(sid)
                    continue
                numeric_pairs += 1
                exact_count += left != right
                consensus += left >= 3 and right >= 3
                if abs(left - right) >= 2:
                    large_count += 1
                    large.add(sid)
                if (left >= 3) != (right >= 3):
                    threshold_count += 1
                    threshold.add(sid)
            row = dict(base, dimension=dimension, numeric_pair_denominator=numeric_pairs,
                       paired_complete_denominator=n)
            for name, count, denominator in (("exact_disagreement", exact_count, numeric_pairs),
                    ("large_disagreement", large_count, numeric_pairs),
                    ("threshold_disagreement", threshold_count, numeric_pairs),
                    ("u_status_disagreement", xor_count, n), ("consensus_pass", consensus, n)):
                row.update({f"{name}_{key}": value for key, value in _metric(count, denominator).items()})
            report["disagreement_statistics"].append(row)
        for judge in ("J1", "J2", "consensus"):
            count = sum((all(_passes(score) for score in scores) if judge == "consensus"
                         else _passes(scores[0 if judge == "J1" else 1])) for scores in all_scores.values())
            report["joint_statistics"].append(dict(base, judge_id=judge, **_metric(count, n)))
        group_row = dict(base, planned_samples=planned, paired_complete_samples=n,
                         execution_completion_rate=_rate(n, planned))
        for name, count, denominator in (("large_disagreement", len(large), n),
                ("threshold_disagreement", len(threshold), n), ("any_unjudgeable", len(unknown), n),
                ("rule_trigger", sum(route_index[sid]["rule_triggered"] for sid in ids), n),
                ("audit", sum(route_index[sid]["audit_selected"] for sid in ids), n),
                ("review_workload", sum(route_index[sid]["needs_review"] for sid in ids), planned)):
            group_row.update({f"{name}_{key}": value for key, value in _metric(count, denominator).items()})
        for status in FINAL_STATUSES:
            count = sum(route_index[sid]["status"] == status for sid in ids)
            group_row[f"{status}_count"], group_row[f"{status}_rate"] = count, _rate(count, planned)
        report["group_statistics"].append(group_row)
    paired_count = sum(route["initial_joint_pass"] is not None for route in routes)
    report["execution"] = {"planned_samples": len(samples), "paired_complete_samples": paired_count,
        "completion": _metric(paired_count, len(samples)),
        "missing_paired": _metric(len(samples) - paired_count, len(samples)),
        "final_record_count": len(records),
        "final_error_records": sum(record["status"] == "error" for record in records),
        "initial_stage_planned": len(samples) * 4,
        "initial_stage_ok": sum(_output(index, sample["sample_id"], judge, stage) is not None
                                 for sample in samples for judge in ("J1", "J2") for stage in INITIAL_STAGES),
        "per_judge_complete": {judge: _metric(sum(_complete(index, sample["sample_id"], judge)
                                      for sample in samples), len(samples)) for judge in ("J1", "J2")}}
    for kind in ("trigger", "audit", "forced"):
        selected = [route for route in routes if route["review_kind"] == kind]
        outputs = [_output(index, route["sample_id"], "J3") for route in selected
                   if _complete(index, route["sample_id"], "J3")]
        for dimension in DIMENSIONS:
            report["j3_statistics"].append(_dimension_row(outputs, dimension,
                {"review_kind": kind, "judge_id": "J3", "planned_reviews": len(selected),
                 "complete_independent_reviews": len(outputs)}))
    strata = defaultdict(list)
    for sample in samples:
        route = route_index[sample["sample_id"]]
        if route["initial_joint_pass"] and not route["rule_triggered"]:
            strata[_stratum(sample)].append(route)
    for stratum, candidates in sorted(strata.items(), key=lambda item: _label(item[0])):
        selected = [route["sample_id"] for route in candidates if route["audit_selected"]]
        report["audit_strata"].append(dict(zip(("source_domain", "k", "difficulty"), stratum),
            eligible_count=len(candidates), selected_count=len(selected),
            actual_fraction=_rate(len(selected), len(candidates)), selected_sample_ids=sorted(selected)))
    counts = Counter(route["status"] for route in routes)
    report["final_status"] = {status: _metric(counts[status], len(samples)) for status in FINAL_STATUSES}
    machine_pass = counts["llm_consensus_pass"] + counts["llm_resolved_pass"]
    machine_fail = counts["llm_consensus_fail"] + counts["llm_resolved_fail"]
    report["final_outcomes"] = {
        "machine_pass": _metric(machine_pass, len(samples)),
        "machine_fail": _metric(machine_fail, len(samples)),
        "not_yet_confirmed": _metric(len(samples) - machine_pass - machine_fail, len(samples)),
    }
    report["human_adjudications"] = {"count": 0, "note": "未输入人工裁决；机器结论不等同人工验证。"}
    return report


def write_report(report, output_dir):
    """创建新的输出目录并写入 JSON、CSV 和中文说明；拒绝覆盖已有目录。"""
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "LLM5_summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2,
                                                             allow_nan=False) + "\n", encoding="utf-8")
    for name, key in (("dimensions", "dimension_statistics"), ("disagreements", "disagreement_statistics"),
                      ("joint", "joint_statistics"), ("groups", "group_statistics"), ("J3", "j3_statistics"),
                      ("routes", "routes"), ("audit_strata", "audit_strata")):
        rows = report[key]
        fields = list(dict.fromkeys(field for row in rows for field in row))
        with (destination / f"LLM5_{name}.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows({field: _label(value) if isinstance(value, (list, dict)) else value
                              for field, value in row.items()} for row in rows)
    execution = report["execution"]
    lines = ["# LLM5 本地统计报告", "", "**单模型流程测试，不是跨家族独立质量结论；真实API或模拟数据来源以运行清单为准。**" if report["protocol"]["smoke"]
             else "本报告仅汇总所提供的最终评审记录。", "",
             f"计划样本 {execution['planned_samples']}；完整双初审 {execution['paired_complete_samples']}。",
             "主表按 J1/J2 配对完整集合计算；U 保留在达标率分母，均值与样本标准差排除 U。",
             "分歧率的数值配对分母与 U 状态分歧分母分别列出；JSON null / CSV 空单元格表示不可计算。",
             "J3 按规则触发、随机抽查、强制复核分别报告，不与主表混合。", "",
             "| 最终状态 | 数量 | 计划分母 |", "|---|---:|---:|"]
    lines += [f"| {status} | {metric['count']} | {metric['denominator']} |"
              for status, metric in report["final_status"].items()]
    lines += ["", "机器通过不表示人工验证；未决及执行缺失不应记为事实错误。",
              "每层抽查比例见 LLM5_audit_strata.csv；抽查和触发样本的失败率不能直接外推全量。"]
    (destination / "LLM5_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(destination)


def main():
    """读取 run-dir 中样本、最终记录和可选 manifest，写入新目录。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--audit-fraction", type=float)
    parser.add_argument("--seed")
    parser.add_argument("--smoke", action="store_true", default=None)
    args = parser.parse_args()
    manifest_path = args.run_dir / "LLM5_run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    data = []
    for filename in ("LLM5_samples.jsonl", "LLM5_records.jsonl"):
        data.append([json.loads(line) for line in (args.run_dir / filename).read_text(encoding="utf-8").split('\n') if line.strip()])
    report = aggregate(*data, audit_fraction=args.audit_fraction if args.audit_fraction is not None else manifest.get("audit_fraction", 0.1),
                       seed=args.seed if args.seed is not None else manifest.get("seed", "20261005"),
                       smoke=args.smoke if args.smoke is not None else manifest.get("smoke", False))
    print(write_report(report, args.output_dir))


if __name__ == "__main__":
    main()
