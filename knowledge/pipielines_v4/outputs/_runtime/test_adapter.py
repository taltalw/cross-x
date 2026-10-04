import importlib.util
import copy
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.error

import adapter as a


def load_stage(name):
    path = Path(__file__).resolve().parents[2] / (name + '.py')
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeAPI:
    model = 'gt-6-as-a'
    base_url = 'https://joyrouter.jd.com/v1'
    temperature = 1
    reasoning_effort = 'low'

    def __init__(self):
        self.calls = []

    def chat(self, system, data, validate, max_tokens):
        self.calls.append(data)
        prompt = data['sample']['prompt']
        if prompt == 'reject':
            raise a.ProviderRejected('explicit provider content_filter')
        if prompt == 'auth':
            raise a.APIError('HTTP 401')
        if 'domain_count' in data:
            return validate({'fusion_domains': ['legal'], 'question_plan': 'Apply the rule to the diagnosis.',
                 'answer_plans': [{'type': key, 'missing_domain': 'medical' if key == 'missing_domain_knowledge' else None,
                                  'plan': 'Apply ' + key} for key in
                    ('correct', 'missing_domain_knowledge', 'parallel_knowledge', 'incorrect_domain_relation')]})
        return validate({'key_facts': ['first concept', 'second concept']})


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.output_root = self.root / 'outputs'
        self.runtime = self.output_root / '_runtime'
        self.runtime.mkdir(parents=True)
        (self.output_root / 'run_manifest.json').write_text(json.dumps({'source_sha256': {}}))
        self.patches = [patch.object(a, 'ROOT', self.output_root), patch.object(a, 'RUNTIME', self.runtime),
                        patch.dict(os.environ, {'V4_API_WORKERS': '3'})]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.directory.cleanup()

    def test_source_lines_order_skip_and_resume(self):
        source = self.root / 'source.jsonl'
        values = [{'prompt': p, 'completion': 'answer'} for p in ('first\u2028part', 'reject', 'last')]
        source.write_text(json.dumps(values[0], ensure_ascii=False) + '\n\n' +
                          '\n'.join(json.dumps(v) for v in values[1:]) + '\n')
        output = self.output_root / '0_extract_key_facts/medical/test.jsonl'
        module = load_stage('0_extract_key_facts')
        api = FakeAPI()
        report = a.parallel_process(module, module.run_extraction, source, output,
                 api=api, source_domain='medical', num=None, max_tokens=256, overwrite=False)
        rows = [row for _, row in a.read_rows(output)]
        self.assertEqual([v['source_line'] for v in rows], [1, 4])
        self.assertEqual([v['sample'] for v in rows], [values[0], values[2]])
        self.assertTrue(all(v['source_file'] == str(source) for v in rows))
        self.assertEqual(report['provider_rejected'], 1)
        self.assertEqual(len(api.calls), 3)
        previous = output.read_bytes()
        module = load_stage('0_extract_key_facts')
        a.parallel_process(module, module.run_extraction, source, output,
                 api=api, source_domain='medical', num=None, max_tokens=256, overwrite=True)
        self.assertEqual(output.read_bytes(), previous)
        self.assertEqual(len(api.calls), 3)
        self.assertEqual(len(list(a.read_rows(self.output_root / 'rejected_samples.jsonl'))), 1)

    def test_stage1_limit_does_not_replace_rejections(self):
        source = self.root / 'source.jsonl'
        rows = [{'source_file': '/original/test.jsonl', 'source_domain': 'medical',
                 'sample': {'prompt': prompt, 'completion': 'answer'}, 'key_facts': ['a', 'b']}
                for prompt in ('first', 'reject', 'third', 'beyond-limit')]
        source.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        output = self.output_root / '1_generate_fusion_plans/medical/test_domain_count_2.jsonl'
        module = load_stage('1_generate_fusion_plans')
        api = FakeAPI()
        result = a.parallel_process(module, module.process, source, output,
                 api=api, domain_count=2, num=3, max_tokens=2048, overwrite=False)
        self.assertEqual(result['eligible'], 3)
        self.assertEqual(result['generated'], 2)
        self.assertEqual(len(api.calls), 3)
        self.assertEqual([v['sample']['prompt'] for _, v in a.read_rows(output)], ['first', 'third'])

    def test_technical_error_remains_fatal(self):
        source = self.root / 'source.jsonl'
        source.write_text(''.join(json.dumps({'prompt': p, 'completion': 'answer'}) + '\n'
                                 for p in ('first', 'auth', 'never')))
        output = self.output_root / '0_extract_key_facts/medical/test.jsonl'
        module = load_stage('0_extract_key_facts')
        api = FakeAPI()
        with patch.dict(os.environ, {'V4_API_WORKERS': '1'}), self.assertRaises(a.APIError):
            a.parallel_process(module, module.run_extraction, source, output,
                 api=api, source_domain='medical', num=None, max_tokens=256, overwrite=False)
        self.assertEqual(len(list(a.read_rows(output))), 1)
        self.assertEqual(len(api.calls), 2)
        self.assertFalse((self.output_root / 'rejected_samples.jsonl').exists())

    def api_context(self):
        a.LOCAL.context = {'job_id': 'test', 'input_file': '/test.jsonl', 'input_line': 1,
                           'input_sha256': 'test'}
        return a.AuditedAPI('https://joyrouter.jd.com/v1', 'fake-test-value', 'gt-6-as-a', 5, 0)

    def test_partial_generation_is_not_emitted_after_refusal(self):
        source = self.root / 'source.jsonl'
        source.write_text('{"prompt":"accepted","completion":"answer"}\n'
                          '{"prompt":"reject","completion":"answer"}\n')
        output = self.output_root / '4_generate_fusion_question/medical/test_domain_count_2.jsonl'
        module = SimpleNamespace(__name__='4_generate_fusion_question', read_rows=a.read_rows)
        def process(input_file, output_file, **kwargs):
            with output_file.open('w') as stream:
                for number, row in module.read_rows(input_file):
                    for difficulty in ('easy', 'medium', 'hard'):
                        if row['prompt'] == 'reject' and difficulty == 'medium':
                            raise a.ProviderRejected('Explicit refusal after one difficulty')
                        a.write_row(stream, {'input_line': number, 'difficulty': difficulty})
            return {'processed': 1, 'generated': 3, 'skipped': 0}
        result = a.parallel_process(module, process, source, output,
                 api=FakeAPI(), domain_count=2, num=None, max_tokens=4096, overwrite=False)
        rows = [row for _, row in a.read_rows(output)]
        self.assertEqual(result['provider_rejected'], 1)
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row['input_line'] == 1 for row in rows))

    @staticmethod
    def response(content, model='gt-6-as-a', finish='stop'):
        return io.BytesIO(json.dumps({'model': model, 'choices': [{'finish_reason': finish,
                          'message': {'content': json.dumps(content)}}]}).encode())

    def test_only_validated_responses_are_cached(self):
        api = self.api_context()
        validate = load_stage('0_extract_key_facts').validate_key_facts
        with (patch.object(a.urllib.request, 'urlopen', side_effect=[
              self.response({'key_facts': []}), self.response({'key_facts': ['a', 'b']})]) as call,
              patch.object(a.time, 'sleep')):
            result = api.chat('system', {'sample': 'test'}, validate, 256)
            self.assertEqual(call.call_count, 2)
            retry = json.loads(call.call_args_list[1].args[0].data)
            self.assertEqual(retry['messages'][0]['content'], 'system')
            self.assertEqual(retry['messages'][-2]['role'], 'assistant')
            self.assertIn('previous response failed validation', retry['messages'][-1]['content'])
        with patch.object(a.urllib.request, 'urlopen', side_effect=AssertionError('Network on cache replay')):
            self.assertEqual(api.chat('system', {'sample': 'test'}, validate, 256), result)
        self.assertEqual(len(list((self.runtime / 'responses/test').glob('*.json'))), 1)

    def test_refusal_auth_and_model_checks(self):
        validate = load_stage('0_extract_key_facts').validate_key_facts
        api = self.api_context()
        for code, body, exception in ((400, {'error': {'code': 'content_filter'}}, a.ProviderRejected),
                                      (401, {'error': {'message': 'bad key'}}, a.APIError)):
            error = urllib.error.HTTPError('url', code, 'failure', {}, io.BytesIO(json.dumps(body).encode()))
            with (patch.object(a.urllib.request, 'urlopen', side_effect=error) as call,
                  self.assertRaises(exception)):
                api.chat('system', {'status': code}, validate, 256)
            self.assertEqual(call.call_count, 1)
        with (patch.object(a.urllib.request, 'urlopen', return_value=self.response({'key_facts': ['a', 'b']}, model='wrong')),
              self.assertRaises(a.APIError)):
            api.chat('system', {'sample': 'wrong'}, validate, 256)
        self.assertFalse((self.runtime / 'responses').exists())

    def test_truncation_increases_output_budget(self):
        api = self.api_context()
        validate = load_stage('0_extract_key_facts').validate_key_facts
        with (patch.object(a.urllib.request, 'urlopen', side_effect=[
              self.response({}, finish='length'), self.response({'key_facts': ['a', 'b']})]) as call,
              patch.object(a.time, 'sleep')):
            api.chat('system', {'sample': 'length'}, validate, 256)
        self.assertEqual(json.loads(call.call_args_list[0].args[0].data)['max_tokens'], 256)
        self.assertGreater(json.loads(call.call_args_list[1].args[0].data)['max_tokens'], 256)

    def test_v4_revised_screening_is_checkpointed_and_revalidated(self):
        module = load_stage('4_generate_fusion_question')
        api = self.api_context()
        sample = {'prompt': 'What does “return” do?\u2003\n', 'completion': 'Returns a value.'}
        screen = {'feasible': True, 'reason': 'The sample supports the revised task.',
                  'selected_samples': {'computer_science': [sample]},
                  'question_plan': 'Return the calculated circle area.',
                  'answer_plans': [{'type': kind, 'missing_domain': 'mathematics' if kind == 'missing_domain_knowledge' else None,
                                    'plan': 'Plan for ' + kind} for kind in
                      ('correct', 'missing_domain_knowledge', 'parallel_knowledge', 'incorrect_domain_relation')],
                  'required_key_facts': {'computer_science': [
                      {'key_fact': phrase, 'necessity': 'Needed to return the calculation.'}
                      for phrase in ('return statement', 'function value', 'return expression')]}}
        validate = lambda value: module.validate_screening(value, 'mathematics', ['computer_science'],
            {'computer_science': {(sample['prompt'], sample['completion'])}})
        invalid = copy.deepcopy(screen)
        invalid['selected_samples']['computer_science'][0]['prompt'] = sample['prompt'].rstrip().replace('“', '\u0000')
        payload = {'sample': 'circle', 'retrieved_samples': {'computer_science': [sample]}}
        with (patch.object(a.urllib.request, 'urlopen', side_effect=[self.response(invalid), self.response(screen)]) as call,
              patch.object(a.time, 'sleep')):
            result = api.chat('v4 screen', payload, validate, 4096)
        feedback = json.loads(call.call_args_list[1].args[0].data)['messages'][-1]['content']
        self.assertIn(json.dumps(sample, ensure_ascii=False), feedback)
        self.assertIn('U+201C', feedback)
        self.assertIn('U+2003', feedback)
        self.assertEqual(a.LOCAL.context['screening'], result)
        del a.LOCAL.context['screening']
        with patch.object(a.urllib.request, 'urlopen', side_effect=AssertionError('Network on cache replay')):
            cached = api.chat('v4 screen', payload, validate, 4096)
        self.assertEqual(a.LOCAL.context['screening'], cached)
        self.assertEqual(cached['question_plan'], screen['question_plan'])

    def test_v4_infeasible_retry_explains_nulls_and_domain_keys(self):
        module = load_stage('4_generate_fusion_question')
        api = self.api_context()
        invalid = {'feasible': False, 'reason': 'No coherent joint task.',
                   'selected_samples': {'chemistry': []},
                   'question_plan': None, 'answer_plans': None, 'required_key_facts': {}}
        corrected = {**invalid, 'required_key_facts': None}
        validate = lambda value: module.validate_screening(value, 'medical', ['chemistry'], {'chemistry': set()})
        with (patch.object(a.urllib.request, 'urlopen', side_effect=[self.response(invalid), self.response(corrected)]) as call,
              patch.object(a.time, 'sleep')):
            result = api.chat('screen', {'fusion_domains': ['chemistry']}, validate, 4096)
        feedback = json.loads(call.call_args_list[1].args[0].data)['messages'][-1]['content']
        self.assertIn('required_key_facts must each be JSON null', feedback)
        self.assertIn('"chemistry": []', feedback)
        self.assertFalse(result['feasible'])
        self.assertEqual(a.LOCAL.context['screening'], result)


if __name__ == '__main__':
    unittest.main(verbosity=2)
