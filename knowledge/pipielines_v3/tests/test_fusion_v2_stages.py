"""Offline integration checks for v3 stages 1-4."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import copy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


s1 = load("stage1", "1_generate_fusion_plans.py")
s2 = load("stage2", "2_extract_required_key_facts.py")
s3 = load("stage3", "3_retrieve_key_fact_matches.py")
s4 = load("stage4", "4_generate_fusion_question.py")
e = load("v2_embed", "embed_required_key_facts.py")
from _pipeline_common import retrieval_query_row, validate_domain_configuration, validate_selected_plan, row_domains


class FakeAPI:
    model = "offline-model"

    def __init__(self, screen_sufficient=True):
        self.calls = []
        self.screen_sufficient = screen_sufficient

    def chat(self, prompt, data, validate, max_tokens):
        self.calls.append(data)
        if "question_plan" not in data:
            value = {
                "fusion_domains": ["medical", "legal"],
                "question_plan": "Assess how a site's exposure pattern, medical effects, and legal duty combine in one decision.",
                "answer_plans": [
                    {"type": "correct", "missing_domain": None, "plan": "Use all three domains together."},
                    {"type": "missing_domain_knowledge", "missing_domain": "medical", "plan": "Omit the exposure mechanism."},
                    {"type": "parallel_knowledge", "missing_domain": None, "plan": "List each domain conclusion separately."},
                    {"type": "incorrect_domain_relation", "missing_domain": None, "plan": "Reverse the relationship between exposure and duty."},
                ],
            }
        elif "required_key_facts" not in data:
            value = {"required_key_facts": {
                "medical": [{"key_fact": "exposure mechanism", "necessity": "Connect exposure to health."},
                             {"key_fact": "dose response", "necessity": "Distinguish outcomes."},
                             {"key_fact": "clinical risk", "necessity": "Supply the health threshold."}],
                "legal": [{"key_fact": "liability duty", "necessity": "Supply the duty rule."},
                           {"key_fact": "causation standard", "necessity": "Connect facts to duty."},
                           {"key_fact": "remedy condition", "necessity": "Set the consequence."}],
            }}
        elif "difficulty" not in data:
            value = {"sufficient": self.screen_sufficient,
                     "reason": "All needs are supported." if self.screen_sufficient else "The retrieved samples do not support the plan.",
                     "supporting_samples": {
                         domain: [samples[0]] if self.screen_sufficient else []
                         for domain, samples in data["retrieved_samples"].items()
                     }}
        else:
            samples = data["retrieved_samples"]
            used = {domain: [samples[domain][0]] for domain in data["fusion_domains"]}
            value = {"question": "Which joint conclusion follows?", "options": {"A": "Correct integrated conclusion.", "B": "Missing mechanism conclusion.", "C": "Parallel conclusion.", "D": "Reversed relation conclusion."},
                     "answer": "A", "explanation": "All domains are necessary.",
                     "distractor_analysis": [
                         {"option": "B", "type": "missing_domain_knowledge", "missing_domain": "medical", "reason": "The mechanism is omitted."},
                         {"option": "C", "type": "parallel_knowledge", "missing_domain": None, "reason": "The facts are not connected."},
                         {"option": "D", "type": "incorrect_domain_relation", "missing_domain": None, "reason": "The relation is reversed."}],
                     "used_samples": used, "plan_adjustment": ""}
        return validate(value)


class FixtureEncoder:
    # Fixture vectors exercise saved-vector retrieval without downloading a model.
    config = {'format_version': 1, 'model': 'fixture', 'revision': 'fixture', 'dimension': 3,
              'max_length': 128, 'chunk_overlap_tokens': 0, 'query_instruction': 'fixture'}

    def document_sequences(self, text):
        return [[ord(c) for c in text]]

    def query_sequence(self, domain, query):
        return [ord(c) for c in domain + query]

    def encode_sequences(self, sequences):
        return np.array([[sum(ids) % 13 + 1, len(ids), 1] for ids in sequences], dtype=np.float32)


class StageTests(unittest.TestCase):
    def test_end_to_end_plan_required_facts_retrieval_generation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.jsonl"
            source.write_text(json.dumps({"source_file": "source.jsonl", "source_domain": "geography", "model": "source-model",
                                          "sample": {"prompt": "A site exposure question", "completion": "The site answer"},
                                          "key_facts": ["site exposure", "spatial context"]}) + "\n")
            plans = root / "plans.jsonl"
            required = root / "required.jsonl"
            retrieved = root / "retrieved.jsonl"
            generated = root / "generated.jsonl"
            api = FakeAPI()
            s1.process(source, plans, api=api, domain_count=3, num=None, max_tokens=100, overwrite=False)
            s2.process(plans, required, api=api, domain_count=3, num=None, max_tokens=100, overwrite=False)

            corpus = root / "corpus"
            for domain, facts in (("medical", ["exposure mechanism", "dose response", "clinical risk"]),
                                  ("legal", ["liability duty", "causation standard", "remedy condition"])):
                path = corpus / domain / "test.jsonl"
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps({"source_file": str(path), "source_domain": domain, "model": "source-model",
                                            "sample": {"prompt": f"A {domain} sample", "completion": " ".join(facts)},
                                            "key_facts": facts}) + "\n")
            # Build a real store with deterministic fixture vectors, then retrieve read-only.
            encoder = FixtureEncoder()
            store_root = root / 'embeddings'
            with_store = s3.EmbeddingStore(store_root, encoder.config)
            try:
                atomic = root / 'atomic'
                for domain in ['medical', 'legal']:
                    path = atomic / domain / 'test.jsonl'
                    path.parent.mkdir(parents=True)
                    annotation = json.loads((corpus / domain / 'test.jsonl').read_text())
                    path.write_text(json.dumps(annotation['sample']) + '\n')
                    with_store.build_corpus(domain, [path], encoder)
                pairs = e.query_inputs([required])
                self.assertEqual(len(pairs), 6)
                with_store.build_queries(pairs, encoder)
                with_store.build_queries([('medical', 'cardiac physiology')], encoder)
            finally:
                with_store.close()
            store = s3.EmbeddingStore(store_root, readonly=True)
            try:
                retriever = s3.backend.Retriever(atomic, ['test'], 3, 2, 60, store)
                s3.process(required, retrieved, [corpus], retriever=retriever,
                           domain_count=3, num=None, overwrite=False)
                row = json.loads(required.read_text())
                self.assertEqual(retrieval_query_row(row)['fusion_idea'], row['question_plan'])
                # Semantic retrieval can return material without shared lexical tokens.
                semantic = copy.deepcopy(row)
                semantic['required_key_facts']['medical'][0]['key_fact'] = 'cardiac physiology'
                semantic_result = s3.retrieve(semantic, retriever, s3.collect_annotations([corpus]))
                first_query_hits = [h for c in semantic_result['retrieved_samples']['medical']
                                    for h in c['hits'] if h['query_index'] == 1]
                self.assertEqual({h['method'] for h in first_query_hits}, {'embedding'})
                skipped = s3.retrieve(row, retriever, {})
                self.assertTrue(skipped['retrieval']['skipped_unannotated_candidates']['medical'])
                missing = copy.deepcopy(row)
                missing['required_key_facts']['medical'][0]['key_fact'] = 'unembedded query'
                with self.assertRaisesRegex(ValueError, 'missing saved query embedding'):
                    s3.retrieve(missing, retriever, s3.collect_annotations([corpus]))
            finally:
                store.close()
            report = s4.process(retrieved, generated, api=api, domain_count=3,
                                num=None, max_tokens=100, max_input_chars=100000, overwrite=False)
            results = [json.loads(line) for line in generated.read_text().splitlines()]
            self.assertEqual((report["processed"], report["skipped"], report["generated"]), (1, 0, 3))
            self.assertEqual([item["difficulty"] for item in results], ["easy", "medium", "hard"])
            self.assertEqual([call["difficulty"] for call in api.calls if "difficulty" in call], ["easy", "medium", "hard"])
            result = results[0]
            self.assertEqual(result["fusion_domains"], ["medical", "legal"])
            self.assertNotIn('fusion_domains', api.calls[0])
            self.assertEqual(len(api.calls[0]['candidate_domains']), 6)
            self.assertNotIn('geography', [d['name'] for d in api.calls[0]['candidate_domains']])
            self.assertEqual(api.calls[1]['fusion_domains'], result['fusion_domains'])
            self.assertEqual(api.calls[1]['question_plan'], result['question_plan'])
            self.assertEqual(result['retrieval']['method'], 'hybrid')
            retrieved_row = json.loads(retrieved.read_text())
            methods = {h['method'] for c in retrieved_row['retrieved_samples']['medical'] for h in c['hits']}
            self.assertEqual(methods, {'bm25', 'embedding'})
            self.assertEqual(set(result['retrieved_samples']['medical'][0]), {'prompt', 'completion'})
            self.assertEqual(result['used_samples']['medical'], [result['retrieved_samples']['medical'][0]])
            self.assertIsInstance(result["question_plan"], str)
            self.assertIn("answer_plans", result)
            self.assertIn("retrieved_samples", result)
            self.assertEqual(set(result["options"]), {"A", "B", "C", "D"})
            self.assertEqual(len(result["required_key_facts"]["medical"]), 3)
            self.assertEqual(set(result["required_key_facts"]["medical"][0]), {"key_fact", "necessity"})

            rejected = root / "rejected.jsonl"
            reject_api = FakeAPI(screen_sufficient=False)
            report = s4.process(retrieved, rejected, api=reject_api, domain_count=3,
                                num=None, max_tokens=100, max_input_chars=100000, overwrite=False)
            self.assertEqual((report["processed"], report["skipped"], report["generated"]), (1, 1, 0))
            self.assertEqual(rejected.read_text(), "")
            self.assertEqual(len(reject_api.calls), 1)

            empty_retrieval = json.loads(retrieved.read_text())
            empty_retrieval["retrieved_samples"]["medical"] = []
            empty_input = root / "empty-retrieval.jsonl"
            empty_input.write_text(json.dumps(empty_retrieval) + "\n")
            empty_api = FakeAPI()
            report = s4.process(empty_input, root / "empty-generated.jsonl", api=empty_api,
                                domain_count=3, num=None, max_tokens=100,
                                max_input_chars=100000, overwrite=False)
            self.assertEqual((report["skipped"], report["generated"], empty_api.calls), (1, 0, []))

            narrowed_input = json.loads(retrieved.read_text())
            extra_candidate = copy.deepcopy(narrowed_input["retrieved_samples"]["medical"][0])
            extra_candidate["candidate_id"] = "medical:extra"
            extra_candidate["sample"]["prompt"] = "A different medical sample"
            narrowed_input["retrieved_samples"]["medical"].append(extra_candidate)
            narrowed_path = root / "narrowed-input.jsonl"
            narrowed_path.write_text(json.dumps(narrowed_input) + "\n")
            narrowed_api = FakeAPI()
            narrowed_output = root / "narrowed-output.jsonl"
            s4.process(narrowed_path, narrowed_output, api=narrowed_api, domain_count=3,
                       num=1, max_tokens=100, max_input_chars=100000, overwrite=False)
            generation_calls = [call for call in narrowed_api.calls if "difficulty" in call]
            self.assertTrue(generation_calls)
            self.assertTrue(all(len(call["retrieved_samples"]["medical"]) == 1 for call in generation_calls))
            self.assertEqual(len(json.loads(narrowed_output.read_text().splitlines()[0])["retrieved_samples"]["medical"]), 2)

            repeated_input = root / "repeated-retrieval.jsonl"
            repeated_input.write_text(retrieved.read_text() * 2)
            limited_api = FakeAPI(screen_sufficient=False)
            report = s4.process(repeated_input, root / "limited-output.jsonl", api=limited_api,
                                domain_count=3, num=1, max_tokens=100,
                                max_input_chars=100000, overwrite=False)
            self.assertEqual((report["processed"], report["skipped"], len(limited_api.calls)), (1, 1, 1))

    def test_screening_rejects_missing_or_wrong_domain_samples(self):
        required = {"medical": [{"key_fact": "dose response"}]}
        sample = {"prompt": "What is dose response?", "completion": "The effect changes with dose."}
        available = {"medical": {(sample["prompt"], sample["completion"])}}
        base = {"sufficient": True, "reason": "Supported.",
                "supporting_samples": {"medical": [sample]}}
        self.assertTrue(s4.validate_screening(base, required, available)["sufficient"])
        for samples in ([], [{"prompt": "Unrelated", "completion": "Other fact."}]):
            bad = copy.deepcopy(base)
            bad["supporting_samples"]["medical"] = samples
            with self.subTest(samples=samples), self.assertRaises(ValueError):
                s4.validate_screening(bad, required, available)

    def test_generation_rejects_samples_outside_the_supplied_domain(self):
        sample = {"prompt": "Medical question", "completion": "Medical answer"}
        available = {"medical": {(sample["prompt"], sample["completion"])}}
        value = {"question": "Which result follows?",
                 "options": {"A": "Correct", "B": "Missing", "C": "Parallel", "D": "Wrong relation"},
                 "answer": "A", "explanation": "Medical reasoning applies.",
                 "distractor_analysis": [
                     {"option": "B", "type": "missing_domain_knowledge", "missing_domain": "medical", "reason": "Missing fact."},
                     {"option": "C", "type": "parallel_knowledge", "missing_domain": None, "reason": "No link."},
                     {"option": "D", "type": "incorrect_domain_relation", "missing_domain": None, "reason": "Wrong link."}],
                 "used_samples": {"medical": [sample]}, "plan_adjustment": ""}
        self.assertEqual(s4.validate_generation(value, ["geography", "medical"], available)["used_samples"], {"medical": [sample]})
        bad = copy.deepcopy(value)
        bad["used_samples"]["medical"] = [{"prompt": "Invented", "completion": "Not supplied"}]
        with self.assertRaisesRegex(ValueError, "supplied samples"):
            s4.validate_generation(bad, ["geography", "medical"], available)

    def test_domain_count_must_match_domains(self):
        with self.assertRaises(ValueError):
            validate_domain_configuration(2, ["medical", "legal"], "geography")

    def test_model_domain_selection_validation(self):
        api = FakeAPI()
        result = api.chat('', {}, lambda value: value, 10)
        for domains in (['medical'], ['medical', 'medical'], ['geography', 'legal'], ['unknown', 'legal'], 'medical,legal'):
            bad = {**result, 'fusion_domains': domains}
            with self.subTest(domains=domains), self.assertRaises(ValueError):
                validate_selected_plan(bad, 'geography', 3)
        self.assertEqual(validate_selected_plan(result, 'geography', 3)['fusion_domains'], ['medical', 'legal'])
        for question_plan in ({'objective': 'old format'}, '', '  '):
            with self.subTest(question_plan=question_plan), self.assertRaises(ValueError):
                validate_selected_plan({**result, 'question_plan': question_plan}, 'geography', 3)

    def test_annotations_ignore_audit_and_detect_conflicts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'request_audit.jsonl').write_text('{"status":200}\n')
            directory = root / 'medical'
            directory.mkdir()
            row = {'source_domain': 'medical', 'sample': {'prompt': 'a', 'completion': 'b'}, 'key_facts': ['one', 'two']}
            (directory / 'train.jsonl').write_text(json.dumps(row) + '\n')
            self.assertEqual(len(s3.collect_annotations([root])), 1)
            (directory / 'dev.jsonl').write_text(json.dumps({**row, 'key_facts': ['three', 'four']}) + '\n')
            with self.assertRaisesRegex(ValueError, 'conflicting'):
                s3.collect_annotations([root])

    def test_downstream_count_mismatch(self):
        row = {'source_domain': 'geography', 'sample': {'prompt': 'a', 'completion': 'b'},
               'key_facts': ['one', 'two'], 'fusion_domains': ['medical', 'legal'], 'domain_count': 3}
        self.assertEqual(row_domains(row), ['medical', 'legal'])
        with self.assertRaisesRegex(ValueError, 'differs'):
            row_domains(row, 2)


if __name__ == "__main__":
    unittest.main()
