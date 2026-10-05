"""保存分数审计的数学口径、抽样和离线命令行回归测试。"""

from __future__ import annotations

import contextlib
import copy
import csv
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

MODULE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE_DIR))
import knc_saved_core as core
import knowledge_need_coverage as cli

DOMAINS = ["a", "b", "c", "d"]


def candidate(cid="document", scores=None):
    """构造带明确需求序号的检索材料。

    Args:
        cid: 材料身份。
        scores: 从1开始的需求序号与分数映射。

    Returns:
        阶段3候选记录。
    """
    return {"candidate_id": cid, "sample": {"prompt": "材料问题", "completion": "材料证据"},
            "rrf_score": 999, "hits": [{"query_index": j, "method": "embedding", "score": s}
                                        for j, s in (scores or {}).items()]}


def plan(source="a", k=2, atom="one", counts=None, score=0.8):
    """构造各领域可有不同需求数量的真实格式方案。

    Returns:
        可直接序列化为阶段3 JSONL行的记录。
    """
    added = [d for d in DOMAINS if d != source][:k - 1]
    counts = counts or [1] * len(added)
    return {"source_domain": source, "domain_count": k, "fusion_domains": added,
            "sample": {"prompt": "原子问题 " + atom, "completion": "原子答案 " + atom},
            "question_plan": "联合使用各领域材料完成问题",
            "required_key_facts": {d: [{"key_fact": f"知识 {d}{j}", "necessity": "任务必要"}
                                        for j in range(1, n + 1)] for d, n in zip(added, counts)},
            "retrieved_samples": {d: [candidate(d, {j: score for j in range(1, n + 1)})]
                                  for d, n in zip(added, counts)},
            "retrieval": {"method": "hybrid", "embedding_config_hash": "same-configuration",
                          "rrf_k": 60, "top_k_per_query_method": 10, "candidate_limit": 10}}


def extract(rows, budgets=None):
    """经真实格式校验后提取测试方案的分数。

    Returns:
        配对明细和逐需求明细。
    """
    return core.extract_scores([core.normalize_plan(row, DOMAINS) for row in rows], budgets or ["all"])


def metrics(rows, ks=None, domains=None, thresholds=None, budgets=None):
    """通过完整聚合入口获得测试结果。

    Returns:
        各层级指标表。
    """
    budgets = budgets or ["all"]
    _, requirements = extract(rows, budgets)
    return core.compute_metrics(requirements, domains or DOMAINS, ks or [2], thresholds or [0.7], budgets)


class SavedScoreTests(unittest.TestCase):
    """检验保存分数与知识需求的对应关系。"""

    def test_uses_embedding_only_and_one_based_need_indices(self):
        """BM25和融合排名分数不能覆盖缺失的embedding配对。"""
        row = plan(counts=[2])
        material = candidate(scores={2: 0.8})
        material["hits"].append({"query_index": 1, "method": "bm25", "score": 999})
        material["matches"] = [{"query_index": 1, "score": 999}]
        row["retrieved_samples"]["b"] = [material]
        pairs, needs = extract([row])
        self.assertEqual([p["embedding_score"] for p in pairs], [None, 0.8])
        self.assertEqual([n["best_saved_score"] for n in needs], [None, 0.8])
        self.assertEqual([core.evaluate_requirement(n, 0.7)["saved_hit"] for n in needs], [0, 1])

    def test_best_material_covers_a_need_once(self):
        """覆盖率以需求计数，同一需求命中多份材料仍只记一次。"""
        row = plan(counts=[2])
        row["retrieved_samples"]["b"] = [candidate("x", {1: 0.71, 2: 0.2}),
                                           candidate("y", {1: 0.9, 2: 0.4})]
        _, needs = extract([row])
        self.assertEqual(needs[0]["best_candidate_id"], "y")
        self.assertEqual(needs[0]["best_candidate_completion"], "材料证据")
        self.assertEqual(metrics([row])["per_plan"][0]["knc_saved"], 0.5)

    def test_threshold_is_inclusive_without_rounding(self):
        """小于0.7但显示可舍入为0.7的分数不能算命中。"""
        row = plan(counts=[3])
        row["retrieved_samples"]["b"] = [candidate(scores={1: 0.7, 2: 0.69999999999, 3: 0.70000000001})]
        _, needs = extract([row])
        self.assertEqual([core.evaluate_requirement(n, 0.7)["saved_hit"] for n in needs], [1, 0, 1])

    def test_missing_zero_and_negative_are_distinct(self):
        """零分和负分是已观察值，缺失不是零分。"""
        row = plan(counts=[3])
        row["retrieved_samples"]["b"] = [candidate(scores={1: 0.0, 2: -0.2})]
        pairs, needs = extract([row])
        self.assertEqual([p["embedding_score"] for p in pairs], [0.0, -0.2, None])
        self.assertEqual([n["score_status"] for n in needs], ["observed", "observed", "no_saved_score"])
        self.assertEqual([core.evaluate_requirement(n, -0.3)["saved_hit"] for n in needs], [1, 1, 0])

    def test_empty_candidates_are_known_uncovered(self):
        """材料列表明确为空时上界为零，配对可用率无分母。"""
        row = plan()
        row["retrieved_samples"]["b"] = []
        pairs, needs = extract([row])
        self.assertEqual(pairs, [])
        self.assertEqual(needs[0]["score_status"], "empty_candidates")
        result = core.evaluate_requirement(needs[0], 0.7)
        self.assertEqual((result["complete_lower"], result["complete_upper"]), (0, 0))
        self.assertIsNone(metrics([row])["per_plan"][0]["pair_score_availability"])

    def test_conservative_bounds_distinguish_missing_pairs(self):
        """已命中、未命中且缺分、全配对未命中分别对应不同边界。"""
        row = plan(counts=[3])
        row["retrieved_samples"]["b"] = [candidate("x", {1: 0.8, 2: 0.2, 3: 0.2}),
                                           candidate("y", {3: 0.3})]
        _, needs = extract([row])
        results = [core.evaluate_requirement(n, 0.7) for n in needs]
        self.assertEqual([(r["complete_lower"], r["complete_upper"]) for r in results], [(1, 1), (0, 1), (0, 0)])
        self.assertEqual([r["complete_state"] for r in results], ["covered", "unknown", "uncovered"])

    def test_identical_duplicate_hits_do_not_inflate_availability(self):
        """重复保存相同命中不增加可用配对计数。"""
        row = plan()
        material = row["retrieved_samples"]["b"][0]
        material["hits"].append(copy.deepcopy(material["hits"][0]))
        _, needs = extract([row])
        self.assertEqual(needs[0]["observed_pairs"], 1)

    def test_conflicting_duplicate_hits_are_rejected(self):
        """同一材料需求出现冲突分数时停止评测。"""
        row = plan()
        row["retrieved_samples"]["b"][0]["hits"].append({"query_index": 1, "method": "embedding", "score": 0.2})
        with self.assertRaisesRegex(ValueError, "冲突"):
            extract([row])

    def test_invalid_scores_are_rejected(self):
        """拒绝非有限值、布尔值、字符串和余弦范围外的数值。"""
        for score in [float("nan"), float("inf"), -float("inf"), True, "0.8", None, -1.01, 1.01]:
            with self.subTest(score=score), self.assertRaises(ValueError):
                extract([plan(score=score)])

    def test_invalid_query_indices_are_rejected(self):
        """需求序号必须是1-based且在当前目标领域的需求范围内。"""
        for index in [0, -1, 2, True, 1.0, "1", None]:
            row = plan()
            row["retrieved_samples"]["b"][0]["hits"][0]["query_index"] = index
            with self.subTest(index=index), self.assertRaises(ValueError):
                extract([row])

    def test_duplicate_candidates_and_missing_domain_are_rejected(self):
        """避免重复材料权重或把缺失领域误当空列表。"""
        row = plan()
        row["retrieved_samples"]["b"] *= 2
        with self.assertRaisesRegex(ValueError, "重复"):
            extract([row])
        row = plan()
        del row["retrieved_samples"]["b"]
        with self.assertRaisesRegex(ValueError, "全部新增领域"):
            extract([row])


class AggregationTests(unittest.TestCase):
    """验证跨领域、跨方案、跨源领域的平均口径。"""

    def test_target_domains_receive_equal_weight(self):
        """两目标域1项全中与3项全不中得到1/2，而非需求池化的1/4。"""
        row = plan(k=3, counts=[1, 3])
        row["retrieved_samples"]["c"] = [candidate(scores={1: 0.1, 2: 0.1, 3: 0.1})]
        result = metrics([row], ks=[3])["per_plan"][0]
        self.assertEqual(result["knc_saved"], 0.5)
        self.assertEqual(result["weakest_domain_saved"], 0)
        self.assertEqual(result["all_covered_saved"], 0)

    def test_source_macro_does_not_pool_unequal_plan_counts(self):
        """a源两方案全中、b源一方案不中时源宏平均为1/2。"""
        rows = [plan(atom="one"), plan(atom="two"), plan(source="b", score=0.1)]
        result = metrics(rows, domains=["a", "b"])["summary"][0]
        self.assertEqual(result["macro_knc_saved"], 0.5)
        self.assertEqual(result["n_plans"], 3)

    def test_missing_source_keeps_full_macro_unavailable(self):
        """局部源领域均值不能冒充声明全集的宏平均。"""
        result = metrics([plan()])["summary"][0]
        self.assertIsNone(result["macro_knc_saved"])
        self.assertEqual(result["observed_source_knc_saved"], 1)
        self.assertEqual(result["missing_sources"], ["b", "c", "d"])

    def test_score_availability_is_not_pair_availability(self):
        """每项需求有一个分数可达100%，但配对矩阵仍可能只有50%。"""
        row = plan(counts=[2])
        row["retrieved_samples"]["b"] = [candidate("x", {1: 0.4}), candidate("y", {2: 0.4})]
        result = metrics([row])["per_plan"][0]
        self.assertEqual(result["need_score_availability"], 1)
        self.assertEqual(result["pair_score_availability"], 0.5)
        self.assertEqual((result["complete_lower"], result["complete_upper"]), (0, 1))

    def test_threshold_and_candidate_prefix_monotonicity(self):
        """阈值升高不增命中，RRF前缀扩大不降保存命中。"""
        row = plan(counts=[2])
        row["retrieved_samples"]["b"] = [candidate("rrf-first", {1: 0.4}),
                                           candidate("rrf-second", {1: 0.8, 2: 0.6})]
        results = metrics([row], thresholds=[0.3, 0.5, 0.7, 0.9], budgets=["1", "2", "all"])["per_plan"]
        lookup = {(r["budget"], r["threshold"]): r["knc_saved"] for r in results}
        self.assertEqual(lookup[("1", 0.7)], 0)
        self.assertEqual(lookup[("2", 0.7)], 0.5)
        for threshold in [0.3, 0.5, 0.7, 0.9]:
            self.assertLessEqual(lookup[("1", threshold)], lookup[("2", threshold)])
            self.assertEqual(lookup[("2", threshold)], lookup[("all", threshold)])
        for budget in ["1", "2", "all"]:
            values = [lookup[(budget, t)] for t in [0.3, 0.5, 0.7, 0.9]]
            self.assertEqual(values, sorted(values, reverse=True))


class SamplingTests(unittest.TestCase):
    """验证抽样单位是跨k共用的原子知识。"""

    def test_paired_sampling_is_order_independent_for_two_three_four_domains(self):
        """重排输入后仍抽到相同方案，每源的三个k共享原子样本。"""
        plans = [core.normalize_plan(plan(source=s, k=k, atom=str(a)), DOMAINS)
                 for s in DOMAINS for k in [2, 3, 4] for a in range(8)]
        selected = core.select_plans(plans, [2, 3, 4], seed=42)
        reversed_selection = core.select_plans(list(reversed(plans)), [4, 2, 3], seed=42)
        self.assertEqual(selected, reversed_selection)
        self.assertEqual(len(selected), 12)
        for source in DOMAINS:
            subset = [p for p in selected if p["source_domain"] == source]
            self.assertEqual({p["domain_count"] for p in subset}, {2, 3, 4})
            self.assertEqual(len({p["atomic_id"] for p in subset}), 1)

    def test_incomplete_pairing_is_rejected_but_all_plans_can_use_it(self):
        """配对抽样不能悄悄替换成不同原子知识。"""
        plans = [core.normalize_plan(plan(k=k, atom=str(k)), DOMAINS) for k in [2, 3, 4]]
        with self.assertRaisesRegex(ValueError, "共有原子样本"):
            core.select_plans(plans, [2, 3, 4])
        self.assertEqual(len(core.select_plans(plans, [2, 3, 4], all_plans=True)), 3)

    def test_requested_sources_and_count_are_respected(self):
        """局部抽样保留指定源与原子样本数量。"""
        plans = [core.normalize_plan(plan(source=s, k=k, atom=str(a)), DOMAINS)
                 for s in DOMAINS for k in [2, 3, 4] for a in range(3)]
        selected = core.select_plans(plans, [2, 3, 4], samples_per_source=2, source_domains=["b"])
        self.assertEqual(len(selected), 6)
        self.assertEqual({p["source_domain"] for p in selected}, {"b"})


class CLITests(unittest.TestCase):
    """验证纯标准库运行、可复核输出与文件保护。"""

    def setUp(self):
        """为每例创建独立输入输出路径。"""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.input = self.root / "input.jsonl"
        self.output = self.root / "reports"
        self.write_rows([plan()])

    def write_rows(self, rows):
        """将合成阶段3记录写入测试专用临时文件。"""
        self.input.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")

    def args(self, extra=()):
        """返回限制在单k与固定领域全集的CLI参数。"""
        return ["--input", str(self.input), "--output", str(self.output), "--domains", *DOMAINS,
                "--domain-counts", "2", "--thresholds", "0.7", "--budgets", "1", *extra]

    def run_cli(self, extra=()):
        """运行入口并捕获预期的终端信息。

        Returns:
            退出码及标准错误。
        """
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as errors:
            code = cli.main(self.args(extra))
        return code, errors.getvalue()

    def test_standard_library_subprocess_writes_nine_reports(self):
        """使用-S禁用site-packages，证明评测不需要模型库。"""
        completed = subprocess.run([sys.executable, "-X", "utf8", "-S", str(MODULE_DIR / "knowledge_need_coverage.py"),
                                    *self.args()], capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual({p.name for p in self.output.iterdir()}, set(cli.REPORT_FILES))
        report = json.loads((self.output / "summary.json").read_text(encoding="utf-8"))
        self.assertTrue(report["manifest"]["offline"])
        self.assertEqual(report["manifest"]["model_calls"], 0)
        self.assertEqual(report["manifest"]["sample"][0]["input_line"], 1)

    def test_network_disabled_and_missing_score_exports_blank_null(self):
        """禁用网络后仍可运行，CSV和JSON保留缺失语义。"""
        row = plan()
        row["retrieved_samples"]["b"] = [candidate()]
        self.write_rows([row])
        with patch("socket.create_connection", side_effect=AssertionError("不允许网络请求")):
            self.assertEqual(self.run_cli()[0], 0)
        with (self.output / "pair_scores.csv").open(encoding="utf-8", newline="") as handle:
            self.assertEqual(next(csv.DictReader(handle))["embedding_score"], "")
        report = json.loads((self.output / "summary.json").read_text(encoding="utf-8"))
        self.assertIsNone(report["pair_scores"][0]["embedding_score"])

    def test_existing_output_requires_explicit_overwrite(self):
        """首次报告保留至明确给出覆盖选项。"""
        self.assertEqual(self.run_cli()[0], 0)
        original = (self.output / "report.md").read_bytes()
        code, error = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn("--overwrite", error)
        self.assertEqual((self.output / "report.md").read_bytes(), original)
        self.assertEqual(self.run_cli(["--overwrite"])[0], 0)

    def test_input_directory_cannot_contain_output(self):
        """即使允许覆盖也不能向输入目录内部写审计报告。"""
        code, error = self.run_cli(["--input", str(self.root), "--output", str(self.root / "nested"), "--overwrite"])
        self.assertEqual(code, 2)
        self.assertIn("输入目录内部", error)
        self.assertFalse((self.root / "nested").exists())

    def test_symlink_report_cannot_overwrite_external_file(self):
        """--overwrite仍不跟随报告文件符号链接。"""
        self.output.mkdir()
        protected = self.root / "protected.txt"
        protected.write_text("保留", encoding="utf-8")
        (self.output / "report.md").symlink_to(protected)
        self.assertEqual(self.run_cli(["--overwrite"])[0], 2)
        self.assertEqual(protected.read_text(encoding="utf-8"), "保留")

    def test_mixed_embedding_and_retrieval_configs_rejected(self):
        """不同模型配置或候选预算不能混合计算同一指标。"""
        for field, value in [("embedding_config_hash", "different"), ("candidate_limit", 5)]:
            other = plan(atom="two")
            other["retrieval"][field] = value
            self.write_rows([plan(), other])
            with self.subTest(field=field):
                code, error = self.run_cli(["--all-plans"])
                self.assertEqual(code, 2)
                self.assertIn("配置不同", error)
                self.assertFalse(self.output.exists())

    def test_duplicate_plans_and_malformed_json_report_location(self):
        """数据错误必须定位具体文件与行号，且不产生结果。"""
        self.write_rows([plan(), plan()])
        code, error = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn(str(self.input) + ":2", error)
        self.input.write_text("{bad json}\n", encoding="utf-8")
        self.assertIn(str(self.input) + ":1", self.run_cli()[1])
        self.assertFalse(self.output.exists())

    def test_unicode_separators_with_bom_crlf_preserve_jsonl_line_numbers(self):
        """JSON字符串中的Unicode分隔符不应被当作JSONL记录换行。"""
        separators = "段落\u2028下一段\u2029后续\u0085结束"
        rows = [plan(atom="first " + separators), plan(atom="second " + separators)]
        serialized = [json.dumps(row, ensure_ascii=False) for row in rows]
        for ending, bom in [("\n", ""), ("\r\n", "\ufeff")]:
            with self.subTest(ending=repr(ending), bom=bool(bom)):
                self.input.write_bytes((bom + ending.join(serialized) + ending).encode("utf-8"))
                plans, metadata = core.load_input(self.input, DOMAINS, [2])
                self.assertEqual(metadata["rows_read"], 2)
                self.assertEqual([p["input_line"] for p in plans], [1, 2])
                self.assertEqual([p["sample"] for p in plans], [r["sample"] for r in rows])
                self.assertEqual(len({p["atomic_id"] for p in plans}), 2)

    def test_invalid_cli_thresholds_and_budgets_fail_without_output(self):
        """拒绝无效阈值和候选预算。"""
        for extra in [["--threshold", "nan"], ["--threshold", "1.1"], ["--budgets", "0"], ["--budgets", "01"]]:
            with self.subTest(extra=extra):
                self.assertEqual(self.run_cli(extra)[0], 2)
                self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
