"""Exercise the v4 shell entry points with a recording Python stand-in."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DOMAINS = ('medical', 'legal', 'financial', 'mathematics', 'computer_science', 'geography', 'chemistry')
STEPS = ('run_0.sh', 'run_1.sh', 'run_2.sh', 'run_3.sh', 'run_4.sh')


class SerialShellTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='v4 shell ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.log = self.root / 'calls.jsonl'
        fake = self.root / 'fake-python'
        fake.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
if args and args[0] == '-c':
    raise SystemExit(7 if os.environ.get('V4_TEST_MISSING_DEP') else 0)
with open(os.environ['V4_TEST_CALLS'], 'a') as out:
    out.write(json.dumps(args) + '\\n')
if Path(args[0]).name == os.environ.get('V4_TEST_FAIL'):
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
        self.env = {**os.environ, 'V4_ROOT': str(self.root / 'output'),
                    'ATOMIC_ROOT': str(self.root / 'atomic'),
                    'EMBEDDING_ROOT': str(self.root / 'vectors'),
                    'PYTHON_BIN': str(fake), 'EMBEDDING_PYTHON_BIN': str(fake),
                    'API_BASE_URL': 'http://mock.invalid', 'API_KEY': 'mock',
                    'MODEL': 'mock', 'NUM': '10', 'V4_TEST_CALLS': str(self.log)}
        for domain in DOMAINS:
            path = Path(self.env['ATOMIC_ROOT']) / domain / 'test.jsonl'
            path.parent.mkdir(parents=True)
            path.write_text('{}\n')

    def run_entry(self, name, *args):
        return subprocess.run(['bash', str(ROOT / name), *args], env=self.env,
                              cwd='/tmp', text=True, capture_output=True)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def prepare_resume_inputs(self):
        for domain in DOMAINS:
            step0 = Path(self.env['V4_ROOT']) / '0_extract_key_facts' / domain / 'test.jsonl'
            step0.parent.mkdir(parents=True, exist_ok=True)
            step0.write_text('{}\n')
            for count in (2, 3, 4):
                step1 = Path(self.env['V4_ROOT']) / '1_generate_fusion_plans' / domain / f'test_domain_count_{count}.jsonl'
                step1.parent.mkdir(parents=True, exist_ok=True)
                step1.write_text('{}\n')

    def assert_resume_calls(self):
        calls = self.calls()
        self.assertEqual(len(calls), 65)
        stages = [Path(args[0]).name for args in calls]
        self.assertEqual(stages[:21], ['2_extract_required_key_facts.py'] * 21)
        self.assertEqual(stages[21:23], ['embed_knowledge.py', 'embed_required_key_facts.py'])
        self.assertEqual(stages[23:44], ['3_retrieve_key_fact_matches.py'] * 21)
        self.assertEqual(stages[44:], ['4_generate_fusion_question.py'] * 21)
        self.assertNotIn('0_extract_key_facts.py', stages)
        self.assertNotIn('1_generate_fusion_plans.py', stages)
        for args in calls:
            stage = Path(args[0]).name
            if stage == '3_retrieve_key_fact_matches.py':
                self.assertEqual(args[args.index('--candidate-limit') + 1], '10')
        outputs = [Path(args[args.index('--output') + 1]) for args in calls if '--output' in args]
        self.assertEqual(len(set(outputs)), 63)
        self.assertTrue(all(path.is_file() and str(path).startswith(self.env['V4_ROOT']) for path in outputs))

    def assert_pipeline_calls(self):
        calls = self.calls()
        self.assertEqual(len(calls), 93)
        stages = [Path(args[0]).name for args in calls]
        self.assertEqual(stages[:7], ['0_extract_key_facts.py'] * 7)
        self.assertEqual(stages[7:28], ['1_generate_fusion_plans.py'] * 21)
        self.assertEqual(stages[28:49], ['2_extract_required_key_facts.py'] * 21)
        self.assertEqual(stages[49:51], ['embed_knowledge.py', 'embed_required_key_facts.py'])
        self.assertEqual(stages[51:72], ['3_retrieve_key_fact_matches.py'] * 21)
        self.assertEqual(stages[72:], ['4_generate_fusion_question.py'] * 21)
        for args in calls:
            stage = Path(args[0]).name
            if stage == '1_generate_fusion_plans.py':
                self.assertEqual(args[args.index('--num') + 1], '10')
            else:
                self.assertNotIn('--num', args)
            if stage == '3_retrieve_key_fact_matches.py':
                self.assertEqual(args[args.index('--candidate-limit') + 1], '10')
            if stage in ('embed_knowledge.py', '3_retrieve_key_fact_matches.py'):
                self.assertEqual(args[args.index('--splits') + 1], 'test')
            if '--embedding-root' in args:
                self.assertEqual(args[args.index('--embedding-root') + 1], self.env['EMBEDDING_ROOT'])
        query_call = calls[50]
        inputs = query_call[query_call.index('--input') + 1:query_call.index('--embedding-root')]
        self.assertEqual(len(inputs), 21)
        outputs = [Path(args[args.index('--output') + 1]) for args in calls if '--output' in args]
        self.assertEqual(len(set(outputs)), 91)
        self.assertTrue(all(path.is_file() and str(path).startswith(self.env['V4_ROOT']) for path in outputs))

    def test_full_pipeline(self):
        self.prepare_resume_inputs()
        result = self.run_entry('run_all.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_resume_calls()
        before = len(self.calls())
        self.assertNotEqual(self.run_entry('run_all.sh').returncode, 0)
        self.assertEqual(len(self.calls()), before)

    def test_individual_steps_and_overwrite(self):
        for entry in STEPS:
            result = self.run_entry(entry)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_pipeline_calls()
        before = len(self.calls())
        self.assertEqual(self.run_entry('run_3.sh', '--overwrite').returncode, 0)
        new_calls = self.calls()[before:]
        self.assertEqual(len(new_calls), 23)
        for args in new_calls:
            self.assertEqual('--overwrite' in args, Path(args[0]).name == '3_retrieve_key_fact_matches.py')

    def test_all_samples_and_stop_on_failure(self):
        self.prepare_resume_inputs()
        self.env['NUM'] = 'all'
        self.env['V4_TEST_FAIL'] = '2_extract_required_key_facts.py'
        result = self.run_entry('run_all.sh')
        self.assertEqual(result.returncode, 7)
        self.assertEqual(len(self.calls()), 1)
        self.assertFalse(any(Path(args[0]).name.startswith('0_') for args in self.calls()))
        self.assertFalse(any(Path(args[0]).name.startswith('1_') for args in self.calls()))

    def test_preflight_before_any_calls(self):
        (Path(self.env['ATOMIC_ROOT']) / 'chemistry/test.jsonl').unlink()
        self.assertNotEqual(self.run_entry('run_all.sh').returncode, 0)
        self.assertEqual(self.calls(), [])
        self.env['NUM'] = '0'
        self.assertNotEqual(self.run_entry('run_1.sh').returncode, 0)
        self.assertEqual(self.calls(), [])
        self.assertNotEqual(self.run_entry('run_4.sh').returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_missing_dependency_stops_before_paid_calls(self):
        self.prepare_resume_inputs()
        self.env['V4_TEST_MISSING_DEP'] = '1'
        result = self.run_entry('run_all.sh')
        self.assertEqual(result.returncode, 7)
        self.assertEqual(self.calls(), [])


if __name__ == '__main__':
    unittest.main()
