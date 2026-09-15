"""Offline embedding integration checks without model downloads or inference APIs."""

import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from _offline_embeddings import EmbeddingStore, LocalQwenEncoder, last_token_pool, token_windows
from embed_knowledge import corpus_inputs, query_inputs


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


r = load("retrieve_offline", "3_retrieve_knowledge.py")
f = load("filter_offline", "4_filter_knowledge.py")


class FakeEncoder:
    """Deterministic fixture only; never used as a production embedding backend."""
    def __init__(self):
        self.calls = 0
        self.config = {"format_version": 1, "model": "test-encoder", "revision": "test-commit", "dimension": 3,
                       "max_length": 24, "chunk_overlap_tokens": 4, "query_instruction": "Retrieve domain knowledge."}

    def document_sequences(self, text):
        return list(token_windows([ord(char) for char in text], 24, 4))

    def query_sequence(self, domain, query):
        return [ord(c) for c in domain + ":" + query]

    def encode_sequences(self, sequences):
        self.calls += 1
        return np.array([[sum(ids) % 17 + 1, len(ids) + 1, 2] for ids in sequences], dtype=np.float32)


def sample(question="What does cardiac injury affect?", answer="The heart."):
    return {"prompt": question, "completion": answer}


def query_row():
    return {"source_domain": "chemistry", "sample": sample("Identify compound X.", "X."),
            "fusion_domains": ["medical"], "fusion_idea": "Assess the effects of the exposure.",
            "queries": {"medical": ["heart injury", "cardiac effect", "exposure treatment"]}}


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.domain = self.root / "atomic/medical"
        self.domain.mkdir(parents=True)
        self.path = self.domain / "train.jsonl"
        self.path.write_text("\n" + json.dumps(sample()) + "\n" + json.dumps(sample()) + "\n")
        self.encoder = FakeEncoder()
        self.store = EmbeddingStore(self.root / "embeddings", self.encoder.config)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def build(self):
        return self.store.build_corpus("medical", [self.path], self.encoder, batch_size=2)

    def test_corpus_dedup_provenance_vectors_and_cache(self):
        report = self.build()
        self.assertEqual(report["samples"], 1)
        self.assertGreater(report["chunks"], 1)
        rows, vectors, mapping, manifest = self.store.load_corpus("medical")
        self.assertEqual(rows[0]["sample"], sample())
        self.assertEqual(rows[0]["source_line"], 2)
        self.assertEqual(rows[0]["candidate_id"], "medical:" + r.sample_hash(sample()))
        np.testing.assert_allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-5)
        self.assertEqual(set(mapping), {0})
        calls = self.encoder.calls
        self.assertEqual(self.build()["status"], "cached")
        self.assertEqual(self.encoder.calls, calls)
        with self.assertRaises(ValueError):
            self.store.load_corpus("medical", ["dev"])

    def test_changed_corpus_requires_explicit_replace(self):
        self.build()
        extra = sample("Which organ is next?", "The kidney.")
        with self.path.open("a") as stream:
            stream.write(json.dumps(extra) + "\n")
        with self.assertRaisesRegex(ValueError, "replace-corpus"):
            self.build()
        original_encode = self.encoder.encode_sequences
        self.encoder.encode_sequences = lambda _: (_ for _ in ()).throw(RuntimeError("simulated interruption"))
        with self.assertRaises(RuntimeError):
            self.store.build_corpus("medical", [self.path], self.encoder, batch_size=2, replace=True)
        self.assertEqual(len(self.store.load_corpus("medical")[0]), 1)
        self.encoder.encode_sequences = original_encode
        self.store.build_corpus("medical", [self.path], self.encoder, batch_size=2, replace=True)
        self.assertEqual(len(self.store.load_corpus("medical")[0]), 2)

    def test_query_cache_domains_and_missing_query(self):
        pairs = [("medical", "heart injury"), ("medical", "heart injury"), ("legal", "heart injury")]
        with contextlib.redirect_stderr(io.StringIO()):
            result = self.store.build_queries(pairs, self.encoder, 2)
        self.assertEqual(result, {"queries": 2, "new_queries": 2})
        calls = self.encoder.calls
        self.assertEqual(self.store.build_queries(pairs, self.encoder)["new_queries"], 0)
        self.assertEqual(self.encoder.calls, calls)
        self.assertEqual(self.store.query_vectors("medical", ["heart injury"]).shape, (1, 3))
        with self.assertRaisesRegex(ValueError, "kind queries"):
            self.store.query_vectors("medical", ["not encoded"])

    def test_wrong_model_config_rejected(self):
        config = copy.deepcopy(self.encoder.config)
        config["model"] = "another-model"
        with self.assertRaisesRegex(ValueError, "differ"):
            EmbeddingStore(self.root / "embeddings", config)

    def test_cpu_retrieval_uses_snapshot_and_saved_queries(self):
        self.build()
        row = query_row()
        with contextlib.redirect_stderr(io.StringIO()):
            self.store.build_queries([("medical", q) for q in row["queries"]["medical"]], self.encoder)
        # Retrieval is self-contained even if original JSONL is subsequently moved.
        self.path.unlink()
        readonly = EmbeddingStore(self.root / "embeddings", readonly=True)
        try:
            retriever = r.Retriever(self.root / "absent", splits=None, offline_store=readonly)
            with contextlib.redirect_stderr(io.StringIO()):
                result = retriever.retrieve(row)
            f.validate_candidates(result)
            self.assertEqual(result["retrieval"]["method"], "hybrid")
            self.assertEqual(result["retrieval"]["embedding_source"], "precomputed")
            self.assertTrue(any(h["method"] == "embedding" for h in result["candidates"]["medical"][0]["hits"]))
            self.assertEqual(result["candidates"]["medical"][0]["sample"], sample())
            self.assertEqual(result["retrieval"]["splits"], {"medical": ["train"]})
            # Exercise the real CLI, without credentials or loading an encoder.
            input_file, output_file = self.root / "query.jsonl", self.root / "retrieved.jsonl"
            input_file.write_text(json.dumps(row) + "\n")
            env = dict(os.environ)
            # Stale configuration from embedding/API experiments must not affect retrieval.
            for key in ("EMBEDDING_MODEL", "EMBEDDING_BASE_URL", "EMBEDDING_API_KEY",
                        "EMBEDDING_DOCUMENT_PREFIX", "EMBEDDING_QUERY_PREFIX"):
                env[key] = "unused-stale-value"
            env["EMBEDDING_SOURCE"] = "api"
            run = subprocess.run([sys.executable, str(ROOT / "3_retrieve_knowledge.py"), "--input", str(input_file),
                                  "--output", str(output_file), "--embedding-root", str(self.root / "embeddings")],
                                 env=env, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            f.validate_candidates(json.loads(output_file.read_text()))
            help_output = subprocess.run([sys.executable, str(ROOT / "3_retrieve_knowledge.py"), "--help"],
                                         capture_output=True, text=True, check=True).stdout
            for obsolete in ("--embedding-model", "--embedding-source", "--embedding-api-key", "--embedding-base-url"):
                self.assertNotIn(obsolete, help_output)
        finally:
            readonly.close()

    def test_empty_and_missing_corpus(self):
        self.path.write_text("")
        self.build()
        rows, matrix, docs, _ = self.store.load_corpus("medical")
        self.assertEqual(rows, [])
        self.assertEqual(matrix.shape, (0, 3))
        self.assertEqual(docs.size, 0)
        with self.assertRaisesRegex(ValueError, "no saved corpus"):
            self.store.load_corpus("legal")


class EncoderTests(unittest.TestCase):
    def test_token_windows_keep_tail(self):
        ids = list(range(19))
        windows = list(token_windows(ids, 8, 2))
        self.assertEqual(windows, [ids[:8], ids[6:14], ids[12:]])
        self.assertEqual({v for part in windows for v in part}, set(ids))
        with self.assertRaises(ValueError):
            list(token_windows(ids, 8, 8))

    def test_pooling_handles_left_right_and_empty_padding(self):
        import torch
        hidden = torch.arange(24).reshape(2, 4, 3)
        mask = torch.tensor([[0, 0, 1, 1], [1, 1, 0, 0]])
        pooled = last_token_pool(hidden, mask)
        self.assertTrue(torch.equal(pooled, torch.stack([hidden[0, 3], hidden[1, 1]])))
        with self.assertRaises(ValueError):
            last_token_pool(hidden, torch.zeros_like(mask))

    def test_query_instruction_and_no_truncation(self):
        class Tokenizer:
            last_text = None
            def encode(self, text, add_special_tokens, truncation):
                assert truncation is False
                self.last_text = text
                return list(range(len(text)))
            def build_inputs_with_special_tokens(self, ids):
                return ids
        encoder = LocalQwenEncoder.__new__(LocalQwenEncoder)
        encoder.tokenizer = Tokenizer()
        encoder.max_length, encoder.overlap, encoder.special_tokens = 300, 10, 0
        encoder.instruction = "Retrieve samples."
        encoder.query_sequence("medical", "heart injury")
        self.assertEqual(encoder.tokenizer.last_text, "Instruct: Retrieve samples. Target domain: medical.\nQuery:heart injury")
        encoder.max_length = 20
        with self.assertRaisesRegex(ValueError, "not truncated"):
            encoder.query_sequence("medical", "heart injury")
        parts = encoder.document_sequences("a" * 55)
        self.assertEqual(parts[-1][-1], 54)


class InputAndScriptTests(unittest.TestCase):
    def test_file_and_directory_input_discovery(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); domain = root / "atomic/medical"; domain.mkdir(parents=True)
            (domain / "train.jsonl").write_text(json.dumps(sample()) + "\n")
            expected = {"medical": [(domain / "train.jsonl").resolve()]}
            self.assertEqual(corpus_inputs([root / "atomic"], ["train"]), expected)
            self.assertEqual(corpus_inputs([domain], ["train"]), expected)
            self.assertEqual(corpus_inputs([domain / "train.jsonl"], ["train"]), expected)
            qdir = root / "queries"; qdir.mkdir()
            for name in ("one.jsonl", "two.jsonl"):
                (qdir / name).write_text(json.dumps(query_row()) + "\n")
            self.assertEqual(len(query_inputs([qdir])), 3)
            with self.assertRaises(FileNotFoundError):
                corpus_inputs([domain], ["dev"])

    def test_embedding_script_paths_and_query_groups(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); log = root / "calls"; fake = root / "fake-python"
            fake.write_text("#!/usr/bin/env python3\nimport json,os,sys\nassert os.environ['CUDA_VISIBLE_DEVICES']=='0'\nwith open(os.environ['TEST_CALL_LOG'],'a') as f:f.write(json.dumps(sys.argv[1:])+'\\n')\n")
            fake.chmod(0o755)
            env = dict(os.environ, KNOWLEDGE_ROOT=str(root), PYTHON_BIN=str(fake), TEST_CALL_LOG=str(log),
                       EMBEDDING_MODEL="Qwen/Qwen3-Embedding-4B", EMBEDDING_ROOT=str(root / "4b"), EMBEDDING_DEVICE="cpu")
            subprocess.run(["bash", str(ROOT / "run_embed_knowledge.sh")], cwd=temp, env=env, check=True)
            calls = [json.loads(v) for v in log.read_text().splitlines()]
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0][calls[0].index("--kind") + 1], "corpus")
            self.assertEqual(calls[1][calls[1].index("--kind") + 1], "queries")
            for args in calls:
                self.assertEqual(args[args.index("--embedding-root") + 1], str(root / "embeddings/Qwen3-Embedding-8B"))
                self.assertEqual(args[args.index("--model") + 1], "Qwen/Qwen3-Embedding-8B")
                self.assertEqual(args[args.index("--dtype") + 1], "bfloat16")
                self.assertEqual(args[args.index("--device") + 1], "cuda:0")
                self.assertEqual(args[args.index("--batch-size") + 1], "8")
                self.assertNotIn("--local-files-only", args)
            self.assertIn(str(root / "results_5.5/2_generate_knowledge_queries"), calls[1])
            self.assertIn(str(root / "results_6/2_generate_knowledge_queries"), calls[1])


if __name__ == "__main__":
    unittest.main()
