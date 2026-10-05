"""CDNS 离线契约测试；所有推理调用均以模拟对象替换。"""

import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE))
import CDNS_data as data
import CDNS_infer as infer
import CDNS_prepare as preparation
import CDNS_score as scoring
import CDNS_validate as validation


def native(sid='s1', domains=('source', 'other')):
    """构造有独立材料标记与敏感生成字段的规范输入。"""
    return {'sample_id': sid, 'source_domain': domains[0], 'domains': list(domains),
            'domain_count': len(domains), 'difficulty': 'easy', 'question': '最终问题\u2028继续',
            'options': {'A': '正确内容', 'B': '干扰内容'}, 'answer': 'A',
            'explanation': 'SECRET_EXPLANATION', 'answer_plan': 'SECRET_PLAN',
            'knowledge': {d: {'materials': [{'text': f'EVIDENCE_{d}',
                                            'explanation': 'SECRET_MATERIAL_EXTRA'}]}
                          for d in domains}}


def stage4():
    """构造阶段4两套新增域材料及原子参考问答。"""
    row = native()
    del row['knowledge']
    del row['domains']
    row.update(fusion_domains=['other'],
               sample={'prompt': '参考题：A 假说 / B 定理', 'completion': 'B'},
               retrieved_samples={'other': [{'prompt': 'RETRIEVED_Q', 'completion': 'R_ANSWER'}]},
               used_samples={'other': [{'prompt': 'USED_Q', 'completion': 'U_ANSWER'}]})
    return row


def fixture(rows):
    """返回规范样本、独立金标和请求集合。"""
    samples = [data.normalize_record(row) for row in rows]
    answers = {sample['sample_id']: sample.pop('answer') for sample in samples}
    requests = [request for sample in samples for request in data.build_requests(sample)]
    return samples, answers, requests


def predictions(requests, answers, patterns):
    """依手算条件填写预测；None 代表缺失，状态字符串代表故障。"""
    config = {'backend': 'unit-test', 'version': 1}
    result = []
    for request in requests:
        value = patterns[request['sample_id']].get((request['condition'], request['domain']))
        if value is None:
            continue
        record = {'request_id': request['request_id'], 'prompt_sha256': request['prompt_sha256'],
                  'inference_config': config, 'inference_id': data.digest(config), 'simulation': True}
        if value in ('error', 'invalid_format'):
            record['status'] = value
        else:
            record.update(status='ok', answer=value if isinstance(value, str)
                          else (answers[request['sample_id']] if value else 'B'))
        result.append(record)
    return result


class DataTests(unittest.TestCase):
    """输入适配和材料遮蔽契约。"""

    def test_every_condition_exact_content_and_count(self):
        for k in (2, 3, 4):
            with self.subTest(k=k):
                domains = ['source', 'other', 'third', 'fourth'][:k]
                sample = data.normalize_record(native(domains=domains))
                requests = data.build_requests(sample)
                self.assertEqual(len(requests), {2: 6, 3: 8, 4: 10}[k])
                self.assertEqual(len({r['request_id'] for r in requests}), len(requests))
                for r in requests:
                    visible = json.loads(r['messages'][1]['content'])
                    expected = domains if r['condition'] == 'full' else (
                        [] if r['condition'] == 'no_domain' else (
                            [r['domain']] if r['condition'] == 'only' else
                            [d for d in domains if d != r['domain']]))
                    self.assertEqual(list(visible['reference_materials']), expected)
                    self.assertEqual(r['included_domains'], expected)
                    self.assertEqual(visible['final_question'], sample['question'])
                    self.assertEqual(visible['options'], sample['options'])
                    self.assertEqual(set(visible), {'reference_materials', 'final_question', 'options'})
                    for d in expected:
                        self.assertEqual(visible['reference_materials'][d]['materials'],
                                         [{'text': f'EVIDENCE_{d}'}])
                    self.assertNotIn('SECRET_', json.dumps(r))
                source_mask = next(r for r in requests if r['condition'] == 'mask' and r['domain'] == 'source')
                self.assertNotIn('EVIDENCE_source', source_mask['messages'][1]['content'])

    def test_stage4_retrieved_and_used_preserve_reference_qa(self):
        for mode, marker in [('retrieved', 'RETRIEVED_Q'), ('used', 'USED_Q')]:
            sample = data.normalize_record(stage4(), mode)
            self.assertEqual(sample['domains'], ['source', 'other'])
            full = data.build_requests(sample)[0]
            visible = json.loads(full['messages'][1]['content'])
            self.assertEqual(visible['reference_materials']['source']['materials'],
                             [{'prompt': '参考题：A 假说 / B 定理', 'completion': 'B'}])
            self.assertIn(marker, full['messages'][1]['content'])
            self.assertIn('distractor options are not established facts', full['messages'][0]['content'])
            self.assertNotIn('SECRET_', json.dumps(full))

    def test_material_variants(self):
        self.assertEqual(data.material_content('fact'), {'text': 'fact'})
        self.assertEqual(data.material_content({'sample': {'prompt': 'q', 'completion': 'a'}}),
                         {'prompt': 'q', 'completion': 'a'})
        for material in ({'prompt': 'q'}, {'text': ''}, 3, {'answer': 'A'}):
            with self.subTest(material=material), self.assertRaises(ValueError):
                data.material_content(material)

    def test_invalid_native_inputs_rejected(self):
        changes = [lambda r: r['knowledge']['source'].update(materials=[]),
                   lambda r: r.update(domains=['source', 'source']),
                   lambda r: r.update(domains=['source', 'missing']),
                   lambda r: r.update(domain_count=3),
                   lambda r: r.update(source_domain='missing'),
                   lambda r: r.update(answer='Z'),
                   lambda r: r.update(domains=['source']),
                   lambda r: r.update(knowledge={}),
                   lambda r: r.update(question=''),
                   lambda r: r.update(options={'ABSTAIN': 'a', 'B': 'b'})]
        for change in changes:
            row = native()
            change(row)
            with self.subTest(row=row), self.assertRaises(ValueError):
                data.normalize_record(row)

    def test_invalid_stage4_inputs_rejected(self):
        for changes in ({'fusion_domains': ['other', 'other']}, {'fusion_domains': ['source']},
                        {'retrieved_samples': {}}, {'sample': None},
                        {'retrieved_samples': {'other': [], 'unexpected': []}}):
            row = stage4()
            row.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                data.normalize_record(row)


class BundleTests(unittest.TestCase):
    """金标隔离、完整性审计和安全 dry-run。"""

    def setUp(self):
        """每个测试建立独立临时输入。"""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.input = self.root / 'source.jsonl'
        self.bundle = self.root / 'prepared'
        data.write_jsonl(self.input, [native()])
        preparation.prepare(self.input, self.bundle)

    def test_gold_separation_unicode_and_hashes(self):
        samples, answers, requests, manifest = data.load_bundle(self.bundle)
        self.assertEqual(answers, {'s1': 'A'})
        self.assertNotIn('answer', samples[0])
        self.assertEqual(samples[0]['question'], '最终问题\u2028继续')
        self.assertEqual(len(list(data.read_jsonl(self.input))), 1)
        self.assertEqual(manifest['request_count'], 6)
        for request in requests:
            self.assertNotIn('answer', request)
            self.assertNotIn('answer', json.loads(request['messages'][1]['content']))

    def test_hash_tampering_rejected(self):
        target = self.bundle / 'CDNS_answers.jsonl'
        target.write_text(target.read_text(encoding='utf-8') + '\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '哈希'):
            data.load_bundle(self.bundle)

    def test_semantic_request_tampering_rejected_even_with_new_file_hash(self):
        target = self.bundle / 'CDNS_requests.jsonl'
        rows = [r for _, r in data.read_jsonl(target)]
        rows[0]['included_domains'] = []
        data.write_jsonl(target, rows)
        path = self.bundle / 'CDNS_manifest.json'
        manifest = json.loads(path.read_text(encoding='utf-8'))
        manifest['files'][target.name] = data.file_digest(target)
        data.write_json(path, manifest)
        with self.assertRaisesRegex(ValueError, '不一致'):
            data.load_bundle(self.bundle)

    def test_duplicate_input_and_empty_filter_rejected(self):
        data.write_jsonl(self.input, [native(), native()])
        with self.assertRaisesRegex(ValueError, '重复样本'):
            preparation.prepare(self.input, self.root / 'duplicate')
        with self.assertRaisesRegex(ValueError, '无样本'):
            preparation.prepare(self.input, self.root / 'empty', difficulty='hard')

    def test_refuse_overwrite(self):
        before = (self.bundle / 'CDNS_manifest.json').read_bytes()
        with self.assertRaises(ValueError):
            preparation.prepare(self.input, self.bundle)
        self.assertEqual((self.bundle / 'CDNS_manifest.json').read_bytes(), before)

    def test_dryrun_never_network_or_secret_or_output(self):
        output = self.root / 'predictions.jsonl'
        with patch('urllib.request.urlopen', side_effect=AssertionError('NETWORK')), \
             patch('CDNS_infer.os.environ.get', side_effect=AssertionError('SECRET')):
            result = infer.run_inference(self.bundle, output)
        self.assertEqual(result, {'mode': 'dry_run', 'requests': 6, 'real_model_calls': 0})
        self.assertFalse(output.exists())

    def test_mock_execute_payload_and_failure_categories(self):
        output = self.root / 'predictions.jsonl'
        replies = [('A', 'stop'), ('nonsense', 'stop'), ('A', 'length'),
                   urllib.error.URLError('SENSITIVE_ERROR'), ('ABSTAIN', 'stop'), ('{"answer":"B"}', 'stop')]
        with patch.object(infer, 'http_completion', side_effect=replies) as http:
            result = infer.run_inference(self.bundle, output, 'http://localhost:1/v1/chat/completions',
                                         'mock', True, seed=17)
        self.assertEqual(result['statuses'], {'ok': 3, 'invalid_format': 1, 'error': 2})
        records = [r for _, r in data.read_jsonl(output)]
        self.assertEqual(len({r['inference_id'] for r in records}), 1)
        self.assertEqual(records[2]['error_type'], 'incomplete_response')
        self.assertNotIn('SENSITIVE_ERROR', output.read_text(encoding='utf-8'))
        for call in http.call_args_list:
            payload = call.args[1]
            self.assertEqual(set(payload), {'model', 'messages', 'temperature', 'max_tokens', 'seed'})
            self.assertNotIn('answer', json.loads(payload['messages'][1]['content']))
        with patch.object(infer, 'http_completion', side_effect=AssertionError('NETWORK')), \
             self.assertRaises(FileExistsError):
            infer.run_inference(self.bundle, output, 'http://localhost:1/v1/chat/completions', 'mock', True)

    def test_invalid_execution_config_zero_requests(self):
        for kwargs in ({'endpoint': 'http://user:pass@localhost/api'}, {'endpoint': 'http://localhost/api?q=key'},
                       {'model': ''}, {'temperature': float('nan')}, {'max_tokens': 0}, {'timeout': -1}):
            config = dict(input_dir=self.bundle, output=self.root / 'invalid.jsonl',
                          endpoint='http://localhost/api', model='mock', execute=True)
            config.update(kwargs)
            with self.subTest(kwargs=kwargs), patch.object(infer, 'http_completion') as http:
                with self.assertRaises(ValueError):
                    infer.run_inference(**config)
                http.assert_not_called()

    def test_cli_prepare_dryrun_validation(self):
        commands = [('CDNS_prepare.py', '--input', str(self.input), '--output-dir', str(self.root / 'cli')),
                    ('CDNS_infer.py', '--input-dir', str(self.root / 'cli')),
                    ('CDNS_validate.py', '--input', str(self.input), '--output-dir', str(self.root / 'validation'))]
        for command in commands:
            result = subprocess.run([sys.executable, '-X', 'utf8', str(MODULE / command[0]), *command[1:]],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((self.root / 'validation' / 'CDNS_validation.json').read_text(encoding='utf-8'))
        self.assertEqual(report['real_model_calls'], 0)
        self.assertTrue(report['validation_only'])


class ScoreTests(unittest.TestCase):
    """非镜像手算例子，覆盖分母、缺失和负贡献。"""

    def setUp(self):
        """四个样本的 Full / 两个 Mask 正确性手工指定。"""
        self.samples, self.answers, self.requests = fixture([native(str(i)) for i in range(4)])
        values = [(1, 0, 0), (1, 1, 0), (0, 0, 1), (1, 0, 1)]
        self.patterns = {str(i): {('full', None): f, ('mask', 'source'): a, ('mask', 'other'): b}
                         for i, (f, a, b) in enumerate(values)}
        self.predictions = predictions(self.requests, self.answers, self.patterns)

    def evaluate(self, results=None):
        """调用待测评分，使用明确选择的预测集合。"""
        return scoring.evaluate(self.samples, self.answers, self.requests,
                                self.predictions if results is None else results)

    def test_cdn_denominator_includes_full_wrong_and_ig_sample_max(self):
        report = self.evaluate()
        summary = report['summary'][0]
        self.assertEqual(summary['CDNS'], 0.25)
        self.assertEqual(summary['IG'], 0.0)
        self.assertEqual(summary['full_accuracy_complete'], 0.75)
        self.assertEqual(summary['best_mask_accuracy_complete'], 0.75)
        self.assertEqual(summary['n_complete'], 4)
        self.assertEqual([r['IG'] for r in report['sample_scores']], [1, 0, -1, 0])
        dc = {r['domain']: r for r in report['domain_contribution'] if r['group_by'] == 'overall'}
        self.assertEqual(dc['source']['DC'], 0.5)
        self.assertEqual(dc['other']['DC'], 0.25)

    def test_only_no_domain_missing_do_not_exclude_core(self):
        report = self.evaluate()
        self.assertEqual(report['missing_predictions'], 12)
        self.assertEqual(report['summary'][0]['n_excluded'], 0)
        diagnostic = [r for r in report['condition_accuracy'] if r['condition'] == 'no_domain']
        self.assertTrue(all(r['accuracy'] is None for r in diagnostic))

    def test_error_invalid_missing_excluded_but_abstain_is_wrong(self):
        self.patterns['0'][('mask', 'source')] = 'ABSTAIN'
        self.patterns['1'][('mask', 'source')] = 'error'
        self.patterns['2'][('mask', 'source')] = 'invalid_format'
        self.patterns['3'][('mask', 'source')] = None
        report = self.evaluate(predictions(self.requests, self.answers, self.patterns))
        self.assertEqual(report['summary'][0]['n_complete'], 1)
        self.assertEqual(report['summary'][0]['CDNS'], 1)
        dc = {r['domain']: r for r in report['domain_contribution'] if r['group_by'] == 'overall'}
        self.assertEqual(dc['source']['n_paired'], 1)
        self.assertEqual(dc['other']['n_paired'], 4)
        self.assertEqual(dc['other']['DC'], 0.25)

    def test_domain_contribution_only_samples_containing_domain(self):
        samples, answers, requests = fixture([native('a'), native('b', ('source', 'third', 'fourth'))])
        patterns = {'a': {('full', None): 1, ('mask', 'source'): 0, ('mask', 'other'): 0},
                    'b': {('full', None): 0, ('mask', 'source'): 1, ('mask', 'third'): 1}}
        report = scoring.evaluate(samples, answers, requests, predictions(requests, answers, patterns))
        dc = {r['domain']: r for r in report['domain_contribution'] if r['group_by'] == 'overall'}
        self.assertEqual(dc['other']['n_total'], 1)
        self.assertEqual(dc['other']['DC'], 1)
        self.assertEqual(dc['third']['DC'], -1)
        self.assertEqual(dc['source']['DC'], 0)
        self.assertIsNone(dc['fourth']['DC'])

    def test_empty_predictions_are_undefined_not_zero(self):
        report = self.evaluate([])
        self.assertEqual(report['summary'][0]['n_excluded'], 4)
        self.assertIsNone(report['summary'][0]['CDNS'])
        self.assertIsNone(report['summary'][0]['IG'])

    def test_invalid_prediction_identity_and_config_rejected(self):
        modifications = [lambda p: p.append(copy.deepcopy(p[0])),
                         lambda p: p[0].update(request_id='unknown'),
                         lambda p: p[0].update(prompt_sha256='changed'),
                         lambda p: p[0].update(inference_id='changed'),
                         lambda p: p[0].update(simulation=False),
                         lambda p: p[0].update(answer='UNKNOWN'),
                         lambda p: p[0].update(status='timeout')]
        for modify in modifications:
            rows = copy.deepcopy(self.predictions)
            modify(rows)
            with self.subTest(rows=rows[0]), self.assertRaises(ValueError):
                self.evaluate(rows)
        rows = copy.deepcopy(self.predictions)
        rows[0]['inference_config'] = {'backend': 'different'}
        rows[0]['inference_id'] = data.digest(rows[0]['inference_config'])
        with self.assertRaisesRegex(ValueError, '混合推理配置'):
            self.evaluate(rows)


class TransportTests(unittest.TestCase):
    """响应解析与 HTTP 层使用假响应，禁止真实联网。"""

    def test_parser_accepts_only_unambiguous_answers(self):
        for text, expected in [(' A ', 'A'), ('{"answer":"B"}', 'B'),
                               ('```json\n{"answer":"A"}\n```', 'A'), ('ABSTAIN', 'ABSTAIN')]:
            self.assertEqual(infer.parse_answer(text, ['A', 'B']), expected)
        for text in ('Because A is right', '{"answer":"C"}', '{"answer":["A"]}', 'A or B', None):
            with self.subTest(text=text), self.assertRaises(ValueError):
                infer.parse_answer(text, ['A', 'B'])

    def test_http_payload_uses_post_and_returns_finish_reason(self):
        response = io.StringIO(json.dumps({'choices': [{'message': {'content': 'A'}, 'finish_reason': 'stop'}]}))
        with patch('urllib.request.urlopen', return_value=response) as opening:
            actual = infer.http_completion('http://localhost/not-called', {'messages': []}, 'fake-token', 2)
        self.assertEqual(actual, ('A', 'stop'))
        request = opening.call_args.args[0]
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(json.loads(request.data), {'messages': []})
        self.assertEqual(request.get_header('Authorization'), 'Bearer fake-token')


if __name__ == '__main__':
    unittest.main()
