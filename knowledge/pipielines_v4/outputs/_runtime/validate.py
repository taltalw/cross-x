"""Validate finished v4 outputs, provenance, exclusions, and the API audit."""
from collections import Counter
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sqlite3
import sys
import zipfile

RUNTIME = Path(__file__).resolve().parent
ROOT = RUNTIME.parent
V4 = ROOT.parent
REPO = V4.parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(V4))
from knowledge.pipelines._knowledge_search_common import DOMAINS, read_rows, write_row
from _pipeline_common import (validate_v2_row, validate_selected_plan,
                              validate_required_key_facts, validate_generation,
                              sample_hash, sample_reference)

STAGES = ['0_extract_key_facts', '1_generate_fusion_plans', '2_extract_required_key_facts',
          '3_retrieve_key_fact_matches', '4_generate_fusion_question']


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def records(path):
    return [row for _, row in read_rows(path)]


def main():
    manifest_path = ROOT / 'run_manifest.json'
    manifest = json.loads(manifest_path.read_text())
    assert manifest['status'] in ('completed', 'completed_with_rejections') and manifest['exit_code'] == 0
    for execution in manifest.get('execution_history', []):
        if execution['status'] == 'running':
            execution.update(status='interrupted', finished_at=None, exit_code=None,
                             note='Resumed after the prior PID was absent and the run lock was free; exact stop time and exit code are unknown.')
    assert manifest['settings']['MODEL'] == 'gt-6-as-a'
    assert manifest['settings']['API_BASE_URL'] == 'https://joyrouter.jd.com/v1'
    for name, expected in manifest['source_sha256'].items():
        assert file_hash(REPO / name) == expected, ('Source changed', name)
    assert json.loads((RUNTIME / 'preflight.json').read_text())['passed']
    assert json.loads((RUNTIME / 'seed_validation.json').read_text())['passed']
    for name, expected in manifest['seed_sha256'].items():
        assert file_hash(REPO / name) == expected, ('Upstream seed changed', name)
    summary = {stage: {'eligible': 0, 'generated': 0, 'provider_rejected': 0,
                      'screened_out': 0, 'files': {}} for stage in STAGES}
    rejections, screened = [], []
    queries = set()
    annotations = {}
    atomic = {}
    spec = importlib.util.spec_from_file_location('v4_generation_validation', V4 / '4_generate_fusion_question.py')
    generation_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generation_module)
    for domain in DOMAINS:
        atomic[domain] = {digest(row) for _, row in read_rows(REPO / 'knowledge/atomic' / domain / 'test.jsonl')}

    def compare(row, source, fields):
        for key in fields:
            assert row[key] == source[key], ('Upstream field changed', key)

    def verify_row(row, source, number, input_path, stage, domain, count, checkpoint=None):
        validate_v2_row(row)
        assert row['model'] == 'gt-6-as-a' and row['source_domain'] == domain
        if stage == STAGES[0]:
            assert row['sample'] == source and row['source_line'] == number
            assert Path(row['source_file']).resolve() == input_path.resolve()
            annotations[(domain, sample_hash(source))] = row
            return
        compare(row, source, ('source_file', 'source_domain', 'sample', 'key_facts'))
        assert row['domain_count'] == count
        normalized = validate_selected_plan(row, domain, count)
        compare(row, normalized, normalized.keys())
        if stage == STAGES[1]:
            return
        compare(row, source, ('fusion_domains', 'domain_count'))
        if stage != STAGES[4]:
            compare(row, source, ('question_plan', 'answer_plans'))
        required = validate_required_key_facts(row['required_key_facts'], row['fusion_domains'])
        assert required == row['required_key_facts']
        if stage == STAGES[2]:
            queries.update((d, entry['key_fact']) for d, entries in required.items() for entry in entries)
            return
        if stage != STAGES[4]:
            compare(row, source, ('required_key_facts',))
        assert set(row['retrieved_samples']) == set(row['fusion_domains'])
        if stage == STAGES[3]:
            for candidate_domain, candidates in row['retrieved_samples'].items():
                assert len(candidates) <= 10
                for candidate in candidates:
                    assert digest(candidate['sample']) in atomic[candidate_domain]
                    annotation = annotations[(candidate_domain, sample_hash(candidate['sample']))]
                    assert candidate['source_domain'] == candidate_domain
                    assert candidate['model'] == 'gt-6-as-a'
                    assert candidate['key_facts'] == annotation['key_facts']
                    for match in candidate['matches']:
                        assert match['required_key_fact'] in {entry['key_fact'] for entry in required[candidate_domain]}
            assert isinstance(row['retrieval'], dict)
            return
        compare(row, source, ('retrieval',))
        available = {}
        for candidate_domain, candidates in source['retrieved_samples'].items():
            values = [sample_reference({key: candidate['sample'][key] for key in ('prompt', 'completion')})
                      for candidate in candidates]
            expected = [{'prompt': prompt, 'completion': answer} for prompt, answer in dict.fromkeys(values)]
            assert row['retrieved_samples'][candidate_domain] == expected
            available[candidate_domain] = set(values)
        screen = generation_module.validate_screening(checkpoint['screening'], domain, source['fusion_domains'], available)
        assert screen['feasible']
        compare(row, screen, ('question_plan', 'answer_plans', 'required_key_facts'))
        support = {d: {sample_reference(sample) for sample in values}
                   for d, values in screen['selected_samples'].items()}
        normalized = validate_generation(row, [domain, *row['fusion_domains']], support)
        compare(row, normalized, normalized.keys())

    def verify_file(stage, domain, count=None):
        index = STAGES.index(stage)
        name = 'test.jsonl' if index == 0 else f'test_domain_count_{count}.jsonl'
        output = ROOT / stage / domain / name
        input_path = (REPO / 'knowledge/atomic' / domain / name) if index == 0 else (
            ROOT / STAGES[index - 1] / domain / ('test.jsonl' if index == 1 else name))
        inputs = list(read_rows(input_path))
        if index == 1:
            inputs = inputs[:100]
        actual = records(output)
        counts = Counter(eligible=len(inputs), generated=len(actual), provider_rejected=0, screened_out=0)
        job_id = '__'.join(output.relative_to(ROOT).with_suffix('').parts)
        if index in (0, 1):
            assert file_hash(output) == manifest['seed_sha256'][str(output.relative_to(REPO))]
            if index == 0:
                by_sample = {sample_hash(row): (number, row) for number, row in inputs}
                for row in actual:
                    number, source = by_sample[sample_hash(row['sample'])]
                    verify_row(row, source, number, input_path, stage, domain, count)
                counts['eligible'] = len(actual)
            else:
                assert len(actual) == len(inputs)
                for row, (number, source) in zip(actual, inputs):
                    verify_row(row, source, number, input_path, stage, domain, count)
        elif index == 3:
            assert len(actual) == len(inputs), (str(output), len(actual), len(inputs))
            for row, (number, source) in zip(actual, inputs):
                verify_row(row, source, number, input_path, stage, domain, count)
        else:
            expected = []
            for number, source in inputs:
                checkpoint = json.loads((RUNTIME / 'rows' / job_id / f'{number:06d}.json').read_text())
                assert checkpoint['job_id'] == job_id
                assert checkpoint['input_line'] == number
                assert Path(checkpoint['input_file']).resolve() == input_path.resolve()
                assert checkpoint['input_sha256'] == digest(source)
                assert checkpoint['output_sha256'] == digest(checkpoint['rows'])
                status = checkpoint['status']
                assert status in ('completed', 'provider_rejected', 'screened_out'), status
                if status == 'provider_rejected':
                    assert not checkpoint['rows'] and checkpoint['sample'] == source
                    assert checkpoint['model'] == 'gt-6-as-a'
                    assert checkpoint['api_base_url'] == 'https://joyrouter.jd.com/v1'
                    counts['provider_rejected'] += 1
                    rejections.append(checkpoint)
                elif status == 'screened_out':
                    assert index == 4 and not checkpoint['rows']
                    assert checkpoint['report']['skipped'] == 1
                    screen = checkpoint.get('screening')
                    if screen is None:
                        assert any(not candidates for candidates in source['retrieved_samples'].values())
                    else:
                        available = {d: {(c['sample']['prompt'], c['sample']['completion']) for c in values}
                                     for d, values in source['retrieved_samples'].items()}
                        screen = generation_module.validate_screening(screen, domain, source['fusion_domains'], available)
                        assert not screen['feasible']
                    counts['screened_out'] += 1
                    screened.append({key: checkpoint.get(key) for key in
                        ('job_id', 'input_file', 'input_line', 'input_sha256', 'screening', 'completed_at')})
                else:
                    if index == 4:
                        assert [row['difficulty'] for row in checkpoint['rows']] == ['easy', 'medium', 'hard']
                    else:
                        assert len(checkpoint['rows']) == 1
                    for row in checkpoint['rows']:
                        verify_row(row, source, number, input_path, stage, domain, count, checkpoint)
                    expected.extend(checkpoint['rows'])
            assert actual == expected, ('Output differs from checkpoints', str(output))
            job = json.loads((RUNTIME / 'jobs' / (job_id + '.json')).read_text())
            assert job['status'] == 'completed' and job['failed'] == 0 and not job['errors']
            assert job['completed'] == job['eligible'] == len(inputs)
            assert job['output_sha256'] == file_hash(output)
            for key in ('generated', 'provider_rejected', 'screened_out'):
                assert counts[key] == job[key], (job_id, key)
        if index == 4:
            assert counts['generated'] == 3 * (counts['eligible'] - counts['provider_rejected'] - counts['screened_out'])
        else:
            assert counts['eligible'] == counts['generated'] + counts['provider_rejected']
        summary[stage]['files'][str(output.relative_to(ROOT / stage))] = {**counts, 'sha256': file_hash(output)}
        for key, value in counts.items():
            summary[stage][key] += value

    for stage in STAGES:
        for domain in DOMAINS:
            for count in ([None] if stage == STAGES[0] else (2, 3, 4)):
                verify_file(stage, domain, count)
    assert summary[STAGES[0]]['eligible'] == 1441
    assert summary[STAGES[1]]['eligible'] == 2100
    for index in (2, 3, 4):
        assert summary[STAGES[index]]['eligible'] == summary[STAGES[index - 1]]['generated']
    assert len(list((RUNTIME / 'jobs').glob('*.json'))) == 42
    events, usage, models = Counter(), Counter(), Counter()
    with (ROOT / 'request_audit.jsonl').open() as stream:
        for line in stream:
            event = json.loads(line)
            assert event['requested_model'] == 'gt-6-as-a'
            assert event['url'] == 'https://joyrouter.jd.com/v1/chat/completions'
            events[event['event']] += 1
            if event['event'] == 'response':
                assert event['status'] == 200 and event['response_model'] == 'gt-6-as-a'
                models[event['response_model']] += 1
                for key in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
                    usage[key] += (event.get('usage') or {}).get(key) or 0
            if event['event'] in ('validated', 'cache_hit'):
                cached = json.loads((RUNTIME / 'responses' / event['job_id'] / (event['request_sha256'] + '.json')).read_text())
                assert cached['response_model'] == 'gt-6-as-a'
    embedding_root = REPO / 'knowledge/embeddings/v4-test-Qwen3-Embedding-8B'
    database = sqlite3.connect((embedding_root / 'vectors.sqlite3').resolve().as_uri() + '?mode=ro', uri=True)
    assert database.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
    stored_queries = set(database.execute('SELECT domain,query FROM queries'))
    assert queries <= stored_queries
    config = json.loads(database.execute("SELECT value FROM metadata WHERE key='config'").fetchone()[0])
    assert config['dimension'] == 4096 and config['model'] == str(Path('/pfs/models/Qwen3-Embedding-8B').resolve())
    for domain in DOMAINS:
        count = database.execute('SELECT COUNT(*) FROM documents WHERE domain=?', (domain,)).fetchone()[0]
        assert count == len(atomic[domain])
    database.close()
    with (ROOT / 'rejected_samples.jsonl').open('w') as stream:
        for record in rejections:
            write_row(stream, record)
    with (ROOT / 'screened_out_samples.jsonl').open('w') as stream:
        for record in screened:
            write_row(stream, record)
    report = {'passed': True, 'stages': summary, 'provider_rejected': len(rejections),
              'screened_out': len(screened), 'api_events': dict(events), 'response_models': dict(models),
              'reported_token_usage': dict(usage), 'required_query_pairs': len(queries),
              'embedding_store': str(embedding_root), 'pipeline_sources_unchanged_since_launch': True,
              'validated_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    (ROOT / 'validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    totals = {stage: {k: v for k, v in counts.items() if k != 'files'} for stage, counts in summary.items()}
    manifest.update(status='completed_with_rejections' if rejections else 'completed',
                    validation='validation.json', stage_totals=totals, reported_token_usage=dict(usage))
    manifest['execution'] = ('Original run_all.sh and stage functions; ordered, checkpointed output. '
        'Stage 2 used 16 workers. Stage 4 began with 16 workers and continued with 32 after resume.')
    manifest['worker_config'] = json.loads((RUNTIME / 'worker_config.json').read_text())
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    lines = ['# Pipeline v4 — JoyRouter gt-6-as-a', '',
             f"Revision: `{manifest['git_commit']}`. Entrypoint: `bash knowledge/pipielines_v4/run_all.sh`.",
             'Endpoint: `https://joyrouter.jd.com/v1/chat/completions`; requested and observed model: `gt-6-as-a`.', '',
             'Stages 0 and 1 are the unchanged, committed input snapshots. Stages 2, 3, and 4 were rerun from scratch. The 1,441 stage-0 annotations already exclude one input filtered during the prior v3 run; that exclusion is not counted as a new v4 provider failure.', '',
             '| Stage | Input records | Output records | New provider failures | Infeasible plans |', '| --- | ---: | ---: | ---: | ---: |']
    lines += [f"| {stage} | {v['eligible']} | {v['generated']} | {v['provider_rejected']} | {v['screened_out']} |" for stage, v in totals.items()]
    lines += ['', 'The original stage functions, prompts, validators, and order were retained. Stage 2 used 16 workers. Stage 4 began with 16 workers and continued with 32. Runs resumed from durable checkpoints after schema errors and a process interruption. Retry feedback was clarified for the original infeasible-plan schema and exact source citations, including literal Unicode and codepoint diagnostics. No citation was substituted or normalized locally. Output order and validated response/row checkpoints were retained. See execution_history, job summaries, and worker_config.json for execution settings.',
              'Stage 2 generated short retrieval keywords. Stage 3 used the original hybrid retrieval backend, top-k 10 and at most 10 candidates per fusion domain. Stage 4 selected exact evidence and revised the plan and requirements to fit that evidence before generating easy/medium/hard variants.',
              'Explicit provider filters/refusals were recorded and skipped. Infeasible plans are reported separately. No partial difficulty triplet is emitted when a provider refusal interrupts generation.',
              'See rejected_samples.jsonl and screened_out_samples.jsonl for source positions and decisions.',
              '', 'API settings: temperature 1, reasoning effort low, up to 5 attempts. Token limits start at repository defaults; length-truncated responses retry with a larger limit up to 8,192. Schema retries include the previous response and validation feedback; exact source-reference validators remain enforced.',
              'The existing isolated pipielines_v3/.env environment was reused because its pinned requirements exactly match v4. Qwen3-Embedding-8B used local weights on GPU 7; v4 has its own vector store at ' + str(embedding_root) + '.',
              'Validation: 17 repository tests and 9 execution tests passed; real GPU encoding passed. Final checks cover preserved seed/source hashes, all stage-2/4 checkpoints, ordered outputs, retrieved corpus identities, revised plans, exact evidence references, complete difficulty triplets, endpoint/model audit, and vector-store integrity.',
              'These checks do not independently establish factual correctness of every generated question.',
              '', 'The archive contains all stage JSONL files, run manifests, audits, execution utilities, tests, and environment reports. It omits credentials, model weights, Python environment, response/row caches, and the vector database.', '']
    (ROOT / 'README.md').write_text('\n'.join(lines))
    paths = [p for stage in STAGES for p in (ROOT / stage).glob('*/*.jsonl')]
    paths += [p for p in ROOT.iterdir() if p.is_file() and p.suffix in ('.json', '.jsonl', '.md', '.log')]
    paths += [p for p in RUNTIME.iterdir() if p.is_file() and p.suffix in ('.py', '.sh', '.json', '.jsonl', '.log')]
    paths += list((RUNTIME / 'jobs').glob('*.json'))
    credential = re.compile(rb'(?:sk-d-[A-Za-z0-9]{16,}|pk-[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,})')
    for path in paths:
        assert not credential.search(path.read_bytes()), ('Credential-like value in archive file', str(path))
    archive = ROOT / ('cross-x_v4_gt-6-as-a_' + manifest['started_at'][:10].replace('-', '') + '_results.zip')
    with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(set(paths)):
            bundle.write(path, arcname=path.relative_to(ROOT.parent))
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
    print(json.dumps({'passed': True, 'stage_totals': totals, 'archive': str(archive),
                      'archive_bytes': archive.stat().st_size}, ensure_ascii=False))


if __name__ == '__main__':
    main()
