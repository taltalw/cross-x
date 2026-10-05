"""必要性审计离线回归：证据契约、独立评分及人工复核路由。"""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from LLM5_tests import LLM5_test_pipeline as fixtures

agg, schema = fixtures.agg, fixtures.schema
NECESSITY = "cross_domain_necessity"
STAGES = ("evidence_scoring", "adjudication")
NECESSITY_FLAGS = ("single_domain_shortcut", "subset_shortcut", "redundant_domain")


class NecessityTests(unittest.TestCase):
    """复用样例工厂，不继承或重复执行 PipelineTests 的测试。"""

    def setUp(self):
        """建立合成资料，并沿用禁止实际联网的隔离环境。"""
        self.fixture = fixtures.PipelineTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.sample = self.fixture.sample

    def output(self, status, stage="evidence_scoring", score=2, sample=None):
        """生成指定审计状态的合法阶段输出。"""
        sample = sample or self.sample
        obj = (fixtures.evidence(sample, 4) if stage == "evidence_scoring"
               else fixtures.adjudication(sample, 4))
        obj["necessity_audit"] = fixtures.necessity_audit(sample, status)
        dimension = self.dimension(obj)
        prefix = "recommended_" if stage == "adjudication" else ""
        dimension.update({prefix + "status": "unjudgeable" if status == "unresolved" else "scored",
                          prefix + "score": None if status == "unresolved" else score})
        if stage == "evidence_scoring":
            dimension["unknown_reason"] = "unresolved_necessity" if status == "unresolved" else None
            if status != "not_found":
                obj["domain_checks"][-1]["necessity"] = (
                    "redundant" if status == "verified_shortcut" else "uncertain")
        elif status != "not_found":
            obj.update(human_review_required=True, human_review_reasons=["Review necessity evidence"])
        return obj

    def dimension(self, obj):
        """定位阶段输出中的必要性维度。"""
        if obj["stage"] == "evidence_scoring":
            return obj["dimensions"][NECESSITY]
        return next(item for item in obj["dimension_resolutions"] if item["dimension"] == NECESSITY)

    def validate(self, obj, sample=None):
        """按正式样本上下文校验单阶段输出。"""
        schema.validate_output(obj["stage"], obj, sample or self.sample)

    def records(self, status, review=False, final_status=None):
        """生成带必要性审计的配对评审和可选 J3 记录。"""
        rows = fixtures.records_for(self.sample, review=review)
        for row in rows:
            if row["stage"] == "evidence_scoring":
                row["output"] = self.output(status)
            elif row["stage"] == "adjudication":
                row["output"] = self.output(final_status or status, "adjudication", score=4
                                             if final_status == "not_found" else 2)
        return rows

    def test_verified_accepts_only_integer_zero_to_two_in_both_stages(self):
        for stage in STAGES:
            for score in (0, 1, 2):
                with self.subTest(stage=stage, score=score):
                    self.validate(self.output("verified_shortcut", stage, score))
            for score in (3, 4, -1, 5, True, False, 2.0, None, "2"):
                with self.subTest(stage=stage, score=score), self.assertRaises(ValueError):
                    self.validate(self.output("verified_shortcut", stage, score))

    def test_verified_cannot_be_unknown(self):
        for stage in STAGES:
            obj = self.output("verified_shortcut", stage)
            prefix = "recommended_" if stage == "adjudication" else ""
            self.dimension(obj).update({prefix + "status": "unjudgeable", prefix + "score": None})
            if stage == "evidence_scoring":
                self.dimension(obj)["unknown_reason"] = "unresolved_necessity"
            with self.subTest(stage=stage), self.assertRaises(ValueError):
                self.validate(obj)

    def test_unresolved_requires_unknown_not_zero_or_pass(self):
        for stage in STAGES:
            self.validate(self.output("unresolved", stage))
            for score in range(5):
                obj = self.output("unresolved", stage)
                prefix = "recommended_" if stage == "adjudication" else ""
                self.dimension(obj).update({prefix + "status": "scored", prefix + "score": score})
                if stage == "evidence_scoring":
                    self.dimension(obj)["unknown_reason"] = None
                with self.subTest(stage=stage, score=score), self.assertRaises(ValueError):
                    self.validate(obj)

    def test_audit_and_each_required_field_cannot_be_missing(self):
        for stage in STAGES:
            obj = self.output("verified_shortcut", stage)
            for field in (None, *obj["necessity_audit"]):
                bad = copy.deepcopy(obj)
                if field is None:
                    del bad["necessity_audit"]
                else:
                    del bad["necessity_audit"][field]
                with self.subTest(stage=stage, field=field), self.assertRaises(ValueError):
                    self.validate(bad)

    def test_verified_rejects_incomplete_or_nonvisible_proof(self):
        domain = self.sample["review_bundle"]["declared_domains"][-1]
        mutations = [{"omitted_domains": value} for value in
                     ([], ["unknown_domain"], [domain, domain], domain, [None])]
        mutations += [{"candidate_answer": value} for value in (None, "", " ", 1)]
        mutations += [{"uniquely_determines_answer": value} for value in (None, False, 1, "true")]
        mutations += [{field: value} for field in ("solution_sketch", "basis") for value in ("", " ", None)]
        mutations += [{"evidence_pointers": value} for value in
                      ([], ["src1"], ["reference_answer"], ["reference_explanation"], ["metadata"],
                       ["options.Z"], ["question", "src1"])]
        for stage in STAGES:
            for mutation in mutations:
                obj = self.output("verified_shortcut", stage)
                obj["necessity_audit"].update(mutation)
                with self.subTest(stage=stage, mutation=mutation), self.assertRaises(ValueError):
                    self.validate(obj)

    def test_formally_present_visible_inputs_are_valid_evidence(self):
        sample = copy.deepcopy(self.sample)
        sample["visible"]["visible_inputs"] = {"constraint": "A is uniquely valid"}
        for stage in STAGES:
            obj = self.output("verified_shortcut", stage, sample=sample)
            obj["necessity_audit"]["evidence_pointers"] = ["visible_inputs"]
            self.validate(obj, sample)

    def test_absent_visible_inputs_cannot_be_cited(self):
        for absent in ("missing", "null"):
            sample = copy.deepcopy(self.sample)
            if absent == "missing":
                sample["visible"].pop("visible_inputs", None)
            else:
                sample["visible"]["visible_inputs"] = None
            for stage in STAGES:
                obj = self.output("verified_shortcut", stage, sample=sample)
                obj["necessity_audit"]["evidence_pointers"] = ["visible_inputs"]
                with self.subTest(absent=absent, stage=stage), self.assertRaises(ValueError):
                    self.validate(obj, sample)

    def test_verified_omitted_domains_must_be_redundant(self):
        for necessity in ("necessary", "uncertain"):
            obj = self.output("verified_shortcut")
            obj["domain_checks"][-1]["necessity"] = necessity
            with self.subTest(necessity=necessity), self.assertRaises(ValueError):
                self.validate(obj)

    def test_confirmed_flags_and_redundancy_cannot_use_unknown(self):
        for finding in (*NECESSITY_FLAGS, "domain_check"):
            obj = self.output("unresolved")
            if finding == "domain_check":
                obj["domain_checks"][-1]["necessity"] = "redundant"
            else:
                obj["flags"] = [dict(type=finding, status="confirmed", description="Confirmed shortcut",
                                     evidence_pointers=["question"])]
            with self.subTest(finding=finding), self.assertRaises(ValueError):
                self.validate(obj)

    def test_suspected_flags_and_uncertain_domains_require_unresolved(self):
        for finding in (*NECESSITY_FLAGS, "domain_check"):
            obj = self.output("not_found", score=4)
            if finding == "domain_check":
                obj["domain_checks"][-1]["necessity"] = "uncertain"
            else:
                obj["flags"] = [dict(type=finding, status="suspected", description="Possible shortcut",
                                     evidence_pointers=["question"])]
            with self.subTest(finding=finding):
                with self.assertRaises(ValueError):
                    self.validate(obj)
                obj["necessity_audit"] = fixtures.necessity_audit(self.sample, "unresolved")
                self.dimension(obj).update(status="unjudgeable", score=None, unknown_reason="unresolved_necessity")
                self.validate(obj)

    def test_verified_proof_takes_priority_over_remaining_suspicions(self):
        obj = self.output("verified_shortcut")
        obj["domain_checks"][0]["necessity"] = "uncertain"
        obj["flags"] = [dict(type="subset_shortcut", status="suspected", description="Another possible route",
                             evidence_pointers=["question"])]
        self.validate(obj)

    def test_two_three_four_domains_support_single_and_subset_shortcuts(self):
        for k in (2, 3, 4):
            sample = self.fixture.make_sample(k=k, name=f"necessity-{k}")
            for omitted_count in (1, k - 1):
                for stage in STAGES:
                    obj = self.output("verified_shortcut", stage, sample=sample)
                    omitted = sample["review_bundle"]["declared_domains"][-omitted_count:]
                    obj["necessity_audit"]["omitted_domains"] = omitted
                    if stage == "evidence_scoring":
                        for check in obj["domain_checks"]:
                            check["necessity"] = "redundant" if check["domain"] in omitted else "necessary"
                    with self.subTest(k=k, omitted_count=omitted_count, stage=stage):
                        self.validate(obj, sample)

    def test_not_found_does_not_impose_a_score_or_lower_other_dimensions(self):
        for stage in STAGES:
            for score in range(5):
                obj = self.output("not_found", stage, score)
                self.validate(obj)
                if stage == "evidence_scoring":
                    values = {d: v["score"] for d, v in obj["dimensions"].items()}
                else:
                    values = {v["dimension"]: v["recommended_score"] for v in obj["dimension_resolutions"]}
                self.assertTrue(all(value == 4 for dimension, value in values.items() if dimension != NECESSITY))

    def test_not_found_cannot_claim_omitted_domains_or_uniqueness(self):
        for stage in STAGES:
            for mutation in ({"omitted_domains": self.sample["review_bundle"]["declared_domains"][:1]},
                             {"uniquely_determines_answer": True}, {"uniquely_determines_answer": False}):
                obj = self.output("not_found", stage)
                obj["necessity_audit"].update(mutation)
                with self.subTest(stage=stage, mutation=mutation), self.assertRaises(ValueError):
                    self.validate(obj)

    def test_no_flag_still_routes_verified_and_unresolved_to_human(self):
        for status in ("verified_shortcut", "unresolved"):
            rows = self.records(status)
            self.assertTrue(all(not row["output"].get("flags") for row in rows))
            for row in rows:
                self.validate(row["output"])
            route = agg.route_samples([self.sample], rows, audit_fraction=0)[0]
            with self.subTest(status=status):
                self.assertTrue(route["rule_triggered"])
                self.assertTrue(route["needs_review"])
                self.assertEqual(route["status"], "pending_human")
                self.assertFalse(route["initial_joint_pass"])

    def test_unresolved_statistics_keep_u_out_of_zero_and_pass_counts(self):
        report = agg.aggregate([self.sample], self.records("unresolved"), audit_fraction=0)
        rows = [row for row in report["dimension_statistics"] if row["group_by"] == "overall"]
        for row in rows:
            if row["dimension"] == NECESSITY:
                self.assertEqual((row["denominator"], row["numeric_n"], row["unjudgeable_count"]), (1, 0, 1))
                self.assertIsNone(row["mean"])
                self.assertEqual((row["score_0_count"], row["pass_count"], row["pass_rate"]), (0, 0, 0))
            else:
                self.assertEqual((row["mean"], row["pass_count"], row["unjudgeable_count"]), (4, 1, 0))
        self.assertEqual(report["final_outcomes"]["machine_pass"]["count"], 0)
        self.assertEqual(report["final_outcomes"]["machine_fail"]["count"], 0)

    def test_j3_audit_findings_require_human_even_without_unresolved_issues(self):
        for status in ("verified_shortcut", "unresolved"):
            obj = self.output(status, "adjudication")
            self.assertEqual(obj["unresolved_issues"], [])
            self.validate(obj)
            obj.update(human_review_required=False, human_review_reasons=[])
            with self.subTest(status=status), self.assertRaises(ValueError):
                self.validate(obj)

    def test_j3_cannot_wash_initial_findings_into_machine_pass(self):
        for status in ("verified_shortcut", "unresolved"):
            rows = self.records(status, review=True, final_status="not_found")
            for row in rows:
                self.validate(row["output"])
            route = agg.route_samples([self.sample], rows, audit_fraction=0)[0]
            with self.subTest(status=status):
                self.assertTrue(route["recommended_joint_pass"])
                self.assertEqual(route["status"], "pending_human")
                self.assertTrue(route["human_review_reasons"])
                report = agg.aggregate([self.sample], rows, audit_fraction=0)
                self.assertEqual(report["final_outcomes"]["machine_pass"]["count"], 0)

    def test_j3_verified_or_unresolved_final_audit_stays_pending_human(self):
        for status in ("verified_shortcut", "unresolved"):
            rows = self.records(status, review=True)
            for row in rows:
                self.validate(row["output"])
            route = agg.route_samples([self.sample], rows, audit_fraction=0)[0]
            with self.subTest(status=status):
                self.assertEqual(route["status"], "pending_human")
                self.assertFalse(route["recommended_joint_pass"])

    def test_aggregate_rejects_contradictory_j3_audit_scores(self):
        for status in ("verified_shortcut", "unresolved"):
            rows = self.records(status, review=True)
            self.dimension(rows[-1]["output"]).update(recommended_status="scored", recommended_score=4)
            with self.subTest(status=status), self.assertRaises(ValueError):
                agg.route_samples([self.sample], rows, audit_fraction=0)

    def test_clean_not_found_can_pass_without_forced_review(self):
        rows = fixtures.records_for(self.sample, scores=(4, 4))
        route = agg.route_samples([self.sample], rows, audit_fraction=0)[0]
        self.assertEqual(route["status"], "llm_consensus_pass")
        self.assertFalse(route["needs_review"])


if __name__ == "__main__":
    unittest.main()
