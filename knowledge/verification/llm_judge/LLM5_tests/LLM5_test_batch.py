"""批量启动的离线验证：选样、配置、零调用预览和失败停止。"""

import contextlib
import io
import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import LLM5_batch as batch
from LLM5_data import AtomicResolver, file_hash, normalize, read_jsonl, write_jsonl


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.addCleanup(patch.stopall)
        patch.object(socket.socket, 'connect', side_effect=AssertionError('No network')).start()
        patch.dict(batch.os.environ, {}, clear=True).start()
        self.env = {
            f'{role}_{field}': value
            for role in ('J1', 'J2', 'J3')
            for field, value in (
                ('API_BASE_URL', f'https://{role.lower()}.example/v1'),
                ('API_KEY', f'secret-{role}'), ('MODEL', f'custom-model-{role}'),
            )
        }
        self.row = {
            'question': 'A question with\u2028an embedded separator?',
            'options': {'A': 'First', 'B': 'Second'}, 'answer': 'A',
            'source_domain': 'chemistry', 'fusion_domains': ['mathematics'], 'domain_count': 2,
            'sample': {'prompt': 'Atomic source?', 'completion': 'Source answer'},
            'used_samples': {'mathematics': [{'prompt': 'Added source?', 'completion': 'Added answer'}]},
        }
        for version in ('v5', 'v6'):
            directory = self.root / version / '4_generate_fusion_question/chemistry'
            directory.mkdir(parents=True)
            path = directory / 'test_domain_count_2.jsonl'
            write_jsonl(path, [self.row, self.row])
            # 原始物理行必须保留，不得用 splitlines() 拆分 U+2028。
            path.write_text('\n' + path.read_text(encoding='utf-8'), encoding='utf-8')
            (directory / 'test_domain_count_2.audit.jsonl').write_text('invalid audit\n')

    def invoke(self, *extra):
        argv = ['LLM5_batch.py', '--v5-root', str(self.root / 'v5'),
                '--v6-root', str(self.root / 'v6'), '--atomic-root', str(self.root / 'atomic'),
                '--domain-counts', '2', '--output-dir', str(self.root / 'output'), *extra]
        with patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()):
            return batch.main()

    def test_separate_endpoints_keys_and_terminal_models(self):
        for base in ('https://j1.example/v1/', 'https://j1.example/v1/chat/completions'):
            with patch.dict(batch.os.environ, {**self.env, 'J1_API_BASE_URL': base}):
                config = batch.make_config()
                self.assertEqual([j['model'] for j in config['judges'].values()],
                                 ['custom-model-J1', 'custom-model-J2', 'custom-model-J3'])
                for role, judge in config['judges'].items():
                    self.assertEqual(judge['endpoint'], f'https://{role.lower()}.example/v1/chat/completions')
                    self.assertEqual(judge['key_env'], f'{role}_API_KEY')
                    self.assertNotIn(self.env[f'{role}_API_KEY'], json.dumps(config))

    def test_missing_model_or_endpoint_rejected_for_each_role(self):
        for role in ('J1', 'J2', 'J3'):
            for suffix in ('MODEL', 'API_BASE_URL'):
                name = f'{role}_{suffix}'
                with patch.dict(batch.os.environ, {**self.env, name: '   '}):
                    with self.assertRaisesRegex(ValueError, name):
                        batch.make_config()

    def test_selection_skips_audit_and_preserves_lines(self):
        samples, sources = batch.collect_samples(self.root / 'v5', self.root / 'atomic', counts=[2])
        self.assertEqual(len(samples), 2)
        self.assertEqual([s['metadata']['input_line'] for s in samples], [2, 3])
        self.assertEqual(len(sources), 1)
        self.assertNotEqual(samples[0]['sample_id'], samples[1]['sample_id'])
        self.assertEqual(len(batch.collect_samples(self.root / 'v5', self.root / 'atomic',
                                                  counts=[2], limit=1)[0]), 1)
        path = Path(sources[0]['path'])
        line, row = next(read_jsonl(path))
        self.assertEqual(normalize(row, path, line, AtomicResolver(self.root / 'atomic')),
                         normalize(row, path, line, AtomicResolver(self.root / 'atomic'),
                                   input_sha256=file_hash(path)))

    def test_missing_selected_file_is_rejected(self):
        with self.assertRaisesRegex(ValueError, '缺少题目文件'):
            batch.collect_samples(self.root / 'v5', self.root / 'atomic')

    def test_dry_run_prepares_both_versions_without_keys_or_network(self):
        self.assertEqual(self.invoke('--dry-run'), 0)
        output = self.root / 'output'
        self.assertEqual(json.loads((output / 'LLM5_batch_manifest.json').read_text())['status'], 'prepared')
        for version in ('v5', 'v6'):
            manifest = json.loads((output / version / 'LLM5_run_manifest.json').read_text())
            self.assertEqual(manifest['http_post_attempts'], 0)
            self.assertEqual(manifest['sample_count'], 2)
            self.assertEqual(manifest['mode'], 'multi_family_review')
            self.assertFalse((output / version / 'LLM5_statistics').exists())
        with self.assertRaises(SystemExit) as exc:
            with contextlib.redirect_stderr(io.StringIO()):
                self.invoke('--dry-run')
        self.assertEqual(exc.exception.code, 2)

    def test_missing_key_rejected_before_creating_output(self):
        for role in ('J1', 'J2', 'J3'):
            with patch.dict(batch.os.environ, {**self.env, f'{role}_API_KEY': ''}):
                errors = io.StringIO()
                with contextlib.redirect_stderr(errors), self.assertRaises(SystemExit) as exc:
                    self.invoke()
                self.assertEqual(exc.exception.code, 2)
                self.assertIn(f'{role}_API_KEY', errors.getvalue())
        self.assertFalse((self.root / 'output').exists())

    def test_validate_both_datasets_before_any_api_calls(self):
        path = self.root / 'v6/4_generate_fusion_question/chemistry/test_domain_count_2.jsonl'
        write_jsonl(path, [{'question': 'Missing fields'}])
        with patch.dict(batch.os.environ, self.env):
            with patch.object(batch, 'run') as run_mock:
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    self.invoke()
                run_mock.assert_not_called()
        self.assertFalse((self.root / 'output').exists())

    def test_incomplete_version_stops_later_version(self):
        with patch.dict(batch.os.environ, self.env):
            with patch.object(batch, 'run', return_value={
                    'status': 'incomplete', 'http_post_attempts': 1, 'sample_count': 2}) as run_mock:
                self.assertEqual(self.invoke(), 1)
                self.assertEqual(run_mock.call_count, 1)
        summary = json.loads((self.root / 'output/LLM5_batch_manifest.json').read_text())
        self.assertEqual(summary['status'], 'incomplete')
        self.assertEqual(summary['datasets']['v6']['status'], 'not_started')


if __name__ == '__main__':
    unittest.main()
