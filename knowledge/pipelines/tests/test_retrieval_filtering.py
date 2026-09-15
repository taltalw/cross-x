"""Offline regression checks; no external API calls or model downloads."""

import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


r = load("retrieval", "3_retrieve_knowledge.py")
f = load("filtering", "4_filter_knowledge.py")
from _knowledge_search_common import APIError, JSONAPI, output_jobs


def query_row():
    return {"source_domain": "chemistry", "sample": {"prompt": "Identify the compound.", "completion": "Compound X."},
            "fusion_domains": ["medical"], "fusion_idea": "Use medical knowledge to assess exposure.",
            "queries": {"medical": ["heart injury", "cardiac injury", "cardiac damage"]}}


def candidate(name="one", answer="Exposure injures the heart."):
    return {"candidate_id": "medical:" + name, "source_file": "/corpus/medical/train.jsonl", "source_line": 1,
            "sample": {"prompt": "Which organ is injured?", "completion": answer}}


def kept(c):
    return {"candidate_id": c["candidate_id"], "keep": True, "supported_knowledge": "Exposure can cause cardiac injury.",
            "reason": "The answer supports the needed effect.",
            "evidence": [{"field": "completion", "quote": c["sample"]["completion"]}]}




class RetrievalTests(unittest.TestCase):
    def test_bm25_scores_and_zero_matches(self):
        index = r.BM25(["heart injury", "kidney injury", "kidney kidney"])
        found = index.search("heart", 10)
        self.assertEqual([i for i, _ in found], [0])
        self.assertAlmostEqual(found[0][1], np.log(1 + 2.5 / 1.5))
        self.assertEqual(index.search("unknown", 10), [])
        self.assertEqual(index.search("the and", 10), [])

    def test_rrf_uses_rank_and_deduplicates(self):
        found = r.fuse([(1, "bm25", [(1, 100), (2, 99)]), (2, "embedding", [(2, 0.1)])], 2, 60)
        self.assertEqual([v[0] for v in found], [2, 1])
        self.assertAlmostEqual(found[0][1], 1 / 62 + 1 / 61)
        self.assertEqual(len(found[0][2]), 2)




    def test_empty_corpus_and_explicit_bm25(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stderr(io.StringIO()):
            root = Path(temp); (root / "medical").mkdir()
            (root / "medical/train.jsonl").write_text("")
            result = r.Retriever(root).retrieve(query_row())
            self.assertEqual(result["candidates"], {"medical": []})
            self.assertEqual(result["retrieval"]["method"], "bm25")


class FilteringTests(unittest.TestCase):
    def test_evidence_grounding_and_id_validation(self):
        c = candidate()
        self.assertEqual(f.validate_decisions({"decisions": [kept(c)]}, [c])["decisions"][0], kept(c))
        for change in [lambda d: d.update(candidate_id="medical:invented"),
                       lambda d: d.update(keep="true"),
                       lambda d: d.update(evidence=[]),
                       lambda d: d["evidence"][0].update(quote="Invented treatment.")]:
            decision = kept(c); change(decision)
            with self.assertRaises(ValueError):
                f.validate_decisions({"decisions": [decision]}, [c])
        with self.assertRaises(ValueError):
            f.validate_decisions({"decisions": []}, [c])

    def test_coverage_rules(self):
        candidates = [candidate()]
        for result in [
            {"status": "sufficient", "selected_ids": [], "missing_knowledge": ""},
            {"status": "partial", "selected_ids": ["medical:one"], "missing_knowledge": ""},
            {"status": "none", "selected_ids": ["medical:one"], "missing_knowledge": "Need evidence"},
            {"status": "sufficient", "selected_ids": ["medical:unknown"], "missing_knowledge": ""},
            {"status": "sufficient", "selected_ids": ["medical:one"] * 2, "missing_knowledge": ""},
        ]:
            with self.assertRaises(ValueError):
                f.validate_coverage(result, candidates, 3)

    def test_end_to_end_filter_and_cache(self):
        class API:
            base_url, model = "https://judge.invalid/v1", "test-judge"
            calls = 0

            def chat(self, prompt, data, validate, max_tokens):
                self.calls += 1
                if prompt == f.FILTER_PROMPT:
                    decisions = []
                    for c in data["candidates"]:
                        decisions.append(kept(c) if c["candidate_id"] == "medical:one" else {
                            "candidate_id": c["candidate_id"], "keep": False, "supported_knowledge": "",
                            "reason": "Does not address the required mechanism.", "evidence": []})
                    return validate({"decisions": decisions})
                return validate({"status": "partial", "selected_ids": ["medical:one"], "missing_knowledge": "Exposure management evidence is missing."})

        with tempfile.TemporaryDirectory() as temp:
            api = API(); judge = f.CachedJudge(api, Path(temp) / "cache.sqlite3")
            row = {**query_row(), "candidates": {"medical": [candidate(), candidate("two", "The kidney.")]}}
            result = f.filter_row(row, judge, batch_size=1)
            self.assertEqual(api.calls, 3)
            self.assertEqual(result["knowledge"]["medical"]["status"], "partial")
            self.assertEqual(result["knowledge"]["medical"]["materials"][0]["sample"], candidate()["sample"])
            self.assertEqual(len(result["knowledge"]["medical"]["materials"]), 1)
            self.assertEqual(f.filter_row(row, judge, batch_size=1), result)
            self.assertEqual(api.calls, 3)
            judge.close()

    def test_empty_candidates_require_no_llm(self):
        class Judge:
            def ask(self, *args):
                raise AssertionError("No LLM needed")
        result = f.filter_row({**query_row(), "candidates": {"medical": []}}, Judge())
        self.assertEqual(result["knowledge"]["medical"]["status"], "none")

    def test_context_guard_never_truncates(self):
        class API:
            base_url, model = "https://judge.invalid/v1", "test"
            def chat(self, *args):
                raise AssertionError("Should reject before API call")
        with tempfile.TemporaryDirectory() as temp:
            judge = f.CachedJudge(API(), Path(temp) / "cache.sqlite3", max_input_chars=20)
            with self.assertRaisesRegex(ValueError, "full sample required"):
                list(f.filtering_batches([candidate()], {}, judge, 5))
            judge.close()

    def test_http_validation_retry_and_configuration_failure(self):
        import urllib.error
        api = JSONAPI("https://mock.invalid/v1", "unused", "mock", retries=1)
        bodies = [io.BytesIO(b'{"bad": 1}'), io.BytesIO(b'{"ok": true}')]
        with patch("urllib.request.urlopen", side_effect=bodies) as request, patch("time.sleep"):
            self.assertTrue(api.request("/test", {}, lambda v: v["ok"]))
            self.assertEqual(request.call_count, 2)
        with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError("https://mock.invalid", 401, "Unauthorized", {}, None)) as request:
            with self.assertRaises(APIError):
                api.request("/test", {}, lambda v: v)
            self.assertEqual(request.call_count, 1)


class IntegrationTests(unittest.TestCase):
    def test_output_collisions_and_partial_failure(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stderr(io.StringIO()):
            root = Path(temp); source = root / "in.jsonl"; target = root / "out.jsonl"
            source.write_text(json.dumps(query_row()) + "\n" + json.dumps(query_row()) + "\n")
            with self.assertRaises(ValueError):
                output_jobs([source], source, root, "3", True)
            class Retriever:
                calls = 0
                def retrieve(self, row):
                    self.calls += 1
                    if self.calls == 2:
                        raise ValueError("missing saved query")
                    return row
            with self.assertRaises(ValueError):
                r.run_file(source, target, Retriever())
            self.assertEqual(len(target.read_text().splitlines()), 1)
            with self.assertRaises(FileExistsError):
                output_jobs([source], target, root, "3", False)

    def test_bilingual_english_parity(self):
        doc = (ROOT / "4_filter_knowledge_prompt_bilingual.md").read_text()
        english = doc.split("## English Template: Candidate Filtering\n\n", 1)[1]
        self.assertEqual(english, f.FILTER_PROMPT + "\n## English Template: Knowledge Coverage\n\n" + f.COVERAGE_PROMPT)

    def test_group_shell_mappings(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); log = root / "calls.jsonl"; fake = root / "fake-python"
            fake.write_text('''#!/usr/bin/env python3
import json, os, sys
with open(os.environ['TEST_CALL_LOG'], 'a') as f:
 f.write(json.dumps({'args':sys.argv[1:],'model':os.environ.get('MODEL'),'url':os.environ.get('API_BASE_URL'),'key':os.environ.get('API_KEY')})+'\\n')
''')
            fake.chmod(0o755)
            for group in ("results_5.5", "results_6"):
                for stage in ("2_generate_knowledge_queries", "3_retrieve_knowledge"):
                    directory = root / group / stage; directory.mkdir(parents=True)
                    for name in ("medical_domain_count_2.jsonl", "file with spaces.jsonl"):
                        (directory / name).write_text("{}\n")
            env = dict(os.environ, KNOWLEDGE_ROOT=str(root), PYTHON_BIN=str(fake), TEST_CALL_LOG=str(log), METHOD="bm25")
            for suffix in ("5_5", "6"):
                for key in ("API_BASE_URL", "API_KEY", "MODEL"):
                    env[f"{key}_{suffix}"] = f"test-{key}-{suffix}"
            for script in ("run_3_retrieve_knowledge.sh", "run_4_filter_knowledge.sh"):
                subprocess.run(["bash", str(ROOT / script), "--overwrite"], cwd=temp, env=env, check=True)
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(len(calls), 4)
            for index, call in enumerate(calls):
                args = call["args"]
                group = "results_5.5" if index % 2 == 0 else "results_6"
                stage = "3_retrieve_knowledge" if index < 2 else "4_filter_knowledge"
                self.assertEqual(Path(args[args.index("--output-root") + 1]), root / group / stage)
                paths = args[args.index("--input") + 1:args.index("--output-root")]
                self.assertEqual(len(paths), 2)
                self.assertTrue(all(Path(p).is_file() for p in paths))
                if index >= 2:
                    suffix = "5_5" if group == "results_5.5" else "6"
                    for actual, name in (("model", "MODEL"), ("url", "API_BASE_URL"), ("key", "API_KEY")):
                        self.assertEqual(call[actual], env[f"{name}_{suffix}"])


if __name__ == "__main__":
    unittest.main()
