"""Check the actual three shell entry points with a recording Python stand-in."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DOMAINS = ('medical', 'legal', 'financial', 'mathematics', 'computer_science', 'geography', 'chemistry')


class SerialShellTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='v2 shell ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.log = self.root / 'calls.jsonl'
        fake = self.root / 'fake-python'
        fake.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ['V2_TEST_CALLS'], 'a') as out:
    out.write(json.dumps(args) + '\\n')
if Path(args[0]).name == os.environ.get('V2_TEST_FAIL'):
    raise SystemExit(7)
if '--input' in args:
    index = args.index('--input') + 1
    while index < len(args) and not args[index].startswith('--'):
        if not Path(args[index]).is_file():
            raise SystemExit('missing input: ' + args[index])
        index += 1
if '--output' in args:
    out = Path(args[args.index('--output') + 1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text('{}\\n')
''')
        fake.chmod(0o755)
        self.env = {**os.environ, 'V2_ROOT': str(self.root / 'output'), 'ATOMIC_ROOT': str(self.root / 'atomic'),
                    'EMBEDDING_ROOT': str(self.root / 'vectors'), 'PYTHON_BIN': str(fake),
                    'EMBEDDING_PYTHON_BIN': str(fake), 'API_BASE_URL': 'http://mock.invalid',
                    'API_KEY': 'mock', 'MODEL': 'mock', 'NUM': '10', 'V2_TEST_CALLS': str(self.log)}
        for domain in DOMAINS:
            path = Path(self.env['ATOMIC_ROOT']) / domain / 'test.jsonl'
            path.parent.mkdir(parents=True)
            path.write_text('{}\n')

    def run_entry(self, name, *args):
        return subprocess.run(['bash', str(ROOT / name), *args], env=self.env,
                              cwd='/tmp', text=True, capture_output=True)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_three_entries_connect_all_groups(self):
        for entry in ('run_012.sh', 'run_embedding_retrieve.sh', 'run_4.sh'):
            result = self.run_entry(entry)
            self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertEqual(len(calls), 7 + 21 + 21 + 2 + 21 + 21)
        stages = [Path(args[0]).name for args in calls]
        self.assertEqual(stages[:7], ['0_extract_key_facts.py'] * 7)
        self.assertEqual(stages[7:28], ['1_generate_fusion_plans.py'] * 21)
        self.assertEqual(stages[28:49], ['2_extract_required_key_facts.py'] * 21)
        for args in calls:
            stage = Path(args[0]).name
            if stage != '1_generate_fusion_plans.py':
                self.assertNotIn('--num', args)
            else:
                self.assertEqual(args[args.index('--num') + 1], '10')
            self.assertNotIn('--fusion-domains', args)
            if stage in ('embed_knowledge.py', '3_retrieve_key_fact_matches.py'):
                self.assertEqual(args[args.index('--splits') + 1], 'test')
            if '--embedding-root' in args:
                self.assertEqual(args[args.index('--embedding-root') + 1], self.env['EMBEDDING_ROOT'])
        query_call = calls[50]
        inputs = query_call[query_call.index('--input') + 1:query_call.index('--embedding-root')]
        self.assertEqual(len(inputs), 21)
        outputs = [Path(a[a.index('--output') + 1]) for a in calls if '--output' in a]
        self.assertEqual(len(set(outputs)), 91)
        self.assertTrue(all(p.is_file() for p in outputs))
        before = len(self.calls())
        self.assertNotEqual(self.run_entry('run_012.sh').returncode, 0)
        self.assertEqual(len(self.calls()), before)  # preflight protects ALL previous outputs
        self.assertEqual(self.run_entry('run_embedding_retrieve.sh', '--overwrite').returncode, 0)
        for args in self.calls()[before:]:
            self.assertEqual('--overwrite' in args, Path(args[0]).name == '3_retrieve_key_fact_matches.py')

    def test_all_samples_and_stop_on_failure(self):
        self.env['NUM'] = 'all'
        self.env['V2_TEST_FAIL'] = '1_generate_fusion_plans.py'
        result = self.run_entry('run_012.sh')
        self.assertEqual(result.returncode, 7)
        self.assertEqual(len(self.calls()), 8)
        self.assertTrue(all('--num' not in args for args in self.calls()))
        self.assertFalse(any(Path(a[0]).name.startswith('2_') for a in self.calls()))

    def test_missing_input_and_invalid_count_fail_before_calls(self):
        (Path(self.env['ATOMIC_ROOT']) / 'chemistry/test.jsonl').unlink()
        self.assertNotEqual(self.run_entry('run_012.sh').returncode, 0)
        self.assertEqual(self.calls(), [])
        self.env['NUM'] = '0'
        self.assertNotEqual(self.run_entry('run_012.sh').returncode, 0)
        self.assertEqual(self.calls(), [])
        self.assertNotEqual(self.run_entry('run_4.sh').returncode, 0)
        self.assertEqual(self.calls(), [])


if __name__ == '__main__':
    unittest.main()
