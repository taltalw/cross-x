"""Execute the original v4 entrypoints with ordered parallel row processing.

Prompts, validators and transformations are imported from the repository.
Only explicitly filtered/refused provider responses are recorded and skipped.
Validated responses and complete per-input results are checkpointed for resume.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed, CancelledError
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import time
import urllib.error
import urllib.request

RUNTIME = Path(__file__).resolve().parent
ROOT = RUNTIME.parent
V4 = ROOT.parent
REPO = V4.parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(V4))
from knowledge.pipelines._knowledge_search_common import APIError, JSONAPI, read_rows, write_row

LOCAL = threading.local()
LOCK = threading.Lock()
SUPPORTED = {'0_extract_key_facts', '1_generate_fusion_plans',
             '2_extract_required_key_facts', '4_generate_fusion_question'}


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False) + '\n')
    temporary.replace(path)


def append(path, value):
    with LOCK:
        with path.open('a') as stream:
            write_row(stream, value)


def clean(value):
    return str(value).replace(os.environ.get('API_KEY') or '\0', '[redacted]')


class ProviderRejected(Exception):
    pass


def explicit_filter(body):
    text = json.dumps(body, ensure_ascii=False).lower()
    return any(marker in text for marker in ('content_filter', 'contentfilter',
               'responsibleaipolicyviolation', 'content management policy'))


class AuditedAPI(JSONAPI):
    def chat(self, system, data, validate, max_tokens):
        context = LOCAL.context
        identity = {'model': self.model, 'api_base_url': self.base_url,
                    'system': system, 'data': data, 'max_tokens': max_tokens,
                    'temperature': self.temperature, 'reasoning_effort': self.reasoning_effort}
        cache_key = digest(identity)
        cache_file = RUNTIME / 'responses' / context['job_id'] / (cache_key + '.json')
        event = {key: context[key] for key in ('job_id', 'input_file', 'input_line', 'input_sha256')}
        event.update(request_sha256=cache_key, requested_model=self.model,
                     url=self.base_url + '/chat/completions', difficulty=data.get('difficulty'))
        if cache_file.exists():
            cached = json.loads(cache_file.read_text())
            if cached['identity_sha256'] != cache_key:
                raise APIError('Response cache identity mismatch')
            value = validate(cached['value'])
            if 'feasible' in value:
                context['screening'] = value
            append(ROOT / 'request_audit.jsonl', {**event, 'event': 'cache_hit', 'time': now()})
            return value
        limit = max_tokens
        attempts = max(self.retries + 1, 5)
        error = 'request failed'
        feedback = None
        previous_content = None
        for attempt in range(attempts):
            payload = {'model': self.model, 'temperature': self.temperature,
                       'messages': [{'role': 'system', 'content': system},
                                    {'role': 'user', 'content': json.dumps(data, ensure_ascii=False)}],
                       'max_tokens': limit, 'response_format': {'type': 'json_object'}}
            if feedback:
                if isinstance(previous_content, str):
                    payload['messages'].append({'role': 'assistant', 'content': previous_content})
                payload['messages'].append({'role': 'user', 'content': feedback})
            if self.reasoning_effort:
                payload['reasoning_effort'] = self.reasoning_effort
            request = urllib.request.Request(event['url'], data=json.dumps(payload, ensure_ascii=False).encode(),
                      headers={'Authorization': 'Bearer ' + self.api_key, 'Content-Type': 'application/json'})
            started = time.monotonic()
            body = None
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = json.load(response)
                observed = body.get('model')
                choice = body.get('choices', [{}])[0]
                message = choice.get('message') or {}
                append(ROOT / 'request_audit.jsonl', {**event, 'event': 'response', 'time': now(),
                       'response_model': observed, 'status': 200, 'attempt': attempt + 1,
                       'validation_feedback_used': bool(feedback),
                       'max_tokens': limit, 'finish_reason': choice.get('finish_reason'),
                       'elapsed_seconds': round(time.monotonic() - started, 3), 'usage': body.get('usage')})
                if observed != self.model:
                    raise APIError('Unexpected response model: ' + str(observed))
                if choice.get('finish_reason') == 'content_filter':
                    raise ProviderRejected('Provider returned finish_reason=content_filter')
                refusal = message.get('refusal') or (message.get('provider_specific_fields') or {}).get('refusal')
                if refusal:
                    raise ProviderRejected('Provider refusal: ' + clean(refusal))
                if choice.get('finish_reason') == 'length':
                    limit = min(8192, max(limit * 2, 1024))
                    raise ValueError('Output token limit reached; retry with increased limit')
                value = validate(json.loads(message['content']))
                save(cache_file, {'identity_sha256': cache_key, 'value': value,
                                 'response_model': observed, 'created_at': now(),
                                 'validation_feedback_used': bool(feedback)})
                if 'feasible' in value:
                    context['screening'] = value
                append(ROOT / 'request_audit.jsonl', {**event, 'event': 'validated', 'time': now()})
                return value
            except urllib.error.HTTPError as exc:
                try:
                    raw = exc.read().decode('utf-8', errors='replace')
                    try:
                        body = json.loads(raw)
                    except ValueError:
                        body = {'message': raw[:1000]}
                finally:
                    exc.close()
                error = 'HTTP ' + str(exc.code) + ': ' + clean(json.dumps(body, ensure_ascii=False))[:1200]
                append(ROOT / 'request_audit.jsonl', {**event, 'event': 'http_error', 'status': exc.code,
                       'reason': error, 'time': now(), 'attempt': attempt + 1})
                if exc.code == 400 and explicit_filter(body):
                    raise ProviderRejected(error) from None
                if exc.code not in (408, 409, 429) and exc.code < 500:
                    raise APIError(error) from None
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                error = clean(exc)
                append(ROOT / 'request_audit.jsonl', {**event, 'event': 'transport_error',
                       'reason': error, 'time': now(), 'attempt': attempt + 1})
            except (ValueError, KeyError, TypeError, IndexError) as exc:
                error = clean(exc)
                if isinstance(body, dict):
                    save(RUNTIME / 'invalid_responses' / context['job_id'] /
                         f'{context["input_line"]:06d}_{time.time_ns()}.json',
                         {'request_sha256': cache_key, 'validation_error': error, 'response': body})
                    choice = body.get('choices', [{}])[0]
                    if choice.get('finish_reason') != 'length':
                        previous_content = (choice.get('message') or {}).get('content')
                        feedback = ('Return a corrected JSON object satisfying the original instructions. '
                                    'The previous response failed validation: ' + error + '. '
                                    'For sample references, copy prompt and completion exactly from a supplied '
                                    'sample. Do not paraphrase, normalize whitespace, or change punctuation.')
                append(ROOT / 'request_audit.jsonl', {**event, 'event': 'validation_error',
                       'reason': error, 'time': now(), 'attempt': attempt + 1})
            if attempt + 1 < attempts:
                time.sleep(min(2 ** attempt, 16))
        raise APIError(f'{error} after {attempts} attempts')


def parallel_process(module, original, input_file, output_file, **kwargs):
    api = kwargs['api']
    job_id = '__'.join(output_file.resolve().relative_to(ROOT).with_suffix('').parts)
    job_dir = RUNTIME / 'rows' / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    rows = list(read_rows(input_file))
    if kwargs.get('num') is not None:
        rows = rows[:kwargs['num']]
    if output_file.resolve() == input_file.resolve():
        raise ValueError('Input and output paths must differ')
    if output_file.exists() and not kwargs.get('overwrite'):
        raise FileExistsError(output_file)
    settings = {key: value for key, value in kwargs.items() if key not in ('api', 'overwrite')}
    settings.update(model=api.model, api_base_url=api.base_url, temperature=api.temperature,
                    reasoning_effort=api.reasoning_effort,
                    source_sha256=json.loads((ROOT / 'run_manifest.json').read_text())['source_sha256'])
    settings_sha = digest(settings)
    original_reader = module.read_rows
    def single_reader(path):
        if hasattr(LOCAL, 'single_row'):
            if Path(path).resolve() != input_file.resolve():
                raise ValueError('Unexpected input read inside row worker')
            yield LOCAL.single_row
        else:
            yield from original_reader(path)
    module.read_rows = single_reader
    module.print = lambda *args, **kw: None
    stopped = threading.Event()
    workers = int(os.environ.get('V4_API_WORKERS', '16'))
    if workers < 1:
        raise ValueError('V4_API_WORKERS must be positive')
    status_path = RUNTIME / 'jobs' / (job_id + '.json')
    status = {'job_id': job_id, 'stage': module.__name__, 'status': 'running',
              'input': str(input_file.resolve()), 'output': str(output_file.resolve()),
              'eligible': len(rows), 'completed': 0, 'generated': 0,
              'provider_rejected': 0, 'screened_out': 0, 'failed': 0, 'started_at': now()}
    save(status_path, status)
    print(f'START {job_id}: {len(rows)} inputs, {workers} workers', flush=True)

    def worker(item):
        number, row = item
        if stopped.is_set():
            raise CancelledError()
        path = job_dir / f'{number:06d}.json'
        context = {'job_id': job_id, 'input_file': str(input_file.resolve()),
                   'input_line': number, 'input_sha256': digest(row), 'settings_sha256': settings_sha}
        if path.exists():
            cached = json.loads(path.read_text())
            if any(cached[key] != value for key, value in context.items()):
                stopped.set()
                raise ValueError('Checkpoint identity mismatch: ' + str(path))
            if cached['status'] in ('completed', 'provider_rejected', 'screened_out'):
                if cached['output_sha256'] != digest(cached['rows']):
                    raise ValueError('Checkpoint output hash mismatch: ' + str(path))
                return cached
        LOCAL.context = context
        LOCAL.single_row = item
        temporary = job_dir / f'{number:06d}.jsonl.part'
        local_kwargs = {**kwargs, 'overwrite': True}
        if 'num' in local_kwargs:
            local_kwargs['num'] = None
        try:
            report = original(input_file, temporary, **local_kwargs)
            output_rows = [value for _, value in read_rows(temporary)]
            outcome = 'screened_out' if report.get('skipped') else 'completed'
            record = {**context, 'status': outcome, 'rows': output_rows, 'report': report,
                      'screening': context.get('screening'), 'completed_at': now(),
                      'output_sha256': digest(output_rows)}
        except ProviderRejected as exc:
            record = {**context, 'status': 'provider_rejected', 'reason': clean(exc),
                      'sample': row, 'rows': [], 'output_sha256': digest([]),
                      'model': api.model, 'api_base_url': api.base_url, 'completed_at': now()}
            append(ROOT / 'rejected_samples.jsonl', record)
        except Exception as exc:
            stopped.set()
            save(path, {**context, 'status': 'failed', 'reason': clean(exc), 'failed_at': now()})
            raise
        save(path, record)
        if temporary.exists():
            temporary.unlink()
        return record

    output_file.parent.mkdir(parents=True, exist_ok=True)
    errors = []
    ready = {}
    next_index = 0
    with output_file.open('w' if kwargs.get('overwrite') else 'x') as output:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(worker, row): index for index, row in enumerate(rows)}
            for future in as_completed(futures):
                try:
                    record = future.result()
                    ready[futures[future]] = record
                    status['completed'] += 1
                    status['generated'] += len(record['rows'])
                    if record['status'] in ('provider_rejected', 'screened_out'):
                        status[record['status']] += 1
                    while next_index in ready:
                        for row in ready.pop(next_index)['rows']:
                            write_row(output, row)
                        next_index += 1
                    if status['completed'] % 10 == 0 or status['completed'] == len(rows):
                        print(f'PROGRESS {job_id}: {status["completed"]}/{len(rows)} inputs; '
                              f'{status["generated"]} outputs; {status["provider_rejected"]} rejected; '
                              f'{status["screened_out"]} screened out', flush=True)
                except CancelledError:
                    continue
                except Exception as exc:
                    stopped.set()
                    errors.append(clean(exc))
                    status['failed'] += 1
                    print(f'FAILED {job_id}: {clean(exc)}', flush=True)
                status['updated_at'] = now()
                save(status_path, status)
    status['status'] = 'failed' if errors else 'completed'
    status['errors'] = errors
    status['output_sha256'] = hashlib.sha256(output_file.read_bytes()).hexdigest()
    status['finished_at'] = now()
    save(status_path, status)
    if errors:
        raise APIError(errors[0])
    return status


def main():
    arguments = sys.argv[1:]
    append(RUNTIME / 'commands.jsonl', {'time': now(), 'argv': arguments})
    if not arguments or Path(arguments[0]).stem not in SUPPORTED:
        os.execv(sys.executable, [sys.executable, *arguments])
    path = Path(arguments[0]).resolve()
    if path.parent != V4:
        raise ValueError('Unexpected pipeline module path')
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    name = 'run_extraction' if path.stem.startswith('0_') else 'process'
    original = getattr(module, name)
    setattr(module, name, lambda input_file, output_file, **kwargs:
            parallel_process(module, original, input_file, output_file, **kwargs))
    module.JSONAPI = AuditedAPI
    sys.argv = arguments
    return module.main()


if __name__ == '__main__':
    raise SystemExit(main())
