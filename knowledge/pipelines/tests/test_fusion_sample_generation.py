"""Offline tests for step-5 generation, plan association, and coverage retention."""

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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("fusion_samples", ROOT / "5_generate_fusion_samples.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def plan_row(domains=None):
    domains = domains or ["chemistry"]
    return {"source_domain": "geography", "sample": {"prompt": "Why is arrival delayed?", "completion": "Routing and retention take time."},
            "fusion_domains": domains, "status": "feasible", "fusion_idea": {
                "idea": "Combine transport and specialized knowledge.", "correct_answer_plan": "Apply all domains to the joint task.",
                "distractor_plans": [{"missing_domain": d, "plan": f"Omit the key {d} inference."} for d in ["geography", *domains]]}}


def filtered_row(status="partial", domains=None):
    plan = plan_row(domains)
    domains = plan["fusion_domains"]
    knowledge = {}
    for domain in domains:
        knowledge[domain] = {"status": status, "missing_knowledge": "Further conditions are missing." if status != "sufficient" else "",
                             "materials": [] if status == "none" else [{
                                 "candidate_id": domain + ":one", "source_file": f"/atomic/{domain}/train.jsonl", "source_line": 3,
                                 "sample": {"prompt": "A question about a domain principle.", "completion": "The supported principle."},
                                 "supported_knowledge": "The material provides a relevant principle.",
                                 "evidence": [{"field": "completion", "quote": "The supported principle."}],
                             }]}
    return {"source_domain": plan["source_domain"], "sample": plan["sample"], "fusion_domains": domains,
            "fusion_idea": plan["fusion_idea"]["idea"], "queries": {d: ["core concept", "specific mechanism", "applicable rule"] for d in domains},
            "knowledge": knowledge}


def generation(domains=None):
    domains = ["geography", *(domains or ["chemistry"])]
    labels = list("ABCD")
    incorrect = [label for label in labels if label != "B"]
    return {"question": "A complete hypothetical joint question?",
            "options": {label: f"Distinct option {label}." for label in labels}, "answer": "B",
            "explanation": "All participating domains support the result.",
            "distractor_analysis": [
                {"option": "A", "type": "missing_domain_knowledge", "missing_domain": domains[0], "reason": "A missing domain principle causes this mistake."},
                {"option": "C", "type": "parallel_knowledge", "missing_domain": None, "reason": "Independent conclusions omit the required interaction."},
                {"option": "D", "type": "incorrect_domain_relation", "missing_domain": None, "reason": "The causal direction between domains is reversed."}],
            "used_material_ids": [domain + ":one" for domain in domains[1:]], "plan_adjustment": ""}


class FakeAPI:
    base_url, model = "https://mock.invalid/v1", "mock-model"

    def __init__(self):
        self.calls = []

    def chat(self, prompt, data, validate, max_tokens):
        self.calls.append(copy.deepcopy(data))
        value = generation(data["fusion_domains"])
        value["knowledge_status"] = {d: "sufficient" for d in data["fusion_domains"]}
        value["status"] = "generated"
        return validate(value)


class PlanTests(unittest.TestCase):
    def test_exact_join_order_independence_and_no_line_alignment(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            unrelated = plan_row(); unrelated["sample"]["prompt"] = "Different original question"
            actual = plan_row(["chemistry", "medical"])
            (root / "plans.jsonl").write_text(json.dumps(unrelated) + "\n\n" + json.dumps(actual) + "\n")
            index = m.PlanIndex(root)
            row = filtered_row(domains=["medical", "chemistry"])
            entry, error = index.match(row)
            self.assertIsNone(error)
            self.assertEqual(entry["source_line"], 3)
            self.assertEqual(entry["plan"], actual["fusion_idea"])
            row["sample"]["completion"] += " Changed."
            self.assertIsNone(index.match(row)[0])

    def test_duplicate_plans_ambiguity_and_idea_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); path = root / "plans.jsonl"; plan = plan_row()
            path.write_text(json.dumps(plan) + "\n" + json.dumps(plan) + "\n")
            self.assertIsNotNone(m.PlanIndex(root).match(filtered_row())[0])
            other = copy.deepcopy(plan); other["fusion_idea"]["correct_answer_plan"] = "Different plan."
            path.write_text(json.dumps(plan) + "\n" + json.dumps(other) + "\n")
            self.assertIn("Multiple", m.PlanIndex(root).match(filtered_row())[1])
            row = filtered_row(); row["fusion_idea"] = "New idea."
            self.assertIn("differs", m.PlanIndex(root).match(row)[1])

    def test_cross_group_plans_rejected(self):
        source = Path("/data/results_5.5/4_filter_knowledge/input.jsonl")
        self.assertEqual(m.plan_directory(source), Path("/data/results_5.5/1_generate_fusion_ideas"))
        with self.assertRaisesRegex(ValueError, "same results group"):
            m.plan_directory(source, Path("/data/results_6/1_generate_fusion_ideas"))


class ValidationTests(unittest.TestCase):
    def test_all_domain_counts_and_evidence(self):
        candidates = [d for d in m.DOMAINS if d != "geography"]
        for count in range(1, 7):
            row = filtered_row(domains=candidates[:count])
            coverage, materials = m.validate_knowledge(row)
            result = m.validate_generation(generation(candidates[:count]), ["geography", *candidates[:count]], materials)
            self.assertEqual(len(result["options"]), 4)
            self.assertEqual(m.generation_input(row, plan_row(candidates[:count])["fusion_idea"])["option_count"], 4)
            self.assertTrue(all(v["status"] == "partial" for v in coverage.values()))
        bad = filtered_row()
        bad["knowledge"]["chemistry"]["materials"][0]["evidence"][0]["quote"] = "Unsupported quote"
        with self.assertRaises(ValueError):
            m.validate_knowledge(bad)

    def test_invalid_generation_rejected(self):
        transforms = [
            lambda v: v["options"].pop("C"),
            lambda v: v["options"].update(C=v["options"]["A"]),
            lambda v: v.update(answer="A and B"),
            lambda v: v["distractor_analysis"].pop(),
            lambda v: v["distractor_analysis"][0].update(option="B"),
            lambda v: v["distractor_analysis"][0].update(missing_domain="history"),
            lambda v: v["distractor_analysis"][0].update(missing_domain=None),
            lambda v: v["distractor_analysis"][1].update(missing_domain="chemistry"),
            lambda v: v["distractor_analysis"][1].update(type="incorrect_domain_relation"),
            lambda v: v["distractor_analysis"][1].update(type="unknown"),
            lambda v: v["distractor_analysis"][1].pop("missing_domain"),
            lambda v: v["options"].update(E="Fifth option"),
            lambda v: v["distractor_analysis"][0].update(reason=""),
            lambda v: v.update(used_material_ids=["chemistry:invented"]),
            lambda v: v.update(used_material_ids=[]),
            lambda v: v.update(used_material_ids=["chemistry:one", "chemistry:one"]),
            lambda v: v.update(plan_adjustment=None),
        ]
        for change in transforms:
            value = generation(); change(value)
            with self.assertRaises(ValueError):
                m.validate_generation(value, ["geography", "chemistry"], {"chemistry:one": "chemistry"})

    def test_each_fusion_domain_must_contribute_material(self):
        value = generation(["chemistry", "medical"])
        value["used_material_ids"] = ["chemistry:one"]
        with self.assertRaisesRegex(ValueError, "each fusion domain"):
            m.validate_generation(value, ["geography", "chemistry", "medical"], {"chemistry:one": "chemistry", "medical:one": "medical"})

    def test_missing_knowledge_can_target_any_domain_and_answer_any_option(self):
        for domain in ["geography", "chemistry", "medical"]:
            for answer in "ABCD":
                value = generation(["chemistry", "medical"])
                value["answer"] = answer
                incorrect = [label for label in "ABCD" if label != answer]
                for item, label in zip(value["distractor_analysis"], incorrect):
                    item["option"] = label
                value["distractor_analysis"][0]["missing_domain"] = domain
                result = m.validate_generation(value, ["geography", "chemistry", "medical"], {"chemistry:one": "chemistry", "medical:one": "medical"})
                self.assertEqual(result["answer"], answer)
                self.assertEqual({item["type"] for item in result["distractor_analysis"]},
                                 {"missing_domain_knowledge", "parallel_knowledge", "incorrect_domain_relation"})


class GenerationTests(unittest.TestCase):
    def test_partial_is_generated_and_flags_plans_are_retained(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / "plans.jsonl").write_text(json.dumps(plan_row()) + "\n")
            api = FakeAPI(); generator = m.Generator(api, root / "cache.sqlite3")
            try:
                row = filtered_row()
                result = m.process_row(row, m.PlanIndex(root), generator, root / "filtered.jsonl", 9)
                self.assertNotIn("status", result)
                self.assertEqual(result["knowledge_status"]["chemistry"], "partial")
                self.assertEqual(result["missing_knowledge"]["chemistry"], "Further conditions are missing.")
                self.assertEqual(api.calls[0]["fusion_idea"]["question_plan"], plan_row()["fusion_idea"]["idea"])
                self.assertEqual(api.calls[0]["fusion_idea"]["answer_plan"], {
                    "correct_answer": plan_row()["fusion_idea"]["correct_answer_plan"],
                    "distractors": plan_row()["fusion_idea"]["distractor_plans"],
                })
                self.assertEqual(api.calls[0]["original_sample"]["question"], row["sample"]["prompt"])
                self.assertEqual(api.calls[0]["fusion_samples"]["chemistry"][0]["answer"], row["knowledge"]["chemistry"]["materials"][0]["sample"]["completion"])
                self.assertNotIn("knowledge_status", api.calls[0])
                self.assertEqual(result["provenance"]["filtered_line"], 9)
                self.assertEqual(result["provenance"]["plan_line"], 1)
                self.assertNotIn("reference_plan", result)
                generator.generate(row, plan_row()["fusion_idea"], {"chemistry:one": "chemistry"})
                self.assertEqual(len(api.calls), 1)
                # Changing the coverage gap changes the request/cache key.
                row["knowledge"]["chemistry"]["missing_knowledge"] = "A new gap."
                generator.generate(row, plan_row()["fusion_idea"], {"chemistry:one": "chemistry"})
                self.assertEqual(len(api.calls), 2)
            finally:
                generator.close()

    def test_sufficient_and_partial_together(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); plan = plan_row(["chemistry", "medical"])
            (root / "plans.jsonl").write_text(json.dumps(plan) + "\n")
            row = filtered_row(domains=["chemistry", "medical"])
            row["knowledge"]["chemistry"].update(status="sufficient", missing_knowledge="")
            generator = m.Generator(FakeAPI(), root / "cache.sqlite3")
            try:
                result = m.process_row(row, m.PlanIndex(root), generator, root / "input.jsonl", 1)
                self.assertNotIn("status", result)
                self.assertEqual(result["knowledge_status"], {"chemistry": "sufficient", "medical": "partial"})
            finally:
                generator.close()

    def test_none_skips_and_missing_plan_errors_without_api(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / "plans.jsonl").write_text(json.dumps(plan_row()) + "\n")
            api = FakeAPI(); generator = m.Generator(api, root / "cache.sqlite3")
            try:
                index = m.PlanIndex(root)
                result = m.process_row(filtered_row("none"), index, generator, root / "input.jsonl", 1)
                self.assertIsNone(result)
                row = filtered_row(); row["sample"]["prompt"] = "Unknown original"
                with self.assertRaisesRegex(ValueError, "No step-1 plan"):
                    m.process_row(row, index, generator, root / "input.jsonl", 2)
                self.assertEqual(api.calls, [])
            finally:
                generator.close()

    def test_llm_eligibility_only_response_is_invalid_and_context_guard(self):
        class RejectingAPI(FakeAPI):
            def chat(self, prompt, data, validate, max_tokens):
                return validate({"status": "not_feasible", "reason": "Unavoidable unsupported knowledge."})
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / "plans.jsonl").write_text(json.dumps(plan_row()) + "\n")
            generator = m.Generator(RejectingAPI(), root / "cache.sqlite3")
            try:
                with self.assertRaisesRegex(ValueError, "question"):
                    m.process_row(filtered_row(), m.PlanIndex(root), generator, root / "input.jsonl", 1)
                generator.max_input_chars = 10
                with self.assertRaisesRegex(ValueError, "no material was truncated"):
                    generator.generate(filtered_row(), plan_row()["fusion_idea"], {"chemistry:one": "chemistry"})
            finally:
                generator.close()


class IntegrationTests(unittest.TestCase):
    def test_none_rows_are_absent_from_saved_results(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stderr(io.StringIO()):
            root = Path(temp); plans_dir = root / "plans"; plans_dir.mkdir()
            (plans_dir / "plans.jsonl").write_text(json.dumps(plan_row()) + "\n")
            source, target = root / "input.jsonl", root / "out.jsonl"
            source.write_text(''.join(json.dumps(filtered_row(status)) + '\n' for status in ['none', 'partial', 'sufficient', 'none']))
            api = FakeAPI(); generator = m.Generator(api, root / "cache.sqlite3")
            try:
                report = m.run_file(source, target, m.PlanIndex(plans_dir), generator)
                rows = [json.loads(line) for line in target.read_text().splitlines()]
                self.assertEqual(report['generated'], 2)
                self.assertEqual(report['skipped_none'], 2)
                self.assertEqual([r['knowledge_status']['chemistry'] for r in rows], ['partial', 'sufficient'])
                self.assertEqual([r['provenance']['filtered_line'] for r in rows], [2, 3])
                self.assertTrue(all('status' not in r and 'knowledge_coverage' not in r for r in rows))
                self.assertEqual(len(api.calls), 2)
            finally:
                generator.close()

    def test_partial_output_retained_on_error(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stderr(io.StringIO()):
            root = Path(temp); plans_dir = root / "plans"; plans_dir.mkdir()
            (plans_dir / "plans.jsonl").write_text(json.dumps(plan_row()) + "\n")
            source, target = root / "input.jsonl", root / "out.jsonl"
            source.write_text(json.dumps(filtered_row()) + "\n" + json.dumps(filtered_row()) + "\n")
            class Generator:
                calls = 0
                def generate(self, *args):
                    self.calls += 1
                    if self.calls == 2:
                        raise m.APIError("Unavailable")
                    return generation()
            with self.assertRaisesRegex(ValueError, "completed output retained"):
                m.run_file(source, target, m.PlanIndex(plans_dir), Generator())
            self.assertEqual(len(target.read_text().splitlines()), 1)

    def test_bilingual_template_matches_code(self):
        document = (ROOT / "5_generate_fusion_samples_prompt_bilingual.md").read_text()
        self.assertEqual(document.split("## English Template\n\n", 1)[1], m.SYSTEM_PROMPT_TEMPLATE)
        for example in re.findall(r"```json\n(.*?)\n```", document, re.S):
            json.loads(example)

    def test_shell_keeps_each_group_configuration_and_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); fake = root / "fake-python"; log = root / "calls.jsonl"
            fake.write_text("#!/usr/bin/env python3\nimport os,sys,json\nwith open(os.environ['TEST_CALL_LOG'],'a') as f:f.write(json.dumps({'args':sys.argv[1:],'model':os.environ['MODEL'],'url':os.environ['API_BASE_URL'],'key':os.environ['API_KEY']})+'\\n')\n")
            fake.chmod(0o755)
            for group in ("results_5.5", "results_6"):
                directory = root / group / "4_filter_knowledge"; directory.mkdir(parents=True)
                for filename in ("medical_count_2.jsonl", "file with spaces.jsonl"):
                    (directory / filename).write_text("{}\n")
            env = dict(os.environ, KNOWLEDGE_ROOT=str(root), PYTHON_BIN=str(fake), TEST_CALL_LOG=str(log))
            for suffix in ("5_5", "6"):
                for name in ("API_BASE_URL", "API_KEY", "MODEL"):
                    env[f"{name}_{suffix}"] = f"mock-{name}-{suffix}"
            script = ROOT / "run_5_generate_fusion_samples.sh"
            subprocess.run(["bash", str(script), "--overwrite"], env=env, cwd=temp, check=True)
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(len(calls), 2)
            for call, group, suffix in zip(calls, ("results_5.5", "results_6"), ("5_5", "6")):
                args = call["args"]
                self.assertEqual(args[args.index("--plans-dir") + 1], str(root / group / "1_generate_fusion_ideas"))
                self.assertEqual(args[args.index("--output-root") + 1], str(root / group / "5_generate_fusion_samples"))
                for actual, name in (("model", "MODEL"), ("url", "API_BASE_URL"), ("key", "API_KEY")):
                    self.assertEqual(call[actual], env[f"{name}_{suffix}"])
            rejected = subprocess.run(["bash", str(script), "--model=shared"], env=env, capture_output=True)
            self.assertEqual(rejected.returncode, 1)


if __name__ == "__main__":
    unittest.main()
