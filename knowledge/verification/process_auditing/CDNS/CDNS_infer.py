"""CDNS 固定模型推理入口；默认只预览，--execute 才发送请求。"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from CDNS_data import digest, load_bundle


def parse_answer(text, labels):
    """严格解析单个标签或 JSON answer，避免从推理文字中猜选项。"""
    if not isinstance(text, str):
        raise ValueError('响应内容不是文本')
    value = text.strip()
    if value in [*labels, 'ABSTAIN']:
        return value
    fenced = re.fullmatch(r'```(?:json)?\s*\n?(.*?)\n?```', value, re.DOTALL)
    if fenced:
        value = fenced.group(1).strip()
    try:
        obj = json.loads(value)
    except ValueError as exc:
        raise ValueError('响应不是单个选项或 JSON answer') from exc
    if not isinstance(obj, dict) or not isinstance(obj.get('answer'), str):
        raise ValueError('响应缺少 answer 字符串')
    answer = obj['answer'].strip()
    if answer not in [*labels, 'ABSTAIN']:
        raise ValueError('响应选项不合法')
    return answer


def http_completion(endpoint, payload, api_key, timeout):
    """POST 标准聊天 messages JSON，仅返回助手文本与终止原因。

    Args:
        endpoint: 完整聊天接口 URL，如本地服务的 /v1/chat/completions。
        payload: model/messages/temperature/max_tokens 等请求参数。
        api_key: 可选鉴权字符串，不写入输出。
        timeout: 单次请求秒数。
    """
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    request = urllib.request.Request(endpoint, data=json.dumps(payload).encode('utf-8'),
                                     headers=headers, method='POST')
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.load(response)
    choice = body['choices'][0]
    return choice['message']['content'], choice.get('finish_reason')


def run_inference(input_dir, output, endpoint=None, model=None, execute=False,
                  temperature=0.0, max_tokens=256, timeout=120.0, seed=None,
                  api_key_env='CDNS_API_KEY'):
    """固定配置逐请求推理；dry-run 不读取密钥、不访问网络、不写预测。

    Returns:
        预览数量或完成状态统计；失败记录保留但不会作为错误答案评分。
    """
    _, _, requests, _ = load_bundle(input_dir)
    if not execute:
        return {'mode': 'dry_run', 'requests': len(requests), 'real_model_calls': 0}
    parsed = urllib.parse.urlsplit(endpoint or '')
    if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('需要不含凭据、查询串或 fragment 的完整 HTTP(S) endpoint')
    if not isinstance(model, str) or not model.strip():
        raise ValueError('--execute 需要 --model')
    if type(max_tokens) is not int or max_tokens < 1:
        raise ValueError('max_tokens 必须为正整数')
    if type(temperature) not in (int, float) or not math.isfinite(temperature) or temperature < 0:
        raise ValueError('temperature 必须为非负有限数')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('timeout 必须为正有限数')
    config = {'endpoint': endpoint, 'model': model, 'temperature': temperature,
              'max_tokens': max_tokens, 'seed': seed}
    inference_id = digest(config)
    api_key = os.environ.get(api_key_env)
    if output is None:
        raise ValueError('--execute 需要 --output')
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    counts = {'ok': 0, 'invalid_format': 0, 'error': 0}
    with output.open('x', encoding='utf-8') as stream:
        for request in requests:
            record = {key: request[key] for key in ('request_id', 'prompt_sha256')}
            record.update({'inference_id': inference_id, 'inference_config': config,
                           'simulation': False})
            payload = {'model': model, 'messages': request['messages'],
                       'temperature': temperature, 'max_tokens': max_tokens}
            if seed is not None:
                payload['seed'] = seed
            try:
                content, finish = http_completion(endpoint, payload, api_key, timeout)
                if finish != 'stop':
                    record.update(status='error', error_type='incomplete_response')
                else:
                    try:
                        answer = parse_answer(content, request['option_labels'])
                        record.update(status='ok', answer=answer, raw_response=content)
                    except ValueError:
                        record.update(status='invalid_format', raw_response=content)
            except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError, TypeError) as exc:
                # 不保存服务端错误正文或异常字符串，避免带入鉴权信息。
                record.update(status='error', error_type=type(exc).__name__)
            counts[record['status']] += 1
            stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n')
            stream.flush()
    return {'mode': 'execute', 'requests': len(requests), 'statuses': counts,
            'inference_id': inference_id, 'output': str(output)}


def main():
    """运行默认不联网的命令行入口。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--endpoint', help='完整聊天 URL；仅 --execute 时使用')
    parser.add_argument('--model')
    parser.add_argument('--execute', action='store_true', help='显式发送真实模型请求')
    parser.add_argument('--temperature', type=float, default=0.0)
    parser.add_argument('--max-tokens', type=int, default=256)
    parser.add_argument('--timeout', type=float, default=120.0)
    parser.add_argument('--seed', type=int)
    parser.add_argument('--api-key-env', default='CDNS_API_KEY')
    args = parser.parse_args()
    try:
        result = run_inference(**vars(args))
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, f'CDNS 推理入口失败：{exc}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
