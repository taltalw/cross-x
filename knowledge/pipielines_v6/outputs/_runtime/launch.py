"""Run the original v4 stages 2–4 with JoyRouter and resumable row execution."""
import argparse
import datetime
import fcntl
import getpass
import hashlib
import json
import os
from pathlib import Path
import subprocess

RUNTIME = Path(__file__).resolve().parent
ROOT = RUNTIME.parent
V4 = ROOT.parent
REPO = V4.parents[1]


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def hashes(paths):
    return {str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--from-stage', choices=('4',))
    args = parser.parse_args()
    if args.from_stage and not args.resume:
        parser.error('--from-stage requires --resume')
    lock = (RUNTIME / 'run.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    sources = [*V4.glob('*.py'), *V4.glob('*.sh'), V4 / 'requirements-crossx.txt',
               *[REPO / 'knowledge/pipelines' / name for name in
                 ('_knowledge_search_common.py', '_offline_embeddings.py',
                  'embed_knowledge.py', '3_retrieve_knowledge.py')]]
    source_hashes = hashes(sources)
    seeds = [p for stage in ('0_extract_key_facts', '1_generate_fusion_plans')
             for p in (ROOT / stage).glob('*/*.jsonl')]
    assert len(seeds) == 28
    seed_hashes = hashes(seeds)
    assert json.loads((RUNTIME / 'preflight.json').read_text())['passed']
    assert json.loads((RUNTIME / 'seed_validation.json').read_text())['passed']
    manifest_path = ROOT / 'run_manifest.json'
    command = ['bash', 'knowledge/pipielines_v4/run_all.sh']
    if args.resume:
        manifest = json.loads(manifest_path.read_text())
        assert manifest['status'] not in ('completed', 'completed_with_rejections'), 'Run already completed'
        assert manifest['source_sha256'] == source_hashes, 'Pipeline sources changed'
        assert manifest['seed_sha256'] == seed_hashes, 'Upstream stage 0/1 files changed'
        manifest.setdefault('execution_history', []).append({k: manifest.get(k) for k in
            ('command', 'status', 'last_started_at', 'finished_at', 'exit_code')})
        prior = manifest['execution_history'][-1]
        if prior['status'] == 'running':
            prior.update(status='interrupted', finished_at=None, exit_code=None,
                         note='Resumed with the run lock free; exact stop time and exit code are unknown.')
        if args.from_stage:
            jobs = list((RUNTIME / 'jobs').glob('2_extract_required_key_facts__*.json'))
            assert len(jobs) == 21
            for path in jobs:
                job = json.loads(path.read_text())
                assert job['status'] == 'completed'
                assert hashlib.sha256(Path(job['output']).read_bytes()).hexdigest() == job['output_sha256']
            retrieval = list((ROOT / '3_retrieve_key_fact_matches').glob('*/*.jsonl'))
            assert len(retrieval) == 21
            assert manifest['retrieval_sha256'] == hashes(retrieval)
            command = ['bash', 'knowledge/pipielines_v4/run_4.sh']
        command.append('--overwrite')
    else:
        assert not manifest_path.exists(), 'Existing run; use --resume'
        manifest = {'started_at': now(), 'git_commit': subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip(),
            'source_sha256': source_hashes, 'seed_sha256': seed_hashes,
            'output_root': str(ROOT), 'initial_command': command.copy(),
            'credentials_persisted': False, 'executed_stages': [2, 3, 4],
            'reused_stages': [0, 1], 'python_environment': str(REPO / 'knowledge/pipielines_v3/.env'),
            'failure_policy': 'Record and skip explicit provider filters/refusals; technical errors remain fatal.',
            'execution': 'Original run_all.sh and per-row functions; 16 workers per input file; ordered output; validated response and row caches',
            'schema_retry_policy': 'Retry schema failures with validation feedback and the previous response; exact supplied-sample citations remain mandatory.',
            'output_token_policy': 'Original defaults; length-truncated responses retried with increased limit up to 8192',
            'api_attempts': 5}
    key = os.environ.get('JOYROUTER_API_KEY') or getpass.getpass('JoyRouter API key (hidden): ')
    assert key.strip(), 'Missing API key'
    settings = {'API_BASE_URL': 'https://joyrouter.jd.com/v1', 'MODEL': 'gt-6-as-a',
                'API_TEMPERATURE': '1', 'API_REASONING_EFFORT': 'low',
                'EMBEDDING_MODEL': '/pfs/models/Qwen3-Embedding-8B',
                'EMBEDDING_ROOT': str(REPO / 'knowledge/embeddings/v4-test-Qwen3-Embedding-8B'),
                'GPU_ID': '7', 'EMBEDDING_DEVICE': 'cuda', 'V4_API_WORKERS': '16',
                'NUM': '100', 'TOP_K': '10', 'CANDIDATE_LIMIT': '10'}
    env = {**os.environ, **settings, 'API_KEY': key,
           'PYTHON_BIN': str(RUNTIME / 'python_proxy.sh'),
           'EMBEDDING_PYTHON_BIN': str(RUNTIME / 'python_proxy.sh'),
           'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUNBUFFERED': '1',
           'TOKENIZERS_PARALLELISM': 'false', 'OMP_NUM_THREADS': '4', 'V4_ROOT': str(ROOT)}
    if args.resume:
        assert manifest['settings'] == settings, 'Run settings changed'
    manifest.update(status='running', command=command, last_started_at=now(),
                    settings=settings, pid=os.getpid())
    manifest.pop('finished_at', None)
    manifest.pop('exit_code', None)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    with (ROOT / 'run.log').open('a') as log:
        process = subprocess.Popen(command, cwd=REPO, env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in process.stdout:
            safe = line.replace(key, '[redacted]')
            log.write(safe)
            log.flush()
            print(safe, end='', flush=True)
        result = process.wait()
    retrieval = list((ROOT / '3_retrieve_key_fact_matches').glob('*/*.jsonl'))
    if len(retrieval) == 21:
        manifest['retrieval_sha256'] = hashes(retrieval)
    manifest.update(status='completed' if result == 0 else 'failed',
                    exit_code=result, finished_at=now())
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print('ALL STAGES COMPLETED' if result == 0 else 'RUN FAILED; completed checkpoints retained', flush=True)
    return result


if __name__ == '__main__':
    raise SystemExit(main())
