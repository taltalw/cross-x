"""Read-only progress report for the v4 execution."""
from collections import Counter
import datetime
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
manifest_path = ROOT / 'run_manifest.json'
manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {'status': 'preparing'}
stages = {}
active = []
for name in ('0_extract_key_facts', '1_generate_fusion_plans', '2_extract_required_key_facts',
             '3_retrieve_key_fact_matches', '4_generate_fusion_question'):
    counts = Counter()
    for path in (ROOT / name).glob('*/*.jsonl'):
        with path.open() as stream:
            counts['output_rows'] += sum(bool(line.strip()) for line in stream)
        counts['output_files'] += 1
    for path in (ROOT / '_runtime/jobs').glob(name + '__*.json'):
        job = json.loads(path.read_text())
        for key in ('eligible', 'completed', 'generated', 'provider_rejected', 'screened_out', 'failed'):
            counts[key] += job.get(key, 0)
        counts['jobs_' + job['status']] += 1
        if job['status'] != 'completed':
            active.append({k: job.get(k) for k in ('job_id', 'status', 'eligible', 'completed', 'errors')})
    stages[name] = dict(counts)
events = Counter()
models = Counter()
last_errors = []
audit_path = ROOT / 'request_audit.jsonl'
if audit_path.exists():
    with audit_path.open() as stream:
        for line in stream:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            events[record['event']] += 1
            if record['event'] == 'response':
                models[record.get('response_model')] += 1
            if record['event'] in ('http_error', 'transport_error', 'validation_error'):
                last_errors = (last_errors + [{k: record.get(k) for k in ('event', 'job_id', 'input_line', 'reason', 'time')}])[-3:]
embedding = {}
database = ROOT.parents[1] / 'embeddings/v4-test-Qwen3-Embedding-8B/vectors.sqlite3'
if database.exists():
    try:
        with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True, timeout=1) as connection:
            for table in ('corpora', 'documents', 'vectors', 'queries'):
                embedding[table] = connection.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
    except sqlite3.Error as exc:
        embedding['status'] = str(exc)
print(json.dumps({'status': manifest['status'], 'stages': stages, 'active_jobs': active,
                  'embedding': embedding,
                  'api_events': dict(events), 'response_models': dict(models), 'last_errors': last_errors,
                  'time': datetime.datetime.now(datetime.timezone.utc).isoformat()}, ensure_ascii=False))
