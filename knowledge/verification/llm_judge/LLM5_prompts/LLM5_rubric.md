# Fixed LLM5 rubric, English v2

Each dimension is scored independently from 0 through 4. Scores 3 and 4 meet the dimension threshold. A score of 0 means a core requirement is demonstrably absent or contradicted; 1 means a serious defect; 2 means partial satisfaction with a substantive unresolved defect; 3 means satisfaction with at most minor nonessential defects; 4 means clear, sufficient, explicitly checkable support. A 3 is not "probably fine" and a 4 is not a reward for verbosity. Use exact question, option, derivation, or source evidence.

## cross_domain_necessity

Question: Does every declared domain make an indispensable substantive contribution, and does a reproducible single-domain, subset, input-leakage, or generic shortcut solve the entire task?

- 0: The task requires no substantive cross-domain knowledge, or a single domain/general shortcut completes all requirements.
- 1: At least one declared domain is decorative: removing its domain reasoning still permits the complete correct answer, although some cross-domain work may remain.
- 2: Domains may contribute, but a contribution can be substantively replaced or bypassed; necessity is not established.
- 3: Every domain has a locatable substantive role, and no valid single-domain/subset shortcut is found; only minor wording issues remain.
- 4: Each domain's essential knowledge, use location, and loss on removal are explicit, and plausible alternative routes have been checked against the question and options.

Check the source domain and every added domain, whether there are two, three, or four. Do not average domain contributions to conceal redundancy. Any demonstrably redundant declared domain prevents a 3 or 4. Distinguish an entirely defeated cross-domain requirement (0) from partial cross-domain work with one seriously redundant domain (1). Failure to imagine a shortcut is insufficient for 4. Removing a necessary number does not establish necessity of the associated discipline. A shortcut must complete the whole task, not just one subquestion. Knowledge already internalized by the solver still counts as knowledge use. Given data, rules, or assumptions are only problematic if they replace the substantive judgment being tested.

Mandatory necessity scoring boundary: a verified valid route omitting any required domain receives a numeric necessity score of 0 through 2. If a material necessity concern cannot be resolved and no decisive shortcut is verified, use unjudgeable/null with unknown_reason=unresolved_necessity; do not use 2 to encode mere uncertainty. An established defect may still justify 0 through 2 despite unrelated uncertainty. A routine check that found no shortcut is not itself an unresolved concern. In multiple-choice tasks, evaluate whether a reduced route uniquely selects the correct option under the actual grading contract, even if it bypasses part of the intended derivation. Shared statements across all options are not discriminative evidence.

## fusion_dependency

Question: Do domains have knowledge dependencies that affect the answer, rather than independent subanswers merely presented together?

- 0: Parts are completely independent; the answer concatenates unrelated subanswers.
- 1: Only a shared setting or terminology connects the domains, with almost no substantive information transfer.
- 2: Some local connection exists, but a domain remains detached or a connection does not affect the conclusion.
- 3: All declared domains participate in one meaningful reasoning dependency structure; cross-domain transfer changes subsequent processing.
- 4: Cross-domain inputs, outputs, constraints, or judgments are explicitly verifiable; the complete structure is tightly and substantively connected.

For an edge, state what domain X produces, where and how domain Y uses it, and why the final answer changes. Not every pair needs a direct edge, and cycles are not required. A chain A to B to C or A and B jointly constraining C can qualify. A connected diagram alone is insufficient without semantic effects. One domain's numerical result used by another domain's rule can be a real dependency. Independent questions combined into a single option are not. Necessary knowledge in separate obligatory subquestions can coexist with poor fusion dependency. Never fabricate edges; an empty edge list is permitted.

## correctness_evaluability

Question: Are the task conditions, reference answer, derivation, and formal grading contract reliable?

- 0: The core answer is demonstrably wrong, the task is internally contradictory, or no defensible correct answer exists.
- 1: Serious missing conditions, ungradable multiplicity, or a key calculation/reasoning error require substantive rewriting.
- 2: The main task is solvable, but a substantive issue affects accepted answers, a key step, or grading.
- 3: Conditions are sufficient, key answers correct, and uniqueness/allowed range and grading rules clear; at most minor defects remain.
- 4: Key derivations and options are individually checked; boundaries, units, rounding, and the grading contract are clear and sufficient.

For single-choice questions verify exactly one correct option. One gold label does not establish actual uniqueness. Open-answer questions need an explicit allowable range, equivalent answers, and scoring rules; do not invent them. A grading rule marked protocol_defined describes the evaluation protocol, not a rule proven to have existed in the original dataset.

## knowledge_grounding

Question: Are key knowledge claims and cross-domain inferences supported in a manner consistent with how the materials are used?

- 0: A source is demonstrably fabricated or a core conclusion directly contradicts the supplied evidence.
- 1: Material with incompatible conditions, scope, or conclusions is explicitly relied on as a key basis.
- 2: Some key claims are supported, but there is a locatable support gap or an invalid transfer.
- 3: Key knowledge is traceable, the material fits its use, and inferences connect; only secondary gaps remain.
- 4: Key knowledge, applicability conditions, and derivations are individually traceable; material is sufficient with no key unsupported claim.

Distinguish direct textual support, valid derivation under given conditions, an explicit task assumption, unsupported claims, and contradiction. The source need not literally contain the final cross-domain answer, but new derivations must be valid. Source availability, retrieval similarity, or atomic completions do not prove correctness. A verifiable invalid transfer warrants a low score. A missing source that prevents verification warrants unjudgeable, not a fabricated finding that the underlying fact is wrong. Report the actual provenance level; local paths, IDs, lines, or hashes establish atomic-record traceability, not verification of an original textbook or authority. An unresolved provenance status is not automatically a contradiction if the provided text still permits substantive checking.

## naturalness_clarity

Question: Is the scenario and fusion objective reasonable, and is the wording minimally sufficient?

- 0: The scenario or expression fails so severely that the actual task cannot be understood.
- 1: Forced stitching or critical ambiguity seriously impedes answering.
- 2: The question is basically readable, but substantive redundancy, ambiguity, decorative background, or unnecessary complexity remains.
- 3: The objective is reasonable, wording clear, and information mostly minimally sufficient, with at most minor redundancy.
- 4: The scenario closely fits the fusion objective; conditions and wording are precise, with no removable substantive decoration.

Do not reward shortness, ornate language, or difficulty alone. A clearly stated reasonable hypothetical scenario can qualify; every question need not reproduce a real-world case.

## Unjudgeable and evidence discipline

Assess unjudgeability per dimension. Use status="unjudgeable", score=null, one of missing_source, insufficient_expertise, missing_grading_rule, insufficient_visible_input, unresolved_evidence_conflict, or unresolved_necessity as unknown_reason, and explain the concrete information needed. If a failure is already sufficiently established, score 0 through 2 and retain that finding even when other details cannot be checked. Do not turn missing files into falsehoods. Timeouts, malformed JSON, and truncation are execution failures and must not be represented as five invented judgments.

A confirmed key answer error conflicts with correctness_evaluability >=3; a confirmed single-domain/subset shortcut or redundant domain conflicts with cross_domain_necessity >=3; an invalid substantive dependency conflicts with fusion_dependency >=3; a confirmed core source contradiction conflicts with knowledge_grounding >=3. Suspected issues remain explicit and trigger review without silently becoming confirmed facts. A score vector cannot neutralize a confirmed critical defect by averaging.
