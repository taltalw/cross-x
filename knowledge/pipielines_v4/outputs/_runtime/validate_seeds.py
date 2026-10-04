"""Validate the supplied stage 0/1 snapshots before rerunning stages 2–4."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

RUNTIME = Path(__file__).resolve().parent
ROOT = RUNTIME.parent
V4 = ROOT.parent
REPO = V4.parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(V4))
from knowledge.pipelines._knowledge_search_common import DOMAINS, read_rows
from _pipeline_common import validate_v2_row, validate_selected_plan, sample_hash


def main():
    files, models = {}, Counter()
    for domain in DOMAINS:
        atomic = {sample_hash(row): row for _, row in read_rows(REPO / 'knowledge/atomic' / domain / 'test.jsonl')}
        path = ROOT / '0_extract_key_facts' / domain / 'test.jsonl'
        annotations = {}
        rows = list(read_rows(path))
        for _, row in rows:
            validate_v2_row(row)
            assert row['source_domain'] == domain
            key = sample_hash(row['sample'])
            assert atomic[key] == row['sample']
            assert key not in annotations
            annotations[key] = row
            models[row.get('model')] += 1
        files[str(path.relative_to(ROOT))] = {'rows': len(rows), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        for count in (2, 3, 4):
            path = ROOT / '1_generate_fusion_plans' / domain / f'test_domain_count_{count}.jsonl'
            plans = list(read_rows(path))
            assert len(plans) == 100
            for (_, row), (_, original) in zip(plans, rows[:100]):
                validate_v2_row(row)
                assert row['source_domain'] == domain and row['domain_count'] == count
                normalized = validate_selected_plan(row, domain, count)
                assert all(row[k] == v for k, v in normalized.items())
                assert all(row[k] == original[k] for k in ('source_file', 'source_domain', 'sample', 'key_facts'))
                models[row.get('model')] += 1
            files[str(path.relative_to(ROOT))] = {'rows': len(plans), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    result = {'passed': True, 'files': files, 'models': dict(models),
              'stage0_rows': sum(v['rows'] for k, v in files.items() if k.startswith('0_')),
              'stage1_rows': sum(v['rows'] for k, v in files.items() if k.startswith('1_'))}
    (RUNTIME / 'seed_validation.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'files'}))


if __name__ == '__main__':
    main()
