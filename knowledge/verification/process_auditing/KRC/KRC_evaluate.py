#!/usr/bin/env python3
"""KRC离线评测：只评测有Embedding分数的配对；混合模式需BM25也有分数。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from pathlib import Path

if __package__:
    from .KRC_data import DOMAINS, digest, fit_normalization, read_plans, split_plans
    from .KRC_core import MODES, aggregate, extract_pairs, requirement_scores
else:
    from KRC_data import DOMAINS, digest, fit_normalization, read_plans, split_plans
    from KRC_core import MODES, aggregate, extract_pairs, requirement_scores

TABLES = ('pair_scores', 'requirement_scores', 'requirement_coverage', 'per_domain', 'per_plan', 'per_source', 'summary')
FILES = [f'KRC_{t}.csv' for t in TABLES] + ['KRC_summary.json', 'KRC_run_manifest.json',
         'KRC_normalization.json', 'KRC_reference_manifest.json', 'KRC_report.md']
LABELS = {'cosine_observed': 'Cosine（Embedding可用集）', 'hybrid_complete': '混合（双路齐全集）',
          'cosine_complete': 'Cosine（双路齐全集）', 'bm25_complete': 'BM25（双路齐全集）'}


def display(value, percent: bool = True) -> str:
    """格式化条件均值，缺失组显示N/A。"""
    return 'N/A' if value is None else (f'{value:.2%}' if percent else f'{value:.6f}')


def render_report(report: dict) -> str:
    """生成自包含中文报告，强调有效需求分母和不同支持集。"""
    m, diagnostic = report['manifest'], report['diagnostics']
    threshold = m['settings']['threshold']
    main = [r for r in report['summary'] if r['budget'] == 'all' and r['threshold'] == threshold]
    lines = ['# KRC：仅评测有分数配对的离线结果', '',
        '指标是检索分数代理，不是已验证的知识充分支持率。本次未加载模型、生成向量或调用API。', '',
        f"读取{m['input']['rows_read']}方案；参考集{len(m['reference_sample'])}方案；评测{len(m['sample'])}方案。",
        f"评测范围共{diagnostic['total_requirements']}需求、{diagnostic['total_pairs']}配对；"
        f"Embedding可用{diagnostic['embedding_pairs']}配对，其中双路齐全{diagnostic['complete_pairs']}配对。",
        f"没有Embedding分数的{diagnostic['total_pairs'] - diagnostic['embedding_pairs']}配对不参与任何模式的评测。",
        f"主展示阈值τ={threshold:g}，混合BM25权重α={m['settings']['alpha']:g}；阈值和权重未经支持标签校准。", '',
        '## 主结果（各k先按新增领域、方案、源领域平均）', '',
        '| 模式 | k | 可评测/总方案 | 纳入/总需求 | 纳入/总配对 | Binary宏平均 | Weighted宏平均 | 有效源领域 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in main:
        lines.append(f"| {LABELS[r['mode']]} | {r['domain_count']} | {r['evaluated_plans']}/{r['total_plans']} | {r['evaluated_requirements']}/{r['total_requirements']} | {r['eligible_pairs']}/{r['total_pairs']} | {display(r['macro_binary'])} | {display(r['macro_weighted'], False)} | {r['evaluated_sources']}/{r['expected_sources']} |")
    lines += ['', '## 如何理解分母', '',
        '- 配对不是需求：同一需求可能对应多条材料；先取每项需求的最佳有效材料，再对需求平均。',
        '- Cosine可用集纳入所有保存了Embedding分数的配对，包括分数为0或负数的配对（负数按约定clip为0）。',
        '- 混合模式仅使用同一配对同时保存BM25与Embedding的记录；BM25缺失不补0，不重新分配权重。',
        '- 一个需求在指定模式和预算下没有有效候选时，weight与covered均为null，并从条件均值分母排除；排除数仍完整报告。',
        '- 新增领域无有效需求则其均值为null；方案按有有效需求的新增领域平均，同时保留总/有效领域数。空方案排除；七源领域缺组时完整macro为N/A，局部均值见CSV的observed_source列。',
        '- 不同支持集上的分数不可直接归因于方法优劣。比较BM25、Cosine、混合，请使用三种complete模式的相同配对/需求集合。',
        '- 加权指标不受阈值影响；CSV汇总为便于与Binary并列而重复展示Weighted，不可跨阈值重复计数。',
        '- 候选预算先按原RRF顺序截取，再筛选有分数配对；不同预算的有效需求分母会改变，条件覆盖曲线不保证单调。', '',
        '## 阈值敏感性（all候选）', '',
        '| 模式 | k | 阈值 | Binary宏平均 | 纳入需求 |', '|---|---:|---:|---:|---:|']
    for r in report['summary']:
        if r['budget'] == 'all' and r['mode'] in ('cosine_observed', 'hybrid_complete'):
            lines.append(f"| {LABELS[r['mode']]} | {r['domain_count']} | {r['threshold']:g} | {display(r['macro_binary'])} | {r['evaluated_requirements']} |")
    lines += ['', '## BM25固定归一化范围', '', '| 目标领域 | 最小值 | 最大值 | 参考分数数量 |', '|---|---:|---:|---:|']
    for d, values in report['normalization']['ranges'].items():
        lines.append(f"| {d} | {values['min']:.6f} | {values['max']:.6f} | {values['observed_scores']} |")
    lines += ['', f"评测双路齐全配对的BM25低端/高端截断：{diagnostic['bm25_clipped_low']}/{diagnostic['bm25_clipped_high']}，分母{diagnostic['complete_pairs']}。", '',
        '参考集与评测集按(源领域,原子样本)互斥，同一原子样本的不同k整体留出。参考范围跨k、阈值、候选预算固定；原始RRF仅用于候选顺序，需求级RRF贡献留作追溯，不加入混合权重。', '',
        '## 复现与边界', '',
        '- KRC_run_manifest.json保存输入哈希、代码哈希、配置、样本文件行号、参考划分和参数。',
        '- KRC_pair_scores.csv只包含有Embedding分数的配对；KRC_requirement_scores.csv保留全部需求及排除原因、最佳材料原文。',
        '- 有分数子集受到召回与排序选择影响，不能代表被排除配对的知识支持情况，也不能外推整体pipeline质量。',
        '- 本次小样本仅用于验证指标实现；预设阈值网格用于敏感性分析，不据覆盖率高低选择“最优阈值”。', '']
    return '\n'.join(lines)


def build_report(args) -> dict:
    """读取输入、固定参考集并计算，输出前先完成全部验证。"""
    thresholds = sorted(set(args.thresholds + [args.threshold]))
    if any(not math.isfinite(t) or not 0 < t <= 1 for t in thresholds):
        raise ValueError('阈值必须在(0,1]')
    budgets = list(dict.fromkeys(['all'] + args.budgets))
    if any(b != 'all' and (not b.isdigit() or int(b) < 1 or str(int(b)) != b) for b in budgets):
        raise ValueError('候选预算必须为all或正整数')
    plans, metadata = read_plans(args.input, args.domains, args.domain_counts)
    pinned, pinned_meta = None, None
    if args.sample_manifest:
        content = args.sample_manifest.read_bytes()
        pinned = json.loads(content)['sample']
        pinned_meta = {'path': str(args.sample_manifest.resolve()), 'sha256': hashlib.sha256(content).hexdigest()}
    reference, selected, pool, split = split_plans(plans, args.domain_counts, args.seed,
        args.reference_fraction, args.samples_per_source, pinned)
    if args.all_evaluation:
        selected = pool
    if args.source_domains:
        if len(set(args.source_domains)) != len(args.source_domains) or not set(args.source_domains) <= {p['source_domain'] for p in selected}:
            raise ValueError('指定源领域不存在或重复')
        selected = [p for p in selected if p['source_domain'] in args.source_domains]
    if not selected:
        raise ValueError('没有选中评测方案')
    norm = fit_normalization(reference)
    norm['input_fingerprints'] = metadata['files']
    if args.normalization:
        saved = json.loads(args.normalization.read_text(encoding='utf-8'))
        if digest(saved) != digest(norm):
            raise ValueError('保存的归一化与当前输入、配置或参考划分不一致')
        norm = saved
    norm_id = digest(norm)
    pairs = extract_pairs(selected, norm, args.alpha)
    requirements = requirement_scores(selected, pairs, budgets)
    report = aggregate(requirements, args.domains, args.domain_counts, budgets, thresholds)
    report.update(pair_scores=[r for r in pairs if r['embedding_available']], requirement_scores=requirements, normalization=norm)
    report['diagnostics'] = {'total_pairs': len(pairs), 'embedding_pairs': sum(p['embedding_available'] for p in pairs),
        'complete_pairs': sum(p['both_available'] for p in pairs),
        'total_requirements': sum(len(needs) for p in selected for needs in p['needs'].values()),
        'bm25_clipped_low': sum(p['bm25_clipped'] == 'low' for p in pairs),
        'bm25_clipped_high': sum(p['bm25_clipped'] == 'high' for p in pairs)}
    identity = ('plan_id', 'atomic_id', 'source_domain', 'domain_count', 'input_file', 'input_line')
    code = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('KRC_*.py')}
    report['manifest'] = {'schema_version': 1, 'metric': 'KRC-observed-v1', 'offline': True, 'model_calls': 0,
        'definition': 'conditional requirement coverage on observed embedding pairs; hybrid requires both scores',
        'input': metadata, 'sample_manifest': pinned_meta, 'normalization_id': norm_id, 'code_sha256': code,
        'normalization_source': str(args.normalization.resolve()) if args.normalization else None,
        'settings': {'domains': args.domains, 'domain_counts': args.domain_counts, 'threshold': args.threshold,
                     'thresholds': thresholds, 'budgets': budgets, 'alpha': args.alpha, 'modes': list(MODES),
                     'seed': args.seed, 'samples_per_source': args.samples_per_source, 'all_evaluation': args.all_evaluation},
        'split': split, 'retrieval_config': selected[0]['config'],
        'reference_sample': [{f: p[f] for f in identity} for p in reference],
        'sample': [{f: p[f] for f in identity} for p in selected]}
    return report


def write_reports(report: dict, output: Path, overwrite: bool = False) -> None:
    """只写KRC_前缀文件，拒绝覆盖输入、符号链接和未授权已有报告。"""
    output = output.resolve()
    m = report['manifest']
    root = Path(m['input']['path'])
    if root.is_dir() and (output == root or root in output.parents):
        raise ValueError('输出目录不能位于原始输入目录中')
    protected = {Path(f['path']).resolve() for f in m['input']['files']}
    for path in (m['normalization_source'], m['sample_manifest']['path'] if m['sample_manifest'] else None):
        if path:
            protected.add(Path(path).resolve())
    for name in FILES:
        target = output / name
        if target.is_symlink() or target.is_dir() or target.resolve() in protected:
            raise ValueError(f'不安全的输出路径: {target}')
        if target.exists() and not overwrite:
            raise ValueError(f'文件已存在: {target}；请换目录或显式--overwrite')
    output.mkdir(parents=True, exist_ok=True)
    for table in TABLES:
        rows = report[table]
        fields = list(rows[0]) if rows else ['requirement_id', 'candidate_id', 'cosine_raw', 'evaluation_status']
        with (output / f'KRC_{table}.csv').open('w', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for k, v in row.items()})
    data = {'KRC_summary.json': report, 'KRC_run_manifest.json': m, 'KRC_normalization.json': report['normalization'],
            'KRC_reference_manifest.json': {'normalization_id': m['normalization_id'], 'split': m['split'], 'sample': m['reference_sample']}}
    for name, value in data.items():
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    (output / 'KRC_report.md').write_text(render_report(report), encoding='utf-8')


def main(argv: list[str] | None = None) -> int:
    """提供无第三方依赖的CLI入口。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--sample-manifest', type=Path, help='复用含sample清单的KNC/KRC运行清单')
    parser.add_argument('--normalization', type=Path, help='复用固定参考文件，并核验与当前划分一致')
    parser.add_argument('--domains', nargs='+', default=list(DOMAINS))
    parser.add_argument('--domain-counts', type=int, nargs='+', default=[2, 3, 4])
    parser.add_argument('--source-domains', nargs='+', help='仅过滤评测样本，不改变参考集或领域全集')
    parser.add_argument('--samples-per-source', type=int, default=1)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--reference-fraction', type=float, default=0.2)
    parser.add_argument('--all-evaluation', action='store_true', help='计算参考集以外全部配对原子方案')
    parser.add_argument('--alpha', type=float, default=0.5, help='混合模式BM25权重，默认0.5')
    parser.add_argument('--threshold', type=float, default=0.5, help='主展示门槛，未经语义标签校准')
    parser.add_argument('--thresholds', type=float, nargs='+', default=[0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8])
    parser.add_argument('--budgets', nargs='+', default=['1', '3', '5', '10'])
    parser.add_argument('--overwrite', action='store_true')
    args = parser.parse_args(argv)
    try:
        report = build_report(args)
        write_reports(report, args.output, args.overwrite)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f'KRC错误: {exc}', file=sys.stderr)
        return 2
    print(f"KRC完成: {args.output.resolve()}；模型调用=0；{report['diagnostics']}")
    for r in report['summary']:
        if r['budget'] == 'all' and r['threshold'] == args.threshold and r['mode'] in ('cosine_observed', 'hybrid_complete'):
            print(f"{r['mode']} k={r['domain_count']}: Binary={display(r['macro_binary'])}, Weighted={display(r['macro_weighted'], False)}, 需求={r['evaluated_requirements']}/{r['total_requirements']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
