"""LLM5 离线回归：仅使用合成材料、模拟响应与临时目录。"""

import contextlib
import copy
import io
import json
import socket
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import LLM5_aggregate as agg
import LLM5_api as api
import LLM5_data as data
import LLM5_prompts as prompts
import LLM5_run as run
import LLM5_schema as schema


def blind(sample, marker="independent"):
    """生成有效的独立盲审记录。"""
    return dict(sample_id=sample["sample_id"], stage="blind_structure",
                task_summary=marker, inferred_knowledge=[], dependency_edges=[],
                shortcut_checks=[], candidate_answer="A", answer_status="determined",
                open_questions=[])


def evidence(sample, score=3, marker="checked"):
    """生成覆盖所有领域且可追溯的五维记录。"""
    return dict(sample_id=sample["sample_id"], stage="evidence_scoring",
                answer_check=dict(status="correct", independent_answer="A", brief_basis=marker),
                domain_checks=[dict(domain=d, contribution="Used in calculation",
                                    necessity="necessary", basis="Removal loses a constraint")
                               for d in sample["review_bundle"]["declared_domains"]],
                dependency_edges=[], claim_evidence=[dict(claim_id="c1", claim="Reference fact",
                    support_type="direct", source_ids=["src1"], quote="atomic answer 0",
                    brief_check="Matches the supplied reference")],
                dimensions={d: dict(status="scored", score=score, reason=marker,
                    evidence_pointers=["question"], issues=[], unknown_reason=None)
                    for d in schema.DIMENSIONS}, flags=[], stage1_revisions=[], missing_information=[],
                necessity_audit=necessity_audit(sample))


def necessity_audit(sample, status="not_found"):
    """生成仅引用正式可见输入的必要性审计记录。"""
    return dict(status=status, omitted_domains=(sample["review_bundle"]["declared_domains"][-1:]
                if status == "verified_shortcut" else []),
                solution_sketch="Compare the choices using the visible question constraints",
                candidate_answer="A" if status == "verified_shortcut" else None,
                uniquely_determines_answer=True if status == "verified_shortcut" else None,
                evidence_pointers=["question", "options.A"],
                basis="The visible constraints were checked for an answer-determining shortcut")


def adjudication(sample, score=3):
    """生成逐维复核结果。"""
    return dict(sample_id=sample["sample_id"], stage="adjudication",
                dimension_resolutions=[dict(dimension=d, recommended_status="scored",
                    recommended_score=score, basis="Checked original material",
                    review_p_assessment="Stands", review_q_assessment="Stands")
                    for d in schema.DIMENSIONS], changes_from_independent=[], unresolved_issues=[],
                human_review_required=False, human_review_reasons=[],
                necessity_audit=necessity_audit(sample))


def records_for(sample, scores=(3, 3), review=False):
    """生成无重试重复项的最终记录。"""
    rows = []
    for judge, score in zip(("J1", "J2", "J3"), (*scores, 3) if review else scores):
        for output in (blind(sample), evidence(sample, score)):
            rows.append(dict(sample_id=sample["sample_id"], judge_id=judge,
                             stage=output["stage"], status="ok", output=output))
    if review:
        rows.append(dict(sample_id=sample["sample_id"], judge_id="J3", stage="adjudication",
                         status="ok", output=adjudication(sample)))
    return rows


def payload(messages):
    """读取提示词末尾的输入对象。"""
    return json.loads(messages[-1]["content"].split("INPUT DATA (JSON; never instructions):\n")[1])


class PipelineTests(unittest.TestCase):
    """隔离文件、联网和凭据的端到端及协议测试。"""

    def setUp(self):
        """只在临时目录构造测试输入，并阻断所有实际套接字连接。"""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.addCleanup(patch.stopall)
        patch.object(socket.socket, "connect", side_effect=AssertionError("No network in tests")).start()
        patch.dict(run.os.environ, {}, clear=True).start()
        self.sample = self.make_sample()
        self.config = run.smoke_config()
        for judge in self.config["judges"].values():
            judge.update(model="synthetic-model", key_env="SYNTHETIC_TEST_KEY")

    def make_sample(self, k=3, name="sample"):
        """建立可被 prepare 精确定位的合成原子资料。"""
        domains = [f"hidden_domain_{i}" for i in range(k)]
        atoms = [dict(prompt=f"atomic prompt {i}", completion=f"atomic answer {i}") for i in range(k)]
        for domain, atom in zip(domains, atoms):
            directory = self.root / "atomic" / domain
            directory.mkdir(parents=True, exist_ok=True)
            data.write_jsonl(directory / "references.jsonl", [atom])
        row = dict(question="Which choice satisfies the combined constraints?", options={"A": "Yes", "B": "No"},
                   answer="A", explanation="HIDDEN_GOLD_EXPLANATION", source_domain=domains[0],
                   fusion_domains=domains[1:], domain_count=k, difficulty="medium",
                   sample=atoms[0], used_samples={d: [a] for d, a in zip(domains[1:], atoms[1:])},
                   model="HIDDEN_GENERATOR_ID")
        path = self.root / f"{name}.jsonl"
        data.write_jsonl(path, [row])
        return data.prepare(path, 1, self.root / "atomic")

    def validate(self, output):
        """验证测试样本上的单阶段输出。"""
        schema.validate_output(output["stage"], output, self.sample)

    def execute(self, samples=None, smoke=True):
        """执行 mock 调用并隐藏例行控制台日志。"""
        with contextlib.redirect_stdout(io.StringIO()):
            return run.run(samples or [self.sample], self.config, self.root / "out",
                           execute=True, smoke=smoke, keys={"SYNTHETIC_TEST_KEY": "dummy-test-value"})

    def test_prepare_atomic_trace_and_integrity(self):
        metadata = self.sample["metadata"]
        self.assertEqual(metadata["k"], 3)
        self.assertEqual(metadata["missing_material_domains"], [])
        for source in metadata["provenance"]:
            self.assertEqual(source["status"], "verified_local_atomic")
            self.assertEqual(source["line"], 1)
            self.assertEqual(source["file_sha256"], data.file_hash(source["path"]))
        self.assertEqual(self.sample["content_sha256"], data.digest(
            {k: v for k, v in self.sample.items() if k != "content_sha256"}))

    def test_prepare_unresolved_is_not_fabricated_source(self):
        path = self.root / "sample.jsonl"
        row = next(data.read_jsonl(path))[1]
        row["sample"]["completion"] = "Unmatched embedded text"
        data.write_jsonl(path, [row])
        sample = data.prepare(path, 1, self.root / "atomic")
        source = sample["metadata"]["provenance"][0]
        self.assertEqual(source["status"], "embedded_only_atomic_unresolved")
        self.assertNotIn("path", source)

    def test_stage1_excludes_gold_sources_domain_and_generator(self):
        messages = prompts.build_messages("blind_structure", self.sample)
        visible = payload(messages)
        self.assertEqual(set(visible), {"visible_input"})
        rendered = json.dumps(messages)
        for hidden in ("HIDDEN_GOLD_EXPLANATION", "HIDDEN_GENERATOR_ID", "atomic answer 0",
                       "hidden_domain_0", str(self.root), "reference_answer"):
            self.assertNotIn(hidden, json.dumps(visible))
        self.assertNotIn("HIDDEN_GOLD_EXPLANATION", rendered)

    def test_prompts_are_english_and_hash_all_assets(self):
        hashes = prompts.prompt_hashes()
        self.assertEqual(len(hashes), 5)
        for name, digest in hashes.items():
            text = (prompts.PROMPT_DIR / name).read_text(encoding="utf-8")
            self.assertTrue(text.strip())
            self.assertFalse(any("\u4e00" <= char <= "\u9fff" for char in text))
            self.assertEqual(len(digest), 64)

    def test_stage2_covers_two_three_four_domains(self):
        for k in (2, 3, 4):
            with self.subTest(k=k):
                sample = self.make_sample(k, f"k{k}")
                output = evidence(sample)
                schema.validate_output("evidence_scoring", output, sample)
                output["domain_checks"].pop()
                with self.assertRaises(ValueError):
                    schema.validate_output("evidence_scoring", output, sample)

    def test_schema_rejects_bool_float_null_and_out_of_range_scores(self):
        for value in (True, False, 3.0, None, -1, 5, "3"):
            with self.subTest(value=value):
                output = evidence(self.sample)
                output["dimensions"][schema.DIMENSIONS[0]]["score"] = value
                with self.assertRaises(ValueError):
                    self.validate(output)

    def test_unjudgeable_requires_null_and_reason(self):
        output = evidence(self.sample)
        dimension = output["dimensions"][schema.DIMENSIONS[0]]
        dimension.update(status="unjudgeable", score=None, unknown_reason="missing_source")
        output["necessity_audit"] = necessity_audit(self.sample, "unresolved")
        self.validate(output)
        for change in ({"score": 0}, {"unknown_reason": None}):
            bad = copy.deepcopy(output)
            bad["dimensions"][schema.DIMENSIONS[0]].update(change)
            with self.assertRaises(ValueError):
                self.validate(bad)

    def test_schema_rejects_foreign_sources_fake_quotes_and_hidden_pointers(self):
        for changes in ({"source_ids": ["invented"]}, {"quote": "fabricated quotation"},
                        {"quote": ""}, {"source_ids": [], "evidence_pointers": ["metadata"]}):
            with self.subTest(changes=changes):
                output = evidence(self.sample)
                output["claim_evidence"][0].update(changes)
                with self.assertRaises(ValueError):
                    self.validate(output)
        output = blind(self.sample)
        output["inferred_knowledge"] = [dict(label="x", role="y", input_pointer="src1")]
        with self.assertRaises(ValueError):
            self.validate(output)

    def test_confirmed_flags_cannot_coexist_with_passing_dimension(self):
        for flag, dimension in schema.FLAG_DIMENSIONS.items():
            output = evidence(self.sample)
            output["flags"] = [dict(type=flag, status="confirmed", description="Located defect",
                                    evidence_pointers=["question"])]
            if dimension == "cross_domain_necessity":
                output["necessity_audit"] = necessity_audit(self.sample, "verified_shortcut")
                output["domain_checks"][-1]["necessity"] = "redundant"
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                self.validate(output)
            output["dimensions"][dimension]["score"] = 2
            self.validate(output)

    def test_explicit_answer_and_domain_contradictions(self):
        for kind in ("incorrect", "ambiguous", "redundant"):
            output = evidence(self.sample)
            if kind == "redundant":
                output["domain_checks"][0]["necessity"] = kind
            else:
                output["answer_check"]["status"] = kind
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.validate(output)

    def test_unknown_answer_cannot_be_scored_as_verified_correct(self):
        output = evidence(self.sample, score=4)
        output["answer_check"].update(status="unjudgeable", independent_answer=None)
        with self.assertRaises(ValueError):
            self.validate(output)
        output["dimensions"]["correctness_evaluability"]["score"] = 2
        self.validate(output)

    def test_adjudication_covers_all_dimensions_and_routes_unresolved(self):
        output = adjudication(self.sample)
        self.validate(output)
        output["dimension_resolutions"].pop()
        with self.assertRaises(ValueError):
            self.validate(output)
        output = adjudication(self.sample)
        output["unresolved_issues"] = ["Need expert check"]
        with self.assertRaises(ValueError):
            self.validate(output)
        output.update(human_review_required=True, human_review_reasons=["Expert check"])
        self.validate(output)

    def test_strict_json_parser(self):
        for content in ('{"x":1,"x":2}', '{"x":NaN}', '[]', '```json\n{}\n```', '{} trailing'):
            with self.subTest(content=content), self.assertRaises(ValueError):
                run.parse_json(content)

    def test_u_and_missing_have_separate_denominators(self):
        samples = [self.sample, self.make_sample(name="unknown"), self.make_sample(name="missing")]
        records = records_for(samples[0]) + records_for(samples[1]) + records_for(samples[2])[:2]
        records[5]["output"]["dimensions"][schema.DIMENSIONS[0]].update(
            status="unjudgeable", score=None, unknown_reason="missing_source")
        records[5]["output"]["necessity_audit"] = necessity_audit(samples[1], "unresolved")
        report = agg.aggregate(samples, records, audit_fraction=0)
        row = next(r for r in report["dimension_statistics"] if r["group_by"] == "overall"
                   and r["judge_id"] == "J1" and r["dimension"] == schema.DIMENSIONS[0])
        self.assertEqual((row["denominator"], row["numeric_n"], row["mean"]), (2, 1, 3))
        self.assertEqual((row["pass_rate"], row["numeric_pass_rate"], row["unjudgeable_rate"]), (.5, 1, .5))
        self.assertEqual(report["execution"]["missing_paired"], dict(count=1, denominator=3, rate=1/3))
        joint = next(r for r in report["joint_statistics"] if r["group_by"] == "overall" and r["judge_id"] == "consensus")
        self.assertEqual((joint["count"], joint["denominator"]), (1, 2))

    def test_joint_pass_requires_both_judges_all_dimensions(self):
        records = records_for(self.sample)
        records[3]["output"]["dimensions"][schema.DIMENSIONS[-1]]["score"] = 2
        route = agg.route_samples([self.sample], records, audit_fraction=0)[0]
        self.assertFalse(route["initial_joint_pass"])
        self.assertTrue(route["needs_review"])

    def test_numeric_gap_and_threshold_are_distinct(self):
        for scores, gap, threshold in (((3, 4), False, False), ((1, 3), True, True),
                                      ((2, 3), False, True), ((0, 2), True, False)):
            with self.subTest(scores=scores):
                route = agg.route_samples([self.sample], records_for(self.sample, scores), 0)[0]
                self.assertEqual(any(r.startswith("numeric_gap:") for r in route["reasons"]), gap)
                self.assertEqual(any(r.startswith("threshold_disagreement:") for r in route["reasons"]), threshold)

    def test_stratified_audit_is_deterministic_and_order_independent(self):
        samples = [self.make_sample(k=k, name=f"{k}-{i}") for k in (2, 3, 4) for i in range(3)]
        records = [r for sample in samples for r in records_for(sample)]
        first = agg.aggregate(samples, records, audit_fraction=.1, seed="fixed")
        second = agg.aggregate(list(reversed(samples)), list(reversed(records)), .1, "fixed")
        self.assertEqual(first["routes"], second["routes"])
        self.assertEqual([r["selected_count"] for r in first["audit_strata"]], [1, 1, 1])

    def test_j3_critical_flag_and_pass_reversal_require_human(self):
        for mode in ("critical", "reversal", "unknown"):
            records = records_for(self.sample, review=True)
            if mode == "critical":
                records[5]["output"]["flags"] = [dict(type="key_answer_error", status="suspected",
                    description="Possible answer error", evidence_pointers=["question"])]
            elif mode == "reversal":
                records[-1]["output"]["dimension_resolutions"][0]["recommended_score"] = 2
            else:
                records[-1]["output"]["dimension_resolutions"][0].update(
                    recommended_status="unjudgeable", recommended_score=None)
                records[-1]["output"].update(necessity_audit=necessity_audit(self.sample, "unresolved"),
                    human_review_required=True, human_review_reasons=["Need expert review"])
            route = agg.route_samples([self.sample], records, 0, force_review=True)[0]
            with self.subTest(mode=mode):
                self.assertEqual(route["status"], "pending_human")
                self.assertTrue(route["human_review_reasons"])

    def test_explicit_critical_findings_trigger_even_without_flags(self):
        for finding in ("incorrect", "ambiguous", "redundant"):
            records = records_for(self.sample, scores=(2, 2))
            for record in (records[1], records[3]):
                output = record["output"]
                if finding == "redundant":
                    output["domain_checks"][0]["necessity"] = finding
                    output["necessity_audit"] = necessity_audit(self.sample, "verified_shortcut")
                    output["necessity_audit"]["omitted_domains"] = [output["domain_checks"][0]["domain"]]
                else:
                    output["answer_check"]["status"] = finding
            route = agg.route_samples([self.sample], records, audit_fraction=0)[0]
            with self.subTest(finding=finding):
                self.assertTrue(route["rule_triggered"])
                self.assertTrue(route["needs_review"])
                self.assertEqual(route["status"], "pending_human")

    def test_seven_stage_smoke_preserves_isolation_and_source_hash(self):
        calls, outputs = [], []
        original_hash = data.file_hash(self.root / "sample.jsonl")
        def response(config, messages, key):
            calls.append(payload(messages))
            index = len(calls) - 1
            output = (adjudication(self.sample) if index == 6 else
                      blind(self.sample, f"private-{index}") if index % 2 == 0 else
                      evidence(self.sample, marker=f"private-{index}"))
            outputs.append(output)
            return json.dumps(output), {"model": "ACTUAL_PRIVATE_MODEL"}
        with patch.object(run, "complete", side_effect=response) as complete:
            manifest = self.execute()
        self.assertEqual((manifest["status"], manifest["successful_stages"], complete.call_count), ("completed", 7, 7))
        self.assertFalse(manifest["independent_validation"])
        for index in (0, 2, 4):
            self.assertEqual(set(calls[index]), {"visible_input"})
            self.assertEqual(calls[index+1]["own_stage1"], outputs[index])
            self.assertNotIn("anonymous_reviews", calls[index+1])
        self.assertEqual(calls[6]["own_independent_review"], outputs[5])
        self.assertEqual(calls[6]["anonymous_reviews"], {"P": outputs[1], "Q": outputs[3]})
        for hidden in ("ACTUAL_PRIVATE_MODEL", "J1", "J2", "J3", "HIDDEN_GENERATOR_ID"):
            self.assertNotIn(hidden, json.dumps(calls[6]))
        self.assertEqual(data.file_hash(self.root / "sample.jsonl"), original_hash)

    def test_validation_retry_saves_only_one_final_record(self):
        runner = run.Runner(self.root, self.config, {"SYNTHETIC_TEST_KEY": "dummy-test-value"})
        with patch.object(run, "complete", side_effect=[("{}", {}), (json.dumps(blind(self.sample)), {})]) as complete:
            with contextlib.redirect_stdout(io.StringIO()):
                result = runner.stage(self.sample, "J1", "blind_structure")
        self.assertIsNotNone(result)
        self.assertEqual((complete.call_count, len(runner.records)), (2, 1))
        self.assertIn("No target score is prescribed", complete.call_args.args[1][-1]["content"])

    def test_initial_401_stops_all_followup_calls(self):
        with patch.object(run, "complete", side_effect=api.APIError("http_error", 401)) as complete:
            manifest = self.execute()
        self.assertEqual(complete.call_count, 1)
        self.assertEqual(manifest["status"], "incomplete")

    def test_j3_401_stops_other_review_candidates(self):
        samples = [self.sample, self.make_sample(name="second")]
        self.config["audit_fraction"] = 1
        for role, judge in self.config["judges"].items():
            judge["family"] = f"distinct-{role}"
            judge["model"] = f"synthetic-{role}"
        responses = [(json.dumps(r["output"]), {}) for s in samples for r in records_for(s)]
        responses += [api.APIError("http_error", 401), api.APIError("http_error", 401)]
        with patch.object(run, "complete", side_effect=responses) as complete:
            manifest = self.execute(samples, smoke=False)
        self.assertEqual(complete.call_count, 9)
        self.assertEqual(manifest["status"], "incomplete")

    def test_dry_run_does_not_read_key_or_call_network(self):
        with patch.object(run.os.environ, "get", side_effect=AssertionError("Credential access")), \
             patch.object(run, "complete", side_effect=AssertionError("Model call")), \
             patch.object(run, "discover_model", side_effect=AssertionError("Discovery")):
            result = run.run([self.sample], run.smoke_config(), self.root / "dry", smoke=True)
        self.assertEqual((result["status"], result["http_post_attempts"]), ("prepared", 0))

    def test_rejects_existing_outputs_same_family_and_multi_sample_smoke(self):
        directory = self.root / "protected"
        directory.mkdir()
        sentinel = directory / "keep.txt"
        sentinel.write_text("unchanged", encoding="utf-8")
        with self.assertRaises(ValueError):
            run.run([self.sample], self.config, directory, smoke=True)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged")
        with self.assertRaises(ValueError):
            run.checked_config(self.config, smoke=False)
        with self.assertRaises(ValueError):
            run.run([self.sample, self.sample], self.config, self.root / "bad", smoke=True)

    def test_tampered_sample_hash_is_rejected_before_output(self):
        self.sample["visible"]["question"] = "Tampered"
        with self.assertRaisesRegex(ValueError, "摘要"):
            run.run([self.sample], self.config, self.root / "bad", smoke=True)
        self.assertFalse((self.root / "bad").exists())

    def test_relabeling_identical_model_as_three_families_is_rejected(self):
        for role, judge in self.config["judges"].items():
            judge["family"] = f"distinct-{role}"
        with self.assertRaises(ValueError):
            run.checked_config(self.config, smoke=False)

    def test_aggregate_cli_preserves_unicode_line_separator_in_jsonl(self):
        self.sample["visible"]["question"] += "\u2028Unicode content"
        data.write_jsonl(self.root / "LLM5_samples.jsonl", [self.sample])
        data.write_jsonl(self.root / "LLM5_records.jsonl", records_for(self.sample))
        argv = ["LLM5_aggregate.py", "--run-dir", str(self.root),
                "--output-dir", str(self.root / "report"), "--audit-fraction", "0"]
        with patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
            agg.main()
        report = json.loads((self.root / "report" / "LLM5_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(report["execution"]["paired_complete_samples"], 1)

    def test_api_redaction_is_recursive(self):
        result = api.redact({"dummy-secret": ["Bearer dummy-secret", "sk-123456789012345"]}, "dummy-secret")
        self.assertEqual(result, {"[REDACTED]": ["Bearer [REDACTED]", "[REDACTED]"]})

    def test_api_refuses_redirects_and_unsafe_endpoints(self):
        with self.assertRaises(api.APIError):
            api.NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.test")
        for endpoint in ("http://remote.test/v1", "https://u:p@host.test", "https://host.test?secret=x",
                         "file:///tmp/file", "https://host.test/#fragment"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                api.valid_endpoint(endpoint)
        self.assertEqual(api.valid_endpoint("http://127.0.0.1:8080/v1"), "http://127.0.0.1:8080/v1")

    def test_api_http_errors_never_expose_response_body(self):
        for status, retryable in ((401, False), (429, True), (500, True)):
            body = io.BytesIO(b"PRIVATE_BODY dummy-secret")
            opener = Mock()
            opener.open.side_effect = urllib.error.HTTPError("https://mock.test", status, "PRIVATE_REASON", {}, body)
            with patch.object(api.urllib.request, "build_opener", return_value=opener):
                with self.assertRaises(api.APIError) as raised:
                    api.request_json("https://mock.test", "dummy-secret", {})
            self.assertEqual(raised.exception.retryable, retryable)
            self.assertNotIn("PRIVATE", str(raised.exception))
            self.assertEqual(body.tell(), 0)


if __name__ == "__main__":
    unittest.main()
