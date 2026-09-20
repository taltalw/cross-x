"""Offline checks for extraction, API validation, and output preservation."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "0_extract_key_facts.py"
spec = importlib.util.spec_from_file_location("key_facts", SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def response(value):
    return io.StringIO(json.dumps({"choices": [{"message": {"content": json.dumps(value)}}]}))


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "input.jsonl"
        self.output = Path(self.temp.name) / "output.jsonl"
        self.sample = {"prompt": "Is IPv4 header length variable?", "completion": "True", "id": "原始样本"}
        self.source.write_text("\n" + json.dumps(self.sample) + "\n" + json.dumps(self.sample) + "\n", encoding="utf-8")
        self.api = m.JSONAPI("https://mock.invalid/v1", "test-key", "test-model", retries=1)
        self.addCleanup(patch.stopall)
        patch("_knowledge_search_common.time.sleep").start()
        self.stderr = contextlib.redirect_stderr(io.StringIO())
        self.stderr.__enter__()
        self.addCleanup(self.stderr.__exit__, None, None, None)

    def test_request_and_output_keep_sample_and_physical_line(self):
        with patch("_knowledge_search_common.urllib.request.urlopen", return_value=response({
            "key_facts": ["IPv4 packet header", "variable header length"],
        })) as http:
            report = m.run_extraction(self.source, self.output, api=self.api, num=1, source_domain="computer_science")
        self.assertEqual(report["processed"], 1)
        self.assertEqual(http.call_count, 1)
        row = json.loads(self.output.read_text())
        self.assertEqual(row["sample"], self.sample)
        self.assertEqual(row["source_line"], 2)
        self.assertEqual(row["source_domain"], "computer_science")
        self.assertEqual(row["key_facts"], ["IPv4 packet header", "variable header length"])
        request = http.call_args.args[0]
        self.assertEqual(request.full_url, "https://mock.invalid/v1/chat/completions")
        payload = json.loads(request.data)
        data = json.loads(payload["messages"][1]["content"])
        self.assertEqual(data["sample"], {k: self.sample[k] for k in ("prompt", "completion")})

    def test_invalid_model_output_is_retried(self):
        with patch("_knowledge_search_common.urllib.request.urlopen", side_effect=[
            response({"key_facts": ["only one"]}),
            response({"key_facts": ["IPv4", "variable header length"]}),
        ]) as http:
            m.run_extraction(self.source, self.output, api=self.api, num=1)
        self.assertEqual(http.call_count, 2)
        self.assertEqual(len(json.loads(self.output.read_text())["key_facts"]), 2)

    def test_failed_request_retains_only_completed_rows(self):
        with patch("_knowledge_search_common.urllib.request.urlopen", side_effect=[
            response({"key_facts": ["IPv4", "variable header length"]}),
            TimeoutError(), TimeoutError(),
        ]):
            with self.assertRaisesRegex(m.APIError, "input line 3.*completed rows retained"):
                m.run_extraction(self.source, self.output, api=self.api)
        self.assertEqual(len(self.output.read_text().splitlines()), 1)
        self.assertEqual(json.loads(self.output.read_text())["source_line"], 2)

    def test_output_and_input_are_protected(self):
        self.output.write_text("existing result\n")
        with patch.object(self.api, "chat") as chat:
            with self.assertRaises(FileExistsError):
                m.run_extraction(self.source, self.output, api=self.api)
            before = self.source.read_text()
            with self.assertRaisesRegex(ValueError, "different files"):
                m.run_extraction(self.source, self.source, api=self.api, overwrite=True)
            chat.assert_not_called()
        self.assertEqual(self.source.read_text(), before)
        self.assertEqual(self.output.read_text(), "existing result\n")

    def test_invalid_phrases_are_rejected(self):
        for phrases in (["a"], ["a", "b", "c", "d"], ["IPv4", " ipv4 "], ["a", " "], ["a", 2]):
            with self.subTest(phrases=phrases), self.assertRaises(ValueError):
                m.validate_key_facts({"key_facts": phrases})
        self.assertEqual(m.validate_key_facts({"key_facts": [" a ", "b", "c"]}), {"key_facts": ["a", "b", "c"]})


if __name__ == "__main__":
    unittest.main()
