"""不记录密钥的标准库聊天API客户端，错误正文不落盘。"""

import json
import re
import urllib.error
import urllib.parse
import urllib.request


class APIError(RuntimeError):
    """仅保留安全错误类别与HTTP状态。"""

    def __init__(self, category, status=None, retryable=False):
        """建立不包含服务响应正文的错误。"""
        self.category, self.status, self.retryable = category, status, retryable
        super().__init__(f'{category}' + (f' (HTTP {status})' if status else ''))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """禁止携带鉴权的请求跟随重定向。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """遇到重定向立即报错，避免跨目标发送密钥。"""
        raise APIError('redirect_refused', code)


def valid_endpoint(endpoint):
    """拒绝URL内凭据与不安全远程HTTP。"""
    parsed = urllib.parse.urlsplit(endpoint)
    local = parsed.hostname in ('localhost', '127.0.0.1', '::1')
    if (parsed.scheme not in ('http', 'https') or not parsed.netloc or
            (parsed.scheme == 'http' and not local) or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
        raise ValueError('endpoint 必须为无凭据的HTTPS URL（本地服务允许HTTP）')
    return endpoint


def redact(value, secret):
    """防止服务返回或异常内容偶然包含凭据。"""
    if isinstance(value, str):
        if secret:
            value = value.replace(secret, '[REDACTED]')
        return re.sub(r'\bsk-[A-Za-z0-9_-]{12,}\b', '[REDACTED]', value)
    if isinstance(value, list):
        return [redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {redact(k, secret): redact(v, secret) for k, v in value.items()}
    return value


def request_json(url, api_key, payload=None, timeout=180):
    """发送单次鉴权请求；禁止记录鉴权头与服务错误正文。"""
    valid_endpoint(url)
    headers = {'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json'}
    data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, headers=headers,
                                     method='POST' if payload is not None else 'GET')
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            value = json.load(response)
    except urllib.error.HTTPError as exc:
        raise APIError('http_error', exc.code, exc.code == 429 or exc.code >= 500) from None
    except (urllib.error.URLError, OSError, TimeoutError):
        raise APIError('connection_error', retryable=True) from None
    except (ValueError, UnicodeError):
        raise APIError('invalid_response_json', retryable=True) from None
    return redact(value, api_key)


def discover_model(endpoint, api_key, timeout=60):
    """只在单样本烟测使用官方模型列表，返回真实可用模型名。"""
    parsed = urllib.parse.urlsplit(endpoint)
    if parsed.netloc != 'api.deepseek.com' or parsed.scheme != 'https':
        raise ValueError('auto 模型发现仅用于 DeepSeek 官方endpoint')
    result = request_json('https://api.deepseek.com/models', api_key, timeout=timeout)
    available = [entry.get('id') for entry in result.get('data', []) if isinstance(entry, dict)]
    for name in ('deepseek-flash', 'deepseek-v4-flash', 'deepseek-chat', 'deepseek-v4-pro'):
        if name in available:
            return name, available
    raise APIError('no_supported_model')


def complete(config, messages, api_key):
    """请求结构化评审，仅保存最终可见content及复现元数据。

    Returns:
        (content, metadata)，不返回内部推理内容或HTTP鉴权信息。
    """
    payload = {'model': config['model'], 'messages': messages,
               'temperature': config.get('temperature', 0),
               'max_tokens': config.get('max_tokens', 7000), 'stream': False,
               'response_format': {'type': 'json_object'}}
    if config.get('thinking') is not None:
        payload['thinking'] = {'type': config['thinking']}
    default_effort = 'xhigh' if 'gpt' in str(config.get('model', '')).lower() else 'max'
    if config.get('reasoning_effort', default_effort) is not None:
        payload['reasoning_effort'] = config.get('reasoning_effort', default_effort)
    if config.get('seed') is not None:
        payload['seed'] = config['seed']
    body = request_json(config['endpoint'], api_key, payload, config.get('timeout', 180))
    try:
        choice = body['choices'][0]
        content = choice['message']['content']
        if choice.get('finish_reason') != 'stop' or not isinstance(content, str) or not content.strip():
            raise APIError('incomplete_response', retryable=True)
        return content, {key: body.get(key) for key in ('id', 'model', 'system_fingerprint', 'usage')}
    except (KeyError, TypeError, IndexError):
        raise APIError('invalid_response_shape', retryable=True) from None
