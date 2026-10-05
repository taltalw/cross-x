"""真实输入审计与模拟端到端验证。禁止联网，不产生真实实验指标。"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from CDNS_data import (digest, file_digest, fresh_directory, load_bundle,
                       normalize_record, read_jsonl, write_json, write_jsonl)
from CDNS_infer import run_inference
from CDNS_prepare import DEFAULT_INPUT, prepare
from CDNS_score import score


def audit_inputs(input_path):
    """全量检查两种材料映射和真实字段，不构造或调用模型。"""
    source = Path(input_path)
    files = sorted(source.rglob('*.jsonl')) if source.is_dir() else [source]
    counts, origins, before = Counter(), Counter(), {}
    if not files:
        raise ValueError('没有输入文件')
    seen = {'retrieved': set(), 'used': set()}
    for path in files:
        before[str(path.resolve())] = file_digest(path)
        for line, row in read_jsonl(path):
            for mode in ('retrieved', 'used'):
                sample = normalize_record(row, mode)
                if sample['sample_id'] in seen[mode]:
                    raise ValueError(f'{path}:{line}: 重复 ID')
                seen[mode].add(sample['sample_id'])
                origins[f'{mode}:{sample["material_origin"]}'] += 1
            counts[(sample['domain_count'], sample['difficulty'])] += 1
    for path, value in before.items():
        if file_digest(path) != value:
            raise ValueError('审计期间原始文件发生变化')
    return {'file_count': len(files), 'sample_count': sum(counts.values()),
            'groups': [{'k': k, 'difficulty': level, 'samples': n,
                        'expected_requests': n * (2 * k + 2)}
                       for (k, level), n in sorted(counts.items())],
            'material_origins': dict(origins), 'source_hashes': before,
            'source_files_unchanged': True, 'real_model_calls': 0}


def simulation_predictions(samples, answers, requests):
    """制造三种已知答案模式，仅用于验证程序逻辑。"""
    cases = {s['sample_id']: i % 3 for i, s in enumerate(samples)}
    first_domain = {s['sample_id']: s['domains'][0] for s in samples}
    config = {'backend': 'synthetic-fixture', 'version': 1}
    predictions = []
    for request in requests:
        sid, condition = request['sample_id'], request['condition']
        case = cases[sid]
        correct = (condition == 'full' and case != 2) or (
            condition in ('mask', 'only') and case != 0 and request['domain'] == first_domain[sid])
        wrong = next(key for key in request['option_labels'] if key != answers[sid])
        predictions.append({'request_id': request['request_id'], 'prompt_sha256': request['prompt_sha256'],
                            'inference_id': digest(config), 'inference_config': config,
                            'status': 'ok', 'answer': answers[sid] if correct else wrong,
                            'simulation': True})
    return predictions, cases


def validate(input_path, output_dir):
    """执行全量只读审计、分组小样本准备、dry-run 和模拟评分。"""
    root = fresh_directory(output_dir)
    with patch('urllib.request.urlopen', side_effect=AssertionError('验证禁止网络访问')):
        audit = audit_inputs(input_path)
        manifest = prepare(input_path, root / 'CDNS_prepared', difficulty='easy', per_group=1)
        samples, answers, requests, _ = load_bundle(root / 'CDNS_prepared')
        dry_run = run_inference(root / 'CDNS_prepared', output=None)
        predictions, cases = simulation_predictions(samples, answers, requests)
        output = root / 'CDNS_mock_predictions.jsonl'
        write_jsonl(output, predictions)
        report = score(root / 'CDNS_prepared', output, root / 'CDNS_mock_scores')
    expected_cdns = sum(case == 0 for case in cases.values()) / len(cases)
    expected_ig = sum({0: 1, 1: 0, 2: -1}[case] for case in cases.values()) / len(cases)
    overall = report['summary'][0]
    if overall['CDNS'] != expected_cdns or overall['IG'] != expected_ig:
        raise AssertionError('模拟整体指标不符合手算值')
    for row in report['sample_scores']:
        case = cases[row['sample_id']]
        if row['CDNS'] != int(case == 0) or row['IG'] != {0: 1, 1: 0, 2: -1}[case]:
            raise AssertionError('模拟逐样本指标不符合手算值')
    by_id = {s['sample_id']: s for s in samples}
    for row in report['domain_sample_scores']:
        case = cases[row['sample_id']]
        first = row['domain'] == by_id[row['sample_id']]['domains'][0]
        expected_dc = 1 if case == 0 else (int(not first) if case == 1 else -int(first))
        if row['DC'] != expected_dc:
            raise AssertionError('模拟逐域贡献不符合手算值')
    result = {'validation_only': True, 'real_model_calls': 0, 'audit': audit,
              'prepared_samples': manifest['sample_count'], 'prepared_requests': len(requests),
              'dry_run': dry_run, 'synthetic_expected': {'CDNS': expected_cdns, 'IG': expected_ig},
              'checks': ['全量双材料映射', '源文件哈希未变', '输入哈希及条件完整性',
                         'dry-run 零调用', '模拟 CDNS/IG/DC 与手算一致'],
              'note': '模拟分数不是 pipeline 质量结果，尚未进行真实模型实验'}
    write_json(root / 'CDNS_validation.json', result)
    return result


def main():
    """执行离线验证 CLI。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=DEFAULT_INPUT)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = validate(args.input, args.output_dir)
    except (ValueError, OSError, AssertionError) as exc:
        parser.exit(2, f'CDNS 验证失败：{exc}\n')
    print(f"CDNS 验证通过：审计 {result['audit']['sample_count']} 样本，"
          f"准备 {result['prepared_samples']} 样本 / {result['prepared_requests']} 请求；真实模型调用 0。")


if __name__ == '__main__':
    main()
