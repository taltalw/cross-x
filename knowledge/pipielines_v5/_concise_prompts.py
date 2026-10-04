"""Actual English prompts used by step 4 (documented verbatim)."""
SCREEN_PROMPT = """Find one compact, evidence-supported cross-domain task using the source
sample's core knowledge and every chosen fusion domain.
The existing question_plan and answer_plans are optional starting points.
Prefer the smallest coherent final target supported by the available evidence,
not a shorter wording of an over-expanded multi-part task.
Select only necessary retrieved samples, citing their exact prompt/completion
from their own domain. Do not invent facts, rewrite references, or add domains.
Produce compact_blueprint with one final target, a common answer form, and
necessary roles for every domain including the source. Obey blueprint_limits.
Multiple reasoning steps are allowed; multiple independent requested outputs
are not. Do not hide independent tasks inside a report, tuple, checklist, or
long code artifact. Preserve the source core knowledge and all chosen domains.
Terminology or setting alone does not establish necessity: explain which
inference or decision fails without each domain's knowledge.
Rewrite the plans and exactly three distinct short required-key-fact phrases
per fusion domain around this target. Three phrases do not mean three visible
subquestions. Do not pad them with duplicated paraphrases or unsupported needs.
Plan three concrete wrong outcomes for the retained error types. Missing domain
knowledge yields a wrong result by omitting/misusing necessary knowledge;
parallel knowledge fails to propagate a required result into the final decision;
incorrect relation misconnects the mapping, direction, object, or combination.
If no natural joint target is supported, return feasible=false, empty lists for
each selected_samples domain, and null for all plans and compact_blueprint.
Return only the required English JSON object (replace domain with actual names):
{
 "feasible": true, "reason": "Evidence-supported feasibility or rejection reason",
 "selected_samples": {"fusion_domain": [{"prompt": "Exact supplied prompt", "completion": "Exact supplied completion"}]},
 "question_plan": "Revised single-target plan",
 "answer_plans": [
  {"type": "correct", "missing_domain": null, "plan": "Correct result"},
  {"type": "missing_domain_knowledge", "missing_domain": "participating domain", "plan": "Concrete wrong result"},
  {"type": "parallel_knowledge", "missing_domain": null, "plan": "Concrete wrong result"},
  {"type": "incorrect_domain_relation", "missing_domain": null, "plan": "Concrete wrong result"}
 ],
 "required_key_facts": {"fusion_domain": [
  {"key_fact": "short phrase one", "necessity": "Necessary contribution"},
  {"key_fact": "short phrase two", "necessity": "Necessary contribution"},
  {"key_fact": "short phrase three", "necessity": "Necessary contribution"}
 ]},
 "compact_blueprint": {
  "target": "One final result", "answer_form": "number",
  "dependency_summary": "How the domains jointly determine this result",
  "domain_roles": {
   "source_domain": {"knowledge": "Required source knowledge", "role": "Contribution to result", "removal_effect": "What becomes wrong or underdetermined"},
   "fusion_domain": {"knowledge": "Required selected knowledge", "role": "Contribution to result", "removal_effect": "What becomes wrong or underdetermined"}
  }
 }
}
answer_form must be one of number, decision, short_text, expression, code.
selected_samples and required_key_facts cover only fusion_domains;
domain_roles covers the source and every fusion domain exactly.
"""

GENERATION_SCHEMA = """
Return only this English JSON object:
{
 "question": "Self-contained question asking one final result",
 "options": {"A": "Outcome", "B": "Outcome", "C": "Outcome", "D": "Outcome"},
 "answer": "A", "explanation": "Full correct reasoning, referring to content, not option letters",
 "distractor_analysis": [
  {"option": "B", "type": "missing_domain_knowledge", "missing_domain": "participating domain", "reason": "Erroneous step -> wrong result -> why this option"},
  {"option": "C", "type": "parallel_knowledge", "missing_domain": null, "reason": "Erroneous step -> wrong result -> why this option"},
  {"option": "D", "type": "incorrect_domain_relation", "missing_domain": null, "reason": "Erroneous step -> wrong result -> why this option"}
 ],
 "used_samples": {"fusion_domain": [{"prompt": "Exact supplied prompt", "completion": "Exact supplied completion"}]},
 "plan_adjustment": "Substantive change from revised plans, or empty string"
}
Each wrong option is annotated once; each error type occurs once. Cite only
actually used selected samples, at least one per fusion domain. Preserve schema.
"""

SYSTEM_PROMPT = """Write one compact, single-target cross-domain multiple-choice item from the
compact_blueprint, revised plans, and selected evidence.
Ask for one final result. Keep all participating domains necessary for it.
Do not expand the blueprint into a report, independent questions, or a worked
solution. A report with multiple unrelated results is not one target.
The question must be self-contained for a knowledgeable model that cannot see
source samples or construction metadata. Include necessary instance conditions,
units, precision, local API contracts and boundaries. Do not supply tested
general rules, formulas, or the entire cross-domain bridge as a given rule.
All four distinct options answer the same target in the declared answer_form.
Use concrete final outcomes, not explanations or statements about missing
knowledge. Put common conditions/code once in the question. Put reasoning and
error mechanisms in private metadata. For code, prefer a local completion
snippet and preserve newlines/indentation; do not give away tested logic in
common code. Obey supplied word AND character hard limits. The soft question
target is guidance, not a minimum; options may be single numbers.
Never remove spaces, truncate code, omit necessary conditions or discard a
domain to meet budgets. Do not expose difficulty, retrieval, coverage, or error
labels in question/options. Difficulty changes application conditions, relations
or boundary cases, not background length or independent subquestions.
Construct one correct option and three concrete wrong outcomes. For
missing_domain_knowledge, omit or misuse necessary domain knowledge; for
parallel_knowledge, fail to propagate a needed local result into the final
decision; for incorrect_domain_relation, connect a mapping, direction, object
or combination incorrectly. Explain the erroneous step and produced outcome
in reason, not a synonym of the label. These are construction intents, not
unique diagnoses recoverable from a short wrong answer.
Do not silently change target or domain set. Record substantive plan adjustments.
In free prose describe option CONTENT, never 'Option A', 'Choice B', etc.;
programmatic permutation moves structured labels only, not variables in code.
""" + GENERATION_SCHEMA

AUDIT_PROMPT = """Audit the actual visible multiple-choice item. No proposed answer key or
construction explanation is provided. Independently determine ALL correct
options, allowing none or several if invalid or underdetermined.
References are private provenance. Use them to verify tested domain knowledge,
not to supply instance-specific conditions missing from the visible question.
Judge self-containedness for a knowledgeable test taker without references.
Check one final target (not a bundled report), same outcome form for all options,
evidence support, no giveaway of tested knowledge or the entire bridge, and
no avoidable answer cues or surface shortcuts. For every participating domain,
including source, identify a necessary contribution and what fails without it.
Mentioning a domain, copying vocabulary, or selecting its sample does not prove
necessity. Removing a domain NAME is different from removing its KNOWLEDGE.
Flag decorative domains, ambiguity, unsupported facts and missing conditions.
Use uncertain rather than inventing certainty. One LLM audit does not prove
that all models are unable to use shortcuts and is not an independent expert
validation or a closed-book capability test. Do not infer unique cognitive
error categories from short wrong answers; mechanisms require separate review.
Return only English JSON:
{
 "correct_options": ["C"], "solution_summary": "Brief independent verification",
 "checks": {
  "single_target": "pass", "self_contained": "pass", "evidence_grounded": "pass",
  "no_knowledge_giveaway": "pass", "same_answer_form": "pass", "no_surface_shortcut": "pass"
 },
 "domain_necessity": {"actual_domain": {"necessary": true, "reason": "Required inference and removal consequence"}},
 "issues": []
}
checks allow pass/fail/uncertain; necessary allows true/false/null. Include each
participating domain exactly. correct_options allows zero or multiple distinct
labels. issues is a list of unresolved issue strings, empty only if none.
"""

REPAIR_PROMPT = """Rewrite the supplied original_candidate once using the specific structured
feedback. Return a new unpermuted candidate in the original generation schema.
Recheck every issue, not just length. Preserve source core knowledge, all
participating domains, the compact_blueprint's final target, evidence-supported
facts, necessary instance conditions, one correct option and three concrete
wrong outcomes. The previous audit may be wrong: verify it against evidence.
Do not simply change the answer key to the judge's label. Do not remove spaces,
truncate code, weaken domain dependence, or bundle independent outputs to fit
limits. Describe option content instead of option letters in free prose.
""" + SYSTEM_PROMPT
