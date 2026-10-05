"""LLM5 两阶段初审、规则复核与统计；默认只准备输入，不调用API。"""

import argparse
import copy
import getpass
import json
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from LLM5_aggregate import aggregate, route_samples, write_report
from LLM5_api import APIError, complete, discover_model, valid_endpoint
from LLM5_data import (DEFAULT_ATOMIC, DEFAULT_INPUT, digest, file_hash, fresh_dir,
                       prepare, read_jsonl, write_json, write_jsonl)
from LLM5_prompts import PROMPT_VERSION, build_messages, prompt_hashes
from LLM5_schema import validate_output


def smoke_config():
    """单样本同模型三角色测试配置，不能用于独立质量验证。"""
    judge = {'endpoint': 'https://api.deepseek.com/chat/completions', 'model': 'auto',
             'family': 'deepseek', 'key_env': 'DEEPSEEK_API_KEY', 'temperature': 0,
             'max_tokens': 7000, 'timeout': 180, 'thinking': 'disabled'}
    return {'judges': {role: dict(judge) for role in ('J1', 'J2', 'J3')},
            'audit_fraction': 0.1, 'seed': '20261005', 'max_retries': 2}


def checked_config(raw, smoke):
    """固定配置白名单；密钥值禁止写入配置文件。"""
    if not isinstance(raw, dict) or set(raw) - {'judges', 'audit_fraction', 'seed', 'max_retries'}:
        raise ValueError('配置只允许 judges/audit_fraction/seed/max_retries')
    judges = raw.get('judges')
    if not isinstance(judges, dict) or set(judges) != {'J1', 'J2', 'J3'}:
        raise ValueError('需要配置 J1/J2/J3')
    allowed = {'endpoint', 'model', 'family', 'key_env', 'temperature', 'max_tokens', 'timeout', 'thinking', 'seed'}
    config = copy.deepcopy(raw)
    for role, judge in config['judges'].items():
        if not isinstance(judge, dict) or set(judge) - allowed:
            raise ValueError(f'{role}: 配置含未知字段（请勿存放API密钥）')
        for field in ('endpoint', 'model', 'family', 'key_env'):
            if not isinstance(judge.get(field), str) or not judge[field].strip():
                raise ValueError(f'{role}: 缺少 {field}')
        valid_endpoint(judge['endpoint'])
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', judge['key_env']):
            raise ValueError('key_env 必须为环境变量名，不能填密钥')
        if judge['model'] == 'auto' and not smoke:
            raise ValueError('正式模式需指定模型版本，不能 auto')
        judge.setdefault('temperature', 0)
        judge.setdefault('max_tokens', 7000)
        judge.setdefault('timeout', 180)
        if type(judge['max_tokens']) is not int or not 1 <= judge['max_tokens'] <= 32768:
            raise ValueError('max_tokens 必须在1..32768')
        for field in ('temperature', 'timeout'):
            value = judge[field]
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (field == 'timeout' and value == 0):
                raise ValueError(f'{field} 数值非法')
        if judge.get('thinking') not in (None, 'enabled', 'disabled'):
            raise ValueError('thinking 需要 enabled/disabled')
        if judge.get('seed') is not None and type(judge['seed']) is not int:
            raise ValueError('seed 必须是整数')
    families = {j['family'].strip().lower() for j in config['judges'].values()}
    if not smoke and (len(families) != 3 or families & {'unknown', 'family_unknown', 'replace_me'}):
        raise ValueError('正式模式需要声明三个不同模型家族；同模型只允许 --smoke-one')
    identities = {(j['endpoint'].rstrip('/'), j['model']) for j in config['judges'].values()}
    if not smoke and len(identities) != 3:
        raise ValueError('正式模式不能以不同family标签重复使用同一endpoint/model')
    config.setdefault('audit_fraction', 0.1)
    config.setdefault('seed', '20261005')
    config.setdefault('max_retries', 2)
    if type(config['audit_fraction']) not in (int, float) or not 0 <= config['audit_fraction'] <= 1:
        raise ValueError('audit_fraction 应在0..1')
    if type(config['max_retries']) is not int or not 0 <= config['max_retries'] <= 2:
        raise ValueError('max_retries 应在0..2')
    return config


def parse_json(content):
    """解析单个JSON对象，拒绝重复键、NaN及额外文本。"""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    def reject_constant(_):
        raise ValueError('nonfinite JSON number')
    value = json.loads(content, object_pairs_hook=unique, parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise ValueError('output must be a JSON object')
    return value


class Runner:
    """隔离每个评审会话，保存最终记录和独立尝试日志。"""

    def __init__(self, root, config, keys):
        """密钥仅保留在进程内存，不序列化Runner。"""
        self.root, self.config, self.keys = root, config, keys
        self.records, self.attempt_count = [], 0
        self.terminal_auth_failure = False
        (root / 'LLM5_calls').mkdir()

    def stage(self, sample, judge, stage, **previous):
        """运行一个阶段，失败最多重试两次，修正提示不指定目标分数。"""
        cfg = self.config['judges'][judge]
        base_messages = build_messages(stage, sample, **previous)
        identity = {'sample_id': sample['sample_id'], 'judge_id': judge, 'stage': stage}
        key = self.keys[cfg['key_env']]
        messages = base_messages
        last_error = 'not_started'
        for attempt in range(self.config['max_retries'] + 1):
            self.attempt_count += 1
            prefix = self.root / 'LLM5_calls' / f'LLM5_{sample["sample_id"]}_{judge}_{stage}_{attempt + 1}'
            record = {**identity, 'attempt': attempt + 1, 'request_sha256': digest(messages),
                      'judge_config_sha256': digest(cfg), 'prompt_version': PROMPT_VERSION,
                      'started_at': datetime.now(timezone.utc).isoformat()}
            write_json(str(prefix) + '_request.json', {'messages': messages, 'config': cfg})
            started = time.monotonic()
            retryable = True
            try:
                content, metadata = complete(cfg, messages, key)
                record['response'] = metadata
                record['raw_content'] = content
                value = parse_json(content)
                validate_output(stage, value, sample)
                record.update(status='ok', output=value)
            except APIError as exc:
                last_error = str(exc)
                retryable = exc.retryable
                record.update(status='error', error_type=exc.category, http_status=exc.status)
                if exc.status in (401, 402, 403):
                    self.terminal_auth_failure = True
            except (ValueError, TypeError, KeyError) as exc:
                last_error = str(exc)[:800]
                record.update(status='error', error_type='invalid_judgment', validation_error=last_error)
                messages = base_messages + [{'role': 'user', 'content':
                    'Your previous attempt failed output validation: ' + last_error +
                    '. Return a complete corrected JSON object. Re-check your findings and use authentic quotes. '
                    'Do not change a valid judgment just to pass validation. No target score is prescribed.'}]
            record['elapsed_seconds'] = round(time.monotonic() - started, 3)
            write_json(str(prefix) + '_response.json', record)
            print(f"{judge} {stage}: {record['status']} (attempt {attempt + 1})", flush=True)
            if record['status'] == 'ok' or not retryable:
                break
        final = {k: v for k, v in record.items() if k not in ('raw_content', 'attempt')}
        self.records.append(final)
        write_jsonl(self.root / 'LLM5_records.jsonl', self.records)
        return final.get('output') if final['status'] == 'ok' else None

    def independent(self, sample, judge):
        """先盲审后证据评分，只传递同一评审自己的盲审记录。"""
        first = self.stage(sample, judge, 'blind_structure')
        if first is None:
            return None
        return self.stage(sample, judge, 'evidence_scoring', own_stage1=first)


def run(samples, config, output_dir, execute=False, smoke=False, keys=None):
    """完成批次编排；smoke强制单题并禁止声称独立验证。

    Args:
        samples: 由prepare生成的规范样本列表。
        config: 不含密钥值的三角色配置。
        output_dir: 新目录。
        execute: 是否真的发送API请求。
        smoke: 是否为同模型单题流程测试。
        keys: 可选内存密钥映射，键为配置中的环境变量名。
    """
    config = checked_config(config, smoke)
    if not samples or (smoke and len(samples) != 1):
        raise ValueError('需要非空样本；--smoke-one 必须恰好一个样本')
    if len({s['sample_id'] for s in samples}) != len(samples):
        raise ValueError('重复样本ID')
    for sample in samples:
        value = {k: v for k, v in sample.items() if k != 'content_sha256'}
        if sample.get('content_sha256') != digest(value):
            raise ValueError('规范输入摘要不符')
    root = fresh_dir(output_dir)
    write_jsonl(root / 'LLM5_samples.jsonl', samples)
    write_jsonl(root / 'LLM5_records.jsonl', [])
    manifest = {'mode': 'single_model_smoke' if smoke else 'multi_family_review',
                'smoke': smoke, 'execute': execute,
                'independent_validation': False if smoke else 'declared_not_verified',
                'family_claims': 'operator_declared_not_automatically_verified',
                'generator_family_status': 'unknown', 'config': config,
                'audit_fraction': config['audit_fraction'], 'seed': config['seed'],
                'prompt_version': PROMPT_VERSION, 'prompt_hashes': prompt_hashes(),
                'sample_count': len(samples), 'http_post_attempts': 0, 'model_discovery_requests': 0,
                'sample_file_sha256': file_hash(root / 'LLM5_samples.jsonl'),
                'code_hashes': {p.name: file_hash(p) for p in Path(__file__).parent.glob('LLM5_*.py')},
                'status': 'prepared', 'created_at': datetime.now(timezone.utc).isoformat()}
    write_json(root / 'LLM5_run_manifest.json', manifest)
    if not execute:
        write_jsonl(root / 'LLM5_stage1_preview.jsonl',
                    [{'sample_id': s['sample_id'], 'messages': build_messages('blind_structure', s)} for s in samples])
        return manifest
    key_map = dict(keys or {})
    for judge in config['judges'].values():
        name = judge['key_env']
        if not key_map.get(name):
            key_map[name] = os.environ.get(name)
        if not isinstance(key_map.get(name), str) or not key_map[name].strip():
            raise ValueError(f'缺少环境变量 {name}；密钥不要写进配置')
    resolved = {}
    try:
        for judge in config['judges'].values():
            if judge['model'] == 'auto':
                identity = (judge['endpoint'], judge['key_env'])
                if identity not in resolved:
                    manifest['model_discovery_requests'] += 1
                    resolved[identity] = discover_model(judge['endpoint'], key_map[judge['key_env']])
                judge['model'], available = resolved[identity]
                manifest['available_models'] = available
    except APIError as exc:
        manifest.update(status='api_blocked', error=str(exc))
        write_json(root / 'LLM5_run_manifest.json', manifest)
        return manifest
    manifest.update(config=config, status='running')
    write_json(root / 'LLM5_run_manifest.json', manifest)
    runner = Runner(root, config, key_map)
    initial = {}
    for sample in samples:
        for judge in ('J1', 'J2'):
            initial[(sample['sample_id'], judge)] = runner.independent(sample, judge)
            if runner.terminal_auth_failure:
                break
        if runner.terminal_auth_failure:
            break
    routes = route_samples(samples, runner.records, config['audit_fraction'], config['seed'], force_review=smoke)
    write_json(root / 'LLM5_review_selection.json', routes)
    candidates = [r for r in routes if r['needs_review']]
    # 按种子稳定排序后交替映射，整个复核集合的 P/Q 数量差不超过1。
    candidates.sort(key=lambda r: digest([config['seed'], r['sample_id']]))
    by_id = {s['sample_id']: s for s in samples}
    mappings = []
    if not runner.terminal_auth_failure:
        for index, route in enumerate(candidates):
            if runner.terminal_auth_failure:
                break
            sample = by_id[route['sample_id']]
            independent = runner.independent(sample, 'J3')
            if independent is None:
                continue
            order = ('J1', 'J2') if index % 2 == 0 else ('J2', 'J1')
            reviews = {label: initial[(sample['sample_id'], judge)] for label, judge in zip(('P', 'Q'), order)}
            mappings.append({'sample_id': sample['sample_id'], 'P': order[0], 'Q': order[1]})
            runner.stage(sample, 'J3', 'adjudication', own_stage2=independent, reviews=reviews)
    write_json(root / 'LLM5_anonymous_mapping.json', mappings)
    report = aggregate(samples, runner.records, config['audit_fraction'], config['seed'], smoke=smoke)
    write_report(report, root / 'LLM5_statistics')
    successful = sum(r['status'] == 'ok' for r in runner.records)
    expected = len(samples) * 4 + len(candidates) * 3
    manifest.update(http_post_attempts=runner.attempt_count, successful_stages=successful,
                    expected_stages=expected, status='completed' if successful == expected else 'incomplete',
                    records_sha256=file_hash(root / 'LLM5_records.jsonl'),
                    human_review_count=sum(r['status'] == 'pending_human' for r in report['routes']))
    write_json(root / 'LLM5_run_manifest.json', manifest)
    return manifest


def main():
    """CLI 默认准备一个真实三域样本；--execute 才请求模型。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=DEFAULT_INPUT)
    parser.add_argument('--line', type=int, default=1)
    parser.add_argument('--atomic-root', type=Path, default=DEFAULT_ATOMIC)
    parser.add_argument('--samples-file', type=Path, help='已经准备且带摘要的规范JSONL，正式批次入口')
    parser.add_argument('--config', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--smoke-one', action='store_true', help='仅1题同家族三角色流程测试，强制复核')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--prompt-key', action='store_true', help='仅烟测时从隐藏交互输入读取密钥')
    args = parser.parse_args()
    try:
        if not args.config and not args.smoke_one:
            raise ValueError('正式模式需 --config；单题流程测试使用 --smoke-one')
        config = json.loads(args.config.read_text(encoding='utf-8')) if args.config else smoke_config()
        samples = [r for _, r in read_jsonl(args.samples_file)] if args.samples_file else [prepare(args.input, args.line, args.atomic_root)]
        keys = None
        if args.prompt_key:
            if not args.smoke_one or not args.execute:
                raise ValueError('--prompt-key 只允许 --smoke-one --execute')
            names = {j['key_env'] for j in config['judges'].values()}
            if len(names) != 1:
                raise ValueError('交互烟测仅支持一个密钥变量')
            keys = {next(iter(names)): getpass.getpass('DeepSeek API key (hidden): ')}
        result = run(samples, config, args.output_dir, args.execute, args.smoke_one, keys)
    except (ValueError, OSError, APIError, KeyError) as exc:
        parser.exit(2, f'LLM5 failed: {exc}\n')
    print(json.dumps({key: result.get(key) for key in ('status', 'sample_count', 'mode', 'http_post_attempts',
                                                     'model_discovery_requests', 'successful_stages', 'human_review_count')}, indent=2))
    if args.execute and result['status'] != 'completed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
