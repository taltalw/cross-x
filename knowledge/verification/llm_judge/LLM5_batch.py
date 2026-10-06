"""一键评估 v5/v6 阶段4结果，复用 LLM5 的两阶段初审与第三位复核。"""

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from LLM5_data import (DEFAULT_ATOMIC, ROOT, AtomicResolver, file_hash, fresh_dir,
                       normalize, read_jsonl, write_json)
from LLM5_run import checked_config, run


def endpoint(base_url):
    """接受 Base URL 或完整聊天接口；不猜测服务商或添加 /v1。"""
    base_url = base_url.strip().rstrip('/')
    return base_url if base_url.endswith('/chat/completions') else base_url + '/chat/completions'


def make_config(dry_run=False):
    """逐角色读取地址和模型，密钥只声明环境变量名；离线预览不读取密钥。"""
    models = (
        ('J1', 'claude-opus-5', 'anthropic'),
        ('J2', 'gemini-3.1-pro', 'google'),
        ('J3', 'deepseek-v4-pro', 'deepseek'),
    )
    judges = {}
    for role, preview_model, default_family in models:
        base_url = os.environ.get(f'{role}_API_BASE_URL', '').strip()
        model = os.environ.get(f'{role}_MODEL', '').strip()
        if not dry_run:
            for name, value in ((f'{role}_API_BASE_URL', base_url), (f'{role}_MODEL', model)):
                if not value:
                    raise ValueError(f'缺少环境变量 {name}；请在终端为每个角色指定地址、密钥和模型')
        judges[role] = {
            'endpoint': endpoint(base_url or f'https://REPLACE_{role}_API_BASE_URL/v1'),
            'model': model or preview_model,
            'family': os.environ.get(f'{role}_FAMILY', default_family),
            'key_env': f'{role}_API_KEY', 'temperature': 0, 'max_tokens': 7000, 'timeout': 180,
        }
        # omit 表示不发送该参数；不是要求模型关闭思考，也不自动回退强度。
        default_effort = 'xhigh' if 'gpt' in judges[role]['model'].lower() else 'max'
        effort = os.environ.get(f'{role}_REASONING_EFFORT', default_effort).strip().lower()
        judges[role]['reasoning_effort'] = None if effort == 'omit' else effort
        if f'{role}_THINKING' in os.environ:
            thinking = os.environ[f'{role}_THINKING'].strip().lower()
            judges[role]['thinking'] = None if thinking == 'omit' else thinking
    return checked_config({
        'judges': judges,
        'audit_fraction': 0.1, 'seed': '20261005', 'max_retries': 2,
    }, smoke=False)


def collect_samples(output_root, atomic_root, domains=None, counts=(2, 3, 4), limit=None):
    """仅收集正式题目 JSONL，复用原子索引和文件摘要，失败即报告物理行。"""
    question_root = output_root / '4_generate_fusion_question'
    if not question_root.is_dir():
        raise ValueError(f'阶段4结果目录不存在：{question_root}')
    selected_domains = domains or sorted(p.name for p in question_root.iterdir() if p.is_dir())
    if not selected_domains:
        raise ValueError(f'未找到领域目录：{question_root}')
    files = [question_root / domain / f'test_domain_count_{count}.jsonl'
             for domain in selected_domains for count in counts]
    for path in files:
        if not path.is_file():
            raise ValueError(f'缺少题目文件：{path}')
    resolver = AtomicResolver(atomic_root)
    samples, sources = [], []
    for path in files:
        sha = file_hash(path)
        selected = 0
        try:
            for line, row in read_jsonl(path):
                try:
                    sample = normalize(row, path, line, resolver, input_sha256=sha)
                except (ValueError, KeyError, TypeError) as exc:
                    raise ValueError(f'{path}:{line}: {exc}') from None
                samples.append(sample)
                selected += 1
                if limit is not None and len(samples) >= limit:
                    break
        except json.JSONDecodeError:
            raise ValueError(f'JSONL 解析失败：{path}；请检查文件内容') from None
        sources.append({'path': str(path), 'sha256': sha, 'selected_samples': selected})
        if limit is not None and len(samples) >= limit:
            break
    if not samples:
        raise ValueError(f'未找到可评估题目：{question_root}')
    return samples, sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='只准备样本和 Prompt，不调用 API')
    parser.add_argument('--versions', nargs='+', choices=('v5', 'v6'), default=['v5', 'v6'])
    parser.add_argument('--v5-root', type=Path,
                        default=Path(os.environ.get('V5_ROOT') or ROOT / 'pipielines_v5/outputs'))
    parser.add_argument('--v6-root', type=Path,
                        default=Path(os.environ.get('V6_ROOT') or ROOT / 'pipielines_v6/outputs'))
    parser.add_argument('--atomic-root', type=Path, default=DEFAULT_ATOMIC)
    parser.add_argument('--domains', nargs='+', help='可选领域筛选，例如 computer_science mathematics')
    parser.add_argument('--domain-counts', nargs='+', type=int, choices=(2, 3, 4), default=[2, 3, 4])
    parser.add_argument('--limit', type=int, help='每个版本最多读取前 N 道题，便于小批量试跑')
    parser.add_argument('--config', type=Path, help='可选高级配置；默认读取 J1/J2/J3_API_BASE_URL、*_MODEL、*_API_KEY')
    parser.add_argument('--output-dir', type=Path, help='新输出目录；默认使用带时间戳的独立目录')
    args = parser.parse_args()
    try:
        if args.limit is not None and args.limit < 1:
            raise ValueError('--limit 必须为正整数')
        for name, values in (('versions', args.versions), ('domains', args.domains),
                             ('domain-counts', args.domain_counts)):
            if values is not None and len(values) != len(set(values)):
                raise ValueError(f'--{name} 不允许重复值')
        if args.domains and any('/' in d or '\\' in d or d in ('.', '..') for d in args.domains):
            raise ValueError('--domains 必须为领域目录名')
        config = (checked_config(json.loads(args.config.read_text(encoding='utf-8')), smoke=False)
                  if args.config else make_config(args.dry_run))
        if not args.dry_run:
            for name in {judge['key_env'] for judge in config['judges'].values()}:
                if not os.environ.get(name, '').strip():
                    raise ValueError(f'缺少环境变量 {name}；请在运行时提供密钥')
        default_output = Path(__file__).resolve().parent / 'LLM5_outputs' / (
            'LLM5_v5_v6_' + ('preview_' if args.dry_run else '') + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
        destination = (args.output_dir or default_output).resolve()
        if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
            raise ValueError('输出目录非空，请指定新的 --output-dir')
        batches = {}
        # 两套数据都完成校验后才开始 API 调用，避免后一个版本输入错误时浪费前序调用。
        for version in args.versions:
            input_root = getattr(args, f'{version}_root').resolve()
            print(f'[{version}] 读取并校验 {input_root}', flush=True)
            samples, sources = collect_samples(input_root, args.atomic_root,
                                               args.domains, args.domain_counts, args.limit)
            batches[version] = samples, sources
            print(f'[{version}] 已准备 {len(samples)} 道题', flush=True)
        fresh_dir(destination)
        write_json(destination / 'LLM5_config.json', config)
        summary = {'status': 'running', 'execute': not args.dry_run,
                   'config_file': str(destination / 'LLM5_config.json'), 'datasets': {}}
        for version, (samples, sources) in batches.items():
            summary['datasets'][version] = {
                'status': 'not_started', 'sample_count': len(samples), 'input_files': sources,
                'run_dir': str(destination / version),
            }
        summary_path = destination / 'LLM5_batch_manifest.json'
        write_json(summary_path, summary)
        print(f'输出目录：{destination}', flush=True)
        for version, (samples, _) in batches.items():
            print(f'[{version}] {"离线预览" if args.dry_run else "开始评审"}；'
                  f'初审 {len(samples) * 4} 个阶段，复核按触发条件及 10% 分层抽查执行', flush=True)
            summary['datasets'][version]['status'] = 'running'
            write_json(summary_path, summary)
            try:
                result = run(samples, config, destination / version, execute=not args.dry_run)
            except Exception:
                summary['status'] = summary['datasets'][version]['status'] = 'failed'
                write_json(summary_path, summary)
                raise
            summary['datasets'][version].update({key: result[key] for key in
                ('status', 'http_post_attempts', 'sample_count')})
            if not args.dry_run:
                summary['datasets'][version]['statistics_dir'] = str(destination / version / 'LLM5_statistics')
            write_json(summary_path, summary)
            print(f'[{version}] 状态：{result["status"]}；API 请求：{result["http_post_attempts"]}', flush=True)
            if not args.dry_run and result['status'] != 'completed':
                summary['status'] = 'incomplete'
                write_json(summary_path, summary)
                print('评审未完整完成，已停止后续版本；请检查该版本的 manifest 和 LLM5_calls。', flush=True)
                return 1
        summary['status'] = 'prepared' if args.dry_run else 'completed'
        write_json(summary_path, summary)
        print(f'批次状态：{summary["status"]}；运行清单：{summary_path}', flush=True)
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f'LLM5 batch failed: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
