"""Offline integration checks for pipelines_v2 stages 1-4."""

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
from _pipeline_common import validate_domain_configuration, validate_selected_plan, row_domains


class FakeAPI:
    model = "offline-model"

    def __init__(self):
        self.calls = []

    def chat(self, prompt, data, validate, max_tokens):
        self.calls.append(data)
        if "question_plan" not in data:
            value = {
                "fusion_domains": ["medical", "legal"],
                "question_plan": {
                    "objective": "Assess a joint environmental health decision.",
                    "conditions": "Use the supplied site and exposure conditions.",
                    "domain_roles": [
                        {"domain": "geography", "role": "site context", "knowledge_needed": "spatial exposure pattern"},
                        {"domain": "medical", "role": "health effect", "knowledge_needed": "exposure mechanism"},
                        {"domain": "legal", "role": "duty", "knowledge_needed": "applicable liability rule"},
                    ],
                    "reasoning_link": "Combine site, health, and duty conditions.",
                },
                "answer_plans": [
                    {"type": "correct", "missing_domain": None, "plan": "Use all three domains together."},
                    {"type": "missing_domain_knowledge", "missing_domain": "medical", "plan": "Omit the exposure mechanism."},
                    {"type": "parallel_knowledge", "missing_domain": None, "plan": "List each domain conclusion separately."},
                    {"type": "incorrect_domain_relation", "missing_domain": None, "plan": "Reverse the relationship between exposure and duty."},
                ],
            }
        elif "required_key_facts" not in data:
            value = {"required_key_facts": {
                "medical": [{"key_fact": "exposure mechanism", "used_by": ["question", "correct"], "necessity": "Connect exposure to health."},
                             {"key_fact": "dose response", "used_by": ["correct", "missing_domain_knowledge"], "necessity": "Distinguish outcomes."},
                             {"key_fact": "clinical risk", "used_by": ["question", "parallel_knowledge"], "necessity": "Supply the health threshold."}],
                "legal": [{"key_fact": "liability duty", "used_by": ["question", "correct"], "necessity": "Supply the duty rule."},
                           {"key_fact": "causation standard", "used_by": ["correct", "missing_domain_knowledge"], "necessity": "Connect facts to duty."},
                           {"key_fact": "remedy condition", "used_by": ["question", "incorrect_domain_relation"], "necessity": "Set the consequence."}],
            }}
        else:
            candidates = data["retrieved_samples"]
            used = [candidates[domain][0]["candidate_id"] for domain in data["fusion_domains"]]
            value = {"question": "Which joint conclusion follows?", "options": {"A": "Correct integrated conclusion.", "B": "Missing mechanism conclusion.", "C": "Parallel conclusion.", "D": "Reversed relation conclusion."},
                     "answer": "A", "explanation": "All domains are necessary.",
                     "distractor_analysis": [
                         {"option": "B", "type": "missing_domain_knowledge", "missing_domain": "medical", "reason": "The mechanism is omitted."},
                         {"option": "C", "type": "parallel_knowledge", "missing_domain": None, "reason": "The facts are not connected."},
                         {"option": "D", "type": "incorrect_domain_relation", "missing_domain": None, "reason": "The relation is reversed."}],
                     "used_material_ids": used, "plan_adjustment": ""}
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
                # Semantic retrieval can return material without shared lexical tokens.
                semantic = copy.deepcopy(row)
                semantic['required_key_facts']['medical'][0]['key_fact'] = 'cardiac physiology'
                semantic_result = s3.retrieve(semantic, retriever, s3.collect_annotations([corpus]))
                first_query_hits = [h for c in semantic_result['retrieved_samples']['medical']
                                    for h in c['hits'] if h['query_index'] == 1]
                self.assertEqual({h['method'] for h in first_query_hits}, {'embedding'})
                with self.assertRaisesRegex(ValueError, 'missing key-fact annotation'):
                    s3.retrieve(row, retriever, {})
                missing = copy.deepcopy(row)
                missing['required_key_facts']['medical'][0]['key_fact'] = 'unembedded query'
                with self.assertRaisesRegex(ValueError, 'missing saved query embedding'):
                    s3.retrieve(missing, retriever, s3.collect_annotations([corpus]))
            finally:
                store.close()
            s4.process(retrieved, generated, api=api, domain_count=3,
                       num=None, max_tokens=100, max_input_chars=100000, overwrite=False)
            result = json.loads(generated.read_text())
            self.assertEqual(result["fusion_domains"], ["medical", "legal"])
            self.assertNotIn('fusion_domains', api.calls[0])
            self.assertEqual(len(api.calls[0]['candidate_domains']), 6)
            self.assertNotIn('geography', [d['name'] for d in api.calls[0]['candidate_domains']])
            self.assertEqual(api.calls[1]['fusion_domains'], result['fusion_domains'])
            self.assertEqual(result['retrieval']['method'], 'hybrid')
            methods = {h['method'] for c in result['retrieved_samples']['medical'] for h in c['hits']}
            self.assertEqual(methods, {'bm25', 'embedding'})
            self.assertIn("question_plan", result)
            self.assertIn("answer_plans", result)
            self.assertIn("retrieved_samples", result)
            self.assertEqual(set(result["options"]), {"A", "B", "C", "D"})
            self.assertEqual(len(result["required_key_facts"]["medical"]), 3)

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
