"""领域分布熵的统计口径与 CLI 行为回归测试。"""

import contextlib
import csv
import importlib.util
import io
import json
import math
import tempfile
import unittest
from collections import Counter
from itertools import combinations
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "domain_distribution_entropy.py"
SPEC = importlib.util.spec_from_file_location("dde_under_test", MODULE_PATH)
dde = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dde)


def record(source="A", added=None, identity="sample-1"):
    """生成独立于真实语料的最小阶段1记录。"""
    added = ["B"] if added is None else added
    return {"source_domain": source, "domain_count": len(added) + 1,
            "fusion_domains": added,
            "sample": {"prompt": identity, "completion": "answer"}}


def source_group(report, source="A", k=2):
    """读取指定源领域与融合规模的统计结果。"""
    return next(g for g in report["per_source"]
                if g["source_domain"] == source and g["domain_count"] == k)


class EntropyDefinitionTests(unittest.TestCase):
    """用可手算的分布验证指标定义。"""

    def test_uniform_combinations_are_one_for_two_three_four_domains(self):
        domains = list("ABCDEFG")
        for k, expected_space in ((2, 6), (3, 15), (4, 20)):
            with self.subTest(k=k):
                frequencies = Counter({t: 2 for t in combinations(domains[1:], k - 1)})
                report = dde.compute_metrics({("A", k): frequencies}, domains, [k])
                group = source_group(report, k=k)
                self.assertAlmostEqual(group["dde"], 1.0)
                self.assertAlmostEqual(group["entropy_nats"], math.log(expected_space))
                self.assertEqual(group["possible_combinations"], expected_space)
                self.assertEqual(group["coverage"], 1.0)

    def test_concentrated_combinations_have_zero_entropy(self):
        for k in (2, 3, 4):
            with self.subTest(k=k):
                report = dde.compute_metrics(
                    {("A", k): Counter({tuple("BCD"[:k - 1]): 10})}, list("ABCDEFG"), [k])
                self.assertEqual(source_group(report, k=k)["dde"], 0.0)

    def test_nonuniform_entropy_uses_fixed_space_including_unseen(self):
        report = dde.compute_metrics(
            {("A", 2): Counter({("B",): 3, ("C",): 1})}, list("ABCD"), [2])
        group = source_group(report)
        expected_h = -0.75 * math.log(0.75) - 0.25 * math.log(0.25)
        self.assertAlmostEqual(group["entropy_nats"], expected_h)
        self.assertAlmostEqual(group["dde"], expected_h / math.log(3))
        self.assertAlmostEqual(group["coverage"], 2 / 3)
        unseen = next(r for r in report["combinations"]
                      if r["source_domain"] == "A" and r["fusion_domains"] == ["D"])
        self.assertEqual((unseen["count"], unseen["probability"]), (0, 0))

    def test_only_possible_combination_has_undefined_normalized_entropy(self):
        domains = list("ABCD")
        counts = {(a, 4): Counter({tuple(d for d in domains if d != a): 1}) for a in domains}
        report = dde.compute_metrics(counts, domains, [4])
        for group in report["per_source"]:
            self.assertIsNone(group["dde"])
            self.assertEqual(group["entropy_nats"], 0)
            self.assertEqual(group["coverage"], 1)
        self.assertIsNone(report["summary_by_k"][0]["macro_dde"])

    def test_missing_source_does_not_become_zero_or_complete_macro(self):
        report = dde.compute_metrics(
            {("A", 2): Counter({("B",): 1, ("C",): 1, ("D",): 1})}, list("ABCD"), [2])
        summary = report["summary_by_k"][0]
        self.assertIsNone(summary["macro_dde"])
        self.assertAlmostEqual(summary["observed_source_macro_dde"], 1)
        self.assertEqual(summary["missing_source_domains"], ["B", "C", "D"])
        missing = source_group(report, "B")
        self.assertIsNone(missing["dde"])
        self.assertIsNone(missing["entropy_nats"])
        self.assertIsNone(missing["coverage"])

    def test_macro_average_gives_each_source_equal_weight(self):
        domains = list("ABCD")
        counts = {("A", 2): Counter({("B",): 100})}
        for source in domains[1:]:
            counts[(source, 2)] = Counter({(d,): 1 for d in domains if d != source})
        summary = dde.compute_metrics(counts, domains, [2])["summary_by_k"][0]
        self.assertAlmostEqual(summary["macro_dde"], 0.75)
        self.assertEqual(summary["n_plans"], 109)

    def test_same_domain_marginals_can_hide_different_combination_entropy(self):
        domains = list("ABCDE")
        cycle = Counter({("B", "C"): 1, ("C", "D"): 1,
                         ("D", "E"): 1, ("B", "E"): 1})
        uniform = Counter({t: 1 for t in combinations(domains[1:], 2)})
        first = source_group(dde.compute_metrics({("A", 3): cycle}, domains, [3]), k=3)
        second = source_group(dde.compute_metrics({("A", 3): uniform}, domains, [3]), k=3)
        self.assertAlmostEqual(first["marginal_dde"], second["marginal_dde"])
        self.assertAlmostEqual(first["dde"], math.log(4) / math.log(6))
        self.assertAlmostEqual(second["dde"], 1)
        self.assertLess(first["dde"], second["dde"])

    def test_domain_inclusion_and_slot_probabilities_use_different_denominators(self):
        report = dde.compute_metrics(
            {("A", 3): Counter({("B", "C"): 3, ("B", "D"): 1})}, list("ABCD"), [3])
        rows = [r for r in report["selection_rates"] if r["source_domain"] == "A"]
        self.assertAlmostEqual(sum(r["inclusion_rate"] for r in rows), 2)
        self.assertAlmostEqual(sum(r["slot_probability"] for r in rows), 1)
        target_b = next(r for r in rows if r["target_domain"] == "B")
        self.assertEqual(target_b["inclusion_rate"], 1)
        self.assertEqual(target_b["slot_probability"], 0.5)


class InputAndCliTests(unittest.TestCase):
    """用临时 JSONL 验证数据身份、错误提示和报告交付。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.input_dir = self.root / "plans"
        self.input_dir.mkdir()
        self.input_file = self.input_dir / "test.jsonl"
        self.output = self.root / "reports"
        self.domains = list("ABCD")

    def write_rows(self, rows):
        self.input_file.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")

    def run_cli(self, *extra, input_path=None, output_path=None):
        args = ["--input", str(input_path or self.input_dir),
                "--output", str(output_path or self.output), "--domains", *self.domains,
                "--domain-counts", "2", "3", "4", *extra]
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = dde.main(args)
        return result, stdout.getvalue(), stderr.getvalue()

    def test_three_domain_combination_order_is_irrelevant(self):
        self.write_rows([record(added=["B", "C"], identity="1"),
                         record(added=["C", "B"], identity="2")])
        counts, metadata = dde.load_plans(self.input_dir, self.domains, [3])
        self.assertEqual(counts[("A", 3)], Counter({("B", "C"): 2}))
        self.assertEqual(metadata["rows_included"], 2)

    def test_duplicate_atomic_sample_and_k_are_rejected_with_location(self):
        self.write_rows([record(), record(added=["C"])])
        with self.assertRaisesRegex(ValueError, r"test.jsonl:2:.*重复.*test.jsonl:1"):
            dde.load_plans(self.input_dir, self.domains, [2])

    def test_same_atomic_sample_across_different_k_is_allowed(self):
        self.write_rows([record(), record(added=["B", "C"]), record(added=["B", "C", "D"])])
        counts, metadata = dde.load_plans(self.input_file, self.domains, [2, 3, 4])
        self.assertEqual(metadata["rows_included"], 3)
        self.assertEqual(set(counts), {("A", 2), ("A", 3), ("A", 4)})

    def test_invalid_fields_and_final_question_records_are_rejected(self):
        invalid = [[], {"source_domain": "unknown"}, {"domain_count": True},
                   {"domain_count": 3}, {"fusion_domains": "B"},
                   {"fusion_domains": ["A"]}, {"fusion_domains": ["Z"]},
                   {"fusion_domains": ["B", "B"], "domain_count": 3},
                   {"sample": {"prompt": "p"}}, {"difficulty": "easy"},
                   {"fused_question": "question"}]
        for change in invalid:
            row = {**record(), **change} if isinstance(change, dict) else change
            with self.subTest(change=change), self.assertRaises(ValueError):
                dde.validate_record(row, self.domains)

    def test_requested_k_filters_are_counted_in_metadata(self):
        self.write_rows([record(), record(added=["B", "C"])])
        counts, metadata = dde.load_plans(self.input_dir, self.domains, [3])
        self.assertEqual(set(counts), {("A", 3)})
        self.assertEqual(metadata["rows_read"], 2)
        self.assertEqual(metadata["rows_excluded_by_k"], 1)

    def test_cli_writes_six_reports_preserving_null_and_empty_csv_values(self):
        self.write_rows([record()])
        result, _, errors = self.run_cli()
        self.assertEqual(result, 0, errors)
        self.assertEqual({p.name for p in self.output.iterdir()}, {
            "summary.json", "summary.csv", "per_source.csv", "combinations.csv",
            "selection_rates.csv", "report.md"})
        report = json.loads((self.output / "summary.json").read_text(encoding="utf-8"))
        self.assertIsNone(report["summary_by_k"][0]["macro_dde"])
        self.assertEqual(report["summary_by_k"][0]["observed_source_macro_dde"], 0)
        with (self.output / "summary.csv").open(encoding="utf-8", newline="") as handle:
            summary = next(csv.DictReader(handle))
        self.assertEqual(summary["macro_dde"], "")
        self.assertEqual(float(summary["observed_source_macro_dde"]), 0)
        self.assertEqual(report["metadata"]["rows_included"], 1)
        self.assertEqual(len(report["metadata"]["files"][0]["sha256"]), 64)

    def test_existing_reports_are_protected_unless_overwrite_is_explicit(self):
        self.write_rows([record()])
        self.assertEqual(self.run_cli()[0], 0)
        sentinel = self.output / "summary.json"
        sentinel.write_text("do not change", encoding="utf-8")
        result, _, errors = self.run_cli()
        self.assertEqual(result, 2)
        self.assertIn("--overwrite", errors)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "do not change")
        self.assertEqual(self.run_cli("--overwrite")[0], 0)
        self.assertIsInstance(json.loads(sentinel.read_text(encoding="utf-8")), dict)

    def test_reports_cannot_be_written_inside_input_tree(self):
        self.write_rows([record()])
        original = self.input_file.read_bytes()
        for target in (self.input_dir, self.input_dir / "nested"):
            with self.subTest(target=target):
                result, _, errors = self.run_cli(output_path=target)
                self.assertEqual(result, 2)
                self.assertIn("输出目录不能位于输入目录内部", errors)
        self.assertEqual(self.input_file.read_bytes(), original)
        self.assertFalse((self.input_dir / "nested").exists())

    def test_invalid_json_does_not_create_partial_output(self):
        self.input_file.write_text('{"source_domain":', encoding="utf-8")
        result, _, errors = self.run_cli()
        self.assertEqual(result, 2)
        self.assertIn("test.jsonl:1", errors)
        self.assertFalse(self.output.exists())

    def test_empty_input_is_not_reported_as_zero_entropy(self):
        self.write_rows([])
        result, _, errors = self.run_cli()
        self.assertEqual(result, 2)
        self.assertIn("输入为空", errors)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
