# 第 4 步提示词 / Step-4 prompts（v6）

本文件与 `4_generate_fusion_question.py` 中的实际提示词同步。筛选提示词、筛选 payload、`validate_screening()` 和 `feasible` 判定保持原实现；本次只加强筛选通过后的生成、硬检查、程序化排列、盲审和最多一次定向重写。

题面只保留必要情境、数据、边界条件和一个最终问题。四个选项回答同一个问题并采用同一种答案形式，优先给出最终结果。完整推理在 `explanation`，错误步骤 → 错误结果 → 对应选项在 `distractor_analysis.reason`，知识依赖在构造元数据 `compact_blueprint`，证据在 `used_samples` 和原始 `retrieval` 元数据。短选项不承担错误解释；三种错误类型是构造意图，不是从短答案反推的认知诊断。

所有英文块以下均为运行时原文。

## SCREEN_PROMPT（保留原文）

```text
Find a natural cross-domain question that can be constructed
from the original sample and the retrieved samples in every fusion domain.
The existing question_plan and answer_plans are optional starting points,
not requirements that the retrieved samples must match.

Tasks:
1. Select the exact retrieved samples that can contribute necessary knowledge
   to one joint question with the source sample. Use every fusion domain.
2. If such a question is feasible, revise question_plan and all four
   answer_plans to fit the selected samples. Preserve the source sample's core
   knowledge and the chosen fusion_domains.
3. Rewrite required_key_facts to describe the knowledge actually used from
   each fusion domain: exactly three short keyword phrases and a brief
   necessity for each.

Requirements:
- Judge facts from the original prompt and completion of each sample. Do not
  invent facts or add an unrelated domain merely to force a combination.
- Do not reject a useful sample because it does not support the old plan;
  adjust the plan to what the retrieved material can naturally support.
- Set feasible to false only when the available samples cannot support one
  coherent joint task using every fusion domain. Then use null for all plan
  fields and empty selected_samples lists.
- List only exact supplied samples from their own domains. Keep each key_fact
  to a few English words, not a sentence; put explanations in necessity.
- Return only this English JSON object:
{
  "feasible": true,
  "reason": "Why the selected samples form one joint task, or why none do.",
  "selected_samples": {
    "fusion_domain": [{"prompt": "Original question", "completion": "Original answer"}]
  },
  "question_plan": "Brief revised joint question idea.",
  "answer_plans": [
    {"type": "correct", "missing_domain": null, "plan": "..."},
    {"type": "missing_domain_knowledge", "missing_domain": "participating domain", "plan": "..."},
    {"type": "parallel_knowledge", "missing_domain": null, "plan": "..."},
    {"type": "incorrect_domain_relation", "missing_domain": null, "plan": "..."}
  ],
  "required_key_facts": {
    "fusion_domain": [
      {"key_fact": "short phrase", "necessity": "Why needed."},
      {"key_fact": "short phrase", "necessity": "Why needed."},
      {"key_fact": "short phrase", "necessity": "Why needed."}
    ]
  }
}

Example:
- input
{
  "source_domain": "mathematics",
  "sample": {"prompt": "Calculate the area of a circle of radius r.", "completion": "pi * r**2"},
  "key_facts": ["circle area", "pi times radius squared"],
  "fusion_domains": ["computer_science"],
  "question_plan": "Reverse a string before calculating a circle's area.",
  "answer_plans": [
    {"type": "correct", "missing_domain": null, "plan": "Reverse the string and calculate the area."},
    {"type": "missing_domain_knowledge", "missing_domain": "mathematics", "plan": "Omit pi."},
    {"type": "parallel_knowledge", "missing_domain": null, "plan": "Keep the two computations separate."},
    {"type": "incorrect_domain_relation", "missing_domain": null, "plan": "Apply the string operation to the radius."}
  ],
  "retrieved_samples": {
    "computer_science": [
      {"prompt": "What do return, math.pi, and ** do in Python?", "completion": "return sends back a value; math.pi is pi; ** exponentiates."}
    ]
  }
}

- output
{
  "feasible": true,
  "reason": "The Python sample can express and return the circle-area calculation.",
  "selected_samples": {
    "computer_science": [
      {"prompt": "What do return, math.pi, and ** do in Python?", "completion": "return sends back a value; math.pi is pi; ** exponentiates."}
    ]
  },
  "question_plan": "Write a Python function that returns the area of a circle from its radius.",
  "answer_plans": [
    {"type": "correct", "missing_domain": null, "plan": "Return pi times radius squared."},
    {"type": "missing_domain_knowledge", "missing_domain": "mathematics", "plan": "Return radius squared without pi."},
    {"type": "parallel_knowledge", "missing_domain": null, "plan": "Compute the area but return the radius."},
    {"type": "incorrect_domain_relation", "missing_domain": null, "plan": "Square pi with the radius."}
  ],
  "required_key_facts": {
    "computer_science": [
      {"key_fact": "Python return statement", "necessity": "Return the computed value."},
      {"key_fact": "math.pi constant", "necessity": "Represent pi in code."},
      {"key_fact": "Python exponentiation", "necessity": "Square the radius."}
    ]
  }
}

```

## SYSTEM_PROMPT

任务介绍与输入说明、`Tasks:`、`Requirements:`、JSON 输出结构和完整 `Example:` 保持分段。生成调用使用筛选后的计划、证据、派生 compact blueprint 和 `length_budget`；长度预算不会进入筛选调用。

```text
Construct one concise cross-domain multiple-choice question from the screened plan and selected evidence.

The input describes an already completed screening decision. It contains the original atomic sample and key facts, fusion_domains, the screened question_plan and answer_plans, required_key_facts, selected retrieved_samples, a compact_blueprint derived from the screened plan, the requested difficulty, and a length_budget. Do not redo screening or change the selected domains.

Tasks:
1. Write a self-contained question that keeps only the necessary situation,
   instance data, assumptions, boundary conditions, and one final question.
   Preserve the screened task's core and require the source knowledge plus every
   selected fusion domain to determine the result.
2. Produce four distinct options answering that same question in one consistent
   answer form. Make them concise final outcomes: a number, decision, short
   conclusion, expression, or local code result. Produce one correct outcome
   and one concrete wrong outcome for each retained error mechanism.
3. Put the complete solution in explanation. For each wrong option, write a
   private distractor_analysis reason connecting: erroneous step -> wrong result
   -> the corresponding option content. Cite actually used selected samples in
   used_samples and record any substantive presentation change in plan_adjustment.

Requirements:
- Screening is complete. Do not reject or replace a screened task because it is
  difficult to present. Do not add a planning call, domain, evidence source,
  independent subquestion, report, checklist, or full worked artifact.
- The visible question contains only necessary context, data, and boundaries plus
  one final question. Shared conditions or code appear once in the question.
  Intermediate reasoning, domain names as hints, construction labels, retrieval
  details, and explanations belong in private fields.
- Preserve all participating-domain dependencies and necessary conditions. Do
  not shorten by deleting a required concept, weakening a domain contribution,
  supplying the tested general rule/formula/bridge, or changing the screened
  target. Include units, precision, local API contracts and edge conditions when
  needed for a unique answer.
- All four options must use the same semantic answer form and be final outcomes,
  not explanations of why an answer is wrong. A short numeric option is valid;
  it must not carry a forced error explanation or error label.
- Keep these mechanisms in private metadata only:
  missing_domain_knowledge = omit or misuse necessary knowledge and produce a
  concrete wrong result;
  parallel_knowledge = a local result exists but is not used in the final
  judgment;
  incorrect_domain_relation = use a wrong mapping, direction, object, or
  combination and produce a concrete wrong result.
  In each reason state erroneous step -> wrong result -> option content. Do not
  make the visible option self-diagnose its mechanism. These labels are
  construction intent, not a unique diagnosis of model cognition.
- Use only exact selected prompt/completion samples in used_samples, at least
  one per fusion domain. Do not expose source evidence or metadata in the item.
- Respect length_budget word and character hard limits. The soft target is only
  guidance and options have no minimum length. Never truncate text or code,
  delete spaces, break indentation, omit conditions, or discard a domain.
- Difficulty changes application conditions, relations, or boundary cases within
  the same target; it must not mainly add background or independent outputs.
- Return only the JSON object below. Do not mention option letters in free prose;
  the program will decide the final option positions after validation.

Return only this English JSON object:
{
  "question": "Necessary context and one final question.",
  "options": {"A": "Final outcome", "B": "Final outcome", "C": "Final outcome", "D": "Final outcome"},
  "answer": "A",
  "explanation": "Complete private reasoning for the correct outcome.",
  "distractor_analysis": [
    {"option": "B", "type": "missing_domain_knowledge", "missing_domain": "participating domain", "reason": "Erroneous step -> wrong result -> option content."},
    {"option": "C", "type": "parallel_knowledge", "missing_domain": null, "reason": "Erroneous step -> wrong result -> option content."},
    {"option": "D", "type": "incorrect_domain_relation", "missing_domain": null, "reason": "Erroneous step -> wrong result -> option content."}
  ],
  "used_samples": {"fusion_domain": [{"prompt": "Exact selected prompt", "completion": "Exact selected completion"}]},
  "plan_adjustment": "Empty string unless the visible presentation changed substantively."
}

Example:
- input
{
  "source_domain": "mathematics",
  "sample": {"prompt": "Calculate the area of a circle of radius r.", "completion": "pi * r**2"},
  "key_facts": ["circle area", "pi times radius squared"],
  "fusion_domains": ["computer_science"],
  "question_plan": "Write a Python function that returns a circle's area from its radius.",
  "answer_plans": [
    {"type": "correct", "missing_domain": null, "plan": "Return pi times radius squared."},
    {"type": "missing_domain_knowledge", "missing_domain": "mathematics", "plan": "Return radius squared without pi."},
    {"type": "parallel_knowledge", "missing_domain": null, "plan": "Compute area but return radius."},
    {"type": "incorrect_domain_relation", "missing_domain": null, "plan": "Square pi together with radius."}
  ],
  "required_key_facts": {"computer_science": [
    {"key_fact": "Python return statement", "necessity": "Return the computed value."},
    {"key_fact": "math.pi constant", "necessity": "Represent pi in code."},
    {"key_fact": "Python exponentiation", "necessity": "Square the radius."}
  ]},
  "retrieved_samples": {"computer_science": [
    {"prompt": "What do return, math.pi and ** mean in Python?", "completion": "return sends a value back; math.pi is pi; ** exponentiates."}
  ]},
  "compact_blueprint": {"target": "The value returned by the area function", "answer_form": "code_or_expression", "dependency_summary": "Circle geometry determines the expression and Python semantics determine the returned value.", "domain_roles": {"mathematics": "area formula", "computer_science": "return and expression semantics"}},
  "length_budget": {"question_target_words": [30, 55], "question_max_words": 75, "option_max_words": 18, "total_visible_max_words": 130, "question_max_chars": 900, "option_max_chars": 216, "total_visible_max_chars": 1560},
  "option_count": 4,
  "difficulty": "easy"
}

- output
{
  "question": "With math imported and r > 0, which function body makes area(r) return the circle's area?",
  "options": {"A": "return math.pi * r**2", "B": "return r**2", "C": "math.pi * r**2\\nreturn r", "D": "return (math.pi * r)**2"},
  "answer": "A",
  "explanation": "The area is pi times radius squared, and the function must return that computed value.",
  "distractor_analysis": [
    {"option": "B", "type": "missing_domain_knowledge", "missing_domain": "mathematics", "reason": "Omitting pi yields radius squared, the concrete value shown by this option."},
    {"option": "C", "type": "parallel_knowledge", "missing_domain": null, "reason": "The area is evaluated but the returned value is radius, the concrete result shown by this option."},
    {"option": "D", "type": "incorrect_domain_relation", "missing_domain": null, "reason": "Applying the square to pi as well as radius yields pi squared times radius squared, shown by this option."}
  ],
  "used_samples": {"computer_science": [{"prompt": "What do return, math.pi and ** mean in Python?", "completion": "return sends a value back; math.pi is pi; ** exponentiates."}]},
  "plan_adjustment": ""
}

```

## AUDIT_PROMPT

盲审只收到 question/options、参与领域、源样本和 selected_samples；不收到 answer、解释、distractor_analysis、计划或 blueprint。审查可以返回零个或多个正确选项以及 `uncertain`，程序据结构化结果判定，不强行改答案。

```text
Audit the visible multiple-choice item produced after screening and generation. The proposed answer key, explanation, distractor labels, plans, blueprint, and construction metadata are deliberately withheld.

The input contains only the visible question/options, participating domains, the source sample, and the selected evidence references. Evidence is private provenance: use it to check domain facts, but do not supply instance-specific conditions that the visible question omitted.

Tasks:
1. Independently solve the visible item and list all correct option labels. Allow
   zero or multiple labels when the item is invalid, ambiguous, or underdetermined.
2. Check whether the item has one final target, is self-contained, is grounded in
   the supplied evidence, avoids giving away the tested knowledge or full bridge,
   uses one answer form across all options, and has no obvious surface shortcut.
3. For every participating domain, including the source domain, identify its
   necessary contribution and what becomes wrong or underdetermined without its
   knowledge. Mentioning a setting or vocabulary is not enough.
4. Report concrete unresolved issues. Do not infer a unique error mechanism from
   a short wrong answer; mechanism review requires private construction metadata.

Requirements:
- This is an answer-label-blind quality audit with reference evidence, not a
  closed-book capability test and not independent expert validation.
- Removing a domain name from the wording is different from removing its
  knowledge. Check actual dependence on each domain.
- Use pass, fail, or uncertain for every check. Use true, false, or null for
  necessary. Uncertain never passes the programmatic gate.
- `correct_options` may be empty or contain multiple distinct labels. Do not
  force a single answer. `issues` must be empty only if no concrete issue remains.
- Return only the following English JSON object.

{
  "correct_options": ["C"],
  "solution_summary": "Brief independent verification.",
  "checks": {
    "single_target": "pass",
    "self_contained": "pass",
    "evidence_grounded": "pass",
    "no_knowledge_giveaway": "pass",
    "same_answer_form": "pass",
    "no_surface_shortcut": "pass"
  },
  "domain_necessity": {"actual_domain": {"necessary": true, "reason": "Necessary inference and removal consequence."}},
  "issues": []
}

Example:
- input
{
  "question": "With math imported and r > 0, which function body makes area(r) return the circle's area?",
  "options": {"A": "return (math.pi * r)**2", "B": "math.pi * r**2\\nreturn r", "C": "return math.pi * r**2", "D": "return r**2"},
  "participating_domains": ["mathematics", "computer_science"],
  "source_sample": {"prompt": "Calculate the area of a circle of radius r.", "completion": "pi * r**2"},
  "selected_samples": {"computer_science": [{"prompt": "What do return, math.pi and ** mean in Python?", "completion": "return sends a value back; math.pi is pi; ** exponentiates."}]}
}

- output
{
  "correct_options": ["C"],
  "solution_summary": "Only the third body returns pi times the radius squared.",
  "checks": {"single_target": "pass", "self_contained": "pass", "evidence_grounded": "pass", "no_knowledge_giveaway": "pass", "same_answer_form": "pass", "no_surface_shortcut": "pass"},
  "domain_necessity": {"mathematics": {"necessary": true, "reason": "The area relation determines pi times radius squared."}, "computer_science": {"necessary": true, "reason": "Return and exponentiation semantics determine the function result."}},
  "issues": []
}

```

## REPAIR_PROMPT

重写调用只修复具体反馈，返回未排列的完整生成对象；重写后重新执行结构、引用、长度、排列和盲审。最多一次，不因生成失败重新筛选或重新检索。

```text
Repair one rejected generated candidate after screening. Return a complete new candidate in the generation JSON schema.

Tasks:
1. Read the original candidate, concrete rejection issues, the screened plan,
   compact_blueprint, selected evidence, and length_budget.
2. Fix every reported structure, visible-length, code-format, self-containedness,
   target, domain-necessity, or semantic issue while preserving the same screened
   target, source knowledge, all domains, evidence and necessary conditions.
3. Return one fresh unshuffled candidate. Do not audit, change the answer merely
   to match a judge label, or request another rewrite.

Requirements:
- Keep visible content to necessary context, data, boundaries, and one final
  question. Keep explanations and error mechanisms in private fields.
- A short numeric/result option is valid and must not contain a forced mechanism
  explanation. Write mechanism details only in distractor_analysis.reason as
  erroneous step -> wrong result -> option content.
- Do not truncate code, remove spaces, omit conditions, drop a domain, replace
  the screened target, invent evidence, or turn the item into a report.
- Use exact selected prompt/completion samples in used_samples. Recheck all four
  options, three mechanisms, answer coverage, length_budget, and code formatting.
- Return only the complete generation JSON object shown in the original
  generation prompt. The program will validate and permute it again.

```

## 后台标签边界 / Metadata boundary

`missing_domain_knowledge`、`parallel_knowledge`、`incorrect_domain_relation` 各保留一次。后台 reason 必须说明“错误步骤 → 错误结果 → 对应选项”；选项本身只给结果。一次盲审不能证明错误机制或所有模型均无捷径。默认长度预算是本项目工程配置，不是外部 benchmark 官方参数。
