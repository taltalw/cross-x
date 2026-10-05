"""KNC 保存分数审计：标准库实现，不导入模型、向量库或网络客户端。"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

if __package__ and "." in __package__:
    from ..DDE.domain_distribution_entropy import DEFAULT_DOMAINS, validate_config, validate_record
else:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from DDE.domain_distribution_entropy import DEFAULT_DOMAINS, validate_config, validate_record

DEFAULT_THRESHOLDS = [0.30, 0.40, 0.50, 0.60, 0.65, 0.70, 0.75, 0.80, 0.90]
RATE_FIELDS = ("knc_saved", "complete_lower", "complete_upper", "need_score_availability")


def stable_id(value) -> str:
    """为身份和抽样生成稳定摘要。"""
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def mean(values) -> float | None:
    """对非空数值序列等权平均；空集合保持缺失。"""
    return math.fsum(values) / len(values) if values else None


def normalize_plan(row: dict, domains: list[str]) -> dict:
    """校验阶段3记录并只保留审计所需的字段。

    Returns:
        含候选逐需求 embedding 分数的方案；缺失分数不补零。
    """
    if isinstance(row, dict) and "difficulty" in row:
        raise ValueError("请使用阶段3检索文件，不要使用最终题目的难度变体")
    source, k, _, atomic_id = validate_record(row, domains)
    required, retrieved = row.get("required_key_facts"), row.get("retrieved_samples")
    added = row["fusion_domains"]
    if not isinstance(required, dict) or set(required) != set(added):
        raise ValueError("required_key_facts 必须覆盖全部新增领域")
    if not isinstance(retrieved, dict) or set(retrieved) != set(added):
        raise ValueError("retrieved_samples 必须覆盖全部新增领域")
    config = row.get("retrieval", {})
    if not isinstance(config, dict) or config.get("method") != "hybrid":
        raise ValueError("本工具要求有 embedding 的 hybrid 检索记录")
    config_hash = config.get("embedding_config_hash")
    if not isinstance(config_hash, str) or not config_hash:
        raise ValueError("缺少 embedding_config_hash，无法核对分数配置")
    normalized = {}
    for domain in added:
        needs, candidates = required[domain], retrieved[domain]
        if not isinstance(needs, list) or not needs:
            raise ValueError(f"{domain}: 需求列表必须非空")
        for need in needs:
            if not isinstance(need, dict) or any(
                not isinstance(need.get(f), str) or not need[f].strip()
                for f in ("key_fact", "necessity")
            ):
                raise ValueError(f"{domain}: 需求缺少 key_fact 或 necessity")
        if not isinstance(candidates, list):
            raise ValueError(f"{domain}: 候选必须是列表；空列表与字段缺失不同")
        items, seen = [], set()
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise ValueError(f"{domain}: 候选必须是对象")
            cid = candidate.get("candidate_id")
            if not isinstance(cid, str) or not cid or cid in seen:
                raise ValueError(f"{domain}: candidate_id 缺失或重复")
            seen.add(cid)
            sample, hits = candidate.get("sample"), candidate.get("hits")
            if not isinstance(sample, dict) or any(not isinstance(sample.get(f), str) for f in ("prompt", "completion")):
                raise ValueError(f"{cid}: 缺少候选问答文本")
            if not isinstance(hits, list):
                raise ValueError(f"{cid}: hits 必须是列表")
            scores = {}
            for hit in hits:
                if not isinstance(hit, dict):
                    raise ValueError(f"{cid}: hit 必须是对象")
                if hit.get("method") != "embedding":
                    continue
                j, score = hit.get("query_index"), hit.get("score")
                if type(j) is not int or not 1 <= j <= len(needs):
                    raise ValueError(f"{cid}: query_index 必须是领域内从1开始的需求序号")
                if type(score) not in (int, float) or not math.isfinite(score) or not -1 <= score <= 1:
                    raise ValueError(f"{cid}: embedding score 必须是[-1,1]内有限数值")
                if j in scores and scores[j] != score:
                    raise ValueError(f"{cid}: 同一需求的重复 embedding hit 分数冲突")
                scores[j] = float(score)
            items.append({"candidate_id": cid, "sample": sample, "scores": scores})
        normalized[domain] = items
    return {"source_domain": source, "domain_count": k, "atomic_id": atomic_id,
            "plan_id": stable_id([source, k, atomic_id]), "sample": row["sample"],
            "question_plan": row.get("question_plan", ""), "fusion_domains": added,
            "required_key_facts": required, "candidates": normalized,
            "embedding_config_hash": config_hash, "retrieval": config}


def load_input(input_path: Path, domains: list[str], domain_counts: list[int]) -> tuple:
    """读取阶段3文件，检测重复方案，保存输入哈希与行号。"""
    validate_config(domains, domain_counts)
    root = input_path.resolve()
    if not root.exists():
        raise ValueError(f"输入不存在: {root}")
    files = sorted(root.rglob("*.jsonl")) if root.is_dir() else [root]
    if not files:
        raise ValueError("没有找到JSONL文件")
    plans, seen = [], set()
    metadata = {"input_path": str(root), "files": [], "rows_read": 0, "rows_excluded_by_k": 0}
    for path in files:
        content = path.read_bytes()
        metadata["files"].append({"path": str(path), "sha256": hashlib.sha256(content).hexdigest()})
        # JSON字符串允许U+2028等Unicode分隔符；JSONL仅按物理换行分记录。
        for line_number, line in enumerate(content.decode("utf-8-sig").split("\n"), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                plan = normalize_plan(row, domains)
                metadata["rows_read"] += 1
                if plan["domain_count"] not in domain_counts:
                    metadata["rows_excluded_by_k"] += 1
                    continue
                if plan["plan_id"] in seen:
                    raise ValueError("同源原子样本同k的方案重复；请勿合并重复实验")
                seen.add(plan["plan_id"])
                plan.update(input_file=str(path), input_line=line_number)
                plans.append(plan)
            except ValueError as exc:
                raise ValueError(f"{path}:{line_number}: {exc}") from exc
    if not plans:
        raise ValueError("输入为空或没有指定k的方案")
    return plans, metadata


def select_plans(plans: list[dict], domain_counts: list[int], samples_per_source: int = 1,
                 seed: int = 42, source_domains: list[str] | None = None,
                 all_plans: bool = False) -> list[dict]:
    """按源领域抽取跨k共享原子样本，排序与文件遍历顺序无关。"""
    if type(samples_per_source) is not int or samples_per_source < 1:
        raise ValueError("samples_per_source 必须为正整数")
    available = {p["source_domain"] for p in plans}
    sources = sorted(available) if source_domains is None else source_domains
    if not sources or len(set(sources)) != len(sources) or not set(sources) <= available:
        raise ValueError("指定的源领域缺失、重复或为空")
    groups = defaultdict(dict)
    for p in plans:
        if p["domain_count"] in domain_counts and p["source_domain"] in sources:
            groups[(p["source_domain"], p["domain_count"])][p["atomic_id"]] = p
    selected = []
    for source in sorted(sources):
        if all_plans:
            for k in domain_counts:
                selected.extend(groups[(source, k)].values())
            continue
        common = set.intersection(*(set(groups[(source, k)]) for k in domain_counts))
        if len(common) < samples_per_source:
            raise ValueError(f"{source}: 跨指定k的共有原子样本仅{len(common)}条；请检查 --domain-counts 或抽样数量")
        chosen = sorted(common, key=lambda a: stable_id([seed, source, a]))[:samples_per_source]
        for atomic in chosen:
            selected.extend(groups[(source, k)][atomic] for k in domain_counts)
    return sorted(selected, key=lambda p: (p["source_domain"], p["domain_count"], p["atomic_id"]))


def extract_scores(plans: list[dict], budgets: list[str]) -> tuple:
    """构建完整配对明细及各预算下的保存分数最大值，缺失保持None。"""
    pairs, requirements = [], []
    for p in plans:
        base = {f: p[f] for f in ("plan_id", "source_domain", "domain_count", "atomic_id")}
        for domain in p["fusion_domains"]:
            candidates = p["candidates"][domain]
            for j, need in enumerate(p["required_key_facts"][domain], 1):
                identity = {**base, "requirement_id": f"{p['plan_id']}:{domain}:{j}",
                            "target_domain": domain, "query_index": j, **need}
                for position, candidate in enumerate(candidates, 1):
                    score = candidate["scores"].get(j)
                    pairs.append({**identity, "candidate_id": candidate["candidate_id"],
                                  "candidate_position": position, "embedding_score": score,
                                  "status": "observed" if score is not None else "not_saved"})
                for budget in budgets:
                    subset = candidates if budget == "all" else candidates[:int(budget)]
                    visible = [(c["scores"][j], c) for c in subset if j in c["scores"]]
                    best = max(visible, key=lambda item: item[0]) if visible else None
                    requirements.append({**identity, "budget": budget,
                        "candidate_count": len(subset), "observed_pairs": len(visible),
                        "missing_pairs": len(subset) - len(visible),
                        "best_saved_score": best[0] if best else None,
                        "best_candidate_id": best[1]["candidate_id"] if best else None,
                        "best_candidate_prompt": best[1]["sample"]["prompt"] if best else None,
                        "best_candidate_completion": best[1]["sample"]["completion"] if best else None,
                        "score_status": "empty_candidates" if not subset else ("observed" if best else "no_saved_score")})
    return pairs, requirements


def evaluate_requirement(row: dict, threshold: float) -> dict:
    """返回保存命中指标及完整配对的保守边界，不对未知分数作推断。"""
    score = row["best_saved_score"]
    covered = score is not None and score >= threshold
    unknown = not covered and row["missing_pairs"] > 0
    return {"threshold": threshold, "saved_hit": int(covered),
            "complete_lower": int(covered), "complete_upper": int(covered or unknown),
            "complete_state": "covered" if covered else ("unknown" if unknown else "uncovered")}


def compute_metrics(requirements: list[dict], domains: list[str], domain_counts: list[int],
                    thresholds: list[float], budgets: list[str]) -> dict:
    """按需求→新增领域→方案→源领域等权汇总。

    Returns:
        阈值明细、逐方案、逐源领域和总体结果；缺失源领域的完整宏平均为None。
    """
    if not thresholds or any(type(t) not in (int, float) or not math.isfinite(t) or not -1 <= t <= 1 for t in thresholds):
        raise ValueError("阈值必须为[-1,1]内有限数值")
    grouped = defaultdict(list)
    for r in requirements:
        grouped[(r["plan_id"], r["budget"])].append(r)
    per_need, per_plan = [], []
    for (pid, budget), rows in grouped.items():
        for threshold in thresholds:
            domain_rates = defaultdict(list)
            states = []
            for r in rows:
                result = evaluate_requirement(r, threshold)
                per_need.append({k: r[k] for k in ("requirement_id", "plan_id", "target_domain", "query_index", "budget")} | result)
                domain_rates[r["target_domain"]].append((r, result))
                states.append(result["complete_state"])
            by_domain = []
            for entries in domain_rates.values():
                by_domain.append({"knc_saved": mean([v["saved_hit"] for _, v in entries]),
                    "complete_lower": mean([v["complete_lower"] for _, v in entries]),
                    "complete_upper": mean([v["complete_upper"] for _, v in entries]),
                    "need_score_availability": mean([int(r["observed_pairs"] > 0) for r, _ in entries])})
            n_pairs = sum(r["candidate_count"] for r in rows)
            observed = sum(r["observed_pairs"] for r in rows)
            per_plan.append({"plan_id": pid, "source_domain": rows[0]["source_domain"],
                "domain_count": rows[0]["domain_count"], "threshold": threshold, "budget": budget,
                "n_needs": len(rows), "needs_with_scores": sum(r["observed_pairs"] > 0 for r in rows),
                "candidate_pairs": n_pairs, "observed_pairs": observed,
                "pair_score_availability": observed / n_pairs if n_pairs else None,
                "unknown_complete_needs": states.count("unknown"),
                **{f: mean([d[f] for d in by_domain]) for f in RATE_FIELDS},
                "all_covered_saved": int(all(d["knc_saved"] == 1 for d in by_domain)),
                "weakest_domain_saved": min(d["knc_saved"] for d in by_domain)})
    per_source, summary = [], []
    for k in domain_counts:
        for budget in budgets:
            for threshold in thresholds:
                groups = []
                for source in domains:
                    ps = [p for p in per_plan if p["source_domain"] == source and p["domain_count"] == k
                          and p["threshold"] == threshold and p["budget"] == budget]
                    entry = {"source_domain": source, "domain_count": k, "threshold": threshold, "budget": budget,
                             "n_plans": len(ps), "n_needs": sum(p["n_needs"] for p in ps),
                             **{f: mean([p[f] for p in ps]) for f in RATE_FIELDS}}
                    per_source.append(entry)
                    if ps:
                        groups.append(entry)
                full = len(groups) == len(domains)
                entry = {"domain_count": k, "threshold": threshold, "budget": budget,
                         "n_plans": sum(g["n_plans"] for g in groups), "n_needs": sum(g["n_needs"] for g in groups),
                         "expected_sources": len(domains), "observed_sources": len(groups),
                         "missing_sources": [a for a in domains if a not in {g["source_domain"] for g in groups}]}
                for field in RATE_FIELDS:
                    value = mean([g[field] for g in groups])
                    entry["observed_source_" + field] = value
                    entry["macro_" + field] = value if full else None
                summary.append(entry)
    return {"requirement_coverage": per_need, "per_plan": per_plan,
            "per_source": per_source, "summary": summary}
