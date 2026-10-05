#!/usr/bin/env python3
"""读取KRC结果生成三组PNG/PDF/SVG，仅绘图依赖matplotlib。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def plot(report: dict, output: Path) -> None:
    """绘制条件覆盖、同支持集加权比较以及纳入率，明确样本分母。

    Args:
        report: KRC_summary.json解析结果。
        output: KRC_figures输出目录。
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter

    settings = report['manifest']['settings']
    ks, tau = settings['domain_counts'], settings['threshold']
    colors = dict(zip(ks, ['#2563eb', '#d97706', '#059669', '#9333ea', '#dc2626', '#475569']))
    marks = dict(zip(ks, ['o', 's', '^', 'D', 'v', 'P']))
    rows = [r for r in report['summary'] if r['budget'] == 'all']
    partial = any(r['macro_weighted'] is None for r in rows)
    prefix = 'observed_source_' if partial else 'macro_'
    population = 'observed-source conditional mean' if partial else 'equal-source conditional macro mean'
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10, 'savefig.dpi': 180,
                         'axes.spines.top': False, 'axes.spines.right': False, 'pdf.fonttype': 42, 'svg.fonttype': 'none'})
    output.mkdir(parents=True, exist_ok=True)

    def save(fig, name):
        """保存同一图的栅格与矢量格式。"""
        for suffix in ('png', 'pdf', 'svg'):
            fig.savefig(output / f'KRC_{name}.{suffix}', bbox_inches='tight')
        plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.4), layout='constrained')
    for ax, mode, title in zip(axes, ['cosine_observed', 'hybrid_complete'],
                              ['Cosine: observed embedding pairs', 'Hybrid: pairs with both scores']):
        for k in ks:
            group = sorted([r for r in rows if r['mode'] == mode and r['domain_count'] == k], key=lambda r: r['threshold'])
            ax.plot([r['threshold'] for r in group], [r[prefix + 'binary'] for r in group],
                    color=colors[k], marker=marks[k], label=f"k={k}, needs={group[0]['evaluated_requirements']}")
        ax.axvline(tau, color='#64748b', linestyle='--', label=f'Main threshold={tau:g}')
        ax.set(xlabel='Score threshold', ylabel='KRC-Binary (conditional)', ylim=(-0.025, 1.05), title=title)
        ax.yaxis.set_major_formatter(PercentFormatter(1))
        ax.grid(axis='y', alpha=0.2)
        ax.legend(fontsize=8)
    fig.suptitle(f'Threshold sensitivity; {population}', fontsize=12)
    save(fig, 'binary_threshold_curve')

    fig, ax = plt.subplots(figsize=(8, 4.4), layout='constrained')
    modes = ['cosine_complete', 'bm25_complete', 'hybrid_complete']
    labels = ['Cosine', 'BM25 normalized', f"Hybrid (BM25 weight={settings['alpha']:g})"]
    for x, (mode, label, color) in enumerate(zip(modes, labels, ['#64748b', '#eab308', '#2563eb'])):
        vals = [next(r for r in rows if r['domain_count'] == k and r['threshold'] == tau and r['mode'] == mode)[prefix + 'weighted'] for k in ks]
        xpos = [i + (x - 1) * 0.24 for i in range(len(ks))]
        ax.bar(xpos, [v if v is not None else 0 for v in vals], width=0.22, color=color, label=label)
        for position, value in zip(xpos, vals):
            ax.text(position, (value or 0) + 0.015, 'N/A' if value is None else f'{value:.3f}', ha='center', fontsize=8)
    ax.set_xticks(range(len(ks)), [f'k={k}' for k in ks])
    ax.set(ylim=(0, 1), ylabel='KRC-Weighted (conditional)',
           title=f'Comparison on identical complete-pair support\n{population}')
    ax.legend(fontsize=8)
    ax.grid(axis='y', alpha=0.15)
    save(fig, 'weighted_coverage')

    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.4), layout='constrained')
    for ax, numerator, denominator, title in zip(axes,
            ['eligible_pairs', 'evaluated_requirements'], ['total_pairs', 'total_requirements'],
            ['Pair inclusion', 'Requirement inclusion']):
        for offset, mode, label, color in [(-0.18, 'cosine_observed', 'Embedding available', '#2563eb'),
                                          (0.18, 'hybrid_complete', 'Both scores available', '#94a3b8')]:
            groups = [next(r for r in rows if r['domain_count'] == k and r['mode'] == mode and r['threshold'] == tau) for k in ks]
            values = [r[numerator] / r[denominator] if r[denominator] else 0 for r in groups]
            ax.bar([i + offset for i in range(len(ks))], values, width=0.34, label=label, color=color)
            for i, (value, row) in enumerate(zip(values, groups)):
                ax.text(i + offset, value + 0.02, f"{row[numerator]}/{row[denominator]}", ha='center', fontsize=8)
        ax.set_xticks(range(len(ks)), [f'k={k}' for k in ks])
        ax.set(ylim=(0, 1.28), ylabel='Inclusion rate (pooled counts)', title=title)
        ax.set_yticks([0, 0.2, 0.4, 0.6, 0.8, 1])
        ax.yaxis.set_major_formatter(PercentFormatter(1))
        ax.legend(fontsize=8, loc='upper left')
    save(fig, 'score_availability')


def main() -> None:
    """只读取已计算KRC结果，不调用评测模型。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    output = args.output or args.input.parent / 'KRC_figures'
    plot(json.loads(args.input.read_text(encoding='utf-8')), output)
    print(f'KRC图表完成: {output.resolve()}')


if __name__ == '__main__':
    main()
