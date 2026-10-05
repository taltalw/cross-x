"""从现有 Pipeline 输出准备 CDNS 实验输入，不调用模型。"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from CDNS_data import (PROMPT_VERSION, build_requests, file_digest, fresh_directory,
                       normalize_record, read_jsonl, write_json, write_jsonl)

DEFAULT_INPUT = Path(__file__).resolve().parents[3] / 'pipielines_v4/outputs/4_generate_fusion_question'


def prepare(input_path, output_dir, materials_source='retrieved', difficulty=None, per_group=None):
    """准备真实数据，每个源领域×k×难度组可限量抽取前若干条。

    Args:
        input_path: 单个 JSONL 或递归包含 JSONL 的目录。
        output_dir: 空输出目录。
        materials_source: 阶段4材料选择。
        difficulty: 可选难度过滤器。
        per_group: 可选分组样本上限。
    """
    if per_group is not None and (type(per_group) is not int or per_group < 1):
        raise ValueError('per_group 必须为正整数')
    path = Path(input_path)
    paths = sorted(path.rglob('*.jsonl')) if path.is_dir() else [path]
    if not paths or any(not p.is_file() for p in paths):
        raise ValueError('未找到输入 JSONL')
    samples, answers, requests, selected, sources = [], [], [], Counter(), []
    seen, scanned = set(), 0
    for file in paths:
        source_hash = file_digest(file)
        for line_no, row in read_jsonl(file):
            scanned += 1
            if difficulty is not None and row.get('difficulty') != difficulty:
                continue
            try:
                sample = normalize_record(row, materials_source)
            except (ValueError, TypeError) as exc:
                raise ValueError(f'{file}:{line_no}: {exc}') from exc
            group = (sample['source_domain'], sample['domain_count'], sample['difficulty'])
            if per_group is not None and selected[group] >= per_group:
                continue
            if sample['sample_id'] in seen:
                raise ValueError(f'{file}:{line_no}: 重复样本 ID')
            seen.add(sample['sample_id'])
            selected[group] += 1
            answers.append({'sample_id': sample['sample_id'], 'answer': sample.pop('answer')})
            sample['provenance'] = {'file': str(file.resolve()), 'line': line_no,
                                    'source_sha256': source_hash}
            samples.append(sample)
            requests.extend(build_requests(sample))
        sources.append({'path': str(file.resolve()), 'sha256': source_hash})
    if not samples:
        raise ValueError('过滤后无样本')
    root = fresh_directory(output_dir)
    for name, rows in [('CDNS_samples.jsonl', samples), ('CDNS_answers.jsonl', answers),
                       ('CDNS_requests.jsonl', requests)]:
        write_jsonl(root / name, rows)
    manifest = {'schema_version': 1, 'prompt_version': PROMPT_VERSION,
                'materials_source': materials_source, 'difficulty_filter': difficulty,
                'per_group_limit': per_group, 'scanned_records': scanned,
                'sample_count': len(samples), 'request_count': len(requests),
                'real_model_calls': 0, 'sources': sources,
                'groups': [{'source_domain': g[0], 'k': g[1], 'difficulty': g[2],
                            'samples': count, 'requests': count * (2 * g[1] + 2)}
                           for g, count in sorted(selected.items())],
                'files': {name: file_digest(root / name) for name in
                          ('CDNS_samples.jsonl', 'CDNS_answers.jsonl', 'CDNS_requests.jsonl')}}
    write_json(root / 'CDNS_manifest.json', manifest)
    return manifest


def main():
    """执行只读数据准备入口。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=DEFAULT_INPUT)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--materials-source', choices=['retrieved', 'used'], default='retrieved')
    parser.add_argument('--difficulty', choices=['easy', 'medium', 'hard'])
    parser.add_argument('--per-group', type=int, help='每个源域×k×难度取前 N 条；省略则全量')
    args = parser.parse_args()
    try:
        result = prepare(args.input, args.output_dir, args.materials_source, args.difficulty, args.per_group)
    except (ValueError, OSError) as exc:
        parser.exit(2, f'CDNS 准备失败：{exc}\n')
    print(f"CDNS 准备完成：{result['sample_count']} 样本，{result['request_count']} 请求；未调用模型。")


if __name__ == '__main__':
    main()
